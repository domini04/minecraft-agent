"""Tests for src.tools.loader — args models, drift guard, and StructuredTool registry.

Pure structural/typing tests. No LLM calls, no network, no body server.
"""

import json
import sys

import pytest
from pydantic import ValidationError

from src.tools.loader import (
    SCHEMAS_DIR,
    TOOL_ARG_MODELS,
    ChatArgs,
    CraftArgs,
    CraftingTablePos,
    GetBotStatusArgs,
    MineArgs,
    NavigateArgs,
    PlaceBlockArgs,
    get_tools,
)

# ---------- Per-tool args-model shape ----------


def test_args_models_shape_chat():
    """ChatArgs accepts in-bounds messages and rejects over-length."""
    assert ChatArgs(message="hi").message == "hi"
    # maxLength=256 — 257 must fail.
    with pytest.raises(ValidationError):
        ChatArgs(message="x" * 257)
    # minLength=1 — empty must fail.
    with pytest.raises(ValidationError):
        ChatArgs(message="")


def test_args_models_shape_get_bot_status():
    """GetBotStatusArgs accepts no kwargs and rejects any extras."""
    assert GetBotStatusArgs().model_dump() == {}
    with pytest.raises(ValidationError):
        GetBotStatusArgs(unexpected=1)


def test_args_models_shape_navigate():
    """NavigateArgs accepts float coords (incl. zero); missing axis rejected."""
    n = NavigateArgs(x=1.5, y=2, z=3.0)
    assert n.x == 1.5
    assert n.y == 2.0
    assert n.z == 3.0
    # zero is fine
    NavigateArgs(x=0, y=0, z=0)
    # missing axis
    with pytest.raises(ValidationError):
        NavigateArgs(x=0, y=0)  # type: ignore[call-arg]


def test_args_models_shape_mine():
    """MineArgs covers happy path, count/target validation, and max_distance bounds."""
    m = MineArgs(target="oak_log", count=1)
    assert m.max_distance is None
    m2 = MineArgs(target="oak_log", count=1, max_distance=64)
    assert m2.max_distance == 64
    # count=0 rejected (minimum=1)
    with pytest.raises(ValidationError):
        MineArgs(target="oak_log", count=0)
    # whitespace-only target rejected (pattern="\\S")
    with pytest.raises(ValidationError):
        MineArgs(target=" ", count=1)
    # max_distance > 128 rejected
    with pytest.raises(ValidationError):
        MineArgs(target="oak_log", count=1, max_distance=129)
    # extra field rejected
    with pytest.raises(ValidationError):
        MineArgs(target="oak_log", count=1, foo="bar")  # type: ignore[call-arg]


def test_args_models_shape_craft():
    """CraftArgs: optional crafting_table_pos (default None) plus int-coord variant."""
    c = CraftArgs(item="wooden_pickaxe", count=1)
    assert c.crafting_table_pos is None
    c2 = CraftArgs(
        item="wooden_pickaxe",
        count=1,
        crafting_table_pos=CraftingTablePos(x=1, y=2, z=3),
    )
    assert c2.crafting_table_pos is not None
    assert c2.crafting_table_pos.x == 1
    assert c2.crafting_table_pos.y == 2
    assert c2.crafting_table_pos.z == 3
    # CraftingTablePos rejects extras
    with pytest.raises(ValidationError):
        CraftingTablePos(x=1, y=2, z=3, foo=1)  # type: ignore[call-arg]


def test_args_models_shape_place_block():
    """PlaceBlockArgs accepts float coords; rejects empty block."""
    p = PlaceBlockArgs(block="dirt", x=0, y=64, z=0)
    assert p.y == 64.0
    with pytest.raises(ValidationError):
        PlaceBlockArgs(block="", x=0, y=0, z=0)


# ---------- get_tools() / bind_tools compatibility ----------


def test_get_tools_shape():
    """get_tools() returns six StructuredTools in index.json order."""
    from langchain_core.tools import StructuredTool

    ts = get_tools()
    assert len(ts) == 6
    assert [t.name for t in ts] == [
        "chat",
        "get_bot_status",
        "navigate",
        "mine",
        "craft",
        "place_block",
    ]
    for t in ts:
        assert isinstance(t, StructuredTool)
        assert t.description and isinstance(t.description, str)
        assert t.args_schema is TOOL_ARG_MODELS[t.name]


def test_get_tools_returns_fresh_list():
    """Mutating the returned list must not affect subsequent get_tools() calls."""
    a = get_tools()
    a.pop()
    b = get_tools()
    assert len(b) == 6


def test_bind_tools_compatible_schema():
    """Emitted schema is bind_tools-compatible: forbid-extras + matching required."""
    with open(SCHEMAS_DIR / "index.json") as f:
        idx = json.load(f)
    for t in get_tools():
        emitted = t.args_schema.model_json_schema()
        assert emitted.get("additionalProperties") is False, t.name
        with open(SCHEMAS_DIR / idx[t.name]) as f:
            js = json.load(f)
        assert set(emitted.get("required", []) or []) == set(
            js.get("required", []) or []
        ), (t.name, emitted.get("required"), js.get("required"))


# ---------- Drift guard ----------


def test_drift_guard_fires():
    """_check_drift raises ImportError when fed a synthetic mutated schema."""
    from src.tools import loader

    # Synthetic mutated input — does NOT touch real files on disk.
    bad_schemas = {
        "chat": {
            "required": ["message", "EXTRA_REQUIRED"],
            "properties": {"message": {"type": "string"}},
            "additionalProperties": False,
        }
    }
    bad_models = {"chat": loader.ChatArgs}
    with pytest.raises(ImportError):
        loader._check_drift(bad_schemas, bad_models)


def test_drift_guard_passes_for_real_schemas():
    """The real on-disk schemas + Pydantic models must NOT drift (sanity check).

    Already enforced at module load, but this test makes the contract explicit.
    """
    from src.tools import loader

    # Re-loading and re-checking should be a no-op (idempotent, no raise).
    loader._check_drift(loader._SCHEMAS, loader.TOOL_ARG_MODELS)


# ---------- Imports-clean ----------


def test_imports_clean():
    """Importing the loader must not pull langgraph/requests into sys.modules.

    LangChain core is unavoidable (it's where StructuredTool comes from), but
    network deps must stay out — StructuredTool construction is lazy in
    get_tools(), so loader-module import alone keeps requests out.
    """
    # Module is already imported by this test file; what we assert is the
    # post-import-state invariant: neither `langgraph` nor `requests` should
    # have been pulled in by `import src.tools.loader` or `import src.models`.
    # This passes only when the test module is imported in a fresh interpreter
    # where nothing else has pulled requests first. Because pytest may have
    # transitive imports, we instead spawn a subprocess for a clean check.
    import subprocess

    code = (
        "import sys; "
        "pre=set(sys.modules); "
        "import src.tools.loader; "
        "import src.models; "
        "new=set(sys.modules)-pre; "
        "bad=[m for m in new if m.startswith(('langgraph','requests','dotenv'))]; "
        "assert not bad, bad; "
        "print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(SCHEMAS_DIR.parent.parent / "brain"),
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "OK" in result.stdout
