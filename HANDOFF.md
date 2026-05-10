# Session Handoff — Phase 3 Complete

**Created**: 2026-05-10 (end of Phase 3 session)
**Branch**: `main` (clean working tree, 4 commits ahead of `origin/main`)
**Latest commit**: `116dfaf` fix(body/mine): tier-scored block selection prevents dig-down trap
**Next phase**: **Phase 4 — Knowledge** (SOP library + tag-based Guide Retriever)

Open this file first thing next session. Then read `docs/LEDGER.md` for the doc index, `docs/DECISION_LOG.md` (decisions 1–28), and `docs/TODO.md` (current sprint trail).

---

## TL;DR

Phases 0, 1, 2, **and 3** are complete. The brain has a working LangGraph planner→executor loop driven by real Gemini 3.1 Flash Lite calls; goals enter via CLI (`python -m src "<goal>"`) and the bot acts on a live Minecraft server. The Phase 3 acceptance gate (`npm run test:smoke:brain`) passed end-to-end with a single-step goal.

This session also added two follow-ups beyond the original plan:
- **Sprint 3k** — Pre-action chat narration: bot announces what it's about to do in MC chat before each non-chat step.
- **Sprint 3l** — Mine-tool fix: tier-scored block selection prevents the dig-down trap observed in live testing.

Phase 4 is the natural next phase — adding the SOP library + tag-based Guide Retriever that lets the agent execute multi-step goals like "get me a stone pickaxe."

---

## State Snapshot

### Phase 3 sprint trail (this session)

| Sprint | Commit | What |
|---|---|---|
| 3a | `23453b2` | Brain Phase 3 deps (langgraph, langchain, langchain-google-genai, python-dotenv) |
| 3b | `531b55e` | `AgentState` TypedDict (Phase-3 subset) + `make_initial_state` factory + `MAX_ITERATIONS=10` |
| 3c-new | `a19fd8f` | Shared JSON Schemas at `shared/tool-schemas/` + body migration to ajv (single source of truth) |
| 3d-new | `653ca4c` | Brain loader: hand-written Pydantic v2 args models, drift guard, `get_tools()`, `PlannerOutput`, `ToolResult` |
| 3e | `5acf4cb` | Planner node + provider-agnostic LLM factory (`get_llm` via `init_chat_model`) |
| 3f | `1588deb` | Executor node with three defensive error paths + bot-status refresh |
| 3g | `50460c3` | LangGraph `StateGraph` wiring with two conditional edges (stop on result-set or cap-exhausted) |
| 3h | `5c41bf7` | CLI entry: `python -m src "<goal>"` with `--model`, `--body-url`, `-v`, exit codes |
| 3j | `34ef7ef` | History-aware planner: human message includes step_results so the LLM can detect goal completion (acceptance gate prerequisite) |
| 3i | `f7c54bf` | Live brain smoke harness + Phase 3 acceptance gate cleared |
| 3k | `40755c7` | Pre-action chat narration (post-Phase-3 polish for demos) |
| 3l | `116dfaf` | Mine tool: tier-scored block selection (post-Phase-3 fix from live observations) |

Plus session housekeeping:
- `ba2a2d2` — chore: project Bash permission allowlist
- `9dc92ee` — docs: Decisions 22–28 logged
- `42aae25` — chore: gitignore `uv.lock`
- `078b94e` — chore: pin default LLM to `gemini-3.1-flash-lite`

### Code

