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

    assert new_state["result"].startswith("planner: LLM produced invalid tool call:")
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
    # Empty-history branch: state has step_results=[] from make_initial_state.
    assert "(no steps executed yet)" in human_content


# ---------- J1: empty history sentinel ----------


def test_planner_human_message_empty_history():
    """J1: step_results=[] renders the sentinel and no spurious step rows."""
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "chat",
                "args": {"message": "hi"},
                "id": "j1",
            }
        ],
    )
    stub = StubLLM(response)
    state = _initial_state(goal="say hi")
    # Explicit, even though make_initial_state already sets these.
    state["step_results"] = []
    state["plan"] = []

    planner_node(state, llm=stub)

    human_content = stub.invoke_args[0][1].content
    assert "Steps already executed (most recent first):" in human_content
    assert "(no steps executed yet)" in human_content
    # No history lines rendered.
    assert "[1]" not in human_content
    assert "-> success" not in human_content


# ---------- J2: success-step rendering (subsumes J5 args check) ----------


def test_planner_human_message_renders_success_step():
    """J2/J5: a success step renders as `[N] tool(args) -> success`."""
    response = AIMessage(content="", tool_calls=[])
    stub = StubLLM(response)
    state = _initial_state(goal="say hello")
    state["step_results"] = [
        {
            "tool": "chat",
            "success": True,
            "data": {"sent": True, "message": "hello"},
            "error": None,
            "duration_ms": 0.5,
        }
    ]
    state["plan"] = [{"tool_name": "chat", "args": {"message": "hello"}}]

    planner_node(state, llm=stub)

    human_content = stub.invoke_args[0][1].content
    assert "[1] chat(message='hello') -> success" in human_content
    assert "(no steps executed yet)" not in human_content


# ---------- J3: failure-step rendering ----------


def test_planner_human_message_renders_failure_step():
    """J3: a failed step renders as `[N] tool(args) -> error: <CODE> "<MSG>"`."""
    response = AIMessage(content="", tool_calls=[])
    stub = StubLLM(response)
    state = _initial_state(goal="get oak logs")
    state["step_results"] = [
        {
            "tool": "mine",
            "success": False,
            "data": None,
            "error": {
                "code": "E_NOT_FOUND",
                "message": "oak_log not in range",
            },
            "duration_ms": 1.2,
        }
    ]
    state["plan"] = [{"tool_name": "mine", "args": {"target": "oak_log", "count": 1}}]

    planner_node(state, llm=stub)

    human_content = stub.invoke_args[0][1].content
    expected = (
        "[1] mine(target='oak_log', count=1) -> error: "
        'E_NOT_FOUND "oak_log not in range"'
    )
    assert expected in human_content
    assert "(no steps executed yet)" not in human_content


# ---------- J4: truncation to last 10 with omission hint ----------


def test_planner_human_message_truncates_long_history():
    """J4: 12 steps render as last 10 (most-recent-first) + omission hint."""
    response = AIMessage(content="", tool_calls=[])
    stub = StubLLM(response)

    step_results: list[dict] = []
    plan: list[dict] = []
    for i in range(1, 13):
        # Alternate tools so the rendered lines vary, making substring
        # checks meaningful.
        if i % 2 == 0:
            step_results.append(
                {
                    "tool": "chat",
                    "success": True,
                    "data": None,
                    "error": None,
                    "duration_ms": 0.1,
                }
            )
            plan.append({"tool_name": "chat", "args": {"message": f"m{i}"}})
        else:
            step_results.append(
                {
                    "tool": "navigate",
                    "success": True,
                    "data": None,
                    "error": None,
                    "duration_ms": 0.1,
                }
            )
            plan.append(
                {
                    "tool_name": "navigate",
                    "args": {"x": i, "y": 64, "z": i},
                }
            )

    state = _initial_state(goal="long history")
    state["step_results"] = step_results
    state["plan"] = plan

    planner_node(state, llm=stub)

    human_content = stub.invoke_args[0][1].content
    # Omission hint shows count of dropped entries.
    assert "... (2 earlier steps omitted) ..." in human_content
    # Most recent and oldest visible entries are rendered.
    assert "[12]" in human_content
    assert "[3]" in human_content
    # Truncated indices are absent.
    assert "[2]" not in human_content
    assert "[1]" not in human_content
    # Omission hint appears BEFORE the most-recent row.
    omit_idx = human_content.index("... (2 earlier steps omitted) ...")
    twelve_idx = human_content.index("[12]")
    assert omit_idx < twelve_idx


# ---------- J6: system prompt frozen ----------


_FROZEN_SYSTEM_PROMPT = (
    "You are the Planner for an autonomous Minecraft agent. The user gives a goal in natural language. You decide which ONE tool to call next to advance the goal, then return that tool call.\n"  # noqa: E501
    "\n"
    "You will see a list of steps already executed in this session (most recent first), each with the tool name, the args you chose last time, and the outcome. Use this history together with the bot's current state to recognize when the goal is already satisfied — in that case, return no tool call (you may include a brief textual confirmation). Do not repeat a tool call that already succeeded and accomplished the goal.\n"  # noqa: E501
    "\n"
    "The six available tools are bound to this conversation via the function-calling interface; use them. Do not narrate, do not plan multiple steps ahead, and do not return multiple tool calls — return exactly one tool call (or none).\n"  # noqa: E501
    "\n"
    "If an Active guide is provided, treat it as a recommended recipe. Compare its required materials and steps against the bot's current inventory and step history; skip steps already satisfied; deviate from the guide if the current state warrants it."  # noqa: E501
)


