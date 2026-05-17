"""Tests for brain/src/sops/loader.py.

Covers:
- load_sop: happy path (with/without suffix), FileNotFoundError
- load_all_sops: returns exactly 5 entries, skips disabled, excludes index.yaml
- scale_sop: concrete stone_pickaxe × 5 assertions, non-mutation, ValueError guards,
  bool rejection, scale: false preservation
- manifest_fingerprint: format, determinism, content-sensitivity
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.sops.loader import (
    _sops_dir,
    load_all_sops,
    load_sop,
    manifest_fingerprint,
    scale_sop,
)

# ---------------------------------------------------------------------------
# load_sop
# ---------------------------------------------------------------------------


def test_load_sop_returns_dict_with_expected_keys():  # L1
    """load_sop('oak_planks') returns a dict with expected top-level keys and values."""
    sop = load_sop("oak_planks")
    assert isinstance(sop, dict)
    assert sop["name"] == "Oak Planks"
    assert sop["yields"] == 4


def test_load_sop_strips_yaml_suffix():  # L2
    """load_sop('oak_planks.yaml') strips the suffix and returns the same SOP."""
    sop_without_suffix = load_sop("oak_planks")
    sop_with_suffix = load_sop("oak_planks.yaml")
    assert sop_without_suffix == sop_with_suffix


def test_load_sop_missing_raises_file_not_found():  # L3
    """load_sop raises FileNotFoundError for a non-existent SOP name."""
    with pytest.raises(FileNotFoundError):
        load_sop("does_not_exist")


# ---------------------------------------------------------------------------
# load_all_sops
# ---------------------------------------------------------------------------


def test_load_all_sops_returns_exactly_five_entries():  # L4
    """load_all_sops() returns exactly the 5 seed SOPs by filename stem."""
    sops = load_all_sops()
    assert set(sops.keys()) == {
        "oak_planks",
        "stick",
        "crafting_table",
        "wooden_pickaxe",
        "stone_pickaxe",
    }


def test_load_all_sops_excludes_index_yaml():  # L6
    """load_all_sops() does not include 'index' as a key (index.yaml is not an SOP)."""
    sops = load_all_sops()
    assert "index" not in sops


def test_load_all_sops_skips_disabled(tmp_path, monkeypatch):  # L5
    """load_all_sops() skips SOP files with disabled: true."""
    # Write one normal SOP and one disabled SOP into tmp_path.
    (tmp_path / "active.yaml").write_text(
        "name: Active\n"
        "description: x\n"
        "tags: []\n"
        "yields: 1\n"
        "requires: []\n"
        "steps:\n"
        "  - {action: craft, item: x, count_per_unit: 1}\n",
        encoding="utf-8",
    )
    (tmp_path / "off.yaml").write_text(
        "name: Off\n"
        "description: x\n"
        "tags: []\n"
        "yields: 1\n"
        "disabled: true\n"
        "requires: []\n"
        "steps:\n"
        "  - {action: craft, item: x, count_per_unit: 1}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.sops.loader._sops_dir", lambda: tmp_path)

    sops = load_all_sops()
    assert "active" in sops
    assert "off" not in sops


def test_load_all_sops_does_not_skip_disabled_false(tmp_path, monkeypatch):
    """load_all_sops() does NOT skip SOPs with disabled: false (only disabled: true skips)."""
    (tmp_path / "enabled.yaml").write_text(
        "name: Enabled\n"
        "description: x\n"
        "tags: []\n"
        "yields: 1\n"
        "disabled: false\n"
        "requires: []\n"
        "steps:\n"
        "  - {action: craft, item: x, count_per_unit: 1}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.sops.loader._sops_dir", lambda: tmp_path)

    sops = load_all_sops()
    assert "enabled" in sops


# ---------------------------------------------------------------------------
# scale_sop — concrete stone_pickaxe × 5
# ---------------------------------------------------------------------------


def test_scale_sop_stone_pickaxe_by_5():  # L7
    """scale_sop(stone_pickaxe, 5) multiplies counts correctly; scale: false steps unchanged."""
    sop = load_sop("stone_pickaxe")
    scaled = scale_sop(sop, 5)

    # yields
    assert scaled["yields"] == 5

    # requires
    requires = scaled["requires"]
    oak_log_req = next(r for r in requires if r["item"] == "oak_log")
    cobblestone_req = next(r for r in requires if r["item"] == "cobblestone")
    assert oak_log_req["count_per_unit"] == 15   # 3 × 5
    assert cobblestone_req["count_per_unit"] == 15  # 3 × 5

    # steps
    steps = scaled["steps"]
    assert steps[0]["count_per_unit"] == 15   # mine oak_log: 3 × 5
    assert steps[1]["count_per_unit"] == 30   # craft oak_planks: 6 × 5
    assert steps[2]["count_per_unit"] == 10   # craft stick: 2 × 5
    assert steps[3]["count_per_unit"] == 1    # craft crafting_table: scale: false → unchanged
    assert steps[3]["scale"] is False          # C13: scale flag preserved in output
    assert steps[4]["count_per_unit"] == 1    # craft wooden_pickaxe: scale: false → unchanged
    assert steps[4]["scale"] is False          # C13: scale flag preserved in output
    assert steps[5]["count_per_unit"] == 15   # mine stone: 3 × 5
    assert steps[6]["count_per_unit"] == 5    # craft stone_pickaxe: 1 × 5


# ---------------------------------------------------------------------------
# scale_sop — mutation guard
# ---------------------------------------------------------------------------


def test_scale_sop_does_not_mutate_input():  # L8
    """scale_sop returns a new dict and does not mutate the original sop."""
    sop = load_sop("stone_pickaxe")
    snapshot = copy.deepcopy(sop)
    scale_sop(sop, 3)
    assert sop == snapshot, "scale_sop must not mutate its input"


def test_scale_sop_n1_is_identity_on_counts():  # L9
    """scale_sop(sop, 1) returns counts equal to the input (but a fresh object)."""
    sop = load_sop("oak_planks")
    scaled = scale_sop(sop, 1)
    assert scaled["yields"] == sop["yields"]
    assert scaled["requires"][0]["count_per_unit"] == sop["requires"][0]["count_per_unit"]
    assert scaled["steps"][0]["count_per_unit"] == sop["steps"][0]["count_per_unit"]
    # Output is a fresh object despite identical values.
    assert scaled is not sop


# ---------------------------------------------------------------------------
# scale_sop — ValueError guards
# ---------------------------------------------------------------------------


def test_scale_sop_zero_raises_value_error():  # L10
    """scale_sop(sop, 0) raises ValueError."""
    sop = load_sop("oak_planks")
    with pytest.raises(ValueError):
        scale_sop(sop, 0)


def test_scale_sop_negative_raises_value_error():  # L11
    """scale_sop(sop, -2) raises ValueError."""
    sop = load_sop("oak_planks")
    with pytest.raises(ValueError):
        scale_sop(sop, -2)


def test_scale_sop_bool_true_raises_value_error():  # L12
    """scale_sop(sop, True) raises ValueError — bool rejection guards Python's True == 1 trap."""
    sop = load_sop("oak_planks")
    with pytest.raises(ValueError):
        scale_sop(sop, True)


