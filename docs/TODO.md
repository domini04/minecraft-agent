# Current Session Progress

**Last Updated**: 2026-05-10
**Current Phase**: Phases 1–3 ✅ complete; Phase 4 next
**Current Stage**: Phase 3 acceptance gate cleared — live brain smoke `npm run test:smoke:brain` PASS

---

## Completed Phases

### Phase 1 — Skeleton (HTTP Bridge) ✅

- Step 0.4: Project scaffolding
- Step 1.1: Express server (`34d34fc`)
- Step 1.2: Mineflayer bot connection (`34d34fc`)
- Step 1.3: `/status` returns live bot data (`c31ee20`)
- Step 1.4: `BodyClient.get_status()` (`ddbe601`)
- Step 1.5 body: `POST /execute` dispatcher (`c31ee20`)
- Step 1.5 brain: `BodyClient.execute()` (`79e3299`)
- Step 1.6: Unit tests (jest + pytest)

### Phase 2 — Core Tools ✅

All six composite tools implemented + verified on live MC server:

| Tool | Commit | Unit tests | Notes |
|------|--------|------------|-------|
| chat | `4f9455e` | 6 | Trivial |
| get_bot_status | `7babf7d` | 7 | Strategy A (param bot, not module state) |
| navigate | `b9570e8` + `8839db1` | 9+2 | Pathfinder; GoalNear(1) + 20s thinkTimeout |
| mine | `bf376ba` + `9eb524b` | 24+3 | collectblock + post-collect inventory verify |
| craft | `7cea36d` | 25 | Option (c): Brain provides `crafting_table_pos` |
| place_block | `6985dfe` + `e503698` | 15+3 | post-place world-state verify (Sprint 9) |

Plus infra: pathfinder (`07971d9`), collectblock (`4dd0ead`).

### Smoke Test Harness ✅

- Sprint 7: harness scaffolding (`640ca01`)
- Sprint 8: scenario hardening (`19d878b`)
- Sprints 12–14: live-run scenario tweaks (`1f02113`, `cba5d4b`, `4e378c9`)

`npm run test:smoke` from `body/`: full lifecycle automation (MC server start → body server → 6 scenarios → cleanup) with deterministic world reset.

---

## Live Smoke Results — Run 7 (final)

```
| chat                 | PASS   |       3ms |
| get_bot_status       | PASS   |       6ms |
| navigate             | PASS   |   42327ms |
| place_block          | PASS   |    2784ms |
| mine                 | PASS   |    2083ms |
| craft                | PASS   |    2016ms |
```

**Three live-only defects discovered + fixed in this iteration loop:**
1. `place_block` returned success without verifying world state → server-revert detection added.
2. `mine` returned success without verifying inventory growth → post-collect verify added.
3. `navigate` used GoalBlock + default 5s thinkTimeout → switched to GoalNear(1) + 20s.

These are exactly the kind of bugs unit tests with mocks cannot catch. Live smoke + retrospective iteration was the right pattern.

---

### Phase 3 — Brain v1 (Planner + Executor on LangGraph) ✅

Acceptance gate (Sprint 3i) cleared on 2026-05-10. Live single-step run:

```
python -m src "say hello in chat"
→ iter 1: planner picks chat(message="hello") → bot says hello in MC
→ iter 2: planner sees chat in step history → returns no tool call → graph stops
→ CLI exit 0; ~19s wall time; 2 Gemini calls (~$0.001)
```

| # | What | Commit |
|---|---|---|
| 3a | Brain Phase 3 deps | `23453b2` |
| 3b | AgentState (Phase-3 subset) + factory | `531b55e` |
| 3c-new | Shared JSON Schemas + body migration to ajv | `a19fd8f` |
| 3d-new | Brain loader, Pydantic models, ToolResult, PlannerOutput | `653ca4c` |
| 3e | Planner node + provider-agnostic LLM factory | `5acf4cb` |
| 3f | Executor node with defensive error handling | `1588deb` |
| 3g | LangGraph wiring with stop edges | `50460c3` |
| 3h | CLI entry `python -m src "<goal>"` | `5c41bf7` |
| 3j | Planner uses step history (acceptance prerequisite) | `34ef7ef` |
| 3i | Live brain smoke harness + acceptance gate | (this commit) |

---

## Test Counts

- **148 body jest tests** passing (9 suites — adds `validate_params` post-3c-new)
- **102 brain pytest tests** passing (Phase 3 nodes, graph, models, CLI; all stub-based)
- **6 deterministic body smoke scenarios** passing (`npm run test:smoke`)
- **1 live brain smoke scenario** passing (`npm run test:smoke:brain` — real Gemini + live MC)

---

## Resume Point

Phase 3 complete. Next: **Phase 4 — Knowledge (SOP library + tag-based Guide Retriever).**

Open follow-ups (low priority, deferrable):
- `Result:` line cosmetically renders Gemini 3.x structured-content list — extract `.text` for plain display.
- `LangChainPendingDeprecationWarning` from langgraph's import surfaces on stderr; silence at brain entry.
- In-world chat control pane (Decision 28) deferred to Phase 3.5 / Phase 8.

---

## Phases ahead

4. Knowledge (SOP + Guide Retriever)
5. Resilience (Reflexion + retries)
6. Construction (stretch)
7. Polish (Streamlit, ChromaDB)