**Brain** (`brain/`):
- `src/state.py` — `AgentState` TypedDict (7 Phase-3 fields), `make_initial_state`, `MAX_ITERATIONS=10`.
- `src/models.py` — `ErrorEnvelope`, `ToolResult` (with `from_envelope` classmethod + cross-field invariant), `PlannerOutput` discriminated union.
- `src/tools/loader.py` — six `<Tool>Args` Pydantic models, drift guard, `get_tools()` returning LangChain `StructuredTool` list ready for `bind_tools()`.
- `src/llm.py` — `get_llm(model=None)` via `init_chat_model`. `_DOTENV_LOADED` guard. Default `google_genai:gemini-3.1-flash-lite`.
- `src/nodes/planner.py` — `planner_node(state, *, llm=None)`. Frozen 3-paragraph system prompt. Human message includes goal, bot_status, **steps history** (Sprint 3j).
- `src/nodes/executor.py` — `executor_node(state, *, body_client=None, announce: bool | None = None)`. Three error paths (out-of-range, malformed envelope, body raise). Bot-status refresh on `get_bot_status` success. Pre-action chat narration via `_format_announcement` (Sprint 3k).
- `src/graph.py` — `build_graph(llm=None, body_client=None, announce=None)` and `run_goal(goal, ...)`. Two conditional edges enforce stop conditions.
- `src/__main__.py` — CLI entry. argparse flags: `--model`, `--body-url`, `--max-iterations` (no-op stderr warning), `-v`, `--no-announce`. Exit codes: 0 (goal complete + all steps success), 1 (incomplete), 2 (caught exception).

**Body** (`body/`):
- `src/utils/validate_params.js` — ajv-based validator helper using shared JSON Schemas. Translation tables map ajv errors back to legacy per-tool message strings (Sprint 3c-new).
- `src/tools/mine.js` — tier-scored block selection: `classifyBlock` / `scoreCandidate` / `selectMineTarget` with `TIER_OFFSET=1000` (Sprint 3l).
- All other body code unchanged from Phase 2.

**Shared**:
- `shared/tool-schemas/{chat,get_bot_status,navigate,mine,craft,place_block}.json` + `index.json` — Draft 2020-12 JSON Schemas. Single source of truth consumed by both body (ajv validator) and brain (Pydantic models via loader).

### Tests

- **Body jest**: 157/157 (9 suites). Includes 29 ajv `validate_params` tests + 9 mine tier-selection tests.
- **Brain pytest**: 120/120. All stub-based — no LLM calls, no network.
- **Body live smoke** (`npm run test:smoke`): 6 deterministic tool scenarios passing.
- **Brain live smoke** (`npm run test:smoke:brain`): single-step goal "say hello in chat" passing end-to-end against real Gemini + live MC.

### Live Minecraft server

- Path: `~/minecraft-server/` (Java 21, MC 1.20.4, port 25565, `online-mode=false`, peaceful, fixed seed `minecraft-agent-dev`, gamemode survival).
- `agent` op'd at level 4.
- Smoke harnesses manage MC lifecycle automatically; for manual demos use `npm run dev:up` from `body/`.

### Decisions added this phase (22–28)

See `docs/DECISION_LOG.md`:
- **22** — LLM via `init_chat_model` + `python-dotenv`, provider-agnostic (default `google_genai:gemini-3.1-flash-lite`).
- **23** — Tool binding via `bind_tools()` (JSON schema, native function-calling) — reliability priority.
- **24** — Phase 3 v1 scope: single-step goals, fixed `MAX_ITERATIONS=10` cap.
- **25** — `AgentState` v1 = Phase-3 subset (7 fields); `guide`/`errors`/`retry_count` deferred to Phases 4/5.
- **26** — Tool schema source-of-truth: shared JSON Schema at `shared/tool-schemas/` (NOT hand-mirrored).
- **27** — Pydantic models for tool args + `PlannerOutput` + `ToolResult` (typed envelopes everywhere).
- **28** — In-world chat control pane deferred to Phase 3.5 / Phase 8 (predefined commands, always-on brain HTTP server).

---

## What's working end-to-end

