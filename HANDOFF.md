# Session Handoff — Phase 4 Implementation Ready

**Created**: 2026-05-10 (end of Phase 3 + Phase 4 design session)
**Branch**: `main` (clean working tree apart from untracked `AGENTS.md`)
**Latest commit**: `2e8486f` docs: handoff for end of Phase 3 session (additional docs commit landing alongside this file)
**Next sprint**: **4a — SOP file format + seed SOPs**

Open this file first. Then `docs/DECISION_LOG.md` (especially the D4 amendment and new D29–D33), then `docs/TODO.md`. All five Phase 4 design decisions are locked; implementation can start immediately.

---

## TL;DR

Phases 0, 1, 2, 3 are complete. Phase 4 design is complete — five decisions (D29–D33) locked in `docs/DECISION_LOG.md`, plus an amendment to D4 superseding "tag-based keyword lookup" with "cache-first LLM router."

Phase 4 implements:
- **SOP library** at `brain/src/sops/` — per-file YAMLs + auto-generated `index.yaml` catalog (D29).
- **Guide Retriever node** — a new LangGraph node that makes one LLM call to pick `{sop_name, count}` from the goal + manifest, with a persistent cache keyed by normalized goal (D30).
- **Declarative SOP scaling** — `scale_sop(sop, n)` multiplies `count_per_unit` fields; no template DSL (D31).
- **Planner prompt extension** — renders the scaled `state.guide` (requires + steps) so the LLM can reason against current inventory (D33).
- **Graph topology update** — `guide_retriever` inserted on the entry edge before `planner`.
- **Phase 4 acceptance gate** — live smoke for a multi-step goal (e.g. craft 1 oak_planks given starting inventory).

