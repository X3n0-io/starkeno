from fastapi.testclient import TestClient

import starkeno.api as api_module
from starkeno.db import record_action


def make_test_client(session_factory):
    """Client con la sessione sovrascritta su un database usa e getta.

    Lo schema arriva dalla fixture `session_factory` (conftest.py): da quando Alembic
    e' l'unica autorita', `make_session_factory` non crea piu' tabelle.
    """

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    api_module.app.dependency_overrides[api_module.get_session] = override_get_session
    return TestClient(api_module.app)


def test_list_agents_returns_aggregated_summaries(session_factory):
    client = make_test_client(session_factory)
    session = session_factory()
    record_action(session, project="scraper", action="fetch", model_used="claude-haiku-4-5", tokens_used=100)
    record_action(session, project="scraper", action="parse", model_used="claude-haiku-4-5", tokens_used=50)
    session.close()

    response = client.get("/api/agents")

    assert response.status_code == 200
    assert response.json() == [{
        "project": "scraper", "total_tokens": 150, "action_count": 2,
        # senza scomposizione dichiarata, il pesato coincide col grezzo: e' il ramo
        "total_effective_tokens": 150,   # "nessuna dichiarazione -> costo pieno"
    }]


def test_list_agent_actions_returns_recent_actions_for_agent(session_factory):
    client = make_test_client(session_factory)
    session = session_factory()
    record_action(session, project="scraper", action="fetch", model_used="claude-haiku-4-5", tokens_used=100)
    record_action(session, project="writer", action="draft", model_used="claude-sonnet-5", tokens_used=300)
    session.close()

    response = client.get("/api/agents/scraper/actions")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["action"] == "fetch"
    assert data[0]["tokens_used"] == 100


def test_dashboard_serves_html_at_root(session_factory):
    client = make_test_client(session_factory)

    response = client.get("/")

    assert response.status_code == 200
    assert "StarkEno" in response.text
    assert "agents-table-body" in response.text
