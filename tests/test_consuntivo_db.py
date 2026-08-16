"""Le due tabelle nuove, su database usa e getta. Nessun test tocca il database reale."""
from datetime import datetime, timedelta, timezone

import pytest

from starkeno import db

INIZIO = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


def _apri(session, *, progetto="progetto", chiave="k1"):
    return db.apri_esecuzione(
        session, run_key=chiave, project=progetto, blueprint_hash="h",
        analysis_json="{}", model_map_json="{}", started_at=INIZIO,
    )


def test_una_esecuzione_aperta_si_ritrova_per_progetto(session):
    _apri(session)

    assert db.esecuzione_aperta(session, "progetto") is not None
    assert db.esecuzione_aperta(session, "altro") is None


def test_una_esecuzione_chiusa_non_risulta_piu_aperta(session):
    run = _apri(session)

    db.chiudi_esecuzione(session, run, ended_at=INIZIO + timedelta(hours=1))

    assert db.esecuzione_aperta(session, "progetto") is None


def test_il_progetto_si_normalizza_come_le_righe_raccolte(session):
    """Senza, un `project` con maiuscole o spazi non incrocia mai le righe raccolte."""
    _apri(session, progetto="  Progetto  ")

    assert db.esecuzione_aperta(session, db.normalizza_progetto("Progetto")) is not None


def test_seq_dei_marcatori_e_progressivo_e_non_arriva_dal_chiamante(session):
    """La regressione: due marcatori con lo stesso `declared_at` e lo stesso `seq`,
    ordinati a caso, con l'intervallo fra i due sul nodo sbagliato."""
    run = _apri(session)

    primo = db.aggiungi_marcatore(session, run, node_id="draft", declared_at=INIZIO)
    secondo = db.aggiungi_marcatore(session, run, node_id="review", declared_at=INIZIO)

    assert (primo.seq, secondo.seq) == (1, 2)


def test_i_marcatori_tornano_come_snapshot_puri_ordinati(session):
    run = _apri(session)
    db.aggiungi_marcatore(session, run, node_id="review", declared_at=INIZIO + timedelta(minutes=10))
    db.aggiungi_marcatore(session, run, node_id="draft", declared_at=INIZIO)

    letti = db.marcatori_di(session, run)

    assert [m.node_id for m in letti] == ["draft", "review"]
    assert letti[0].declared_at.tzinfo is not None


def test_righe_nella_finestra_filtra_progetto_e_intervallo(session):
    for minuti, progetto in ((5, "progetto"), (5, "altro"), (500, "progetto")):
        db.scrivi_chiamate(session, [_chiamata(minuti, progetto)])

    righe = db.righe_nella_finestra(
        session, "progetto", INIZIO, INIZIO + timedelta(hours=1)
    )

    assert len(righe) == 1
    assert righe[0].timestamp.tzinfo is not None


def _chiamata(minuti, progetto):
    from starkeno.transcript import Chiamata

    quando = INIZIO + timedelta(minutes=minuti)
    return Chiamata(
        session_id="s1", message_id="m%d%s" % (minuti, progetto),
        timestamp=quando.isoformat(), project=progetto, action="read",
        model_used="opus", input_tokens=600, cache_read_tokens=100,
        cache_write_tokens=100, output_tokens=200, azione_fallita=0, esito_noto=1,
        azioni_nella_chiamata=1, skill="", plugin="", mcp_server="", is_sidechain=0,
    )


def test_la_mappatura_si_aggiorna_anche_su_un_esecuzione_chiusa(session):
    """E' il ciclo utile: il confronto elenca i modelli non mappati, li dichiari, e
    ricalcoli. La regressione: la mappatura tardiva viene ignorata in silenzio e il
    confronto continua a dire «moneta ignota» per sempre."""
    run = _apri(session)
    db.chiudi_esecuzione(session, run, ended_at=INIZIO + timedelta(hours=1))

    db.aggiorna_mappatura(session, run, model_map_json='{"opus-4": "economy"}')

    assert db.esecuzione_snapshot(run).model_map == {"opus-4": "economy"}


def test_chiudere_prima_di_aprire_e_rifiutato(session):
    """Un orologio che torna indietro non deve produrre una finestra negativa."""
    run = _apri(session)

    with pytest.raises(ValueError):
        db.chiudi_esecuzione(session, run, ended_at=INIZIO - timedelta(minutes=1))

    assert db.esecuzione_aperta(session, "progetto") is not None