def test_scale_sop_bool_false_raises_value_error():
    """scale_sop(sop, False) raises ValueError (False == 0 would be wrong anyway)."""
    sop = load_sop("oak_planks")
    with pytest.raises(ValueError):
        scale_sop(sop, False)


# ---------------------------------------------------------------------------
# manifest_fingerprint
# ---------------------------------------------------------------------------


def test_manifest_fingerprint_format():  # L13
    """manifest_fingerprint returns 'sha256:<64 hex chars>' for the real index.yaml."""
    index_path = _sops_dir() / "index.yaml"
    fp = manifest_fingerprint(index_path)
    assert fp.startswith("sha256:"), f"Expected 'sha256:' prefix, got {fp!r}"
    hex_part = fp[len("sha256:"):]
    assert len(hex_part) == 64, f"Expected 64 hex chars, got {len(hex_part)}"
    assert all(c in "0123456789abcdef" for c in hex_part), (
        f"Expected lowercase hex digits only, got {hex_part!r}"
    )


def test_manifest_fingerprint_is_deterministic():  # L14
    """manifest_fingerprint returns the same value on repeated calls for the same file."""
    index_path = _sops_dir() / "index.yaml"
    fp1 = manifest_fingerprint(index_path)
    fp2 = manifest_fingerprint(index_path)
    assert fp1 == fp2


def test_manifest_fingerprint_differs_for_different_content(tmp_path):  # L15
    """manifest_fingerprint produces different values for files with different content."""
    file_a = tmp_path / "a.yaml"
    file_b = tmp_path / "b.yaml"
    file_a.write_bytes(b"content: alpha\n")
    file_b.write_bytes(b"content: beta\n")
    assert manifest_fingerprint(file_a) != manifest_fingerprint(file_b)


def test_manifest_fingerprint_missing_file_raises():
    """manifest_fingerprint raises FileNotFoundError for a non-existent path."""
    with pytest.raises(FileNotFoundError):
        manifest_fingerprint(Path("/nonexistent/path/index.yaml"))
