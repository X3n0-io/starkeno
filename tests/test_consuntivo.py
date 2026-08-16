"""Regressioni concrete dell'attribuzione: ogni test uccide un modo di sbagliare nodo."""
import dataclasses
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from starkeno.consuntivo import (
    Attribuzione,
    ConfrontoNodo,
    Consuntivo,
    Esecuzione,
    Marcatore,
    Moneta,
    RigaOsservata,
    SCENARI,
    StimaScenario,
    TotaliOsservati,
    attribuisci,
    calcola_moneta,
    costruisci,
    posizione_nella_banda,
    rendi_testo,
    stime_per_scenario,
    totali,
    totali_per_modello,
)
from starkeno.preflight_schema import Blueprint
from starkeno.preflight_simulate import simulate_blueprint

INIZIO = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


def _riga(minuti, *, sessione="s1", modello="opus", totale=1000):
    return RigaOsservata(
        session_id=sessione,
        timestamp=INIZIO + timedelta(minutes=minuti),
        model_used=modello,
        tokens_used=totale,
        cache_read_tokens=100,
        cache_write_tokens=100,
        output_tokens=200,
        azioni_nella_chiamata=1,
    )


def _esecuzione(*, fine_minuti=60):
    return Esecuzione(
        run_key="k1",
        project="progetto",
        blueprint_hash="h",
        started_at=INIZIO,
        ended_at=None if fine_minuti is None else INIZIO + timedelta(minutes=fine_minuti),
        model_map={},
    )


def _marcatore(nodo, minuti, seq):
    return Marcatore(node_id=nodo, declared_at=INIZIO + timedelta(minutes=minuti), seq=seq)


def _nodi(attribuzione):
    return {nodo: len(righe) for nodo, righe in attribuzione.per_nodo}


def _riga_grezza(totale, *, lettura, scrittura, uscita, modello="opus", azioni=1):
    return RigaOsservata(
        session_id="s1", timestamp=INIZIO, model_used=modello, tokens_used=totale,
        cache_read_tokens=lettura, cache_write_tokens=scrittura, output_tokens=uscita,
        azioni_nella_chiamata=azioni,
    )


def test_totali_scompongono_le_quattro_classi_come_il_conto():
    """`ingresso = totale - lettura - scrittura - uscita`, identico a calcola_conto."""
    righe = [_riga_grezza(1000, lettura=100, scrittura=50, uscita=200, azioni=3)]

    risultato = totali(righe)

    assert risultato.chiamate == 1
    assert risultato.azioni == 3
    assert risultato.input_tokens == 650
    assert risultato.cache_read_tokens == 100
    assert risultato.cache_write_tokens == 50
    assert risultato.output_tokens == 200
    assert risultato.totale_tokens == 1000
    assert risultato.righe_non_scomposte == 0


def test_una_scomposizione_parziale_vale_come_nessuna_scomposizione():
    """NULL significa «non dichiarato». Trattarlo come 0 sottostima la spesa, ed e'
    esattamente cio' che `record_action` documenta di non voler fare."""
    righe = [_riga_grezza(1000, lettura=100, scrittura=None, uscita=200)]

    risultato = totali(righe)

    assert risultato.totale_tokens == 1000
    assert risultato.righe_non_scomposte == 1
    assert risultato.input_tokens == 0
    assert risultato.cache_read_tokens == 0


def test_totali_per_modello_separano_i_modelli_e_ordinano_per_nome():
    righe = [
        _riga_grezza(1000, lettura=0, scrittura=0, uscita=100, modello="sonnet"),
        _riga_grezza(2000, lettura=0, scrittura=0, uscita=200, modello="opus"),
    ]

    risultato = totali_per_modello(righe)

    assert [nome for nome, _ in risultato] == ["opus", "sonnet"]
    assert risultato[0][1].totale_tokens == 2000


def test_riga_sul_confine_appartiene_al_nodo_nuovo():
    """Intervalli SEMIAPERTI. Con intervalli chiusi la riga finisce sul nodo precedente."""
    marcatori = [_marcatore("draft", 0, 1), _marcatore("review", 10, 2)]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(10)])

    assert risultato.stato == "ok"
    assert _nodi(risultato) == {"draft": 0, "review": 1}


