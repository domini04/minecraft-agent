"""Phase-4 Guide Retriever node (Sprint 4c).

Reads state["goal"], picks the single best matching SOP from the catalog,
extracts a unit count, applies scale_sop, and writes the result to
state["guide"]. A persistent cache short-circuits repeat goals.

Inventory-independent (D33): never reads state["bot_status"].
"""

from __future__ import annotations

import json
import re
import sys
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from src.sops.cache import NONE_SENTINEL
from src.sops.loader import load_all_sops, scale_sop
from src.state import AgentState

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from src.sops.cache import SOPRouteCache


# ---------------------------------------------------------------------------
# Frozen prompts (module-level constants, never modified at runtime)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = (
    "You are the Guide Retriever for an autonomous Minecraft agent.\n"
    "\n"
    "Given a user goal, pick the single best matching SOP (Standard Operating Procedure) "
    "from the catalog below. If the goal doesn't fit any SOP, return \"none\".\n"
    "\n"
    "Also extract the requested count from the goal. Default to 1 if the goal doesn't "
    "specify a number. Use integer count only.\n"
    "\n"
    "Respond in this exact JSON shape, no other text:\n"
    '{{\"sop_name\": \"<name | none>\", \"count\": <integer | null>}}\n'
    "\n"
    "Available SOPs:\n"
    "{catalog}"
)

_RETRY_REMINDER = (
    "Your previous response did not match the required JSON shape. "
    "Respond with EXACTLY: {{\"sop_name\": ..., \"count\": ...}}. "
    "Allowed names: [{allowed}]."
)


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------

