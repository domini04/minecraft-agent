"""Stub-driven tests for the ``python -m src`` CLI entry point.

Every test that exercises the planner/executor loop injects ``StubLLM`` /
``CyclingStubLLM`` and ``StubBodyClient`` directly via ``main(..., llm=,
body_client=)`` so neither the real ``get_llm()`` nor the real
``BodyClient`` is ever exercised — no network, no credentials, no
provider clients constructed. Stubs are defined inline (not imported
from ``test_graph.py``) to keep test files independent, matching the
existing convention in ``test_graph.py:84-89``.

Subprocess tests (T3, T4, T11) shell out to ``python -m src ...`` from
the ``brain/`` directory so the package layout
(``[tool.hatch.build.targets.wheel] packages = ["src"]``) is exercised.

Coverage map (Sprint 3h plan §2.1) — H1..H14:

* T1  / H1  — module is importable, ``main`` callable.
* T2  / H2,H5 — main() with stubs returns 0; summary printed.
* T3  / H3  — ``python -m src --help`` exits 0 and mentions ``goal``.
* T4  / H4  — ``python -m src`` (no args) exits 2.
* T5  / H6  — one-step success run prints ``success=True``.
* T6  / H7  — failed step + result-set → exit 1 (has_failed branch).
* T7  / H8  — cap-exhaustion → exit 1, ``Iterations: 10``.
* T8  / H9  — ``--model`` reaches ``get_llm`` with the right kwarg.
* T9  / H10 — ``--body-url`` reaches ``BodyClient(__init__)``.
* T10 / H11 — exception during construction → exit 2 + stderr.
* T11 / H12 — ``import src.__main__`` adds no HTTP-client modules.
* T12 / extra — ``--max-iterations`` warns to stderr + still runs.
* T13 / extra — ``-v`` prints the verbose state dump.
* T14 / extra — step ``data`` truncated to 3 kv pairs and 40 chars.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.__main__ import main

BRAIN_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _disable_announce_by_default(monkeypatch):
    """Sprint 3k: turn off pre-action announcements for all main() tests
    that don't explicitly opt in. Tests that exercise announcement behavior
    override this with their own monkeypatch.setenv or `--no-announce`.
    """
    monkeypatch.setenv("BRAIN_ANNOUNCE", "0")


# ---------- inline stubs (independent of test_graph.py) ----------


class StubLLM:
    """LLM stub that returns a queued sequence of AIMessages.

    ``bind_tools`` returns ``self``. ``invoke`` pops the next response
    off the front of the queue.
    """

    def __init__(self, responses):
        self._queue = list(responses)
        self.bind_tools_calls = 0
        self.invoke_calls = 0

    def bind_tools(self, tools):
        self.bind_tools_calls += 1
        return self

    def invoke(self, messages):
        self.invoke_calls += 1
        if not self._queue:
            raise AssertionError("StubLLM exhausted")
        return self._queue.pop(0)


class CyclingStubLLM:
    """LLM stub that ALWAYS returns the same response (drives cap exhaustion)."""

    def __init__(self, response):
        self._response = response
        self.invoke_calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.invoke_calls += 1
        return self._response


class StubBodyClient:
    """Records ``(tool, params)`` and returns a pre-configured envelope."""

    def __init__(self, response=None):
        self._response = response
        self.calls = []

    def execute(self, tool, params=None):
        self.calls.append((tool, params))
        return self._response


def _navigate_tool_call(call_id="nav-1"):
    """AIMessage carrying one valid navigate tool call."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "navigate",
                "args": {"x": 1, "y": 64, "z": 2},
                "id": call_id,
            }
        ],
    )


def _navigate_success_envelope(data=None):
    return {
        "success": True,
        "data": {"reached": True} if data is None else data,
        "tool": "navigate",
        "duration_ms": 12.3,
    }


def _navigate_failure_envelope():
    return {
        "success": False,
        "data": None,
        "error": {
            "code": "PATH_NOT_FOUND",
            "message": "no path",
            "context": None,
        },
        "tool": "navigate",
        "duration_ms": 4.5,
    }


