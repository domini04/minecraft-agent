# Decision Log: Autonomous Minecraft Builder Agent

This document records the architectural and technical decisions made during blueprint clarification. Each entry captures the context, options considered, and reasoning behind the chosen direction.

---

## Decision 1: Server Environment

**Question**: What Minecraft server environment will the bot connect to?

**Context**: The project is a personal portfolio piece — no multiplayer, no mods needed. Priorities are ease of setup and ease of bot integration.

| Option | Considered | Notes |
|--------|:---------:|-------|
| Vanilla Java Edition | **Chosen** | Simplest setup. Most recognizable to portfolio reviewers. Mineflayer has full protocol support. No unnecessary features. |
| Paper/Spigot Server | Rejected | Admin control and plugins are unnecessary for a single-bot portfolio project. Adds complexity without benefit. |
| Singleplayer LAN | Rejected | Can't run headless, not automatable, not reproducible. Bad for demos and portfolio presentation. |

**Decision**: Vanilla Java Edition server with `online-mode=false` for local bot auth.

---

## Decision 2: Primary LLM Model

**Question**: Which LLM model will serve as the primary "Brain"?

**Context**: The blueprint originally referenced outdated models (OpenAI/Anthropic generic). The agent makes many API calls per task, so cost matters. The model needs reliable tool-calling for structured output.

| Option | Considered | Notes |
|--------|:---------:|-------|
| Gemini 3.0 Flash | **Chosen** | $0.50/1M input, $3.00/1M output. Fast, cost-effective for high-frequency tool dispatch. Sufficient reasoning for plan-and-execute pattern. |
| Claude 4.5 Sonnet | Deferred | Stronger reasoning but more expensive. Will be tested post-development for comparison. |
| GPT-5 Mini | Deferred | Will be tested post-development for cost/performance comparison. |

**Decision**: Gemini 3.0 Flash (`gemini-3-flash-preview`) as primary model. Claude 4.5 Sonnet and GPT-5 Mini for post-development benchmarking.

---

## Decision 3: Model Flexibility

**Question**: Should the system be locked to one LLM provider or designed to swap models?

**Context**: LangChain/LangGraph natively supports model abstraction via `BaseChatModel`. Making the system provider-agnostic is nearly free in terms of implementation effort.

| Option | Considered | Notes |
|--------|:---------:|-------|
| Model-agnostic (via LangChain) | **Chosen** | Allows model swaps via configuration. Demonstrates good software design in portfolio. Enables post-development model comparison. Near-zero additional effort. |
| Hardcoded provider | Rejected | Locks in one SDK. No benefit over the abstract approach. |

**Decision**: Model-agnostic design using LangChain's `BaseChatModel` interface.

---

## Decision 4: RAG / SOP Retrieval Strategy

**Question**: How should the agent find the right SOP (Standard Operating Procedure) for a given task?

**Context**: The SOP library will be small (<100 documents). Vector DB is overkill for this scale but has portfolio value. The priority is debuggability during development.

| Option | Considered | Notes |
|--------|:---------:|-------|
| Tag-based keyword lookup (v1) | **Chosen for initial development** | Dead simple. Deterministic — you can see exactly which SOP was selected and why. Easy to debug during core pipeline development. |
| ChromaDB vector search (v2) | **Chosen as later enhancement** | Enables fuzzy matching ("make me a shelter" → "house" SOP). Adds portfolio value. The swap is clean via LangChain's `BaseRetriever` interface. |
| FAISS | Rejected | Same overhead as ChromaDB without the server/persistence features. No clear advantage. |
| SOPs in prompt context | Rejected | Works for small sets but doesn't demonstrate retrieval architecture. |

**Reasoning for phased approach**: Debugging clarity. During development, when the agent fails, you need to know: was the retrieval wrong, or was the plan wrong? Tag lookup makes retrieval transparent. ChromaDB adds a "why did it pick this?" debugging layer. Adding it after the core pipeline works means you only debug one thing at a time.

**Decision**: Tag-based lookup for v1, ChromaDB as a v2 enhancement.

---

## Decision 5: Brain ↔ Body Communication Pattern

**Question**: How should the Python Brain communicate with the Node.js Body?

