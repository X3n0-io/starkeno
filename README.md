# StarkEno

Finds waste and errors in how you work with coding agents, and tells you what to do
about it.

**What it observes:** the API calls your agent already makes. StarkEno does not watch you
type and does not wrap your agent — it re-reads the transcripts the agent writes by
itself, and reconstructs what your way of working costs, broken down by project, model,
session, skill, plugin and MCP server.

**How it gets there:** one end-of-turn hook. It is fail-open and silent — it exits `0`
whatever happens and never writes to stderr, because a problem in StarkEno must not cost
you a turn.

**Why tokens are not the point:** they are the unit that waste and error are measured in,
not the product. A re-read file, a retried command, a task that took three attempts —
tokens are how you see them and how you compare them.

> **Status: Phase 2.** Collection is automatic and the local bill is available as a
> generated HTML page. The five measured signals arrive in Phase 3; the old R1–R4 alerts
> are not shown at startup.

## Supported agents

| Agent | Status |
|---|---|
| Codex | Supported. Installable as a plugin, reads the event-based transcript. |
| Claude Code | Supported. Installable as a plugin, reads the message-based transcript. |
| Antigravity | Detected and reported, **not measurable**. Its transcript contains no token counts anywhere in its data folder — checked by file name and by content, including Gemini's native `promptTokenCount`, `candidatesTokenCount` and `cachedContentTokenCount` keys. |
| Cursor, OpenCode, OpenClaw | Not yet. No real transcript to read a schema from. |

An agent that is recognised but not measurable produces **zero calls, never an estimate**.
`starkeno doctor` lists what it found on your machine and, for anything it cannot measure,
says why — because the hooks must stay silent, and zero rows with no explanation is
indistinguishable from a defect.

## Install

You need Python 3.12, 3.13 or 3.14 on your `PATH`. From the project root:

```bash
pip install .
```

### Codex

StarkEno ships as a Codex plugin with two hooks:

- `Stop` starts the end-of-turn re-read in the background and records the new calls;
- `SessionStart`, synchronous and limited to `startup`, adds context for a short welcome
  line only while there is no history yet.

1. restart the ChatGPT/Codex desktop app, since the repository marketplace is read at
   startup;
2. open `/plugins`, pick **StarkEno Local** and install `starkeno`;
3. start a new session;
4. open `/hooks`, review and approve `SessionStart` and `Stop`;
5. complete three normal turns;
6. run `starkeno doctor` and check the schema revision, a recent collection and the
   plugin being found.

Do not edit `~/.codex/config.toml` by hand. If the app does not expose the marketplace,
the official alternative is `codex plugin marketplace add .`, to be used only when the
local `codex` binary runs without an `Access denied` error.

### Claude Code

```bash
claude plugin marketplace add .
```

```bash
claude plugin install starkeno@starkeno-local
```

Then start a new session, approve the hooks, complete a turn and check with
`starkeno doctor`.

The Claude Code bundle lives in its own directory and its hooks are **not** the Codex
ones. That is not tidiness, it is measurement:

- the hooks are **synchronous**. The non-blocking variants were tried on real turns and
  collected nothing: the launcher returns in 354 ms and `async: true` returns immediately,
  while ingestion needs about 1600 ms, and the process does not survive. Claude Code does
  not even collect the outcome of an async hook, so an empty error list means "I don't
  know", not "it went fine";
- there is a `SessionEnd` as well as a `Stop`. `Stop` fires *before* the turn is on disk;
  since ingestion re-reads everything and is idempotent, turn N is picked up at turn N+1,
  but the last turn of a session would never get a next turn. `SessionEnd` runs with the
  transcript closed.

### What the hooks do, and what they do not

- On Codex, `Stop` uses a launcher that returns control immediately and leaves ingestion
  running in the background. It works even on Codex runtimes that document `async` but
  still skip it as unsupported. Full ingestion took 1.2–1.7 s on the largest transcript
  found (68.6 MB), and the turn does not wait for it.
- All of them exit `0` whatever happens and never write to stderr. A problem in StarkEno
  must not break your work.
- **No data leaves your machine.** Calls are stored in local SQLite.
- Ingestion is idempotent. If it misses a turn, the next one re-reads the same transcript
  without duplicating calls that are already recorded.

`SessionStart` does not write to the interface directly. Its `additionalContext` tells the
model to show a single short line in the next useful message. It welcomes you when the
database is missing or empty, and stays quiet once you have history. It creates no
database and applies no migrations.

## The bill

Generates the page and opens it in your default browser:

```bash
starkeno report
```

To choose the file, or not open the browser:

```bash
starkeno report --output starkeno-bill.html --no-open
```

The page is a static HTML file: it starts no server and does not modify the database. It
shows actions and calls, weighted total, cost of work, loading and re-reading, unknown
outcomes, partitions and the local rhythm of the last seven days. The skill/plugin/MCP
labels overlap and must not be summed.

