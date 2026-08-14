"""Task 4 — R1 `loop`: l'agente e' bloccato.

Un loop e' MANCANZA DI PROGRESSO. Con azioni specifiche si vede nella ripetizione, con
categorie grezze si vedrebbe nella sequenza — ma solo se i dettagli ci sono. Due
rilevatori, un solo alert.

Tutti i test costruiscono liste a mano con `now` come parametro e una configurazione
DIVERSA dai default: e' l'unico modo di verificare che le soglie siano davvero iniettate.
"""
from datetime import datetime, timedelta, timezone

import pytest

from starkeno.config import snapshot
from starkeno.rules import NON_VALUTABILE, OK, VIOLAZIONE, ActionRecord, valuta_r1

ORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
BARRA = chr(92)


def azioni(etichette, *, fine=ORA, passo_secondi=10, primo_id=1):
    """Costruisce una sequenza che TERMINA a `fine`, un'azione ogni `passo_secondi`.

    Termina a `fine` e non parte da li' perche' entrambi i rilevatori guardano il
    passato recente rispetto a `now`: una sequenza costruita in avanti finirebbe nel
    futuro e non verrebbe vista.
    """
    n = len(etichette)
    return [
        ActionRecord(
            id=primo_id + i,
            project="a",
            action=etichetta,
            model_used="claude-opus-4-5",
            tokens_used=1000,
            cache_read_tokens=None,
            cache_write_tokens=None,
            output_tokens=None,
            timestamp=fine - timedelta(seconds=passo_secondi * (n - 1 - i)),
        )
        for i, etichetta in enumerate(etichette)
    ]


# Valori DIVERSI dai default di config.py, cosi' che una regola che li ignorasse fallisca.
# `snapshot` rivalida gli invarianti: PROMOTE_MIN_MINUTES deve restare sopra
# LOOP_CYCLE_WINDOW_MINUTES (I1), e LOOP_SEQUENCE_LEN sopra MAX_LEN x K_MIXED (I2).
CONF = snapshot(
    LOOP_WINDOW_MINUTES=4,
    LOOP_MIN_REPEATS=8,
    LOOP_SEQUENCE_LEN=40,
    LOOP_CYCLE_WINDOW_MINUTES=9,
    LOOP_CYCLE_MAX_LEN=5,
    LOOP_CYCLE_K_MIXED_DETAIL=5,
    LOOP_CYCLE_K_SAME_DETAIL=4,
    LOOP_MIN_HISTORY=18,
    PROMOTE_MIN_MINUTES=14,
)


# ======================================================================= storia
def test_too_little_history_abstains_and_never_says_ok():
    """Storia insufficiente deve dire "sto ancora calibrando", non "tutto a posto".

    Senza il terzo stato, una regola tace per ignoranza e sembra dare via libera.
    """
    esito = valuta_r1(azioni(["read:a.py", "edit:a.py", "test:t/"] * 5), now=ORA, config=CONF)

    assert esito.stato == NON_VALUTABILE
    assert "storia" in esito.motivo.lower()


def test_history_is_counted_on_the_records_it_receives():
    """C9: `LOOP_MIN_HISTORY` si misura sulle azioni della finestra attiva.

    La scelta cambia quando `LOOP_CYCLE_K_SAME_DETAIL` diventa raggiungibile: con la
    storia contata su TUTTO lo scibile, un agente vecchio scatterebbe a K=4, con la
    storia contata sulla finestra ne servono molte di piu'. Lo spec non lo dice, e due
    implementatori sceglierebbero diversamente.
    """
    poche = valuta_r1(azioni(["x:%d" % i for i in range(CONF.LOOP_MIN_HISTORY - 1)]),
                      now=ORA, config=CONF)
    assert poche.stato == NON_VALUTABILE

    abbastanza = valuta_r1(azioni(["x:%d" % i for i in range(CONF.LOOP_MIN_HISTORY)]),
                           now=ORA, config=CONF)
    assert abbastanza.stato != NON_VALUTABILE


# =========================================================== rilevatore A
def riscaldamento_poi(coda):
    """Storia varia (per superare LOOP_MIN_HISTORY) seguita dal comportamento in esame.

    L'ordine conta: `azioni()` costruisce una sequenza che TERMINA a `now`, quindi i
    primi elementi sono i piu' vecchi. Mettere le ripetizioni all'inizio le farebbe
    cadere fuori dalla finestra corta del rilevatore A — che e' anche cio' che succede
    davvero quando un agente si blocca alla fine di una sessione sana.
    """
    return ["passo_%d:file_%d" % (i, i) for i in range(CONF.LOOP_MIN_HISTORY)] + coda