**Context**: Minecraft actions can take seconds to minutes (pathfinding across map, mining multiple blocks). The communication pattern must handle this without unnecessary complexity.

| Option | Considered | Notes |
|--------|:---------:|-------|
| Synchronous HTTP | **Chosen** | Simple blocking requests. Python sends POST, Express blocks until Mineflayer action completes, returns result. With generous timeouts (~5 min), handles most actions. |
| Async fire-and-poll | Rejected for now | Requires task tracking on Node.js side, polling logic in Python. More complex. Available as an upgrade path if timeout issues arise. |
| WebSocket (event-driven) | Rejected for now | Most complex. Real-time streaming is unnecessary when the LLM processes steps sequentially. |

**Reasoning**: The agent executes one tool call at a time (plan → execute step → check → next step). There's no benefit to async communication when the Brain waits for each result before deciding the next action. Synchronous keeps the Tool Executor node trivial: send request → get result → pass to next node.

**Decision**: Synchronous HTTP with generous timeouts. Upgrade to async polling only if timeout issues arise.

---

## Decision 6: User Interface

**Question**: What interface does the user interact with?

**Context**: Portfolio project. The UI needs to support development workflow (fast iteration) and eventual demo presentation (visual appeal).

| Option | Considered | Notes |
|--------|:---------:|-------|
| CLI first, Streamlit later | **Chosen** | CLI is what you use during development anyway. Streamlit adds visual polish for portfolio. Separating them means UI work doesn't block core agent development. |
| Streamlit from the start | Rejected | Adds a dependency and maintenance burden during the phase when focus should be on agent logic. |
| CLI only | Rejected | Misses portfolio presentation opportunity. |

**Decision**: CLI for development (v1), Streamlit for portfolio presentation (v2).

---

## Decision 7: Agent Capability Scope

**Question**: What should the agent be able to do? Where does "done" live on the complexity spectrum?

**Context**: Minecraft agent capabilities range from single actions (L1) to continuous survival (L4). Each level is a significant jump in complexity. A portfolio project needs a clear "done" condition.

| Level | Description | Decision |
|-------|-------------|----------|
| L1 | Single actions (mine, navigate) | Included — building block for L2 |
| L2 | Multi-step dependency chains ("Get me a stone pickaxe") | **Minimum viable demo** |
| L3 | Basic construction ("Build a 5x5 house") | **Stretch goal** |
| L4 | Survival loops (reactive, continuous) | Out of scope — fundamentally different architecture (event-driven, not plan-execute) |

**Reasoning**: L2 demonstrates the full agent pipeline (retrieve SOP → plan → execute → replan) with meaningful complexity (dependency chains). L3 adds spatial reasoning and block placement. L4 requires a reactive architecture that conflicts with the plan-and-execute pattern — it's essentially a different project.

**Decision**: L2 minimum, L3 stretch, L4 out of scope.

---

## Decision 8: SOP Format

**Question**: What format should Standard Operating Procedures follow?

**Context**: SOPs are the agent's "knowledge" — they tell it how to accomplish tasks. The format affects both authoring effort and execution reliability.

| Option | Considered | Notes |
|--------|:---------:|-------|
| Semi-structured YAML | **Chosen** | Structured enough for deterministic execution (tags, materials, ordered steps). Human-readable enough to author quickly. Aligns with deterministic tooling philosophy — LLM follows steps, doesn't interpret prose. |
| Rigid JSON schema | Rejected | Harder to author with no meaningful advantage over YAML for this use case. |
| Free-text natural language | Rejected | Requires the LLM to *interpret* instructions, not just *follow* them. Adds error surface (miscounted materials, skipped steps). Violates the principle that the LLM decides "what" not "how." |

**Authoring workflow**: Draft each SOP in natural language first (to think through the logic), then convert to the YAML template. Natural language serves as the "design" step; YAML is the "implementation."

**Decision**: Semi-structured YAML templates. Author via natural language draft → YAML conversion.

---

## Decision 9: Error Handling & Retry Policy

**Question**: How should the agent handle failures? How many retries? What happens when retries are exhausted?

**Context**: Minecraft is unpredictable — resources may not be nearby, paths may be blocked, the bot may encounter unexpected terrain. The agent needs a clear failure protocol.

