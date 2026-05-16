"""Structural tests for brain/src/state.py.

These tests assert shape (keys, types, defaults, mutability isolation) only.
No LLM, no HTTP, no LangGraph. Behavioural tests belong with the planner and
executor nodes (Sprints 3c/3d).
"""

from typing import get_type_hints

import pytest

from src.state import MAX_ITERATIONS, AgentState, make_initial_state

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AGENT_STATE_FIELDS = {
    "goal",
    "plan",
    "current_step",
    "step_results",
    "bot_status",
    "iteration_count",
    "result",
    "guide",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_agent_state_has_expected_fields():
    """AgentState has exactly the 8 fields including ``guide`` (Phase 4) — no more, no less.

    The set covers all Phase-3 fields plus the Phase-4 ``guide`` slot added in
    Sprint 4a. Phase-5 fields (``errors``, ``retry_count``) must not be present yet.
    """
    hints = get_type_hints(AgentState)
    assert set(hints.keys()) == _AGENT_STATE_FIELDS, (
        f"Field mismatch. Got: {set(hints.keys())!r}, expected: {_AGENT_STATE_FIELDS!r}"
    )


def test_agent_state_field_types():
    """Each AgentState field resolves to the expected Python type.

    ``list[dict]`` and ``dict`` are parameterised generics; the test checks
    the *origin* type (``list`` / ``dict``) for those and a direct ``is``
    comparison for the scalar types (``str``, ``int``).
    """
    hints = get_type_hints(AgentState)

    assert hints["goal"] is str
    assert hints["current_step"] is int
    assert hints["iteration_count"] is int
    assert hints["result"] is str

    # Parameterised generics: get_type_hints resolves list[dict] → list[dict];
    # __origin__ gives us the bare collection type.
    import typing

    plan_origin = getattr(hints["plan"], "__origin__", hints["plan"])
    step_results_origin = getattr(hints["step_results"], "__origin__", hints["step_results"])
    bot_status_origin = getattr(hints["bot_status"], "__origin__", hints["bot_status"])
    guide_origin = getattr(hints["guide"], "__origin__", hints["guide"])

    assert plan_origin is list, f"plan type origin should be list, got {plan_origin!r}"
    assert step_results_origin is list, (
        f"step_results type origin should be list, got {step_results_origin!r}"
    )
    assert bot_status_origin is dict, (
        f"bot_status type origin should be dict, got {bot_status_origin!r}"
    )
    assert guide_origin is dict, (
        f"guide type origin should be dict, got {guide_origin!r}"
    )


def test_make_initial_state_defaults():
    """make_initial_state returns all eight keys with documented defaults."""
    s = make_initial_state("test goal")

    assert s["goal"] == "test goal"
    assert s["plan"] == []
    assert s["current_step"] == 0
    assert s["step_results"] == []
    assert s["bot_status"] == {}
    assert s["iteration_count"] == 0
    assert s["result"] == ""
    assert s["guide"] == {}
    assert set(s.keys()) == _AGENT_STATE_FIELDS, (
        f"Key mismatch. Got: {set(s.keys())!r}, expected: {_AGENT_STATE_FIELDS!r}"
    )


def test_step_results_is_mutable_list():
    """step_results supports mutation and is isolated across factory calls.

    Verifies:
    1. Items can be appended to ``step_results`` and retrieved.
    2. Two separate ``make_initial_state`` calls produce distinct list objects
       (factory constructs fresh literals, not shared references).
    """
    s1 = make_initial_state("goal a")
    s2 = make_initial_state("goal b")

    # Mutation should work.
    s1["step_results"].append({"step": 0, "ok": True})
    assert s1["step_results"] == [{"step": 0, "ok": True}]

    # s2 must be unaffected — it must hold its own independent list.
    assert s2["step_results"] == []
    assert s1["step_results"] is not s2["step_results"]


def test_max_iterations_constant():
    """MAX_ITERATIONS equals 10 — locks the Phase-3 iteration cap.

    Prevents Sprint 3e's conditional edge from drifting to a different value
    without an explicit change to this module.
    """
    assert MAX_ITERATIONS == 10
