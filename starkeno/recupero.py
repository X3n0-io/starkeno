"""Inventario e recupero esplicito dello storico SQLite di StarkEno."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from starkeno.diagnostica import CandidatoDatabase, ispeziona_database
from starkeno.migrazioni import revisione_head


class RecuperoError(RuntimeError):
    """Il recupero non puo' proseguire senza rischiare lo storico."""


def inventaria_candidati(
    *, canonico: Path, radice_progetto: Path,
) -> tuple[CandidatoDatabase, ...]:
    """Controlla solo i tre percorsi StarkEno noti, senza cercare file personali."""
    radice = Path(radice_progetto)
    percorsi = (
        Path(canonico),
        radice / "starkeno.db",
        radice / "starkeno.db.trasferito",
    )
    return tuple(ispeziona_database(percorso) for percorso in percorsi)


def _uri_sola_lettura(path: Path) -> str:
    percorso = quote(path.resolve().as_posix(), safe="/:")
    parametri = "mode=ro"
    if not path.with_name(path.name + "-wal").exists():
        parametri += "&immutable=1"
    return "file:%s?%s" % (percorso, parametri)


def _copia_sqlite(sorgente: Path, destinazione: Path) -> None:
    """Copia uno snapshot consistente, includendo le transazioni nel WAL."""
    origine = sqlite3.connect(_uri_sola_lettura(sorgente), uri=True)
    copia = None
    try:
        copia = sqlite3.connect(str(destinazione))
        origine.backup(copia)
    finally:
        if copia is not None:
            copia.close()
        origine.close()


def recupera_database(
    sorgente: Path,
    destinazione: Path,
    *,
    now: datetime,
    migra: Callable[[Path], None],
) -> Path | None:
    """Copia, migra e verifica lo storico prima di sostituire la destinazione.

    La sorgente non viene mai modificata. Se la destinazione esiste, ne viene creata
    una copia consistente e timestampata prima della sostituzione atomica.
    """
    sorgente = Path(sorgente)
    destinazione = Path(destinazione)
    if sorgente.resolve() == destinazione.resolve():
        raise RecuperoError("sorgente e destinazione coincidono")

    stato_sorgente = ispeziona_database(sorgente)
    if not stato_sorgente.integro:
        raise RecuperoError("sorgente non integra")

    destinazione.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = destinazione.with_name(destinazione.name + ".recupero")
    if temporaneo.exists():
        raise RecuperoError("recupero precedente incompleto")

    backup = None
    if destinazione.exists():
        if not ispeziona_database(destinazione).integro:
            raise RecuperoError("destinazione non integra")
        if any(
            destinazione.with_name(destinazione.name + suffisso).exists()
            for suffisso in ("-wal", "-shm")
        ):
            raise RecuperoError("chiudi StarkEno prima del recupero")
        istante = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = destinazione.with_name(
            destinazione.name + ".backup-" + istante
        )
        if backup.exists():
            raise RecuperoError("backup di destinazione gia' presente")

    try:
        _copia_sqlite(sorgente, temporaneo)
        migra(temporaneo)
        stato_temporaneo = ispeziona_database(temporaneo)
        if not stato_temporaneo.integro:
            raise RecuperoError("copia migrata non integra")
        if stato_temporaneo.revisione != revisione_head():
            raise RecuperoError("copia migrata non a head")
        if stato_temporaneo.righe != stato_sorgente.righe:
            raise RecuperoError("conteggio righe cambiato durante il recupero")

        if backup is not None:
            _copia_sqlite(destinazione, backup)
        os.replace(temporaneo, destinazione)
        return backup
    finally:
        if temporaneo.exists():
            temporaneo.unlink()
