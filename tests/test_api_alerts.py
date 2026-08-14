"""Task 11 — la superficie di lettura.

Senza questa sezione la v1 puo' essere "completa" — tutti i test verdi, il supervisore
che gira, `alerts` che si riempie — **senza che un solo alert raggiunga mai un essere
umano**.

Due trappole note, entrambe con un test dedicato:

**L'ordine di registrazione.** Le rotte vanno dichiarate PRIMA di
`app.mount("/", StaticFiles(html=True))`. Il catch-all degli statici oscura tutto quello
che viene dopo e restituisce un 404 statico — non un errore, una pagina.

**I DateTime nullable.** `resolved_at` e `muted_until` sono nulli su ogni alert non
risolto, cioe' nel caso NORMALE. Il pattern `a.timestamp.isoformat()` applicato a `None`
solleva `AttributeError` -> HTTP 500 dal primo minuto di vita della v1.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import starkeno.api as api_module
from starkeno.db import (
    record_action,
    resolve_alert,
    set_rule_status,
    upsert_alert,
    write_heartbeat,
)

ORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(session_factory):
    def override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    api_module.app.dependency_overrides[api_module.get_session] = override
    yield TestClient(api_module.app)
    api_module.app.dependency_overrides.clear()


def crea_alert(session_factory, *, agente="scraper", regola="loop", status="open",
               dettaglio="ciclo ripetuto", evidenza=None):
    session = session_factory()
    alert = upsert_alert(session, project=agente, rule=regola, detail=dettaglio,
                         evidence=evidenza if evidenza is not None else {"k": [1, 2]},
                         last_seen=ORA, now=ORA)
    alert.status = status
    session.commit()
    identificativo = alert.id
    session.close()
    return identificativo


# ============================================================ l'ordine delle rotte
def test_every_api_route_is_registered_before_the_static_mount():
    """**Il catch-all degli statici oscura tutto cio' che viene dopo.**

    E non con un errore: con un 404 di StaticFiles, che sembra "endpoint inesistente" e
    manda a cercare il bug nella parte sbagliata del codice.
    """
    from starlette.routing import Mount

    posizioni_api = [i for i, r in enumerate(api_module.app.routes)
                     if getattr(r, "path", "").startswith("/api/")]
    posizioni_mount = [i for i, r in enumerate(api_module.app.routes)
                       if isinstance(r, Mount)]

    assert posizioni_api, "nessuna rotta /api registrata"
    assert posizioni_mount, "il mount degli statici e' sparito"
    assert max(posizioni_api) < min(posizioni_mount), (
        "una rotta /api e' dichiarata dopo app.mount: sara' oscurata dal catch-all"
    )


# ==================================================================== GET /api/alerts
def test_alerts_defaults_to_the_live_ones(client, session_factory):
    crea_alert(session_factory, regola="loop", status="open")
    crea_alert(session_factory, regola="expensive_model", status="candidate")
    crea_alert(session_factory, regola="steady_waste", status="resolved")

    risposta = client.get("/api/alerts")

    assert risposta.status_code == 200
    regole = {a["rule"] for a in risposta.json()}
    assert regole == {"loop", "expensive_model"}


def test_a_null_resolved_at_does_not_produce_a_500(client, session_factory):
    """**Il caso normale, non un caso limite.**

    Dal primo minuto di vita della v1 ogni alert aperto ha `resolved_at` e `muted_until`
    a NULL. Un `.isoformat()` diretto li fa esplodere.
    """
    crea_alert(session_factory, status="open")

    risposta = client.get("/api/alerts")

    assert risposta.status_code == 200, risposta.text
    riga = risposta.json()[0]
    assert riga["resolved_at"] is None
    assert riga["muted_until"] is None
    assert riga["first_seen"] is not None


def test_evidence_round_trips_as_a_structure_not_a_string(client, session_factory):
    """La dashboard deve poterci leggere dentro `related_rule` e le anomalie di R3."""
    crea_alert(session_factory, evidenza={"rilevatore": "ciclo", "related_rule": "loop",
                                          "ripetizioni": 7})

    riga = client.get("/api/alerts").json()[0]

    assert riga["evidence"] == {"rilevatore": "ciclo", "related_rule": "loop",
                                "ripetizioni": 7}


def test_stale_is_distinguishable_from_recovery(client, session_factory):
    """Archiviazione per inattivita' e rientro sono due cose diverse, e la dashboard le
    marca diversamente: senza il campo, "risolto" mentirebbe su meta' dei casi."""
    session = session_factory()
    a = upsert_alert(session, project="fermo", rule="loop", detail="x",
                     evidence={}, last_seen=ORA, now=ORA)
    resolve_alert(session, a, resolution="stale", now=ORA)
    b = upsert_alert(session, project="rientrato", rule="loop", detail="y",
                     evidence={}, last_seen=ORA, now=ORA)
    resolve_alert(session, b, resolution="recovery", now=ORA)
    session.close()

    righe = client.get("/api/alerts?status=resolved").json()
    per_agente = {r["project"]: r["resolution"] for r in righe}

    assert per_agente == {"fermo": "stale", "rientrato": "recovery"}


