# Minecraft Agent

An LLM-powered autonomous agent that executes multi-step crafting chains and basic construction tasks in Minecraft.

## Overview

This project demonstrates AI agent architecture by building an autonomous Minecraft bot capable of understanding natural language goals (e.g., "Get me a stone pickaxe") and executing them without human intervention.

**Core Philosophy**: *Deterministic Tooling* — the LLM ("The Brain") handles planning and decision-making, while human-written code ("The Body") handles physics and execution. The LLM decides *what* to do; the code handles *how*.

### Capability Scope

| Level | Description | Status |
|-------|-------------|--------|
| **L1** | Single actions (mine, navigate, craft) | Included |
| **L2** | Multi-step dependency chains ("Get me a stone pickaxe") | **Minimum Viable Demo** |
| **L3** | Basic construction ("Build a 5x5 house") | Stretch Goal |
| **L4** | Survival loops (reactive, continuous) | Out of scope |

## Architecture

The system uses a **microservices bridge pattern** with two processes communicating via HTTP:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            User Interface                               │
│                          CLI / Streamlit (v2)                           │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────────┐
│                         THE BRAIN (Python)                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   Guide     │───▶│   Planner   │───▶│   Executor  │──┐              │
│  │  Retriever  │    │             │    │             │  │              │
│  └─────────────┘    └─────────────┘    └─────────────┘  │              │
│         ▲                                    │          │              │
│         │           ┌─────────────┐          ▼          │              │
│  ┌──────┴──────┐    │  Reflexion  │◀────[on error]     │              │
│  │  SOP Store  │    │   (retry)   │                     │              │
│  │ (YAML/Tags) │    └─────────────┘                     │              │
│  └─────────────┘                                        │              │
└─────────────────────────────────────────────────────────┼──────────────┘
                                                          │
                                              HTTP POST /execute
                                                          │
┌─────────────────────────────────────────────────────────▼──────────────┐
│                         THE BODY (Node.js)                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Express Server                              │   │
│  │   Receives {tool, params} → Executes → Returns JSON response    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                  │                                      │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Mineflayer Bot                              │   │
│  │   Pathfinding • Block interaction • Inventory • Crafting        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                  │                                      │
└──────────────────────────────────┼──────────────────────────────────────┘
                                   │
                        Minecraft Protocol
                                   │
                    ┌──────────────▼──────────────┐
                    │     Minecraft Server        │
                    │   Vanilla Java Edition      │
                    └─────────────────────────────┘
```

## Technology Stack

### The Brain (Python)

| Component | Technology |
|-----------|------------|
| Runtime | Python 3.11+ |
| Orchestration | LangGraph |
| LLM Interface | LangChain (model-agnostic) |
| Primary LLM | Gemini 3.0 Flash |
| SOP Retrieval | Tag-based lookup (v1) → ChromaDB (v2) |
| Monitoring | LangSmith |

### The Body (Node.js)

| Component | Technology |
|-----------|------------|
| Runtime | Node.js LTS |
| Bot Framework | Mineflayer |
| Navigation | mineflayer-pathfinder |
| Mining | mineflayer-collectblock |
| API Layer | Express.js |

## Composite Tools

Six coarse-grained tools handle all Minecraft interactions:

| Tool | Signature | Description |
|------|-----------|-------------|
| `mine` | `mine(target, count)` | Find, navigate to, and mine blocks |
| `craft` | `craft(item, count)` | Look up recipe and craft items |
| `place_block` | `place_block(block, x, y, z)` | Navigate and place a block at coordinates |
| `navigate` | `navigate(x, y, z)` | Pathfind to target location |
| `get_bot_status` | `get_bot_status()` | Return health, position, inventory, surroundings |
| `chat` | `chat(message)` | Send in-game chat message |

## Project Structure

```
minecraft-agent/
├── brain/              # Python - LangGraph agent (The Brain)
│   └── src/
├── body/               # Node.js - Mineflayer bot (The Body)
│   └── src/
├── sops/               # Standard Operating Procedures (YAML)
└── docs/               # Project documentation
    ├── TECHNICAL_BLUEPRINT.md   # Full system specification
    ├── FEASIBILITY_REPORT.md    # Mineflayer capability assessment
    ├── PRIOR_ART_REPORT.md      # MineDojo & Voyager analysis
    ├── PROGRESSION_PLAN.md      # Development phases & steps
    ├── PHASE1_HTTP_BRIDGE.md    # HTTP API contract
    ├── DECISION_LOG.md          # Architectural decisions
    ├── AGENT_STATE.md           # LangGraph state structure
    └── TODO.md                  # Current progress tracker
```

## Development Status

**Current Phase**: Phase 1 — Skeleton (HTTP Bridge)

| Phase | Name | Status |
|-------|------|--------|
| 0 | Pre-Development | Complete |
| 1 | Skeleton (HTTP Bridge) | **In Progress** |
| 2 | Core Tools | Not started |
| 3 | Brain v1 (Planner + Executor) | Not started |
| 4 | Knowledge (SOP Retrieval) | Not started |
| 5 | Resilience (Error Recovery) | Not started |
| 6 | Construction (Stretch) | Not started |
| 7 | Polish (Stretch) | Not started |

See [docs/TODO.md](docs/TODO.md) for detailed progress.

## Getting Started

### Prerequisites

- Node.js LTS
- Python 3.11+
- Java 21 (for Minecraft server)
- Minecraft Java Edition server (vanilla, offline mode)

### Setup

1. **Start Minecraft server** (offline mode, fixed seed)

2. **Start the Body (Node.js)**
   ```bash
   cd body
   npm install
   npm start
   ```

3. **Start the Brain (Python)** — *not yet implemented*
   ```bash
   cd brain
   pip install -e .
   # python -m brain.main
   ```

## Documentation

| Document | Description |
|----------|-------------|
| [TECHNICAL_BLUEPRINT.md](docs/TECHNICAL_BLUEPRINT.md) | Complete system specification |
| [FEASIBILITY_REPORT.md](docs/FEASIBILITY_REPORT.md) | Mineflayer capability assessment |
| [PRIOR_ART_REPORT.md](docs/PRIOR_ART_REPORT.md) | Analysis of MineDojo & Voyager |
| [PROGRESSION_PLAN.md](docs/PROGRESSION_PLAN.md) | Development phases and steps |
| [DECISION_LOG.md](docs/DECISION_LOG.md) | Architectural decision log |

## Design Decisions

Key architectural choices:

- **Coarse composite tools** over fine-grained primitives — reduces LLM planning complexity
- **Synchronous HTTP** over async/WebSocket — simpler debugging, adequate for single-bot scope
- **Static SOPs** over dynamic skill learning — appropriate for bounded L2/L3 scope
- **Predefined tools** over LLM code generation — safer, more reliable with modern tool-calling APIs

See [DECISION_LOG.md](docs/DECISION_LOG.md) for full reasoning.

## Acknowledgments

Architecture informed by analysis of:
- [Voyager](https://github.com/MineDojo/Voyager) — LLM-powered Minecraft agent (NVIDIA Research)
- [MineDojo](https://github.com/MineDojo/MineDojo) — Minecraft RL research framework

## License

Personal portfolio project.
