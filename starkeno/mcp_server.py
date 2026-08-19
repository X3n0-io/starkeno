from pathlib import Path

from mcp.server import MCPServer

import starkeno.db as db
from starkeno.config import DB_PATH, MAX_PLAUSIBLE_TOKENS, TOKEN_COST_WEIGHTS
from starkeno.db import make_session_factory, normalizza_progetto, record_action
from starkeno.preflight_interpret import interpretation_task, read_interpretation
from starkeno.preflight_service import (
    BlueprintInputError,
    validate_stored_analysis,
    write_blueprint_atomic,
)
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


def _dentro_la_radice(percorso: str) -> tuple[Path | None, Path, Path]:
    """Risolve `percorso` e dice se sta dentro la working directory del server.

    `Path.resolve()` normalizza sia i `..` sia i symlink, quindi il confronto va fatto
    DOPO la risoluzione — mai sulla stringa grezza, che i `..` la aggirerebbero.
    """
    radice = Path.cwd().resolve()
    risolto = Path(percorso).resolve()
    if not risolto.is_relative_to(radice):
        return None, risolto, radice
    return risolto, risolto, radice


def _confina_output_path(output_path: str) -> tuple[Path | None, str]:
    """Come sopra, per una SCRITTURA. Il messaggio dice che non e' stato scritto nulla."""
    dentro, risolto, radice = _dentro_la_radice(output_path)
    if dentro is None:
        return None, (
            f"Path error, nothing was written: `output_path` ({output_path}) resolves to "
            f"{risolto}, which is outside the server's working directory ({radice}).\n"
            "Pass an `output_path` that resolves inside the working directory — a relative "
            "path, or an absolute path already under it — and call preflight_save_draft "
            "again."
        )
    return dentro, ""


def _confina_input_path(input_path: str) -> tuple[Path | None, str]:
    """Come sopra, per una LETTURA. Il percorso lo sceglie l'agente anche qui."""
    dentro, risolto, radice = _dentro_la_radice(input_path)
    if dentro is None:
        return None, (
            f"Path error, nothing was read: ({input_path}) resolves to {risolto}, which "
            f"is outside the server's working directory ({radice}).\n"
            "Pass a path that resolves inside the working directory and call again."
        )
    return dentro, ""


