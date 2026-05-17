"""SOP loader, scaler, and manifest-fingerprint utilities.

Pure-Python; no network, no LLM, no graph dependencies. Sprint 4b deliverable.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import yaml


def _sops_dir() -> Path:
    """Absolute path to brain/src/sops/, resolved relative to this file."""
    return Path(__file__).resolve().parent


def load_sop(name: str) -> dict[str, Any]:
    """Load and return a single SOP by name.

    Args:
        name: SOP identifier, with or without `.yaml` suffix.
              E.g. ``"oak_planks"`` or ``"oak_planks.yaml"`` are both valid.

    Returns:
        Parsed top-level YAML dict.

    Raises:
        FileNotFoundError: If no matching YAML file exists.
        ValueError: If the file exists but cannot be parsed as valid YAML.
    """
    if name.endswith(".yaml"):
        name = name[:-5]
    path = _sops_dir() / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"SOP not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
        sop = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e
    return sop


def load_all_sops() -> dict[str, dict[str, Any]]:
    """Load all enabled SOPs from the sops directory.

    Excludes ``index.yaml`` (auto-generated catalog) and any SOP file
    that has ``disabled: true`` at the top level (D29).

    Returns:
        ``{stem: sop_dict}`` mapping, e.g. ``{"oak_planks": {...}, ...}``.
        Keys are filename stems (not the human-readable ``sop["name"]``).
    """
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(_sops_dir().glob("*.yaml")):
        if path.name == "index.yaml":
            continue
        sop = load_sop(path.stem)
        if sop.get("disabled") is True:
            continue
        out[path.stem] = sop
    return out


def scale_sop(sop: dict[str, Any], n: int) -> dict[str, Any]:
    """Return a new SOP dict scaled by *n* units (D31).

    Multiplied fields:
    - ``yields`` × n (always; no opt-out).
    - Each entry in ``requires``: ``count_per_unit`` × n (D33: no per-entry flag).
    - Each entry in ``steps``: ``count_per_unit`` × n **unless** the step has
      ``scale: false``, in which case ``count_per_unit`` is left unchanged.

    The ``scale: false`` key itself is preserved in the output dict (it is
    metadata, not consumed here).

    Args:
        sop: Parsed SOP dict (e.g. from :func:`load_sop`). Not mutated.
        n: Positive integer ≥ 1. Booleans are explicitly rejected.

    Returns:
        Fresh deep-copied dict with scaled numeric fields.

    Raises:
        ValueError: If ``n`` is a bool, zero, or negative.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError(f"scale_sop requires n >= 1 (int, not bool), got {n!r}")

    out = copy.deepcopy(sop)

    if "yields" in out:
        out["yields"] = out["yields"] * n

    if "requires" in out and isinstance(out["requires"], list):
        for req in out["requires"]:
            if isinstance(req, dict) and "count_per_unit" in req:
                req["count_per_unit"] = req["count_per_unit"] * n

    if "steps" in out and isinstance(out["steps"], list):
        for step in out["steps"]:
            if not isinstance(step, dict):
                continue
            if step.get("scale") is False:
                continue  # opted out of scaling
            if "count_per_unit" in step:
                step["count_per_unit"] = step["count_per_unit"] * n

    return out


def manifest_fingerprint(index_path: "Path | str") -> str:
    """Return the SHA-256 fingerprint of *index_path* as ``"sha256:<hex>"``.

    Reads bytes (not text) for cross-platform stability — line-ending changes
    intentionally invalidate the fingerprint, which is correct for Sprint 4c's
    cache invalidation logic (D30).

    Args:
        index_path: Path to ``index.yaml`` (str or Path).

    Returns:
        ``"sha256:<64-hex-chars>"``.

    Raises:
        FileNotFoundError: If the path does not exist (propagated from read_bytes).
    """
    path = Path(index_path)
    data = path.read_bytes()
    return f"sha256:{hashlib.sha256(data).hexdigest()}"
