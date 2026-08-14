"""Task 6 — R3 `spend_anomaly`: spesa fuori scala rispetto alla PROPRIA storia.

Tre proprieta' di questa regola non sono ovvie e vanno tenute a mente leggendo i test.

**E' valutata su tutte le azioni non ancora esaminate**, non sull'ultima. Un agente
veloce (40 azioni al minuto) nasconderebbe la chiamata da 600k token dietro le
successive: al giro dopo "l'ultima azione" e' un'altra, e l'anomalia piu' cara della
giornata non verrebbe valutata da nessuno — un buco che PEGGIORA al crescere del
throughput.

**Le anomalie vanno ricordate fra un giro e l'altro.** Servono due anomalie in 24 ore,
ma il watermark fa si' che ogni giro veda solo le azioni nuove: la prima anomalia
sparirebbe prima che arrivi la seconda. La memoria e' l'`evidence` dell'alert candidate,
e la regola riceve le anomalie gia' note per fonderle e potare quelle scadute.

**E' strutturalmente cieca a un agente che spreca dal primo giorno**, perche' e' relativa
alla storia dell'agente stesso. E' il buco che R4 copre.
"""
from datetime import datetime, timedelta, timezone

from starkeno.config import snapshot
from starkeno.rules import (
    NON_VALUTABILE,
    OK,
    VIOLAZIONE,
    CandidatoSpesa,
    valuta_r3,
)

ORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)

# Valori DIVERSI dai default, cosi' che una regola che li ignorasse fallisca.
CONF = snapshot(
    SPEND_ABS_FLOOR_TOKENS=40_000,
    SPEND_MEDIAN_MULT=8,
    SPEND_P95_MULT=2,
    SPEND_MIN_HISTORY=25,
    SPEND_HISTORY_WINDOW=150,
    SPEND_PROMOTE_MIN_ANOMALIES=2,
    SPEND_ANOMALY_WINDOW_HOURS=12,
)

# Baseline tranquilla. I valori sono scelti perche' le TRE soglie risultino DISTINTE:
#   floor        = 40.000
#   8 x mediana  = 64.000   <- il vincolo attivo
#   2 x p95      = 24.000
# Con la prima versione (mediana 5.000) il floor e il multiplo della mediana valevano
# entrambi 40.000, e nessun valore poteva stare fra i due: il test che verifica la
# congiunzione delle tre condizioni non aveva modo di isolarle. Verificato eseguendo.
BASELINE = tuple([8_000] * 40 + [12_000] * 8 + [15_000, 18_000])


def candidato(effective, *, quando=ORA, action_id=9999, baseline=BASELINE):
    return CandidatoSpesa(
        action_id=action_id, timestamp=quando, effective=effective, baseline=baseline
    )


def soglia_richiesta(config=CONF, baseline=BASELINE):
    """La soglia effettiva: le tre condizioni sono congiuntive, vince la piu' alta."""
    import statistics

    from starkeno.rules import percentile_nearest_rank

    return max(
        config.SPEND_ABS_FLOOR_TOKENS,
        config.SPEND_MEDIAN_MULT * statistics.median(baseline),
        config.SPEND_P95_MULT * percentile_nearest_rank(baseline, 0.95),
    )


# ============================================================ le tre condizioni
def test_the_three_conditions_are_conjunctive():
    """Ciascuna da sola non basta: tre test, ciascuno con una sola condizione mancante."""
    import statistics

    from starkeno.rules import percentile_nearest_rank

    mediana = statistics.median(BASELINE)
    p95 = percentile_nearest_rank(BASELINE, 0.95)

    # sopra il floor e sopra il p95, ma sotto 8x la mediana
    assert CONF.SPEND_MEDIAN_MULT * mediana > CONF.SPEND_ABS_FLOOR_TOKENS
    sotto_mediana = CONF.SPEND_MEDIAN_MULT * mediana - 1
    assert sotto_mediana >= CONF.SPEND_ABS_FLOOR_TOKENS
    assert sotto_mediana >= CONF.SPEND_P95_MULT * p95
    assert valuta_r3([candidato(sotto_mediana)], anomalie_note=(), now=ORA, config=CONF).stato == OK

    # sopra tutto tranne il floor
    basso = CONF.SPEND_ABS_FLOOR_TOKENS - 1
    magra = tuple([10] * 60)   # mediana 10, p95 10: i due multipli sono irrisori
    assert valuta_r3([candidato(basso, baseline=magra)], anomalie_note=(),
                     now=ORA, config=CONF).stato == OK