def preflight_save_draft_impl(
    interpretation_json: str, output_path: str, format: str = "json",
    overwrite: bool = False,
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

    risolto, errore_percorso = _confina_output_path(output_path)
    if risolto is None:
        return errore_percorso

    if risolto.exists() and not overwrite:
        return (
            f"Write error, nothing was written: {risolto} already exists.\n"
            "Call preflight_save_draft again with overwrite=True to replace it on "
            "purpose, or choose a different `output_path`."
        )

    try:
        written = write_blueprint_atomic(
            interpretation.blueprint, risolto, format=format, source_path=None
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
    interpretation_json: str, output_path: str, format: str = "json",
    overwrite: bool = False,
) -> str:
    """Validate an Interpretation JSON and save the Draft Blueprint it contains.

    `interpretation_json` is the JSON YOU produced from the task returned by
    `preflight_interpretation_task` — one object with `blueprint`, `assumptions` and
    `open_questions`. `format` is "json" or "yaml" and defaults to "json".

    WRITES ARE CONFINED to the server's current working directory. `output_path` is
    resolved (`..` and symlinks included) and the result MUST land inside that
    working directory — pass a relative path, or an absolute path that already lives
    under it. Anything that resolves outside — via `..` or via an absolute path
    elsewhere — is rejected and nothing is written.

    An EXISTING file at the resolved `output_path` is never overwritten silently: by
    default the call is rejected and the file on disk is left byte-for-byte
    untouched. Pass `overwrite=True` only when you deliberately intend to replace it.

    On success, the returned text confirms the path written, lists the assumptions
    and open questions you recorded, and states that the Draft is NOT confirmed: a
    later `starkeno preflight analyze` still needs the literal --confirmed flag.

    On failure THIS TOOL DOES NOT RAISE. It returns the validation, path-confinement
    or existing-file error as plain text instead, and writes nothing. Read the
    message, fix the offending argument yourself (`interpretation_json`,
    `output_path` or `overwrite`), and call preflight_save_draft again — do not ask
    the user to fix it, do not resend the same arguments unchanged, and do not
    fabricate a Blueprint the original text does not support.
    """
    return preflight_save_draft_impl(interpretation_json, output_path, format, overwrite)


# ========================================================== il consuntivo di un'esecuzione
#
# Questi tre tool TOCCANO il database, e non e' un'incoerenza con i due Preflight qui
# sopra: sono OSSERVAZIONE, non predizione, e stanno accanto a `log_agent_action`.
#
# Non sono fail-open come gli hook, ed e' deliberato. Un hook silenzioso protegge il
# turno dell'utente; un marcatore perso in silenzio produce un'attribuzione SBAGLIATA,
# che e' il danno peggiore di tutti. Qui un errore si dichiara — come testo, mai come
# eccezione.


def _carica_analisi(percorso: Path):
    """Legge il preventivo da file e delega la validazione a
    `preflight_service.validate_stored_analysis`."""
    testo = percorso.read_text(encoding="utf-8")
    return validate_stored_analysis(testo)


def _mappa_modelli(model_map: str | None) -> tuple[dict | None, str]:
    """Il `model_map` come dizionario, oppure `(None, errore)` da restituire al chiamante.

    UNA copia sola, e non e' pignoleria: due copie della stessa regola scritte in due
    task diversi sono gia' divergute una volta su questo ramo, producendo un `KeyError`
    che e' uscito da un tool documentato come «non solleva mai». `blueprint_run_start` e
    `blueprint_run_end` devono accettare e rifiutare gli stessi input, con lo stesso
    testo, oggi e dopo la prossima modifica.

    `None`/vuoto vale come mappa vuota: e' il chiamante a decidere se questo significa
    «nessuna mappatura» (start) o «non aggiornare quella esistente» (end).
    """
    import json as _json

    try:
        mappa = _json.loads(model_map) if model_map else {}
        if not isinstance(mappa, dict):
            raise ValueError("model_map deve essere un oggetto JSON")
    except ValueError as errore_mappa:
        return None, "model_map error, nothing was recorded: %s" % errore_mappa
    return mappa, ""


def blueprint_run_start_impl(analysis_path: str, project: str,
                             model_map: str | None = None) -> str:
    import json as _json
    import uuid
    from datetime import datetime, timezone

    percorso, errore = _confina_input_path(analysis_path)
    if percorso is None:
        return errore
    try:
        testo, _blueprint, simulazione = _carica_analisi(percorso)
    except (OSError, ValueError, UnicodeError) as errore_analisi:
        motivo = " ".join(str(errore_analisi).splitlines())
        return (
            "Analysis error, nothing was recorded: " + motivo + "\n"
            "Produce the analysis with `starkeno preflight analyze --confirmed "
            "--format json` and call blueprint_run_start again with its path."
        )
    mappa, errore_mappa = _mappa_modelli(model_map)
    if mappa is None:
        return errore_mappa

    session = get_session_factory()()
    try:
        aperta = db.esecuzione_aperta(session, project)
        if aperta is not None:
            return (
                "Run error, nothing was recorded: c'e' gia' un'esecuzione aperta su "
                "questo progetto (run_key: %s, aperta il %s).\n"
                "Chiudila con blueprint_run_end prima di aprirne un'altra: "
                "un'esecuzione dimenticata aperta si prende ogni chiamata successiva "
                "del progetto." % (aperta.run_key, aperta.started_at.isoformat())
            )
        run = db.apri_esecuzione(
            session, run_key=uuid.uuid4().hex, project=project,
            blueprint_hash=simulazione.blueprint_hash, analysis_json=testo,
            model_map_json=_json.dumps(mappa), started_at=datetime.now(timezone.utc),
        )
        return (
            "Esecuzione aperta — run_key: %s\n"
            "Dichiara ogni cambio di nodo con blueprint_run_node, e chiudi con "
            "blueprint_run_end. Le chiamate fuori da un intervallo dichiarato "
            "risulteranno non attribuite invece di essere indovinate." % run.run_key
        )
    finally:
        session.close()


def blueprint_run_node_impl(run_key: str, node_id: str) -> str:
    from datetime import datetime, timezone

    session = get_session_factory()()
    try:
        run = db.leggi_esecuzione(session, run_key)
        if run is None:
            return "Run error, nothing was recorded: run_key sconosciuta (%s)." % run_key
        if run.ended_at is not None:
            return (
                "Run error, nothing was recorded: l'esecuzione %s e' gia' chiusa (%s)."
                % (run_key, run.ended_at.isoformat())
            )
        try:
            # `analysis_json` e' il preventivo conservato verbatim: si rilegge con la
            # STESSA validazione di `_carica_analisi` e della CLI (`consuntivo`), mai con
            # una copia locale che possa divergere di nuovo.
            _testo, blueprint, _simulazione = validate_stored_analysis(run.analysis_json)
        except ValueError as errore:
            return "Run error, nothing was recorded: %s" % errore
        validi = tuple(nodo.id for nodo in blueprint.nodes)
        if node_id not in validi:
            return (
                "Node error, nothing was recorded: '%s' non e' un nodo di questo "
                "Blueprint. Nodi validi: %s." % (node_id, ", ".join(validi))
            )
        db.aggiungi_marcatore(
            session, run, node_id=node_id, declared_at=datetime.now(timezone.utc)
        )
        return "Nodo corrente: %s (esecuzione %s)." % (node_id, run_key)
    finally:
        session.close()


def blueprint_run_end_impl(run_key: str, model_map: str | None = None) -> str:
    import json as _json
    from datetime import datetime, timezone

    from starkeno import consuntivo as consuntivo_modulo

    session = get_session_factory()()
    try:
        run = db.leggi_esecuzione(session, run_key)
        if run is None:
            return "Run error, nothing was recorded: run_key sconosciuta (%s)." % run_key
        # La mappatura si aggiorna ANCHE su un'esecuzione gia' chiusa: e' il ciclo
        # utile. Il primo confronto elenca i modelli non mappati, tu li dichiari, e
        # richiami questo tool per ricalcolare. L'attribuzione e' una vista: ricalcolarla
        # non tocca nessuna riga raccolta.
        mappa_json = None
        if model_map:
            mappa, errore_mappa = _mappa_modelli(model_map)
            if mappa is None:
                return errore_mappa
            mappa_json = _json.dumps(mappa)

        if run.ended_at is None:
            try:
                db.chiudi_esecuzione(
                    session, run, ended_at=datetime.now(timezone.utc),
                    model_map_json=mappa_json,
                )
            except ValueError as errore:
                return "Run error, nothing was recorded: %s" % errore
        elif mappa_json is not None:
            db.aggiorna_mappatura(session, run, model_map_json=mappa_json)

        try:
            # Stessa validazione della CLI (`consuntivo`) e di `_carica_analisi`: una
            # sola, mai una copia locale che possa divergere di nuovo.
            _testo, blueprint, simulazione = validate_stored_analysis(run.analysis_json)
        except ValueError as errore:
            return "Run error, nothing was recorded: %s" % errore
        esecuzione = db.esecuzione_snapshot(run)
        righe = db.righe_nella_finestra(
            session, run.project, run.started_at, run.ended_at
        )
        attribuzione = consuntivo_modulo.attribuisci(
            esecuzione, db.marcatori_di(session, run), righe
        )
        # `consuntivo.py` e' puro e non legge `config`: le guardie di qualita' dati di
        # `rules.effective_tokens` gliele passa questa porta, come fa `cli.py`.
        return consuntivo_modulo.rendi_testo(consuntivo_modulo.costruisci(
            esecuzione, attribuzione, simulazione, blueprint,
            weights=TOKEN_COST_WEIGHTS, max_plausible=MAX_PLAUSIBLE_TOKENS,
        ))
    finally:
        session.close()


@mcp.tool()
def blueprint_run_start(analysis_path: str, project: str,
                        model_map: str | None = None) -> str:
    """Open a Blueprint run and return its `run_key`.

    `analysis_path` is the JSON analysis produced by `starkeno preflight analyze
    --confirmed --format json`. It is stored verbatim: the run is compared against the
    estimate you were actually shown, not one recomputed later.

    READS ARE CONFINED to the server's current working directory, `..` and symlinks
    resolved first. `project` must be the last path segment of the working directory
    the agent is running in — it is how collected calls are matched.

    `model_map` is an optional JSON object mapping the OBSERVED model name to a
    `models[].id` of the Blueprint, e.g. `{"claude-opus-4": "opus"}`. Without it the
    comparison still counts tokens and declares the money unknown; it never guesses.

    THIS TOOL DOES NOT RAISE. Errors — an analysis that will not load, a path outside
    the working directory, a run already open on this project — come back as plain
    text and nothing is recorded. Read the message, fix the argument yourself and call
    again.
    """
    return blueprint_run_start_impl(analysis_path, project, model_map)


@mcp.tool()
def blueprint_run_node(run_key: str, node_id: str) -> str:
    """Declare that work is moving to node `node_id` of the running Blueprint.

    Call this EVERY time you start working on a different node. Calls that fall
    outside any declared interval are reported as unattributed rather than assigned to
    a neighbouring node: a number attributed to the wrong node is worse than one left
    unattributed, because it sends the calibration in the wrong direction.

    `node_id` is validated against the Blueprint stored with the run. An unknown id is
    rejected and the message lists the valid ones.

    THIS TOOL DOES NOT RAISE. Errors come back as plain text and nothing is recorded.
    """
    return blueprint_run_node_impl(run_key, node_id)


@mcp.tool()
def blueprint_run_end(run_key: str, model_map: str | None = None) -> str:
    """Close the run and return the comparison between the estimate and what was spent.

    `model_map` REPLACES the one given at `blueprint_run_start` when provided; omit it
    to leave the existing one unchanged.

    The returned text states where the observed total falls inside the estimated band,
    the per-node deltas ordered by size, and what it refuses to attribute and why.
    Estimated node invocations and observed API calls are printed side by side and
    never subtracted: they are different units.

    EXPECT THE FIRST COMPARISON TO BE SHORT OR EMPTY. You call this DURING a turn,
    but the rows of that turn are written by the `Stop` hook AFTER the turn ends: the
    calls you just made — often the biggest — are not in the database yet, so the
    comparison may say `senza_osservazioni` or report a total that is too low. That is
    timing, not a failure. Run `starkeno consuntivo --run <run_key>` later, or call
    this tool again, and the same comparison is recomputed over the rows that have
    arrived in the meantime.

    Calling it again on an already closed run recomputes the comparison without
    changing anything — attribution is a view, not a stamp on the collected rows.

    THIS TOOL DOES NOT RAISE. Errors come back as plain text.
    """
    return blueprint_run_end_impl(run_key, model_map)


if __name__ == "__main__":
    # Controllo di versione dello schema PRIMA di accettare qualsiasi connessione.
    # E' l'unico punto del sistema dove e' giusto fallire rumorosamente (§7): partire
    # con uno schema disallineato significa `no such column` inghiottiti dai try/except
    # e un supervisore che produce zero alert restando identico a una flotta sana.
    check_or_die(get_session_factory().kw["bind"])

    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, streamable_http_path="/mcp")