```
[User] python -m src "say hello in chat"
   │
   ▼
[Brain CLI] argparse → run_goal → make_initial_state → graph.invoke
   │
   ▼
[Planner node] reads goal+bot_status+step_history → bind_tools(get_tools())
                → real Gemini call → AIMessage with tool_calls
   │ appends {"tool_name": "chat", "args": {"message": "hello"}} to state.plan
   ▼
[Conditional edge] current_step < len(plan) → executor
   │
   ▼
[Executor node] (announce skipped — tool is chat itself)
                → BodyClient.execute("chat", {"message": "hello"})
   │
   ▼
[Body /execute] dispatcher → ajv validate → chat.js → bot.chat("hello")
   │
   ▼
[Mineflayer] sends chat packet to live MC server
   │
   ▼
[Executor] coerces envelope to ToolResult → appends to step_results → advances current_step
   │
   ▼
[Conditional edge] iteration_count<10 AND no result → planner
   │
   ▼
[Planner iter 2] sees "[1] chat(message='hello') -> success" in steps history
                → returns AIMessage with no tool calls + content "The goal has already been satisfied."
   │ sets state.result, no plan append
   ▼
[Conditional edge] current_step >= len(plan) → END
   │
   ▼
[CLI] formats summary, exit 0
```

Live smoke artifact captured at `body/test/smoke/results/last-brain-run.json` (gitignored).

---

## Architecture invariants (DO NOT VIOLATE)

1. **Brain/Body split**: brain decides, body executes. Communication only over the localhost HTTP bridge (`POST /execute`). Decisions 5, 15–21 are frozen.
2. **Deterministic tooling**: tools are human-written, parameter-validated, return well-typed envelopes. No LLM reasoning inside tool bodies.
3. **Single source of truth for tool schemas**: `shared/tool-schemas/*.json` (Draft 2020-12). Body validates with ajv; brain generates Pydantic models + LangChain tools. Adding a tool means editing JSON, not duplicating contracts.
4. **Provider-agnostic LLM**: all LLM imports go through `langchain.chat_models.init_chat_model`. No direct provider SDK imports outside `src/llm.py`.
5. **State immutability** in graph nodes: shallow-copy input state, rebuild only changed fields. Never mutate input lists/dicts.
6. **No-network test discipline**: lazy imports for `BodyClient`, `BaseChatModel`, etc. `from src.X import Y` from production code paths must NOT pull `requests`/`httpx`/`urllib3` into `sys.modules` at import time.

---

## Open follow-ups (not blocking, deferrable)

| Item | Severity | Note |
|---|---|---|
| `Result:` line cosmetically renders Gemini 3.x's structured-content list (`[{type, text, extras}]`) | Low | ~5-line fix in `__main__.py`'s formatter to extract `.text`. Polish sprint. |
| `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus` shows up on stderr | Low | One `warnings.filterwarnings(...)` in brain entry. |
| In-world chat control pane (Decision 28) | Deferred | Phase 3.5 or Phase 8. Predefined commands, always-on brain HTTP server. |
| Pathfinder navigate occasional stuck-then-recover | Observed | Body-level pathfinder re-planning. Not a brain concern. May want bigger `thinkTimeout` budgets if it hurts demos. |
| Float-boundary handling for mine support detection | Low | Sprint 3l Option-A picked literal `botFloor.y - 1`; the originally proposed `-0.5` offset was dropped after Planner traced through three position cases. May need revisit if observed mid-pathfinding. |
| `--max-iterations` CLI flag is parsed but no-op | Low | Honoring would require modifying state.py's `MAX_ITERATIONS`. Stderr warning documents this. |
| Eslint config doesn't recognize jest globals in `*.test.js` | Pre-existing | Body lint surfaces `describe/it/expect/jest is not defined` errors. Not introduced by Phase 3 work; predates this session. |
| `AGENTS.md` at repo root — untracked | Decision pending | A subagent created this earlier (~35 lines, near-duplicate of `CLAUDE.md`, Codex/Cursor convention). Decide: keep as a tool-neutral instruction file, or delete. Currently sitting in working tree. |

---

## Phase 4 — what to plan next session

### Goal

Add **SOPs** (Standard Operating Procedures) + a **Guide Retriever node** so the agent can execute multi-step goals like "get me a stone pickaxe" by retrieving a recipe-shaped plan template that the LLM follows step-by-step.

### Per Decision 4 + Decision 8

- SOPs are semi-structured YAML files (one per goal class, e.g. `stone_pickaxe.yaml`).
- Stored under `brain/src/sops/` (or similar — Phase 4 plan picks).
- Each SOP has: `name`, `tags` (for retrieval), `requires` (input items), `steps` (ordered tool-call sequence with placeholders).
- Retrieval is **tag-based keyword lookup** for v1 (NOT vector search). ChromaDB upgrade comes in Phase 7.