| Aspect | Decision | Reasoning |
|--------|----------|-----------|
| Max retries | 3 per step | Balances persistence with avoiding infinite loops. 3 attempts with different approaches is usually enough to determine if a step is feasible. |
| On exhaustion | Report failure and stop | Clean exit. User sees what failed and why. Safer than skipping steps (which could cascade into worse failures). |
| Monitoring | LangSmith tracing | Full visibility into every node execution. Post-mortem analysis of where and why failures occur. |
| Documentation | Living failure scenario doc | Pre-document known scenarios. Add new ones as discovered during development. Serves as both debugging reference and portfolio artifact. |

**Decision**: 3 retries → report & stop. LangSmith monitoring. Maintained failure scenario document.

---

## Decision 10: Tool Granularity

**Question**: Should the Mineflayer tools be fine-grained primitives or coarse composite actions?

**Context**: This determines how much decision-making the LLM does per action. Fine tools = more LLM calls + more LLM decisions. Coarse tools = fewer calls + code handles the "how."

| Option | Considered | Notes |
|--------|:---------:|-------|
| Coarse (composite) | **Chosen** | Each tool is a complete action (e.g., `mine` handles find → navigate → dig → collect). LLM decides "what" to do; code handles "how." Fewer API calls, lower cost, smaller error surface. Aligns with Brain/Body philosophy. |
| Fine (primitives) | Rejected | 20+ API calls to mine 5 logs. Each call costs tokens. More opportunities for the LLM to make mistakes. Pushes the "how" back onto the LLM. |
| Hybrid | Rejected | Added complexity without clear benefit at this scope. Coarse tools with optional parameters achieves the same flexibility. |

**Key analogy**: Coarse = "Go mine 5 logs" (delegating to a capable worker). Fine = "Walk to 120,65,45. Look down. Click. Pick up the drop." (micromanaging every action).

**Decision**: Coarse composite tools. Add optional parameters (e.g., `max_radius`) if finer control is needed for specific cases.

---

## Decision 11: Tool Set (v1)

**Question**: What specific tools does the agent need for L2/L3 scope?

**Context**: The tool set must cover all actions needed for multi-step crafting (L2) and basic construction (L3). Internal helper actions (equip, find_block) are absorbed into composite tools.

| Tool | Purpose | Rationale |
|------|---------|-----------|
| `mine(target, count)` | Gather resources | Core action for any crafting chain |
| `craft(item, count)` | Create items | Handles recipe lookup, crafting table placement, and crafting |
| `place_block(block, x, y, z)` | Place blocks in world | Required for L3 construction |
| `navigate(x, y, z)` | Move to location | Required for exploration and positioning |
| `get_bot_status()` | Observe world state | How the LLM "sees" — inventory, health, position, surroundings |
| `chat(message)` | In-game communication | Useful for debugging, demo visibility |

**Absorbed actions**: `equip` is internal to `mine` and `place_block`. `find_block` is internal to `mine` and `get_bot_status`.

**Decision**: 6 composite tools for v1.

---

## Decision 12: Agent State Structure

**Question**: What data does the LangGraph state track?

**Context**: Every LangGraph node reads from and writes to a shared state. The state shape must support all 5 nodes (Retriever, Planner, Executor, Replanner, Reflexion).

**Decision**: Initial structure accepted as a starting point (see `AGENT_STATE.md`). A separate document is maintained and updated as the project evolves. The state was not locked down because implementation will reveal additional needs.

---

## Decision 13: Development Roadmap

**Question**: What phases should development follow, and what are the "done" criteria?

**Context**: The original blueprint had 4 phases with informal goals. Gaps existed: only 3 of 6 tools were assigned, Reflexion had no phase, and stretch goals had no roadmap entry.

| Phase | Original | Revised | Why Changed |
|-------|----------|---------|-------------|
| 1 | Skeleton (connection) | Skeleton (same) | No change needed |
| 2 | 3 tools | All 6 composite tools | Original only covered half the tool set |
| 3 | Planner + Executor | Brain v1 (same scope) | Clarified "done" criteria |
| 4 | RAG + SOPs | Knowledge (tag lookup + SOPs) | Specified tag-based retrieval instead of ChromaDB |
| — | *Not planned* | **Phase 5: Resilience** | Reflexion node was in architecture but had no development phase |
| — | *Not planned* | **Phase 6: Construction (stretch)** | L3 stretch goal had no roadmap entry |
| — | *Not planned* | **Phase 7: Polish (stretch)** | Streamlit, ChromaDB, and documentation had no phase |