def test_righe_prima_del_primo_marcatore_non_sono_attribuite():
    """La regressione: finiscono sul primo nodo, che non le ha mai prodotte."""
    marcatori = [_marcatore("draft", 10, 1)]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(5), _riga(15)])

    assert _nodi(risultato) == {"draft": 1}
    assert len(risultato.non_attribuite) == 1


def test_due_sessioni_fermano_il_confronto():
    """La regressione: le somma, e attribuisce a un nodo il lavoro di un altro lavoro."""
    marcatori = [_marcatore("draft", 0, 1)]

    risultato = attribuisci(
        _esecuzione(), marcatori, [_riga(5, sessione="s1"), _riga(6, sessione="s2")]
    )

    assert risultato.stato == "ambigua"
    assert risultato.per_nodo == ()
    assert risultato.sessioni == ("s1", "s2")
    assert "s1" in risultato.motivo and "s2" in risultato.motivo


def test_una_riga_senza_sessione_non_rende_ambigua_l_esecuzione():
    """`record_action` non imposta mai `session_id`: ogni riga di `log_agent_action` ha
    sessione vuota. Senza questa clausola UNA sola di esse rende ambigua ogni
    esecuzione, per sempre."""
    marcatori = [_marcatore("draft", 0, 1)]

    risultato = attribuisci(
        _esecuzione(), marcatori, [_riga(5, sessione="s1"), _riga(6, sessione="")]
    )

    assert risultato.stato == "ok"
    assert _nodi(risultato) == {"draft": 1}
    assert len(risultato.senza_sessione) == 1


def test_solo_righe_senza_sessione_e_senza_osservazioni():
    """La regressione: risulta `ok` con tutto in un secchio, come se avesse osservato."""
    marcatori = [_marcatore("draft", 0, 1)]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(5, sessione="")])

    assert risultato.stato == "senza_osservazioni"
    assert len(risultato.senza_sessione) == 1


def test_esecuzione_aperta_non_produce_attribuzione():
    """La regressione: calcola su una finestra che non e' ancora chiusa."""
    risultato = attribuisci(
        _esecuzione(fine_minuti=None), [_marcatore("draft", 0, 1)], [_riga(5)]
    )

    assert risultato.stato == "aperta"
    assert risultato.per_nodo == ()


def test_righe_fuori_dalla_finestra_sono_ignorate():
    """La finestra autorevole e' qui, non nel pre-filtro SQL."""
    marcatori = [_marcatore("draft", 0, 1)]

    risultato = attribuisci(_esecuzione(fine_minuti=30), marcatori, [_riga(10), _riga(50)])

    assert _nodi(risultato) == {"draft": 1}
    assert risultato.non_attribuite == ()


def test_stesso_nodo_dichiarato_due_volte_produce_una_riga_sola():
    """Un ritorno su `review` non deve produrre due `review` nel confronto."""
    marcatori = [
        _marcatore("draft", 0, 1),
        _marcatore("review", 10, 2),
        _marcatore("draft", 20, 3),
    ]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(5), _riga(15), _riga(25)])

    assert _nodi(risultato) == {"draft": 2, "review": 1}


def test_marcatori_con_lo_stesso_istante_si_ordinano_per_seq():
    """Senza `seq` l'ordine di due marcatori simultanei dipende dall'ordinamento."""
    marcatori = [_marcatore("review", 10, 2), _marcatore("draft", 10, 1)]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(15)])

    assert [nodo for nodo, _ in risultato.per_nodo] == ["draft", "review"]
    assert _nodi(risultato) == {"draft": 0, "review": 1}


def test_esecuzione_senza_marcatori_mette_tutto_in_non_attribuite():
    risultato = attribuisci(_esecuzione(), [], [_riga(5), _riga(6)])

    assert risultato.stato == "ok"
    assert risultato.per_nodo == ()
    assert len(risultato.non_attribuite) == 2


FIXTURE = Path(__file__).parent / "fixtures" / "preflight" / "minimal.json"


def _blueprint(**prezzi):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = True
    payload["models"][0].update(prezzi)
    return Blueprint.model_validate(payload)


