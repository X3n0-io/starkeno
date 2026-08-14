from starkeno.db import (
    record_action,
    get_agent_summaries,
    get_recent_actions,
)


def test_record_action_creates_row(session):
    entry = record_action(
        session,
        project="scraper",
        action="fetch_page",
        model_used="claude-haiku-4-5",
        tokens_used=150,
    )

    assert entry.id is not None
    assert entry.project == "scraper"
    assert entry.tokens_used == 150


def test_get_agent_summaries_aggregates_by_agent(session):
    record_action(session, project="scraper", action="fetch_page", model_used="claude-haiku-4-5", tokens_used=100)
    record_action(session, project="scraper", action="parse_page", model_used="claude-haiku-4-5", tokens_used=50)
    record_action(session, project="writer", action="draft_post", model_used="claude-sonnet-5", tokens_used=300)

    summaries = get_agent_summaries(session)
    by_name = {s["project"]: s for s in summaries}

    assert by_name["scraper"]["total_tokens"] == 150
    assert by_name["scraper"]["action_count"] == 2
    assert by_name["writer"]["total_tokens"] == 300
    assert by_name["writer"]["action_count"] == 1


def test_get_recent_actions_filters_by_agent_and_orders_newest_first(session):
    record_action(session, project="scraper", action="first", model_used="claude-haiku-4-5", tokens_used=10)
    record_action(session, project="writer", action="other_agent", model_used="claude-sonnet-5", tokens_used=999)
    record_action(session, project="scraper", action="second", model_used="claude-haiku-4-5", tokens_used=20)

    actions = get_recent_actions(session, project="scraper", limit=10)

    assert len(actions) == 2
    assert actions[0].action == "second"
    assert actions[1].action == "first"
