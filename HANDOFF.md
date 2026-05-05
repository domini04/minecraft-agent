# Session Handoff — Phase 3 Kickoff

**Created**: 2026-05-02 (end of session that completed Phases 1+2)
**Next phase**: Phase 3 — Brain v1 (Planner + Executor on LangGraph)
**Branch**: `main` (clean working tree)
**Latest commit**: `04f9e8a` docs(todo): Phase 2 complete — live smoke 6/6 at run 7

---

## TL;DR

Phases 0, 1, 2 are complete. The body process exposes a working `/execute` RPC with all six tools (chat, get_bot_status, navigate, mine, craft, place_block) verified against a **live Minecraft server** by an automated smoke harness (`npm run test:smoke`). The brain side has a working `BodyClient` (Python) that POSTs to `/execute`. **No LLM, no LangGraph, no planner yet** — that is Phase 3.

Open this file first thing next session. Then read `docs/LEDGER.md` for the doc index.

---

## State Snapshot

### Code

- **Body** (Node.js / Express / Mineflayer at `body/`):
  - `body/src/server.js` — Express entry point.
  - `body/src/app.js` — `GET /status` (returns live bot state) + `POST /execute` (RPC dispatcher with 4-min timeout, 6 tool stubs registered).
  - `body/src/bot.js` — Mineflayer bot creation; loads `mineflayer-pathfinder` + `mineflayer-collectblock` plugins; sets default `Movements` on spawn.
  - `body/src/tools/{chat,get_bot_status,navigate,mine,craft,place_block}.js` — all six implementations.
  - `body/src/utils/{response,timeout}.js` — envelope builders + `withTimeout`.
  - `body/test/smoke/` — full live-server smoke harness (see "Smoke harness" below).
- **Brain** (Python / requests at `brain/`):
  - `brain/src/body_client.py` — `BodyClient` class with `get_status()` and `execute(tool, params=None)`. `execute()` uses 300s (5-min) timeout per Decision 19. Raises on HTTP 4xx/5xx (`raise_for_status`). Returns full JSON envelope on 200.
  - `brain/tests/test_body_client.py` — pytest, all mocked.

### Tests

- **119 unit tests** passing across 8 jest suites + pytest. Run from `body/`: `npm test`. Run from `brain/`: `pytest`.
- **6 live smoke scenarios** passing. Run from `body/`: `npm run test:smoke`. See "Smoke harness" below.

### Dependencies (already installed)

- `body/package.json`: `express ^4.21.0`, `mineflayer ^4.20.1`, `mineflayer-pathfinder ^2.4.5`, `mineflayer-collectblock ^1.6.0`. Dev: `jest`, `supertest`.
- `brain/pyproject.toml`: `requests >=2.31.0`. Dev: `pytest >=8.0.0`. Configured: `ruff` (NOT installed; lint not required).

### Live Minecraft server

- Path: `~/minecraft-server/` (Java 21, MC 1.20.4).
- Config (`server.properties`): port 25565, online-mode false, peaceful, max-players 2, level-seed `minecraft-agent-dev`, gamemode survival.
- `agent` is op'd in `ops.json` (level 4) — required for `/give`, `/tp`, `/setblock` in smoke scenarios.
- The smoke harness manages MC server lifecycle automatically; no manual start needed for `npm run test:smoke`.

---

## What's working end-to-end

```
[Brain Python] BodyClient.execute("chat", {"message":"hi"})
   │
   │  POST http://127.0.0.1:3000/execute
   │  body: {"tool":"chat","params":{"message":"hi"}}
   │  timeout: 300s
   ▼
[Body Node] /execute dispatcher (app.js)
   │
   │  validates tool name; dispatches to chat(params, bot)
   ▼
[Body Node] chat tool (tools/chat.js)
   │
   │  validates, calls bot.chat("hi")
   ▼
[Mineflayer] sends chat packet to server
   │
   │  returns {sent: true, message: "hi"}
   ▼
[Body Node] wraps in envelope: {success: true, data: {...}, tool: "chat", duration_ms: 0.5}
   │
   ▼
[Brain Python] returns the envelope dict to caller
```

All 6 tools follow this path. Live verified.

---

## Architecture invariants (DO NOT VIOLATE)

1. **Brain/Body split is load-bearing.** Brain (Python/LangGraph) decides; Body (Node/Mineflayer) executes. They communicate ONLY over the localhost HTTP bridge. The single endpoint is `POST /execute`. Decisions 15–21 in `docs/DECISION_LOG.md` are frozen.