## Experimental Preflight

Preflight currently exposes a local, structured core. `draft` validates and normalises a
JSON or YAML Blueprint without simulating it. `analyze` requires the literal `--confirmed`
flag: that explicit confirmation creates a new revision, and only then runs lint and
simulation.

JSON in, JSON out:

```bash
python -m starkeno preflight draft --input tests/fixtures/preflight/simple.json --format json --output preflight-draft.json
```

YAML in, HTML report out:

```bash
python -m starkeno preflight draft --input tests/fixtures/preflight/medium.json --format yaml --output preflight-draft.yaml
python -m starkeno preflight analyze --input preflight-draft.yaml --confirmed --samples 50 --format html --output preflight-report.html
```

The core does not yet interpret natural-language descriptions and does not execute the
workflow: it analyses already-structured Blueprints only. The natural `design` and
`review` surfaces, the Codex skill/plugin and the public site are later increments, not
capabilities included in this experimental version.

Missing tool costs stay unknown: a free tool must explicitly declare a fixed cost of zero.
Costs in different currencies are not converted or summed.

## Where the data lives

The database does not live in the plugin folder: updates cannot erase your history.

| System | Path |
|---|---|
| Windows | `%USERPROFILE%\.starkeno\starkeno.db` |
| macOS | `~/Library/Application Support/StarkEno/starkeno.db` |
| Linux | `$XDG_DATA_HOME/starkeno/starkeno.db`, otherwise `~/.local/share/starkeno/starkeno.db` |

`STARKENO_DB_PATH` takes precedence over these paths.

On Windows the database is deliberately **not** under `%LOCALAPPDATA%`, even though that
is the platform convention. A process launched by an MSIX-packaged host writes there into
the package's private overlay: measured, the same script counted 12 rows when run from the
hook and 699 from a shell, at the same path. Collection would be written to a database
that `report` and `doctor` never look at, without a single error. If you are upgrading
from an earlier version, `starkeno doctor` reports the old history as recoverable.

`starkeno doctor` takes a read-only inventory of the canonical path, of `starkeno.db` next
to the code, and of any `starkeno.db.trasferito`. No hook moves or renames your history.
Recovery always requires an explicit path and confirmation:

```bash
starkeno doctor --repair-from ./starkeno.db.trasferito --confirm-repair
```

The source is left intact; if the destination exists it is backed up to a timestamped copy
first. Recovery migrates and verifies the copy before adopting it.

## Installing the hooks by hand

The Codex plugin ships `.codex-plugin/plugin.json` and `hooks/hooks.json`, whose commands
use `PLUGIN_ROOT` and the dedicated Windows variants. The Claude Code plugin ships
`plugin-claude-code/`, whose hooks invoke the modules directly and depend on no plugin
path. For a manual trial, use absolute paths to the Python files, then check the
configuration with `/hooks` in the Codex CLI.

> The Codex scripts must be invoked by path. `python -m starkeno.hook_ingestione` from an
> unrelated folder will not find the package unless it is installed; the entry points
> include the bootstrap needed to work from the project folder opened in Codex.

## Checking that it is collecting

```bash
python -c "
import sqlite3, starkeno.config as c
con = sqlite3.connect(c.DB_PATH)
print('database:', c.DB_PATH)
print('calls:', con.execute('SELECT COUNT(*) FROM agent_actions').fetchone()[0])
for r in con.execute('SELECT project, COUNT(*), SUM(tokens_used) FROM agent_actions GROUP BY project ORDER BY 2 DESC'):
    print('  %-28s %5d calls  %12d tokens' % r)
"
```

## What is inside

| | |
|---|---|
| `starkeno/harness.py` | Which agents are recognised, and which can be measured |
| `starkeno/transcript.py` | From `.jsonl` to API calls; a pure module |
| `starkeno/hook_avvia_ingestione.py` | Non-blocking launcher, for Codex |
| `starkeno/hook_ingestione.py` | Idempotent end-of-turn ingestion |
| `starkeno/hook_inizio_sessione.py` | Synchronous session-start hook |
| `starkeno/conto.py` | Pure model of the bill |
| `starkeno/report_conto.py` | Static HTML page generator |
| `starkeno/percorsi.py` | Per-platform data paths |
| `starkeno/db.py` | Models and queries; the only module that talks to SQLAlchemy |
| `migrations/` | Alembic chain, the single authority on the schema |

```bash
python -m pytest -q
```

## Licence

MIT — see [LICENSE](LICENSE).

## Open source project

- [How to contribute](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Code of conduct](CODE_OF_CONDUCT.md)

## A note on thresholds

The historical thresholds in `config.py` are not values to ship: they come from one
person's data. Phase 3 will use thresholds derived from the history of whoever installs
StarkEno.