**Decision**: 7-phase roadmap with concrete "done when" criteria for each phase.

---

## Decision 14: Minecraft World Configuration

**Question**: Should the world be randomized or fixed for development and demos?

**Context**: Reproducibility matters for debugging (same world = same conditions = reproducible bugs). Demo consistency matters for portfolio presentation.

| Option | Considered | Notes |
|--------|:---------:|-------|
| Fixed seed, normal world | **Chosen** | Reproducible terrain for consistent debugging and demos. Normal generation shows the agent handling real Minecraft terrain (not a flat test world). |
| Fixed seed, flat world | Rejected | Too artificial. Doesn't demonstrate the agent handling terrain challenges. |
| Random seed | Rejected | Different world each run makes bugs hard to reproduce and demos inconsistent. |

**Decision**: Fixed seed, normal world generation.

---

## Decision 15: HTTP API Route Design

**Phase**: 1 (Skeleton)

**Question**: How should the Python Brain specify which tool to execute on the Node.js Body?

**Context**: We need an HTTP API design for Brain-to-Body communication. Two common patterns exist: REST-style (one URL per resource/action) and RPC-style (one endpoint, action in body).

| Option | Considered | Notes |
|--------|:---------:|-------|
| RPC-style (`/execute`) | **Chosen** | Single endpoint, tool name in request body. Matches LangChain's tool-calling pattern `{name, args}`. Simpler routing — one handler with a dispatch map. Easier to extend (add tool to registry, not a new route). |
| REST-style (`/tools/{name}`) | Rejected | One route per tool (6+ routes). Tool name in URL. More explicit, but adds routing boilerplate. Our use case is actions (verbs), not resources (nouns) — RPC is a better semantic fit. |

**Examples**:
```bash
# RPC-style (chosen)
POST /execute
{"tool": "mine", "params": {"target": "oak_log", "count": 5}}

# REST-style (rejected)
POST /tools/mine
{"target": "oak_log", "count": 5}
```

**Decision**: RPC-style with single `/execute` endpoint.

---

## Decision 16: HTTP Request Format

**Phase**: 1 (Skeleton)

**Question**: How should tool parameters be structured in the request body?

**Context**: The request body needs the tool name and its parameters. Should all fields be at the same level (flat), or should params be nested?

| Option | Considered | Notes |
|--------|:---------:|-------|
| Nested params | **Chosen** | Clear separation: `tool` is metadata, `params` are tool-specific. Extensible — can add request-level fields (`timeout`) without collision. Matches LangChain's `{name, args}` structure. `req.body.params` gives exactly what the handler needs. |
| Flat structure | Rejected | Mixes tool name with parameters. What if a tool needs a param called `tool`? Adding metadata (e.g., `timeout`) creates ambiguity — is it a param or request-level? |

**Examples**:
```json
// Nested (chosen)
{
  "tool": "mine",
  "params": {
    "target": "oak_log",
    "count": 5
  }
}

// Flat (rejected)
{
  "tool": "mine",
  "target": "oak_log",
  "count": 5
}
```

**Decision**: Nested structure with `tool` and `params` as separate fields.

---

## Decision 17: HTTP Response Format

**Phase**: 1 (Skeleton)

**Question**: How detailed should success and error responses be?

**Context**: The LangGraph agent needs response data for decision-making. In Phase 5, the Reflexion node will analyze errors to suggest corrections. The response format affects how well the agent can understand outcomes.

| Option | Considered | Notes |
|--------|:---------:|-------|
| Structured responses | **Chosen** | Rich detail: error codes, context, duration. Error codes enable programmatic handling (Reflexion can match `RESOURCE_NOT_FOUND` reliably). Context aids debugging (bot position, search radius). Duration tracking for performance analysis. |
| Simple responses | Rejected | String errors only. Reflexion would rely on fragile string parsing. Less context for debugging. Sufficient for basic use but limits agent intelligence. |

**Success response format**:
```json
{
  "success": true,
  "data": {
    "items_collected": 5,
    "item_type": "oak_log"
  },
  "tool": "mine",
  "duration_ms": 3420
}
```

