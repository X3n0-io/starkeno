"""Il pacchetto installabile deve rispettare il contratto degli hook Codex."""
import json
from pathlib import Path

import starkeno


RADICE = Path(__file__).resolve().parent.parent


def _configurazione_hook(evento: str):
    dichiarazione = json.loads(
        (RADICE / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )
    (gruppo,) = dichiarazione["hooks"][evento]
    (hook,) = gruppo["hooks"]
    return gruppo, hook


def test_manifest_codex_ha_shape_completa_e_punta_agli_hook():
    manifest = json.loads(
        (RADICE / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    assert manifest["name"] == "starkeno"
    assert manifest["description"]
    assert manifest["version"]
    assert manifest["hooks"] == "./hooks/hooks.json"
    assert manifest["license"] == "MIT"
    assert manifest["author"]["name"]
    assert not (RADICE / ".claude-plugin" / "plugin.json").exists()


def test_manifest_version_matches_python_package():
    manifest = json.loads(
        (RADICE / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    assert manifest["version"] == starkeno.__version__ == "0.3.2"


def test_repo_marketplace_exposes_the_root_plugin():
    catalogo = json.loads(
        (RADICE / ".agents" / "plugins" / "marketplace.json").read_text(
            encoding="utf-8"
        )
    )
    (voce,) = catalogo["plugins"]

    assert catalogo["name"] == "starkeno-local"
    assert voce["name"] == "starkeno"
    assert voce["source"] == {"source": "local", "path": "./"}
    assert voce["policy"] == {
        "installation": "AVAILABLE", "authentication": "ON_INSTALL",
    }
    assert voce["category"] == "Productivity"
    assert (
        RADICE / voce["source"]["path"] / ".codex-plugin" / "plugin.json"
    ).is_file()


def test_session_start_e_stop_compatibile_puntano_a_script_esistenti():
    gruppo_start, start = _configurazione_hook("SessionStart")
    _gruppo_stop, stop = _configurazione_hook("Stop")

    assert gruppo_start["matcher"] == "startup"
    assert start["type"] == stop["type"] == "command"
    assert start["async"] is False
    assert "async" not in stop, (
        "Codex 0.147 salta gli hook dichiarati async prima della revisione"
    )
    assert 0 < start["timeout"] <= 10
    assert stop["timeout"] == 5

    for hook, script in (
        (start, "starkeno/hook_inizio_sessione.py"),
        (stop, "starkeno/hook_avvia_ingestione.py"),
    ):
        assert hook["command"].startswith("python ")
        assert "${PLUGIN_ROOT}" in hook["command"]
        assert hook["command"].replace("\\", "/").rstrip('"').endswith(script)
        assert hook["commandWindows"].startswith("python ")
        assert "%PLUGIN_ROOT%" in hook["commandWindows"]
        assert hook["commandWindows"].replace("\\", "/").rstrip('"').endswith(script)
        assert (RADICE / script).is_file()


def test_configurazione_runtime_non_dipende_da_variabili_claude():
    contenuto = (RADICE / "hooks" / "hooks.json").read_text(encoding="utf-8")

    assert "CLAUDE_PLUGIN_ROOT" not in contenuto
    assert "PLUGIN_ROOT" in contenuto


def test_readme_documenta_fase_2_e_comportamento_reale_di_codex():
    readme = (RADICE / "README.md").read_text(encoding="utf-8")

    assert "Claude Code" not in readme
    assert "Fase 2" in readme
    assert "starkeno report" in readme
    assert "starkeno doctor" in readme
    assert "/plugins" in readme
    assert "/hooks" in readme
    assert "SessionStart" in readme and "sincrono" in readme
    assert "Stop" in readme and "background" in readme
    assert "modello" in readme and "riga" in readme
