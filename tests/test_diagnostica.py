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


# ===================================== la copia installata puo' essere vecchia
#
# Misurato il 19/08/2026, ed e' costato quattro giorni di raccolta finita nel file
# sbagliato. Correggere il bundle nel repository NON aggiorna la copia che l'harness
# ha gia' installato: Claude Code la tiene in `plugins/cache/<mercato>/<plugin>/
# <versione>/` e il suo registro fissa quel percorso. Il repository e la macchina
# possono quindi divergere a tempo indefinito, e nessuno dei due lo dice, perche' gli
# hook sono muti per l'invariante 12.


def _copia_installata(claude_root: Path, comando: str) -> Path:
    """Una copia del bundle Claude Code nel layout di cache osservato."""
    percorso = (claude_root / "plugins" / "cache" / "mercato-locale"
                / "starkeno" / "0.3.2" / "hooks" / "hooks.json")
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": comando, "async": False, "timeout": 30}]}]}}),
        encoding="utf-8",
    )
    return percorso


def _bundle_spedito(radice: Path, comando: str) -> Path:
    percorso = radice / "plugin-claude-code" / "hooks" / "hooks.json"
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": comando, "async": False, "timeout": 30}]}]}},
            indent=2),
        encoding="utf-8",
    )
    return percorso


def test_il_doctor_vede_la_copia_installata_piu_vecchia_del_pacchetto(tmp_path):
    """LA regressione: il bundle corretto nel repository e la copia installata che
    esegue ancora il comando vecchio. E' esattamente lo stato in cui la macchina e'
    rimasta per quattro giorni raccogliendo nel database sbagliato."""
    from starkeno.diagnostica import confronta_plugin_claude

    claude = tmp_path / "home" / ".claude"
    installata = _copia_installata(claude, "python -m starkeno.hook_ingestione")
    _bundle_spedito(tmp_path / "pacchetto", "python -P -m starkeno.hook_ingestione")

    controllo = confronta_plugin_claude(claude, tmp_path / "pacchetto")

    assert controllo.stato == "attenzione", (
        "la copia installata esegue codice diverso da quello del pacchetto"
    )
    assert str(installata) in controllo.dati["copie_divergenti"], "non dice QUALE copia"


def test_una_copia_installata_allineata_non_allarma(tmp_path):
    """Il rovescio, e ha una regressione propria: il confronto e' STRUTTURALE, non
    testuale. Le due copie qui hanno lo stesso contenuto con indentazione diversa —
    e su Windows differiscono anche di fine riga, perche' una la scrive l'harness e
    l'altra esce da git. Un confronto fra stringhe direbbe `attenzione` a ogni
    installazione sana, e si imparerebbe a ignorarlo."""
    from starkeno.diagnostica import confronta_plugin_claude

    claude = tmp_path / "home" / ".claude"
    _copia_installata(claude, "python -P -m starkeno.hook_ingestione")
    _bundle_spedito(tmp_path / "pacchetto", "python -P -m starkeno.hook_ingestione")

    controllo = confronta_plugin_claude(claude, tmp_path / "pacchetto")

    assert controllo.stato == "ok", "stesso contenuto, sola indentazione diversa"


def test_senza_claude_code_il_controllo_tace(tmp_path):
    """Chi usa solo Codex non deve vedere un avviso su un harness che non ha."""
    from starkeno.diagnostica import confronta_plugin_claude

    _bundle_spedito(tmp_path / "pacchetto", "python -P -m starkeno.hook_ingestione")

    controllo = confronta_plugin_claude(tmp_path / "home" / ".claude", tmp_path / "pacchetto")

    assert controllo.stato == "ok"
