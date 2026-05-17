"""Unit tests for brain/src/sops/cache.py (SOPRouteCache + normalize_goal).

All tests are isolated from the real brain/.cache/ directory.
Tests that need controlled fingerprints monkeypatch _index_path in
src.sops.cache to point at a tmp file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import src.sops.cache as cache_mod
from src.sops.cache import (
    NONE_SENTINEL,
    SCHEMA_VERSION,
    SOPRouteCache,
    normalize_goal,
)


# ---------------------------------------------------------------------------
# C-T1: normalize_goal
# ---------------------------------------------------------------------------


def test_normalize_goal_lowercases_and_collapses_whitespace():
    """C-T1: normalize_goal lowercases, collapses internal whitespace, strips ends."""
    assert normalize_goal("  Make 5  STONE pickaxes ") == "make 5 stone pickaxes"
    assert normalize_goal("\tcraft\noak\tplanks\t") == "craft oak planks"
    assert normalize_goal("HELLO   WORLD") == "hello world"
    assert normalize_goal("  ") == ""
    assert normalize_goal("already normalized") == "already normalized"


# ---------------------------------------------------------------------------
# C-T2: load() on nonexistent file
# ---------------------------------------------------------------------------


def test_load_nonexistent_file_returns_empty_shape(tmp_path):
    """C-T2: load() on nonexistent file returns correct empty schema shape."""
    cache = SOPRouteCache(cache_path=tmp_path / "sop_routes.json")
    # Verify the cache file doesn't exist yet
    assert not (tmp_path / "sop_routes.json").exists()

    data = cache.load()

    assert data["schema_version"] == SCHEMA_VERSION
    assert "manifest_fingerprint" in data
    assert data["entries"] == {}

    # C1: verify required methods exist
    for method in ("load", "get", "set", "clear"):
        assert hasattr(cache, method), f"Missing method: {method}"


# ---------------------------------------------------------------------------
# C-T3: set then get (with whitespace/case variant)
# ---------------------------------------------------------------------------


def test_set_then_get_normalizes_key(tmp_path):
    """C-T3: set(...) then get(...) with whitespace/case variant returns the entry."""
    cache = SOPRouteCache(cache_path=tmp_path / "sop_routes.json")
    cache.set("Get me a stone pickaxe", "stone_pickaxe", 1)

    # Exact match
    result = cache.get("Get me a stone pickaxe")
    assert result == {"sop_name": "stone_pickaxe", "count": 1}

    # Case + whitespace variant normalizes to the same key
    result2 = cache.get("  GET ME A STONE PICKAXE  ")
    assert result2 == {"sop_name": "stone_pickaxe", "count": 1}


# ---------------------------------------------------------------------------
# C-T4: entries persist across instances (file roundtrip)
# ---------------------------------------------------------------------------


def test_entries_persist_across_instances(tmp_path):
    """C-T4: a fresh SOPRouteCache instance reads entries set by prior instance."""
    path = tmp_path / "sop_routes.json"

    cache1 = SOPRouteCache(cache_path=path)
    cache1.set("craft oak planks", "oak_planks", 3)

    # Fresh instance, same path
    cache2 = SOPRouteCache(cache_path=path)
    result = cache2.get("craft oak planks")
    assert result == {"sop_name": "oak_planks", "count": 3}


# ---------------------------------------------------------------------------
# C-T5: fingerprint mismatch drops entries
# ---------------------------------------------------------------------------


def test_fingerprint_mismatch_drops_entries(tmp_path):
    """C-T5: a cache file with mismatched fingerprint has its entries dropped."""
    path = tmp_path / "sop_routes.json"

    # Write a cache file by hand with a stale fingerprint and one entry
    stale_data = {
        "schema_version": SCHEMA_VERSION,
        "manifest_fingerprint": "sha256:deadbeef",
        "entries": {
            "craft oak planks": {"sop_name": "oak_planks", "count": 1}
        },
    }
    path.write_text(json.dumps(stale_data), encoding="utf-8")

    cache = SOPRouteCache(cache_path=path)
    data = cache.load()
    assert data["entries"] == {}
    # Fingerprint is updated to current
    assert data["manifest_fingerprint"] != "sha256:deadbeef"


# ---------------------------------------------------------------------------
# C-T6: fingerprint match preserves entries
# ---------------------------------------------------------------------------


def test_fingerprint_match_preserves_entries(tmp_path):
    """C-T6: a cache file with matching fingerprint keeps its entries."""
    path = tmp_path / "sop_routes.json"

    # Determine current fingerprint using the real index.yaml
    from src.sops.loader import manifest_fingerprint
    index_path = cache_mod._index_path()
    if not index_path.exists():
        pytest.skip("index.yaml not found; Sprint 4b not yet run")

    current_fp = manifest_fingerprint(index_path)

    # Write a cache file with the current fingerprint
    good_data = {
        "schema_version": SCHEMA_VERSION,
        "manifest_fingerprint": current_fp,
        "entries": {
            "craft oak planks": {"sop_name": "oak_planks", "count": 2}
        },
    }
    path.write_text(json.dumps(good_data), encoding="utf-8")

    cache = SOPRouteCache(cache_path=path)
    data = cache.load()
    assert data["entries"] == {
        "craft oak planks": {"sop_name": "oak_planks", "count": 2}
    }


# ---------------------------------------------------------------------------
# C-T7: clear() empties entries
# ---------------------------------------------------------------------------


def test_clear_wipes_entries_and_get_returns_none(tmp_path):
    """C-T7: clear() writes empty-entries file; subsequent get(...) returns None."""
    path = tmp_path / "sop_routes.json"
    cache = SOPRouteCache(cache_path=path)

    # Populate first
    cache.set("some goal", "oak_planks", 1)
    assert cache.get("some goal") is not None

    cache.clear()
    assert cache.get("some goal") is None

    # File exists and has empty entries
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["entries"] == {}
    assert "manifest_fingerprint" in on_disk


# ---------------------------------------------------------------------------
# C-T8: get unknown goal returns None
# ---------------------------------------------------------------------------


def test_get_unknown_goal_returns_none(tmp_path):
    """C-T8: get("unknown goal") returns None."""
    cache = SOPRouteCache(cache_path=tmp_path / "sop_routes.json")
    assert cache.get("unknown goal") is None


# ---------------------------------------------------------------------------
# C-T9: <none> sentinel stored with null count
# ---------------------------------------------------------------------------


def test_none_sentinel_stored_with_null_count(tmp_path):
    """C-T9: set('say hello', '<none>', None) stores correctly."""
    path = tmp_path / "sop_routes.json"
    cache = SOPRouteCache(cache_path=path)

    cache.set("say hello", NONE_SENTINEL, None)

    # In-memory read
    result = cache.get("say hello")
    assert result == {"sop_name": NONE_SENTINEL, "count": None}

    # On-disk JSON shows null
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    key = normalize_goal("say hello")
    assert on_disk["entries"][key]["count"] is None


# ---------------------------------------------------------------------------
# C-T10: atomic write — tmp file cleaned up on failure
# ---------------------------------------------------------------------------


def test_atomic_write_cleans_up_tmp_on_failure(tmp_path):
    """C-T10: if os.replace raises, the .tmp file is cleaned up."""
    path = tmp_path / "sop_routes.json"
    cache = SOPRouteCache(cache_path=path)

    original_replace = os.replace

    replace_call_count = [0]

    def failing_replace(src, dst):
        replace_call_count[0] += 1
        if replace_call_count[0] == 1:
            # Remove tmp manually to simulate partial failure scenario
            try:
                os.unlink(src)
            except OSError:
                pass
            raise OSError("simulated replace failure")
        return original_replace(src, dst)

    with patch("src.sops.cache.os.replace", side_effect=failing_replace):
        with pytest.raises(OSError, match="simulated replace failure"):
            cache.set("goal", "oak_planks", 1)

    # Cache path should not have been created
    assert not path.exists()

    # No stray .tmp files remain (best-effort: some OSes may differ)
    tmp_files = list(tmp_path.glob(".sop_routes_*.tmp"))
    assert len(tmp_files) == 0, f"Found stray tmp files: {tmp_files}"


# ---------------------------------------------------------------------------
# C-T11: module CLI _cli(["clear"]) clears custom-path cache
# ---------------------------------------------------------------------------


def test_cli_clear_wipes_cache(tmp_path, monkeypatch):
    """C-T11: _cli(['clear']) invokes SOPRouteCache().clear() on the default path."""
    path = tmp_path / "sop_routes.json"

    # Monkeypatch _default_cache_path so the CLI cache hits our tmp path
    monkeypatch.setattr(cache_mod, "_default_cache_path", lambda: path)

    # Pre-populate the cache file manually
    from src.sops.loader import manifest_fingerprint
    index_path = cache_mod._index_path()
    current_fp = manifest_fingerprint(index_path) if index_path.exists() else ""
    data = {
        "schema_version": SCHEMA_VERSION,
        "manifest_fingerprint": current_fp,
        "entries": {"some key": {"sop_name": "oak_planks", "count": 1}},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")

    # Run CLI
    from src.sops.cache import _cli
    rc = _cli(["clear"])
    assert rc == 0

    # Verify cleared
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["entries"] == {}


def test_cli_bad_args_returns_2(capsys):
    """C-T11 extra: bad CLI args return exit code 2."""
    from src.sops.cache import _cli
    rc = _cli([])
    assert rc == 2
    rc2 = _cli(["bad_command"])
    assert rc2 == 2
    rc3 = _cli(["clear", "extra"])
    assert rc3 == 2


# ---------------------------------------------------------------------------
# C11: brain/.gitignore contains .cache/
# ---------------------------------------------------------------------------


def test_brain_gitignore_ignores_cache_dir():
    """C11: brain/.gitignore exists and contains '.cache/' entry."""
    gitignore_path = Path(__file__).resolve().parent.parent / ".gitignore"
    assert gitignore_path.exists(), f"brain/.gitignore not found at {gitignore_path}"
    content = gitignore_path.read_text(encoding="utf-8")
    assert ".cache/" in content, f"'.cache/' not found in brain/.gitignore:\n{content}"
