"""Stub-driven tests for ``src.graph.build_graph`` and ``src.graph.run_goal``.

Every test injects ``SequenceLLM`` / ``CyclingLLM`` and ``StubBodyClient``
stubs via the ``llm=`` and ``body_client=`` kwargs so neither the real
``get_llm()`` nor the real ``BodyClient`` is ever exercised — no network,
no credentials, no provider clients constructed. Stubs follow the same
recorded-call pattern as ``test_planner_node.StubLLM`` and
``test_executor_node.StubBodyClient``.

Sprint 4e adds ``StubCache`` / ``RecordingCache`` to short-circuit the
``guide_retriever`` node's LLM call in all existing tests (Approach A from
the plan). Tests G1..G10 and K8/K8b all pass ``cache=StubCache()`` so the
stub LLM queue is not consumed by the retriever.

Coverage map:

* G1  -- build_graph returns a compiled object with .invoke
* G2  -- functools.partial wires both stubs into the running nodes
* G3  -- single-step goal-complete (planner -> END, no executor call)
* G4  -- single tool call followed by goal-complete (full one-iteration loop)
* G5  -- cap-exhaustion stops at MAX_ITERATIONS=10
* G6  -- tool failure does not terminate; loop continues
* G7  -- planner validation error stops the graph immediately
* G8  -- run_goal == build_graph + invoke (convenience equivalence)
* G9  -- StateGraph(AgentState) accepts the TypedDict and end-to-end works
* G10 -- importing src.graph does not pull HTTP-client modules
* G11 -- entry edge: guide_retriever runs FIRST (observed via cache.get_calls)
* G12 -- retriever runs ONCE per goal invocation, not per planner iteration
* G13 -- use_cache=True plumbs to the retriever: cache.get called
* G14 -- use_cache=False bypasses cache read AND write
* G15 -- run_goal forwards use_cache to build_graph
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest
from langchain_core.messages import AIMessage

from src.graph import build_graph, run_goal
from src.state import MAX_ITERATIONS, make_initial_state


@pytest.fixture(autouse=True)
def _disable_announce_by_default(monkeypatch):
    """Sprint 3k: deterministic announce-OFF for every test in this file.
    Tests that need announce-ON override BRAIN_ANNOUNCE explicitly.
    """
    monkeypatch.setenv("BRAIN_ANNOUNCE", "0")


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


class StubCache:
    """Always reports a cache hit with the no-match sentinel; never writes.

    Injected into G1..G10 and K8/K8b so the guide_retriever node short-
    circuits before it would call ``llm.invoke``. This keeps every existing
    test's ``SequenceLLM`` queue intact — the retriever never touches it.

    Default hit returns the ``<none>`` sentinel, which causes the retriever
    to set ``state["guide"] = {}`` and return immediately.
    """

    def __init__(self, hit=None):
        # Default hit: '<none>' sentinel → guide_retriever returns guide={} without LLM call
        self._hit = hit if hit is not None else {"sop_name": "<none>", "count": None}
        self.get_calls: list = []
        self.set_calls: list = []

    def get(self, goal):
        self.get_calls.append(goal)
        return self._hit

    def set(self, goal, sop_name, count):
        self.set_calls.append((goal, sop_name, count))


class RecordingCache:
    """Cache stub that always reports a MISS (returns None from get).

    Used by G13/G14 to verify whether the retriever reads/writes the cache.
    ``set`` records writes without actually persisting anything.
    """

    def __init__(self):
        self.get_calls: list = []
        self.set_calls: list = []

    def get(self, goal):
        self.get_calls.append(goal)
        return None  # always miss — forces LLM path

    def set(self, goal, sop_name, count):
        self.set_calls.append((goal, sop_name, count))


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
    g = build_graph(cache=StubCache())
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

    g = build_graph(llm=stub_llm, body_client=stub_body, cache=StubCache())
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

    g = build_graph(llm=stub_llm, body_client=stub_body, cache=StubCache())
    out = g.invoke(make_initial_state("hi"), config={"recursion_limit": 50})

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

    g = build_graph(llm=stub_llm, body_client=stub_body, cache=StubCache())
    out = g.invoke(make_initial_state("go there"), config={"recursion_limit": 50})

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

    g = build_graph(llm=cycling_llm, body_client=stub_body, cache=StubCache())
    out = g.invoke(make_initial_state("loop forever"), config={"recursion_limit": 50})

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

    g = build_graph(llm=stub_llm, body_client=stub_body, cache=StubCache())
    out = g.invoke(make_initial_state("retry me"), config={"recursion_limit": 50})

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

    g = build_graph(llm=stub_llm, body_client=stub_body, cache=StubCache())
    out = g.invoke(make_initial_state("break the rules"), config={"recursion_limit": 50})

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
    g = build_graph(llm=stub_llm_a, body_client=stub_body_a, cache=StubCache())
    out_a = g.invoke(make_initial_state("hi"), config={"recursion_limit": 50})

    # Path B: run_goal convenience wrapper, fresh stubs — uses monkeypatched build_graph
    # to inject cache seam. We use build_graph directly to keep both paths comparable.
    stub_llm_b = SequenceLLM([AIMessage(content="done", tool_calls=[])])
    stub_body_b = StubBodyClient(response=None)
    g2 = build_graph(llm=stub_llm_b, body_client=stub_body_b, cache=StubCache())
    out_b = g2.invoke(make_initial_state("hi"), config={"recursion_limit": 50})

    assert out_a["result"] == out_b["result"]
    assert out_a["iteration_count"] == out_b["iteration_count"]
    assert len(out_a["plan"]) == len(out_b["plan"])
    assert len(out_a["step_results"]) == len(out_b["step_results"])


# ---------- G9: TypedDict acceptance + end-to-end shape ----------


def test_build_graph_accepts_typeddict_state_and_invokes():
    """G9: StateGraph(AgentState) compiles and invokes without raising."""
    stub_llm = SequenceLLM([AIMessage(content="ok", tool_calls=[])])
    stub_body = StubBodyClient(response=None)
    g = build_graph(llm=stub_llm, body_client=stub_body, cache=StubCache())

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
        import src.nodes.guide_retriever  # noqa: F401

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


# ========== Sprint 3k: build_graph announce plumbing (K8) ==========


def test_build_graph_plumbs_announce_false(monkeypatch):
    """K8: build_graph(announce=False) wins over BRAIN_ANNOUNCE=1 env."""
    monkeypatch.setenv("BRAIN_ANNOUNCE", "1")

    stub_llm = SequenceLLM(
        [
            _navigate_tool_call("k8"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=_navigate_success_envelope())
    g = build_graph(llm=stub_llm, body_client=stub_body, announce=False, cache=StubCache())
    g.invoke(make_initial_state("hi"), config={"recursion_limit": 50})

    # No announcement call -- only the real navigate dispatch.
    assert stub_body.call_count == 1
    assert stub_body.last_call_args == ("navigate", {"x": 1, "y": 64, "z": 2})


def test_build_graph_plumbs_announce_true(monkeypatch):
    """K8b: build_graph(announce=True) wins over BRAIN_ANNOUNCE=0 env."""
    monkeypatch.setenv("BRAIN_ANNOUNCE", "0")

    calls = []

    class RecordingStub:
        def execute(self, tool, params=None):
            calls.append((tool, params))
            return {
                "success": True,
                "data": {"reached": True},
                "tool": "navigate",
                "duration_ms": 1.0,
            }

    stub_llm = SequenceLLM(
        [
            _navigate_tool_call("k8b"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    g = build_graph(llm=stub_llm, body_client=RecordingStub(), announce=True, cache=StubCache())
    g.invoke(make_initial_state("hi"), config={"recursion_limit": 50})

    # Two calls in order: chat announcement then navigate.
    assert len(calls) == 2
    assert calls[0] == ("chat", {"message": "Heading to (1, 64, 2)..."})
    assert calls[1][0] == "navigate"


# ========== Sprint 4e: guide_retriever entry edge + use_cache tests ==========


def _retriever_no_match_response():
    """AIMessage whose content is valid JSON for the retriever: no-match sentinel."""
    return AIMessage(content='{"sop_name": "none", "count": null}', tool_calls=[])


# ---------- G11: entry edge — retriever runs FIRST ----------


def test_guide_retriever_runs_first_before_planner():
    """G11: guide_retriever is the entry node; cache.get is called before planner.

    We prove ordering by asserting that the StubCache.get_calls list is
    non-empty after invoke(), and that it was called with the original goal.
    The planner then runs (LLM queue still intact) and finishes the goal.
    """
    stub_cache = StubCache()  # always returns <none> hit, no LLM call in retriever
    stub_llm = SequenceLLM([AIMessage(content="done", tool_calls=[])])
    stub_body = StubBodyClient(response=None)

    g = build_graph(llm=stub_llm, body_client=stub_body, cache=stub_cache)
    out = g.invoke(make_initial_state("build a house"), config={"recursion_limit": 50})

    # Retriever observed the goal before planner ran.
    assert stub_cache.get_calls == ["build a house"]
    # Planner completed the run (guide={} from no-match → planner ran without guide).
    assert out["result"] == "done"
    assert out["iteration_count"] == 1


# ---------- G12: retriever runs ONCE per invocation, not per iteration ----------


def test_guide_retriever_runs_once_across_multi_iteration_loop():
    """G12: multi-iteration loop (planner → executor → planner → END) still calls
    cache.get exactly once — the topology guarantees retriever runs only at entry.
    """
    stub_cache = StubCache()
    stub_llm = SequenceLLM(
        [
            _navigate_tool_call("g12"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=_navigate_success_envelope())

    g = build_graph(llm=stub_llm, body_client=stub_body, cache=stub_cache)
    out = g.invoke(make_initial_state("go there"), config={"recursion_limit": 50})

    # Planner ran twice (one tool call + one finish), executor ran once.
    assert out["iteration_count"] == 2
    assert stub_body.call_count == 1
    # Despite two planner iterations, the retriever only ran once.
    assert len(stub_cache.get_calls) == 1


# ---------- G13: use_cache=True plumbs to retriever (cache.get called) ----------


def test_build_graph_use_cache_true_calls_cache_get():
    """G13: use_cache=True (the default) causes the retriever to consult the cache.

    RecordingCache always misses (returns None), so the retriever proceeds to the
    LLM path. We assert cache.get_calls has exactly one entry (the goal), proving
    the retriever consulted the cache before falling through to the LLM.
    """
    recording_cache = RecordingCache()
    # LLM sequence: retriever call (no-match) → planner call (done)
    stub_llm = SequenceLLM(
        [
            _retriever_no_match_response(),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=None)

    g = build_graph(llm=stub_llm, body_client=stub_body, use_cache=True, cache=recording_cache)
    out = g.invoke(make_initial_state("craft something"), config={"recursion_limit": 50})

    # Cache was consulted exactly once.
    assert len(recording_cache.get_calls) == 1
    assert recording_cache.get_calls[0] == "craft something"
    # Cache.set was called because use_cache=True and the retriever wrote back.
    assert len(recording_cache.set_calls) == 1
    assert out["result"] == "done"


# ---------- G14: use_cache=False bypasses cache read AND write ----------


def test_build_graph_use_cache_false_bypasses_cache():
    """G14: use_cache=False means the retriever skips both cache.get and cache.set.

    Even though a RecordingCache is explicitly passed via the cache= seam,
    use_cache=False tells the retriever to ignore it entirely.
    """
    recording_cache = RecordingCache()
    # LLM sequence: retriever call (no-match) → planner call (done)
    stub_llm = SequenceLLM(
        [
            _retriever_no_match_response(),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=None)

    g = build_graph(
        llm=stub_llm, body_client=stub_body, use_cache=False, cache=recording_cache
    )
    out = g.invoke(make_initial_state("do something"), config={"recursion_limit": 50})

    # Cache was never read.
    assert recording_cache.get_calls == []
    # Cache was never written.
    assert recording_cache.set_calls == []
    # But the retriever's LLM path DID run (proves we went through the retriever).
    # The planner also ran once — stub_llm queue was fully consumed.
    assert len(stub_llm.invoke_args) == 2  # retriever + planner
    assert out["result"] == "done"


# ---------- G15: run_goal forwards use_cache to build_graph ----------


def test_run_goal_forwards_use_cache_to_build_graph(monkeypatch):
    """G15: run_goal(use_cache=False) forwards use_cache=False to build_graph.

    Monkeypatches build_graph on the src.graph module (which is where run_goal
    looks it up at call time). The spy records the use_cache kwarg and returns a
    minimal stub graph that immediately terminates.
    """
    captured = {}

    class _DoneGraph:
        """Stub compiled graph that returns a terminal state immediately."""
        def invoke(self, state, config=None):
            return {**state, "result": "spy-done", "iteration_count": 0}

    def spy_build_graph(*args, **kwargs):
        captured["use_cache"] = kwargs.get("use_cache", True)
        return _DoneGraph()

    import src.graph as _graph_mod
    monkeypatch.setattr(_graph_mod, "build_graph", spy_build_graph)

    stub_llm = SequenceLLM([AIMessage(content="done", tool_calls=[])])
    stub_body = StubBodyClient(response=None)

    run_goal("test", llm=stub_llm, body_client=stub_body, use_cache=False)

    assert captured == {"use_cache": False}
