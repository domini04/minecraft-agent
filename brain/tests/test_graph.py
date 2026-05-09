"""Stub-driven tests for ``src.graph.build_graph`` and ``src.graph.run_goal``.

Every test injects ``SequenceLLM`` / ``CyclingLLM`` and ``StubBodyClient``
stubs via the ``llm=`` and ``body_client=`` kwargs so neither the real
``get_llm()`` nor the real ``BodyClient`` is ever exercised — no network,
no credentials, no provider clients constructed. Stubs follow the same
recorded-call pattern as ``test_planner_node.StubLLM`` and
``test_executor_node.StubBodyClient``.

Coverage map (Sprint 3g plan §3):

* G1 -- build_graph returns a compiled object with .invoke
* G2 -- functools.partial wires both stubs into the running nodes
* G3 -- single-step goal-complete (planner -> END, no executor call)
* G4 -- single tool call followed by goal-complete (full one-iteration loop)
* G5 -- cap-exhaustion stops at MAX_ITERATIONS=10
* G6 -- tool failure does not terminate; loop continues
* G7 -- planner validation error stops the graph immediately
* G8 -- run_goal == build_graph + invoke (convenience equivalence)
* G9 -- StateGraph(AgentState) accepts the TypedDict and end-to-end works
* G10 -- importing src.graph does not pull HTTP-client modules
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

from langchain_core.messages import AIMessage

from src.graph import build_graph, run_goal
from src.state import MAX_ITERATIONS, make_initial_state

# ---------- helpers ----------


class SequenceLLM:
    """LLM stub that returns a queued sequence of AIMessages.

    ``bind_tools`` returns ``self``. ``invoke`` pops the next response
    off the front of the queue and records every invocation's message
    list. Mirrors ``StubLLM`` from ``test_planner_node`` but sequenced
    for multi-iteration tests.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.bind_tools_args: list = []
        self.invoke_args: list = []

    def bind_tools(self, tools):
        self.bind_tools_args.append(list(tools))
        return self

    def invoke(self, messages):
        self.invoke_args.append(list(messages))
        if not self._responses:
            raise AssertionError("SequenceLLM ran out of responses")
        return self._responses.pop(0)


class CyclingLLM:
    """LLM stub that ALWAYS returns the same response.

    Used by the cap-exhaustion test (G5) to drive the planner indefinitely
    until ``MAX_ITERATIONS`` fires the executor-side conditional edge.
    """

    def __init__(self, response: AIMessage):
        self._response = response
        self.invoke_count = 0
        self.bind_tools_args: list = []

    def bind_tools(self, tools):
        self.bind_tools_args.append(list(tools))
        return self

    def invoke(self, messages):
        self.invoke_count += 1
        return self._response


class StubBodyClient:
    """Records ``(tool, params)`` and returns a pre-configured envelope.

    Re-implemented here rather than imported from ``test_executor_node``
    to avoid cross-test-file coupling. Identical contract.
    """

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.last_call_args = None
        self.call_count = 0

    def execute(self, tool, params=None):
        self.call_count += 1
        self.last_call_args = (tool, params)
        if self._raises is not None:
            raise self._raises
        return self._response