def _blueprint_senza_massimo():
    """Come `_blueprint`, ma con `max_retries` assente sul nodo `draft` (`nodes[0]`).

    Questo fa scattare `_has_unbounded_maximum` in `preflight_simulate.py`
    (`max_retries is None` e `retry_probability.max > 0`), quindi la simulazione lascia
    `maximum = None`. Il grafo NON e' pero' inevitabilmente unbounded — lo richiederebbe
    `retry_probability.typical >= 1`, e quello di `draft` e' 0.05 — quindi `optimistic`,
    `typical` e `prudent` restano tutti presenti: e' l'unico modo di ottenere un Blueprint
    con esattamente uno scenario assente e gli altri tre no."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = True
    payload["nodes"][0]["budget"]["max_retries"] = None
    return Blueprint.model_validate(payload)


def _simulazione(blueprint):
    return simulate_blueprint(blueprint, samples=8, seed=7)


def _scenario(nome, totale):
    """Scenari SINTETICI: la banda va provata su valori scelti, non su una simulazione
    i cui scenari potrebbero coincidere e rendere il test intermittente."""
    return StimaScenario(
        nome=nome, input_tokens=totale, output_tokens=0, cache_read_tokens=0,
        cache_write_tokens=0, totale_tokens=totale, executions=1, llm_calls=1,
        tool_calls=0, costo=None, valuta=None,
    )


def test_posizione_nella_banda_dice_dove_cade_l_osservato():
    scenari = (
        _scenario("optimistic", 100), _scenario("typical", 200),
        _scenario("prudent", 300), _scenario("maximum", 400),
    )

    assert posizione_nella_banda(50, scenari) == "sotto optimistic"
    assert posizione_nella_banda(250, scenari) == "fra typical e prudent"
    assert posizione_nella_banda(200, scenari) == "esattamente su typical"
    assert posizione_nella_banda(500, scenari) == "oltre maximum"


def test_uno_scenario_assente_non_entra_nella_banda_come_zero():
    """La regressione: `None` letto come 0 mette ogni osservazione «oltre il massimo»."""
    parziali = (_scenario("optimistic", 100), _scenario("typical", 200))

    testo = posizione_nella_banda(10**9, parziali)

    assert "prudent" in testo and "maximum" in testo
    assert "banda incompleta" in testo


def test_stime_per_scenario_salta_gli_scenari_assenti():
    """Un `maximum` None non deve comparire come uno scenario da zero token.

    La regressione: togliere `if scenario is not None:` in `stime_per_scenario` prova a
    costruire uno `StimaScenario` anche dal `maximum` assente di `_blueprint_senza_massimo`
    (vedi la sua docstring) invece di ometterlo."""
    scenari = stime_per_scenario(_simulazione(_blueprint_senza_massimo()))

    nomi = {s.nome for s in scenari}
    assert "maximum" not in nomi
    assert nomi == {"optimistic", "typical", "prudent"}
    assert not any(s.nome == "maximum" and s.totale_tokens == 0 for s in scenari)


def test_nodi_ordinati_per_scarto_assoluto_decrescente():
    """La prima riga deve rispondere a «dove e' finito il grosso»."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    marcatori = [_marcatore("draft", 0, 1), _marcatore("review", 30, 2)]
    righe = [_riga(5, totale=50), _riga(35, totale=500_000)]
    attribuzione = attribuisci(esecuzione, marcatori, righe)

    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)

    assert [nodo.node_id for nodo in consuntivo.nodi][0] == "review"


def test_un_nodo_senza_osservazioni_compare_a_zero_e_lo_dichiara():
    """«costato poco» e «mai eseguito» sono cose diverse: sparire le confonde."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    marcatori = [_marcatore("draft", 0, 1)]
    attribuzione = attribuisci(esecuzione, marcatori, [_riga(5)])

    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)

    review = [nodo for nodo in consuntivo.nodi if nodo.node_id == "review"]
    assert len(review) == 1
    assert review[0].osservato is None


def test_il_join_col_nodo_stimato_usa_il_node_id():
    """La regressione: se `per_nodo_typical.get(nodo.id)` in `costruisci` smettesse di
    combaciare, o le due sorgenti di `executions_stimate` / `chiamate_osservate` si
    scambiassero, la suite restava verde lo stesso — prima solo l'ordinamento e il nodo
    da 500000 token erano coperti, e quel nodo domina qualunque scarto per costruzione."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    marcatori = [_marcatore("draft", 0, 1), _marcatore("review", 30, 2)]
    righe = [_riga(5, totale=300), _riga(10, totale=400), _riga(35, totale=100)]
    attribuzione = attribuisci(esecuzione, marcatori, righe)

    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)

    per_nodo = {nodo.node_id: nodo for nodo in consuntivo.nodi}
    draft, review = per_nodo["draft"], per_nodo["review"]

    assert draft.stima_typical is not None and draft.stima_typical.nome == "typical"
    assert draft.stima_typical.totale_tokens > 0  # draft e' llm, con budget reale

    assert review.stima_typical is not None
    assert review.stima_typical.totale_tokens == 0  # review e' human, budget tutto zero
    # Il contrasto e' il punto: un join che pescasse il nodo sbagliato scambierebbe
    # questi due totali.

    assert draft.stima_typical.totale_tokens == (
        draft.stima_typical.input_tokens + draft.stima_typical.output_tokens
        + draft.stima_typical.cache_read_tokens + draft.stima_typical.cache_write_tokens
    )
    assert draft.executions_stimate >= 1
    assert draft.chiamate_osservate == 2

    assert draft.scarto_totale_tokens == (
        draft.osservato.totale_tokens - draft.stima_typical.totale_tokens
    )


