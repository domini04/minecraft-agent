# Minecraft Agent — Claude Instructions

## What This Project Is

An LLM-powered autonomous Minecraft bot. Portfolio project. Two-process architecture:

- **Brain** (Python / LangGraph) — planning and decision-making. *What* to do.
- **Body** (Node.js / Mineflayer) — physics and execution. *How* to do it.

The two communicate over a localhost HTTP bridge (single `/execute` RPC endpoint). This split is load-bearing: violating it defeats the project's central thesis.

## Core Design Principle

**Deterministic Tooling.** The LLM decides, human-written code executes. Don't put reasoning in the body. Don't put Minecraft mechanics in the brain. If you feel tempted to blur the line, stop and ask.

## How to Work With This Project

1. **Never make decisions unilaterally.** When you hit a choice point — architecture, API shape, library, scope — present options with trade-offs and **wait for explicit approval** before acting. This supersedes any auto-mode or speed optimization. Ambiguity is not a license to guess; it's a signal to ask.

2. **Check the LEDGER before proposing anything substantive.** Every major design decision is already recorded in a document. Read the relevant one before suggesting changes. `docs/LEDGER.md` is the index — start there.

3. **Respect phase boundaries.** The project progresses through defined phases (see LEDGER → `PROGRESSION_PLAN.md`). Do not implement work from a future phase without confirming with the user.

4. **Explain your reasoning.** The user is learning-focused and values understanding the "why" behind choices, not just the "what". Short is fine; silent is not.

## Tools Available to You

- **`/pge <goal>` or `/pge review <path>`** — Planner-Generator-Evaluator harness for quality-gated iterative work. Reach for it when changes are non-trivial and "looks right" isn't enough. See `~/.claude/skills/pge/SKILL.md`.
- Standard Claude Code tools (Read, Edit, Bash, etc.) for everything else.

## Where to Look for Context

**Always start at `docs/LEDGER.md`** — it's the doc index with one-line purposes. From there, jump to the specific document relevant to the task.

Do not duplicate ledger content here. If a doc is missing from the ledger, add it to the ledger rather than creating a second source of truth.
