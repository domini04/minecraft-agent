# Current Session Progress

**Last Updated**: 2026-05-02
**Current Phase**: Phase 1 ✅ + Phase 2 ✅ complete; Phase 3 next
**Current Stage**: Phase 2 acceptance gate (live smoke 6/6) PASSED at run 7

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

## Test Counts

- **119 unit tests** passing (jest 8 suites + pytest)
- **6 live smoke scenarios** passing (deterministic, automated)

---

## Resume Point

Phase 2 complete and verified. Next: **Phase 3 — Brain v1 (Planner + Executor on LangGraph).**

Phase 3 work involves:
- Add LangGraph + LangChain to `brain/pyproject.toml`
- Implement Planner node: prompts the LLM with goal + bot state, returns next tool call
- Implement Executor node: dispatches the tool via `BodyClient.execute()`, captures result
- Implement state schema (matches `docs/AGENT_STATE.md`)
- LLM provider: Gemini 3 Flash (model-agnostic via LangChain)
- Single-step proof: agent goal "navigate to 100,64,100 then chat hello" succeeds

---

## Phases ahead

3. Brain v1 (Planner + Executor on LangGraph)
4. Knowledge (SOP + Guide Retriever)
5. Resilience (Reflexion + retries)
6. Construction (stretch)
7. Polish (Streamlit, ChromaDB)