**Error response format**:
```json
{
  "success": false,
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "No oak_log found within search radius",
    "context": {
      "target": "oak_log",
      "search_radius": 64,
      "bot_position": {"x": 100, "y": 64, "z": 100}
    }
  },
  "tool": "mine",
  "duration_ms": 1250
}
```

**Proposed error codes**:
| Code | When |
|------|------|
| `RESOURCE_NOT_FOUND` | Block/entity not found nearby |
| `PATH_BLOCKED` | Pathfinder can't reach target |
| `INSUFFICIENT_MATERIALS` | Missing items for craft |
| `INVENTORY_FULL` | Can't pick up items |
| `INVALID_PARAMS` | Bad input to tool |
| `ACTION_FAILED` | Generic action failure |
| `TIMEOUT` | Action took too long |
| `BOT_DIED` | Bot died during action |
| `DISCONNECTED` | Lost connection to server |

**Note**: Actual error context will be adapted based on what Mineflayer provides. Design for ideal, adjust to reality.

**Decision**: Structured responses with error codes and context.

---

## Decision 18: HTTP Status Codes

**Phase**: 1 (Skeleton)

**Question**: What HTTP status code should tool failures return?

**Context**: When a tool fails (e.g., "no oak_log found"), should the HTTP response be 404 Not Found, or 200 OK with error in body? This is about separating HTTP-layer issues from application-layer issues.

| Option | Considered | Notes |
|--------|:---------:|-------|
| Always 200 for tool results | **Chosen** | Tool failures are application-level outcomes, not HTTP failures. HTTP 200 = "I received your request and here's my answer." Simpler client logic — just check `success` field. Matches RPC conventions. Reserve HTTP errors for protocol issues. |
| Semantic HTTP status codes | Rejected | Maps error types to 4xx/5xx. More "correct" HTTP, but our errors aren't HTTP errors. Adds client complexity (handle multiple status codes). Conflates transport and application layers. |

**HTTP errors we still use**:
| Situation | HTTP Status |
|-----------|-------------|
| Valid tool call, any outcome | 200 OK |
| Malformed JSON in request | 400 Bad Request |
| Unknown route | 404 Not Found |
| Server crash (Express error) | 500 Internal Server Error |

**Decision**: Always 200 for tool results. HTTP errors reserved for protocol issues only.

---

## Decision 19: Timeout Handling

**Phase**: 1 (Skeleton)

**Question**: How long should the Brain wait for the Body, and what happens when time runs out?

**Context**: Minecraft actions vary in duration. Mining 64 blocks might take 3 minutes. The timeout strategy affects both reliability and error handling.

### Understanding the Timeout Points

There are two timeout locations:

```
Brain (Python)                     Body (Node.js)                    Minecraft
     │                                  │                                │
     │  ──── HTTP Request ────────────> │                                │
     │                                  │                                │
     │        ⏱️ CLIENT TIMEOUT         │     ⏱️ ACTION TIMEOUT          │
     │   (Python stops waiting)         │  (Our code in Express)         │
     │                                  │                                │
```

1. **Client timeout** (Python): How long `requests.post()` waits
2. **Action timeout** (Express): Our code wrapping Mineflayer calls

**Critical insight**: Mineflayer has no built-in timeout — it waits indefinitely. We must implement action timeouts in Express.

### The Sync Problem

If client times out before action timeout:
```
Brain: "Mine 64 logs" ───────────────────────────>  Body
        │                                            │
        │  (waiting...)                              │  (mining...)
        │                                            │
     3 min: "Timeout! I give up"                     │  (still mining...)
        │                                            │
        X  Brain moves on, thinks it failed          │  (still mining...)
                                                     │
                                                  5 min: "Done! 64 logs collected"
                                                     │
                                                     X  Response goes nowhere
```

Result: Bot has 64 logs, but Brain doesn't know. State desync.

### Solution: Action Timeout < Client Timeout

```
Action timeout (Node.js):  4 minutes
Client timeout (Python):   5 minutes
```

This ensures:
1. If action takes too long, **Body** gives up first and returns TIMEOUT error
2. Brain receives the error and knows what happened
3. Both sides stay synchronized

