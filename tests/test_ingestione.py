"""La scrittura delle chiamate lette dal transcript.

Idempotente per costruzione, non per accortezza del chiamante: la chiave e'
`(session_id, message_id)` e l'indice unico la fa rispettare dal database.
"""
from starkeno import db
from starkeno.transcript import Chiamata


def _chiamata(message_id="m1", session_id="s1", **extra):
    campi = dict(
        session_id=session_id, message_id=message_id,
        timestamp="2026-08-07T10:00:00.000Z", project="starkeno",
        action="read:app.py", model_used="claude-opus-5",
        input_tokens=100, cache_read_tokens=900, cache_write_tokens=10,
        output_tokens=50, azione_fallita=0, esito_noto=1,
        azioni_nella_chiamata=1, skill="", plugin="", mcp_server="", is_sidechain=0)
    campi.update(extra)
    return Chiamata(**campi)


def test_scrive_le_chiamate(session):
    scritte = db.scrivi_chiamate(session, [_chiamata("m1"), _chiamata("m2")])
    assert scritte == 2
    assert session.query(db.AgentAction).count() == 2


def test_rieseguirla_sullo_stesso_transcript_non_duplica_niente(session):
    """LA prova che rende l'hook sicuro: gira a ogni turno sullo stesso file, che
    cresce. Senza questa, ogni turno riscriverebbe tutta la storia."""
    chiamate = [_chiamata("m1"), _chiamata("m2")]
    assert db.scrivi_chiamate(session, chiamate) == 2
    assert db.scrivi_chiamate(session, chiamate) == 0
    assert session.query(db.AgentAction).count() == 2


def test_scrive_solo_le_nuove_quando_il_transcript_cresce(session):
    db.scrivi_chiamate(session, [_chiamata("m1")])
    scritte = db.scrivi_chiamate(session, [_chiamata("m1"), _chiamata("m2")])
    assert scritte == 1
    assert session.query(db.AgentAction).count() == 2


def test_lo_stesso_message_id_in_sessioni_diverse_sono_due_righe(session):
    """`message.id` da solo NON e' unico: misurato, 71 righe -> 34 id."""
    db.scrivi_chiamate(session, [_chiamata("m1", session_id="A"),
                                 _chiamata("m1", session_id="B")])
    assert session.query(db.AgentAction).count() == 2


def test_il_timestamp_scritto_e_quello_del_transcript_non_l_ora_di_ingestione(session):
    """Il default della colonna e' l'ora dell'insert: qui va sovrascritto, o l'hook
    comprimerebbe ore di lavoro nell'istante in cui gira, e le regole a finestra corta
    lo vedrebbero come una raffica."""
    db.scrivi_chiamate(session, [_chiamata("m1", timestamp="2026-07-01T08:30:00.000Z")])
    riga = session.query(db.AgentAction).one()
    assert riga.timestamp.year == 2026 and riga.timestamp.month == 7
    assert riga.timestamp.tzinfo is not None, "invariante 1: sopra db.py tutto e' aware-UTC"


def test_una_chiamata_con_timestamp_illeggibile_si_salta_senza_fermare_le_altre(session):
    scritte = db.scrivi_chiamate(session, [
        _chiamata("m1", timestamp="non e' una data"),
        _chiamata("m2"),
    ])
    assert scritte == 1