def test_alerts_are_ordered_by_last_seen_descending(client, session_factory):
    session = session_factory()
    for nome, quando in (("vecchio", ORA - timedelta(hours=3)), ("nuovo", ORA)):
        upsert_alert(session, project=nome, rule="loop", detail="x", evidence={},
                     last_seen=quando, now=ORA)
    session.close()

    nomi = [a["project"] for a in client.get("/api/alerts").json()]

    assert nomi == ["nuovo", "vecchio"]


def test_status_all_returns_everything(client, session_factory):
    crea_alert(session_factory, regola="loop", status="open")
    crea_alert(session_factory, regola="expensive_model", status="resolved")
    crea_alert(session_factory, regola="steady_waste", status="dismissed")

    assert len(client.get("/api/alerts?status=all").json()) == 3


def test_an_unknown_status_is_rejected_not_silently_ignored(client):
    """Un filtro sconosciuto che restituisse tutto sarebbe peggio di un errore."""
    assert client.get("/api/alerts?status=inventato").status_code == 422


# =============================================================== GET /api/rule-status
def test_rule_status_exposes_the_third_state_and_the_error_state(client, session_factory):
    """**Le due righe che rendono visibile il silenzio.**

    `non_valutabile` dice "sto ancora calibrando" invece di dare via libera; `error` dice
    che una regola e' rotta, e senza di esso una regola che solleva un'eccezione e'
    visivamente identica a una che dice OK.
    """
    session = session_factory()
    set_rule_status(session, "a", "loop", state="non_valutabile",
                    reason="azioni senza dettaglio", now=ORA)
    set_rule_status(session, "a", "steady_waste", state="error",
                    reason="ZeroDivisionError: boom", now=ORA)
    set_rule_status(session, "a", "expensive_model", state="ok", reason=None, now=ORA)
    session.close()

    per_regola = {r["rule"]: r for r in client.get("/api/rule-status").json()}

    assert per_regola["loop"]["state"] == "non_valutabile"
    assert per_regola["loop"]["reason"] == "azioni senza dettaglio"
    assert per_regola["steady_waste"]["state"] == "error"
    assert "ZeroDivisionError" in per_regola["steady_waste"]["reason"]
    assert per_regola["expensive_model"]["reason"] is None


# ========================================================== GET /api/supervisor/status
def test_supervisor_status_works_before_the_first_round(client):
    """Prima del primo giro `supervisor_state` e' vuota. L'endpoint deve dirlo, non
    esplodere: e' proprio lo stato in cui si e' quando qualcosa non e' partito."""
    risposta = client.get("/api/supervisor/status")

    assert risposta.status_code == 200
    assert risposta.json()["last_run_at"] is None