def _strip_code_fence(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` wrappers if present. Trim whitespace."""
    s = text.strip()
    if s.startswith("```"):
        # drop leading fence (with optional language tag)
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _parse_response(content: str) -> dict | None:
    """Parse to dict; return None on any failure."""
    try:
        return json.loads(_strip_code_fence(content))
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(
    parsed: dict | None, allowed_names: set[str]
) -> tuple[str | None, int | None]:
    """Return (sop_name, count) or (None, None) on any validation failure.

    Rules:
    - parsed must be a dict.
    - 'sop_name' must be a string and either == 'none' or in allowed_names.
    - 'count' must be either None (only when sop_name == 'none') or a positive int.
      Booleans are explicitly rejected because bool is a subclass of int.
    """
    if not isinstance(parsed, dict):
        return None, None

    sop_name = parsed.get("sop_name")
    if not isinstance(sop_name, str):
        return None, None

    # Normalise: lowercase "none" is the no-match sentinel
    if sop_name == "none":
        # For no-match, count must be None or null — we accept either
        count = parsed.get("count")
        # count can be None/null for no-match; anything else is ignored
        # (we just return count=None for the no-match case)
        return "none", None

    # Real SOP name must be in the allowed catalog
    if sop_name not in allowed_names:
        return None, None

    # count must be a positive integer (bool excluded)
    count = parsed.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        return None, None

    return sop_name, count


# ---------------------------------------------------------------------------
# Catalog rendering helpers
# ---------------------------------------------------------------------------

def _render_catalog(catalog: dict[str, dict]) -> str:
    """Render catalog lines for the system prompt.

    Format per SOP:
        - <name>     : <description> (tags: <tag1, tag2, ...>)
    """
    lines = []
    for name, sop in catalog.items():
        description = sop.get("description", "")
        tags = sop.get("tags", [])
        if isinstance(tags, list):
            tags_str = ", ".join(str(t) for t in tags)
        else:
            tags_str = str(tags)
        lines.append(f"- {name:<16}: {description} (tags: {tags_str})")
    return "\n".join(lines)


def _render_system_prompt(catalog: dict[str, dict]) -> str:
    """Fill the {catalog} slot in _SYSTEM_PROMPT_TEMPLATE."""
    return _SYSTEM_PROMPT_TEMPLATE.format(catalog=_render_catalog(catalog))


# ---------------------------------------------------------------------------
# Cache-hit materialisation
# ---------------------------------------------------------------------------

def _materialize(hit: dict, catalog: dict[str, dict]) -> dict:
    """Convert a cache entry to a state['guide'] value.

    - sop_name == '<none>' (sentinel) -> {} (no-match cached).
    - sop_name in catalog            -> scale_sop(catalog[name], count or 1).
    - sop_name no longer in catalog  -> {} (defensive; fingerprint check should
      have caught this, but be safe if catalog drift slipped through).
    """
    sop_name = hit.get("sop_name", "")
    if sop_name == NONE_SENTINEL:
        return {}
    if sop_name not in catalog:
        # Defensive: catalog drifted despite fingerprint; treat as no-match
        return {}
    count = hit.get("count")
    n = count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 1
    scaled = scale_sop(catalog[sop_name], n)
    scaled["count"] = n  # planner uses this for ×N notation
    return scaled


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def guide_retriever_node(
    state: AgentState,
    *,
    llm: "BaseChatModel | None" = None,
    cache: "SOPRouteCache | None" = None,
    use_cache: bool = True,
) -> AgentState:
    """Phase-4 Guide Retriever: pick the best SOP for the current goal.

    Args:
        state: Current AgentState. Read-only from caller's perspective — this
            function shallow-copies and returns the copy.
        llm: Optional injected chat model (test seam). When None, get_llm() is
            called lazily inside the function so importing this module does not
            trigger network/credential resolution.
        cache: Optional injected SOPRouteCache (test seam). When None and
            use_cache=True, a default SOPRouteCache() is created lazily.
        use_cache: When False, cache read AND write are both bypassed.

    Returns:
        A new AgentState with state["guide"] populated (scaled SOP or {}).
    """
    new_state: AgentState = dict(state)  # shallow copy
    goal = new_state.get("goal", "") or ""

    catalog = load_all_sops()  # {name: sop_dict}
    allowed = set(catalog.keys())

    # ---- cache HIT path ----
    cache_obj = cache
    if use_cache:
        if cache_obj is None:
            from src.sops.cache import SOPRouteCache
            cache_obj = SOPRouteCache()
        hit = cache_obj.get(goal)
        if hit is not None:
            new_state["guide"] = _materialize(hit, catalog)
            return new_state

    # ---- LLM call (cache MISS) ----
    if llm is None:
        from src.llm import get_llm
        llm = get_llm()

    sys_msg = SystemMessage(content=_render_system_prompt(catalog))
    human = HumanMessage(content=goal)
    response = llm.invoke([sys_msg, human])
    parsed = _parse_response(getattr(response, "content", "") or "")
    sop_name, count = _validate(parsed, allowed)

    # ---- 1-retry on validation failure ----
    if sop_name is None:
        retry_sys = SystemMessage(
            content=_render_system_prompt(catalog)
            + "\n\n"
            + _RETRY_REMINDER.format(allowed=", ".join(sorted(allowed)))
        )
        response = llm.invoke([retry_sys, human])
        parsed = _parse_response(getattr(response, "content", "") or "")
        sop_name, count = _validate(parsed, allowed)

    # ---- final fallback: no-match ----
    if sop_name is None:
        print(
            f"retriever: LLM produced invalid output twice for goal={goal!r}, "
            f"treating as no-match",
            file=sys.stderr,
        )
        sop_name = "none"
        count = None

    # ---- cache write ----
    if use_cache and cache_obj is not None:
        cache_obj.set(
            goal,
            sop_name if sop_name != "none" else NONE_SENTINEL,
            count,
        )

    # ---- state.guide population ----
    if sop_name == "none":
        new_state["guide"] = {}
        print(
            f"retriever: no SOP matched goal={goal!r}, proceeding with direct reasoning",
            file=sys.stderr,
        )
    else:
        sop = catalog[sop_name]
        n = count if count is not None else 1
        scaled = scale_sop(sop, n)
        scaled["count"] = n  # planner uses this for ×N notation
        new_state["guide"] = scaled
    return new_state
