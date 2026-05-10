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

import os
import sys
from typing import TYPE_CHECKING

from pydantic import ValidationError

from src.models import ErrorEnvelope, ToolResult
from src.state import AgentState

if TYPE_CHECKING:
    from src.body_client import BodyClient


# Tool name -> format string. BYTE-FROZEN per Sprint 3k plan §2.2.
# Any tool not listed here (or ``chat``) yields ``None`` from
# ``_format_announcement`` and is silently skipped.
_ANNOUNCE_TEMPLATES: dict[str, str] = {
    "get_bot_status": "Checking my status...",
    "navigate": "Heading to ({x}, {y}, {z})...",
    "mine": "Mining {count} {target}...",
    "craft": "Crafting {count} {item}...",
    "place_block": "Placing {block} at ({x}, {y}, {z})...",
}

# Env var values that DISABLE announcement (case-sensitive list per §2.4).
_ANNOUNCE_DISABLE_VALUES = frozenset({"0", "false", "False", "FALSE", "no", "off"})


def _resolve_announce(arg: bool | None) -> bool:
    """Resolve the announce flag: explicit kwarg -> env -> default ON.

    Args:
        arg: The ``announce=`` kwarg passed to ``executor_node``. ``None``
            means "fall through to env"; ``True``/``False`` is taken as-is.

    Returns:
        ``True`` when announcement should fire, ``False`` otherwise.
    """
    if arg is not None:
        return arg
    raw = os.environ.get("BRAIN_ANNOUNCE")
    if raw is None:
        return True
    return raw not in _ANNOUNCE_DISABLE_VALUES


def _format_announcement(step: dict) -> str | None:
    """Render the chat announcement for a plan step, or ``None`` to skip.

    Returns ``None`` when:

    * the tool is ``chat`` (don't announce a chat with another chat), OR
    * the tool is not in ``_ANNOUNCE_TEMPLATES`` (defensive -- planner's
      validator already excludes unknown tools).

    For ``navigate`` / ``place_block`` the x/y/z coordinates are coerced via
    ``int()`` (truncate toward zero, matching the body's pathfinder rounding).
    """
    tool_name = step.get("tool_name")
    if tool_name == "chat":
        return None
    template = _ANNOUNCE_TEMPLATES.get(tool_name)
    if template is None:
        return None
    args = step.get("args") or {}
    if tool_name == "navigate":
        return template.format(
            x=int(args.get("x", 0)),
            y=int(args.get("y", 0)),
            z=int(args.get("z", 0)),
        )
    if tool_name == "place_block":
        return template.format(
            block=args.get("block", ""),
            x=int(args.get("x", 0)),
            y=int(args.get("y", 0)),
            z=int(args.get("z", 0)),
        )
    if tool_name == "mine":
        return template.format(
            count=args.get("count", 0),
            target=args.get("target", ""),
        )
    if tool_name == "craft":
        return template.format(
            count=args.get("count", 0),
            item=args.get("item", ""),
        )
    if tool_name == "get_bot_status":
        return template
    return None  # unreachable -- keeps mypy happy


def executor_node(
    state: AgentState,
    *,
    body_client: "BodyClient | None" = None,
    announce: bool | None = None,
) -> AgentState:
    """Dispatch the current plan step through the body and record the result.

    Args:
        state: Phase-3 ``AgentState``. Must include ``plan`` and
            ``current_step``; other fields read from defaults if absent.
        body_client: Optional injected ``BodyClient`` (or stub). When ``None``,
            a real ``BodyClient`` is constructed lazily — that import lives
            inside the function body to keep ``requests`` out of
            ``sys.modules`` at module load time.
        announce: Optional override for the pre-action chat narration
            (Sprint 3k). ``None`` (default) defers to the ``BRAIN_ANNOUNCE``
            env var; absent env -> default ON. ``True``/``False`` forces the
            behavior, overriding env. When announcing, the executor sends a
            ``chat`` tool call with a deterministic per-tool template before
            dispatching the real tool; failures are swallowed and logged to
            stderr (the announcement does NOT touch ``state``).

    Returns:
        A new ``AgentState`` dict (shallow copy of the input) with
        ``step_results`` rebuilt to include the new ``ToolResult.model_dump()``,
        ``current_step`` advanced by one, and -- only on a successful
        ``get_bot_status`` call with non-None data -- ``bot_status`` replaced
        with a fresh dict copied from the result payload.
    """
    new_state: AgentState = dict(
        state
    )  # shallow copy; preserves identity of unchanged fields

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

    # --- Pre-action announcement (Sprint 3k) ------------------------------
    if _resolve_announce(announce):
        announce_text = _format_announcement(step_dict)
        if announce_text is not None:
            try:
                body_client.execute("chat", {"message": announce_text})
            except Exception as exc:  # noqa: BLE001
                print(
                    f"executor: announcement failed (swallowed): {exc!r}",
                    file=sys.stderr,
                )

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
