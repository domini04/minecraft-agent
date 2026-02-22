# Project Progression Plan

**Date**: 2026-02-05
**Source**: Derived from TECHNICAL_BLUEPRINT.md roadmap, refined with findings from FEASIBILITY_REPORT.md and PRIOR_ART_REPORT.md
**Structure**: 7 phases broken into ~35 concrete steps with clear completion criteria

---

## Development Workflow

**Before each phase begins**, follow this three-stage process:

### Stage 1: Understand(and discuss)
- **What it does** — The component's purpose and functionality
- **Role in project** — How it fits into the larger system architecture
- **How it works** — Internal mechanics at the component level

### Stage 2: Design
- **Create architecture** — Document the component's structure, interfaces, data flow
- **Evaluate** — Review the design for completeness, edge cases, potential issues
- **Approve** — User confirms the design before implementation begins

### Stage 3: Implement
- **Build** — Write the code following the approved design
- **Test** — Verify against completion criteria
- **Commit** — Save progress with atomic commits

This ensures we understand before we build, and design before we code.

---

## Phase 0 — Pre-Development

| Step | Task | Done When |
|---|---|---|
| 0.1 | Technical blueprint creation & clarification | **Done** |
| 0.2 | Mineflayer feasibility assessment | **Done** |
| 0.3 | Prior art investigation (MineDojo, Voyager) | **Done** |
| 0.4 | Project scaffolding & repo setup | **Done** |
| 0.5 | (Obsolete)Minecraft server setup & manual verification | Server running, can join manually, fixed seed confirmed | -> Will opt for local minecraft session instead.
| 0.6 | (Postponed)GCP deployment planning | Services selected, infrastructure documented | -> Will develop using local setup first, then move to deployment.

---

## Phase 1 — Skeleton (HTTP Bridge)

**Goal**: Two processes talking to each other. The bridge works.

| Step | Task | Done When |
|---|---|---|
| 1.1 | **Node.js project init** — Express server with `GET /status` health-check endpoint (no Mineflayer yet) | `curl localhost:3000/status` returns `{ok: true}` |
| 1.2 | **Mineflayer bot connection** — Bot joins the Minecraft server and stays connected | Bot appears in-game, no crashes |
| 1.3 | **Wire bot to Express** — `/status` returns live bot data (health, position, food) | `curl /status` returns `{health: 20, position: {x,y,z}, food: 20}` |
| 1.4 | **Python client** — Simple Python script that calls `/status` and prints the result | Python prints bot status from the running server |
| 1.5 | **POST /execute scaffold** — Express accepts `{tool, params}` and returns a stub response | `curl -X POST /execute` returns `{success: false, error: "not implemented"}` |
| 1.6 | **Unit tests for Express endpoints** | Tests pass for /status and /execute stub |

---

## Phase 2 — Core Tools (Node.js)

**Goal**: Every tool works. The Body is complete.

Order is deliberate — each tool builds on patterns from the previous one.

| Step | Task | Done When |
|---|---|---|
| 2.1 | **`get_bot_status`** — Health, hunger, position, inventory, nearby blocks/entities | Returns full status JSON via cURL |
| 2.2 | **`chat`** — Send a message in-game | Message appears in Minecraft chat |
| 2.3 | **`navigate`** — Pathfinder integration, move to x/y/z | Bot walks to target coordinates |
| 2.4 | **`mine`** — findBlocks + pathfinder + collectblock loop | Bot mines N blocks of target type, items in inventory |
| 2.5 | **`craft`** — Recipe lookup, crafting table detection, 2x2 vs 3x3 handling | Bot crafts items (test: planks from logs, then sticks from planks) |
| 2.6 | **`place_block`** — Reference block search (6-direction), GoalPlaceBlock, placement | Bot places a block at target coordinates |
| 2.7 | **Tool unit tests** — Each tool has tests for success cases and common error cases | All tool tests pass |
| 2.8 | **Integration test** — Manual cURL sequence: mine logs → craft planks → craft sticks → craft table → place table → craft wooden pickaxe | Full crafting chain works via sequential cURL calls |

---

## Phase 3 — Brain v1 (LangGraph Planner + Executor)

**Goal**: Agent can execute simple multi-step commands via LLM planning. No SOPs, no error recovery yet.

| Step | Task | Done When |
|---|---|---|
| 3.1 | **Python project init** — LangGraph, LangChain, Gemini 3.0 Flash setup | LLM responds to a test prompt |
| 3.2 | **Tool definitions** — Define the 6 tools as LangChain tools (name, description, schema) | Tools registered, LLM can see them |
| 3.3 | **Executor node** — Sends tool call to Express, parses response, updates state | Single tool call works end-to-end (e.g., "navigate to 100,64,100") |
| 3.4 | **Planner node** — LLM breaks a goal into a step list (no SOP retrieval yet) | Given "go to 100,64,100 and chat hello", produces 2-step plan |
| 3.5 | **Replanner node** — Advances steps, checks completion, routes to next step or end | Multi-step plan executes to completion |
| 3.6 | **LangSmith integration** — Traces visible in LangSmith dashboard | Can see full node-by-node execution trace |
| 3.7 | **Brain unit tests** — Test planner output format, executor HTTP calls (mocked), replanner routing logic | All brain tests pass |

