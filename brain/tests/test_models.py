"""Tests for src.models — ToolResult coercion + PlannerOutput discriminated union.

Pure structural/typing tests. No LLM calls, no network, no body server.
"""

import pytest
from pydantic import ValidationError

from src.models import (
    ChatPlan,
    MinePlan,
    NavigatePlan,
    ToolResult,
    parse_planner_output,
)

# ---------- PlannerOutput discriminated union ----------


def test_planner_output_navigate_variant():
    """A navigate plan dict parses to NavigatePlan with float-coerced coords."""
    p = parse_planner_output(
        {"tool_name": "navigate", "args": {"x": 1, "y": 2, "z": 3}}
    )
    assert isinstance(p, NavigatePlan)
    assert p.args.x == 1.0
    assert p.args.y == 2.0
    assert p.args.z == 3.0


def test_planner_output_chat_variant():
    """A chat plan dict parses to ChatPlan."""
    p = parse_planner_output({"tool_name": "chat", "args": {"message": "hi"}})
    assert isinstance(p, ChatPlan)
    assert p.args.message == "hi"


def test_planner_output_rejects_unknown_tool():
    """An unknown tool_name fails the discriminated union."""
    with pytest.raises(ValidationError):
        parse_planner_output({"tool_name": "explode", "args": {}})


def test_planner_output_rejects_mismatched_args():
    """Args that don't satisfy the matching args model fail validation."""
    with pytest.raises(ValidationError):
        # mine doesn't accept `x`
        parse_planner_output({"tool_name": "mine", "args": {"x": 1}})


def test_planner_output_mine_happy_path():
    """A well-formed mine plan parses to MinePlan."""
    p = parse_planner_output(
        {"tool_name": "mine", "args": {"target": "oak_log", "count": 3}}
    )
    assert isinstance(p, MinePlan)
    assert p.args.target == "oak_log"
    assert p.args.count == 3
    assert p.args.max_distance is None


# ---------- ToolResult coercion + invariant ----------


def test_tool_result_from_envelope_success():
    """A success envelope coerces with data preserved and error=None."""
    r = ToolResult.from_envelope(
        {"success": True, "data": {"foo": 1}, "tool": "chat", "duration_ms": 0.5}
    )
    assert r.success is True
    assert r.error is None
    assert r.data == {"foo": 1}
    assert r.tool == "chat"
    assert r.duration_ms == 0.5


def test_tool_result_from_envelope_success_with_null_data():
    """A success envelope with data=null is accepted (e.g. place_block no-payload)."""
    r = ToolResult.from_envelope(
        {"success": True, "data": None, "tool": "place_block", "duration_ms": 1.0}
    )
    assert r.success is True
    assert r.data is None
    assert r.error is None


def test_tool_result_from_envelope_failure():
    """A failure envelope coerces ErrorEnvelope nested-dict into typed object."""
    r = ToolResult.from_envelope(
        {
            "success": False,
            "data": None,
            "error": {"code": "TIMEOUT", "message": "x", "context": None},
            "tool": "mine",
            "duration_ms": 1.2,
        }
    )
    assert r.success is False
    assert r.error is not None
    assert r.error.code == "TIMEOUT"
    assert r.error.message == "x"
    assert r.error.context is None


def test_tool_result_invariant_violation():
    """success=True with non-None error is rejected (cross-field invariant)."""
    with pytest.raises(ValidationError):
        ToolResult.from_envelope(
            {
                "success": True,
                "error": {"code": "X", "message": "y"},
                "tool": "chat",
                "duration_ms": 0.1,
            }
        )


def test_tool_result_failure_requires_error():
    """success=False without an error is rejected (cross-field invariant)."""
    with pytest.raises(ValidationError):
        ToolResult.from_envelope(
            {"success": False, "tool": "chat", "duration_ms": 0.1}
        )
