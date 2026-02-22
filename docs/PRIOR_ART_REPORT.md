# Prior Art Investigation: MineDojo & Voyager

**Date**: 2026-02-05
**Purpose**: Investigate two existing Minecraft agent projects, learn their approaches, and evaluate relevance to our blueprint.
**Conclusion**: Our design holds up. No architectural changes needed. Several implementation-level patterns identified for reference during Phase 2 and Phase 5.

---

## 1. MineDojo

**Repo**: https://github.com/MineDojo/MineDojo
**Paper**: NeurIPS 2022 Outstanding Paper Award
**Paradigm**: Reinforcement learning research framework

### What It Does

MineDojo treats Minecraft as a Gym-style RL benchmark. Agents receive pixel observations (RGB frames, compass, voxel data) and output low-level actions (movement, camera pitch/yaw, attack, jump). It includes:

- **3,142 benchmark tasks**: Survival, harvesting, tech tree crafting chains, combat
- **Massive knowledge base**: 730K YouTube videos, 7K wiki pages, 340K Reddit posts
- **MineCLIP**: Vision-language reward model trained on YouTube gameplay to score agent behavior

### Relevance to Our Project

**Paradigm mismatch**: MineDojo agents see pixels and press buttons. Our agent sees structured data and calls composite tools. Fundamentally different approach.

| MineDojo Aspect | Relevant? | Notes |
|---|---|---|
| Gym-style RL environment | No | We use LLM planning, not RL training |
| Low-level action space | No | We use coarse composite tools |
| Tech tree task definitions | Minor | Useful as SOP authoring reference — they've enumerated crafting chain dependencies |
| GPT-3 step-by-step guidance | Minor | Validates that LLMs can reason about Minecraft crafting chains |
| Knowledge base (YouTube/Wiki/Reddit) | No | We use human-authored SOPs |
| MineCLIP reward model | No | We use structured tool responses, not vision-based rewards |

**Verdict**: Different paradigm, minimal relevance. The tech tree task definitions may help when authoring SOPs.

---

## 2. Voyager

**Repo**: https://github.com/MineDojo/Voyager
**Paper**: 2023 (NVIDIA Research)
**Paradigm**: LLM-powered autonomous agent — **architecturally closest to our project**

### What It Does

Voyager is a GPT-4-powered agent that continuously explores Minecraft, learns skills, and accumulates a reusable skill library. Four components:

1. **Automatic Curriculum** — LLM proposes next task based on progress history
2. **Action Agent** — LLM generates JavaScript code executed in Mineflayer runtime
3. **Skill Library** — ChromaDB-backed store of learned JS functions + descriptions
4. **Critic Agent** — LLM-based self-verification of task success/failure

### Architecture Comparison

#### Bridge: Python ↔ HTTP ↔ Node.js

| | Voyager | Our Blueprint |
|---|---|---|
| Protocol | HTTP POST (`/start`, `/step`) | HTTP POST (`/execute`) |
| Timeout | 600s | 300s |
| JS server | Subprocess spawned by Python | Standalone Express server |
| Payload | Raw JavaScript code strings | Structured JSON `{tool, params}` |

Voyager independently uses the same Python-HTTP-Node.js pattern, validating our architecture.

#### LLM Code Generation vs. Predefined Tools

**Voyager**: LLM writes raw JavaScript that gets `eval()`'d in Mineflayer.
**Us**: LLM selects from 6 predefined composite tools with structured parameters.

Voyager's code-gen approach was a product of its time (mid-2023):
- Tool calling / function calling APIs didn't exist yet
- Their goal (open-ended lifelong learning) required novel behavior composition
- GPT-4 was their only option and happened to be excellent at code generation

Our predefined-tool approach is better for our goals:
- Modern LLMs have native tool calling with structured output
- `eval()`'ing LLM code is a security and reliability risk
- Our scope is bounded (L2/L3), not open-ended
- Aligns with blueprint philosophy: "Deterministic Tooling — human-written code handles how"

#### Skill Library vs. SOP Store