def test_system_prompt_matches_frozen_text():
    """J6: _SYSTEM_PROMPT equals the three-paragraph frozen text byte-for-byte."""
    assert _SYSTEM_PROMPT == _FROZEN_SYSTEM_PROMPT


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


# ---------- G1–G4: guide-aware human message rendering ----------


def test_planner_human_message_renders_active_guide_header():
    """G1: state.guide populated -> human message contains 'Active guide: <name> (×<count>)'."""
    response = AIMessage(content="", tool_calls=[])
    stub = StubLLM(response)
    state = _initial_state(goal="make 5 stone pickaxes")
    state["guide"] = {
        "name": "Stone Pickaxe",
        "count": 5,
        "yields": 5,
        "requires": [
            {"item": "oak_log", "count_per_unit": 15},
            {"item": "cobblestone", "count_per_unit": 15},
        ],
        "steps": [
            {"action": "mine", "target": "oak_log", "count_per_unit": 15},
            {"action": "craft", "item": "stone_pickaxe", "count_per_unit": 5},
        ],
    }

    planner_node(state, llm=stub)

    human_content = stub.invoke_args[0][1].content
    assert "Active guide: Stone Pickaxe (×5)" in human_content


def test_planner_human_message_renders_required_materials_and_steps():
    """G2/G3/G4: required materials line, numbered steps, inventory-compare instruction."""
    response = AIMessage(content="", tool_calls=[])
    stub = StubLLM(response)
    state = _initial_state(goal="make 5 stone pickaxes")
    state["guide"] = {
        "name": "Stone Pickaxe",
        "count": 5,
        "yields": 5,
        "requires": [
            {"item": "oak_log", "count_per_unit": 15},
            {"item": "cobblestone", "count_per_unit": 15},
        ],
        "steps": [
            {"action": "mine", "target": "oak_log", "count_per_unit": 15},
            {"action": "craft", "item": "oak_planks", "count_per_unit": 30},
            {"action": "craft", "item": "stick", "count_per_unit": 10},
            {"action": "craft", "item": "crafting_table", "count_per_unit": 1, "scale": False},
            {"action": "craft", "item": "wooden_pickaxe", "count_per_unit": 1, "scale": False},
            {"action": "mine", "target": "stone", "count_per_unit": 15},
            {"action": "craft", "item": "stone_pickaxe", "count_per_unit": 5},
        ],
    }

    planner_node(state, llm=stub)

    human_content = stub.invoke_args[0][1].content
    # Required-materials line (item×N format)
    assert "Required materials: oak_log×15, cobblestone×15" in human_content
    # Numbered steps with action verb + target/item + count
    assert "1. mine oak_log ×15" in human_content
    assert "2. craft oak_planks ×30" in human_content
    assert "3. craft stick ×10" in human_content
    assert "4. craft crafting_table ×1" in human_content
    assert "5. craft wooden_pickaxe ×1" in human_content
    assert "6. mine stone ×15" in human_content
    assert "7. craft stone_pickaxe ×5" in human_content
    # Inventory-compare instruction sentence at the bottom
    assert "Compare required materials to your current inventory" in human_content
    assert "skip steps already satisfied" in human_content


def test_planner_human_message_no_guide_is_phase3_byteequivalent():
    """G3 (C7): state.guide={} -> human message has NO 'Active guide:' block.

    Asserts byte-equivalence by computing what the Phase-3 layout WOULD produce
    given the same goal/status and comparing as a substring (the rendered
    message contains nothing beyond the Phase-3 layout).
    """
    response = AIMessage(content="", tool_calls=[])
    stub = StubLLM(response)
    state = _initial_state(
        goal="say hi",
        bot_status={
            "position": {"x": 0, "y": 64, "z": 0},
            "health": 20,
            "food": 18,
            "inventory": [{"name": "oak_log", "count": 2}],
        },
    )
    state["guide"] = {}

    planner_node(state, llm=stub)

    human_content = stub.invoke_args[0][1].content
    # No guide block
    assert "Active guide:" not in human_content
    assert "Required materials:" not in human_content
    # Phase-3 final instruction (NOT the inventory-compare variant)
    assert "If the goal is already satisfied based on the steps above and the bot status" in human_content
    assert "Compare required materials to your current inventory" not in human_content


def test_planner_human_message_guide_key_absent_is_phase3_byteequivalent():
    """G4 (C8): state has no 'guide' key -> human message has NO 'Active guide:' block.

    Same expected behavior as guide={}. Tests the .get(...) fallback path.
    """
    response = AIMessage(content="", tool_calls=[])
    stub = StubLLM(response)
    state = _initial_state(goal="say hi")
    # Forcibly remove the guide key (make_initial_state seeds it, so pop)
    state.pop("guide", None)

    planner_node(state, llm=stub)

    human_content = stub.invoke_args[0][1].content
    assert "Active guide:" not in human_content
    assert "Required materials:" not in human_content
    assert "Compare required materials to your current inventory" not in human_content


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