def test_identical_action_repeated_enough_times_is_a_violation():
    sequenza = riscaldamento_poi(["read_file:app.py"] * CONF.LOOP_MIN_REPEATS)
    esito = valuta_r1(azioni(sequenza, passo_secondi=2), now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE
    assert "read_file" in esito.motivo


def test_one_repetition_below_the_threshold_is_not_a_violation():
    """Il confine esatto: a soglia-1 non deve scattare."""
    sequenza = riscaldamento_poi(["read_file:app.py"] * (CONF.LOOP_MIN_REPEATS - 1))
    esito = valuta_r1(azioni(sequenza, passo_secondi=2), now=ORA, config=CONF)

    assert esito.stato != VIOLAZIONE


def test_repetitions_outside_the_short_window_do_not_count():
    """La finestra del rilevatore A e' relativa a `now`, non alla sequenza."""
    vecchie = azioni(["read_file:app.py"] * CONF.LOOP_MIN_REPEATS,
                     fine=ORA - timedelta(minutes=CONF.LOOP_WINDOW_MINUTES + 5))
    recenti = azioni(["passo:%d" % i for i in range(CONF.LOOP_MIN_HISTORY)],
                     fine=ORA, primo_id=500)
    esito = valuta_r1(vecchie + recenti, now=ORA, config=CONF)

    assert esito.stato != VIOLAZIONE


# =========================================================== rilevatore B
def test_the_classic_loop_fires_on_identical_details():
    """`read → edit → test` sugli stessi file: il loop piu' comune che esista.

    **Il numero di ripetizioni e' esattamente `K_SAME_DETAIL`, e non uno di piu'.**
    Il test isola cosi' la decisione che conta di piu' in R1: la classificazione dei
    dettagli PER POSIZIONE.

    Per posizione: 0 e 1 vedono sempre `app.py`, 2 vede sempre `tests/` -> tutte
    "identica" -> soglia K_SAME (4). Guardando invece l'INSIEME dei dettagli della
    finestra si otterrebbe {app.py, tests/} -> "misto" -> soglia K_MIXED (5), e con
    esattamente 4 ripetizioni la regola tacerebbe.

    Con piu' ripetizioni il test passerebbe in entrambe le letture e non direbbe niente:
    la prima versione ne usava 7 ed era vacua — verificato mutando il codice.
    """
    ripetizioni = CONF.LOOP_CYCLE_K_SAME_DETAIL
    assert ripetizioni < CONF.LOOP_CYCLE_K_MIXED_DETAIL, "il test non separa le due letture"

    riscaldamento = ["avvio_%d:f%d" % (i, i) for i in range(CONF.LOOP_MIN_HISTORY)]
    ciclo = ["read:app.py", "edit:app.py", "test:tests/"] * ripetizioni
    esito = valuta_r1(azioni(riscaldamento + ciclo, passo_secondi=2), now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE
    assert esito.evidenza["rilevatore"] == "ciclo"
    assert esito.evidenza["lunghezza_ciclo"] == 3
    assert esito.evidenza["dettagli_per_posizione"] == ["identica", "identica", "identica"]


def test_a_cycle_with_one_advancing_position_needs_more_evidence():
    """Misto: il segnale c'e' ma e' ambiguo, quindi serve piu' evidenza (K_MIXED).

    Con K fra la soglia SAME e la soglia MIXED non deve scattare.
    """
    k = CONF.LOOP_CYCLE_K_SAME_DETAIL  # abbastanza per SAME, non per MIXED
    assert k < CONF.LOOP_CYCLE_K_MIXED_DETAIL, "il test non separa i due casi"

    misto = [x for i in range(k) for x in ("read:app.py", "edit:app.py", "test:t%d" % i)]
    misto += ["riscaldamento:%d" % i for i in range(CONF.LOOP_MIN_HISTORY)]
    esito = valuta_r1(azioni(misto[-CONF.LOOP_SEQUENCE_LEN:]), now=ORA, config=CONF)

    assert esito.stato != VIOLAZIONE


def test_a_healthy_batch_is_not_a_loop():
    """`fetch/validate/save:user_1..100`: il ciclo si ripete cento volte ed e' SANO.

    Il batch non rivisita mai lo stesso oggetto, il loop rivisita sempre lo stesso. Tutte
    le posizioni hanno dettagli distinti, quindi sta avanzando.
    """
    sequenza = [v + ":user_%d" % i for i in range(1, 101) for v in ("fetch", "validate", "save")]
    esito = valuta_r1(azioni(sequenza, passo_secondi=1), now=ORA, config=CONF)

    assert esito.stato == OK


def test_a_run_of_a_single_category_does_not_become_a_cycle_below_the_repeat_threshold():
    """**N5.** Una corsa di categorie identiche crea un ciclo finto a OGNI lunghezza.

    Misurato sullo pseudocodice letterale: 200 azioni `read_file` danno L=2 K=100 e
    L=3 K=66. Sono cicli da 1 travestiti — affare del rilevatore A — ma niente li
    escludeva dal rilevatore B, che cosi' scavalcava la soglia di A.

    Il caso e' costruito per ISOLARE quella guardia: `read_file:a` e `read_file:b`
    alternati, 7 volte ciascuno.
      - rilevatore A: ogni coppia (categoria, dettaglio) compare 7 volte, sotto la
        soglia di 8 -> non scatta, correttamente;
      - rilevatore B senza guardia: L=2, blocco [read_file, read_file], K=7, dettagli
        identici per posizione -> soglia K_SAME=4 -> VIOLAZIONE a meta' della soglia di A;
      - rilevatore B con guardia: il blocco ha una sola categoria, si salta -> OK.

    La prima versione di questo test usava 200 categorie nude ed era vacua: con i
    dettagli assenti scattava il ramo dell'astensione, che mascherava del tutto la
    guardia mancante. Verificato mutando il codice.
    """
    quante = CONF.LOOP_MIN_REPEATS - 1
    riscaldamento = ["avvio_%d:f%d" % (i, i) for i in range(CONF.LOOP_MIN_HISTORY)]
    alternate = ["read_file:a", "read_file:b"] * quante
    esito = valuta_r1(azioni(riscaldamento + alternate, passo_secondi=2), now=ORA, config=CONF)

    assert esito.stato == OK, (
        "una corsa a categoria unica e' stata letta come ciclo: %s" % esito.motivo
    )


def test_two_hundred_bare_reads_abstain_rather_than_firing():
    """Lo stesso caso senza dettagli: qui vince l'astensione, non la guardia."""
    esito = valuta_r1(azioni(["read_file"] * 200, passo_secondi=1), now=ORA, config=CONF)

    assert esito.stato == NON_VALUTABILE


def test_the_cycle_must_be_recent():
    """Un ciclo finito ore fa non e' un agente bloccato ADESSO.

    Le azioni caricate coprono SUPERVISOR_ACTIVE_AGENT_HOURS (48h): senza questo
    controllo, un blocco di ieri verrebbe segnalato oggi.
    """
    vecchio = azioni(["read:app.py", "edit:app.py", "test:t/"] * 10,
                     fine=ORA - timedelta(minutes=CONF.LOOP_CYCLE_WINDOW_MINUTES + 30))
    esito = valuta_r1(vecchio, now=ORA, config=CONF)

    assert esito.stato != VIOLAZIONE


def test_a_long_cycle_is_still_detectable():
    """Protegge l'invariante I2: LOOP_SEQUENCE_LEN deve contenere MAX_LEN x K_MIXED."""
    lunghezza = CONF.LOOP_CYCLE_MAX_LEN
    ciclo = ["p%d:file%d.py" % (i, i) for i in range(lunghezza)]
    esito = valuta_r1(azioni(ciclo * CONF.LOOP_CYCLE_K_MIXED_DETAIL, passo_secondi=2),
                      now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE
    assert esito.evidenza["lunghezza_ciclo"] == lunghezza


# ================================================= astensione senza dettaglio (C8)
def test_a_fast_indexer_without_details_is_not_accused_of_looping():
    """**N4.** `LOOP_MIN_REPEATS_NO_DETAIL=40` non proteggeva nessuno.

    Misurato: un indicizzatore sano a 3 azioni/secondo supera 40 in 13 secondi, a 1
    az/s in 40 secondi. Nessun valore fisso separa "veloce e sano" da "bloccato" quando
    il dettaglio manca, perche' «100 oggetti diversi» e «lo stesso oggetto 100 volte»
    sono LA STESSA STRINGA. L'informazione non c'e' e nessuna soglia la crea.

    Astenersi e' quello che il terzo stato prescrive per i dati inutilizzabili, ed e'
    cio' che rende reale l'incentivo del contratto col chiamante: dai il dettaglio,
    ottieni il rilevamento.
    """
    esito = valuta_r1(azioni(["read_file"] * 200, passo_secondi=1), now=ORA, config=CONF)

    assert esito.stato == NON_VALUTABILE
    assert "dettaglio" in esito.motivo.lower()


def test_a_healthy_three_phase_agent_without_details_is_not_accused_either():
    """**N6.** `plan:` / `act:` / `observe:` ripetuti.

    §4 promette che la guardia sul parsing protegga questo caso. Misurato: non lo
    protegge, lo sposta soltanto dal ramo K=3 al ramo K=6 — a 18 azioni in 10 minuti un
    agente sano a tre fasi veniva comunque accusato.
    """
    esito = valuta_r1(azioni(["plan:", "act:", "observe:"] * 10, passo_secondi=5),
                      now=ORA, config=CONF)

    assert esito.stato == NON_VALUTABILE
    assert "dettaglio" in esito.motivo.lower()


def test_windows_paths_abstain_rather_than_firing_or_clearing():
    """Un agente che logga percorsi Windows nudi non e' valutabile da R1.

    Non e' OK — R1 non ha visto nulla che dimostri che sta avanzando — e non e'
    VIOLAZIONE. E' visibile in `rule_status` col motivo, ed e' il chiamante a poterlo
    risolvere passando `categoria:dettaglio`.
    """
    percorsi = ["C:" + BARRA + "Users" + BARRA + "esempio" + BARRA + "f%d.py" % i for i in range(30)]
    esito = valuta_r1(azioni(percorsi), now=ORA, config=CONF)

    assert esito.stato == NON_VALUTABILE


def test_a_healthy_varied_sequence_with_details_is_ok():
    """Il complemento: con i dettagli e senza cicli, R1 dice OK e non si astiene."""
    sano = ["read:a", "edit:a", "test:t", "commit:a", "read:b", "search:q", "edit:b",
            "test:t", "commit:b"] * 4
    esito = valuta_r1(azioni(sano), now=ORA, config=CONF)

    assert esito.stato == OK
    assert esito.motivo is None


# ============================================================ combinazione (C12)
def test_a_violation_wins_over_an_abstention():
    """Precedenza VIOLAZIONE > NON_VALUTABILE > OK.

    Un agente che logga meta' azioni con dettaglio e meta' senza, e che ripete
    identicamente quelle col dettaglio, e' bloccato: l'astensione dell'altro rilevatore
    non deve nasconderlo.
    """
    sequenza = ["read_file:app.py"] * CONF.LOOP_MIN_REPEATS + ["nudo"] * CONF.LOOP_MIN_HISTORY
    esito = valuta_r1(azioni(sequenza, passo_secondi=1), now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE


def test_an_abstention_wins_over_ok():
    """Non si dice OK quando meta' delle prove era inutilizzabile.

    E' il fallimento peggiore di questo sistema — il silenzio indistinguibile dalla
    salute — nella sua forma piu' piccola.
    """
    esito = valuta_r1(azioni(["nudo_%d" % i for i in range(30)]), now=ORA, config=CONF)

    assert esito.stato == NON_VALUTABILE


# ================================================================== last_seen
def test_last_seen_is_the_timestamp_of_the_most_recent_contributing_action():
    """`last_seen` e' tempo AZIONE, non tempo del giro del supervisore.

    E' la definizione che fa funzionare tutta la chiusura degli alert: quando il
    comportamento cattivo cessa, `last_seen` smette di avanzare e la finestra pulita
    dopo di esso puo' crescere. Col tempo del ciclo, un agente fermo sembrerebbe guarito.
    """
    fine_loop = ORA - timedelta(minutes=2)
    registri = azioni(["read:app.py", "edit:app.py", "test:t/"] * 8, fine=fine_loop)
    esito = valuta_r1(registri, now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE
    assert esito.ultimo_contributo == fine_loop
    assert esito.ultimo_contributo != ORA


# ============================================================ config iniettata
def test_the_thresholds_actually_come_from_the_injected_config():
    """Con soglie diverse, gli stessi dati devono dare esiti diversi.

    Senza questo test, una `rules.py` con le costanti scritte a mano passerebbe tutto il
    resto del file.
    """
    dati = azioni(["altro_%d:f%d" % (i, i) for i in range(25)] + ["read_file:app.py"] * 9,
                  passo_secondi=1)

    severa = snapshot(LOOP_MIN_REPEATS=9, LOOP_MIN_HISTORY=18)
    # 20 e non 50: `snapshot` rivalida gli invarianti, e I4 impone
    # LOOP_MIN_REPEATS <= RESOLVE_MIN_HEALTHY_ACTIONS. Il controllo ha rifiutato la
    # prima versione di questo test, che e' esattamente cio' per cui esiste.
    permissiva = snapshot(LOOP_MIN_REPEATS=20, LOOP_MIN_HISTORY=18)

    assert valuta_r1(dati, now=ORA, config=severa).stato == VIOLAZIONE
    assert valuta_r1(dati, now=ORA, config=permissiva).stato != VIOLAZIONE


def test_evidence_is_json_serializable():
    """`evidence` finisce in una colonna String come JSON: deve poterci andare."""
    import json

    esito = valuta_r1(azioni(["read:app.py", "edit:app.py", "test:t/"] * 8),
                      now=ORA, config=CONF)
    assert json.loads(json.dumps(esito.evidenza)) == esito.evidenza
