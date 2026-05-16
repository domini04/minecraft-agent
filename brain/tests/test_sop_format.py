"""Format-conformance tests for the SOP YAML files in brain/src/sops/.

Responsibilities:
1. Discovery  — enumerate *.yaml files under brain/src/sops/ (excluding index.yaml).
2. Count check — assert exactly 5 SOP files exist.
3. YAML parse  — each file parses without error.
4. Schema conformance — each parsed dict passes the hand-rolled validator.
5. stone_pickaxe.yaml-specific assertions:
   - Final step is {action: craft, item: stone_pickaxe, count_per_unit: 1} with no scale: false.
   - Intermediate crafting_table and wooden_pickaxe steps carry scale: false.
6. No index.yaml guard — index.yaml must NOT exist yet (Sprint 4b deliverable).

This module is intentionally free of the Sprint-4b loader/Pydantic model so
it cannot accidentally couple to code that does not exist yet.
"""

from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------

_SOPS_DIR = Path(__file__).resolve().parent.parent / "src" / "sops"

# Collect SOP files: all *.yaml except index.yaml (Sprint 4b deliverable).
_SOP_FILES = sorted(
    p for p in _SOPS_DIR.glob("*.yaml") if p.name != "index.yaml"
)

_EXPECTED_SOP_COUNT = 5

_VALID_ACTIONS = {"mine", "craft"}

# ---------------------------------------------------------------------------
# Hand-rolled validator
# ---------------------------------------------------------------------------


def _validate_sop(name: str, sop: object) -> list[str]:
    """Return a list of error messages; empty list means the SOP is valid.

    Args:
        name: Human-readable identifier for the file (used in error messages).
        sop:  Parsed YAML object (expected to be a dict).
    """
    errors: list[str] = []

    if not isinstance(sop, dict):
        errors.append(f"{name}: top-level value must be a dict, got {type(sop).__name__}")
        return errors  # Cannot proceed with further checks.

    # --- Required top-level keys ---
    required_keys = ("name", "description", "tags", "yields", "requires", "steps")
    for key in required_keys:
        if key not in sop:
            errors.append(f"{name}: missing required key {key!r}")

    # --- `name` ---
    if "name" in sop:
        if not isinstance(sop["name"], str) or not sop["name"].strip():
            errors.append(f"{name}: 'name' must be a non-empty string")

    # --- `description` ---
    if "description" in sop:
        if not isinstance(sop["description"], str) or not sop["description"].strip():
            errors.append(f"{name}: 'description' must be a non-empty string")

    # --- `tags` ---
    if "tags" in sop:
        tags = sop["tags"]
        if not isinstance(tags, list):
            errors.append(f"{name}: 'tags' must be a list, got {type(tags).__name__}")
        else:
            for i, tag in enumerate(tags):
                if not isinstance(tag, str):
                    errors.append(f"{name}: 'tags[{i}]' must be a string, got {type(tag).__name__}")

    # --- `yields` ---
    if "yields" in sop:
        y = sop["yields"]
        if not isinstance(y, int) or isinstance(y, bool) or y <= 0:
            errors.append(f"{name}: 'yields' must be a positive integer (> 0), got {y!r}")

    # --- `requires` ---
    if "requires" in sop:
        reqs = sop["requires"]
        if not isinstance(reqs, list):
            errors.append(f"{name}: 'requires' must be a list, got {type(reqs).__name__}")
        else:
            for i, req in enumerate(reqs):
                if not isinstance(req, dict):
                    errors.append(
                        f"{name}: 'requires[{i}]' must be a dict, got {type(req).__name__}"
                    )
                    continue
                # Required keys in each requires entry.
                if "item" not in req:
                    errors.append(f"{name}: 'requires[{i}]' missing key 'item'")
                elif not isinstance(req["item"], str) or not req["item"].strip():
                    errors.append(f"{name}: 'requires[{i}].item' must be a non-empty string")
                if "count_per_unit" not in req:
                    errors.append(f"{name}: 'requires[{i}]' missing key 'count_per_unit'")
                else:
                    cpu = req["count_per_unit"]
                    if not isinstance(cpu, int) or isinstance(cpu, bool) or cpu < 1:
                        errors.append(
                            f"{name}: 'requires[{i}].count_per_unit' must be an int >= 1, got {cpu!r}"
                        )

    # --- `steps` ---
    if "steps" in sop:
        steps = sop["steps"]
        if not isinstance(steps, list) or len(steps) == 0:
            errors.append(f"{name}: 'steps' must be a non-empty list")
        else:
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    errors.append(
                        f"{name}: 'steps[{i}]' must be a dict, got {type(step).__name__}"
                    )
                    continue

                # --- action ---
                if "action" not in step:
                    errors.append(f"{name}: 'steps[{i}]' missing required key 'action'")
                    continue
                action = step["action"]
                if action not in _VALID_ACTIONS:
                    errors.append(
                        f"{name}: 'steps[{i}].action' must be one of {sorted(_VALID_ACTIONS)}, got {action!r}"
                    )
                    continue

                # --- mutual exclusivity: target (mine) vs item (craft) ---
                has_target = "target" in step
                has_item = "item" in step

                if has_target and has_item:
                    errors.append(
                        f"{name}: 'steps[{i}]' has both 'target' and 'item'; exactly one is required"
                    )
                elif action == "mine" and not has_target:
                    errors.append(
                        f"{name}: 'steps[{i}]' action='mine' requires 'target' field"
                    )
                elif action == "craft" and not has_item:
                    errors.append(
                        f"{name}: 'steps[{i}]' action='craft' requires 'item' field"
                    )
                elif action == "mine" and has_target:
                    if not isinstance(step["target"], str) or not step["target"].strip():
                        errors.append(
                            f"{name}: 'steps[{i}].target' must be a non-empty string"
                        )
                elif action == "craft" and has_item:
                    if not isinstance(step["item"], str) or not step["item"].strip():
                        errors.append(
                            f"{name}: 'steps[{i}].item' must be a non-empty string"
                        )

                # --- count_per_unit ---
                if "count_per_unit" not in step:
                    errors.append(
                        f"{name}: 'steps[{i}]' missing required key 'count_per_unit'"
                    )
                else:
                    cpu = step["count_per_unit"]
                    if not isinstance(cpu, int) or isinstance(cpu, bool) or cpu < 1:
                        errors.append(
                            f"{name}: 'steps[{i}].count_per_unit' must be an int >= 1, got {cpu!r}"
                        )

                # --- scale (optional, must be bool if present) ---
                if "scale" in step:
                    sc = step["scale"]
                    if not isinstance(sc, bool):
                        errors.append(
                            f"{name}: 'steps[{i}].scale' must be a bool if present, got {sc!r}"
                        )

    # --- `disabled` (optional) ---
    if "disabled" in sop:
        if not isinstance(sop["disabled"], bool):
            errors.append(
                f"{name}: 'disabled' must be a bool if present, got {sop['disabled']!r}"
            )

    return errors


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sops_directory_exists():
    """brain/src/sops/ directory is present."""
    assert _SOPS_DIR.is_dir(), f"Expected sops directory at {_SOPS_DIR}"


