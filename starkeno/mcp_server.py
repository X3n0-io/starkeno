from mcp.server import MCPServer

import starkeno.db as db
from starkeno.config import DB_PATH
from starkeno.db import make_session_factory, normalizza_progetto, record_action
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


if __name__ == "__main__":
    # Controllo di versione dello schema PRIMA di accettare qualsiasi connessione.
    # E' l'unico punto del sistema dove e' giusto fallire rumorosamente (§7): partire
    # con uno schema disallineato significa `no such column` inghiottiti dai try/except
    # e un supervisore che produce zero alert restando identico a una flotta sana.
    check_or_die(get_session_factory().kw["bind"])

    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, streamable_http_path="/mcp")
