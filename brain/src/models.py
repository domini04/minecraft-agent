"""Typed envelope + planner-output models for the Phase-3 graph.

This module pairs with ``src.tools.loader`` to produce the typed boundary
between the LangGraph nodes and (a) the LLM tool-call dicts coming from
``llm.bind_tools(...)``; (b) the body's ``/execute`` envelope dicts coming
from ``BodyClient.execute(...)``.

Public surface:

* ``ErrorEnvelope`` — strict shape mirroring Decision 18.
* ``ToolResult`` — typed wrapper around the body's ``/execute`` envelope.
  ``from_envelope(dict) -> ToolResult`` is the coercer used by the executor
  node (Sprint 3f). A ``model_validator(mode="after")`` enforces the
  cross-field success/error pairing invariant. Note: per Decision 17/18,
  ``data`` MAY be ``None`` even on ``success=True`` (e.g. ``place_block``'s
  no-payload success), so that pairing is not enforced here.
* ``PlannerOutput`` — Pydantic v2 discriminated union over six per-tool plan
  variants keyed by ``tool_name``. ``parse_planner_output(dict)`` coerces an
  LLM tool-call dict into the matching typed variant.

No LLM imports, no network, no body server. Tests are pure structural.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from src.tools.loader import (
    ChatArgs,
    CraftArgs,
    GetBotStatusArgs,
    MineArgs,
    NavigateArgs,
    PlaceBlockArgs,
)

__all__ = [
    "ErrorEnvelope",
    "ToolResult",
    "ChatPlan",
    "GetBotStatusPlan",
    "NavigatePlan",
    "MinePlan",
    "CraftPlan",
    "PlaceBlockPlan",
    "PlannerOutput",
    "parse_planner_output",
]


# ---------- Body /execute envelope ----------


class ErrorEnvelope(BaseModel):
    """Shape of the ``error`` sub-dict in a body ``/execute`` failure response."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    context: Optional[dict] = None


class ToolResult(BaseModel):
    """Typed wrapper around the body's ``/execute`` envelope.

    Mirrors Decision 17/18's envelope shape:

    * ``success: bool`` — whether the body completed the tool call.
    * ``data`` — tool-specific payload on success, ``None`` for tools that
      have no return data (e.g. ``place_block``). NOT enforced as
      non-None on success — the body legitimately returns ``data: null``
      for some success cases.
    * ``error`` — populated iff ``success=False``; ``None`` iff
      ``success=True``. Enforced by ``_check_success_invariant`` below.
    * ``tool`` — the tool name that produced the envelope.
    * ``duration_ms`` — wall-clock duration as measured by the body.

    The hard invariant is the success<->error pairing, not the success<->data
    pairing.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    data: Optional[dict] = None
    error: Optional[ErrorEnvelope] = None
    tool: str
    duration_ms: float

    @model_validator(mode="after")
    def _check_success_invariant(self) -> "ToolResult":
        if self.success and self.error is not None:
            raise ValueError(
                "success=True envelope must have error=None"
            )
        if not self.success and self.error is None:
            raise ValueError(
                "success=False envelope must include error"
            )
        return self

    @classmethod
    def from_envelope(cls, envelope: dict) -> "ToolResult":
        """Coerce a raw body envelope dict into a typed ``ToolResult``.

        Pydantic handles nested coercion (the ``error`` sub-dict becomes an
        ``ErrorEnvelope``). Validation errors propagate as ``ValidationError``.
        """
        return cls.model_validate(envelope)


# ---------- Planner-output discriminated union ----------


class ChatPlan(BaseModel):
    """Planner output variant: a ``chat`` tool call."""

    model_config = ConfigDict(extra="forbid")

    tool_name: Literal["chat"]
    args: ChatArgs


class GetBotStatusPlan(BaseModel):
    """Planner output variant: a ``get_bot_status`` tool call."""

    model_config = ConfigDict(extra="forbid")

    tool_name: Literal["get_bot_status"]
    args: GetBotStatusArgs


class NavigatePlan(BaseModel):
    """Planner output variant: a ``navigate`` tool call."""

    model_config = ConfigDict(extra="forbid")

    tool_name: Literal["navigate"]
    args: NavigateArgs


class MinePlan(BaseModel):
    """Planner output variant: a ``mine`` tool call."""

    model_config = ConfigDict(extra="forbid")

    tool_name: Literal["mine"]
    args: MineArgs


class CraftPlan(BaseModel):
    """Planner output variant: a ``craft`` tool call."""

    model_config = ConfigDict(extra="forbid")

    tool_name: Literal["craft"]
    args: CraftArgs


class PlaceBlockPlan(BaseModel):
    """Planner output variant: a ``place_block`` tool call."""

    model_config = ConfigDict(extra="forbid")

    tool_name: Literal["place_block"]
    args: PlaceBlockArgs


PlannerOutput = Annotated[
    Union[
        ChatPlan,
        GetBotStatusPlan,
        NavigatePlan,
        MinePlan,
        CraftPlan,
        PlaceBlockPlan,
    ],
    Field(discriminator="tool_name"),
]
"""Discriminated union over the six per-tool plan variants.

Use ``parse_planner_output`` to coerce a dict into the matching variant.
Bare ``PlannerOutput`` is exported so consumers can construct their own
``TypeAdapter`` if they prefer.
"""

_PLANNER_OUTPUT_ADAPTER: TypeAdapter = TypeAdapter(PlannerOutput)


def parse_planner_output(data: dict):
    """Coerce an LLM tool-call dict into the matching ``PlannerOutput`` variant.

    Args:
        data: dict shaped ``{"tool_name": <name>, "args": {...}}``.

    Returns:
        One of ``ChatPlan``/``GetBotStatusPlan``/.../``PlaceBlockPlan``.

    Raises:
        pydantic.ValidationError: when ``tool_name`` is unknown or ``args``
            don't satisfy the matching args model.
    """
    return _PLANNER_OUTPUT_ADAPTER.validate_python(data)