2. **Deterministic tooling.** The LLM does not hold Minecraft mechanics. Tools are human-written, parameter-validated, and return well-typed envelopes. Adding LLM reasoning to a tool body is a project-thesis violation.

3. **Tool envelope shape (frozen):**
   - Success: `{success: true, data: <tool-specific>, tool: <name>, duration_ms: <number>}`
   - Failure: `{success: false, error: {code, message, context?}, tool, duration_ms}`
   - HTTP status is always 200 for tool results; 400 for protocol errors (malformed request, unknown tool); 500 for unhandled exceptions.

4. **Out of scope for tools (Phase 5/6 work, do NOT add now):** retry logic, partial-success envelopes, ToolError class, per-tool LangSmith hooks, tool durability.

---

## Smoke harness — `npm run test:smoke`

Located at `body/test/smoke/`. Fully automated end-to-end:

1. Resets the world (`rm -rf world/ world_nether/ world_the_end/` in `~/minecraft-server`).
2. Patches `ops.json` to op the bot.
3. Spawns the MC server child process; waits for `Done (Xs)!` log line (default timeout 120s).
4. Spawns the body server child process; waits for `[Bot] Spawned in world` AND `GET /status` returning `bot != null`.
5. Runs 6 scenarios in order: `00-chat`, `01-get-bot-status`, `02-navigate`, `03-place-block`, `04-mine`, `05-craft`.
6. Tears down body (SIGTERM), MC server (`stop\n` to stdin), removes PID file.
7. Writes `body/test/smoke/results/last-run.json` with full per-scenario data.

CLI flags:
- `--keep-world` — skip world reset (faster iteration).
- `--force-kill` — bypass orphan-detection refusal.
- `--dry-run` — exercise harness without spawning MC (Tier 1 tests).
- `--help` — usage.

Other entry points:
- `npm run dev:up` — start MC + body, foreground tail of combined logs prefixed `[mc]`/`[body]`, Ctrl-C tears both down.
- `npm run dev:down` — kill running smoke processes via `.pids` file.
- `npm run test:smoke:keep` — alias for `--keep-world`.

Env vars: `MC_SERVER_DIR` (default `$HOME/minecraft-server`), `BOT_HOST`, `BOT_PORT`, `MC_HOST`, `MC_PORT`, `MC_USERNAME`, `SMOKE_MC_READY_TIMEOUT_MS`, `SMOKE_BOT_READY_TIMEOUT_MS`, `SMOKE_SCENARIO_TIMEOUT_MS`, `KEEP_WORLD`.

See `body/test/smoke/README.md` for troubleshooting.

---

## Live-only defects discovered + fixed in iteration loop

These are recorded because they're the kind of bugs that mocked unit tests cannot catch — kept here as **historical context for future tool authors** and as **examples of why live smoke matters**.

1. **`place_block` silent revert** (Sprint 9, commit `e503698`). `bot.placeBlock()` resolves on packet ACK, not actual placement. Server can silently reject and revert via Block-Update packet that arrives after the promise. Fix: tool now reads `bot.blockAt(targetPos)` after a `VERIFY_SETTLE_MS` delay; throws `place_block: placement reverted by server` if the cell is still air or null.

2. **`mine` silent pickup-fail** (Sprint 10, commit `9eb524b`). `bot.collectBlock.collect()` resolves on dig completion, not pickup. Drop can despawn or pickup can race. Fix: tool tracks per-iteration inventory delta; throws `mine: collect resolved but inventory did not increase` if count didn't grow by 1.

3. **`navigate` GoalBlock + 5s thinkTimeout** (Sprint 11, commit `8839db1`). Pathfinder's default 5s thinkTimeout was too short for complex terrain; `GoalBlock` was too strict (bot stops on top of goal block, +1y). Fix: switched to `GoalNear(x, y, z, 1)`; bumped thinkTimeout to 20000ms with save-and-restore; env var `NAVIGATE_THINK_TIMEOUT_MS` overrides.

These three fixes are in `body/src/tools/{place_block,mine,navigate}.js`. All have unit tests covering the new error paths.

---

## Phase 3 — Brain v1 (next session)

### What it is

Add a LangGraph-based agent that reads goals (natural language), plans tool calls via an LLM, executes them via the existing `BodyClient`, and loops until the goal is met or a stop condition fires.

### Source-of-truth docs to read first