# ---------- T1: import surface ----------


def test_main_is_importable():
    """T1/H1: ``main`` is exposed and callable from ``src.__main__``."""
    assert callable(main)


# ---------- T2: stubs + zero tool calls -> exit 0 ----------


def test_main_with_stubs_returns_zero_on_goal_complete(capsys):
    """T2/H2,H5: planner returns no tool calls, planner sets result, exit 0."""
    stub_llm = StubLLM([AIMessage(content="done", tool_calls=[])])
    stub_body = StubBodyClient(response=None)

    rc = main(["hi"], llm=stub_llm, body_client=stub_body)

    out = capsys.readouterr().out
    assert rc == 0
    assert "Result:" in out
    assert "done" in out


# ---------- T3: --help works via subprocess ----------


def test_main_help_subprocess():
    """T3/H3: ``python -m src --help`` prints usage and exits 0."""
    result = subprocess.run(
        [sys.executable, "-m", "src", "--help"],
        cwd=str(BRAIN_DIR),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    assert "goal" in result.stdout


# ---------- T4: no args -> argparse exits 2 ----------


def test_main_no_args_subprocess_nonzero():
    """T4/H4: missing required ``goal`` -> argparse exits 2 with stderr."""
    result = subprocess.run(
        [sys.executable, "-m", "src"],
        cwd=str(BRAIN_DIR),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "goal" in result.stderr


# ---------- T5: single-step success run prints success=True ----------


def test_main_goal_with_one_step_success(capsys):
    """T5/H6: navigate -> done sequence prints a success=True step row."""
    stub_llm = StubLLM(
        [
            _navigate_tool_call("t5"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=_navigate_success_envelope())

    rc = main(["go there"], llm=stub_llm, body_client=stub_body)

    out = capsys.readouterr().out
    assert rc == 0
    assert "success=True" in out
    assert "navigate" in out
    assert "Result:" in out


# ---------- T6: failed step + planner sets result -> exit 1 ----------


def test_main_goal_with_failed_step(capsys):
    """T6/H7: a failure envelope makes ``has_failed`` True; classifier -> 1."""
    stub_llm = StubLLM(
        [
            _navigate_tool_call("t6"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=_navigate_failure_envelope())

    rc = main(["retry me"], llm=stub_llm, body_client=stub_body)

    out = capsys.readouterr().out
    assert rc == 1
    assert "success=False" in out
    assert "PATH_NOT_FOUND" in out


# ---------- T7: cap exhaustion -> exit 1, "Iterations: 10" ----------


def test_main_cap_exhausted_returns_one(capsys):
    """T7/H8: cycling LLM exhausts MAX_ITERATIONS=10 with no result; exit 1."""
    cycling = CyclingStubLLM(_navigate_tool_call("t7"))
    stub_body = StubBodyClient(response=_navigate_success_envelope())

    rc = main(["loop forever"], llm=cycling, body_client=stub_body)

    out = capsys.readouterr().out
    assert rc == 1
    assert "Iterations: 10" in out
    # No truthy result was set by the planner.
    assert "(no result" in out


# ---------- T8: --model override is forwarded to get_llm ----------


def test_main_model_override_passed_to_get_llm(monkeypatch, capsys):
    """T8/H9: ``--model X`` causes ``get_llm(model=X)`` to be called."""
    received_kwargs = {}

    def spy_get_llm(*, model=None):
        received_kwargs["model"] = model
        # Return a stub LLM that completes the run in zero tool calls.
        return StubLLM([AIMessage(content="done", tool_calls=[])])

    monkeypatch.setattr("src.llm.get_llm", spy_get_llm)
    stub_body = StubBodyClient(response=None)

    rc = main(
        ["g", "--model", "anthropic:claude-haiku-4-5"],
        body_client=stub_body,
    )

    capsys.readouterr()  # drain captured output
    assert rc == 0
    assert received_kwargs == {"model": "anthropic:claude-haiku-4-5"}


# ---------- T9: --body-url override is forwarded to BodyClient ----------


def test_main_body_url_override_passed_to_BodyClient(monkeypatch, capsys):
    """T9/H10: ``--body-url URL`` causes ``BodyClient(base_url=URL)`` to be built."""
    captured = {}

    class SpyBodyClient:
        def __init__(self, base_url=None):
            captured["base_url"] = base_url
            self.calls = []

        def execute(self, tool, params=None):
            self.calls.append((tool, params))
            return None

    monkeypatch.setattr("src.body_client.BodyClient", SpyBodyClient)
    stub_llm = StubLLM([AIMessage(content="done", tool_calls=[])])

    rc = main(
        ["g", "--body-url", "http://localhost:9999"],
        llm=stub_llm,
    )

    capsys.readouterr()
    assert rc == 0
    assert captured == {"base_url": "http://localhost:9999"}


# ---------- T10: hard error during construction -> exit 2 ----------


def test_main_hard_error_exits_two(monkeypatch, capsys):
    """T10/H11: exception in get_llm bubbles to exit 2 + stderr ``error:``."""

    def boom(*, model=None):
        raise KeyError("missing api key")

    monkeypatch.setattr("src.llm.get_llm", boom)

    rc = main(["g", "--model", "x:y"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "error:" in captured.err
    # The repr of the KeyError leaks through, confirming it was caught from
    # the construction path (not from inside run_goal).
    assert "missing api key" in captured.err


# ---------- T11: importing src.__main__ adds no HTTP-client modules ----------


def test_main_no_network_imports_subprocess():
    """T11/H12: ``import src.__main__`` adds no requests/httpx/urllib3 surface.

    Mirrors the baseline-vs-probe pattern used in ``test_graph.py``'s
    ``test_graph_no_network_imports``.
    """
    deny_prefixes = ("requests", "httpx", "urllib3")

    baseline_code = textwrap.dedent(
        """
        import sys
        import argparse  # noqa: F401
        import pprint  # noqa: F401

        deny = ("requests", "httpx", "urllib3")
        leaked = sorted(m for m in sys.modules if m.startswith(deny))
        for m in leaked:
            print(m)
        """
    )
    baseline = subprocess.run(
        [sys.executable, "-c", baseline_code],
        cwd=str(BRAIN_DIR),
        capture_output=True,
        text=True,
    )
    assert baseline.returncode == 0, f"stderr={baseline.stderr}"
    baseline_set = set(baseline.stdout.split())

    probe_code = textwrap.dedent(
        """
        import sys
        import src.__main__  # noqa: F401

        deny = ("requests", "httpx", "urllib3")
        leaked = sorted(m for m in sys.modules if m.startswith(deny))
        for m in leaked:
            print(m)
        """
    )
    probe = subprocess.run(
        [sys.executable, "-c", probe_code],
        cwd=str(BRAIN_DIR),
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, f"stderr={probe.stderr}"
    probe_set = set(probe.stdout.split())

    extra = probe_set - baseline_set
    assert not extra, (
        f"src.__main__ pulled HTTP-client modules beyond the allowed "
        f"baseline: {sorted(extra)}"
    )
    assert deny_prefixes  # sanity


# ---------- T12: --max-iterations warns + still completes ----------


def test_main_max_iterations_flag_warns_but_succeeds(capsys):
    """T12: ``--max-iterations N`` emits a WARNING to stderr but does not abort."""
    stub_llm = StubLLM([AIMessage(content="done", tool_calls=[])])
    stub_body = StubBodyClient(response=None)

    rc = main(
        ["g", "--max-iterations", "5"],
        llm=stub_llm,
        body_client=stub_body,
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "WARNING" in captured.err
    assert "Phase 3" in captured.err


# ---------- T13: -v prints verbose state dump ----------


def test_main_verbose_dumps_state(capsys):
    """T13: ``-v`` appends the ``--- Verbose state dump ---`` block."""
    stub_llm = StubLLM([AIMessage(content="done", tool_calls=[])])
    stub_body = StubBodyClient(response=None)

    rc = main(["g", "-v"], llm=stub_llm, body_client=stub_body)

    out = capsys.readouterr().out
    assert rc == 0
    assert "Verbose state dump" in out
    # A few state keys should appear in the pformat output.
    assert "iteration_count" in out
    assert "step_results" in out


# ---------- T14: data field truncation rules ----------


def test_main_step_data_truncation(capsys):
    """T14: data renders <=3 kv pairs and truncates long values to 40 chars."""
    long_value = "x" * 200
    envelope = _navigate_success_envelope(
        data={
            "long": long_value,
            "k1": "v1",
            "k2": "v2",
            "k3": "v3",  # 4th pair must be dropped
        }
    )
    stub_llm = StubLLM(
        [
            _navigate_tool_call("t14"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=envelope)

    rc = main(["g"], llm=stub_llm, body_client=stub_body)

    out = capsys.readouterr().out
    assert rc == 0

    # Find the step row (the line containing "[0]").
    step_rows = [line for line in out.splitlines() if "[0]" in line]
    assert step_rows, f"no step row found in:\n{out}"
    row = step_rows[0]

    # Truncated long value: must NOT contain the full 200-char string.
    assert long_value not in row
    # Ellipsis indicates truncation occurred.
    assert "..." in row

    # Only 3 kv pairs (=) inside the data= region:
    # split on "data=" and count commas in the tail.
    assert "data=" in row
    data_tail = row.split("data=", 1)[1]
    pairs = data_tail.split(",")
    assert len(pairs) == 3, f"expected 3 kv pairs, got {pairs}"
    # k3 should be dropped (only first 3 dict keys retained).
    assert "k3=" not in row


# ========== Sprint 3k: --no-announce CLI flag (K6) ==========


def test_main_no_announce_flag_disables_announcement(monkeypatch, capsys):
    """K6: --no-announce flag -> announcement chat call is suppressed.

    Drive with BRAIN_ANNOUNCE=1 to prove the CLI flag overrides the env.
    """
    monkeypatch.setenv("BRAIN_ANNOUNCE", "1")  # default-on environment

    stub_llm = StubLLM(
        [
            _navigate_tool_call("k6"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=_navigate_success_envelope())

    rc = main(
        ["go there", "--no-announce"],
        llm=stub_llm,
        body_client=stub_body,
    )

    capsys.readouterr()  # drain
    assert rc == 0
    # Only the real navigate call -- no chat announcement.
    assert len(stub_body.calls) == 1
    assert stub_body.calls[0] == ("navigate", {"x": 1, "y": 64, "z": 2})


def test_main_no_announce_flag_parsed_in_help():
    """K6b: ``--help`` mentions --no-announce."""
    result = subprocess.run(
        [sys.executable, "-m", "src", "--help"],
        cwd=str(BRAIN_DIR),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--no-announce" in result.stdout


def test_main_announce_default_on_fires_chat(monkeypatch, capsys):
    """K6c: without --no-announce and env=1, the chat announcement fires."""
    monkeypatch.setenv("BRAIN_ANNOUNCE", "1")

    stub_llm = StubLLM(
        [
            _navigate_tool_call("k6c"),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    stub_body = StubBodyClient(response=_navigate_success_envelope())

    rc = main(["go there"], llm=stub_llm, body_client=stub_body)
    capsys.readouterr()
    assert rc == 0
    # Two calls: announcement chat then real navigate.
    assert len(stub_body.calls) == 2
    assert stub_body.calls[0] == ("chat", {"message": "Heading to (1, 64, 2)..."})
    assert stub_body.calls[1] == ("navigate", {"x": 1, "y": 64, "z": 2})


if __name__ == "__main__":  # pragma: no cover - manual invocation aid
    sys.exit(pytest.main([__file__, "-v"]))