### Timeout Flow

```
Python Brain              Express (our code)              Mineflayer            Minecraft
     │                          │                             │                     │
     │  POST /execute           │                             │                     │
     │ ───────────────────────> │                             │                     │
     │                          │                             │                     │
     │                          │  Start timeout timer (4m)   │                     │
     │                          │  ─────────┐                 │                     │
     │                          │           │                 │                     │
     │                          │  Call mineBlocks()          │                     │
     │                          │ ──────────────────────────> │                     │
     │                          │                             │  bot actions        │
     │                          │                             │ ──────────────────> │
     │                          │                             │                     │
     │  (waiting, up to 5m)     │  (waiting, up to 4m)       │  (mining...)        │
     │                          │           │                 │                     │
     │                          │                             │                     │
     │                          │  CASE A: Mineflayer done   │                     │
     │                          │ <────────────────────────── │                     │
     │                          │  Cancel timer, return OK    │                     │
     │ <─────────────────────── │                             │                     │
     │  {success: true, data}   │                             │                     │
     │                          │                             │                     │
     │                          │  CASE B: Timer fires first │                     │
     │                          │ <────────┘                  │                     │
     │                          │  Cancel Mineflayer, return error                  │
     │ <─────────────────────── │                             │                     │
     │  {success: false,        │                             │                     │
     │   error: {code: TIMEOUT}}│                             │                     │
```

| Setting | Value | Reasoning |
|---------|-------|-----------|
| Default action timeout | 4 minutes | Long enough for big mining jobs |
| Default client timeout | 5 minutes | 1-minute buffer over action timeout |
| Per-tool overrides | Deferred | Start simple, tune if issues arise |

**Decision**: 4-minute action timeout (Express), 5-minute client timeout (Python). Global defaults initially, per-tool tuning deferred.

---

## Decision 20: Content-Type Handling

**Phase**: 1 (Skeleton)

**Question**: What content format should the API support, and how strictly should it validate Content-Type headers?

**Context**: The Brain sends JSON to the Body. Should we support other formats? Should we reject requests with wrong/missing Content-Type headers?

### Sub-decision 20a: Format Support

| Option | Considered | Notes |
|--------|:---------:|-------|
| JSON only | **Chosen** | Native to JavaScript. LangChain tool calls are JSON. Express has built-in `express.json()`. No need for alternatives. |
| Multiple formats | Rejected | MessagePack/Protobuf add complexity without benefit. No client needs non-JSON. |

### Sub-decision 20b: Validation Strictness

| Option | Considered | Notes |
|--------|:---------:|-------|
| Strict (reject wrong Content-Type) | Rejected | Could reject valid JSON if header missing. Adds friction. |
| Lenient (parse anyway) | Rejected | Silent failures make debugging harder. |
| Lenient with logging | **Chosen** | Parse JSON regardless of header, but log warning if Content-Type is unexpected. Works reliably, surfaces misconfigurations. |

**Decision**: JSON only. Lenient parsing with debug logging for unexpected Content-Type.

---

## Decision 21: Authentication & Network Binding

**Phase**: 1 (Skeleton)

**Question**: Should the `/execute` endpoint require authentication? How should network binding be configured?

**Context**: This is a local development project. Brain and Body run on the same machine. Security vs. simplicity trade-off.

| Option | Considered | Notes |
|--------|:---------:|-------|
| No auth + bind to 0.0.0.0 | Rejected | Exposes API to network. Anyone who can reach the port controls the bot. |
| API key required | Rejected | Adds configuration overhead for local-only use. Available as opt-in if needed later. |
| Localhost binding (configurable) | **Chosen** | Bind to `127.0.0.1` by default — only local processes can connect. Configure via `BOT_HOST` env var for cloud deployment. |

**Implementation**:
```javascript
const HOST = process.env.BOT_HOST || '127.0.0.1';
const PORT = process.env.BOT_PORT || 3000;
app.listen(PORT, HOST);
```

**Deployment implications**:
- Local / single VM: Use defaults (localhost binding)
- Cloud Run / GKE separate pods: Set `BOT_HOST=0.0.0.0` and add auth middleware

**Decision**: Localhost binding by default (`127.0.0.1`). Configurable via `BOT_HOST` env var for cloud deployment.