def test_le_chiamate_stimate_e_osservate_non_si_sottraggono():
    """`executions` conta invocazioni di nodo, la riga conta chiamate API: unita'
    diverse. La regressione da uccidere e' un campo di scarto fra le due."""
    campi = {campo for campo in ConfrontoNodo.__dataclass_fields__}

    assert "scarto_chiamate" not in campi
    assert "scarto_executions" not in campi
    assert "executions_stimate" in campi
    assert "chiamate_osservate" in campi


def test_uno_stato_non_ok_non_produce_nodi():
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    attribuzione = attribuisci(
        esecuzione, [_marcatore("draft", 0, 1)],
        [_riga(5, sessione="s1"), _riga(6, sessione="s2")],
    )

    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)

    assert consuntivo.stato == "ambigua"
    assert consuntivo.nodi == ()
    assert consuntivo.motivo


PREZZI = {
    "input_price_per_million": "3.00",
    "output_price_per_million": "15.00",
    "cache_read_price_per_million": "0.30",
    "cache_write_price_per_million": "3.75",
}


def test_i_token_osservati_si_prezzano_col_listino_del_blueprint():
    """Gli STESSI prezzi della stima: cosi' lo scarto isola il volume, non il listino."""
    blueprint = _blueprint(**PREZZI)
    righe = [_riga_grezza(1_000_000, lettura=0, scrittura=0, uscita=0, modello="opus-4")]

    moneta = calcola_moneta(righe, {"opus-4": "economy"}, blueprint)

    assert moneta is not None
    assert moneta.valuta == "USD"
    assert moneta.osservata == Decimal("3.00")
    assert moneta.token_non_prezzati == 0


def test_un_modello_non_mappato_conta_i_token_e_dichiara_la_moneta_ignota():
    """La regressione peggiore: prezzarlo zero. Un costo mancante sembra un costo basso."""
    blueprint = _blueprint(**PREZZI)
    righe = [_riga_grezza(1_000_000, lettura=0, scrittura=0, uscita=0, modello="ignoto")]

    moneta = calcola_moneta(righe, {}, blueprint)

    assert moneta is not None
    assert moneta.osservata == Decimal("0")
    assert moneta.token_non_prezzati == 1_000_000
    assert moneta.modelli_senza_prezzo == (("ignoto", 1_000_000, "non mappato"),)


def test_un_modello_mappato_a_un_id_inesistente_dichiara_profilo_inesistente():
    """La regressione: prima di questo fix un id battuto male in `model_map` spariva nello
    stesso `token_non_prezzati` di un modello mai dichiarato, senza lasciare traccia in
    `modelli_non_mappati` (che vedeva solo `model_map.get(nome) is None`). Qui il rimedio
    e' diverso — correggere l'id, non aggiungerlo — quindi va distinto."""
    blueprint = _blueprint(**PREZZI)
    righe = [_riga_grezza(1_000_000, lettura=0, scrittura=0, uscita=0, modello="opus-4")]

    moneta = calcola_moneta(righe, {"opus-4": "id-che-non-esiste"}, blueprint)

    assert moneta is not None
    assert moneta.osservata == Decimal("0")
    assert moneta.token_non_prezzati == 1_000_000
    assert moneta.modelli_senza_prezzo == (
        ("opus-4", 1_000_000, "profilo inesistente"),
    )