def _navigate_tool_call(call_id="nav-1"):
    """Build an AIMessage carrying one valid navigate tool call."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "navigate",
                "args": {"x": 1, "y": 64, "z": 2},
                "id": call_id,
            }
        ],
    )


def _navigate_success_envelope():
    """Body envelope for a successful navigate dispatch."""
    return {
        "success": True,
        "data": {"reached": True},
        "tool": "navigate",
        "duration_ms": 12.3,
    }


def _navigate_failure_envelope():
    """Body envelope for a failed navigate dispatch (success=False)."""
    return {
        "success": False,
        "data": None,
        "error": {
            "code": "PATH_NOT_FOUND",
            "message": "no path",
            "context": None,
        },
        "tool": "navigate",
        "duration_ms": 4.5,
    }


# ---------- G1: build_graph returns compiled object ----------


def test_build_graph_returns_compiled_object():
    """G1: build_graph() returns an object exposing .invoke."""
    g = build_graph()
    assert callable(getattr(g, "invoke", None))


# ---------- G2: partials wire stubs into running nodes ----------


def test_build_graph_injects_stubs_via_partial():
    """G2: stubs are reached on invocation (proves functools.partial wiring)."""
    stub_llm = SequenceLLM(
        [
            _navigate_tool_call("g2"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=_navigate_success_envelope())

    g = build_graph(llm=stub_llm, body_client=stub_body)
    out = g.invoke(make_initial_state("hi"), config={"recursion_limit": 50})

    # Both stubs were exercised: planner partial called twice, executor partial once.
    assert len(stub_llm.invoke_args) == 2
    assert stub_body.call_count == 1
    # Final state still consistent.
    assert out["result"] == "done"


# ---------- G3: single-step goal complete (no executor call) ----------


def test_run_goal_single_step_goal_complete():
    """G3: zero tool calls -> planner sets result, executor never runs."""
    stub_llm = SequenceLLM([AIMessage(content="done", tool_calls=[])])
    stub_body = StubBodyClient(response=None)

    out = run_goal("hi", llm=stub_llm, body_client=stub_body)

    assert out["result"] == "done"
    assert out["plan"] == []
    assert out["iteration_count"] == 1
    assert out["step_results"] == []
    assert stub_body.call_count == 0


# ---------- G4: single tool call then complete ----------


def test_run_goal_single_step_tool_call_then_complete():
    """G4: one tool call followed by no-tool-call -> full one-iteration loop."""
    stub_llm = SequenceLLM(
        [
            _navigate_tool_call("g4"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=_navigate_success_envelope())

    out = run_goal("go there", llm=stub_llm, body_client=stub_body)

    assert len(out["plan"]) == 1
    assert out["plan"][0]["tool_name"] == "navigate"
    assert len(out["step_results"]) == 1
    assert out["step_results"][0]["success"] is True
    assert out["iteration_count"] == 2
    assert out["result"] == "done"
    assert out["current_step"] == 1
    assert stub_body.call_count == 1
    assert stub_body.last_call_args == ("navigate", {"x": 1, "y": 64, "z": 2})


# ---------- G5: cap exhaustion ----------


def test_run_goal_cap_exhaustion_stops_at_max_iterations():
    """G5: looping LLM hits MAX_ITERATIONS cap before LangGraph recursion limit."""
    cycling_llm = CyclingLLM(_navigate_tool_call("g5"))
    stub_body = StubBodyClient(response=_navigate_success_envelope())

    out = run_goal("loop forever", llm=cycling_llm, body_client=stub_body)

    assert len(out["plan"]) == MAX_ITERATIONS == 10
    assert len(out["step_results"]) == 10
    assert out["iteration_count"] == 10
    # No synthetic cap-exhausted message in Phase 3 (graph layer doesn't
    # synthesize result strings).
    assert out["result"] == ""
    assert out["current_step"] == 10
    assert cycling_llm.invoke_count == 10
    assert stub_body.call_count == 10


# ---------- G6: tool failure does not terminate ----------


def test_run_goal_tool_failure_continues_loop():
    """G6: success=False envelope does NOT terminate; planner is asked again."""
    stub_llm = SequenceLLM(
        [
            _navigate_tool_call("g6"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=_navigate_failure_envelope())

    out = run_goal("retry me", llm=stub_llm, body_client=stub_body)

    assert out["iteration_count"] == 2
    assert len(out["step_results"]) == 1
    assert out["step_results"][0]["success"] is False
    assert out["result"] == "done"
    assert stub_body.call_count == 1


# ---------- G7: planner validation error stops ----------


def test_run_goal_planner_validation_error_stops():
    """G7: malformed tool args -> planner sets error result, executor never runs."""
    bad_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "mine",
                "args": {"target": "oak_log", "count": 0},
                "id": "g7",
            }
        ],
    )
    stub_llm = SequenceLLM([bad_call])
    stub_body = StubBodyClient(response=None)

    out = run_goal("break the rules", llm=stub_llm, body_client=stub_body)

    assert out["result"].startswith("planner: LLM produced invalid tool call:")
    assert out["plan"] == []
    assert out["iteration_count"] == 1
    assert out["step_results"] == []
    assert stub_body.call_count == 0


# ---------- G8: run_goal == build_graph + invoke ----------


def test_run_goal_matches_build_graph_invoke():
    """G8: convenience wrapper equivalent to build_graph(...).invoke(...)."""
    # Path A: explicit build + invoke.
    stub_llm_a = SequenceLLM([AIMessage(content="done", tool_calls=[])])
    stub_body_a = StubBodyClient(response=None)
    g = build_graph(llm=stub_llm_a, body_client=stub_body_a)
    out_a = g.invoke(make_initial_state("hi"), config={"recursion_limit": 50})

    # Path B: run_goal convenience wrapper, fresh stubs.
    stub_llm_b = SequenceLLM([AIMessage(content="done", tool_calls=[])])
    stub_body_b = StubBodyClient(response=None)
    out_b = run_goal("hi", llm=stub_llm_b, body_client=stub_body_b)

    assert out_a["result"] == out_b["result"]
    assert out_a["iteration_count"] == out_b["iteration_count"]
    assert len(out_a["plan"]) == len(out_b["plan"])
    assert len(out_a["step_results"]) == len(out_b["step_results"])


# ---------- G9: TypedDict acceptance + end-to-end shape ----------


def test_build_graph_accepts_typeddict_state_and_invokes():
    """G9: StateGraph(AgentState) compiles and invokes without raising."""
    stub_llm = SequenceLLM([AIMessage(content="ok", tool_calls=[])])
    stub_body = StubBodyClient(response=None)
    g = build_graph(llm=stub_llm, body_client=stub_body)

    out = g.invoke(make_initial_state("ping"), config={"recursion_limit": 50})

    assert isinstance(out, dict)
    for key in (
        "goal",
        "plan",
        "current_step",
        "step_results",
        "bot_status",
        "iteration_count",
        "result",
    ):
        assert key in out, f"missing key in output state: {key}"


# ---------- G10: no-network import surface ----------


def test_graph_no_network_imports():
    """G10: importing src.graph adds no HTTP-client surface beyond baseline.

    Pattern mirrors ``test_planner_no_network_imports`` /
    ``test_executor_no_network_imports``: a baseline subprocess imports
    only the dependencies ``src.graph`` is allowed to drag in
    (``langgraph.graph``, ``src.state``, ``src.nodes.planner``,
    ``src.nodes.executor``). A probe subprocess imports ``src.graph`` and
    must not pull any additional ``requests`` / ``httpx`` / ``urllib3``
    surface beyond the baseline.
    """
    deny_prefixes = ("requests", "httpx", "urllib3")

    baseline_code = textwrap.dedent(
        """
        import sys
        import langgraph.graph  # noqa: F401
        import src.state  # noqa: F401
        import src.nodes.planner  # noqa: F401
        import src.nodes.executor  # noqa: F401

        deny = ("requests", "httpx", "urllib3")
        leaked = sorted(m for m in sys.modules if m.startswith(deny))
        for m in leaked:
            print(m)
        """
    )
    baseline = subprocess.run(
        [sys.executable, "-c", baseline_code],
        capture_output=True,
        text=True,
    )
    assert baseline.returncode == 0, (
        f"baseline subprocess failed:\nstderr={baseline.stderr}"
    )
    baseline_set = set(baseline.stdout.split())

    graph_code = textwrap.dedent(
        """
        import sys
        import src.graph  # noqa: F401

        deny = ("requests", "httpx", "urllib3")
        leaked = sorted(m for m in sys.modules if m.startswith(deny))
        for m in leaked:
            print(m)
        """
    )
    graph_proc = subprocess.run(
        [sys.executable, "-c", graph_code],
        capture_output=True,
        text=True,
    )
    assert graph_proc.returncode == 0, (
        f"graph subprocess failed:\nstderr={graph_proc.stderr}"
    )
    graph_set = set(graph_proc.stdout.split())

    extra = graph_set - baseline_set
    assert not extra, (
        f"src.graph pulled HTTP-client modules beyond the allowed "
        f"baseline: {sorted(extra)}"
    )
    # Sanity: deny prefixes are real, the test isn't trivially vacuous.
    assert deny_prefixes
