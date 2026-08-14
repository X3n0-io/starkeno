from starkeno.db import get_agent_summaries
import starkeno.mcp_server as mcp_server_module
from starkeno.mcp_server import log_agent_action_impl


def test_log_agent_action_impl_records_to_db(session_factory, monkeypatch):
    test_session_factory = session_factory
    monkeypatch.setattr(mcp_server_module, "get_session_factory", lambda: test_session_factory)

    result = log_agent_action_impl(
        project="scraper",
        action="fetch_page",
        model_used="claude-haiku-4-5",
        tokens_used=150,
    )

    assert "scraper" in result
    assert "150" in result

    session = test_session_factory()
    summaries = get_agent_summaries(session)
    assert summaries == [{
        "project": "scraper", "total_tokens": 150, "action_count": 1,
        "total_effective_tokens": 150,
    }]
    session.close()
