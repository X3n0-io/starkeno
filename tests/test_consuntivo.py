"""Regressioni concrete dell'attribuzione: ogni test uccide un modo di sbagliare nodo."""
from datetime import datetime, timedelta, timezone

from starkeno.consuntivo import (
    Attribuzione,
    Esecuzione,
    Marcatore,
    RigaOsservata,
    attribuisci,
)

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
