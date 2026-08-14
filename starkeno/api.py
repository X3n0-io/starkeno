"""API di lettura della dashboard.

**L'ordine di registrazione delle rotte non e' libero.** Tutte le rotte `/api/...` vanno
dichiarate PRIMA di `app.mount("/", StaticFiles(html=True))`, in fondo al file: il
catch-all degli statici oscura tutto cio' che viene dopo e risponde con un 404 di
StaticFiles — non un errore, una pagina — che sembra "endpoint inesistente" e manda a
cercare il bug nella parte sbagliata del codice.

**Ogni DateTime passa da `_iso`.** `resolved_at` e `muted_until` sono nulli su ogni alert
non risolto, cioe' nel caso normale: un `.isoformat()` diretto solleva `AttributeError`
e produce un HTTP 500 dal primo minuto di vita della v1.
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from starkeno.config import DB_PATH
from starkeno.db import (
    STATI_ALERT,
    STATI_VIVI,
    dismiss_alert,
    get_agent_summaries,
    get_alerts,
    get_heartbeat,
    get_recent_actions,
    get_rule_status,
    make_session_factory,
    mute_alert,
)
from starkeno.db import Alert as AlertRow
from starkeno.schema_version import check_or_die

_session_factory = None


def get_session_factory():
    """Costruita alla prima richiesta, non all'import: vedi mcp_server.get_session_factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(DB_PATH)
    return _session_factory


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Controllo di versione dello schema all'avvio del processo.

    Nel lifespan e non all'import: costruire la session factory al momento dell'import
    e' esattamente cio' che l'invariante 2 di CLAUDE.md vieta. Qui gira quando uvicorn
    avvia davvero l'applicazione.

    Nota per i test: `TestClient(app).get(...)` NON esegue il lifespan (verificato); lo
    esegue solo la forma `with TestClient(app) as client`. I test dell'API usano la
    prima, quindi non passano di qui.
    """
    check_or_die(get_session_factory().kw["bind"])
    yield


app = FastAPI(title="StarkEno Dashboard API", lifespan=lifespan)


def get_session():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _iso(valore: datetime | None) -> str | None:
    """L'UNICO punto in cui un DateTime diventa stringa.

    Esiste perche' meta' delle colonne temporali degli alert sono nullable e lo sono nel
    caso normale, non in un caso limite. Un helper solo, e nessun `.isoformat()` sparso.
    """
    return None if valore is None else valore.isoformat()


def _evidence(grezza: str | None):
    """`evidence` esce come STRUTTURA, non come stringa.

    La dashboard ci legge dentro `related_rule` per raggruppare gli alert di uno stesso
    incidente, e le anomalie di R3. Se il JSON fosse corrotto si restituisce un oggetto
    diagnostico invece di far fallire l'endpoint: un alert illeggibile e' meglio di una
    pagina vuota.
    """
    if not grezza:
        return {}
    try:
        return json.loads(grezza)
    except (ValueError, TypeError):
        return {"_evidence_illeggibile": grezza[:200]}


def _alert_dict(a) -> dict:
    return {
        "id": a.id,
        "project": a.project,
        "rule": a.rule,
        "status": a.status,
        "detail": a.detail,
        "evidence": _evidence(a.evidence),
        "episodes": a.episodes,
        "observed_rounds": a.observed_rounds,
        "first_seen": _iso(a.first_seen),
        "last_seen": _iso(a.last_seen),
        "resolved_at": _iso(a.resolved_at),
        "resolution": a.resolution,
        "muted_until": _iso(a.muted_until),
        "user_note": a.user_note,
    }


class DismissBody(BaseModel):
    note: str

    @field_validator("note")
    @classmethod
    def non_vuota(cls, valore: str) -> str:
        """La nota e' obbligatoria e non puo' essere spazi.

        Non e' burocrazia: la storia dei falsi positivi col loro motivo e' il dato che
        serve per tarare soglie che oggi non sono tarate su niente.
        """
        if not valore or not valore.strip():
            raise ValueError("la nota e' obbligatoria")
        return valore.strip()


class MuteBody(BaseModel):
    until: datetime


# --------------------------------------------------------------------------- agenti
@app.get("/api/agents")
def list_agents(session: Session = Depends(get_session)):
    return get_agent_summaries(session)


@app.get("/api/agents/{project}/actions")
def list_agent_actions(project: str, session: Session = Depends(get_session)):
    actions = get_recent_actions(session, project=project, limit=20)
    return [
        {
            "id": a.id,
            "action": a.action,
            "model_used": a.model_used,
            "tokens_used": a.tokens_used,
            "cache_read_tokens": a.cache_read_tokens,
            "cache_write_tokens": a.cache_write_tokens,
            "output_tokens": a.output_tokens,
            # gia' aware-UTC: la normalizzazione avviene in db.UTCDateTime, non qui
            "timestamp": _iso(a.timestamp),
        }
        for a in actions
    ]


# --------------------------------------------------------------------------- alert
@app.get("/api/alerts")
def list_alerts(
    status: str = Query("live", pattern="^(live|all|candidate|open|resolved|dismissed)$"),
    session: Session = Depends(get_session),
):
    """Default `live` = candidate + open.

    Un filtro sconosciuto viene RIFIUTATO dal pattern, non ignorato: restituire tutto su
    un filtro scritto male sarebbe peggio di un errore, perche' sembrerebbe funzionare.
    """
    if status == "live":
        stati = STATI_VIVI
    elif status == "all":
        stati = STATI_ALERT
    else:
        stati = (status,)
    return [_alert_dict(a) for a in get_alerts(session, stati)]


@app.post("/api/alerts/{alert_id}/dismiss")
def dismiss(alert_id: int, corpo: DismissBody, session: Session = Depends(get_session)):
    alert = session.get(AlertRow, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert inesistente")
    return _alert_dict(dismiss_alert(session, alert, note=corpo.note,
                                     now=datetime.now(alert.first_seen.tzinfo)))


@app.post("/api/alerts/{alert_id}/mute")
def mute(alert_id: int, corpo: MuteBody, session: Session = Depends(get_session)):
    alert = session.get(AlertRow, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert inesistente")
    return _alert_dict(mute_alert(session, alert, until=corpo.until))


# ---------------------------------------------------------------- stato delle regole
@app.get("/api/rule-status")
def list_rule_status(session: Session = Depends(get_session)):
    """Include `non_valutabile` e `error`, che sono il punto di questa tabella.

    Senza `error`, una regola che solleva un'eccezione e' visivamente identica a una che
    dice OK; senza `non_valutabile`, una regola che tace per ignoranza sembra dare via
    libera. Sono i due modi in cui il silenzio si traveste da salute.
    """
    return [
        {
            "project": r.project,
            "rule": r.rule,
            "state": r.state,
            "reason": r.reason,
            "updated_at": _iso(r.updated_at),
        }
        for r in get_rule_status(session)
    ]


# -------------------------------------------------------------- stato del supervisore
@app.get("/api/supervisor/status")
def supervisor_status(session: Session = Depends(get_session)):
    """L'heartbeat. Risponde anche quando non c'e' ancora stato nessun giro.

    Un supervisore morto e un sistema sano mostrano la stessa schermata — zero alert — e
    questo endpoint e' l'unica cosa che li distingue. Se esplodesse su
    `supervisor_state` vuota, fallirebbe proprio nello stato in cui serve di piu': quando
    il processo non e' partito.
    """
    battito = get_heartbeat(session)
    if battito is None:
        return {
            "last_run_at": None, "last_run_ms": None, "agents_evaluated": 0,
            "rules_failed": 0, "last_error": None, "consecutive_errors": 0,
        }
    return {
        "last_run_at": _iso(battito.last_run_at),
        "last_run_ms": battito.last_run_ms,
        "agents_evaluated": battito.agents_evaluated,
        "rules_failed": battito.rules_failed,
        "last_error": battito.last_error,
        "consecutive_errors": battito.consecutive_errors,
    }


# ============================================================================
# IL MOUNT VA PER ULTIMO. Nessuna rotta sotto questa riga verrebbe mai raggiunta.
# ============================================================================
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
