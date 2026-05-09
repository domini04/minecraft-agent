"""CLI entry point: ``python -m src "<goal>"`` (run from ``brain/``).

Sprint 3h frozen design (see `.pge/.../plan.md`):

* Single ``main(argv=None, *, llm=None, body_client=None) -> int`` entry.
* Lazy imports for ``BodyClient`` and ``get_llm`` so a bare
  ``import src.__main__`` does NOT pull ``requests`` or
  ``langchain_google_genai``. Top-level imports are stdlib only.
* ``--max-iterations`` is parsed but is currently a no-op; honoring it
  would require threading the value into ``src.state.MAX_ITERATIONS``,
  which is out of scope for Sprint 3h. A stderr WARNING is emitted when
  the flag is supplied so the operator is not silently misled.
* Stub injection: when ``llm=`` or ``body_client=`` is passed to
  ``main()`` directly, the corresponding ``--model`` / ``--body-url``
  resolution is skipped entirely (test seam).
* Exit codes:
    - ``0``: ``state["result"]`` is truthy AND every step in
      ``step_results`` reported ``success=True``.
    - ``1``: any other terminal state (no result, or one+ failed step).
    - ``2``: hard error — uncaught exception during dependency
      construction or graph invocation, OR argparse rejected argv.
"""

from __future__ import annotations

import argparse
import pprint
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from src.body_client import BodyClient

