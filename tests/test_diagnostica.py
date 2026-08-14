import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from starkeno.diagnostica import (
    _controllo_round_trip,
    esegui_diagnosi,
    ispeziona_database,
    trova_plugin_codex,
)
from starkeno.migrazioni import revisione_head, upgrade_head
from starkeno import risorse


ORA = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _inserisci_azione(path: Path, timestamp="2026-08-12 10:00:00"):
    # `closing(...)` chiude, `conn` governa la transazione: il solo
    # `with sqlite3.connect(...)` fa commit ma NON chiude.
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO agent_actions"
            "(project, action, model_used, tokens_used, timestamp, session_id, message_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("progetto", "read:app.py", "gpt-5", 100, timestamp, "s1", "m1"),
        )


def _plugin_minimo(root: Path, *, versione="0.3.0") -> Path:
    manifest = root / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "name": "starkeno", "version": versione,
        "hooks": "./hooks/hooks.json",
    }), encoding="utf-8")
    hooks = root / "hooks" / "hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text('{"hooks": {}}', encoding="utf-8")
    return root


def test_missing_database_is_reported_without_being_created(tmp_path):
    path = tmp_path / "non-esiste" / "starkeno.db"

    esito = ispeziona_database(path)

    assert esito.integro is False
    assert esito.errore == "database_assente"
    assert not path.exists()


def test_database_inspection_reports_integrity_revision_rows_and_freshness(tmp_path):
    path = tmp_path / "starkeno.db"
    upgrade_head(path, silenzioso=True)
    _inserisci_azione(path)

    esito = ispeziona_database(path)

    assert (esito.integro, esito.revisione, esito.righe) == (
        True, revisione_head(), 1,
    )
    assert esito.ultimo_evento == "2026-08-12 10:00:00"
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()


def test_a_corrupt_database_is_not_reported_as_empty(tmp_path):
    path = tmp_path / "rotto.db"
    path.write_bytes(b"non e sqlite")

    esito = ispeziona_database(path)

    assert esito.integro is False
    assert esito.errore == "database_illeggibile"
    assert esito.righe is None


def test_codex_plugin_is_found_in_the_official_cache_layout(tmp_path):
    root = tmp_path / "plugins" / "cache" / "starkeno-local" / "starkeno" / "local"
    _plugin_minimo(root)

    esito = trova_plugin_codex(tmp_path)

    assert esito.stato == "ok"
    assert esito.dati["versione"] == "0.3.0"


def test_codex_plugin_absence_is_explicit(tmp_path):
    esito = trova_plugin_codex(tmp_path)

    assert esito.stato == "errore"
    assert esito.codice == "plugin_codex"


def test_plugin_root_prefers_source_and_falls_back_to_the_bundle(tmp_path, monkeypatch):
    sorgente = _plugin_minimo(tmp_path / "sorgente", versione="0.3.0")
    bundle = _plugin_minimo(tmp_path / "bundle", versione="0.3.0")
    monkeypatch.setattr(risorse, "_radice_sorgente", lambda: sorgente)
    monkeypatch.setattr(risorse, "_radice_pacchetto", lambda: bundle)

    assert risorse.plugin_root() == sorgente

    (sorgente / ".codex-plugin" / "plugin.json").unlink()
    assert risorse.plugin_root() == bundle


def test_diagnosis_separates_installed_plugin_manual_trust_and_fresh_collection(tmp_path):
    database = tmp_path / "dati" / "starkeno.db"
    database.parent.mkdir()
    upgrade_head(database, silenzioso=True)
    _inserisci_azione(database)
    plugin = _plugin_minimo(tmp_path / "plugin")
    cache = tmp_path / "codex" / "plugins" / "cache" / "locale" / "starkeno" / "local"
    _plugin_minimo(cache)

    controlli = esegui_diagnosi(
        db_path=database, codex_root=tmp_path / "codex", plugin_root=plugin, now=ORA,
        home=tmp_path / "home",
    )
    per_codice = {controllo.codice: controllo for controllo in controlli}

    assert per_codice["database"].stato == "ok"
    assert per_codice["schema"].stato == "ok"
    assert per_codice["plugin_codex"].stato == "ok"
    assert per_codice["hook_trust"].stato == "manuale"
    assert per_codice["raccolta"].stato == "ok"


def test_stale_collection_is_not_reported_as_healthy(tmp_path):
    database = tmp_path / "starkeno.db"
    upgrade_head(database, silenzioso=True)
    _inserisci_azione(database, timestamp="2026-07-01 10:00:00")
    plugin = _plugin_minimo(tmp_path / "plugin")

    controlli = esegui_diagnosi(
        db_path=database, codex_root=tmp_path / "codex", plugin_root=plugin, now=ORA,
        home=tmp_path / "home",
    )
    raccolta = next(c for c in controlli if c.codice == "raccolta")

    assert raccolta.stato == "errore"
    assert "non recente" in raccolta.dettaglio


def test_antigravity_rilevato_e_dichiarato_non_misurabile(tmp_path):
    """Zero chiamate senza spiegazione e' indistinguibile da un difetto."""
    from starkeno import diagnostica

    (tmp_path / ".gemini" / "antigravity").mkdir(parents=True)

    rilevati = dict((n, (m, r)) for n, m, r in diagnostica.harness_rilevati(tmp_path))

    assert "antigravity" in rilevati, "installato e non rilevato"
    misurabile, motivo = rilevati["antigravity"]
    assert misurabile is False
    assert "token" in motivo.lower(), "non dice PERCHE' non e' misurabile"


def test_un_harness_assente_non_viene_riportato(tmp_path):
    from starkeno import diagnostica

    assert diagnostica.harness_rilevati(tmp_path) == []


def test_isolated_round_trip_creates_writes_and_reads_only_a_temporary_database():
    controllo = _controllo_round_trip()

    assert controllo.codice == "round_trip"
    assert controllo.stato == "ok"
    assert controllo.dati == {"righe": 1, "revisione": revisione_head()}
