"""Unit tests for brain/src/nodes/guide_retriever.py.

All tests inject a StubLLM and an isolated SOPRouteCache so no real LLM or
real cache file is ever touched. The StubLLM pattern mirrors test_planner_node.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.nodes.guide_retriever import (
    _RETRY_REMINDER,
    _SYSTEM_PROMPT_TEMPLATE,
    _materialize,
    _parse_response,
    _strip_code_fence,
    _validate,
    guide_retriever_node,
)
from src.sops.cache import NONE_SENTINEL, SOPRouteCache
from src.sops.loader import load_all_sops, scale_sop
from src.state import make_initial_state


# ---------------------------------------------------------------------------
# StubLLM — mirrors test_planner_node.py
# ---------------------------------------------------------------------------


class StubLLM:
    """Minimal LLM stub. Returns canned AIMessage responses in sequence.

    Records invoke calls so tests can assert on call count and message content.
    Raises AssertionError if invoked beyond available responses.
    """

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.invoke_args: list = []

    def invoke(self, messages):
        self.invoke_args.append(list(messages))
        if not self._responses:
            raise AssertionError("StubLLM ran out of responses")
        return self._responses.pop(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(goal: str, guide=None, bot_status=None) -> dict:
    s = make_initial_state(goal)
    if guide is not None:
        s["guide"] = guide
    if bot_status is not None:
        s["bot_status"] = bot_status
    return s


def _make_cache(tmp_path: Path) -> SOPRouteCache:
    return SOPRouteCache(cache_path=tmp_path / "sop_routes.json")


# ---------------------------------------------------------------------------
# Low-level helper unit tests (strip_code_fence, parse, validate)
# ---------------------------------------------------------------------------


def test_strip_code_fence_no_fence():
    assert _strip_code_fence('{"a": 1}') == '{"a": 1}'


def test_strip_code_fence_json_tag():
    raw = '```json\n{"a": 1}\n```'
    assert _strip_code_fence(raw) == '{"a": 1}'


def test_strip_code_fence_no_tag():
    raw = '```\n{"a": 1}\n```'
    assert _strip_code_fence(raw) == '{"a": 1}'


def test_parse_response_valid():
    result = _parse_response('{"sop_name": "oak_planks", "count": 1}')
    assert result == {"sop_name": "oak_planks", "count": 1}


def test_parse_response_invalid_returns_none():
    assert _parse_response("not json at all") is None
    assert _parse_response("") is None


def test_validate_valid_sop():
    allowed = {"oak_planks", "stick"}
    sop_name, count = _validate({"sop_name": "oak_planks", "count": 2}, allowed)
    assert sop_name == "oak_planks"
    assert count == 2


def test_validate_none_sop():
    allowed = {"oak_planks"}
    sop_name, count = _validate({"sop_name": "none", "count": None}, allowed)
    assert sop_name == "none"
    assert count is None


def test_validate_hallucinated_name():
    allowed = {"oak_planks"}
    sop_name, count = _validate({"sop_name": "diamond_pickaxe", "count": 1}, allowed)
    assert sop_name is None
    assert count is None


def test_validate_bool_count_rejected():
    allowed = {"oak_planks"}
    sop_name, count = _validate({"sop_name": "oak_planks", "count": True}, allowed)
    assert sop_name is None


def test_validate_zero_count_rejected():
    allowed = {"oak_planks"}
    sop_name, count = _validate({"sop_name": "oak_planks", "count": 0}, allowed)
    assert sop_name is None


def test_validate_null_count_for_real_sop_rejected():
    """count=null for a real sop_name is invalid (triggers retry path)."""
    allowed = {"oak_planks"}
    sop_name, count = _validate({"sop_name": "oak_planks", "count": None}, allowed)
    assert sop_name is None


def test_validate_not_a_dict():
    sop_name, count = _validate(None, {"oak_planks"})
    assert sop_name is None
    sop_name, count = _validate("string", {"oak_planks"})  # type: ignore[arg-type]
    assert sop_name is None


# ---------------------------------------------------------------------------
# R-T1: Cache HIT — no LLM call
# ---------------------------------------------------------------------------


def test_cache_hit_no_llm_call(tmp_path):
    """R-T1: cache HIT skips LLM; guide is materialized from cache."""
    cache = _make_cache(tmp_path)
    catalog = load_all_sops()
    cache.set("craft 1 oak_planks", "oak_planks", 1)

    stub = StubLLM(responses=[])  # empty — would raise if invoked
    state = _make_state("craft 1 oak_planks")

    new_state = guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    assert len(stub.invoke_args) == 0, "LLM should NOT be called on cache HIT"
    expected = scale_sop(catalog["oak_planks"], 1)
    assert new_state["guide"] == expected


# ---------------------------------------------------------------------------
# R-T2: Cache MISS + valid LLM response
# ---------------------------------------------------------------------------


def test_cache_miss_valid_llm_response(tmp_path):
    """R-T2: cache MISS → one LLM call → guide set → entry cached."""
    cache = _make_cache(tmp_path)
    catalog = load_all_sops()

    stub = StubLLM(
        responses=[AIMessage(content='{"sop_name":"oak_planks","count":1}')]
    )
    state = _make_state("craft 1 oak_planks")

    new_state = guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    assert len(stub.invoke_args) == 1
    expected = scale_sop(catalog["oak_planks"], 1)
    assert new_state["guide"] == expected

    # Cache should have the entry
    entry = cache.get("craft 1 oak_planks")
    assert entry is not None
    assert entry["sop_name"] == "oak_planks"
    assert entry["count"] == 1


# ---------------------------------------------------------------------------
# R-T3: Cache MISS + invalid then valid on retry
# ---------------------------------------------------------------------------


def test_cache_miss_retry_success(tmp_path):
    """R-T3: first invalid LLM response → retry → valid → guide set."""
    cache = _make_cache(tmp_path)
    catalog = load_all_sops()

    stub = StubLLM(
        responses=[
            AIMessage(content="not json at all"),
            AIMessage(content='{"sop_name":"stick","count":2}'),
        ]
    )
    state = _make_state("craft some sticks")

    new_state = guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    assert len(stub.invoke_args) == 2, "Should call LLM twice (first + retry)"

    # Retry prompt should contain the RETRY_REMINDER text
    retry_system_content = stub.invoke_args[1][0].content
    assert "Respond with EXACTLY" in retry_system_content

    expected = scale_sop(catalog["stick"], 2)
    assert new_state["guide"] == expected


# ---------------------------------------------------------------------------
# R-T4: Cache MISS + invalid twice → fallback
# ---------------------------------------------------------------------------


def test_cache_miss_double_invalid_fallback(tmp_path, capsys):
    """R-T4: two invalid responses → no-match fallback, <none> cached, stderr."""
    cache = _make_cache(tmp_path)

    stub = StubLLM(
        responses=[
            AIMessage(content="garbage"),
            AIMessage(content='{"oops":true}'),
        ]
    )
    state = _make_state("do something weird")

    new_state = guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    assert new_state["guide"] == {}

    # Cache should have <none> sentinel
    entry = cache.get("do something weird")
    assert entry is not None
    assert entry["sop_name"] == NONE_SENTINEL
    assert entry["count"] is None

    captured = capsys.readouterr()
    assert "LLM produced invalid output twice" in captured.err
    assert "no SOP matched" in captured.err


# ---------------------------------------------------------------------------
# R-T5: LLM no-match response ("none")
# ---------------------------------------------------------------------------


def test_llm_no_match_response(tmp_path, capsys):
    """R-T5: LLM returns 'none' → guide={}, sentinel cached, one call, stderr."""
    cache = _make_cache(tmp_path)

    stub = StubLLM(
        responses=[AIMessage(content='{"sop_name":"none","count":null}')]
    )
    state = _make_state("do something exotic")

    new_state = guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    assert new_state["guide"] == {}
    assert len(stub.invoke_args) == 1  # no retry needed — "none" is valid

    entry = cache.get("do something exotic")
    assert entry is not None
    assert entry["sop_name"] == NONE_SENTINEL

    captured = capsys.readouterr()
    assert "no SOP matched" in captured.err


# ---------------------------------------------------------------------------
# R-T6: Count extraction (n=5)
# ---------------------------------------------------------------------------


def test_count_extraction_n5(tmp_path):
    """R-T6: LLM returns count=5; guide has yields and steps scaled x5."""
    cache = _make_cache(tmp_path)
    catalog = load_all_sops()

    stub = StubLLM(
        responses=[AIMessage(content='{"sop_name":"stone_pickaxe","count":5}')]
    )
    state = _make_state("craft 5 stone pickaxes")

    new_state = guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    expected = scale_sop(catalog["stone_pickaxe"], 5)
    assert new_state["guide"]["yields"] == expected["yields"]

    # Find the mine-oak_log step (count_per_unit: 3 base, should be 15 after x5)
    guide_steps = new_state["guide"].get("steps", [])
    mine_oak = next(
        (s for s in guide_steps if s.get("action") == "mine" and s.get("target") == "oak_log"),
        None,
    )
    assert mine_oak is not None, "mine oak_log step not found"
    assert mine_oak["count_per_unit"] == 15  # 3 * 5


# ---------------------------------------------------------------------------
# R-T7: Default count=1 on cache hit with count=None (legacy cache entry)
# ---------------------------------------------------------------------------


def test_cache_hit_null_count_defaults_to_1(tmp_path):
    """R-T7: cache hit with count=None for a real sop materializes as scale_sop(sop, 1)."""
    cache = _make_cache(tmp_path)
    catalog = load_all_sops()

    # Inject legacy cache entry manually (count=None for a real SOP)
    cache_path = tmp_path / "sop_routes.json"
    from src.sops.loader import manifest_fingerprint
    import src.sops.cache as cache_mod
    index_path = cache_mod._index_path()
    fp = manifest_fingerprint(index_path) if index_path.exists() else ""
    data = {
        "schema_version": 1,
        "manifest_fingerprint": fp,
        "entries": {
            "craft sticks": {"sop_name": "stick", "count": None}
        },
    }
    cache_path.write_text(json.dumps(data), encoding="utf-8")

    fresh_cache = SOPRouteCache(cache_path=cache_path)
    stub = StubLLM(responses=[])  # should not be called

    state = _make_state("craft sticks")
    new_state = guide_retriever_node(state, llm=stub, cache=fresh_cache, use_cache=True)

    assert len(stub.invoke_args) == 0
    expected = scale_sop(catalog["stick"], 1)
    assert new_state["guide"] == expected


# ---------------------------------------------------------------------------
# R-T8: use_cache=False bypasses read and write
# ---------------------------------------------------------------------------


def test_use_cache_false_bypasses_read_and_write(tmp_path):
    """R-T8: use_cache=False → LLM always called; cache untouched."""
    cache_path = tmp_path / "sop_routes.json"
    cache = SOPRouteCache(cache_path=cache_path)

    # Pre-populate cache
    cache.set("craft sticks", "stick", 1)

    # Capture file contents before
    contents_before = cache_path.read_text(encoding="utf-8")

    stub = StubLLM(
        responses=[AIMessage(content='{"sop_name":"stick","count":3}')]
    )
    state = _make_state("craft sticks")

    new_state = guide_retriever_node(
        state, llm=stub, cache=cache, use_cache=False
    )

    # LLM WAS called (cache read bypassed)
    assert len(stub.invoke_args) == 1

    # Cache file is UNCHANGED (cache write bypassed)
    contents_after = cache_path.read_text(encoding="utf-8")
    assert contents_before == contents_after


# ---------------------------------------------------------------------------
# R-T9: Code-fence JSON
# ---------------------------------------------------------------------------


def test_code_fence_json_parsed_correctly(tmp_path):
    """R-T9: LLM response wrapped in ```json ... ``` parses correctly."""
    cache = _make_cache(tmp_path)
    catalog = load_all_sops()

    stub = StubLLM(
        responses=[
            AIMessage(
                content='```json\n{"sop_name":"oak_planks","count":1}\n```'
            )
        ]
    )
    state = _make_state("craft oak planks")

    new_state = guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    assert len(stub.invoke_args) == 1  # parsed on first try, no retry
    expected = scale_sop(catalog["oak_planks"], 1)
    assert new_state["guide"] == expected


# ---------------------------------------------------------------------------
# R-T10: Hallucinated SOP → retry → still hallucinated → fallback
# ---------------------------------------------------------------------------


def test_hallucinated_sop_triggers_retry_then_fallback(tmp_path, capsys):
    """R-T10: hallucinated name → retry → still hallucinated → guide={}."""
    cache = _make_cache(tmp_path)

    stub = StubLLM(
        responses=[
            AIMessage(content='{"sop_name":"diamond_pickaxe","count":1}'),
            AIMessage(content='{"sop_name":"diamond_pickaxe","count":1}'),
        ]
    )
    state = _make_state("craft a diamond pickaxe")

    new_state = guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    assert len(stub.invoke_args) == 2  # first + retry
    assert new_state["guide"] == {}

    entry = cache.get("craft a diamond pickaxe")
    assert entry is not None
    assert entry["sop_name"] == NONE_SENTINEL

    captured = capsys.readouterr()
    assert "LLM produced invalid output twice" in captured.err


# ---------------------------------------------------------------------------
# R-T11: State immutability
# ---------------------------------------------------------------------------


def test_state_immutability(tmp_path):
    """R-T11: input state is NOT mutated; returned state has new guide."""
    cache = _make_cache(tmp_path)

    stub = StubLLM(
        responses=[AIMessage(content='{"sop_name":"stick","count":1}')]
    )
    original_guide = {"sentinel": "original"}
    state = _make_state("craft sticks", guide=original_guide)

    new_state = guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    # Input state unchanged
    assert state["guide"] == {"sentinel": "original"}
    # Returned state has new guide
    assert new_state["guide"] != {"sentinel": "original"}
    # The returned dict is a new object
    assert new_state is not state


# ---------------------------------------------------------------------------
# R-T12: System prompt includes catalog
# ---------------------------------------------------------------------------


def test_system_prompt_includes_catalog(tmp_path):
    """R-T12: system message contains SOP names from load_all_sops()."""
    cache = _make_cache(tmp_path)
    catalog = load_all_sops()

    stub = StubLLM(
        responses=[AIMessage(content='{"sop_name":"oak_planks","count":1}')]
    )
    state = _make_state("craft something")

    guide_retriever_node(state, llm=stub, cache=cache, use_cache=True)

    assert len(stub.invoke_args) == 1
    system_content = stub.invoke_args[0][0].content

    for sop_name in catalog.keys():
        assert sop_name in system_content, (
            f"SOP name '{sop_name}' not found in system prompt"
        )


# ---------------------------------------------------------------------------
# R-T13: Inventory-independence (D33)
# ---------------------------------------------------------------------------


def test_inventory_independence_d33(tmp_path):
    """R-T13: two states with different bot_status but same goal both get same guide."""
    cache = _make_cache(tmp_path)
    catalog = load_all_sops()

    # Pre-populate cache once
    cache.set("craft oak planks", "oak_planks", 1)

    stub_a = StubLLM(responses=[])  # cache HIT — no LLM call needed
    stub_b = StubLLM(responses=[])

    state_a = _make_state("craft oak planks", bot_status={"inventory": []})
    state_b = _make_state(
        "craft oak planks",
        bot_status={"inventory": [{"name": "oak_log", "count": 5}]},
    )

    result_a = guide_retriever_node(state_a, llm=stub_a, cache=cache, use_cache=True)
    result_b = guide_retriever_node(state_b, llm=stub_b, cache=cache, use_cache=True)

    assert len(stub_a.invoke_args) == 0
    assert len(stub_b.invoke_args) == 0

    expected = scale_sop(catalog["oak_planks"], 1)
    assert result_a["guide"] == expected
    assert result_b["guide"] == expected
    assert result_a["guide"] == result_b["guide"]
