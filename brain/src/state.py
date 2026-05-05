"""Phase-3 subset of the LangGraph shared state.

This module defines the AgentState TypedDict and the make_initial_state factory
used by the Phase-3 Planner+Executor graph. It intentionally contains only the
seven fields active in Phase 3; the forward-looking complete schema (including
Phase 4–5 fields ``guide``, ``retry_count``, and ``errors``) is documented in
docs/AGENT_STATE.md.

No network calls, no LLM imports, no LangGraph dependencies — pure stdlib typing.
"""

from typing import TypedDict

# Fixed iteration cap for the Phase-3 Planner node.
# Sprint 3e conditional edge compares ``state["iteration_count"]`` against this
# constant. Defined here so that ``state.py`` is the single source of truth
# for both the field and the limit it bounds.
MAX_ITERATIONS: int = 10


class AgentState(TypedDict, total=False):
    """Shared state dict threaded through every node in the Phase-3 LangGraph.

    ``total=False`` lets individual nodes write only the fields they own;
    ``make_initial_state`` seeds all seven keys so downstream nodes can read
    safe empty defaults without risking a ``KeyError``.

    See docs/AGENT_STATE.md for the complete forward-looking field spec
    including Phase 4–5 fields deferred from this implementation.
    """

    goal: str
    """User's natural-language request, set at graph entry and never mutated."""

    plan: list[dict]
    """Ordered tool calls produced by the Planner node."""

    current_step: int
    """Zero-based index into ``plan`` pointing at the step being executed."""

    step_results: list[dict]
    """Accumulated execution results; Executor node appends one entry per step."""

    bot_status: dict
    """Last-known bot snapshot, refreshed via the ``get_bot_status`` tool."""

    iteration_count: int
    """Number of times the Planner node has fired; gated against MAX_ITERATIONS."""

    result: str
    """Final output message set when the graph reaches a terminal node."""


def make_initial_state(goal: str) -> AgentState:
    """Return a fully-seeded AgentState with Phase-3 defaults.

    All seven fields are populated so that every downstream node can read them
    without a ``KeyError``. Mutable defaults (``plan``, ``step_results``,
    ``bot_status``) are constructed as fresh literals inside this function body
    on every call — never shared across invocations.

    Args:
        goal: The user's natural-language request verbatim.

    Returns:
        An AgentState dict ready to be passed as the initial state to the
        LangGraph ``StateGraph.invoke()`` call in Sprint 3e.

    See docs/AGENT_STATE.md for the field semantics.
    """
    return AgentState(
        goal=goal,
        plan=[],
        current_step=0,
        step_results=[],
        bot_status={},
        iteration_count=0,
        result="",
    )
