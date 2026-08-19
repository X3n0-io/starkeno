# StarkEno

*Read this in [Italian](README.md) — Italian is the project's language, and
this page is the translation.*

**What will this agent run cost — before you run it?**

Every other tool in this space answers afterwards. They read the same local transcripts
your agent already writes and tell you, accurately, what you have already spent. That is
a solved problem and there are good tools for it.

StarkEno is built around the question they do not ask. It is the only thing here worth
your attention, and it is early.

> **Status: Phase 2.** Collection works and the local bill is real and installable.
> The forecast is built and reachable by hand, and has been scored against a real
> execution exactly once — that measurement is the next thing on this page.

## The one real measurement

> StarkEno estimated a run at **331,500 tokens** at most.
> The run cost **3,035,535**. The forecast was wrong by **9x**.

One run, one machine, one agent. It is at the top of this README instead of buried,
because a forecasting tool that hides its error is worth nothing — and because the error
turned out to be the interesting part.

**It was not noise. It was structural, and the structure is known.**

The simulator counts context written into the cache once per invocation, and context read
back only on retries. A real agent does something else entirely: it has no memory between
turns, so it resends everything it knows on *every* turn. On the machine this was measured
on, that re-reading was **60% of a full week's spend** — the exact quantity the simulator
barely counts.

So the model was not miscalculating. It was modelling the wrong animal.

That distinction matters, and it is the reason this project exists rather than being
abandoned: **a random error is a dead end, a structural one is a coefficient.** The open
question is which shape it has —

- if the gap is a **multiplicative constant**, the fix is one number and the forecast
  becomes useful immediately;
- if it **depends on the shape of the work** — a long run, a run with heavy re-reading, a
  run full of retries — then it needs a model per shape.

Telling those two apart needs more real runs. That is the current work, and it is the
honest state of the project: one measurement, a known mechanism, and an unanswered
question.

## What you can actually run today

