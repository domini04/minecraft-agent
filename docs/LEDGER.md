# Documentation Ledger

Index of every project document. Read this before proposing substantive changes — most design questions already have an answer in one of these files.

**Maintenance rule:** when a new document is created or retired, update this ledger in the same change. Do not let it go stale.

---

## 1. Specifications (authoritative — read these first)

| Document | Purpose |
|---|---|
| [`TECHNICAL_BLUEPRINT.md`](TECHNICAL_BLUEPRINT.md) | v1.0 project spec. Objective, scope (L1/L2/L3 capabilities), architecture, tool list, and the 14 foundational decisions. The single source of truth for *what* we're building. |
| [`DECISION_LOG.md`](DECISION_LOG.md) | Every architectural/technical decision with context, options considered, and reasoning. Numbered (1–21+). When a decision is disputed, this is the canonical record. |
| [`AGENT_STATE.md`](AGENT_STATE.md) | LangGraph shared-state schema. Field-by-field description of what every brain node reads and writes. |
| [`EXECUTE_API_DESIGN.md`](EXECUTE_API_DESIGN.md) | `/execute` endpoint contract (Phase 1, Steps 1.5–1.6). Request/response shape, error codes, timeouts. Depends on Decisions 15–21. |
| [`PHASE1_HTTP_BRIDGE.md`](PHASE1_HTTP_BRIDGE.md) | Phase 1 component overview. Explains the brain-body split and HTTP bridge at a conceptual level. |

## 2. Process & Planning

| Document | Purpose |
|---|---|
| [`PROGRESSION_PLAN.md`](PROGRESSION_PLAN.md) | 7 phases × ~35 steps with completion criteria. Defines the three-stage workflow (Understand → Design → Implement) used before each phase. |
| [`TODO.md`](TODO.md) | Live working list. Current phase, current step, completed items. Update as work progresses. |

## 3. Research Reports (context, not spec)

| Document | Purpose |
|---|---|
| [`FEASIBILITY_REPORT.md`](FEASIBILITY_REPORT.md) | Verified that Mineflayer supports every capability the blueprint requires. Verdict: feasible. |
| [`PRIOR_ART_REPORT.md`](PRIOR_ART_REPORT.md) | Investigation of MineDojo and Voyager. Our design survives comparison; implementation patterns flagged for Phase 2 and Phase 5. |

## 4. Root

| Document | Purpose |
|---|---|
| [`../README.md`](../README.md) | Public-facing project description (for portfolio reviewers). Keep aligned with the blueprint. |
| [`../CLAUDE.md`](../CLAUDE.md) | High-level instructions for Claude Code sessions. Points back to this ledger for detail. |

---

## How to Use This Ledger

**For a new task:**
1. Identify which category the task touches (spec change? new phase work? research question?).
2. Read the relevant document(s) from the table above.
3. Only *then* propose changes.

**When creating a new doc:**
1. Add a row to the correct section here, in the same commit.
2. If the new doc supersedes an existing one, mark the old one with a "Superseded by X" note at its top rather than deleting — decision history matters.

**When retiring a doc:**
1. Do not delete. Add a "Retired" suffix in the table and a one-line reason.
2. Keep the file for historical context.
