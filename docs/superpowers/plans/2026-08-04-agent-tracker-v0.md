# StarkEno v0 — Agent Activity Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational piece of StarkEno: an MCP server that lets any AI agent (or Claude directly) log its actions — which model it used, how many tokens it spent — into SQLite, readable through a small FastAPI dashboard. No chat-driven dashboard customization and no rule-based Supervisor yet — just working data going in, and a working page showing it come out.

**Architecture:** Two small standalone Python processes sharing one SQLite file. An MCP server (Streamable HTTP transport) exposes a `log_agent_action` tool that any MCP client (including Claude) can call. A separate FastAPI app reads the same database and serves a static HTML dashboard plus a small JSON API. The two processes are decoupled by shared storage rather than merged into one — simpler to build, run, and debug solo, and it matches how the eventual Supervisor Agent will plug in later (as a third process reading the same data).

**Tech Stack:** Python 3.11+, `mcp[cli]` (official Model Context Protocol SDK), FastAPI, Uvicorn, SQLAlchemy, SQLite, pytest, plain HTML/JS + Tailwind (via CDN) for the dashboard — no build step.

## Global Constraints

- Project root: `<radice-progetto>` (already created)
- Python 3.11+
- Flat `starkeno/` package at project root (no `src/` layout) — keeps imports simple for pytest with no path hacks
- All timestamps stored in UTC
- **SSE transport is deprecated** per the current official MCP SDK docs (verified 04/08/2026 against live docs — supersedes the original spec's SSE choice). This plan uses **Streamable HTTP** transport instead.
- TDD: the failing test is written and run *before* the implementation, for every task
- Commit after each task, only once its tests pass

---

## Task 1: Data model — agent action logging

**Files:**
- Create: `starkeno/__init__.py`
- Create: `starkeno/config.py`
- Create: `starkeno/db.py`
- Create: `tests/test_db.py`
- Create: `requirements.txt`
- Create: `pyproject.toml`

**Interfaces:**
- Produces:
  - `starkeno.config.DB_PATH: str`
  - `starkeno.db.AgentAction` — SQLAlchemy model, columns: `id, agent_name, action, model_used, tokens_used, timestamp`
  - `starkeno.db.make_session_factory(db_path: str) -> sessionmaker`
  - `starkeno.db.record_action(session, agent_name: str, action: str, model_used: str, tokens_used: int) -> AgentAction`
  - `starkeno.db.get_agent_summaries(session) -> list[dict]` — each dict has keys `agent_name, total_tokens, action_count`
  - `starkeno.db.get_recent_actions(session, agent_name: str, limit: int = 20) -> list[AgentAction]`, newest first

- [ ] **Step 1: Create project scaffolding**

```bash
cd "<radice-progetto>"
mkdir -p starkeno tests scripts starkeno/static
touch starkeno/__init__.py
```

Create `requirements.txt`:

```
fastapi
uvicorn[standard]
mcp[cli]
sqlalchemy
httpx
pytest
```

Create `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

Create `starkeno/config.py`:

```python
DB_PATH = "starkeno.db"
```

Install dependencies:

```bash
pip install -r requirements.txt
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_db.py`:

```python
from starkeno.db import (
    make_session_factory,
    record_action,
    get_agent_summaries,
    get_recent_actions,
)


def test_record_action_creates_row(tmp_path):
    db_path = tmp_path / "test.db"
    SessionLocal = make_session_factory(str(db_path))
    session = SessionLocal()

    entry = record_action(
        session,
        agent_name="scraper",
        action="fetch_page",
        model_used="claude-haiku-4-5",
        tokens_used=150,
    )

    assert entry.id is not None
    assert entry.agent_name == "scraper"
    assert entry.tokens_used == 150
    session.close()


def test_get_agent_summaries_aggregates_by_agent(tmp_path):
    db_path = tmp_path / "test.db"
    SessionLocal = make_session_factory(str(db_path))
    session = SessionLocal()

    record_action(session, agent_name="scraper", action="fetch_page", model_used="claude-haiku-4-5", tokens_used=100)
    record_action(session, agent_name="scraper", action="parse_page", model_used="claude-haiku-4-5", tokens_used=50)
    record_action(session, agent_name="writer", action="draft_post", model_used="claude-sonnet-5", tokens_used=300)

    summaries = get_agent_summaries(session)
    by_name = {s["agent_name"]: s for s in summaries}

    assert by_name["scraper"]["total_tokens"] == 150
    assert by_name["scraper"]["action_count"] == 2
    assert by_name["writer"]["total_tokens"] == 300
    assert by_name["writer"]["action_count"] == 1
    session.close()


def test_get_recent_actions_filters_by_agent_and_orders_newest_first(tmp_path):
    db_path = tmp_path / "test.db"
    SessionLocal = make_session_factory(str(db_path))
    session = SessionLocal()

    record_action(session, agent_name="scraper", action="first", model_used="claude-haiku-4-5", tokens_used=10)
    record_action(session, agent_name="writer", action="other_agent", model_used="claude-sonnet-5", tokens_used=999)
    record_action(session, agent_name="scraper", action="second", model_used="claude-haiku-4-5", tokens_used=20)

    actions = get_recent_actions(session, agent_name="scraper", limit=10)

    assert len(actions) == 2
    assert actions[0].action == "second"
    assert actions[1].action == "first"
    session.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'starkeno.db'`

- [ ] **Step 4: Implement `starkeno/db.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, DateTime, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session

Base = declarative_base()


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True)
    agent_name = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    model_used = Column(String, nullable=False)
    tokens_used = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


