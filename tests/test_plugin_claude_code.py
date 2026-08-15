"""Il bundle Claude Code e' separato da quello Codex, e non puo' non esserlo.

Misurato il 15/08/2026 installando il plugin e strumentando un hook vero.

1. Claude Code **copia** il plugin in `~/.claude/plugins/cache/<marketplace>/<plugin>/
   <versione>/`. Con un marketplace di tipo `directory` pero' `${CLAUDE_PLUGIN_ROOT}`
   risolve al SORGENTE, non alla copia: modificare la copia non cambia niente. Su
   un'installazione da git la copia sarebbe l'unica cosa presente, e li' non esiste
   nessun `starkeno/` accanto al bundle.
2. Gli hook si invocano quindi per modulo, non per percorso: `python -m starkeno.<hook>`
   vale in entrambi i casi e usa i due prerequisiti che il README gia' impone — Python
   sul PATH e il pacchetto installato. Verificato con una sonda dentro il bundle:
   l'interprete e' quello giusto, `import starkeno` riesce, e stdin arriva completo di
   `transcript_path`.
3. Il manifest NON dichiara `hooks`: Claude Code scopre `hooks/hooks.json` per
   convenzione e i percorsi del manifest si SOMMANO a quelli scoperti invece di
   sostituirli, quindi dichiarare il percorso predefinito rischia di registrare gli hook
   due volte. Nessuno dei plugin ufficiali lo dichiara.
4. Lo `Stop` e' SINCRONO e chiama l'ingestione DIRETTAMENTE. Le due varianti non
   bloccanti sono state provate su turni veri e **non hanno raccolto niente**:
   l'avviatore di Codex, che stacca un figlio e rientra in 354 ms mentre l'ingestione ne
   richiede 1600; e `async: true`, che rientra subito uguale. In entrambi i casi il
   processo non sopravvive, Claude Code registra l'hook come concluso senza errori, e
   arrivano **zero righe senza un solo segnale**. Con `async` Claude Code non raccoglie
   nemmeno l'esito, quindi `hookErrors: []` non vuol dire «e' andata bene», vuol dire
   «non lo so».

   Costa circa 1,6 s a fine turno, quando l'utente sta gia' leggendo la risposta. E' il
   prezzo dell'unica configurazione che raccoglie davvero, ed e' la stessa che usano gli
   hook `Stop` dei plugin ufficiali. Codex resta sull'avviatore: li' serve, e li'
   funziona.
5. C'e' anche un `SessionEnd`, e non e' ridondanza. Lo `Stop` di Claude Code scatta
   PRIMA che il turno sia sul disco: misurato, la chiamata portava timestamp 14:21:17,8
   e l'hook e' partito alle 14:21:18,7 leggendo un transcript che non la conteneva
   ancora. Rileggendo tutto a ogni giro, il turno N viene recuperato allo `Stop` del
   turno N+1 — ma l'ULTIMO turno di ogni sessione non avrebbe mai un giro successivo e
   si perderebbe per sempre. `SessionEnd` arriva a transcript chiuso e lo raccoglie.
   Sovrapporli non duplica niente: la scrittura e' idempotente sulla chiave
   `(session_id, message_id)`.
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

    for hook, modulo in (
        (start, "starkeno.hook_inizio_sessione"),
        (stop, "starkeno.hook_ingestione"),
    ):
        assert hook["command"] == "python -m " + modulo
        assert (RADICE / modulo.replace(".", "/")).with_suffix(".py").is_file()


def test_lo_stop_claude_e_sincrono_e_non_passa_dall_avviatore():
    """LA regressione misurata su turni veri: le due varianti non bloccanti — l'avviatore
    di Codex e `async: true` — raccolgono ZERO righe senza emettere un errore. Rendere
    di nuovo non bloccante questo hook significa spegnere la raccolta in silenzio."""
    (gruppo_stop,) = _hooks()["hooks"]["Stop"]
    (stop,) = gruppo_stop["hooks"]

    assert "hook_avvia_ingestione" not in stop["command"], (
        "l'avviatore serve a Codex, che blocca sull'hook; qui fa perdere la raccolta"
    )
    assert stop["async"] is False, (
        "provato: con async il processo non sopravvive e non arriva nessuna riga"
    )
    assert stop["timeout"] >= 30, "l'ingestione misurata dura circa 1,6 s"


def test_esiste_un_session_end_che_recupera_l_ultimo_turno():
    """Senza, l'ultimo turno di OGNI sessione si perde: lo Stop lo legge prima che sia
    scritto, e un turno successivo che lo recuperi non c'e'."""
    hooks = _hooks()["hooks"]
    assert "SessionEnd" in hooks, "l'ultimo turno di ogni sessione resterebbe fuori"

    (gruppo,) = hooks["SessionEnd"]
    (fine,) = gruppo["hooks"]
    (gruppo_stop,) = hooks["Stop"]
    (stop,) = gruppo_stop["hooks"]

    assert fine["command"] == stop["command"], (
        "deve ingerire, non fare qualcosa di diverso dallo Stop"
    )
    assert fine["async"] is False, "vale la stessa misura dello Stop"


def test_il_session_start_claude_resta_sincrono():
    """Inietta `additionalContext`: se non fosse sincrono, il contesto arriverebbe a
    turno gia' cominciato."""
    (gruppo_start,) = _hooks()["hooks"]["SessionStart"]
    (start,) = gruppo_start["hooks"]

    assert start["async"] is False
    assert 0 < start["timeout"] <= 10


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
