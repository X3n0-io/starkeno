"""Regressioni trovate dalla revisione di completezza del 2026-08-05.

Ognuno di questi test fallisce sul codice pre-correzione, e ognuno protegge un difetto
che sarebbe stato silenzioso: nessuno di questi bug produce un errore visibile all'utente,
tutti e quattro si manifestano come "sembra che funzioni".
"""
import os
import subprocess
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from starkeno.db import (
    AgentAction,
    make_session_factory,
    record_action,
    get_recent_actions,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------- timezone
def test_timestamp_roundtrips_as_aware_utc(session):
    """Il timestamp riletto dal DB deve essere aware-UTC.

    Senza questo, ogni finestra temporale del Supervisore solleva TypeError,
    il try/except per-regola lo inghiotte, e il sistema produce zero alert per sempre.
    """
    record_action(session, project="a", action="x", model_used="m", tokens_used=1)
    session.expire_all()  # forza la rilettura dal database, non dalla cache di sessione

    row = session.query(AgentAction).first()
    assert row.timestamp.tzinfo is not None, "timestamp riletto naive: aritmetica temporale rotta"
    assert row.timestamp.utcoffset().total_seconds() == 0

    # è questa l'operazione che il supervisore fa a ogni giro, per ogni regola
    delta = datetime.now(timezone.utc) - row.timestamp
    assert delta.total_seconds() >= 0


def test_naive_timestamp_written_is_read_back_as_utc(session):
    """Un chiamante che passa un datetime naive non deve far fallire la scrittura.

    §7 dello spec: il log non deve mai fallire. Il naive viene interpretato come UTC.
    """
    session.add(
        AgentAction(
            project="a", action="x", model_used="m", tokens_used=1,
            timestamp=datetime(2026, 8, 5, 12, 0, 0),  # naive
        )
    )
    session.commit()
    session.expire_all()

    row = session.query(AgentAction).first()
    assert row.timestamp.tzinfo is not None
    assert row.timestamp == datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------- ordine stabile
def test_recent_actions_deterministic_when_timestamps_collide(session):
    """Più azioni nello stesso istante devono avere un ordine stabile.

    È il caso normale per un agente in loop, cioè esattamente il caso interessante:
    senza un tiebreaker, la stessa query dà ordini diversi e una regola che ne dipende
    alterna VIOLAZIONE e OK sugli stessi identici dati.
    """
    same = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        session.add(
            AgentAction(project="a", action=f"n{i}", model_used="m", tokens_used=i, timestamp=same)
        )
    session.commit()

    first = [a.id for a in get_recent_actions(session, project="a", limit=10)]
    second = [a.id for a in get_recent_actions(session, project="a", limit=10)]

    assert first == second, "ordinamento non deterministico a parità di timestamp"
    assert first == sorted(first, reverse=True), "a parità di timestamp deve vincere l'id più alto"


# ------------------------------------------------------------------------- WAL
def test_wal_journal_mode_is_enabled(tmp_path):
    """Senza WAL i lettori bloccano gli scrittori: la dashboard blocca il logging."""
    SessionLocal = make_session_factory(str(tmp_path / "t.db"))
    session = SessionLocal()
    try:
        mode = session.execute(text("PRAGMA journal_mode")).scalar()
        assert mode.lower() == "wal"
    finally:
        session.close()
        SessionLocal.kw["bind"].dispose()


def test_busy_timeout_is_configured(tmp_path):
    """Senza timeout esplicito, due scritture concorrenti fanno fallire il log.

    Il default di python-sqlite3 e' 5000ms, quindi la soglia va sopra quel valore:
    altrimenti il test passerebbe senza che nessuno abbia configurato niente.
    """
    from starkeno.config import SQLITE_BUSY_TIMEOUT_SECONDS

    SessionLocal = make_session_factory(str(tmp_path / "t.db"))
    session = SessionLocal()
    try:
        timeout_ms = session.execute(text("PRAGMA busy_timeout")).scalar()
        assert timeout_ms == int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)
        assert timeout_ms > 5000, "e' rimasto il default di sqlite3, non e' stato configurato"
    finally:
        session.close()
        SessionLocal.kw["bind"].dispose()


# --------------------------------------------------- nessun effetto all'import
def test_importing_modules_does_not_create_the_database(tmp_path):
    """Importare un modulo non deve toccare il database configurato.

    Verificato prima della correzione: `python -c "import starkeno.mcp_server"` RICREA
    starkeno.db con lo schema di create_all e senza alembic_version. Di conseguenza un
    semplice `pytest` riavvelena il database di produzione, e la catena Alembic nasce rotta.
    """
    db_path = tmp_path / "should_not_exist.db"
    env = {**os.environ, "STARKENO_DB_PATH": str(db_path), "PYTHONPATH": PROJECT_ROOT}

    for module in ("starkeno.mcp_server", "starkeno.api"):
        if db_path.exists():
            db_path.unlink()
        result = subprocess.run(
            [sys.executable, "-c",
             f"import {module}; from starkeno.config import DB_PATH; print(DB_PATH)"],
            cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"import di {module} fallito: {result.stderr}"

        # senza questa asserzione il test sarebbe vacuo: se l'override venisse ignorato,
        # il modulo creerebbe il database DI PRODUZIONE e il tmp_path resterebbe pulito,
        # facendo passare il test proprio mentre il bug e' pienamente presente
        assert result.stdout.strip() == str(db_path), (
            "STARKENO_DB_PATH ignorato: il test starebbe guardando il file sbagliato"
        )
        assert not db_path.exists(), f"importare {module} ha creato il database"