The forecasting half is **not shipped as a ready feature** — see
[The forecast](#the-forecast-estimate-against-execution) for exactly what that means and
how to reach it anyway.

What is finished, tested and installable is the other half: the measurement the forecast
has to be checked against.

**One end-of-turn hook re-reads the transcript your agent already writes**, and records
each API call in a local SQLite database. StarkEno never watches you type and never wraps
your agent.

**Nothing leaves your machine.** No network call, no account, no telemetry. The bill is a
static HTML file on your disk.

**It cannot cost you a turn.** The hooks exit `0` whatever happens and never write to
stderr. If StarkEno breaks, your work does not — which is also why a broken StarkEno is
invisible, and why `starkeno doctor` exists.

**Two agents, one bill.** Claude Code and Codex land in the same database with the same
totals. If you use both, nothing else adds them up for you.

> **The tool itself speaks Italian.** The bill, the `doctor` messages and the check
> names are in Italian, because that is the project's language. This page is a
> translation of the README, not a localisation of the product. Said here rather than
> discovered after installing — the check names quoted below are the literal strings
> you will see.

## Quick start

Paste this to Claude Code or Codex:

> Install StarkEno from https://github.com/X3n0-io/starkeno on this machine, then verify
> it is collecting.

Or do it yourself. **Two steps, and both are required** — the plugin is only a manifest,
and without the package the hooks run, import nothing, and exit `0` in silence:

```bash
pip install git+https://github.com/X3n0-io/starkeno.git
```

```bash
claude plugin marketplace add X3n0-io/starkeno
claude plugin install starkeno@starkeno-local
```

Restart the agent, approve the hooks, work one normal turn, then:

```bash
starkeno doctor     # is it actually collecting?
starkeno report     # the bill
```

If `doctor` is not green, believe `doctor` — not the absence of errors. A silent StarkEno
looks exactly like a working one.

## The bill

```bash
starkeno report                                          # generates and opens it
starkeno report --output bill.html --no-open             # or just write the file
```

A static HTML page on your disk. It starts no server, makes no network call and does not
touch the database. What it shows, and why each column is there:

| Column | What it counts | Why you care |
|---|---|---|
| **Cost of work** | tokens the model actually produced | the only part that is the job |
| **Cost of loading** | context written into the cache | the price of setting the job up |
| **Cost of re-reading** | context read back on later turns | paid again on every turn, for the same material |
| Unknown outcomes | calls whose success could not be determined | how much of the picture is guesswork |
| Unclassifiable rows | calls whose token breakdown contradicts itself | how much to distrust |

The last two rows are the ones other tools do not show you. A number you cannot check is
worth less than a smaller number you can, and the forecast is only as good as the
measurement it is scored against.

An illustrative shape — *your numbers will differ, and the ratio is the interesting part*:

```
1 678 calls, 2 036 actions

  cost of work         10 500 000     15%
  cost of loading      20 150 000     28%
  cost of re-reading   41 750 000     58%   <-- the same context, again and again
```

The same totals are broken down by project, model, session, skill, plugin and MCP
server, plus the local rhythm of the last seven days. **The skill, plugin and MCP labels
overlap and must never be summed** — one call can carry all three.

## Install

### Let your agent do it

Paste this to Claude Code or Codex:

> Install StarkEno from https://github.com/X3n0-io/starkeno on this machine, then verify
> it is collecting.

**Instructions for the agent.** There are two steps and skipping the first is the common
failure: the plugin is only a manifest, and without the package the hooks run, fail to
import anything, and exit `0` in silence.

1. Install the package. Requires Python 3.12–3.14 on `PATH`:
   ```bash
   pip install git+https://github.com/X3n0-io/starkeno.git
   ```
   Verify with `starkeno --help`. If the command is not found, the user's `pip` and
   `python` are different installations — resolve that before continuing.

2. Install the plugin for the agent in use. For Claude Code:
   ```bash
   claude plugin marketplace add X3n0-io/starkeno
   claude plugin install starkeno@starkeno-local
   ```
   For Codex, add the same repository as a marketplace from its plugin panel and install
   `starkeno`. Do not hand-edit `~/.codex/config.toml`.

3. Have the user restart the agent and approve the hooks when asked. Hooks are read at
   session start, so nothing collects until then.

4. After one completed turn, verify:
   ```bash
   starkeno doctor
   ```

| What it says | What it means | What to do |
|---|---|---|
| `raccolta: nessun evento raccolto` | nothing has ever been collected | the package is missing, or the hooks were never approved |
| `plugin_claude_aggiornato: ... diverso dal pacchetto` | the installed plugin copy is older than the package | refresh it through the agent; never delete the cached copy by hand, that uninstalls it |
| `inventario_storici: la raccolta sta scrivendo altrove` | rows are landing in a database no command reads | nothing is lost; the two need merging |
| `schema: schema disallineato` | the database predates the current revision | report it to the user rather than migrating silently |

Do not report success until `starkeno doctor` shows a recent collection. A silent
StarkEno looks exactly like a working one.

### Do it yourself

StarkEno is **two separate things, and you need both**:

1. the **Python package**, which does all the work;
2. the **plugin** for your agent, which is only a manifest saying when to call it.

Installing the plugin does **not** install the package. If the package is missing, the
hooks still run, fail to import it, and exit `0` in silence — by design, because a hook
must never break your turn. The result is an agent that looks instrumented and collects
nothing, with no error anywhere. `starkeno doctor` is what tells you; run it after
installing.

You need Python 3.12, 3.13 or 3.14 on your `PATH`. There is no PyPI release yet, so the
package comes straight from git:

```bash
pip install git+https://github.com/X3n0-io/starkeno.git
```

Or from a clone, if you want the source to hand:

```bash
git clone https://github.com/X3n0-io/starkeno.git
cd starkeno
pip install .
```

Then install the plugin for your agent — Codex below, Claude Code after it.

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

## Checking that it is collecting

Start here:

```bash
starkeno doctor
```

Four of its checks answer four different questions, and each one has been the thing that
was actually wrong at least once:

| Check | Says |
|---|---|
| `raccolta` | whether anything has been collected recently at all |
| `plugin_claude_aggiornato` | whether the installed plugin copy matches your package |
| `inventario_storici` | whether some *other* database has newer rows than the canonical one — the signature of collection being written to the wrong file |
| `schema` | whether the database has been migrated to the current revision |

A misrouted collection does not look broken. The hook succeeds, the rows are complete,
and they land in a file nothing else reads. `inventario_storici` exists because that
happened, and went unnoticed for four days.

**Calls are grouped by `project`, which is the last segment of the working directory the
agent session was started in** — not the repository you happen to be editing. If you open
your agent in one folder and work on code in another, the rows carry the first one.

For the raw numbers:

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

## Updating

**Correcting the code does not update what runs on your machine.** Agents install a
plugin by *copying* it into their own cache, and that copy — not your working tree — is
what executes. Fixing a hook in the repository, or even pulling a new version, changes
nothing until the agent re-copies it.

This is the single most important thing to know about running StarkEno, because it fails
silently in both directions: the repository looks fixed, the machine keeps running the
old code, and hooks are not allowed to complain.

To update:

```bash
git pull
pip install .
```

then update the plugin **through the agent itself** — its plugin command or panel — so it
refreshes its copy. Do not delete the cached copy by hand: the agent records the install
path, and removing the directory uninstalls the plugin rather than refreshing it.

Then verify:

```bash
starkeno doctor
```

`plugin_claude_aggiornato` compares the installed copy against the package you have and
says `attenzione` when they differ. It is the check that turns "I fixed it days ago" into
something you can see.

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

## The forecast: estimate against execution

This is the half the project is for.

Preflight estimates what a Blueprint *should* cost. The hooks record what the agent
*actually* spent. The comparison puts the two side by side: where the observed total falls
inside the estimated band, and the per-node gap, ordered by size. Run it again next week
and you can see whether the forecast is getting closer.

> ### What "not shipped" means, precisely
>
> **The plugin does not register these tools.** It installs hooks and a skill, not an MCP
> server. To reach the forecast you must register `python -P -m starkeno.mcp_server` as a
> stdio MCP server yourself, and you must hand it a structured Blueprint — Preflight does
> not yet read a workflow described in prose.
>
> That is deliberate, not an oversight. This half has been checked against a real
> execution **once**, and against synthetic fixtures otherwise. The project does not ship
> what it has not measured. The bill and the diagnosis need none of it.
>
> If you want to help answer the open question, this is the part to try.

### Why the comparison can be trusted even when the forecast is wrong

A forecast is only worth what the scorekeeping behind it is worth. Three decisions carry
that weight, and they are the reason the 9x above is believable as a *measurement* rather
than as an artefact:

**Attribution is declared, never guessed.** The agent marks each change of node as it
works. Calls that fall outside every declared interval are reported as unattributed rather
than assigned to a neighbour. A number on the wrong node sends the calibration in the
wrong direction, which is worse than a number left unclaimed.

**Attribution is a view, not a stamp.** It is computed at comparison time and never
written as a column on the collected row. Closing a run twice recomputes it. The raw
measurement stays raw, so a mistake in the attribution logic is fixable after the fact
instead of baked into your history.

**When it cannot tell, it stops.** If the window contains more than one session, the
comparison halts and says so instead of picking one. Observed on real data: this fires on
10–25% of windows, and the dominant cause is genuine concurrency between sessions.

Both sides declare their holes. Observed calls whose model is not mapped to a Blueprint
model, or whose token breakdown is missing or contradicts itself, are counted and named
instead of being priced at a plausible-looking number; and when the Blueprint leaves a
price out, the estimate says which model it could not price. Money is reported as
**absent, not zero**, when there is no complete price list at all, or when the price lists
use more than one currency.

### The 9x, in the output

One gap is expected and is not a defect: the simulation counts `cache_write` once per
invocation and `cache_read` only on retries, while a real agent resends the context every
turn. Observed cache reads will be much larger than estimated ones, systematically. The
output says so, because the first person to see it will think they got a subtraction
wrong.

### The tools

Three MCP tools drive it, alongside `log_agent_action`. None of them raises: errors come
back as plain text, and nothing is recorded.

| Tool | What it does |
|---|---|
| `blueprint_run_start` | Opens a run against a stored `preflight analyze --format json` output and returns its `run_key`. The analysis is kept verbatim, so the run is compared against the estimate you were shown, not one recomputed later. |
| `blueprint_run_node` | Declares that work has moved to a node. Unknown node ids are rejected and the message lists the valid ones. |
| `blueprint_run_end` | Closes the run and returns the comparison. Calling it again on a closed run recomputes it — attribution is a view, not a stamp on the collected rows. |

To read the same comparison from a terminal, without spending the agent's tokens:

```bash
starkeno consuntivo --elenco                 # list the recorded runs
starkeno consuntivo --run <run_key>          # the comparison as text
starkeno consuntivo --run <run_key> --json   # the same, machine-readable
```

The command opens the database read-only: it creates nothing and migrates nothing. On a
machine where the hooks have not collected yet, it says so and exits non-zero.

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
## How it is built, and why

The decisions below are all measured, and the
measurement is written next to each one. They are here rather than in the install
instructions because you do not need them to use StarkEno — only to change it.

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

### Why the skill exists twice

`skills/starkeno/SKILL.md` and `plugin-claude-code/skills/starkeno/SKILL.md` are the same
file, and a test fails if they stop being identical.

Duplication is normally the wrong answer, and this project has twice paid for two copies
of one rule drifting apart. Here it is forced: the two harnesses mount **different plugin
roots** from this single repository — Claude Code mounts `plugin-claude-code/`, Codex
mounts the repository root — and a skill under one is invisible to the other. It cannot
live only at the root, because Claude Code cannot see `../skills/`; and Claude Code
cannot mount the root instead, because the `hooks/hooks.json` there is the Codex one,
whose `PLUGIN_ROOT` it does not expand.

Measured on 2026-08-19, twice: first by asking Codex a cost question and watching the
skill *not* fire — which is how the two-roots problem was found at all — and then, after
the second copy existed, by asking again and watching it fire.

### Installing the hooks by hand

The Codex plugin ships `.codex-plugin/plugin.json` and `hooks/hooks.json`, whose commands
use `PLUGIN_ROOT` and the dedicated Windows variants. The Claude Code plugin ships
`plugin-claude-code/`, whose hooks invoke the modules directly and depend on no plugin
path. For a manual trial, use absolute paths to the Python files, then check the
configuration with `/hooks` in the Codex CLI.

> The Codex scripts must be invoked by path. `python -m starkeno.hook_ingestione` from an
> unrelated folder will not find the package unless it is installed; the entry points
> include the bootstrap needed to work from the project folder opened in Codex.

> The Claude Code hooks use `python -P -m`. The `-P` is not decoration: without it the
> first entry of `sys.path` is the **session's working directory**, which takes
> precedence over the installed package. Anyone working inside a checkout of StarkEno
> would run *that* checkout's code instead of the installed one. Measured on 2026-08-19:
> a session whose working directory was an older checkout collected every call correctly
> and wrote them to that checkout's data path, so `report`, `doctor` and `consuntivo` saw
> none of them — with no error and nothing on stderr, because a hook is not allowed to
> produce either.

## What is not done yet

Stated plainly, because a README that hides its gaps costs more than one that names them.

- **The forecast has been scored against reality once.** One run, one machine, one agent.
  Everything else is synthetic fixtures. Until there are more, treat the predictive half
  as an open research question with a working harness, not as a feature.
- **The forecasting half is not shipped.** Its MCP tools exist and are documented above,
  but the plugin does not register them, on purpose — see the note in that section.
- **Preflight does not read prose.** It analyses already-structured Blueprints. Describing
  a workflow in natural language and getting an estimate is the intended surface, not the
  current one.
- **No pinned release.** There is no PyPI package. `pip install git+…` works, but it
  installs whatever `main` happens to be at that moment: there is no tag to pin to, and
  no way to say which version you are running beyond the one in the manifest.
- **The bill reports, it does not forecast.** There is no spending cap and no alerting on
  one: the page tells you what a run cost, never that a run is about to cost too much.
- ~~The skill is unproven on Codex.~~ **Verified on both** on 2026-08-19: asked a cost
  question, Claude Code and Codex each invoked the skill. It took one negative
  measurement first — see *Why the skill exists twice*.
- **Only two agents are measured.** Codex and Claude Code. Antigravity is recognised but
  cannot be measured, because its transcript carries no token counts, and it reports zero
  calls rather than a guess.
- **Thresholds are reasoned, not measured** — see the note at the end of this file.
## What is inside

| | |
|---|---|
| `starkeno/harness.py` | Which agents are recognised, and which can be measured |
| `starkeno/transcript.py` | From `.jsonl` to API calls; a pure module |
| `starkeno/hook_avvia_ingestione.py` | Non-blocking launcher, for Codex |
| `starkeno/hook_ingestione.py` | Idempotent end-of-turn ingestion |
| `starkeno/hook_inizio_sessione.py` | Synchronous session-start hook; states one measured fact after a break |
| `plugin-claude-code/skills/starkeno/` | The skill that tells the agent what StarkEno answers, and when — the copy Claude Code mounts |
| `skills/starkeno/` | The same file, byte for byte, where Codex mounts it. A test fails if the two drift apart |
| `starkeno/conto.py` | Pure model of the bill |
| `starkeno/consuntivo.py` | Pure model of estimate against execution |
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
