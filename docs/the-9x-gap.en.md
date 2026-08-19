# The 9x gap

*Last updated: 2026-08-19. Measurements: 2.*

*Read this in [Italian](lo-scarto-9x.md) — Italian is the project's language.*

StarkEno tries to tell you what a coding-agent run will cost **before** it starts. The
first time that forecast was scored against a real execution, it was wrong by nine times.

```
predicted (estimated maximum)     331,500 tokens
observed  (real execution)      3,035,535 tokens
                                ─────────────────
gap                                   9.15x
```

This page says **why**, and asks for help answering the question that follows.

> **331,500 is not an average estimate: it is the `maximum` scenario.** The simulator does
> not produce a number, it produces four scenarios — `optimistic`, `typical`, `prudent`,
> `maximum` — and the one that was nine times off was already its worst case.
>
> You can run it yourself in two commands, with no plugin and no hooks installed: see
> [Try the simulation](../README.en.md#try-the-simulation-right-now).

---

## Why it is not an arithmetic bug

Faced with 9x, the temptation is to hunt for a mistake in the sums. There isn't one. The
simulator does exactly what it was written to do — what it was written to do is the part
that is wrong.

The simulator counts:

- context **written** to the cache (`cache_write`) **once per invocation**;
- context **read back** (`cache_read`) **only on retries**.

That is the model of a call to a model: send a prompt, get a response, retry if something
fails.

A coding agent does not work that way. **It has no memory between turns**, so on every
turn it resends everything it knows: the files it opened, the instructions, the
conversation so far. Not on retries — **always**.

On the machine where this was measured, that re-reading was **60% of a full week's spend**.
The simulator almost never counts it.

> The model was not miscalculating. It was describing the wrong animal: a call to a model
> instead of a conversation with an agent.

## Why this is the content, not the embarrassment

A **random** error is a dead end: if the forecast is wrong unpredictably, there is nothing
to correct and the tool is useless.

A **structural** error is a coefficient. If you know *which* quantity the model fails to
count, and that quantity is measurable, the correction is arithmetic.

Which is why the measurement sits at the top of the README instead of at the bottom of a
backlog. A forecasting tool that hides its own error is worth nothing. The number that
matters about a forecaster is not how often it is right — it is **how wrong it gets, and
whether it is wrong the same way every time.**

## The open question

One of two things is true:

**Hypothesis A — it is a multiplicative constant.** The gap is roughly 9x on any workload.
Then the fix is a single number, and the forecast becomes useful immediately.

**Hypothesis B — it depends on the shape of the work.** A long run re-reads more than a
short one; one full of retries behaves differently from a linear one; one holding twenty
files open is not one that touches two. Then it needs a model per shape, and the work is
far larger.

**One measurement cannot tell them apart.** Literally: a single point does not determine a
slope.

## How you can answer it

What is needed is real executions of **different shapes**. One moves the project; five,
from five different people, closes the question.

You do not need to send me your database, and I do not want it. What is needed is **eight
numbers and a description**.

1. **Record a run.** Follow the forecast section of the README: a structured Blueprint,
   `preflight analyze --confirmed`, then the three MCP tools `blueprint_run_start` /
   `blueprint_run_node` / `blueprint_run_end` around the real work.

2. **Read the comparison.**
   ```bash
   starkeno consuntivo --run <run_key> --json
   ```

3. **Send only the totals**, from both sides: `input_tokens`, `output_tokens`,
   `cache_read_tokens`, `cache_write_tokens`, `totale_tokens` — plus
   `righe_non_scomposte` and `righe_rifiutate`, which say how much to trust the rest, and
   which harness you used. And one line about the **shape** of the work: how long, how
   many files, retries, linear or branching.

4. **Strip what is about you.** Before pasting, delete `project`, `session_id`, `run_key`
   and `blueprint_hash` — the first two say what you were working on. The numbers above
   say nothing about you.

   > If it strikes you as odd that a privacy-first project is asking for data, you are
   > right to notice. That is why the request is manual, voluntary, and limited to numbers
   > that describe nobody. StarkEno sends nothing on its own and never will: if it ever
   > did, it would have stopped being this project.

5. **Open an issue** with the **"Una misura"** template at
   [github.com/X3n0-io/starkeno/issues/new/choose](https://github.com/X3n0-io/starkeno/issues/new/choose).

Every measurement received goes into the table below, credited to whoever sent it.

## Measurements so far

| # | Date | Harness | Shape of the work | Predicted | Observed | Gap | From |
|---|---|---|---|---|---|---|---|
| 1 | 2026-08-18 | Codex | 7 nodes, linear, no retries | 331,500 | 3,035,535 | **9.15x** | the author |
| 2 | 2026-08-19 | Claude Code | long session, 150 turns, loop with retries | 11,098,500 | 34,303,668 | **3.1x** | the author |

## What two points say

Two measurements do not make a curve, but they are **enough to rule something out**:
9.15x and 3.1x are not the same number. The gap is **not a multiplicative constant**, and
hypothesis A — the one that would have made the fix a single number — is the less likely
of the two.

Which means the work ahead is the large one: finding out **what** it depends on. The two
measurements differ in everything — harness, shape, presence of retries, length — so they
isolate no variable yet.

Other numbers from measurement 2, worth more than the ratio itself:

- **Observed re-reading is 97.0% of the spend.** Not 60%: in a long session the
  accumulated context eats everything. The 60% was a week's average, mixing short
  sessions with long ones.
- **On re-reading alone the gap is 5.4x** (33,273,660 observed against 6,168,350
  estimated), while on the total it is 3.1x. The simulator is *most* wrong precisely on
  the line item that weighs most.
- **Against the `typical` scenario the gap is 44x.** Anyone reading the typical instead of
  the maximum would be off by nearly two orders of magnitude.

### What this measurement is not, said before anyone asks

- **It is not a node-attributed `consuntivo`.** It compares totals: no
  `blueprint_run_node` markers, no attribution. Measurement 1 is the stronger of the two.
- **The Blueprint was written afterwards**, describing the shape of the session. The
  per-turn budgets are what a planner would write — the material one turn uses — not the
  accumulated context, which is the consequence the simulator fails to model. It remains
  an after-the-fact description, and someone redoing it with different numbers gets
  different ratios.
- **The window contained two sessions.** A real `consuntivo` would have refused to
  attribute, and would have been right.

What is needed is a measurement done properly — Blueprint written **first**, markers on
the nodes — and done by someone who is not the author.



---

## What is already known, and need not be re-measured

So that nobody spends time on closed questions:

- **The comparison works on real data.** Status `ok`, rows attributed to nodes through the
  database, `righe_rifiutate = 0` and `righe_non_scomposte = 0`. The fear that real data
  would trip the guards did not materialise.
- **The multi-session refusal is not a frequency problem.** It fires on 10–25% of windows
  between fifteen minutes and an hour, and the dominant cause is genuine concurrency
  between sessions, not context compaction.
- **The gap runs in the expected direction.** Observed cache reads are larger than
  estimated ones, always. If anyone measures the opposite, that is big news and should be
  reported immediately.