def test_sop_count():
    """Exactly 5 SOP YAML files exist (excluding index.yaml)."""
    assert len(_SOP_FILES) == _EXPECTED_SOP_COUNT, (
        f"Expected {_EXPECTED_SOP_COUNT} SOP files, found {len(_SOP_FILES)}: "
        f"{[p.name for p in _SOP_FILES]}"
    )


def test_no_index_yaml_yet():
    """index.yaml does not exist yet — it is Sprint 4b's deliverable."""
    index_path = _SOPS_DIR / "index.yaml"
    assert not index_path.exists(), (
        f"index.yaml must not exist until Sprint 4b; found at {index_path}"
    )


@pytest.mark.parametrize("sop_path", _SOP_FILES, ids=lambda p: p.name)
def test_each_sop_parses_as_yaml(sop_path: Path):
    """Each SOP file parses with yaml.safe_load without error."""
    text = sop_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    assert parsed is not None, f"{sop_path.name}: parsed as None (empty file?)"


@pytest.mark.parametrize("sop_path", _SOP_FILES, ids=lambda p: p.name)
def test_each_sop_conforms_to_schema(sop_path: Path):
    """Each SOP passes the hand-rolled schema validator."""
    text = sop_path.read_text(encoding="utf-8")
    sop = yaml.safe_load(text)
    errors = _validate_sop(sop_path.name, sop)
    assert errors == [], (
        f"{sop_path.name} failed schema validation:\n" + "\n".join(f"  - {e}" for e in errors)
    )


def test_stone_pickaxe_final_step():
    """stone_pickaxe.yaml's final step is craft stone_pickaxe count_per_unit: 1 (no scale: false)."""
    sop_path = _SOPS_DIR / "stone_pickaxe.yaml"
    assert sop_path.exists(), "stone_pickaxe.yaml must exist"

    sop = yaml.safe_load(sop_path.read_text(encoding="utf-8"))
    steps = sop["steps"]
    final = steps[-1]

    assert final.get("action") == "craft", (
        f"Final step action should be 'craft', got {final.get('action')!r}"
    )
    assert final.get("item") == "stone_pickaxe", (
        f"Final step item should be 'stone_pickaxe', got {final.get('item')!r}"
    )
    assert final.get("count_per_unit") == 1, (
        f"Final step count_per_unit should be 1, got {final.get('count_per_unit')!r}"
    )
    # The final yield step must NOT have scale: false (it scales with N).
    assert "scale" not in final or final["scale"] is not False, (
        "Final step must not have scale: false — the yield scales with N"
    )


def test_stone_pickaxe_intermediate_tools_have_scale_false():
    """crafting_table and wooden_pickaxe steps inside stone_pickaxe.yaml carry scale: false."""
    sop_path = _SOPS_DIR / "stone_pickaxe.yaml"
    assert sop_path.exists(), "stone_pickaxe.yaml must exist"

    sop = yaml.safe_load(sop_path.read_text(encoding="utf-8"))
    steps = sop["steps"]

    intermediate_items = {"crafting_table", "wooden_pickaxe"}
    for i, step in enumerate(steps):
        item = step.get("item")
        if item in intermediate_items:
            assert step.get("scale") is False, (
                f"steps[{i}] (item={item!r}) must have scale: false "
                f"as it is an intermediate tool step; got scale={step.get('scale')!r}"
            )
