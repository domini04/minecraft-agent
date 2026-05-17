"""Phase-3 Planner node.

Reads ``state["goal"]`` and ``state["bot_status"]``, asks the LLM (with the
six tools bound via ``bind_tools(get_tools())``) which ONE tool to call next,
and writes the resulting plan entry into ``state["plan"]``. Per Decision 24
this is single-step: each planner invocation produces zero-or-one tool call.

Three response shapes are handled:

* **One tool call** -- coerced through ``parse_planner_output`` into a
  ``PlannerOutput`` variant; appended to ``state["plan"]`` as the dict
  ``{"tool_name": <name>, "args": <args dict>}``.
* **Zero tool calls** -- treated as "goal satisfied"; ``state["result"]`` is
  set to ``response.content`` (or the literal ``"goal complete"`` if content
  is empty); ``state["plan"]`` is NOT appended to.
* **Validation error** on a malformed tool-call -- ``state["result"]`` is set
  to ``"planner: LLM produced invalid tool call: <error message>"``;
  ``state["plan"]`` is NOT appended to. Phase 5 will replace this bail with a
  retry/Reflexion loop.

In all three cases ``state["iteration_count"]`` is incremented by exactly 1.
``state["bot_status"]`` is read but never written -- the executor (Sprint 3f)
owns bot_status updates.

The function is pure-in-spirit: it shallow-copies the input ``AgentState``
dict, mutates the copy, and returns it. The caller (LangGraph) never sees a
mutated input.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from src.models import parse_planner_output
from src.state import AgentState
from src.tools.loader import get_tools

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


# Frozen system prompt -- MUST match Sprint 3j plan §System prompt verbatim.
# Long lines are required to preserve byte-for-byte equivalence with the plan,
# hence the per-line E501 silencing.
_SYSTEM_PROMPT = (
    "You are the Planner for an autonomous Minecraft agent. The user gives a goal in natural language. You decide which ONE tool to call next to advance the goal, then return that tool call.\n"  # noqa: E501
    "\n"
    "You will see a list of steps already executed in this session (most recent first), each with the tool name, the args you chose last time, and the outcome. Use this history together with the bot's current state to recognize when the goal is already satisfied — in that case, return no tool call (you may include a brief textual confirmation). Do not repeat a tool call that already succeeded and accomplished the goal.\n"  # noqa: E501
    "\n"
    "The six available tools are bound to this conversation via the function-calling interface; use them. Do not narrate, do not plan multiple steps ahead, and do not return multiple tool calls — return exactly one tool call (or none).\n"  # noqa: E501
    "\n"
    "If an Active guide is provided, treat it as a recommended recipe. Compare its required materials and steps against the bot's current inventory and step history; skip steps already satisfied; deviate from the guide if the current state warrants it."  # noqa: E501
)


def _format_guide_block(guide: dict) -> str:
    """Render the 'Active guide:' block from a scaled guide dict.

    Output shape::

        Active guide: <display_name> (×<count>)
          Required materials: <item1>×<n1>, <item2>×<n2>, ...
          Steps:
            1. <action> <target_or_item> ×<count_per_unit>
            ...

    The multiplier character is Unicode × (U+00D7), not ASCII x.
    """
    display_name = guide.get("name", "<unnamed SOP>")
    count = guide.get("count")
    count_str = str(count) if isinstance(count, int) and not isinstance(count, bool) else "?"

    requires = guide.get("requires") or []
    if requires:
        materials_parts = [f"{r['item']}×{r['count_per_unit']}" for r in requires]
        materials_line = f"  Required materials: {', '.join(materials_parts)}"
    else:
        materials_line = "  Required materials: (none)"

    steps = guide.get("steps") or []
    step_lines: list[str] = ["  Steps:"]
    for i, step in enumerate(steps, start=1):
        action = step.get("action", "?")
        if action == "mine":
            target_or_item = step.get("target", "?")
        else:
            target_or_item = step.get("item") or step.get("target") or "?"
        cpu = step.get("count_per_unit", "?")
        step_lines.append(f"    {i}. {action} {target_or_item} ×{cpu}")

    steps_block = "\n".join(step_lines)

    return (
        f"Active guide: {display_name} (×{count_str})\n"
        f"{materials_line}\n"
        f"{steps_block}"
    )


def _format_step_history(step_results: list[dict], plan: list[dict]) -> str:
    """Render the 'Steps already executed' block (frozen format).

    Returns the full multi-line block, including the
    ``Steps already executed (most recent first):`` header. If
    ``step_results`` is empty, the body is the single sentinel line
    ``  (no steps executed yet)``. Otherwise the most-recent-first list
    of step lines is rendered, capped at the last 10 entries with an
    omission hint above when more exist.

    This function does NOT mutate either input. ``step_results`` is sliced
    (which produces a fresh list) and then iterated; ``plan`` is only
    indexed. The frozen per-line shape is::

        [N] tool_name(k=repr(v), ...) -> success
        [N] tool_name(k=repr(v), ...) -> error: <CODE> "<MESSAGE>"

    where ``N`` is 1-based and matches "iteration N".
    """
    header = "Steps already executed (most recent first):"

    if not step_results:
        return f"{header}\n  (no steps executed yet)"

    total = len(step_results)
    # Show only the last 10 entries, in storage order (oldest of-the-visible
    # first); we then reverse so most recent appears first. Slicing returns
    # fresh lists -- no mutation of inputs.
    visible = step_results[-10:]
    # Map visible entries back to their original 1-based index. The last
    # entry's display index is `total`; the entry before it is `total-1`; etc.
    visible_indices = list(range(total - len(visible) + 1, total + 1))

    lines: list[str] = [header]
    if total > 10:
        omitted = total - 10
        lines.append(f"  ... ({omitted} earlier steps omitted) ...")

    # Reverse so most-recent-first.
    for display_idx, step in zip(
        reversed(visible_indices), reversed(visible), strict=True
    ):
        # Storage position of this step in the original step_results list.
        storage_idx = display_idx - 1

        # Tool name: prefer step_results[i]["tool"], fall back to
        # plan[i]["tool_name"], else literal "unknown_tool".
        tool_name = step.get("tool") if isinstance(step, dict) else None
        if not tool_name:
            if storage_idx < len(plan) and isinstance(plan[storage_idx], dict):
                tool_name = plan[storage_idx].get("tool_name")
        if not tool_name:
            tool_name = "unknown_tool"

        # Args: pull from plan[i]["args"] (a dict). Render as
        # key=repr(value), joined by ", ", in dict insertion order. If
        # plan[i] is missing, render no args (empty parens).
        if storage_idx < len(plan) and isinstance(plan[storage_idx], dict):
            args = plan[storage_idx].get("args") or {}
        else:
            args = {}
        if isinstance(args, dict) and args:
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
        else:
            args_str = ""

        # Outcome: success -> " -> success"; failure -> error code+message.
        success = bool(step.get("success")) if isinstance(step, dict) else False
        if success:
            outcome = " -> success"
        else:
            err = step.get("error") if isinstance(step, dict) else None
            if isinstance(err, dict):
                code = err.get("code") or "<unknown>"
                message = err.get("message") or "<unknown>"
            else:
                code = "<unknown>"
                message = "<unknown>"
            outcome = f' -> error: {code} "{message}"'

        lines.append(f"  [{display_idx}] {tool_name}({args_str}){outcome}")

    return "\n".join(lines)


def _format_human_message(
    goal: str,
    bot_status: dict,
    step_results: list[dict],
    plan: list[dict],
    guide: dict | None = None,
) -> str:
    """Render the compact human-message template fed to the Planner LLM.

    When ``guide`` is truthy, an 'Active guide:' block is inserted between
    the inventory line and the step history, and the final instruction
    sentence switches to the inventory-compare variant. When ``guide`` is
    falsy (None, {}, or absent), the output is byte-identical to the
    Phase-3 layout.

    Position is rendered numerically without rounding when ``bot_status``
    carries a ``{"x", "y", "z"}`` sub-dict; otherwise ``unknown``. Inventory
    is rendered as a comma-joined list of item names (counts deliberately
    omitted to keep the prompt compact, per Constraint 2).

    The step-history block is delegated to ``_format_step_history`` --
    see that function for per-step formatting rules and truncation. Neither
    helper mutates ``step_results`` or ``plan``.
    """
    pos = bot_status.get("position")
    if isinstance(pos, dict) and "x" in pos and "y" in pos and "z" in pos:
        position_str = f"x={pos['x']}, y={pos['y']}, z={pos['z']}"
    else:
        position_str = "unknown"

    health = bot_status.get("health")
    health_str = "unknown" if health is None else str(health)

    food = bot_status.get("food")
    food_str = "unknown" if food is None else str(food)

    inventory = bot_status.get("inventory") or []
    names = [
        item["name"] for item in inventory if isinstance(item, dict) and "name" in item
    ]
    inventory_str = ", ".join(names) if names else "empty"

    history_block = _format_step_history(step_results, plan)

    guide_section = ""
    final_instruction = (
        "Decide the next single tool call. If the goal is already satisfied based on the steps above and the bot status, return no tool call."  # noqa: E501
    )
    if guide:
        guide_section = f"{_format_guide_block(guide)}\n\n"
        final_instruction = (
            "Decide the next single tool call. Compare required materials to your current inventory; skip steps already satisfied. If the goal is fully satisfied, return no tool call."  # noqa: E501
        )

    return (
        f"Goal: {goal}\n"
        "\n"
        "Bot status:\n"
        f"- position: {position_str}\n"
        f"- health: {health_str}\n"
        f"- food: {food_str}\n"
        f"- inventory: {inventory_str}\n"
        "\n"
        f"{guide_section}"
        f"{history_block}\n"
        "\n"
        f"{final_instruction}"
    )


def planner_node(
    state: AgentState, *, llm: "BaseChatModel" | None = None
) -> AgentState:
    """Phase-3 Planner: pick the next single tool call (or none).

    Args:
        state: Current ``AgentState``. Read-only as far as the caller is
            concerned -- this function shallow-copies ``state`` and returns
            the copy.
        llm: Optional injected chat model (test seam). When ``None``,
            ``get_llm()`` is called lazily inside the function so importing
            this module does not trigger network/credential resolution.

    Returns:
        A new ``AgentState`` dict with ``iteration_count`` incremented and
        either ``plan`` extended (tool-call branch) or ``result`` populated
        (no-tool-call / validation-error branch).
    """
    new_state: AgentState = dict(state)  # shallow copy -- bot_status identity preserved

    if llm is None:
        # Lazy import so module load doesn't pull provider clients.
        from src.llm import get_llm

        llm = get_llm()

    tools = get_tools()
    bound = llm.bind_tools(tools)

    system = SystemMessage(content=_SYSTEM_PROMPT)
    human = HumanMessage(
        content=_format_human_message(
            new_state.get("goal", ""),
            new_state.get("bot_status", {}) or {},
            list(new_state.get("step_results", []) or []),
            list(new_state.get("plan", []) or []),
            new_state.get("guide") or None,
        )
    )
    response = bound.invoke([system, human])

    new_state["iteration_count"] = int(new_state.get("iteration_count", 0)) + 1

    tool_calls = list(getattr(response, "tool_calls", []) or [])

    if len(tool_calls) == 0:
        content = getattr(response, "content", "") or ""
        new_state["result"] = content if content else "goal complete"
        return new_state

    # One or more -- take the first (Decision 24: single-step).
    tc = tool_calls[0]
    raw = {"tool_name": tc["name"], "args": tc["args"]}
    try:
        parse_planner_output(raw)
    except ValidationError as exc:
        new_state["result"] = f"planner: LLM produced invalid tool call: {exc}"
        return new_state

    # Build a NEW plan list so the input state's plan is never mutated.
    new_plan = list(new_state.get("plan", []) or [])
    new_plan.append({"tool_name": tc["name"], "args": tc["args"]})
    new_state["plan"] = new_plan
    return new_state
