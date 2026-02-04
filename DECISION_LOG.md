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
