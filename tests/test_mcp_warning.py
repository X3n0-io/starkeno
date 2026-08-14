"""Task 10 — il warning in linea, e le difese su `project`.

`log_agent_action` e' l'operazione critica del sistema: e' dentro il loop di ogni agente
tracciato, e se rallenta o fallisce si perdono sia i dati sia il lavoro dell'agente.
Percio' il percorso in linea e' deliberatamente stupido — una sola lookup indicizzata,
nessuna valutazione di regole — e tutto quello che il Supervisore aggiunge sta dentro un
try/except.

**Solo `open`, mai `candidate`.** Se la lookup includesse i candidate, una raffica che si
risolve da sola (429 + retry, poi successo) avviserebbe l'agente fino a
PROMOTE_MIN_MINUTES prima di svanire, reintroducendo esattamente la classe di falsi
positivi che la separazione fra percorso in linea e periodico esiste per uccidere.
"""
from datetime import datetime, timezone

import pytest

import starkeno.mcp_server as mcp_server_module
from starkeno.db import AgentAction, get_agent_summaries, upsert_alert
from starkeno.mcp_server import log_agent_action_impl

ORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def logga(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_server_module, "get_session_factory", lambda: session_factory)
    return log_agent_action_impl


def apri_alert(session_factory, agente, *, status):
    session = session_factory()
    alert = upsert_alert(session, project=agente, rule="loop", detail="ciclo ripetuto",
                         evidence={}, last_seen=ORA, now=ORA)
    alert.status = status
    session.commit()
    session.close()


# ============================================================== il warning
def test_an_open_alert_adds_a_warning_to_the_response(logga, session_factory):
    apri_alert(session_factory, "scraper", status="open")

    risposta = logga(project="scraper", action="fetch:pagina",
                     model_used="claude-haiku-4-5", tokens_used=150)

    assert "ciclo ripetuto" in risposta
    assert "loop" in risposta


def test_a_candidate_alert_adds_no_warning(logga, session_factory):
    """**La distinzione che tiene in piedi la separazione in linea/periodico.**

    Un candidate e' una violazione ancora in osservazione: potrebbe sparire da sola prima
    della promozione. Avvisarne l'agente significherebbe iniettare rumore — e token —
    dentro il suo loop per un problema che non e' ancora un problema.
    """
    apri_alert(session_factory, "scraper", status="candidate")

    risposta = logga(project="scraper", action="fetch:pagina",
                     model_used="claude-haiku-4-5", tokens_used=150)

    assert "ciclo ripetuto" not in risposta
    assert "loop" not in risposta


def test_with_no_alert_the_response_is_byte_identical_to_v0(logga):
    """La v0 rispondeva con una frase precisa. Chi la parsa non deve accorgersi della v1."""
    risposta = logga(project="scraper", action="fetch_page",
                     model_used="claude-haiku-4-5", tokens_used=150)

    assert risposta == (
        "Logged action 'fetch_page' for agent 'scraper' (150 tokens, model claude-haiku-4-5)"
    )


def test_an_alert_for_another_agent_does_not_leak(logga, session_factory):
    apri_alert(session_factory, "altro", status="open")

    risposta = logga(project="scraper", action="fetch:pagina",
                     model_used="claude-haiku-4-5", tokens_used=150)

    assert "ciclo ripetuto" not in risposta


# ====================================================== il log non fallisce mai
def test_a_failing_lookup_still_records_the_action_and_reports_success(logga, monkeypatch):
    """**Il test critico di tutto il progetto.**

    Un layer di osservabilita' che rompe la cosa che osserva e' PEGGIO che inutile: si
    perdono sia i dati sia il lavoro dell'agente. Se la lookup degli alert esplode,
    l'azione dev'essere registrata comunque e la risposta dev'essere quella normale.
    """
    import starkeno.db as db_module

    def esplode(*args, **kwargs):
        raise RuntimeError("indice corrotto")

    monkeypatch.setattr(db_module, "get_open_alerts", esplode)

    risposta = logga(project="scraper", action="fetch_page",
                     model_used="claude-haiku-4-5", tokens_used=150)

    assert "Logged action" in risposta
    assert "indice corrotto" not in risposta


