"""Structural tests for ``src.llm.get_llm``.

All tests mock ``init_chat_model`` and ``load_dotenv`` on the ``src.llm``
module attribute (NOT the upstream packages) so the test is hermetic and
no real provider client is ever instantiated. ``_DOTENV_LOADED`` is reset
to ``False`` at the start of each test via the ``reset_dotenv_flag``
fixture so the lazy-load path is exercised deterministically.
"""

from unittest.mock import MagicMock

import pytest

from src import llm as llm_module


@pytest.fixture
def reset_dotenv_flag(monkeypatch):
    """Reset the module-level ``_DOTENV_LOADED`` guard before each test."""
    monkeypatch.setattr(llm_module, "_DOTENV_LOADED", False)


def test_get_llm_default_model_string(monkeypatch, reset_dotenv_flag):
    """L1: default resolves to ``google_genai:gemini-3.1-flash-lite``."""
    monkeypatch.delenv("BRAIN_LLM_MODEL", raising=False)
    init_mock = MagicMock(return_value="SENTINEL_LLM")
    dotenv_mock = MagicMock()
    monkeypatch.setattr(llm_module, "init_chat_model", init_mock)
    monkeypatch.setattr(llm_module, "load_dotenv", dotenv_mock)

    llm_module.get_llm()

    init_mock.assert_called_once_with(
        "google_genai:gemini-3.1-flash-lite", temperature=0
    )


def test_get_llm_env_override(monkeypatch, reset_dotenv_flag):
    """L2: ``BRAIN_LLM_MODEL`` env var overrides the default."""
    monkeypatch.setenv("BRAIN_LLM_MODEL", "anthropic:claude-haiku-4-5")
    init_mock = MagicMock(return_value="SENTINEL_LLM")
    dotenv_mock = MagicMock()
    monkeypatch.setattr(llm_module, "init_chat_model", init_mock)
    monkeypatch.setattr(llm_module, "load_dotenv", dotenv_mock)

    llm_module.get_llm()

    init_mock.assert_called_once_with(
        "anthropic:claude-haiku-4-5", temperature=0
    )


def test_get_llm_explicit_arg_wins_over_env(monkeypatch, reset_dotenv_flag):
    """L3: explicit ``model=`` argument wins over the env var."""
    monkeypatch.setenv("BRAIN_LLM_MODEL", "x:y")
    init_mock = MagicMock(return_value="SENTINEL_LLM")
    dotenv_mock = MagicMock()
    monkeypatch.setattr(llm_module, "init_chat_model", init_mock)
    monkeypatch.setattr(llm_module, "load_dotenv", dotenv_mock)

    llm_module.get_llm("a:b")

    init_mock.assert_called_once_with("a:b", temperature=0)


def test_get_llm_load_dotenv_called_at_most_once(
    monkeypatch, reset_dotenv_flag
):
    """L4: ``load_dotenv(override=False)`` runs exactly once across N calls."""
    monkeypatch.delenv("BRAIN_LLM_MODEL", raising=False)
    init_mock = MagicMock(return_value="SENTINEL_LLM")
    dotenv_mock = MagicMock()
    monkeypatch.setattr(llm_module, "init_chat_model", init_mock)
    monkeypatch.setattr(llm_module, "load_dotenv", dotenv_mock)

    llm_module.get_llm()
    llm_module.get_llm()
    llm_module.get_llm()

    dotenv_mock.assert_called_once_with(override=False)
    assert init_mock.call_count == 3


def test_get_llm_returns_init_chat_model_result(
    monkeypatch, reset_dotenv_flag
):
    """L5: ``get_llm`` returns whatever ``init_chat_model`` returns, unwrapped."""
    monkeypatch.delenv("BRAIN_LLM_MODEL", raising=False)
    sentinel = object()
    init_mock = MagicMock(return_value=sentinel)
    dotenv_mock = MagicMock()
    monkeypatch.setattr(llm_module, "init_chat_model", init_mock)
    monkeypatch.setattr(llm_module, "load_dotenv", dotenv_mock)

    result = llm_module.get_llm()

    assert result is sentinel