def test_un_modello_mappato_a_un_listino_incompleto_dichiara_listino_incompleto():
    """La regressione: prima di questo fix un profilo che esiste ma con un prezzo
    mancante spariva anch'esso in `token_non_prezzati` senza comparire in
    `modelli_non_mappati`, indistinguibile da un id inesistente o da un modello mai
    dichiarato — coi tre motivi confusi, chi legge non sa se dichiarare, correggere o
    completare il listino."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = True
    payload["models"][0].update(PREZZI)  # "economy": prezzato per intero, cosi'
    # calcola_moneta non torna None per assenza di QUALSIASI listino completo.
    incompleto = json.loads(json.dumps(payload["models"][0]))
    incompleto.update({"id": "incompleto", "output_price_per_million": None})
    payload["models"].append(incompleto)
    blueprint = Blueprint.model_validate(payload)
    righe = [_riga_grezza(1_000_000, lettura=0, scrittura=0, uscita=0, modello="opus-4")]

    moneta = calcola_moneta(righe, {"opus-4": "incompleto"}, blueprint)

    assert moneta is not None
    assert moneta.osservata == Decimal("0")
    assert moneta.token_non_prezzati == 1_000_000
    assert moneta.modelli_senza_prezzo == (
        ("opus-4", 1_000_000, "listino incompleto"),
    )


def test_la_moneta_e_i_totali_leggono_le_stesse_righe():
    """La regressione futura da bloccare: `costruisci` ricostruiva la lista delle righe
    osservate DUE volte, una per `calcola_moneta` e una per `totali`, una quindicina di
    righe piu' sotto. Oggi combaciano, ma se una delle due cambiasse da sola la moneta si
    scollerebbe in silenzio dai totali che dovrebbe descrivere. Righe sia su un nodo sia
    in `non_attribuite`, e nessun modello mappato: se le due basi divergessero, questa
    uguaglianza si romperebbe subito."""
    blueprint = _blueprint(**PREZZI)
    esecuzione = _esecuzione()
    marcatori = [_marcatore("draft", 10, 1)]
    righe = [_riga(5), _riga(15)]
    attribuzione = attribuisci(esecuzione, marcatori, righe)

    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)

    # Precondizione: le righe finiscono davvero su entrambe le sponde.
    assert len(attribuzione.non_attribuite) == 1
    assert sum(len(r) for _, r in attribuzione.per_nodo) == 1
    assert consuntivo.moneta is not None
    assert consuntivo.moneta.token_non_prezzati == consuntivo.osservato.totale_tokens


def test_senza_prezzi_nel_blueprint_la_moneta_e_assente_non_zero():
    """La fixture minimal ha tutti i prezzi a null: e' il caso normale, non un errore."""
    blueprint = _blueprint()
    righe = [_riga_grezza(1000, lettura=0, scrittura=0, uscita=0, modello="opus-4")]

    assert calcola_moneta(righe, {"opus-4": "economy"}, blueprint) is None


def test_valute_diverse_fra_i_modelli_mappati_rendono_la_moneta_assente():
    """Sommare USD ed EUR produrrebbe un numero che non e' denaro."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = True
    payload["models"][0].update(PREZZI)
    secondo = json.loads(json.dumps(payload["models"][0]))
    secondo.update({"id": "premium", "currency": "EUR"})
    payload["models"].append(secondo)
    blueprint = Blueprint.model_validate(payload)
    righe = [
        _riga_grezza(1000, lettura=0, scrittura=0, uscita=0, modello="a"),
        _riga_grezza(1000, lettura=0, scrittura=0, uscita=0, modello="b"),
    ]

    assert calcola_moneta(righe, {"a": "economy", "b": "premium"}, blueprint) is None


def test_una_riga_non_scomposta_non_si_prezza():
    """Senza scomposizione non si sa quanto sia output: prezzarla a tariffa input mente."""
    blueprint = _blueprint(**PREZZI)
    righe = [_riga_grezza(1_000_000, lettura=0, scrittura=None, uscita=0, modello="opus-4")]

    moneta = calcola_moneta(righe, {"opus-4": "economy"}, blueprint)

    assert moneta is not None
    assert moneta.osservata == Decimal("0")
    assert moneta.token_non_prezzati == 1_000_000


def test_la_resa_dichiara_lo_scarto_atteso_sulla_cache():
    """Chi lo vede la prima volta pensa di aver sbagliato una sottrazione: la simulazione
    conta cache_write una volta e cache_read solo sui retry, un agente vero rispedisce il
    contesto a ogni turno. Va scritto, non lasciato dedurre."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    attribuzione = attribuisci(esecuzione, [_marcatore("draft", 0, 1)], [_riga(5)])

    testo = rendi_testo(costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint))

    assert "cache" in testo.lower()
    assert "contesto a ogni turno" in testo