### State schema additions (per Decision 25)

`AgentState` gains `guide: dict` field — populated by the Guide Retriever node, read by the Planner.

### New graph topology

```
START → guide_retriever → planner → executor → planner → ... → END
```

The `guide_retriever` is a new graph node. Sits before the planner. Reads `state.goal`, matches against the SOP tag index, populates `state.guide` with the matched SOP (or empty dict if no match — planner falls back to direct LLM reasoning).

### Sprints to plan (rough)

1. **4a** — SOP file format + a few seed SOPs (e.g. `oak_planks`, `crafting_table`, `wooden_pickaxe`, `stone`, `stone_pickaxe`).
2. **4b** — `brain/src/sops/loader.py` + tag-based retrieval helper. Pure function: `find_sop(goal: str, sop_index) -> dict | None`.
3. **4c** — `guide_retriever_node` + tests.
4. **4d** — Update `_format_human_message` to include the matched SOP in the planner prompt.
5. **4e** — Update graph wiring: insert `guide_retriever` before `planner` on the entry edge.
6. **4f** — Live smoke for a multi-step goal (e.g. "craft 1 oak_planks" given a starting inventory) — Phase 4 acceptance gate.

Each sprint = one PGE loop per `memory/feedback_commit_cadence.md`.

### Decisions still to lock at Phase 4 kickoff

1. **SOP storage shape**: one file per SOP, or one consolidated `index.yaml`? Lean toward one-file-per-SOP for git-friendliness.
2. **Tag matching algorithm**: simple substring? Fuzzy? Generator picks; freeze in plan.
3. **Variable substitution in steps**: e.g. an SOP step says `{"action": "mine", "target": "oak_log", "count": "{{count * 4}}"}` — does the brain do template expansion? Probably yes; spec the exact syntax in Phase 4 plan.
4. **What happens when no SOP matches**: brain falls through to direct planner reasoning (Phase 3 behavior). Confirm.
5. **Inventory pre-checks**: SOP `requires` block — does Guide Retriever verify inventory before populating `guide`, or does the planner / executor handle it? Lean toward planner.

---

## Quick smoke check at session start

```bash
cd /Users/yub/Desktop/Dev/Projects/minecraft-agent

# Working tree should be clean
git status

# Latest commit should be 116dfaf
git log --oneline -1

# Tests should be green
cd body && npm test           # 157 passed
cd ../brain && pytest -q       # 120 passed

# (Optional) Live brain smoke — costs ~$0.001 in Gemini calls
cd ../body && npm run test:smoke:brain
# Expected: VERDICT: PASS (iterations=2)
```

---

## Pending session-end housekeeping

- Background MC server: stopped (`pgrep` confirmed clean at session end).
- Background body process: stopped.
- Stale `body/test/smoke/results/.pids` from earlier dev:up: removed at session end.
- `AGENTS.md` at root: still present, untracked. User decision pending — see Open Follow-ups.
- Memory at `~/.claude/projects/-Users-yub-Desktop-Dev-Projects-minecraft-agent/memory/` — Phase 3 decisions captured at `project_phase3_decisions.md`. May want to add a Phase 4 prep memo at next session start.

---

## Files to touch first thing next session

1. `HANDOFF.md` (this file) — read in full.
2. `docs/LEDGER.md` — confirm doc index is current.
3. `docs/TODO.md` — sprint trail + test counts + Phase 4 next-step pointer.
4. `docs/DECISION_LOG.md` — Decisions 22–28 are the freshest; Phase 4 will likely add 29–3X.
5. `docs/PROGRESSION_PLAN.md` — Phase 4 step list (probably needs a refresh against the sprint shape outlined above).
6. `~/.claude/projects/-Users-yub-Desktop-Dev-Projects-minecraft-agent/memory/MEMORY.md` — quick context refresh.

Phase 3 done. Ready for Phase 4 when you are.