# Step rendering tunables (frozen per plan §1.5).
_TOOL_PAD = 16
_MAX_KV_PAIRS = 3
_MAX_VALUE_LEN = 40


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser used by ``main`` and ``--help``.

    The parser is exposed only as a private helper so tests can exercise
    it without invoking ``main()``.
    """
    parser = argparse.ArgumentParser(
        prog="python -m src",
        description=(
            "Run the Minecraft brain on a single natural-language goal. "
            "Drives the LangGraph planner -> executor loop once and "
            "prints a summary of the final state."
        ),
    )
    parser.add_argument(
        "goal",
        help="Natural-language objective for the agent.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=('Override BRAIN_LLM_MODEL (e.g. "anthropic:claude-haiku-4-5").'),
    )
    parser.add_argument(
        "--body-url",
        dest="body_url",
        default=None,
        help=(
            "Override BodyClient base URL (default: env BOT_URL or "
            "http://127.0.0.1:3000)."
        ),
    )
    parser.add_argument(
        "--max-iterations",
        dest="max_iterations",
        type=int,
        default=None,
        help=(
            "[Phase 3 NO-OP] Reserved for Phase 5+; supplying this flag "
            "currently emits a WARNING to stderr and is otherwise ignored."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print the full state dict at the end (in addition to summary).",
    )
    return parser


def _truncate(value: Any) -> str:
    """Return ``str(value)`` truncated to ``_MAX_VALUE_LEN`` chars with ellipsis."""
    text = str(value)
    if len(text) > _MAX_VALUE_LEN:
        return text[: _MAX_VALUE_LEN - 3] + "..."
    return text


def _format_data(data: Any) -> str:
    """Render a step_result ``data`` field per the frozen format rules.

    * ``None`` or empty dict → ``data=(none)``.
    * Non-dict (defensive) → ``data=(none)``.
    * Otherwise: up to ``_MAX_KV_PAIRS`` ``key=value`` pairs joined by
      ``,`` (no spaces). Each value truncated via ``_truncate``.
    """
    if not isinstance(data, dict) or not data:
        return "data=(none)"
    items = list(data.items())[:_MAX_KV_PAIRS]
    pairs = ",".join(f"{k}={_truncate(v)}" for k, v in items)
    return f"data={pairs}"


def _format_error(error: Any) -> str:
    """Render a step_result ``error`` field per the frozen format rules.

    Falls back to ``error=(unknown)`` when the structure is missing or
    malformed.
    """
    if not isinstance(error, dict):
        return "error=(unknown)"
    code = error.get("code")
    message = error.get("message")
    if code is None and message is None:
        return "error=(unknown)"
    code_str = "(unknown)" if code is None else str(code)
    msg_str = "" if message is None else _truncate(message)
    return f"error={code_str}: {msg_str}"


def _format_summary(state: dict) -> str:
    """Build the default (non-verbose) text summary block."""
    goal = state.get("goal", "")
    iteration_count = state.get("iteration_count", 0)
    step_results = state.get("step_results") or []
    result = state.get("result") or "(no result -- cap exhausted or failure)"

    lines = [
        f"Goal: {goal}",
        f"Iterations: {iteration_count} (cap=10)",
        f"Steps: {len(step_results)}",
    ]
    for idx, sr in enumerate(step_results):
        tool_name = str(sr.get("tool", "?")).ljust(_TOOL_PAD)
        success = bool(sr.get("success", False))
        if success:
            tail = _format_data(sr.get("data"))
            lines.append(f"  [{idx}] {tool_name} success=True   {tail}")
        else:
            tail = _format_error(sr.get("error"))
            lines.append(f"  [{idx}] {tool_name} success=False  {tail}")
    lines.append(f"Result: {result}")
    return "\n".join(lines)


def _format_verbose(state: dict) -> str:
    """Build the verbose state-dump block appended after the summary."""
    return "--- Verbose state dump ---\n" + pprint.pformat(state, width=100)


def _classify_exit(state: dict) -> int:
    """Map a successful (non-exceptional) terminal state to 0 or 1.

    ``0`` iff ``state["result"]`` is truthy AND every step's
    ``success`` flag is True. Anything else → ``1``.
    """
    step_results = state.get("step_results") or []
    has_failed = any(not sr.get("success", False) for sr in step_results)
    has_result = bool(state.get("result"))
    if has_result and not has_failed:
        return 0
    return 1


def main(
    argv: list[str] | None = None,
    *,
    llm: "BaseChatModel | None" = None,
    body_client: "BodyClient | None" = None,
) -> int:
    """Entry point — parse argv, run the goal, print summary, return exit code.

    Args:
        argv: Argument list (without the program name). When ``None``
            (the default) argparse falls back to ``sys.argv[1:]``.
        llm: Optional pre-built chat model. When supplied, the
            ``--model`` flag's resolution path is bypassed entirely.
        body_client: Optional ``BodyClient`` (or stub). When supplied,
            the ``--body-url`` flag's resolution path is bypassed
            entirely.

    Returns:
        Process exit code: ``0`` on full success, ``1`` on a
        terminated-but-unsatisfied run, ``2`` on a hard error
        (exception during construction or graph invocation).

    The function never re-raises; all exceptions surface as exit ``2``
    with a single ``error: ...`` line on stderr.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- --max-iterations is parsed but currently a no-op (frozen design) ---
    if args.max_iterations is not None:
        print(
            "WARNING: --max-iterations is a no-op in Phase 3 "
            "(MAX_ITERATIONS=10 is fixed in src.state); "
            "the supplied value is ignored.",
            file=sys.stderr,
        )

    # --- Resolve dependencies (lazy imports, stub injection wins) ----------
    try:
        if llm is None and args.model:
            from src.llm import get_llm  # lazy: keeps import surface clean

            llm = get_llm(model=args.model)
        if body_client is None and args.body_url:
            from src.body_client import BodyClient as _BodyClient  # lazy

            body_client = _BodyClient(base_url=args.body_url)
    except Exception as exc:  # noqa: BLE001 - we want the broadest catch here
        print(f"error: failed to initialize: {exc!r}", file=sys.stderr)
        return 2

    # --- Run the graph ------------------------------------------------------
    try:
        from src.graph import run_goal  # lazy: pulls langgraph only when used

        final = run_goal(args.goal, llm=llm, body_client=body_client)
    except Exception as exc:  # noqa: BLE001
        print(f"error: run failed: {exc!r}", file=sys.stderr)
        return 2

    # --- Render output ------------------------------------------------------
    print(_format_summary(final))
    if args.verbose:
        print(_format_verbose(final))

    return _classify_exit(final)


if __name__ == "__main__":
    sys.exit(main())
