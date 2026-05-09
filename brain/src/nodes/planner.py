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


# Frozen system prompt -- MUST match Sprint 3e plan §System prompt verbatim.
# Long lines are required to preserve byte-for-byte equivalence with the plan,
# hence the per-line E501 silencing.
_SYSTEM_PROMPT = (
    "You are the Planner for an autonomous Minecraft agent. The user gives a goal in natural language. You decide which ONE tool to call next to advance the goal, then return that tool call.\n"  # noqa: E501
    "\n"
    "If the goal is already satisfied based on the bot's current state, return no tool call (you may include a brief textual confirmation).\n"  # noqa: E501
    "\n"
    "The six available tools are bound to this conversation via the function-calling interface; use them. Do not narrate, do not plan multiple steps ahead, and do not return multiple tool calls — return exactly one tool call (or none)."  # noqa: E501
)


def _format_human_message(goal: str, bot_status: dict) -> str:
    """Render the compact human-message template fed to the Planner LLM.

    Format (frozen):

        Goal: <goal>

        Bot status:
        - position: <x=..., y=..., z=...> | unknown
        - health: <value> | unknown
        - food: <value> | unknown
        - inventory: <name1, name2, ...> | empty

        Decide the next single tool call.

    Position is rendered numerically without rounding when ``bot_status``
    carries a ``{"x", "y", "z"}`` sub-dict; otherwise ``unknown``. Inventory
    is rendered as a comma-joined list of item names (counts deliberately
    omitted to keep the prompt compact, per Constraint 2).
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
        item["name"]
        for item in inventory
        if isinstance(item, dict) and "name" in item
    ]
    inventory_str = ", ".join(names) if names else "empty"

    return (
        f"Goal: {goal}\n"
        "\n"
        "Bot status:\n"
        f"- position: {position_str}\n"
        f"- health: {health_str}\n"
        f"- food: {food_str}\n"
        f"- inventory: {inventory_str}\n"
        "\n"
        "Decide the next single tool call."
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
