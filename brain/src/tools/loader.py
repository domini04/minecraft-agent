"""Tool loader: hand-written Pydantic args models + StructuredTool registry.

This module is the typed Python interface over ``shared/tool-schemas/``. It
provides:

- Six Pydantic v2 args models (``ChatArgs``, ``GetBotStatusArgs``,
  ``NavigateArgs``, ``MineArgs``, ``CraftArgs``, ``PlaceBlockArgs``) plus the
  nested ``CraftingTablePos`` — each mirrors the corresponding JSON Schema's
  required/properties/additionalProperties contract.
- A startup *drift guard* (``_check_drift``) that compares each model's
  emitted ``model_json_schema()`` against the on-disk JSON Schema and raises
  ``ImportError`` on mismatch — fast-fail at module load.
- ``get_tools() -> list[StructuredTool]`` returning the six tools in the
  order fixed by ``index.json``. Each tool's ``func`` is a named placeholder
  raising ``NotImplementedError`` — execution is dispatched by Sprint 3f's
  executor node, not by these shells.

No LLM calls, no network, no body server. The module stays import-light:
LangChain core is pulled for ``StructuredTool``; ``langgraph`` and
``requests`` must NOT be transitively imported (asserted by C8).
"""

from __future__ import annotations

import json
import pathlib
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from langchain_core.tools import StructuredTool

__all__ = [
    "ChatArgs",
    "GetBotStatusArgs",
    "NavigateArgs",
    "MineArgs",
    "CraftArgs",
    "PlaceBlockArgs",
    "CraftingTablePos",
    "TOOL_ARG_MODELS",
    "TOOL_DESCRIPTIONS",
    "SCHEMAS_DIR",
    "get_tools",
]

# brain/src/tools/loader.py -> parents[3] = repo root
SCHEMAS_DIR: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[3] / "shared" / "tool-schemas"
)

if not SCHEMAS_DIR.is_dir():
    raise ImportError(
        f"shared/tool-schemas directory not found at {SCHEMAS_DIR!s}; "
        "brain/src/tools/loader.py expects to live three levels under repo root."
    )


# ---------- Args models (Approach B: hand-written) ----------


class ChatArgs(BaseModel):
    """Args for the ``chat`` tool — a single in-game chat message."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=256)


class GetBotStatusArgs(BaseModel):
    """Args for the ``get_bot_status`` tool — no parameters."""

    model_config = ConfigDict(extra="forbid")


class NavigateArgs(BaseModel):
    """Args for the ``navigate`` tool — float coords (no per-field bounds)."""

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    z: float


class MineArgs(BaseModel):
    """Args for the ``mine`` tool."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1, pattern=r"\S")
    count: int = Field(ge=1)
    max_distance: Optional[int] = Field(default=None, ge=1, le=128)


class CraftingTablePos(BaseModel):
    """Optional explicit crafting-table coordinates (integer block coords)."""

    model_config = ConfigDict(extra="forbid")

    x: int
    y: int
    z: int


class CraftArgs(BaseModel):
    """Args for the ``craft`` tool."""

    model_config = ConfigDict(extra="forbid")

    item: str = Field(min_length=1, pattern=r"\S")
    count: int = Field(ge=1)
    crafting_table_pos: Optional[CraftingTablePos] = None


class PlaceBlockArgs(BaseModel):
    """Args for the ``place_block`` tool — float-permissive coords."""

    model_config = ConfigDict(extra="forbid")

    block: str = Field(min_length=1, pattern=r"\S")
    x: float
    y: float
    z: float


# ---------- Registries (index.json order) ----------


def _load_schemas() -> dict[str, dict]:
    """Load ``index.json`` and each per-tool schema, preserving insertion order."""
    with open(SCHEMAS_DIR / "index.json") as f:
        index = json.load(f)
    schemas: dict[str, dict] = {}
    for tool_name, filename in index.items():
        with open(SCHEMAS_DIR / filename) as f:
            schemas[tool_name] = json.load(f)
    return schemas


_SCHEMAS: dict[str, dict] = _load_schemas()

# Built in index.json order; Python dict preserves insertion order.
TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "chat": ChatArgs,
    "get_bot_status": GetBotStatusArgs,
    "navigate": NavigateArgs,
    "mine": MineArgs,
    "craft": CraftArgs,
    "place_block": PlaceBlockArgs,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    name: _SCHEMAS[name]["description"] for name in TOOL_ARG_MODELS
}


# ---------- Drift guard ----------


def _resolve_property_type(
    prop_schema: dict, model_schema: dict
) -> Optional[str]:
    """Return the JSON-Schema ``type`` string for a Pydantic-emitted property.

    Handles three shapes:

    * Direct: ``{"type": "string"}`` -> ``"string"``.
    * Optional via anyOf: ``{"anyOf": [{"type": "integer"}, {"type": "null"}]}``
      -> ``"integer"`` (the non-null branch).
    * $ref to a nested defs entry (e.g. ``CraftingTablePos``): resolve the ref
      against ``model_schema["$defs"]`` (or ``definitions``) and return its
      top-level ``type``.

    Returns ``None`` if no type can be resolved.
    """
    if "type" in prop_schema:
        return prop_schema["type"]
    if "$ref" in prop_schema:
        ref = prop_schema["$ref"]
        # Pydantic v2 uses "#/$defs/Name"
        if ref.startswith("#/$defs/"):
            defs = model_schema.get("$defs", {})
            target = defs.get(ref.removeprefix("#/$defs/"))
            if target and "type" in target:
                return target["type"]
        if ref.startswith("#/definitions/"):
            defs = model_schema.get("definitions", {})
            target = defs.get(ref.removeprefix("#/definitions/"))
            if target and "type" in target:
                return target["type"]
        return None
    if "anyOf" in prop_schema:
        for branch in prop_schema["anyOf"]:
            if branch.get("type") == "null":
                continue
            inner = _resolve_property_type(branch, model_schema)
            if inner is not None:
                return inner
        return None
    return None


