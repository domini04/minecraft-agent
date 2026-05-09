"""Phase-3 LangGraph wiring: planner -> executor loop.

This module compiles the Phase-3 ``StateGraph`` that drives a single
goal-resolution run. The topology is::

    START -> planner
    planner --conditional--> {executor, END}
    executor --conditional--> {planner, END}

Two conditional edges guard the loop:

* ``_should_continue_after_planner`` — routes to ``executor`` iff the
  planner appended a new step (``current_step < len(plan)``); otherwise
  routes to ``END``. The planner sets ``state.result`` in both the
  no-tool-call and validation-error branches WITHOUT appending to plan,
  so the length comparison is sufficient — there's no need to inspect
  ``state.result`` here.
* ``_should_continue_after_executor`` — routes to ``END`` iff the
  executor's out-of-range guard fired (``state.result`` populated) OR
  the planner's iteration counter has reached ``MAX_ITERATIONS``;
  otherwise loops back to ``planner``.

``llm`` and ``body_client`` are injected via ``functools.partial`` ONLY
when the caller supplies them (test seam). Production runs pass
``None`` and the planner / executor nodes resolve their dependencies
lazily on first invocation. This keeps ``requests`` and
``langchain_google_genai`` out of ``sys.modules`` at module load time.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from src.nodes.executor import executor_node
from src.nodes.planner import planner_node
from src.state import MAX_ITERATIONS, AgentState, make_initial_state

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from src.body_client import BodyClient


def _should_continue_after_planner(state: AgentState) -> str:
    """Route from planner to executor or END.

    The planner appends to ``plan`` iff it produced a valid tool call.
    In every other branch (no tool call OR validation error) ``plan``
    is unchanged and ``current_step`` is unchanged, so
    ``current_step >= len(plan)``.

    Args:
        state: Current ``AgentState`` after the planner node returned.

    Returns:
        ``"executor"`` when a new step was appended; ``"end"`` otherwise.
    """
    plan = state.get("plan", []) or []
    current_step = int(state.get("current_step", 0))
    if current_step < len(plan):
        return "executor"
    return "end"


def _should_continue_after_executor(state: AgentState) -> str:
    """Route from executor to planner or END.

    Stop on either:

    * ``state.result`` set (the executor's out-of-range guard fired), or
    * ``iteration_count >= MAX_ITERATIONS`` (cap exhausted).

    The cap check uses ``iteration_count``, which is incremented by the
    PLANNER, not the executor. After the executor runs, the value
    reflects the number of planner invocations so far in this run.

    Args:
        state: Current ``AgentState`` after the executor node returned.

    Returns:
        ``"end"`` when terminating; ``"planner"`` to loop again.
    """
    if state.get("result"):
        return "end"
    if int(state.get("iteration_count", 0)) >= MAX_ITERATIONS:
        return "end"
    return "planner"


def build_graph(
    llm: "BaseChatModel | None" = None,
    body_client: "BodyClient | None" = None,
):
    """Compile the Phase-3 planner -> executor LangGraph.

    Args:
        llm: Optional pre-bound chat model. When non-None, injected into
            the planner node via ``functools.partial``. When None, the
            planner resolves its own LLM lazily on first invocation.
        body_client: Optional ``BodyClient`` (or stub). When non-None,
            injected into the executor node via ``functools.partial``.
            When None, the executor constructs a real ``BodyClient``
            lazily.

    Returns:
        A compiled LangGraph (``CompiledStateGraph``). Call
        ``.invoke(state, ...)`` to drive a single goal-resolution run.
        The graph is stateless across invocations.
    """
    planner_fn = partial(planner_node, llm=llm) if llm is not None else planner_node
    executor_fn = (
        partial(executor_node, body_client=body_client)
        if body_client is not None
        else executor_node
    )

    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_fn)
    graph.add_node("executor", executor_fn)
    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        _should_continue_after_planner,
        {"executor": "executor", "end": END},
    )
    graph.add_conditional_edges(
        "executor",
        _should_continue_after_executor,
        {"planner": "planner", "end": END},
    )
    return graph.compile()


def run_goal(
    goal: str,
    llm: "BaseChatModel | None" = None,
    body_client: "BodyClient | None" = None,
) -> AgentState:
    """Build the graph, seed initial state, invoke once, return final state.

    Convenience wrapper for the CLI (Sprint 3h) and end-to-end tests.

    Args:
        goal: User's natural-language request.
        llm: Optional injected chat model (test seam).
        body_client: Optional injected ``BodyClient`` (test seam).

    Returns:
        The final ``AgentState`` dict after the graph terminates.
    """
    initial = make_initial_state(goal)
    graph = build_graph(llm=llm, body_client=body_client)
    return graph.invoke(initial, config={"recursion_limit": 50})
