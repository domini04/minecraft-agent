"""Stub-LLM tests for ``src.nodes.planner.planner_node``.

Every test injects a ``StubLLM`` via the ``llm=`` kwarg so the real
``get_llm()`` path is never exercised -- no network, no credentials, no
provider clients constructed. The stub records ``bind_tools`` and
``invoke`` arguments so tests can assert on tool-binding shape and the
exact message list passed to the model.
"""

from __future__ import annotations

import copy
import subprocess
import sys
import textwrap

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.nodes.planner import _SYSTEM_PROMPT, planner_node
from src.state import make_initial_state

# ---------- helpers ----------


class StubLLM:
    """Minimal LLM stub honoring the ``bind_tools``/``invoke`` contract.

    Records the arguments to ``bind_tools`` and ``invoke`` so tests can
    assert on them. ``bind_tools`` returns ``self`` for chained calls in
    the planner.
    """

    def __init__(self, response: AIMessage):
        self._response = response
        self.bind_tools_args: list = []
        self.invoke_args: list = []

    def bind_tools(self, tools):
        self.bind_tools_args.append(list(tools))
        return self

    def invoke(self, messages):
        self.invoke_args.append(list(messages))
        return self._response


def _initial_state(goal="hi", bot_status=None, plan=None, iteration_count=0):
    """Construct an AgentState with optional overrides."""
    s = make_initial_state(goal)
    if bot_status is not None:
        s["bot_status"] = bot_status
    if plan is not None:
        s["plan"] = plan
    s["iteration_count"] = iteration_count
    return s


# ---------- P1: tool-call branch ----------


def test_planner_appends_plan_on_tool_call():
    """P1: a single tool call appends a dict entry and increments counter."""
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "navigate",
                "args": {"x": 1, "y": 2, "z": 3},
                "id": "a",
            }
        ],
    )
    stub = StubLLM(response)
    state = _initial_state(goal="go there")

    new_state = planner_node(state, llm=stub)

    assert new_state["plan"] == [
        {"tool_name": "navigate", "args": {"x": 1, "y": 2, "z": 3}}
    ]
    assert new_state["iteration_count"] == 1
    # bot_status untouched (identity preserved across shallow copy).
    assert new_state["bot_status"] is state["bot_status"]


# ---------- P2/P3: no-tool-call branches ----------


def test_planner_no_tool_call_sets_result():
    """P2: zero tool calls + content -> result == content, plan untouched."""
    response = AIMessage(content="done", tool_calls=[])
    stub = StubLLM(response)
    state = _initial_state(goal="say done")

    new_state = planner_node(state, llm=stub)

    assert new_state["result"] == "done"
    assert new_state["plan"] == []
    assert new_state["iteration_count"] == 1


def test_planner_no_tool_call_empty_content_falls_back():
    """P3: zero tool calls + empty content -> result == 'goal complete'."""
    response = AIMessage(content="", tool_calls=[])
    stub = StubLLM(response)
    state = _initial_state(goal="silent")

    new_state = planner_node(state, llm=stub)

    assert new_state["result"] == "goal complete"
    assert new_state["plan"] == []
    assert new_state["iteration_count"] == 1


# ---------- P4: validation-error branch ----------


def test_planner_bad_tool_call_sets_error_result():
    """P4: malformed tool call -> error result, no plan append, counter +1."""
    # MineArgs requires count >= 1; count=0 trips the validator.
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "mine",
                "args": {"target": "oak_log", "count": 0},
                "id": "b",
            }
        ],
    )
    stub = StubLLM(response)
    state = _initial_state(goal="break the rules")

    new_state = planner_node(state, llm=stub)

    assert new_state["result"].startswith(
        "planner: LLM produced invalid tool call:"
    )
    assert new_state["plan"] == []
    assert new_state["iteration_count"] == 1


# ---------- P5: bind_tools shape ----------


def test_planner_bind_tools_called_with_six_in_index_order():
    """P5: bind_tools fires once with the six tools in index.json order."""
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "chat",
                "args": {"message": "hi"},
                "id": "c",
            }
        ],
    )
    stub = StubLLM(response)
    state = _initial_state(goal="chat hi")

    planner_node(state, llm=stub)

    assert len(stub.bind_tools_args) == 1
    bound_tools = stub.bind_tools_args[0]
    assert len(bound_tools) == 6
    names = [t.name for t in bound_tools]
    assert names == [
        "chat",
        "get_bot_status",
        "navigate",
        "mine",
        "craft",
        "place_block",
    ]


# ---------- P6: invoke message shape ----------


def test_planner_invoke_messages_shape():
    """P6: invoke gets [SystemMessage, HumanMessage] with correct content."""
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "navigate",
                "args": {"x": 10, "y": 64, "z": 20},
                "id": "d",
            }
        ],
    )
    stub = StubLLM(response)
    state = _initial_state(
        goal="get oak logs",
        bot_status={
            "position": {"x": 10, "y": 64, "z": 20},
            "health": 20,
            "food": 18,
            "inventory": [{"name": "oak_log", "count": 2}],
        },
    )

    planner_node(state, llm=stub)

    messages = stub.invoke_args[0]
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == _SYSTEM_PROMPT
    assert isinstance(messages[1], HumanMessage)
    human_content = messages[1].content
    assert "Goal: get oak logs" in human_content
    assert "position: x=10, y=64, z=20" in human_content


