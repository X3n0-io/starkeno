"""Il bundle Claude Code e' separato da quello Codex, e non puo' non esserlo.

Misurato il 15/08/2026 installando un plugin locale usa-e-getta: Claude Code **copia**
la cartella del plugin in `~/.claude/plugins/cache/<marketplace>/<plugin>/<versione>/` e
copia soltanto quella. Il marketplace resta referenziato dov'e', il plugin no.

Da qui discende tutto il resto:

1. `${CLAUDE_PLUGIN_ROOT}/../starkeno/...` non risolve, perche' nella cache non c'e'
   nessun `starkeno/`. E fallirebbe nel modo peggiore: gli hook escono 0 e tacciono, e
   l'utente vedrebbe zero righe senza sapere perche' (vedi il commento misurato in
   `hook_ingestione.py`).
2. Gli hook si invocano quindi per modulo, non per percorso: `python -m starkeno.<hook>`
   non dipende dalla radice del plugin e usa i due prerequisiti che il README gia'
   impone — Python sul PATH e il pacchetto installato.
3. Il manifest NON dichiara `hooks`: Claude Code scopre `hooks/hooks.json` per
   convenzione e i percorsi del manifest si SOMMANO a quelli scoperti invece di
   sostituirli, quindi dichiarare il percorso predefinito rischia di registrare gli hook
   due volte. Nessuno dei plugin ufficiali lo dichiara.
"""
import json
from pathlib import Path

import starkeno


RADICE = Path(__file__).resolve().parent.parent
BUNDLE = RADICE / "plugin-claude-code"


def _manifest() -> dict:
    return json.loads(
        (BUNDLE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )


def _hooks() -> dict:
    return json.loads(
        (BUNDLE / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )


def test_il_manifest_claude_code_esiste_ed_e_completo():
    manifest = _manifest()

    assert manifest["name"] == "starkeno"
    assert manifest["description"]
    assert manifest["license"] == "MIT"
    assert manifest["author"]["name"]


def test_i_due_manifest_dichiarano_la_stessa_versione():
    """Due manifest che divergono in versione sono due plugin diversi con lo stesso
    nome."""
    codex = json.loads(
        (RADICE / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    assert _manifest()["version"] == codex["version"] == starkeno.__version__


def test_il_manifest_claude_non_dichiara_gli_hook():
    """Il percorso predefinito si SOMMA a quello dichiarato: dichiararlo li registra
    due volte, e un hook di fine turno eseguito due volte lo paga l'utente."""
    assert "hooks" not in _manifest()
    assert (BUNDLE / "hooks" / "hooks.json").is_file(), "scoperto per convenzione"


def test_gli_hook_claude_non_dipendono_dalla_radice_del_plugin():
    """LA regressione di questo task. Claude Code copia il bundle nella cache: qualunque
    percorso relativo alla radice del plugin non trova `starkeno/`, e tace."""
    contenuto = (BUNDLE / "hooks" / "hooks.json").read_text(encoding="utf-8")

    assert "PLUGIN_ROOT" not in contenuto, (
        "un percorso relativo alla radice del plugin non risolve dopo la copia in cache"
    )
    assert ".." not in contenuto


def test_gli_hook_claude_invocano_moduli_che_esistono():
    hooks = _hooks()
    (gruppo_start,) = hooks["hooks"]["SessionStart"]
    (start,) = gruppo_start["hooks"]
    (gruppo_stop,) = hooks["hooks"]["Stop"]
    (stop,) = gruppo_stop["hooks"]

    assert gruppo_start["matcher"] == "startup"
    assert start["type"] == stop["type"] == "command"
    assert 0 < start["timeout"] <= 10 and 0 < stop["timeout"] <= 10

    for hook, modulo in (
        (start, "starkeno.hook_inizio_sessione"),
        (stop, "starkeno.hook_avvia_ingestione"),
    ):
        assert hook["command"] == "python -m " + modulo
        assert (RADICE / modulo.replace(".", "/")).with_suffix(".py").is_file()


def test_il_bundle_codex_resta_intatto():
    """Il bundle Codex non deve accorgersi dell'esistenza di quello Claude Code."""
    codex = (RADICE / "hooks" / "hooks.json").read_text(encoding="utf-8")

    assert "CLAUDE_PLUGIN_ROOT" not in codex
    assert "PLUGIN_ROOT" in codex
    assert not (RADICE / ".claude-plugin" / "plugin.json").exists(), (
        "un manifest Claude Code nella radice farebbe scoprire gli hook Codex a "
        "Claude Code, che non espande %s" % "PLUGIN_ROOT"
    )


def test_il_marketplace_espone_il_bundle_claude_code():
    """Senza marketplace il plugin non e' installabile, che e' lo scopo del task."""
    catalogo = json.loads(
        (RADICE / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    (voce,) = catalogo["plugins"]

    assert voce["name"] == "starkeno"
    assert voce["source"] == "./plugin-claude-code"
    assert (RADICE / voce["source"] / ".claude-plugin" / "plugin.json").is_file()