1. `docs/LEDGER.md` — start here for doc index.
2. `docs/TECHNICAL_BLUEPRINT.md` — Phase 3 high-level scope (Brain v1 = single-step Planner + Executor).
3. `docs/AGENT_STATE.md` — LangGraph state schema (already designed).
4. `docs/DECISION_LOG.md` — Decisions 1–21. Specifically:
   - Decision 1: LangGraph as orchestration framework.
   - Decision 4: Gemini 3 Flash as primary model, model-agnostic via LangChain.
   - Decision 7: Error handling — 3 retries → report & stop.
5. `docs/PROGRESSION_PLAN.md` — three-stage workflow (Understand → Design → Implement) for Phase 3.

### Decisions still open (need user input at session start)

1. **Gemini API key**: do you have `GEMINI_API_KEY` ready? If not, set up auth first. Alternative: use a different LangChain-supported provider (OpenAI, Claude API, Ollama local) for the proof-of-concept.
2. **Planner prompt strategy**: system prompt design, few-shot examples, tool schema description (JSON schema vs natural-language list).
3. **Stop criteria**: goal-completion check vs fixed iteration cap vs LLM-self-reports-done. Recommend fixed cap (e.g., 10 steps) for v1; intelligent stop in Phase 5.
4. **Initial scope**: single-step ("chat hello") or multi-step ("mine 5 oak_log → craft pickaxe")? Recommend **single-step first** to lock the harness end-to-end, then expand.

### Recommended Phase 3 sprint order

| # | Sprint | Files | Notes |
|---|--------|-------|-------|
| 3a | Add LangGraph + LangChain deps to `brain/pyproject.toml` | `brain/pyproject.toml` | Pure infra; no logic. |
| 3b | Implement state schema (`AgentState` TypedDict) per `docs/AGENT_STATE.md` | `brain/src/state.py` (new), `brain/tests/test_state.py` | |
| 3c | Implement Planner node (LLM call → tool spec) | `brain/src/nodes/planner.py`, tests | LLM mocked. |
| 3d | Implement Executor node (calls `BodyClient.execute`) | `brain/src/nodes/executor.py`, tests | BodyClient mocked. |
| 3e | Wire LangGraph graph: planner → executor → loop with stop condition | `brain/src/graph.py`, tests | |
| 3f | CLI entry point: `python -m brain "navigate to 100,64,100 and chat hello"` | `brain/src/__main__.py` | |
| 3g | Live smoke: agent achieves single-step goal end-to-end | extend `body/test/smoke/` or new `brain/test/smoke/` | The Phase 3 acceptance gate. |

Each sprint = one PGE loop per the project's commit cadence (`memory/feedback_commit_cadence.md`).

---

## Process & cadence (loaded from memory; restated for clarity)

- **Decisions**: never make architectural decisions unilaterally. Present options + tradeoffs + recommendation; wait for explicit user approval. Routine technical choices within a frozen design ARE fine to make autonomously (auto-mode rule).
- **Sprints**: each implementation sprint = one PGE (Planner-Generator-Evaluator) loop. Doc-only sprints don't need PGE.
- **Commits**: only on PGE `[VERDICT:PASS]`. Atomic, scoped to the sprint's target files. Never `git add -A`. Use the project's commit-message style (`type(scope): subject` + body + Co-Authored-By trailer).
- **Memory**: `memory/MEMORY.md` is the index; per-topic markdown files for feedback/project facts. See `feedback_commit_cadence.md`, `feedback_autonomy.md`, `feedback_phase2_cadence.md`.
- **PGE harness sessions**: live in `.pge/<id>/` (gitignored). Each session has `state.json`, `plan.md`, `iteration-N/{generation,evaluation}.md`, `report.md`. Active session ID is timestamp-prefixed.

---

## Quick smoke check at session start

To verify the system is in the documented state:

```bash
# Working tree should be clean
cd /Users/yub/Desktop/Dev/Projects/minecraft-agent
git status

# Latest commit should be 04f9e8a
git log --oneline -1

# Unit tests should be 119/119 green
cd body && npm test
cd ../brain && pytest

# (Optional) Full live smoke — requires ~70s, MC server will start automatically
cd ../body && npm run test:smoke
# Expected: 6 PASS, last-run.json updated, processes cleaned up
```

---

## Pending session-end housekeeping

- Background Minecraft server process: should already be stopped by the smoke harness's cleanup at end of run 7. To confirm: `pgrep -fl 'java.*server.jar'`. If still running, `kill <pid>`.
- Background body process: same; should be down after smoke teardown.

No other state to clean up. Memory files are committed at `~/.claude/projects/-Users-yub-Desktop-Dev-Projects-minecraft-agent/memory/`.