def test_an_action_above_all_three_thresholds_is_an_anomaly():
    esito = valuta_r3([candidato(soglia_richiesta())], anomalie_note=(), now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE
    assert len(esito.evidenza["anomalie"]) == 1


def test_the_highest_of_the_three_thresholds_wins():
    """Con una baseline alta vince `SPEND_MEDIAN_MULT x mediana`, non il floor assoluto.

    Misurato sui default di produzione: per un agente leggero vince il floor, per uno
    medio o pesante vincono i 10x la mediana. Un agente pesante ha bisogno di una
    chiamata quasi un ordine di grandezza sopra la propria normalita' — R3 parlera'
    raramente, ed e' voluto.
    """
    pesante = tuple([80_000] * 50)
    richiesta = soglia_richiesta(baseline=pesante)
    assert richiesta > CONF.SPEND_ABS_FLOOR_TOKENS

    sotto = valuta_r3([candidato(richiesta - 1, baseline=pesante)], anomalie_note=(),
                      now=ORA, config=CONF)
    sopra = valuta_r3([candidato(richiesta, baseline=pesante)], anomalie_note=(),
                      now=ORA, config=CONF)

    assert sotto.stato == OK
    assert sopra.stato == VIOLAZIONE


def test_the_baseline_uses_the_median_not_the_mean():
    """**Mediana e percentile, non media**, e il test lo dimostra sull'ESITO.

    La media viene trascinata proprio dai valori anomali che stiamo cercando, quindi ogni
    anomalia gia' avvenuta renderebbe la regola piu' sorda alla successiva.

    La baseline qui contiene due picchi da 500k — due anomalie passate, esattamente lo
    scenario che conta:
        mediana = 8.000   -> soglia 8x = 64.000    -> un candidato da 70.000 e' anomalo
        media   = 28.320  -> soglia 8x = 226.560   -> lo stesso candidato passa inosservato

    Una prima versione di questo test confrontava media e mediana senza mai chiamare la
    regola, e usava per il resto una baseline a valori tutti uguali — dove media e
    mediana coincidono. Sostituire l'una con l'altra non cambiava nessun esito.
    Verificato mutando il codice.
    """
    import statistics

    con_picchi = tuple([8_000] * 40 + [12_000] * 8 + [500_000] * 2)
    assert statistics.median(con_picchi) == 8_000
    assert statistics.mean(con_picchi) > 25_000, "la media e' trascinata dai picchi"

    esito = valuta_r3([candidato(70_000, baseline=con_picchi)], anomalie_note=(),
                      now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE, (
        "la soglia e' stata calcolata sulla media: due anomalie passate hanno reso la "
        "regola sorda alla terza"
    )


# ======================================================== baseline insufficiente
def test_a_short_baseline_abstains_and_never_says_ok():
    corta = tuple([5_000] * (CONF.SPEND_MIN_HISTORY - 1))
    esito = valuta_r3([candidato(10_000_000, baseline=corta)], anomalie_note=(),
                      now=ORA, config=CONF)

    assert esito.stato == NON_VALUTABILE
    assert "baseline" in esito.motivo.lower()
    assert str(CONF.SPEND_MIN_HISTORY - 1) in esito.motivo


def test_a_baseline_exactly_at_the_minimum_is_evaluable():
    esatta = tuple([5_000] * CONF.SPEND_MIN_HISTORY)
    esito = valuta_r3([candidato(10_000_000, baseline=esatta)], anomalie_note=(),
                      now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE


def test_candidates_with_a_usable_baseline_are_evaluated_even_if_others_are_not():
    """Non si butta via un candidato valutabile perche' un altro non lo era."""
    corta = tuple([5_000] * 3)
    esito = valuta_r3(
        [candidato(10 ** 7, action_id=1, baseline=corta),
         candidato(10 ** 7, action_id=2, baseline=BASELINE)],
        anomalie_note=(), now=ORA, config=CONF,
    )

    assert esito.stato == VIOLAZIONE
    assert [a["action_id"] for a in esito.evidenza["anomalie"]] == [2]


# ============================================================== token inutilizzabili
def test_a_candidate_with_non_positive_effective_tokens_does_not_count_as_evidence():
    """Il filtro di scarto e' su `effective_tokens`, non su `tokens_used`.

    E' la grandezza che viene poi confrontata: scartare sui token grezzi lascerebbe
    passare righe il cui valore pesato e' zero o negativo.

    L'effetto osservabile non e' che una riga a zero venga giudicata anomala — non
    potrebbe, nessun valore non positivo supera una soglia positiva — ma che NON conti
    come prova di aver potuto valutare qualcosa. Qui il candidato a zero ha una baseline
    lunga e quello valido ce l'ha corta: senza lo scarto, la baseline lunga del candidato
    inutilizzabile farebbe credere alla regola di aver valutato, e l'esito passerebbe da
    "sto ancora calibrando" a "tutto a posto".

    La prima versione di questo test usava due candidati a zero con baseline piena e
    verificava solo che l'esito fosse OK: rimuovendo lo scarto restava OK lo stesso.
    """
    corta = tuple([8_000] * 3)
    esito = valuta_r3(
        [candidato(0, action_id=1, baseline=BASELINE),
         candidato(70_000, action_id=2, baseline=corta)],
        anomalie_note=(), now=ORA, config=CONF,
    )

    assert esito.stato == NON_VALUTABILE, (
        "la baseline di un candidato inutilizzabile e' stata contata come prova"
    )
    assert "baseline" in esito.motivo.lower()


def test_no_new_candidates_is_ok_not_an_abstention():
    """Nessuna azione nuova e' il caso NORMALE di un agente tranquillo, non un dato mancante."""
    esito = valuta_r3([], anomalie_note=(), now=ORA, config=CONF)

    assert esito.stato == OK


# ================================================ memoria delle anomalie fra i giri
def test_previously_known_anomalies_are_carried_forward():
    """**La decisione che lo spec lascia aperta.**

    Servono due anomalie in `SPEND_ANOMALY_WINDOW_HOURS`, ma il watermark fa si' che
    ogni giro veda solo le azioni NUOVE: senza memoria, la prima anomalia sparirebbe
    prima che arrivi la seconda e il conteggio non salirebbe mai oltre uno.

    La memoria e' l'`evidence` dell'alert, e la regola la riceve e la restituisce fusa.
    """
    nota = {"action_id": 1, "timestamp": (ORA - timedelta(hours=2)).isoformat(),
            "effective": 500_000}
    esito = valuta_r3([candidato(soglia_richiesta(), action_id=2)],
                      anomalie_note=(nota,), now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE
    assert [a["action_id"] for a in esito.evidenza["anomalie"]] == [1, 2]
    assert esito.evidenza["anomalie_nella_finestra"] == 2


def test_anomalies_older_than_the_window_are_pruned():
    """Altrimenti il conteggio cresce per sempre e la promozione diventa irreversibile."""
    scaduta = {
        "action_id": 1,
        "timestamp": (ORA - timedelta(hours=CONF.SPEND_ANOMALY_WINDOW_HOURS + 1)).isoformat(),
        "effective": 500_000,
    }
    esito = valuta_r3([candidato(soglia_richiesta(), action_id=2)],
                      anomalie_note=(scaduta,), now=ORA, config=CONF)

    assert [a["action_id"] for a in esito.evidenza["anomalie"]] == [2]
    assert esito.evidenza["anomalie_nella_finestra"] == 1


def test_known_anomalies_alone_keep_the_violation_alive():
    """Un giro senza azioni nuove non deve far sparire una violazione ancora valida."""
    note = tuple(
        {"action_id": i, "timestamp": (ORA - timedelta(hours=1)).isoformat(),
         "effective": 500_000}
        for i in (1, 2)
    )
    esito = valuta_r3([], anomalie_note=note, now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE
    assert esito.evidenza["anomalie_nella_finestra"] == 2


def test_the_same_anomaly_is_never_counted_twice():
    """Il watermark potrebbe essere riscritto solo a fine giro riuscito: un giro fallito
    fa rivedere le stesse azioni, e senza deduplica il conteggio salirebbe da solo."""
    nota = {"action_id": 7, "timestamp": ORA.isoformat(), "effective": 900_000}
    esito = valuta_r3([candidato(soglia_richiesta(), action_id=7)],
                      anomalie_note=(nota,), now=ORA, config=CONF)

    assert esito.evidenza["anomalie_nella_finestra"] == 1


# ============================================================== promozione e conteggio
def test_the_anomaly_count_is_exposed_for_the_promotion_rule():
    """Una sola anomalia e' gia' una violazione, ma non basta a promuovere.

    Un'anomalia isolata e' una violazione storica su una riga IMMUTABILE: non puo'
    auto-risolversi, quindi la difesa anti-raffica del ciclo di vita non la coprirebbe, e
    una singola analisi one-shot alle 18:00 diventerebbe un alert permanente. Il
    conteggio esce nell'evidence perche' e' la riconciliazione a decidere la promozione.
    """
    esito = valuta_r3([candidato(soglia_richiesta())], anomalie_note=(), now=ORA, config=CONF)

    assert esito.stato == VIOLAZIONE
    assert esito.evidenza["anomalie_nella_finestra"] == 1
    assert esito.evidenza["soglia_promozione"] == CONF.SPEND_PROMOTE_MIN_ANOMALIES
    assert esito.evidenza["anomalie_nella_finestra"] < CONF.SPEND_PROMOTE_MIN_ANOMALIES


# ================================================================== last_seen
def test_last_seen_is_the_most_recent_anomaly_not_the_round_time():
    quando = ORA - timedelta(minutes=17)
    esito = valuta_r3([candidato(soglia_richiesta(), quando=quando)],
                      anomalie_note=(), now=ORA, config=CONF)

    assert esito.ultimo_contributo == quando


# ============================================================= config iniettata
def test_the_thresholds_come_from_the_injected_config():
    # 70.000 sta sopra la soglia severa (8 x mediana = 64.000) e sotto quella
    # permissiva (100 x mediana = 800.000)
    dato = [candidato(70_000)]

    severa = snapshot(SPEND_ABS_FLOOR_TOKENS=40_000, SPEND_MEDIAN_MULT=8,
                      SPEND_P95_MULT=2, SPEND_MIN_HISTORY=25)
    permissiva = snapshot(SPEND_ABS_FLOOR_TOKENS=40_000, SPEND_MEDIAN_MULT=100,
                          SPEND_P95_MULT=2, SPEND_MIN_HISTORY=25)

    assert valuta_r3(dato, anomalie_note=(), now=ORA, config=severa).stato == VIOLAZIONE
    assert valuta_r3(dato, anomalie_note=(), now=ORA, config=permissiva).stato == OK


def test_evidence_is_json_serializable():
    import json

    esito = valuta_r3([candidato(soglia_richiesta())], anomalie_note=(), now=ORA, config=CONF)
    assert json.loads(json.dumps(esito.evidenza)) == esito.evidenza