Estimated 6–7 PGE sprints (4a–4f, plus optional 4g for the DECISION_LOG amendment if it isn't committed alongside this handoff).

---

## State Snapshot

### Code (post-Phase-3)

```
brain/
  pyproject.toml                  langgraph + langchain + langchain-google-genai + python-dotenv
  src/
    __init__.py
    body_client.py                BodyClient.execute(tool, params) — raw envelope dict
    state.py                      AgentState TypedDict (7 fields), make_initial_state, MAX_ITERATIONS=10
    models.py                     ErrorEnvelope, ToolResult (.from_envelope), PlannerOutput discriminated union
    llm.py                        get_llm() via init_chat_model, _DOTENV_LOADED guard
    graph.py                      build_graph(llm, body_client, announce), run_goal(goal, ...)
    __main__.py                   CLI: python -m src "<goal>"  [--model, --body-url, -v, --no-announce]
    tools/
      __init__.py
      loader.py                   6 args models + drift guard + get_tools() → list[StructuredTool]
    nodes/
      __init__.py
      planner.py                  planner_node — frozen prompt, three response branches, step-history-aware
      executor.py                 executor_node — three defensive error paths, bot_status refresh, pre-action narration
  tests/
    test_body_client.py           12 tests
    test_phase3_deps.py           1 test
    test_state.py                 5 tests
    test_tool_loader.py           ~14 tests
    test_models.py                ~7 tests
    test_llm.py                   5 tests
    test_planner_node.py          ~15 tests (incl Sprint 3j history tests)
    test_executor_node.py         ~12 tests
    test_graph.py                 10 tests
    test_main.py                  14 tests
    (total: 120/120 green; no network, all stubs)

body/
  package.json                    express + mineflayer + pathfinder + collectblock + ajv ^8
  src/
    server.js, app.js, bot.js     express + dispatcher + bot lifecycle
    utils/validate_params.js      ajv-based + per-tool legacy-message translation tables
    utils/{response,timeout}.js
    tools/{chat,get_bot_status,navigate,mine,craft,place_block}.js
                                  (mine has tier-scored selection from Sprint 3l)
  test/smoke/
    run.js                        6 deterministic tool scenarios
    run-with-brain.js             live brain smoke (Phase 3 acceptance gate)
    brain-scenario.js             spawns brain CLI + 5 gating assertions

shared/
  tool-schemas/                   index.json + 6 JSON Schemas (Draft 2020-12)
                                  single source of truth for body validators + brain Pydantic models

docs/
  DECISION_LOG.md                 33 decisions; D4 amended; D29–D33 are Phase 4
  AGENT_STATE.md                  forward-looking schema (Phase-3 subset live, Phase-4 + Phase-5 fields documented)
  TECHNICAL_BLUEPRINT.md
  EXECUTE_API_DESIGN.md
  PHASE1_HTTP_BRIDGE.md
  PROGRESSION_PLAN.md
  TODO.md                         current sprint trail
  LEDGER.md                       doc index
```

### Tests + smoke

- Body jest: **157/157** (9 suites, includes ajv `validate_params` + tier-selection tests).
- Brain pytest: **120/120** (all stub-based; no network).
- Body deterministic smoke: 6 scenarios PASS (`npm run test:smoke`).
- Brain live smoke: 1 scenario PASS (`npm run test:smoke:brain`).

---

## Phase 4 — implementation-ready overview

### Five locked decisions (full text: `docs/DECISION_LOG.md` D29–D33)

| # | Decision | One-liner |
|---|---|---|
| **D29** | SOP storage shape | Per-file `brain/src/sops/<name>.yaml` + auto-generated `index.yaml` catalog. `python -m src.sops.build_index` regenerates; pytest drift-guard. `disabled: true` flag opt-out. |
| **D30** | Retrieval (supersedes D4) | Cache-first LLM router. `guide_retriever_node` makes one call → `{sop_name, count}`. Persistent JSON cache at `brain/.cache/sop_routes.json` keyed by normalized goal; SHA-256 of `index.yaml` is the invalidation fingerprint. 1-retry validation; `"<none>"` sentinel for confirmed no-match. `--no-cache` + `python -m src.sops.cache clear` escape hatches. |
| **D31** | Variable substitution | Declarative `count_per_unit` data fields; pure `scale_sop(sop, n)` multiplies. `scale: false` opt-out flag for "always 1" steps (e.g. crafting table). Count comes from retriever's LLM call (default 1). No template DSL. |
| **D32** | No-SOP fallback | `state.guide = {}` → planner prompt omits the guide section entirely; behavior matches Phase 3. Cache stores `"<none>"`. Stderr log on miss. |
| **D33** | Inventory pre-checks | Planner owns it. Guide Retriever stays inventory-agnostic to preserve cache. Planner prompt is extended to render the scaled guide alongside inventory + an explicit "compare required materials to your current inventory; skip steps already satisfied" instruction. |

### AgentState v2 (Phase 4 additions)

Per Decision 25, `AgentState` adds one Phase-4 field:

```python
class AgentState(TypedDict, total=False):
    # Phase 3 (existing)
    goal: str
    plan: list[dict]
    current_step: int
    step_results: list[dict]
    bot_status: dict
    iteration_count: int
    result: str
    # Phase 4 (new)
    guide: dict           # populated by guide_retriever_node; empty {} on no-match
```

`make_initial_state(goal)` seeds `guide={}`. The drift-guard test from Sprint 3b needs updating to expect 8 fields instead of 7.

### Graph topology change

**Before (Phase 3)**:
```
START → planner → [conditional] → executor → [conditional] → planner → ... → END
```

**After (Phase 4)**:
```
START → guide_retriever → planner → [conditional] → executor → [conditional] → planner → ... → END
```

`guide_retriever` runs exactly once per goal (the retriever caches its result internally; even if it ran multiple times the cache would short-circuit). The post-planner and post-executor conditional edges from Phase 3 stay unchanged.

### Cache spec (D30 — full)

```jsonc
// brain/.cache/sop_routes.json (gitignored)
{
  "schema_version": 1,
  "manifest_fingerprint": "sha256:<hex>",
  "entries": {
    "get me a stone pickaxe":  { "sop_name": "stone_pickaxe", "count": 1 },
    "make 5 stone pickaxes":   { "sop_name": "stone_pickaxe", "count": 5 },
    "craft 3 oak planks":      { "sop_name": "oak_planks",    "count": 3 },
    "say hello in chat":       { "sop_name": "<none>",        "count": null }
  }
}
```

Normalization: `re.sub(r"\s+", " ", goal.lower()).strip()`. No article-stripping, no stemming.

Invalidation on load: compute SHA-256 of current `index.yaml`; if `manifest_fingerprint` mismatches, set `entries` to `{}`. Save with updated fingerprint after writing any new entry.

### SOP YAML format (D29 + D31 + D33)

```yaml
# brain/src/sops/stone_pickaxe.yaml
name: Stone Pickaxe
description: Craft a stone pickaxe from cobblestone and sticks, mining inputs as needed.
tags: [crafting, tools, pickaxe, stone]
yields: 1
disabled: false   # optional; defaults to false
requires:
  - { item: oak_log,     count_per_unit: 3 }
  - { item: cobblestone, count_per_unit: 3 }
steps:
  - { action: mine,  target: oak_log,        count_per_unit: 3 }
  - { action: craft, item:   oak_planks,     count_per_unit: 6 }
  - { action: craft, item:   stick,          count_per_unit: 2 }
  - { action: craft, item:   crafting_table, count_per_unit: 1, scale: false }
  - { action: craft, item:   wooden_pickaxe, count_per_unit: 1, scale: false }
  - { action: mine,  target: stone,          count_per_unit: 3 }
  - { action: craft, item:   stone_pickaxe,  count_per_unit: 1 }
```

Auto-generated catalog (Sprint 4b builds this):

```yaml
# brain/src/sops/index.yaml — AUTO-GENERATED, do not hand-edit
schema_version: 1
sops:
  - name: oak_planks
    file: oak_planks.yaml
    description: Craft oak planks from oak logs.
    tags: [crafting, planks, wood]
    yields: 4
  - name: stone_pickaxe
    file: stone_pickaxe.yaml
    description: Craft a stone pickaxe from cobblestone and sticks, mining inputs as needed.
    tags: [crafting, tools, pickaxe, stone]
    yields: 1
  # ... one entry per SOP file
```

### Guide Retriever prompt (Sprint 4c — frozen at sprint plan time)

System prompt sketch:
```
You are the Guide Retriever for an autonomous Minecraft agent.

Given a user goal, pick the single best matching SOP (Standard Operating Procedure) from the catalog below. If the goal doesn't fit any SOP, return "none".

Also extract the requested count from the goal. Default to 1 if the goal doesn't specify a number. Use integer count only.

Respond in this exact JSON shape, no other text:
{"sop_name": "<name | none>", "count": <integer | null>}

Available SOPs:
- oak_planks     : Craft oak planks from oak logs.                            (tags: crafting, planks, wood)
- stone_pickaxe  : Craft a stone pickaxe from cobblestone and sticks.         (tags: crafting, tools, pickaxe, stone)
- ...
```

Human message: just the goal string. The catalog is part of the system prompt so caching keys only need the goal.

Validation: parse JSON → check `sop_name` is in the manifest or `"none"` → check `count` is positive int (or null when sop_name == "none"). If invalid, retry once with a stronger reminder: `"Your previous response did not match the required JSON shape. Respond with EXACTLY: {\"sop_name\": ..., \"count\": ...}. Allowed names: [<list>]."`. If still invalid → return no-match, log to stderr.

### Planner prompt extension (Sprint 4d)

Existing `_format_human_message` (Sprint 3j) renders goal + bot_status + step_history. Add a new "Active guide" section ONLY when `state.guide` is non-empty:

```
Goal: make 5 stone pickaxes

Bot status:
  position: x=120, y=64, z=-45
  health: 20, food: 18
  inventory: oak_log×3, cobblestone×2

Active guide: Stone Pickaxe (×5)
  Required materials: oak_log×15, cobblestone×15
  Steps:
    1. mine oak_log ×15
    2. craft oak_planks ×30
    3. craft stick ×10
    4. craft crafting_table ×1
    5. craft wooden_pickaxe ×1
    6. mine stone ×15
    7. craft stone_pickaxe ×5

Steps already executed (most recent first):
  (no steps executed yet)

Decide the next single tool call. Compare required materials to your current inventory; skip steps already satisfied. If the goal is fully satisfied, return no tool call.
```

System prompt amendment: add one sentence to the planner's `_SYSTEM_PROMPT` (Sprint 3j) — something like:
> "If an Active guide is provided, treat it as a recommended recipe. Compare its required materials and steps against the bot's current inventory and step history; skip steps already satisfied; deviate from the guide if the current state warrants it."

The frozen-prompt test from Sprint 3j will need updating to match the amended system prompt.

---

## Sprint plan — Phase 4

Each sprint = one PGE loop per `memory/feedback_commit_cadence.md`. Acceptance criteria are defined in the PGE plan for each sprint.

### Sprint 4a — SOP file format + seed SOPs

**Files**:
- `brain/src/sops/__init__.py` (new) — package marker.
- `brain/src/sops/*.yaml` (new) — 5 seed SOPs:
  - `oak_planks.yaml` — 1 oak_log → 4 planks. 1 step.
  - `stick.yaml` — 2 oak_planks → 4 sticks. 1 step.
  - `crafting_table.yaml` — 4 oak_planks → 1 crafting_table. 1 step.
  - `wooden_pickaxe.yaml` — needs 3 planks + 2 sticks + crafting_table; produces 1 wooden_pickaxe. 3–5 steps.
  - `stone_pickaxe.yaml` — full chain ending in 1 stone_pickaxe.
- `brain/tests/test_sop_format.py` (new) — schema validation. Each SOP must have required fields with correct types. Use a small validator helper (PyYAML + Pydantic models or a hand-rolled schema check).

**Acceptance**:
- All 5 SOPs validate against the format schema.
- No `index.yaml` yet (that lands in 4b).
- pytest green (baseline + N).

### Sprint 4b — Loader, build_index, scale_sop, drift guard

**Files**:
- `brain/src/sops/loader.py` (new) — `load_all_sops() -> dict[str, dict]`, `load_sop(name) -> dict`, `scale_sop(sop, n) -> dict`, `manifest_fingerprint(index_path) -> str`.
- `brain/src/sops/build_index.py` (new) — `python -m src.sops.build_index` regenerates `index.yaml` from disk state. Idempotent; preserves field order.
- `brain/src/sops/index.yaml` (new, generated) — initial catalog of the 5 seed SOPs.
- `brain/tests/test_sop_loader.py` (new) — `load_sop`, `scale_sop` (incl. `scale: false` handling), `disabled: true` skipping, `manifest_fingerprint` stability.
- `brain/tests/test_sop_index_drift.py` (new) — drift guard. Asserts `index.yaml` matches what `build_index` would produce now.

**Acceptance**:
- `python -m src.sops.build_index` produces the expected catalog.
- `scale_sop(stone_pickaxe, 5)` produces correctly multiplied counts; `scale: false` steps stay at their per-unit value.
- pytest green; drift-guard test passes against the checked-in `index.yaml`.

### Sprint 4c — Guide Retriever node (with cache)

**Files**:
- `brain/src/sops/cache.py` (new) — `SOPRouteCache` class: load/save, normalize_goal, get/set, clear (CLI subcommand). SHA-256 fingerprint check on load.
- `brain/src/nodes/guide_retriever.py` (new) — `guide_retriever_node(state, *, llm=None, use_cache: bool | None = None) -> AgentState`. Prompt as sketched above. Validation + 1-retry. Populates `state.guide` (with `scale_sop` already applied) or leaves `{}` on no-match.
- `brain/.cache/` (new, gitignored) — cache directory.
- `brain/tests/test_sop_cache.py` (new) — read/write, normalization, fingerprint invalidation, `--no-cache` semantics.
- `brain/tests/test_guide_retriever_node.py` (new) — stub LLM tests: hits cache, misses then hits, validation retries, no-match path, count extraction, scale_sop integration.

Tests use a stub LLM matching the patterns in `test_planner_node.py` (StubLLM with `invoke` recording).

**Acceptance**:
- Cache hits return without LLM call (verifiable via stub recorder).
- Cache misses call LLM, validate, cache result.
- 1-retry on bad LLM output works as specified.
- Manifest fingerprint mismatch drops entries.
- pytest green.

### Sprint 4d — Planner prompt extension for guide context

**Files**:
- `brain/src/nodes/planner.py` (modify) — extend `_format_human_message` to render `state.guide` when non-empty. Amend `_SYSTEM_PROMPT` with the guide-awareness sentence.
- `brain/tests/test_planner_node.py` (modify) — update frozen-prompt assertion; add 3–4 new tests covering "guide present" prompt rendering.

**Acceptance**:
- Frozen prompt updated and asserted exactly.
- Planner with non-empty `state.guide` produces the "Active guide" block in human message.
- Planner with empty `state.guide` produces no guide section (D32 fallback behavior).
- pytest green.

### Sprint 4e — Graph wiring

**Files**:
- `brain/src/graph.py` (modify) — add `guide_retriever` node; entry edge `START → guide_retriever → planner`; `build_graph(llm, body_client, announce, use_cache)` plumbs the new flag.
- `brain/src/__main__.py` (modify) — add `--no-cache` CLI flag plumbed through to `run_goal`.
- `brain/tests/test_graph.py` (modify) — add tests: guide_retriever runs once per invocation; cache plumbing via stub; existing G1–G10 still pass with the new entry node.
- `brain/tests/test_main.py` (modify) — `--no-cache` flag parsed and plumbed.

**Acceptance**:
- Existing graph tests pass (entry edge change is the only graph topology shift).
- New tests verify `guide_retriever` invocation order.
- `python -m src --help` shows `--no-cache`.
- pytest green.

### Sprint 4f — Phase 4 live smoke (acceptance gate)

**Files**:
- `body/test/smoke/brain-scenario.js` (modify) — accept a new optional goal beyond the existing "say hello in chat" so we can target a multi-step goal.
- `body/test/smoke/run-with-brain-multi.js` (new, OR extend existing) — Phase 4 smoke runner.
- Possibly: a body-side helper that pre-seeds inventory (e.g. `/give agent oak_log 5`) so the goal "craft 1 oak_planks" can complete without mining.

**Acceptance**:
- Live run: `python -m src "craft 1 oak_planks"` against live MC + live Gemini.
- Expected: guide retriever picks `oak_planks` (1 LLM call), planner sees the scaled guide, picks `craft(oak_planks, 1)` (1 LLM call), executor dispatches, body crafts, next planner iteration sees the success in history and returns no-tool-call (1 LLM call). CLI exits 0. Total ~3 LLM calls (~$0.001).
- Or a slightly more interesting goal like "make 4 sticks" or "make a crafting table" — Generator picks per cost vs. demo value.

**Cost cap**: 1 PGE iteration's live smoke ≤ ~$0.01. Total Phase 4 acceptance ≤ ~$0.05.

### Sprint 4g (optional, may merge into another sprint) — Docs / DECISION_LOG amendments

If the DECISION_LOG.md amendments aren't already in the same commit as this handoff (they ARE; see `git log`), a small docs-only sprint to:
- Add Phase 4 column to test counts in TODO.md.
- Update PROGRESSION_PLAN.md Phase 4 step list to match the new architecture (current text references "tag-based retriever" — outdated).

Likely just fold into 4a.

---

## Architecture invariants (still DO NOT VIOLATE)

These all carry forward from Phase 3:

1. **Brain/Body split**: brain decides, body executes. Communication only over `POST /execute` (localhost). Decisions 5, 15–21.
2. **Deterministic tooling**: tools are human-written, parameter-validated. No LLM reasoning inside tool bodies.
3. **Single source of truth for tool schemas**: `shared/tool-schemas/*.json`. Decision 26.
4. **Provider-agnostic LLM**: all LLM access via `init_chat_model` (`src/llm.py`).
5. **State immutability** in graph nodes: shallow-copy + rebuild changed fields only.
6. **No-network test discipline**: brain test imports must not pull `requests`/`httpx`/`urllib3`. Lazy imports for `BodyClient`/`BaseChatModel`.

Phase 4 adds one more:

7. **Guide Retriever cache key invariance**: the retriever's cache key MUST stay inventory-independent. Inventory checks belong in the planner (D33), not the retriever. Violating this would defeat the cache.

---

## Open follow-ups (not blocking Phase 4)

| Item | Severity | Notes |
|---|---|---|
| `Result:` line renders Gemini 3.x structured-content list | Low | ~5-line fix in `__main__.py`'s formatter. Polish. |
| `LangChainPendingDeprecationWarning` from langgraph on stderr | Low | One `warnings.filterwarnings` in brain entry. |
| In-world chat control pane (Decision 28) | Deferred | Phase 3.5 or Phase 8. |
| `AGENTS.md` at repo root | Untracked | Codex/Cursor-style sibling of CLAUDE.md from a stray subagent. Keep, delete, or formalize — your call next session. |
| Hard-prereq SOP schema flag | Deferred to Phase 5 | Per D33 — `acquire: prerequisite` vs `acquire: derived` distinction. |
| Eslint jest globals | Pre-existing | Body lint complains about jest-defined names in `*.test.js`. Predates Phase 3 work. |

---

## Quick smoke check at session start

```bash
cd /Users/yub/Desktop/Dev/Projects/minecraft-agent

# Working tree should be clean (modulo AGENTS.md decision)
git status

# Latest commits — should include the Phase 4 docs commit
git log --oneline -3

# Tests should be green
cd body && npm test           # 157 passed
cd ../brain && pytest -q      # 120 passed

# (Optional) Live brain smoke — costs ~$0.001
cd ../body && npm run test:smoke:brain
# Expected: VERDICT: PASS (iterations=2)
```

---

## Decisions waiting for you to lock at next session start

None — all five Phase 4 design decisions are locked in `docs/DECISION_LOG.md` (D29–D33). The next session can start implementation directly with Sprint 4a.

Two micro-decisions that can be made during sprint planning rather than at the doc level:

1. **Which 5 seed SOPs?** Suggested: `oak_planks`, `stick`, `crafting_table`, `wooden_pickaxe`, `stone_pickaxe`. Forms a linear dependency chain that exercises scaling + multiple steps.
2. **Sprint 4f smoke goal?** Suggested: `"craft 1 oak_planks"` (simplest — exercises full pipeline with minimal moving parts) OR `"make 4 sticks"` (slightly richer — exercises scaling). Either works.

---

## Files to touch first thing next session

1. `HANDOFF.md` (this file) — read in full.
2. `docs/DECISION_LOG.md` — confirm D4 amendment + D29–D33 are landed and clear.
3. `docs/TODO.md` — current sprint trail, test counts, Phase 4 plan.
4. `brain/src/state.py` — note where `guide: dict` field gets added in Sprint 4a (will need a `test_state.py` update too).
5. `brain/src/nodes/planner.py` — note the `_format_human_message` and `_SYSTEM_PROMPT` extension points for Sprint 4d.
6. `brain/src/graph.py` — note the entry-edge change spot for Sprint 4e.
7. `~/.claude/projects/-Users-yub-Desktop-Dev-Projects-minecraft-agent/memory/project_phase4_decisions.md` — quick decision summary.

Phase 4 design done. Implementation begins next session at Sprint 4a.
