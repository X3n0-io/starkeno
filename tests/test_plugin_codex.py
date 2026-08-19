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
    """Il letterale e' un FERMO, non una ridondanza: la versione e' anche il percorso
    di cache del plugin (`.../<plugin>/<versione>/`), quindi cambiarla e' come si
    consegna una modifica agli hook a chi ha gia' installato. Lasciarla ferma nasconde
    la correzione; cambiarla di riflesso la nasconde altrettanto. Il letterale obbliga
    a passare di qui apposta."""
    manifest = json.loads(
        (RADICE / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    assert manifest["version"] == starkeno.__version__ == "0.4.0"


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


def test_readme_documenta_il_comportamento_reale_degli_hook():
    """Il README e' in ITALIANO e nomina Claude Code.

    Prima vietava quel nome, ed era giusto: il plugin non esisteva. Il divieto e' caduto
    quando Claude Code e' diventato installabile e la raccolta e' stata verificata su
    turni veri.

    La lingua e' passata dall'inglese all'italiano il 19/08/2026, per coerenza con il
    conto: il prodotto parlava italiano e la vetrina inglese, e chi installava trovava
    un'interfaccia in una lingua che il README non aveva mai usato.
    """
    readme = (RADICE / "README.md").read_text(encoding="utf-8")

    assert "Fase 2" in readme
    assert "starkeno report" in readme
    assert "starkeno doctor" in readme
    assert "/plugins" in readme and "/hooks" in readme
    assert "SessionStart" in readme and "Stop" in readme
    assert "background" in readme, "l'avviatore non bloccante di Codex resta un fatto"


def test_il_readme_distingue_gli_hook_dei_due_harness():
    """I due harness NON hanno la stessa configurazione, e il README non deve lasciar
    credere il contrario: su Codex lo `Stop` e' un avviatore in background, su Claude
    Code e' sincrono perche' il processo staccato non sopravvive."""
    readme = (RADICE / "README.md").read_text(encoding="utf-8")

    assert "sincron" in readme.lower()
    assert "SessionEnd" in readme, (
        "senza SessionEnd l'ultimo turno di ogni sessione Claude Code si perde"
    )


# ==================================== la skill deve stare anche nella radice del repo
#
# I due harness montano radici di plugin DIVERSE dallo stesso repository:
# Claude Code monta `plugin-claude-code/` (`.claude-plugin/marketplace.json`), Codex
# monta la radice (`.agents/plugins/marketplace.json`, `path: "./"`). Una skill sotto la
# prima e' invisibile alla seconda, e nessun test lo diceva.


SKILL_CODEX = RADICE / "skills" / "starkeno" / "SKILL.md"
SKILL_CLAUDE = RADICE / "plugin-claude-code" / "skills" / "starkeno" / "SKILL.md"


def test_la_skill_esiste_anche_nella_radice_che_monta_codex():
    """LA regressione, misurata il 19/08/2026 chiedendo a Codex quanto avesse speso: la
    skill non e' partita. Era in `plugin-claude-code/skills/`, dove Codex non guarda."""
    assert SKILL_CODEX.is_file(), (
        "Codex monta la radice del repository: senza `skills/` qui non vede la skill"
    )


def test_le_due_copie_della_skill_restano_identiche():
    """La duplicazione e' FORZATA dalle due radici — la skill non puo' stare solo alla
    radice, perche' Claude Code monta `plugin-claude-code/` e non vede `../skills/` —
    ma questo progetto ha gia' pagato due volte per due copie della stessa regola che
    divergono (`effective_tokens`, il parsing di `model_map`).

    Qui la divergenza costerebbe in silenzio: due agenti con due idee diverse di quando
    invocare StarkEno, e nessuno dei due che se ne accorge. `read_text` normalizza i fine
    riga, quindi il confronto e' sul contenuto e non sul checkout.
    """
    assert SKILL_CODEX.read_text(encoding="utf-8") == \
        SKILL_CLAUDE.read_text(encoding="utf-8"), (
            "le due copie della skill sono divergute: allineale"
        )
