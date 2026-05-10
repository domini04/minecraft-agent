"""Stub-BodyClient tests for ``src.nodes.executor.executor_node``.

Every test injects a ``StubBodyClient`` via the ``body_client=`` kwarg so
the real ``BodyClient`` path is never exercised -- no network, no body
server. The stub records ``execute`` arguments so tests can assert on the
exact dispatch (tool, params) shape, and may be configured to raise
instead of returning a recorded envelope.

Coverage map (Sprint 3f plan):

* E1 -- dispatch happy path
* E2 -- dispatch failure envelope (success=False, executor doesn't set result)
* E3 -- bot_status refresh on get_bot_status success
* E4 -- no bot_status refresh on get_bot_status failure
* E5 -- no bot_status refresh on other-tool success
* E6 -- malformed envelope synthesizes MALFORMED_ENVELOPE
* E7 -- body_client.execute raises -> BODY_CLIENT_ERROR synthesized
* E8 -- out-of-range current_step (past end + empty plan sub-cases)
* E9 -- state immutability (input dict + nested lists/dicts preserved)
* E10 -- lazy body_client import (no ``requests`` in sys.modules)
"""

from __future__ import annotations

import copy
import subprocess
import sys
import textwrap

from src.nodes.executor import executor_node
from src.state import make_initial_state

# ---------- helpers ----------