def test_the_action_is_persisted_even_when_the_lookup_fails(logga, session_factory,
                                                            monkeypatch):
    import starkeno.db as db_module

    monkeypatch.setattr(db_module, "get_open_alerts",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    logga(project="scraper", action="fetch_page", model_used="claude-haiku-4-5",
          tokens_used=150)

    session = session_factory()
    assert get_agent_summaries(session) == [{
        "project": "scraper", "total_tokens": 150, "action_count": 1,
        "total_effective_tokens": 150,
    }]
    session.close()


# ============================================================ scomposizione token
def test_omitted_breakdown_is_stored_as_null_not_zero(logga, session_factory):
    """NULL significa "non dichiarato", 0 significherebbe "dichiarato pari a zero".

    Confonderli sottostima la spesa: con degli 0, `effective_tokens` applicherebbe la
    formula pesata a una scomposizione inventata invece di ricadere sul costo pieno.
    """
    logga(project="scraper", action="fetch", model_used="claude-haiku-4-5",
          tokens_used=9000)

    session = session_factory()
    riga = session.query(AgentAction).one()
    assert (riga.cache_read_tokens, riga.cache_write_tokens, riga.output_tokens) == (None, None, None)
    session.close()


def test_record_action_itself_defaults_the_breakdown_to_null(session):
    """Il default va verificato anche su `record_action`, non solo attraverso l'MCP.

    Il tool MCP passa sempre i tre parametri esplicitamente, quindi un default sbagliato
    in `db.record_action` non si vedrebbe da quel percorso — e `record_action` e' la
    funzione che chiunque altro usera'. Verificato mutando il codice: il test che passa
    dall'MCP restava verde con i default a 0.
    """
    from starkeno.db import record_action

    record_action(session, project="diretto", action="x", model_used="m",
                  tokens_used=9000)

    riga = session.query(AgentAction).one()
    assert (riga.cache_read_tokens, riga.cache_write_tokens, riga.output_tokens) == (None, None, None)


def test_a_declared_breakdown_round_trips(logga, session_factory):
    logga(project="scraper", action="fetch", model_used="claude-opus-4-5",
          tokens_used=13000, cache_read_tokens=0, cache_write_tokens=0, output_tokens=8000)

    session = session_factory()
    riga = session.query(AgentAction).one()
    assert (riga.cache_read_tokens, riga.cache_write_tokens, riga.output_tokens) == (0, 0, 8000)
    session.close()


def test_the_docstring_carries_the_caller_contract():
    """Tre proprieta' di cui il Supervisore ha bisogno NON sono verificabili dal
    Supervisore. Vanno nella docstring del tool MCP, che e' la documentazione che gli
    agenti leggono davvero."""
    documentazione = mcp_server_module.log_agent_action.__doc__ or ""

    assert "categoria:dettaglio" in documentazione, "manca il contratto sulla granularita'"
    assert "cache_read_input_tokens" in documentazione, "manca lo snippet dell'SDK"
    assert "or 0" in documentazione, "manca l'avvertenza sugli Optional dell'SDK"
    assert "cache_creation_input_tokens" in documentazione, "manca il campo dei cache write"


# ============================================================== qualita' di project
def test_project_is_stripped(logga, session_factory):
    """`project` e' la chiave di partizione di ogni regola e meta' dell'identita' di
    ogni alert, ed e' una stringa libera senza vincoli."""
    logga(project="  scraper  ", action="fetch", model_used="claude-haiku-4-5",
          tokens_used=10)

    session = session_factory()
    assert session.query(AgentAction).one().project == "scraper"
    session.close()


def test_an_empty_project_is_recorded_under_a_visible_placeholder(logga, session_factory):
    """**Non si rifiuta la scrittura: il log non deve mai fallire.**

    Rifiutare una riga con `project` vuoto farebbe perdere l'azione dell'agente per un
    bug del chiamante. La riga si registra sotto un segnaposto riconoscibile, cosi' il
    problema diventa VISIBILE in dashboard invece di sparire.
    """
    risposta = logga(project="   ", action="fetch", model_used="claude-haiku-4-5",
                     tokens_used=10)

    assert "Logged action" in risposta
    session = session_factory()
    nome = session.query(AgentAction).one().project
    assert nome and nome.strip(), "nome vuoto scritto nel database"
    assert nome != "   "
    session.close()


def test_an_absurdly_long_project_is_capped(logga, session_factory):
    logga(project="x" * 500, action="fetch", model_used="claude-haiku-4-5", tokens_used=10)

    session = session_factory()
    assert len(session.query(AgentAction).one().project) <= 128
    session.close()