# ---------- P7/P8: state immutability and identity ----------


def test_planner_does_not_mutate_input_state():
    """P7: input dict and its plan list survive the call unchanged."""
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "navigate",
                "args": {"x": 1, "y": 2, "z": 3},
                "id": "e",
            }
        ],
    )
    stub = StubLLM(response)
    state = _initial_state(
        goal="go",
        bot_status={"position": {"x": 0, "y": 64, "z": 0}},
        plan=[],
        iteration_count=0,
    )
    snapshot = copy.deepcopy(state)
    plan_id_before = id(state["plan"])
    bot_status_id_before = id(state["bot_status"])

    new_state = planner_node(state, llm=stub)

    # Input state dict unchanged in every field.
    assert state == snapshot
    # Plan list identity preserved on the input (we didn't mutate it).
    assert id(state["plan"]) == plan_id_before
    # bot_status identity preserved on the input.
    assert id(state["bot_status"]) == bot_status_id_before
    # Returned plan is a NEW list (append branch).
    assert new_state["plan"] is not state["plan"]
    # bot_status identity is shared across the shallow copy.
    assert new_state["bot_status"] is state["bot_status"]


def test_planner_returns_new_dict_not_input():
    """P8: returned dict is a fresh shallow copy, not the input dict."""
    response = AIMessage(content="", tool_calls=[])
    stub = StubLLM(response)
    state = _initial_state(goal="x")

    new_state = planner_node(state, llm=stub)

    assert new_state is not state


# ---------- P9: counter increments on each branch ----------


def test_planner_increments_iteration_count_on_each_branch():
    """P9: every response shape advances iteration_count by exactly 1.

    Three sub-cases run inline: tool-call / no-tool-call / bad-tool-call.
    Each starts from ``iteration_count=2`` and asserts ``new_state ==
    3`` -- one assertion per branch keeps the test count aligned with
    the plan's N=10 count.
    """
    # tool-call branch
    tool_resp = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "navigate",
                "args": {"x": 1, "y": 2, "z": 3},
                "id": "p9a",
            }
        ],
    )
    s = _initial_state(goal="g", iteration_count=2)
    out = planner_node(s, llm=StubLLM(tool_resp))
    assert out["iteration_count"] == 3

    # no-tool-call branch
    s = _initial_state(goal="g", iteration_count=2)
    out = planner_node(s, llm=StubLLM(AIMessage(content="ok", tool_calls=[])))
    assert out["iteration_count"] == 3

    # bad-tool-call branch (MineArgs.count=0 invalid)
    bad_resp = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "mine",
                "args": {"target": "oak_log", "count": 0},
                "id": "p9b",
            }
        ],
    )
    s = _initial_state(goal="g", iteration_count=2)
    out = planner_node(s, llm=StubLLM(bad_resp))
    assert out["iteration_count"] == 3


# ---------- P10: no-network import surface ----------


def test_planner_no_network_imports():
    """P10: importing src.nodes.planner adds no extra HTTP-client surface.

    Per the plan's deny-list note: HTTP-client modules (``requests``,
    ``httpx``, ``urllib3``) are tolerated only if they ride in via the
    planner's already-required imports (``langchain_core.messages``,
    ``src.models``, ``src.tools.loader``). The test compares planner-
    induced leakage against a baseline subprocess that imports only those
    permitted dependencies; the planner must NOT widen the deny-list
    surface beyond that baseline.
    """
    deny_prefixes = ("requests", "httpx", "urllib3")

    # Baseline: import only the planner's required allowed dependencies.
    baseline_code = textwrap.dedent(
        """
        import sys
        import langchain_core.messages  # noqa: F401
        import src.models  # noqa: F401
        import src.tools.loader  # noqa: F401
        from src.state import AgentState  # noqa: F401

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

    # Planner: import src.nodes.planner only.
    planner_code = textwrap.dedent(
        """
        import sys
        import src.nodes.planner  # noqa: F401

        deny = ("requests", "httpx", "urllib3")
        leaked = sorted(m for m in sys.modules if m.startswith(deny))
        for m in leaked:
            print(m)
        """
    )
    planner_proc = subprocess.run(
        [sys.executable, "-c", planner_code],
        capture_output=True,
        text=True,
    )
    assert planner_proc.returncode == 0, (
        f"planner subprocess failed:\nstderr={planner_proc.stderr}"
    )
    planner_set = set(planner_proc.stdout.split())

    extra = planner_set - baseline_set
    assert not extra, (
        f"src.nodes.planner pulled HTTP-client modules beyond the "
        f"allowed baseline: {sorted(extra)}"
    )
    # Sanity: deny prefixes are real, the test isn't trivially vacuous.
    assert deny_prefixes  # keep prefixes referenced for readers