class StubBodyClient:
    """Records ``(tool, params)`` and returns a pre-configured envelope.

    If ``raises`` is set, ``execute`` raises that exception instead of
    returning ``response``. Mirrors the ``StubLLM`` recorded-call pattern in
    ``test_planner_node`` -- no ``unittest.mock`` patches.
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


def _make_state(
    goal="hi",
    plan=None,
    current_step=0,
    step_results=None,
    bot_status=None,
):
    """Construct an AgentState with optional overrides."""
    s = make_initial_state(goal)
    if plan is not None:
        s["plan"] = plan
    s["current_step"] = current_step
    if step_results is not None:
        s["step_results"] = step_results
    if bot_status is not None:
        s["bot_status"] = bot_status
    return s


# ---------- E1: dispatch happy path ----------


def test_executor_dispatch_happy_path():
    """E1: navigate-success envelope is appended and current_step advances."""
    plan = [{"tool_name": "navigate", "args": {"x": 1, "y": 64, "z": 2}}]
    stub = StubBodyClient(
        response={
            "success": True,
            "data": {"reached": True},
            "tool": "navigate",
            "duration_ms": 12.3,
        }
    )
    state = _make_state(plan=plan, current_step=0)

    new_state = executor_node(state, body_client=stub, announce=False)

    assert stub.call_count == 1
    assert stub.last_call_args == ("navigate", {"x": 1, "y": 64, "z": 2})
    assert len(new_state["step_results"]) == 1
    row = new_state["step_results"][0]
    assert row["success"] is True
    assert row["tool"] == "navigate"
    assert row["data"] == {"reached": True}
    assert row["error"] is None
    assert row["duration_ms"] == 12.3
    assert new_state["current_step"] == 1
    # Executor does not set state.result on a successful step.
    assert new_state.get("result", "") == ""


# ---------- E2: dispatch failure envelope (success=False) ----------


def test_executor_dispatch_failure_envelope():
    """E2: success=False envelope is recorded; result NOT set; step advances."""
    plan = [{"tool_name": "mine", "args": {"target": "oak_log", "count": 3}}]
    stub = StubBodyClient(
        response={
            "success": False,
            "error": {
                "code": "RESOURCE_NOT_FOUND",
                "message": "no oak_log nearby",
                "context": None,
            },
            "tool": "mine",
            "duration_ms": 50.0,
        }
    )
    state = _make_state(plan=plan, current_step=0)

    new_state = executor_node(state, body_client=stub, announce=False)

    row = new_state["step_results"][-1]
    assert row["success"] is False
    assert row["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert row["error"]["message"] == "no oak_log nearby"
    assert row["data"] is None
    assert new_state["current_step"] == 1
    assert new_state.get("result", "") == ""


# ---------- E3: bot_status refresh on get_bot_status success ----------


def test_executor_bot_status_refresh_on_get_bot_status_success():
    """E3: get_bot_status success replaces bot_status with a fresh dict."""
    plan = [{"tool_name": "get_bot_status", "args": {}}]
    payload = {
        "position": {"x": 10, "y": 64, "z": 20},
        "health": 18,
        "food": 16,
        "inventory": [{"name": "oak_log", "count": 3}],
    }
    stub = StubBodyClient(
        response={
            "success": True,
            "data": payload,
            "tool": "get_bot_status",
            "duration_ms": 5.0,
        }
    )
    state = _make_state(plan=plan, current_step=0, bot_status={})

    new_state = executor_node(state, body_client=stub, announce=False)

    assert new_state["bot_status"]["position"] == {"x": 10, "y": 64, "z": 20}
    assert new_state["bot_status"]["health"] == 18
    assert new_state["bot_status"]["inventory"] == [{"name": "oak_log", "count": 3}]
    # New dict identity (input bot_status was {}; output is the refreshed copy).
    assert new_state["bot_status"] is not state["bot_status"]
    assert new_state["current_step"] == 1
    assert new_state["step_results"][-1]["success"] is True


# ---------- E4: no bot_status refresh on get_bot_status failure ----------


def test_executor_no_bot_status_refresh_on_get_bot_status_failure():
    """E4: failed get_bot_status leaves bot_status untouched (identity preserved)."""
    plan = [{"tool_name": "get_bot_status", "args": {}}]
    stub = StubBodyClient(
        response={
            "success": False,
            "error": {
                "code": "BOT_DISCONNECTED",
                "message": "bot not connected",
                "context": None,
            },
            "tool": "get_bot_status",
            "duration_ms": 1.0,
        }
    )
    initial_bot_status = {"position": {"x": 0, "y": 64, "z": 0}, "health": 20}
    state = _make_state(plan=plan, current_step=0, bot_status=initial_bot_status)

    new_state = executor_node(state, body_client=stub, announce=False)

    assert new_state["bot_status"] == {
        "position": {"x": 0, "y": 64, "z": 0},
        "health": 20,
    }
    # Identity preserved across the shallow-copy (we did NOT rewrite bot_status).
    assert new_state["bot_status"] is state["bot_status"]
    assert new_state["current_step"] == 1
    assert new_state["step_results"][-1]["success"] is False


# ---------- E5: no bot_status refresh on other-tool success ----------


def test_executor_no_bot_status_refresh_on_other_tool_success():
    """E5: a successful non-get_bot_status tool leaves bot_status untouched."""
    plan = [{"tool_name": "navigate", "args": {"x": 5, "y": 64, "z": 5}}]
    stub = StubBodyClient(
        response={
            "success": True,
            "data": {"reached": True},
            "tool": "navigate",
            "duration_ms": 8.0,
        }
    )
    initial_bot_status = {"position": {"x": 0, "y": 64, "z": 0}}
    state = _make_state(plan=plan, current_step=0, bot_status=initial_bot_status)

    new_state = executor_node(state, body_client=stub, announce=False)

    assert new_state["bot_status"] == {"position": {"x": 0, "y": 64, "z": 0}}
    assert new_state["bot_status"] is state["bot_status"]
    assert new_state["current_step"] == 1


# ---------- E6: malformed envelope synthesizes MALFORMED_ENVELOPE ----------


def test_executor_malformed_envelope_synthesizes_error_result():
    """E6: bad envelope -> MALFORMED_ENVELOPE row; step still advances."""
    plan = [{"tool_name": "chat", "args": {"message": "hi"}}]
    stub = StubBodyClient(
        response={"weird": "shape", "no_required_fields": True},
    )
    state = _make_state(plan=plan, current_step=0)

    new_state = executor_node(state, body_client=stub, announce=False)

    row = new_state["step_results"][-1]
    assert row["success"] is False
    assert row["error"]["code"] == "MALFORMED_ENVELOPE"
    assert isinstance(row["error"]["message"], str)
    assert row["error"]["message"]  # non-empty
    assert row["tool"] == "chat"
    assert row["duration_ms"] == 0.0
    assert new_state["current_step"] == 1  # still advanced
    assert new_state.get("result", "") == ""  # NOT set by executor


# ---------- E7: BodyClient.execute raises -> BODY_CLIENT_ERROR ----------


def test_executor_body_client_raise_synthesizes_error_result():
    """E7: BodyClient raises -> BODY_CLIENT_ERROR row; step still advances."""
    plan = [{"tool_name": "navigate", "args": {"x": 1, "y": 64, "z": 1}}]
    stub = StubBodyClient(raises=ConnectionError("Connection refused"))
    state = _make_state(plan=plan, current_step=0)

    new_state = executor_node(state, body_client=stub, announce=False)

    row = new_state["step_results"][-1]
    assert row["success"] is False
    assert row["error"]["code"] == "BODY_CLIENT_ERROR"
    assert row["error"]["message"] == "Connection refused"
    assert row["tool"] == "navigate"
    assert row["duration_ms"] == 0.0
    assert new_state["current_step"] == 1
    assert new_state.get("result", "") == ""
    # Stub was actually called once (and raised) -- we recorded the call.
    assert stub.call_count == 1


# ---------- E8: out-of-range current_step ----------


def test_executor_out_of_range_current_step_past_end():
    """E8a: current_step past plan end -> result set, step NOT advanced."""
    plan = [{"tool_name": "chat", "args": {"message": "hi"}}]
    stub = StubBodyClient(response=None)
    state = _make_state(plan=plan, current_step=2, step_results=[])

    new_state = executor_node(state, body_client=stub, announce=False)

    assert stub.call_count == 0
    assert new_state["result"] == (
        "executor: no step to execute (current_step=2, plan_len=1)"
    )
    assert new_state["current_step"] == 2  # NOT advanced
    assert new_state["step_results"] == []


def test_executor_out_of_range_current_step_empty_plan():
    """E8b: empty plan -> result set with plan_len=0, step NOT advanced."""
    stub = StubBodyClient(response=None)
    state = _make_state(plan=[], current_step=0, step_results=[])

    new_state = executor_node(state, body_client=stub, announce=False)

    assert stub.call_count == 0
    assert new_state["result"] == (
        "executor: no step to execute (current_step=0, plan_len=0)"
    )
    assert new_state["current_step"] == 0
    assert new_state["step_results"] == []


# ---------- E9: state immutability ----------


def test_executor_does_not_mutate_input_state():
    """E9: input state + nested lists/dicts unchanged; step_results rebuilt."""
    plan = [{"tool_name": "navigate", "args": {"x": 1, "y": 64, "z": 2}}]
    stub = StubBodyClient(
        response={
            "success": True,
            "data": {"reached": True},
            "tool": "navigate",
            "duration_ms": 12.3,
        }
    )
    state = _make_state(
        plan=plan,
        current_step=0,
        step_results=[],
        bot_status={"position": {"x": 0, "y": 64, "z": 0}},
    )
    snapshot = copy.deepcopy(state)
    plan_id_before = id(state["plan"])
    step_results_id_before = id(state["step_results"])
    bot_status_id_before = id(state["bot_status"])

    new_state = executor_node(state, body_client=stub, announce=False)

    # Deep equality: input state is unchanged in every field.
    assert state == snapshot
    # Input nested-list identities preserved (we never mutated them).
    assert id(state["plan"]) == plan_id_before
    assert id(state["step_results"]) == step_results_id_before
    assert id(state["bot_status"]) == bot_status_id_before
    # Returned step_results is a NEW list (executor rebuilt this field).
    assert new_state["step_results"] is not state["step_results"]
    # Returned dict is a fresh shallow copy, not the input dict.
    assert new_state is not state


# ---------- E10: lazy body_client import (no requests in sys.modules) ----------


def test_executor_no_network_imports():
    """E10: importing src.nodes.executor adds no extra HTTP-client surface.

    Mirrors ``test_planner_no_network_imports``: HTTP-client modules
    (``requests``, ``httpx``, ``urllib3``) are tolerated only if they ride
    in via the executor's already-required imports (``pydantic``,
    ``src.models``, ``src.state``). The test compares executor-induced
    leakage against a baseline subprocess that imports only those
    permitted dependencies; the executor must NOT widen the deny-list
    surface beyond that baseline.
    """
    deny_prefixes = ("requests", "httpx", "urllib3")

    baseline_code = textwrap.dedent(
        """
        import sys
        import pydantic  # noqa: F401
        import src.models  # noqa: F401
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

    executor_code = textwrap.dedent(
        """
        import sys
        import src.nodes.executor  # noqa: F401

        deny = ("requests", "httpx", "urllib3")
        leaked = sorted(m for m in sys.modules if m.startswith(deny))
        for m in leaked:
            print(m)
        """
    )
    executor_proc = subprocess.run(
        [sys.executable, "-c", executor_code],
        capture_output=True,
        text=True,
    )
    assert executor_proc.returncode == 0, (
        f"executor subprocess failed:\nstderr={executor_proc.stderr}"
    )
    executor_set = set(executor_proc.stdout.split())

    extra = executor_set - baseline_set
    assert not extra, (
        f"src.nodes.executor pulled HTTP-client modules beyond the "
        f"allowed baseline: {sorted(extra)}"
    )
    assert deny_prefixes  # keep prefixes referenced for readers