def test_supervisor_status_reports_the_heartbeat(client, session_factory):
    session = session_factory()
    write_heartbeat(session, now=ORA, duration_ms=31, agents_evaluated=4,
                    rules_failed=1, last_error="loop: boom")
    session.close()

    corpo = client.get("/api/supervisor/status").json()

    assert corpo["agents_evaluated"] == 4
    assert corpo["rules_failed"] == 1
    assert corpo["consecutive_errors"] == 1
    assert corpo["last_error"] == "loop: boom"
    assert corpo["last_run_at"].startswith("2026-08-06")


# ============================================================ POST dismiss / mute
def test_dismiss_requires_a_note(client, session_factory):
    """**La nota non e' burocrazia.**

    La storia dei falsi positivi con il loro motivo e' il dato che serve per tarare le
    soglie, e le soglie di questa v1 non sono tarate su niente.
    """
    identificativo = crea_alert(session_factory)

    assert client.post("/api/alerts/%d/dismiss" % identificativo, json={}).status_code == 422
    assert client.post("/api/alerts/%d/dismiss" % identificativo,
                       json={"note": "   "}).status_code == 422


def test_dismiss_marks_the_alert_and_keeps_the_note(client, session_factory):
    """Senza dismiss, un falso positivo su un agente sano e sempre attivo non e'
    chiudibile da nessuna via: il recupero non scatta perche' la violazione e' presente a
    ogni giro, lo stantio non scatta perche' l'agente gira. E l'alert inietta un warning
    dentro il loop dell'agente per sempre."""
    identificativo = crea_alert(session_factory)

    risposta = client.post("/api/alerts/%d/dismiss" % identificativo,
                           json={"note": "eval-runner: 25 chiamate piccole per progetto"})

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["status"] == "dismissed"
    assert "eval-runner" in corpo["user_note"]
    assert client.get("/api/alerts").json() == []


def test_a_dismissed_alert_lets_a_new_one_be_created(client, session_factory):
    """`dismissed` resta fuori dall'indice unico parziale, di proposito."""
    identificativo = crea_alert(session_factory)
    client.post("/api/alerts/%d/dismiss" % identificativo, json={"note": "falso positivo"})

    nuovo = crea_alert(session_factory)      # non deve sollevare

    assert nuovo != identificativo
    assert len(client.get("/api/alerts?status=all").json()) == 2


def test_mute_sets_the_deadline(client, session_factory):
    identificativo = crea_alert(session_factory)
    fino = ORA + timedelta(days=2)

    risposta = client.post("/api/alerts/%d/mute" % identificativo,
                           json={"until": fino.isoformat()})

    assert risposta.status_code == 200
    assert risposta.json()["muted_until"].startswith("2026-08-08")


def test_acting_on_a_missing_alert_returns_404(client):
    assert client.post("/api/alerts/9999/dismiss", json={"note": "x"}).status_code == 404
    assert client.post("/api/alerts/9999/mute",
                       json={"until": ORA.isoformat()}).status_code == 404


# ============================================================ token pesati
def test_agents_expose_weighted_tokens_next_to_raw_ones(client, session_factory):
    """Oggi il numero piu' grande della dashboard e' in un'unita' DIVERSA da quella con
    cui ragionano gli alert. R3 e R4 misurano su `effective_tokens`, e senza la colonna
    accanto ai grezzi un alert da 500k pesati sembrerebbe sbagliato guardando i totali."""
    session = session_factory()
    record_action(session, project="scraper", action="x", model_used="claude-opus-4-5",
                  tokens_used=13_000, cache_read_tokens=0, cache_write_tokens=0,
                  output_tokens=8_000)
    session.close()

    riga = client.get("/api/agents").json()[0]

    assert riga["total_tokens"] == 13_000
    assert riga["total_effective_tokens"] == 45_000
