from pathlib import Path

from mcp.server import MCPServer

import starkeno.db as db
from starkeno.config import DB_PATH
from starkeno.db import make_session_factory, normalizza_progetto, record_action
from starkeno.preflight_interpret import interpretation_task, read_interpretation
from starkeno.preflight_service import BlueprintInputError, write_blueprint_atomic
from starkeno.schema_version import check_or_die

_session_factory = None


def get_session_factory():
    """Costruisce la session factory alla prima chiamata, non all'import.

    Farlo all'import significa che `import starkeno.mcp_server` apre (e, se manca,
    CREA) il database configurato. Verificato: bastava un `pytest` per ricreare il
    database di produzione con lo schema di create_all e senza `alembic_version`,
    lasciando la catena delle migrazioni rotta in partenza.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(DB_PATH)
    return _session_factory


mcp = MCPServer("StarkEno")


def _warning_per(session, project: str) -> str:
    """Il warning da accodare alla risposta, o stringa vuota.

    **Solo gli alert `open`, mai i `candidate.`** Un candidate e' una violazione ancora
    in osservazione che potrebbe sparire da sola prima della promozione: avvisarne
    l'agente significherebbe iniettare rumore — e token — dentro il suo loop per un
    problema che non e' ancora un problema. E' esattamente la classe di falsi positivi
    che la separazione fra percorso in linea e percorso periodico esiste per uccidere.

    La query passa dall'indice parziale `ix_alerts_open`. Misurato: e' un COVERING INDEX,
    non tocca mai la tabella.
    """
    aperti = db.get_open_alerts(session, project)
    if not aperti:
        return ""
    righe = "; ".join("%s: %s" % (a.rule, a.detail) for a in aperti)
    return "\n\n[StarkEno] Segnalazioni aperte su questo agente — %s" % righe


def log_agent_action_impl(project: str, action: str, model_used: str, tokens_used: int,
                          cache_read_tokens: int | None = None,
                          cache_write_tokens: int | None = None,
                          output_tokens: int | None = None) -> str:
    session = get_session_factory()()
    try:
        record_action(
            session,
            project=project,
            action=action,
            model_used=model_used,
            tokens_used=tokens_used,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            output_tokens=output_tokens,
        )
        risposta = (
            "Logged action '%s' for agent '%s' (%d tokens, model %s)"
            % (action, project, tokens_used, model_used)
        )

        # TUTTO cio' che il Supervisore aggiunge sta qui dentro. Un layer di
        # osservabilita' che rompe la cosa che osserva e' PEGGIO che inutile: si
        # perderebbero sia i dati sia il lavoro dell'agente. Se la lookup fallisce,
        # l'azione resta registrata e la risposta e' quella normale.
        try:
            risposta += _warning_per(session, normalizza_progetto(project))
        except Exception:                          # noqa: BLE001 — deliberato
            pass

        return risposta
    finally:
        session.close()


@mcp.tool()
def log_agent_action(project: str, action: str, model_used: str, tokens_used: int,
                     cache_read_tokens: int | None = None,
                     cache_write_tokens: int | None = None,
                     output_tokens: int | None = None) -> str:
    """Record an action taken by an AI agent, including which model it used and how many
    tokens it consumed.

    GRANULARITA' DI `action`
    ------------------------
    Usa `categoria:dettaglio` quando l'azione ha un oggetto:

        read_file:src/app.py        fetch:https://api.dev/utenti

    Con sole categorie il rilevamento dei loop non funziona: senza dettaglio, «100
    oggetti diversi» e «lo stesso oggetto 100 volte» sono la stessa identica stringa, e
    la regola si astiene invece di indovinare.

    Il rumore variabile va DOPO un `?`, dove viene rimosso:

        search:query?ts=1730992811       corretto
        search:query_1730992811          lo scambia per un oggetto nuovo

    `tokens_used`
    -------------
    Token TOTALI, cache read INCLUSI.

    SCOMPOSIZIONE — opzionale, ma o tutta o niente
    ----------------------------------------------
    Una dichiarazione parziale viene trattata come nessuna dichiarazione, quindi i tre
    campi vanno passati insieme:

        u = response.usage
        log_agent_action(
            ...,
            tokens_used        = (u.input_tokens + (u.cache_read_input_tokens or 0)
                                  + (u.cache_creation_input_tokens or 0) + u.output_tokens),
            cache_read_tokens  = u.cache_read_input_tokens or 0,
            cache_write_tokens = u.cache_creation_input_tokens or 0,
            output_tokens      = u.output_tokens,
        )

    Gli `or 0` non sono cosmetici: nell'SDK quei due campi sono Optional e valgono None
    su ogni chiamata che non tocca la cache.

    L'errore da non fare e' mettere i cache WRITE insieme ai read: costano piu'
    dell'input normale (1.25x), non meno (0.1x), e confonderli sottostima la spesa di
    oltre dieci volte — proprio sul caso caro.
    """
    return log_agent_action_impl(project, action, model_used, tokens_used,
                                 cache_read_tokens, cache_write_tokens, output_tokens)


# ======================================================= porta d'ingresso Preflight
#
# StarkEno non chiama alcun modello e non ha alcuna chiave: l'agente che l'utente sta
# gia' usando (Claude Code, Codex, ...) e' l'interprete. Questi due tool sono l'unico
# punto di contatto: il primo restituisce il compito, il secondo valida cio' che
# l'agente ha prodotto da solo. Ne' l'uno ne' l'altro tocca il database — Preflight e'
# offline, e chiamare `get_session_factory()` qui aprirebbe (e, se manca, creerebbe) il
# database configurato per un percorso che non ne ha alcun bisogno.


def preflight_interpretation_task_impl(text: str) -> str:
    return interpretation_task(text)


@mcp.tool()
def preflight_interpretation_task(text: str) -> str:
    """Return the task for turning free-text `text` into a Preflight Draft Blueprint.

    StarkEno calls no model and holds no API key for this: YOU are the interpreter.
    Read the rules and the JSON schema embedded in the returned task, then produce
    only a single JSON object that validates against that schema — no prose, no
    markdown code fences, nothing before or after it. Call `preflight_save_draft`
    with that JSON as `interpretation_json` next; do not show it to the user first
    and do not write the Blueprint file yourself.

    The returned string is a stable prefix for a given `text`: calling this twice
    with the same `text` returns byte-identical output, so it is safe to call again
    if you need the task text a second time.
    """
    return preflight_interpretation_task_impl(text)


def preflight_save_draft_impl(
    interpretation_json: str, output_path: str, format: str = "json"
) -> str:
    try:
        interpretation = read_interpretation(interpretation_json)
    except (ValueError, BlueprintInputError) as errore:
        motivo = " ".join(str(errore).splitlines())
        return (
            "Validation error, nothing was written: " + motivo + "\n"
            "Fix the JSON yourself using this message and call preflight_save_draft "
            "again with the corrected `interpretation_json`."
        )

    try:
        written = write_blueprint_atomic(
            interpretation.blueprint, Path(output_path), format=format, source_path=None
        )
    except (OSError, ValueError, BlueprintInputError) as errore:
        motivo = " ".join(str(errore).splitlines())
        return (
            "Write error, nothing was written: " + motivo + "\n"
            "Fix `output_path` or `format` and call preflight_save_draft again."
        )

    righe = [f"Draft salvato in {written}."]
    if interpretation.assumptions:
        righe.append("Assunzioni: " + "; ".join(interpretation.assumptions))
    if interpretation.open_questions:
        righe.append("Domande aperte: " + "; ".join(interpretation.open_questions))
    righe.append(
        "Il Draft non e' confermato: 'starkeno preflight analyze' richiede ancora "
        "il flag letterale --confirmed."
    )
    return "\n".join(righe)


@mcp.tool()
def preflight_save_draft(
    interpretation_json: str, output_path: str, format: str = "json"
) -> str:
    """Validate an Interpretation JSON and save the Draft Blueprint it contains.

    `interpretation_json` is the JSON YOU produced from the task returned by
    `preflight_interpretation_task` — one object with `blueprint`, `assumptions` and
    `open_questions`. `format` is "json" or "yaml" and defaults to "json".

    On success, the returned text confirms the path written, lists the assumptions
    and open questions you recorded, and states that the Draft is NOT confirmed: a
    later `starkeno preflight analyze` still needs the literal --confirmed flag.

    On failure THIS TOOL DOES NOT RAISE. It returns the validation error as plain
    text instead, and writes nothing. Read the message, fix the JSON yourself, and
    call preflight_save_draft again with the corrected `interpretation_json` — do
    not ask the user to fix it, do not resend the same JSON unchanged, and do not
    fabricate a Blueprint the original text does not support.
    """
    return preflight_save_draft_impl(interpretation_json, output_path, format)


if __name__ == "__main__":
    # Controllo di versione dello schema PRIMA di accettare qualsiasi connessione.
    # E' l'unico punto del sistema dove e' giusto fallire rumorosamente (§7): partire
    # con uno schema disallineato significa `no such column` inghiottiti dai try/except
    # e un supervisore che produce zero alert restando identico a una flotta sana.
    check_or_die(get_session_factory().kw["bind"])

    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, streamable_http_path="/mcp")