# ---------- bonus: stub-with-no-body-client kwarg fail-safe ----------
# (Not strictly required by E1-E10, but helps ensure tests don't accidentally
# fall through to a real BodyClient if the kwarg name ever changes. Acts as
# a smoke test for the keyword-only signature.)


def test_executor_signature_is_kwarg_only_for_body_client():
    """The body_client parameter is keyword-only (matches plan signature)."""
    import inspect

    sig = inspect.signature(executor_node)
    params = sig.parameters
    assert "body_client" in params
    assert params["body_client"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["body_client"].default is None


# ========== Sprint 3k: pre-action announcement (K1-K7) ==========


# ---------- K1: announce fires before non-chat tool dispatch ----------


def test_executor_announces_before_non_chat_tool():
    """K1: navigate step -> stub records 2 calls in order: chat then navigate."""
    plan = [{"tool_name": "navigate", "args": {"x": 1, "y": 64, "z": 2}}]
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

    state = _make_state(plan=plan, current_step=0)
    new_state = executor_node(state, body_client=RecordingStub(), announce=True)

    assert len(calls) == 2
    assert calls[0] == ("chat", {"message": "Heading to (1, 64, 2)..."})
    assert calls[1] == ("navigate", {"x": 1, "y": 64, "z": 2})
    # The actual tool result is recorded; announcement is NOT in step_results.
    assert len(new_state["step_results"]) == 1
    assert new_state["step_results"][0]["tool"] == "navigate"


# ---------- K2: announce skipped on chat tool ----------


def test_executor_skips_announce_on_chat_tool():
    """K2: chat step -> stub records 1 call (the chat itself, no announcement)."""
    plan = [{"tool_name": "chat", "args": {"message": "hello"}}]
    calls = []

    class RecordingStub:
        def execute(self, tool, params=None):
            calls.append((tool, params))
            return {
                "success": True,
                "data": None,
                "tool": "chat",
                "duration_ms": 1.0,
            }

    state = _make_state(plan=plan, current_step=0)
    new_state = executor_node(state, body_client=RecordingStub(), announce=True)

    assert len(calls) == 1
    assert calls[0] == ("chat", {"message": "hello"})
    assert new_state["step_results"][0]["tool"] == "chat"


# ---------- K3: announcement failure swallowed ----------


def test_executor_announcement_failure_is_swallowed(capsys):
    """K3: chat call raises; real tool still runs; no BODY_CLIENT_ERROR row."""
    plan = [{"tool_name": "navigate", "args": {"x": 1, "y": 64, "z": 2}}]
    calls = []

    class FlakyStub:
        def execute(self, tool, params=None):
            calls.append((tool, params))
            if tool == "chat":
                raise ConnectionError("body offline")
            return {
                "success": True,
                "data": {"reached": True},
                "tool": "navigate",
                "duration_ms": 1.0,
            }

    state = _make_state(plan=plan, current_step=0)
    new_state = executor_node(state, body_client=FlakyStub(), announce=True)

    # Both attempts happened: chat raised, navigate succeeded.
    assert len(calls) == 2
    assert calls[0][0] == "chat"
    assert calls[1][0] == "navigate"
    # Real tool result recorded; NOT a BODY_CLIENT_ERROR.
    assert len(new_state["step_results"]) == 1
    row = new_state["step_results"][0]
    assert row["success"] is True
    assert row["tool"] == "navigate"
    # Stderr got the swallow log.
    captured = capsys.readouterr()
    assert "announcement failed" in captured.err
    assert "body offline" in captured.err


# ---------- K4: announce=False disables ----------


def test_executor_announce_false_skips_chat_call():
    """K4: announce=False -> no announcement chat call, only the real tool."""
    plan = [{"tool_name": "navigate", "args": {"x": 1, "y": 64, "z": 2}}]
    stub = StubBodyClient(
        response={
            "success": True,
            "data": {"reached": True},
            "tool": "navigate",
            "duration_ms": 1.0,
        }
    )
    state = _make_state(plan=plan, current_step=0)

    new_state = executor_node(state, body_client=stub, announce=False)

    assert stub.call_count == 1
    assert stub.last_call_args == ("navigate", {"x": 1, "y": 64, "z": 2})
    assert new_state["step_results"][0]["success"] is True


# ---------- K5: env BRAIN_ANNOUNCE=0 disables ----------


def test_executor_env_disable_skips_chat_call(monkeypatch):
    """K5: BRAIN_ANNOUNCE=0 in env disables when no explicit kwarg supplied."""
    monkeypatch.setenv("BRAIN_ANNOUNCE", "0")
    plan = [{"tool_name": "navigate", "args": {"x": 1, "y": 64, "z": 2}}]
    stub = StubBodyClient(
        response={
            "success": True,
            "data": {"reached": True},
            "tool": "navigate",
            "duration_ms": 1.0,
        }
    )
    state = _make_state(plan=plan, current_step=0)

    # No announce= kwarg -> falls through to env.
    new_state = executor_node(state, body_client=stub)

    assert stub.call_count == 1
    assert stub.last_call_args == ("navigate", {"x": 1, "y": 64, "z": 2})
    assert new_state["step_results"][0]["success"] is True


def test_executor_env_default_on_when_unset(monkeypatch):
    """K5b: BRAIN_ANNOUNCE unset + no kwarg -> announcement fires (default ON)."""
    monkeypatch.delenv("BRAIN_ANNOUNCE", raising=False)
    plan = [{"tool_name": "navigate", "args": {"x": 1, "y": 64, "z": 2}}]
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

    state = _make_state(plan=plan, current_step=0)
    executor_node(state, body_client=RecordingStub())  # no announce kwarg

    assert len(calls) == 2
    assert calls[0] == ("chat", {"message": "Heading to (1, 64, 2)..."})


# ---------- K7: templates frozen (per-tool exact-string assertions) ----------


def test_announcement_template_get_bot_status():
    from src.nodes.executor import _format_announcement

    assert (
        _format_announcement({"tool_name": "get_bot_status", "args": {}})
        == "Checking my status..."
    )


def test_announcement_template_navigate_int_coerces_floats():
    from src.nodes.executor import _format_announcement

    # Floats are int-coerced (truncate toward zero).
    assert (
        _format_announcement(
            {"tool_name": "navigate", "args": {"x": 1.7, "y": 64.0, "z": -2.9}}
        )
        == "Heading to (1, 64, -2)..."
    )
    # Plain ints pass through.
    assert (
        _format_announcement(
            {"tool_name": "navigate", "args": {"x": 10, "y": 64, "z": 20}}
        )
        == "Heading to (10, 64, 20)..."
    )


def test_announcement_template_mine():
    from src.nodes.executor import _format_announcement

    assert (
        _format_announcement(
            {"tool_name": "mine", "args": {"count": 3, "target": "oak_log"}}
        )
        == "Mining 3 oak_log..."
    )


def test_announcement_template_craft():
    from src.nodes.executor import _format_announcement

    assert (
        _format_announcement(
            {"tool_name": "craft", "args": {"count": 2, "item": "stick"}}
        )
        == "Crafting 2 stick..."
    )


def test_announcement_template_place_block_int_coerces_floats():
    from src.nodes.executor import _format_announcement

    assert (
        _format_announcement(
            {
                "tool_name": "place_block",
                "args": {"block": "stone", "x": 5.4, "y": 64.0, "z": 7.9},
            }
        )
        == "Placing stone at (5, 64, 7)..."
    )


def test_announcement_template_chat_returns_none():
    from src.nodes.executor import _format_announcement

    assert (
        _format_announcement({"tool_name": "chat", "args": {"message": "hi"}}) is None
    )


def test_announcement_template_unknown_tool_returns_none():
    from src.nodes.executor import _format_announcement

    assert _format_announcement({"tool_name": "fly_to_mars", "args": {}}) is None
