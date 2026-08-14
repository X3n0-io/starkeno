import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command

from starkeno.diagnostica import ispeziona_database
from starkeno.migrazioni import configurazione_alembic, revisione_head, upgrade_head
from starkeno.recupero import (
    RecuperoError,
    inventaria_candidati,
    recupera_database,
)


ORA = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _crea_database(path: Path, revisione="0003", righe=1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(configurazione_alembic(path), revisione)
    colonna = "agent_name" if revisione <= "0003" else "project"
    with sqlite3.connect(path) as conn:
        for indice in range(righe):
            conn.execute(
                "INSERT INTO agent_actions"
                f"({colonna}, action, model_used, tokens_used, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                ("progetto", f"read:file-{indice}.py", "gpt-5", 100,
                 "2026-08-12 10:00:00"),
            )
    return path


def test_inventory_only_checks_known_starkeno_paths(tmp_path):
    canonico = tmp_path / "dati" / "starkeno.db"
    radice = tmp_path / "repo"

    trovati = inventaria_candidati(canonico=canonico, radice_progetto=radice)

    assert [x.percorso for x in trovati] == [
        canonico,
        radice / "starkeno.db",
        radice / "starkeno.db.trasferito",
    ]


def test_recovery_copies_migrates_and_preserves_the_source(tmp_path):
    sorgente = _crea_database(tmp_path / "storico.db", righe=3)
    with sqlite3.connect(sorgente) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    assert not sorgente.with_name(sorgente.name + "-wal").exists()
    assert not sorgente.with_name(sorgente.name + "-shm").exists()
    destinazione = tmp_path / "dati" / "starkeno.db"

    backup = recupera_database(
        sorgente, destinazione, now=ORA,
        migra=lambda p: upgrade_head(p, silenzioso=True),
    )

    assert backup is None
    assert sorgente.exists()
    assert ispeziona_database(sorgente).righe == 3
    assert ispeziona_database(destinazione).righe == 3
    assert ispeziona_database(destinazione).revisione == revisione_head()
    assert not sorgente.with_name(sorgente.name + "-wal").exists()
    assert not sorgente.with_name(sorgente.name + "-shm").exists()


def test_existing_destination_is_backed_up_before_replacement(tmp_path):
    sorgente = _crea_database(tmp_path / "storico.db", righe=3)
    destinazione = _crea_database(
        tmp_path / "dati" / "starkeno.db", revisione="0005", righe=1,
    )

    backup = recupera_database(
        sorgente, destinazione, now=ORA,
        migra=lambda p: upgrade_head(p, silenzioso=True),
    )

    assert backup == destinazione.with_name(
        "starkeno.db.backup-20260812T120000Z"
    )
    assert ispeziona_database(backup).righe == 1
    assert ispeziona_database(destinazione).righe == 3
    assert ispeziona_database(sorgente).righe == 3


def test_failed_migration_leaves_source_and_destination_unchanged(tmp_path):
    sorgente = _crea_database(tmp_path / "storico.db", righe=3)
    destinazione = _crea_database(
        tmp_path / "dati" / "starkeno.db", revisione="0005", righe=1,
    )

    def migrazione_fallita(_path):
        raise RuntimeError("migrazione fallita")

    with pytest.raises(RuntimeError, match="migrazione fallita"):
        recupera_database(sorgente, destinazione, now=ORA, migra=migrazione_fallita)

    assert ispeziona_database(sorgente).righe == 3
    assert ispeziona_database(destinazione).righe == 1
    assert not destinazione.with_name("starkeno.db.recupero").exists()
    assert not list(destinazione.parent.glob("*.backup-*"))


def test_recovery_rejects_a_corrupt_source_without_touching_destination(tmp_path):
    sorgente = tmp_path / "rotto.db"
    sorgente.write_bytes(b"non e sqlite")
    destinazione = _crea_database(
        tmp_path / "dati" / "starkeno.db", revisione="0005", righe=1,
    )

    with pytest.raises(RecuperoError, match="sorgente non integra"):
        recupera_database(
            sorgente, destinazione, now=ORA,
            migra=lambda p: upgrade_head(p, silenzioso=True),
        )

    assert ispeziona_database(destinazione).righe == 1