def make_session_factory(db_path: str) -> sessionmaker:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def record_action(
    session: Session,
    agent_name: str,
    action: str,
    model_used: str,
    tokens_used: int,
) -> AgentAction:
    entry = AgentAction(
        agent_name=agent_name,
        action=action,
        model_used=model_used,
        tokens_used=tokens_used,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def get_agent_summaries(session: Session) -> list[dict]:
    rows = (
        session.query(
            AgentAction.agent_name,
            func.sum(AgentAction.tokens_used).label("total_tokens"),
            func.count(AgentAction.id).label("action_count"),
        )
        .group_by(AgentAction.agent_name)
        .all()
    )
    return [
        {"agent_name": r.agent_name, "total_tokens": r.total_tokens, "action_count": r.action_count}
        for r in rows
    ]


def get_recent_actions(session: Session, agent_name: str, limit: int = 20) -> list[AgentAction]:
    return (
        session.query(AgentAction)
        .filter(AgentAction.agent_name == agent_name)
        .order_by(AgentAction.timestamp.desc())
        .limit(limit)
        .all()
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git init
git add starkeno tests requirements.txt pyproject.toml
git commit -m "feat: agent action data model with SQLite storage"
```

---

## Task 2: MCP server — `log_agent_action` tool

**Files:**
- Create: `starkeno/mcp_server.py`
- Create: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `starkeno.config.DB_PATH` (Task 1), `starkeno.db.make_session_factory` (Task 1), `starkeno.db.record_action` (Task 1), `starkeno.db.get_agent_summaries` (Task 1)
- Produces:
  - `starkeno.mcp_server.SessionLocal` (module-level session factory, swappable in tests via `monkeypatch`)
  - `starkeno.mcp_server.log_agent_action_impl(agent_name: str, action: str, model_used: str, tokens_used: int) -> str`
  - `starkeno.mcp_server.mcp` — the `MCPServer` instance, with `log_agent_action` registered as a tool

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_server.py`:

```python
from starkeno.db import make_session_factory, get_agent_summaries
import starkeno.mcp_server as mcp_server_module
from starkeno.mcp_server import log_agent_action_impl


def test_log_agent_action_impl_records_to_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    test_session_factory = make_session_factory(str(db_path))
    monkeypatch.setattr(mcp_server_module, "SessionLocal", test_session_factory)

    result = log_agent_action_impl(
        agent_name="scraper",
        action="fetch_page",
        model_used="claude-haiku-4-5",
        tokens_used=150,
    )

    assert "scraper" in result
    assert "150" in result

    session = test_session_factory()
    summaries = get_agent_summaries(session)
    assert summaries == [{"agent_name": "scraper", "total_tokens": 150, "action_count": 1}]
    session.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'starkeno.mcp_server'`

- [ ] **Step 3: Implement `starkeno/mcp_server.py`**

```python
from mcp.server import MCPServer

from starkeno.config import DB_PATH
from starkeno.db import make_session_factory, record_action

SessionLocal = make_session_factory(DB_PATH)

mcp = MCPServer("StarkEno")


def log_agent_action_impl(agent_name: str, action: str, model_used: str, tokens_used: int) -> str:
    session = SessionLocal()
    try:
        record_action(
            session,
            agent_name=agent_name,
            action=action,
            model_used=model_used,
            tokens_used=tokens_used,
        )
        return f"Logged action '{action}' for agent '{agent_name}' ({tokens_used} tokens, model {model_used})"
    finally:
        session.close()


@mcp.tool()
def log_agent_action(agent_name: str, action: str, model_used: str, tokens_used: int) -> str:
    """Record an action taken by an AI agent, including which model it used and how many tokens it consumed."""
    return log_agent_action_impl(agent_name, action, model_used, tokens_used)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, streamable_http_path="/mcp")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_server.py -v`
Expected: `1 passed`

- [ ] **Step 5: Manual smoke test — server starts**

Run: `python -m starkeno.mcp_server`
Expected: process starts and stays running (no traceback) with Uvicorn startup log lines, listening on `127.0.0.1:8765`. Stop with `Ctrl+C`. This confirms the server boots; Task 5 confirms a real client can talk to it.

(Note: `python starkeno/mcp_server.py` — invoking by file path instead of `-m` — fails with `ModuleNotFoundError: No module named 'starkeno'`, because `mcp_server.py` uses the absolute import `from starkeno.config import DB_PATH`, and running a script by path only adds its own directory to `sys.path`, not the project root. Always use `-m`.)

- [ ] **Step 6: Commit**

```bash
git add starkeno/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: MCP server exposing log_agent_action tool"
```

---

## Task 3: FastAPI read API

**Files:**
- Create: `starkeno/api.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Consumes: `starkeno.config.DB_PATH` (Task 1), `starkeno.db.make_session_factory` / `get_agent_summaries` / `get_recent_actions` (Task 1)
- Produces:
  - `starkeno.api.app` — FastAPI instance
  - `starkeno.api.get_session` — FastAPI dependency, overridable in tests
  - `GET /api/agents` → `list[{"agent_name": str, "total_tokens": int, "action_count": int}]`
  - `GET /api/agents/{agent_name}/actions` → `list[{"id": int, "action": str, "model_used": str, "tokens_used": int, "timestamp": str}]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api.py`:

```python
from fastapi.testclient import TestClient

import starkeno.api as api_module
from starkeno.db import make_session_factory, record_action


def make_test_client(tmp_path):
    db_path = tmp_path / "test.db"
    test_session_factory = make_session_factory(str(db_path))

    def override_get_session():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    api_module.app.dependency_overrides[api_module.get_session] = override_get_session
    return TestClient(api_module.app), test_session_factory


def test_list_agents_returns_aggregated_summaries(tmp_path):
    client, session_factory = make_test_client(tmp_path)
    session = session_factory()
    record_action(session, agent_name="scraper", action="fetch", model_used="claude-haiku-4-5", tokens_used=100)
    record_action(session, agent_name="scraper", action="parse", model_used="claude-haiku-4-5", tokens_used=50)
    session.close()

    response = client.get("/api/agents")

    assert response.status_code == 200
    assert response.json() == [{"agent_name": "scraper", "total_tokens": 150, "action_count": 2}]


def test_list_agent_actions_returns_recent_actions_for_agent(tmp_path):
    client, session_factory = make_test_client(tmp_path)
    session = session_factory()
    record_action(session, agent_name="scraper", action="fetch", model_used="claude-haiku-4-5", tokens_used=100)
    record_action(session, agent_name="writer", action="draft", model_used="claude-sonnet-5", tokens_used=300)
    session.close()

    response = client.get("/api/agents/scraper/actions")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["action"] == "fetch"
    assert data[0]["tokens_used"] == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'starkeno.api'`

- [ ] **Step 3: Implement `starkeno/api.py`**

```python
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from starkeno.config import DB_PATH
from starkeno.db import make_session_factory, get_agent_summaries, get_recent_actions

SessionLocal = make_session_factory(DB_PATH)

app = FastAPI(title="StarkEno Dashboard API")


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.get("/api/agents")
def list_agents(session: Session = Depends(get_session)):
    return get_agent_summaries(session)


@app.get("/api/agents/{agent_name}/actions")
def list_agent_actions(agent_name: str, session: Session = Depends(get_session)):
    actions = get_recent_actions(session, agent_name=agent_name, limit=20)
    return [
        {
            "id": a.id,
            "action": a.action,
            "model_used": a.model_used,
            "tokens_used": a.tokens_used,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in actions
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add starkeno/api.py tests/test_api.py
git commit -m "feat: FastAPI read endpoints for agent summaries and actions"
```

---

## Task 4: Dashboard static page

**Files:**
- Create: `starkeno/static/index.html`
- Modify: `starkeno/api.py` (add static file mount, appended after the `/api/...` routes so it doesn't shadow them)
- Modify: `tests/test_api.py` (add dashboard serving test)

**Interfaces:**
- Consumes: `starkeno.api.app` (Task 3), `GET /api/agents` (Task 3, fetched client-side via JS — not at import time)
- Produces: static HTML served at `GET /`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api.py`:

```python
def test_dashboard_serves_html_at_root(tmp_path):
    client, _ = make_test_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "StarkEno" in response.text
    assert "agents-table-body" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py -v`
Expected: FAIL — `404` instead of `200` (no route/static mount serves `/` yet)

- [ ] **Step 3: Create `starkeno/static/index.html`**

```html
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <title>StarkEno — Dashboard Agenti</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 p-8">
  <h1 class="text-2xl font-bold mb-6">StarkEno — Agenti attivi</h1>
  <table class="w-full text-left border-collapse">
    <thead>
      <tr class="border-b border-slate-700">
        <th class="py-2">Agente</th>
        <th class="py-2">Token totali</th>
        <th class="py-2">Numero azioni</th>
      </tr>
    </thead>
    <tbody id="agents-table-body"></tbody>
  </table>

  <script>
    async function loadAgents() {
      const response = await fetch("/api/agents");
      const agents = await response.json();
      const tbody = document.getElementById("agents-table-body");
      tbody.innerHTML = "";
      for (const agent of agents) {
        const row = document.createElement("tr");
        row.className = "border-b border-slate-800";
        row.innerHTML = `
          <td class="py-2">${agent.agent_name}</td>
          <td class="py-2">${agent.total_tokens}</td>
          <td class="py-2">${agent.action_count}</td>
        `;
        tbody.appendChild(row);
      }
    }

    loadAgents();
  </script>
</body>
</html>
```

- [ ] **Step 4: Mount the static directory — replace `starkeno/api.py` with this complete file**

Mounting order matters: the static mount must be the last line, after every `@app.get(...)` route, so it doesn't shadow `/api/...`.

```python
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from starkeno.config import DB_PATH
from starkeno.db import make_session_factory, get_agent_summaries, get_recent_actions

SessionLocal = make_session_factory(DB_PATH)

app = FastAPI(title="StarkEno Dashboard API")


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.get("/api/agents")
def list_agents(session: Session = Depends(get_session)):
    return get_agent_summaries(session)


@app.get("/api/agents/{agent_name}/actions")
def list_agent_actions(agent_name: str, session: Session = Depends(get_session)):
    actions = get_recent_actions(session, agent_name=agent_name, limit=20)
    return [
        {
            "id": a.id,
            "action": a.action,
            "model_used": a.model_used,
            "tokens_used": a.tokens_used,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in actions
    ]


app.mount("/", StaticFiles(directory="starkeno/static", html=True), name="static")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add starkeno/static/index.html starkeno/api.py tests/test_api.py
git commit -m "feat: static dashboard page listing agent summaries"
```

---

## Task 5: Wire it together end to end

**Files:**
- Create: `scripts/smoke_test_client.py`

**Interfaces:**
- Consumes: the running MCP server from Task 2 (`http://127.0.0.1:8765/mcp`, Streamable HTTP)

This task has no pytest step — it is a manual, end-to-end proof that the two processes really talk to each other and to the dashboard. Every command and its expected output is exact.

- [ ] **Step 1: Create the smoke-test MCP client**

```python
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with streamable_http_client("http://127.0.0.1:8765/mcp") as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "log_agent_action",
                {
                    "agent_name": "smoke-test-agent",
                    "action": "manual_verification",
                    "model_used": "claude-sonnet-5",
                    "tokens_used": 42,
                },
            )
            print(result.content)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Start the MCP server (terminal 1)**

```bash
python -m starkeno.mcp_server
```

Expected: stays running, no traceback, listening on `127.0.0.1:8765`. (Use `-m`, not `python starkeno/mcp_server.py` by path — see the note in Task 2 Step 5.)

- [ ] **Step 3: Start the dashboard (terminal 2)**

```bash
uvicorn starkeno.api:app --reload --port 8000
```

Expected: stays running, `Uvicorn running on http://127.0.0.1:8000`.

- [ ] **Step 4: Run the smoke-test client (terminal 3)**

```bash
python scripts/smoke_test_client.py
```

Expected output: a `TextContent`/result object whose text includes `Logged action 'manual_verification' for agent 'smoke-test-agent' (42 tokens, model claude-sonnet-5)`.

- [ ] **Step 5: Confirm it shows up on the dashboard**

Open `http://127.0.0.1:8000/` in a browser.
Expected: a table row `smoke-test-agent | 42 | 1`.

This closes the real loop: an MCP client (standing in for Claude) logs an action → it lands in SQLite → the dashboard shows it, with zero manual database editing. Everything after this plan (chat-driven dashboard customization, the rule-based Supervisor) builds on this working skeleton.

- [ ] **Step 6: Commit**

```bash
git add scripts/smoke_test_client.py
git commit -m "chore: end-to-end smoke test client for MCP -> DB -> dashboard flow"
```
