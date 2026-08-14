"""Diagnosi locale e in sola lettura dell'installazione StarkEno."""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.parse import quote

from starkeno.migrazioni import revisione_head


StatoControllo = Literal["ok", "attenzione", "errore", "manuale"]


@dataclass(frozen=True)
class Controllo:
    codice: str
    stato: StatoControllo
    dettaglio: str
    dati: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidatoDatabase:
    percorso: Path
    integro: bool
    revisione: str | None
    righe: int | None
    ultimo_evento: str | None
    errore: str | None


def _uri_sola_lettura(path: Path) -> str:
    percorso = quote(path.resolve().as_posix(), safe="/:")
    parametri = "mode=ro"
    if not path.with_name(path.name + "-wal").exists():
        parametri += "&immutable=1"
    return "file:%s?%s" % (percorso, parametri)


def ispeziona_database(path: Path) -> CandidatoDatabase:
    """Legge integrità e stato senza creare il file o i sidecar SQLite."""
    path = Path(path)
    if not path.exists():
        return CandidatoDatabase(path, False, None, None, None, "database_assente")
    if not path.is_file():
        return CandidatoDatabase(path, False, None, None, None, "database_non_file")

    connessione = None
    try:
        connessione = sqlite3.connect(_uri_sola_lettura(path), uri=True)
        verifica = connessione.execute("PRAGMA quick_check").fetchone()
        if not verifica or verifica[0] != "ok":
            return CandidatoDatabase(
                path, False, None, None, None, "integrita_fallita",
            )
        tabelle = {
            riga[0]
            for riga in connessione.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "agent_actions" not in tabelle:
            return CandidatoDatabase(
                path, False, None, None, None, "schema_incompleto",
            )
        revisione = None
        if "alembic_version" in tabelle:
            riga = connessione.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            revisione = riga[0] if riga else None
        righe, ultimo = connessione.execute(
            "SELECT COUNT(*), MAX(timestamp) FROM agent_actions"
        ).fetchone()
        return CandidatoDatabase(path, True, revisione, righe, ultimo, None)
    except (OSError, sqlite3.DatabaseError):
        return CandidatoDatabase(
            path, False, None, None, None, "database_illeggibile",
        )
    finally:
        if connessione is not None:
            connessione.close()


def trova_plugin_codex(codex_root: Path) -> Controllo:
    """Cerca StarkEno soltanto nel layout cache documentato da Codex."""
    cache = Path(codex_root) / "plugins" / "cache"
    trovati = []
    if cache.is_dir():
        for manifest in cache.rglob(".codex-plugin/plugin.json"):
            try:
                dati = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if dati.get("name") == "starkeno" and dati.get("version"):
                trovati.append((str(dati["version"]), manifest))
    if not trovati:
        return Controllo(
            "plugin_codex", "errore", "plugin StarkEno non trovato nella cache Codex",
        )
    trovati.sort(key=lambda elemento: (elemento[0], str(elemento[1])))
    versione, manifest = trovati[-1]
    return Controllo(
        "plugin_codex", "ok", "plugin StarkEno presente",
        {"versione": versione, "manifest": str(manifest)},
    )


def _controllo_python() -> Controllo:
    versione = sys.version_info[:2]
    supportata = (3, 12) <= versione < (3, 15)
    return Controllo(
        "python", "ok" if supportata else "errore",
        "Python %d.%d%s" % (
            versione[0], versione[1], " supportato" if supportata else " non supportato",
        ),
        {"versione": "%d.%d" % versione},
    )


def _controllo_dipendenze() -> Controllo:
    richieste = ("fastapi", "uvicorn", "mcp", "sqlalchemy", "alembic", "httpx")
    mancanti = []
    versioni = {}
    for nome in richieste:
        try:
            versioni[nome] = metadata.version(nome)
        except metadata.PackageNotFoundError:
            mancanti.append(nome)
    if mancanti:
        return Controllo(
            "dipendenze", "errore", "dipendenze mancanti: " + ", ".join(mancanti),
            {"mancanti": mancanti},
        )
    return Controllo("dipendenze", "ok", "dipendenze runtime presenti", versioni)


def _controllo_bundle(plugin_root: Path) -> Controllo:
    manifest = Path(plugin_root) / ".codex-plugin" / "plugin.json"
    try:
        dati = json.loads(manifest.read_text(encoding="utf-8"))
        riferimento_hook = dati["hooks"]
        hooks = Path(plugin_root) / riferimento_hook
        json.loads(hooks.read_text(encoding="utf-8"))
    except (OSError, KeyError, ValueError, TypeError):
        return Controllo("bundle_plugin", "errore", "manifest o hook del plugin invalidi")
    return Controllo(
        "bundle_plugin", "ok", "manifest e hook del plugin validi",
        {"versione": str(dati.get("version", ""))},
    )


def _controllo_round_trip() -> Controllo:
    """Prova migrazione, scrittura e lettura su un database usa-e-getta."""
    from starkeno import db
    from starkeno.migrazioni import upgrade_head

    try:
        with TemporaryDirectory(prefix="starkeno-doctor-") as temporanea:
            percorso = Path(temporanea) / "round-trip.db"
            upgrade_head(percorso, silenzioso=True)
            fabbrica = db.make_session_factory(str(percorso))
            sessione = fabbrica()
            try:
                db.record_action(
                    sessione,
                    project="doctor",
                    action="round_trip",
                    model_used="diagnostica",
                    tokens_used=1,
                )
                righe = db.conta_chiamate(sessione)
            finally:
                sessione.close()
                fabbrica.kw["bind"].dispose()
            stato = ispeziona_database(percorso)
            if not stato.integro or stato.revisione != revisione_head() or righe != 1:
                return Controllo(
                    "round_trip", "errore", "round-trip isolato incompleto",
                )
            return Controllo(
                "round_trip", "ok", "round-trip isolato riuscito",
                {"righe": righe, "revisione": stato.revisione},
            )
    except Exception as errore:
        return Controllo(
            "round_trip", "errore", "round-trip isolato fallito",
            {"errore": type(errore).__name__},
        )


def _timestamp_utc(valore: str) -> datetime:
    letto = datetime.fromisoformat(valore)
    if letto.tzinfo is not None:
        return letto.astimezone(timezone.utc)
    return datetime(
        letto.year, letto.month, letto.day, letto.hour, letto.minute, letto.second,
        letto.microsecond, tzinfo=timezone.utc,
    )


def esegui_diagnosi(
    *, db_path: Path, codex_root: Path, plugin_root: Path, now: datetime,
) -> tuple[Controllo, ...]:
    """Compone controlli distinti: un fallimento non si traveste da salute."""
    candidato = ispeziona_database(Path(db_path))
    if candidato.integro:
        database = Controllo(
            "database", "ok", "database integro",
            {"righe": candidato.righe or 0, "ultimo_evento": candidato.ultimo_evento},
        )
        schema = Controllo(
            "schema", "ok" if candidato.revisione == revisione_head() else "errore",
            "schema a head" if candidato.revisione == revisione_head()
            else "schema disallineato",
            {"trovata": candidato.revisione, "attesa": revisione_head()},
        )
    else:
        database = Controllo(
            "database", "errore", candidato.errore or "database non integro",
        )
        schema = Controllo("schema", "errore", "schema non verificabile")

    plugin = trova_plugin_codex(Path(codex_root))
    if plugin.stato == "ok":
        trust = Controllo(
            "hook_trust", "manuale",
            "verifica SessionStart e Stop con /hooks in una nuova sessione",
        )
    else:
        trust = Controllo(
            "hook_trust", "errore", "installa il plugin prima di approvare gli hook",
        )

    if not candidato.integro or not candidato.ultimo_evento:
        raccolta = Controllo("raccolta", "errore", "nessun evento raccolto")
    else:
        ultimo = _timestamp_utc(candidato.ultimo_evento)
        recente = timedelta(0) <= now.astimezone(timezone.utc) - ultimo <= timedelta(days=7)
        raccolta = Controllo(
            "raccolta", "ok" if recente else "errore",
            "raccolta recente" if recente else "raccolta non recente o nel futuro",
            {"ultimo_evento": candidato.ultimo_evento},
        )

    return (
        _controllo_python(), _controllo_dipendenze(), _controllo_bundle(plugin_root),
        _controllo_round_trip(), database, schema, plugin, trust, raccolta,
    )