| | Voyager | Our Blueprint |
|---|---|---|
| Format | JS code + LLM description | YAML with tags, materials, steps |
| Storage | JSON + filesystem + ChromaDB | YAML files |
| Retrieval | Vector similarity (OpenAI embeddings) | Tag keyword match (v1) → ChromaDB (v2) |
| Growth | Dynamic — auto-generated on success | Static — human-authored |

Both converge on the concept of a retrievable knowledge store keyed by natural language. Voyager's dynamic growth suits open-ended exploration; our static SOPs suit bounded scope.

#### Critic Agent vs. Reflexion Node

| | Voyager | Our Blueprint |
|---|---|---|
| Purpose | Verify success/failure | Analyze errors, adjust approach |
| Input | Full game state snapshot | Error + error history |
| Output | `{success, critique}` | Modified plan or adjusted params |
| Trigger | After every action | Only on failure |
| LLM | GPT-3.5-turbo (temp=0) | Same as planner (Gemini 3.0 Flash) |

Our design is cleaner for structured tools — tool responses already indicate success/failure, so we don't need LLM-based verification. Voyager needs it because arbitrary code has unpredictable outcomes.

**Notable detail**: Voyager's critic receives full game state (health, inventory, position, nearby blocks) for context. Worth enriching our Reflexion node's input with `get_bot_status()` data during Phase 5.

### Control Primitives — Implementation Reference

Voyager's JS primitives solve the same Mineflayer integration problems we'll face. Key patterns:

#### `mineBlock.js`
- `findBlocks()` with `maxDistance: 32` (practical over full chunk range)
- `collectBlock.collect(targets, {ignoreNoPath: true, count})` — `ignoreNoPath` skips unreachable blocks instead of throwing
- Failure counter: throws after 10 consecutive failures, suggesting exploration

#### `craftItem.js`
- Searches for crafting table within 32 blocks first
- Falls back to no-table crafting (2x2 recipes) if none found
- `recipesFor(itemId, null, 1, craftingTable)[0]` — takes first available recipe
- Does NOT auto-place a crafting table (differs from our SOP approach where placement is explicit)

#### `placeItem.js` — Most valuable reference
- Tests all 6 adjacent directions (`±x, ±y, ±z`) to find non-air reference block
- Uses `GoalPlaceBlock(position, bot.world, {})` for pathfinder navigation
- Verifies success by checking inventory count before/after placement
- Tracks failure count, throws after 10 failures

#### `exploreUntil.js`
- Biased random walk: random targets 10-30 blocks in specified direction
- Re-targets every 2 seconds via setInterval
- Callback checks if resource was found
- Max duration: 1200 seconds
- We don't have an explore tool, but this pattern is needed inside `mine` for "resource not found" fallback

---

## 3. Summary of Applicable Insights

### Design Validations (no changes needed)
- Python ↔ HTTP ↔ Node.js bridge pattern — independently validated by Voyager
- Predefined composite tools — superior to code generation for bounded scope with modern LLMs
- Static SOP store — appropriate for our scope vs. Voyager's dynamic skill library
- Structured tool responses for success/failure — cleaner than LLM-based verification

### Implementation References (for Phase 2)
- `ignoreNoPath: true` flag on `collectBlock.collect()` — prevents throwing on unreachable blocks
- 6-direction reference block search for `placeItem` — solves the `placeBlock` API translation
- `GoalPlaceBlock` confirmed working for block placement navigation
- Inventory count before/after as placement success check
- `maxDistance: 32` as practical search radius for `findBlocks()`

### Implementation References (for Phase 5)
- Enrich Reflexion node input with full bot status alongside error data
- Explore-on-failure pattern (random walk with callback) for `mine` tool when resources not found
- Failure counters with escalating responses (retry → explore → give up)

### Explicitly Not Adopting
- LLM code generation (`eval()` of LLM output) — security risk, fragile, unnecessary with modern tool calling
- Dynamic skill library growth — adds complexity, not needed for bounded L2/L3 scope
- LLM-based success verification — our structured tool responses already indicate success/failure
- MineDojo's RL/pixel-based approach — fundamentally different paradigm