---

## Phase 4 — Knowledge (SOP Retrieval)

**Goal**: The L2 minimum viable demo works. Core portfolio deliverable.

| Step | Task | Done When |
|---|---|---|
| 4.1 | **Author core SOPs** — YAML files for key crafting chains (wooden pickaxe, stone pickaxe, furnace, iron pickaxe) | 4-6 SOP files with correct tags and steps |
| 4.2 | **SOP loader** — Python reads YAML files from a directory | SOPs load into memory as dicts |
| 4.3 | **Tag-based retriever** — Match user goal keywords against SOP tags | "Get me a stone pickaxe" → returns stone pickaxe SOP |
| 4.4 | **Guide Retriever node** — Integrate retriever into LangGraph flow (Node 1) | Planner receives SOP context for its planning |
| 4.5 | **Retriever tests** — Test tag matching accuracy for various goal phrasings | Correct SOP returned for each test case |
| 4.6 | **End-to-end test** — "Get me a stone pickaxe" completes autonomously | Bot has stone pickaxe in inventory |

---

## Phase 5 — Resilience (Error Recovery)

**Goal**: Agent recovers from common failures. Robust enough for demo.

| Step | Task | Done When |
|---|---|---|
| 5.1 | **Structured error responses** — Standardize error JSON from all Node.js tools | Every tool returns `{success: false, error: "...", context: {...}}` on failure |
| 5.2 | **Retry logic** — Conditional edge: retry < 3 → Reflexion, else → Fail | Failed step retries up to 3 times |
| 5.3 | **Reflexion node** — LLM analyzes error + bot status, suggests correction | Given "no oak_log found", suggests navigate to new area |
| 5.4 | **Explore-on-failure** — `mine` tool handles "not found" with random-walk exploration | Bot explores and retries when blocks aren't nearby |
| 5.5 | **Resilience tests** — Simulate known failure scenarios, verify recovery | Agent recovers from "resource not found", "path blocked", "insufficient materials" |
| 5.6 | **Error documentation** — Document discovered failure scenarios and recoveries | Living error table updated with real cases |

---

## Phase 6 — Construction (Stretch)

**Goal**: Agent can build simple structures from SOPs.

| Step | Task | Done When |
|---|---|---|
| 6.1 | **Building SOP format** — Define YAML structure for coordinate-based construction (block list with relative positions) | Format designed and documented |
| 6.2 | **Author building SOP** — Write a 5x5 house SOP | SOP file with block placements exists |
| 6.3 | **Construction executor** — Sequential `place_block` calls from SOP, layer-by-layer | Agent builds the structure |

---

## Phase 7 — Polish (Stretch)

**Goal**: Portfolio-ready presentation.

| Step | Task | Done When |
|---|---|---|
| 7.1 | **ChromaDB retriever** — Replace tag lookup with vector search | Fuzzy goal matching works |
| 7.2 | **Streamlit UI** — Input box + status display + log viewer | User can interact via browser |
| 7.3 | **Alternative LLM comparison** — Run same tasks with Claude 4.5 Sonnet, GPT-5 Mini | Cost/performance comparison documented |
| 7.4 | **GCP deployment** — Deploy to cloud infrastructure | System runs on GCP, accessible remotely |
| 7.5 | **Portfolio documentation** — README, demo video/GIF, architecture diagrams | Project is presentable |

---

## Testing Strategy

### Per-Phase Testing

| Phase | Test Type | What's Tested |
|---|---|---|
| 1 (Skeleton) | Unit | Express endpoints respond correctly |
| 2 (Tools) | Unit + Integration | Each tool succeeds/fails correctly; full cURL chain works |
| 3 (Brain) | Unit (mocked) + Integration | Planner output format; executor-to-Express calls; replanner routing |
| 4 (Knowledge) | Unit + E2E | Tag matching accuracy; full autonomous crafting chain |
| 5 (Resilience) | Scenario-based | Simulated failures trigger correct recovery paths |

### Testing Considerations

- **Node.js tools**: Test against a live Minecraft server. Mocking Mineflayer at the API level is brittle — the real value is verifying game physics work.
- **Python brain**: Mock the HTTP calls to Express for unit tests. Integration tests require both processes running.
- **End-to-end**: Requires all three systems (Minecraft server, Express, Python) running. These are manual or CI-triggered.
- **Test world**: Use a known seed with predictable resource placement for reproducible tests.

---

## Deployment Strategy

### Components to Deploy

| Component | Type | Requirements |
|---|---|---|
| Minecraft Server | Java process | 2-4 GB RAM, persistent storage, fixed seed |
| Node.js Express (The Body) | Node.js process | Must be low-latency to Minecraft server, persistent Mineflayer connection |
| Python LangGraph (The Brain) | Python process | API access to Gemini, LangSmith |
| ChromaDB (v2) | Database | Persistent vector storage |
| Streamlit UI (v2) | Web app | Public-facing HTTP endpoint |

### Key Constraint

The Minecraft server and the Node.js Mineflayer bot **must** be co-located (same machine or same local network) for reliable, low-latency bot-to-server communication. The Python Brain can be separate since it communicates via HTTP.

### GCP Service Selection

See deployment planning (Step 0.6) — service recommendations to be finalized based on cost/complexity trade-offs.