def _check_drift(
    schemas: dict[str, dict], models: dict[str, type[BaseModel]]
) -> None:
    """Compare on-disk JSON schemas against Pydantic-emitted schemas.

    Raises ``ImportError`` on the first detected mismatch. Compared dimensions:

    * Tool-name set equality.
    * ``required`` set equality (treats missing/empty as equal).
    * ``additionalProperties is False`` on both sides.
    * Each property declared in the JSON Schema has a same-typed counterpart
      in the Pydantic-emitted schema (per ``_resolve_property_type``).

    Pure function — no I/O. The module-load invocation passes the on-disk
    schemas; tests can pass synthetic dicts to exercise the failure path
    without touching real files.
    """
    schema_names = set(schemas.keys())
    model_names = set(models.keys())
    if schema_names != model_names:
        raise ImportError(
            "Schema/Pydantic drift in tool registry: schema names "
            f"{sorted(schema_names)} != model names {sorted(model_names)}"
        )

    for tool_name, schema in schemas.items():
        model = models[tool_name]
        model_schema = model.model_json_schema()

        schema_required = set(schema.get("required", []) or [])
        model_required = set(model_schema.get("required", []) or [])
        if schema_required != model_required:
            raise ImportError(
                f"Schema/Pydantic drift in {tool_name}: required mismatch "
                f"schema={sorted(schema_required)} model={sorted(model_required)}"
            )

        if schema.get("additionalProperties", True) is not False:
            raise ImportError(
                f"Schema/Pydantic drift in {tool_name}: "
                "JSON Schema must set additionalProperties=false"
            )
        if model_schema.get("additionalProperties") is not False:
            raise ImportError(
                f"Schema/Pydantic drift in {tool_name}: "
                "Pydantic model must emit additionalProperties=false "
                "(set model_config = ConfigDict(extra='forbid'))"
            )

        schema_props = schema.get("properties", {}) or {}
        model_props = model_schema.get("properties", {}) or {}
        for prop_name, prop_schema in schema_props.items():
            if prop_name not in model_props:
                raise ImportError(
                    f"Schema/Pydantic drift in {tool_name}: "
                    f"property {prop_name!r} missing from Pydantic model"
                )
            expected_type = prop_schema.get("type")
            actual_type = _resolve_property_type(
                model_props[prop_name], model_schema
            )
            if expected_type != actual_type:
                raise ImportError(
                    f"Schema/Pydantic drift in {tool_name}.{prop_name}: "
                    f"schema type={expected_type!r} pydantic type={actual_type!r}"
                )


# Fail-fast at import time.
_check_drift(_SCHEMAS, TOOL_ARG_MODELS)


# ---------- StructuredTool factory ----------


def _make_placeholder(tool_name: str):
    """Return a *named* placeholder callable for ``tool_name``.

    The function's ``__name__`` is set to ``_<tool_name>_placeholder`` so
    Sprint 3f tracebacks identify which tool the LLM tried to invoke directly
    (instead of going through the executor node).
    """

    def _placeholder(**_kwargs: Any) -> None:
        raise NotImplementedError(
            "dispatched via executor node — Sprint 3f"
        )

    _placeholder.__name__ = f"_{tool_name}_placeholder"
    _placeholder.__qualname__ = _placeholder.__name__
    return _placeholder


_TOOLS_CACHE: Optional[list["StructuredTool"]] = None


def _build_tools() -> list["StructuredTool"]:
    # Lazy import: avoids pulling ``langchain_core.utils.utils`` (and its
    # transitive ``requests`` import) into ``sys.modules`` at loader-module
    # import time. The C8 imports-clean criterion requires that merely
    # importing ``src.tools.loader`` not pull network deps.
    from langchain_core.tools import StructuredTool

    tools: list[StructuredTool] = []
    for name, args_model in TOOL_ARG_MODELS.items():
        tools.append(
            StructuredTool.from_function(
                func=_make_placeholder(name),
                name=name,
                description=TOOL_DESCRIPTIONS[name],
                args_schema=args_model,
                return_direct=False,
            )
        )
    return tools


def get_tools() -> list["StructuredTool"]:
    """Return the six tools as a fresh list, in ``index.json`` order.

    The underlying ``StructuredTool`` objects are constructed lazily on the
    first call and cached; subsequent calls return a shallow copy of the
    cached list so callers can reorder/filter without affecting later calls.
    Each tool's ``func`` raises ``NotImplementedError`` — execution is the
    executor node's job (Sprint 3f), not these shells'.

    The lazy construction keeps loader-module import light: ``StructuredTool``
    transitively imports ``requests``, which the C8 imports-clean criterion
    forbids at loader-import time.
    """
    global _TOOLS_CACHE
    if _TOOLS_CACHE is None:
        _TOOLS_CACHE = _build_tools()
    return list(_TOOLS_CACHE)