def test_la_resa_di_uno_stato_non_ok_dice_il_motivo_e_non_stampa_numeri():
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    attribuzione = attribuisci(
        esecuzione, [_marcatore("draft", 0, 1)],
        [_riga(5, sessione="s1"), _riga(6, sessione="s2")],
    )

    testo = rendi_testo(costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint))

    assert "ambigua" in testo
    assert "s1" in testo and "s2" in testo
    assert "Per nodo" not in testo


def test_ogni_numero_dice_su_quante_chiamate_e_calcolato():
    """Il Passo 3 lo richiedera' comunque: un numero tarato su tre esecuzioni e uno
    tarato su trecento non valgono uguale.

    Due nodi con un numero DIVERSO di righe: con un solo nodo (o due nodi con lo stesso
    conteggio) l'assert sul "su N chiamate" per nodo sarebbe soddisfatto anche dalla riga
    d'intestazione aggregata (`osservato.chiamate`), che riporta lo stesso N per
    coincidenza — e un `rendi_testo` a cui manchi la clausola per nodo passerebbe lo
    stesso. Qui `draft` (2 righe) e `review` (3 righe) restano distinti dal totale
    aggregato (5 righe), quindi ciascuno dei tre numeri prova solo la riga che dichiara di
    provare."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    marcatori = [_marcatore("draft", 0, 1), _marcatore("review", 30, 2)]
    righe = [_riga(5), _riga(10), _riga(35), _riga(40), _riga(45)]
    attribuzione = attribuisci(esecuzione, marcatori, righe)
    assert _nodi(attribuzione) == {"draft": 2, "review": 3}  # precondizione sui secchi

    testo = rendi_testo(costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint))

    assert "su 2 chiamate" in testo  # la riga di `draft`
    assert "su 3 chiamate" in testo  # la riga di `review`
    assert "su 5 chiamate" in testo  # l'intestazione aggregata (2 + 3)


def test_la_resa_di_uno_stato_non_ok_conta_le_righe_senza_sessione_ma_non_altri_numeri():
    """Eccezione dichiarata alla regola «uno stato diverso da ok non stampa numeri»: il
    conteggio delle righe senza sessione e' diagnostico (spiega perche' non c'e' un
    confronto), non un numero di risultato, e resta anche qui. La regressione da uccidere
    e' doppia: sparire del tutto (nessuna test lo copriva finora), o trascinarsi dietro un
    numero di risultato vero e proprio."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    attribuzione = attribuisci(
        esecuzione, [_marcatore("draft", 0, 1)],
        [_riga(5, sessione="s1"), _riga(6, sessione="s2"), _riga(7, sessione="")],
    )
    assert attribuzione.stato == "ambigua"
    assert len(attribuzione.senza_sessione) == 1  # precondizione: il secchio non e' vuoto

    testo = rendi_testo(costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint))

    assert "Righe senza sessione nella finestra: 1 (mai attribuite)" in testo
    assert "Per nodo" not in testo
    assert "Stimato:" not in testo


def test_un_motivo_sconosciuto_in_moneta_non_fa_cadere_la_resa():
    """`_RIMEDIO_PER_MOTIVO[motivo]` era l'unico accesso non guardato del file: oggi i tre
    motivi di `calcola_moneta` combaciano sempre con le sue chiavi, ma nulla lo impone, e
    `Moneta` e' un dataclass pubblico congelato che chiunque puo' costruire con un motivo
    inventato. La regressione da uccidere e' un `KeyError` che affonderebbe la resa — CLI e
    tool MCP insieme — su un confronto gia' calcolato correttamente."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    attribuzione = attribuisci(esecuzione, [_marcatore("draft", 0, 1)], [_riga(5)])
    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)
    moneta_con_motivo_ignoto = Moneta(
        valuta="USD", osservata=Decimal("0"), token_non_prezzati=10,
        modelli_senza_prezzo=(("modello-x", 10, "motivo-inventato"),),
    )
    consuntivo = dataclasses.replace(consuntivo, moneta=moneta_con_motivo_ignoto)

    testo = rendi_testo(consuntivo)  # non deve sollevare

    assert "motivo-inventato" in testo
