---
name: starkeno
description: >
  Answer what the user's coding-agent work actually costs, from data StarkEno has
  already collected on this machine. Use whenever the user asks how much a session or
  project cost, where tokens are going, why something felt expensive or slow, what the
  biggest cost driver is, or asks to see the bill or the spend breakdown. Triggers on
  "how much did this cost", "where am I wasting tokens", "why was this so expensive",
  "show me the bill", "token spend", "cost breakdown", "what did today cost". Also use
  it when StarkEno looks installed but is collecting nothing.
---

# StarkEno

StarkEno re-reads the transcripts the agent already writes and reconstructs what the
user's way of working costs, broken down by project, model, session, skill, plugin and
MCP server. It does not watch the user type and does not wrap the agent.

**Everything stays on this machine.** StarkEno makes no network call, and neither should
you on its behalf.

## Answering a cost question

```bash
starkeno report --no-open
```

This writes a static HTML file and prints its path. It starts no server and does not
modify the database. Read the file and answer from it.

For the raw figures without the page, query the database read-only. For runs compared
against an estimate, `starkeno consuntivo --elenco` lists them and
`starkeno consuntivo --run <key>` shows one.

## Rules that matter more than the answer

- **Never invent a number.** If something is not in the output, say it is not collected.
  A confident wrong cost figure is worse than "StarkEno does not measure that".
- **Tokens are the unit, not the point.** Name the waste — context re-read on every
  turn, a file re-opened ten times, a task that took three attempts — and use the
  numbers as evidence. A total alone tells the user nothing they can act on.
- **The three cost columns are not interchangeable.** Work, loading and re-reading
  answer different questions; re-reading being the largest is the normal and most
  actionable finding.
- **The skill, plugin and MCP labels overlap.** Never sum them.

## When the numbers look wrong or missing

Run the diagnosis first and fix what it reports before trusting any figure:

```bash
starkeno doctor
```

- `starkeno: command not found` — the Python package is not installed. Installing the
  plugin does **not** install it; they are two separate steps. Point the user at the
  install section of the project README and offer to run it.
- `raccolta: nessun evento raccolto` — nothing has ever been collected. Usually the
  package is missing, or the hooks were never approved in this agent.
- `inventario_storici: la raccolta sta scrivendo altrove` — collection is landing in a
  database no command reads. The rows are not lost; say so, and that they need merging.
- `plugin_claude_aggiornato: ... diverso dal pacchetto` — the installed plugin copy is
  older than the package. The agent must refresh its own copy; deleting the cached copy
  by hand uninstalls it instead.
- `schema: schema disallineato` — the database predates the current revision.

## When not to use this skill

For questions about the agent's *output* — whether the code is right, whether the task
succeeded. StarkEno measures what was spent, never what was obtained.

<!-- Questa skill esiste in DUE copie, e devono restare identiche:
     `skills/starkeno/SKILL.md`                      <- radice del repo, la monta Codex
     `plugin-claude-code/skills/starkeno/SKILL.md`   <- la monta Claude Code
     I due harness montano radici di plugin diverse dallo stesso repository, quindi una
     copia sola e' invisibile a uno dei due: misurato il 19/08/2026 chiedendo a Codex
     quanto avesse speso, e la skill non e' partita.
     `test_le_due_copie_della_skill_restano_identiche` diventa rosso se divergono. -->
