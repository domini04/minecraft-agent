"""Phase-3 Executor node.

Reads the next step from ``state["plan"]``, dispatches it via the body's
``/execute`` endpoint through ``BodyClient``, coerces the response into a
typed ``ToolResult``, appends the result (as a dict) to ``state["step_results"]``,
and advances ``state["current_step"]``. If the dispatched tool was
``get_bot_status`` and the call succeeded with non-None data, refreshes
``state["bot_status"]`` from ``result.data``.

Per Sprint 3e plan §"State mutation discipline", this is the ONLY node that
writes ``bot_status``.

Three error paths are handled in-band (no exceptions escape):

* **Out-of-range step** -- ``state["result"]`` set; ``current_step`` NOT
  advanced; no body call is made.
* **Malformed envelope** (Pydantic ``ValidationError`` on coercion) --
  synthetic ``ToolResult`` with ``error.code = "MALFORMED_ENVELOPE"`` is
  appended; ``current_step`` IS advanced; ``state["result"]`` NOT set
  (graph layer decides).
* **BodyClient raises** (network error, server down, ...) -- synthetic
  ``ToolResult`` with ``error.code = "BODY_CLIENT_ERROR"`` is appended;
  ``current_step`` IS advanced; ``state["result"]`` NOT set.

The function shallow-copies ``state``, rebuilds the ``step_results`` list
(since it's the field this node mutates), and returns the new dict. The
input ``state`` is never mutated.

Lazy ``BodyClient`` import: when ``body_client is None``, the symbol is
imported inside the function body so importing this module doesn't pull
``requests`` into ``sys.modules`` (matches the lazy LLM pattern in
``planner.py``; verified by E10 in the sprint plan).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from src.models import ErrorEnvelope, ToolResult
from src.state import AgentState

if TYPE_CHECKING:
    from src.body_client import BodyClient


def executor_node(
    state: AgentState, *, body_client: "BodyClient | None" = None
) -> AgentState:
    """Dispatch the current plan step through the body and record the result.

    Args:
        state: Phase-3 ``AgentState``. Must include ``plan`` and
            ``current_step``; other fields read from defaults if absent.
        body_client: Optional injected ``BodyClient`` (or stub). When ``None``,
            a real ``BodyClient`` is constructed lazily — that import lives
            inside the function body to keep ``requests`` out of
            ``sys.modules`` at module load time.

    Returns:
        A new ``AgentState`` dict (shallow copy of the input) with
        ``step_results`` rebuilt to include the new ``ToolResult.model_dump()``,
        ``current_step`` advanced by one, and -- only on a successful
        ``get_bot_status`` call with non-None data -- ``bot_status`` replaced
        with a fresh dict copied from the result payload.
    """
    new_state: AgentState = dict(state)  # shallow copy; preserves identity of unchanged fields

    plan = state.get("plan", []) or []
    current_step = int(state.get("current_step", 0))

    # --- Out-of-range guard ------------------------------------------------
    if current_step >= len(plan):
        new_state["result"] = (
            f"executor: no step to execute "
            f"(current_step={current_step}, plan_len={len(plan)})"
        )
        return new_state

    step_dict = plan[current_step]
    tool_name = step_dict["tool_name"]
    args = step_dict.get("args", {}) or {}

    # --- Lazy BodyClient resolution ---------------------------------------
    if body_client is None:
        # Lazy import: keeps ``requests`` out of ``sys.modules`` at module load.
        from src.body_client import BodyClient

        body_client = BodyClient()

    # --- Dispatch ---------------------------------------------------------
    try:
        envelope = body_client.execute(tool_name, args)
    except Exception as exc:  # noqa: BLE001 -- intentional brain<->body boundary
        tool_result = ToolResult(
            success=False,
            data=None,
            error=ErrorEnvelope(
                code="BODY_CLIENT_ERROR",
                message=str(exc),
                context=None,
            ),
            tool=tool_name,
            duration_ms=0.0,
        )
    else:
        try:
            tool_result = ToolResult.from_envelope(envelope)
        except ValidationError as exc:
            tool_result = ToolResult(
                success=False,
                data=None,
                error=ErrorEnvelope(
                    code="MALFORMED_ENVELOPE",
                    message=str(exc),
                    context=None,
                ),
                tool=tool_name,
                duration_ms=0.0,
            )

    # --- Append result (rebuild list -- this field is the one we mutate) --
    new_state["step_results"] = list(state.get("step_results", []) or []) + [
        tool_result.model_dump()
    ]

    # --- Bot-status refresh (only this node writes bot_status) ------------
    if (
        tool_name == "get_bot_status"
        and tool_result.success
        and tool_result.data is not None
    ):
        # Copy to avoid sharing identity with tool_result.data.
        new_state["bot_status"] = dict(tool_result.data)

    # --- Advance step counter ---------------------------------------------
    new_state["current_step"] = current_step + 1

    return new_state
