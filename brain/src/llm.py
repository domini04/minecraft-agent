"""Provider-agnostic chat-model factory for the Brain.

Wraps ``langchain.chat_models.init_chat_model`` so the entire Brain has one
chokepoint that knows about API keys, provider strings, and `.env` loading.
Per Decision 22, all LLM imports go through ``init_chat_model`` -- no direct
``ChatGoogleGenerativeAI``/``ChatAnthropic`` imports anywhere else.

`.env` is loaded exactly once per process (lazy, on the first ``get_llm()``
call) via ``python-dotenv``. The default model string is
``google_genai:gemini-3-flash-preview`` and is overridable by either:

* the ``BRAIN_LLM_MODEL`` env var, or
* the ``model`` keyword argument to ``get_llm`` (which wins over env).

No network calls happen at import time. Instantiation of the underlying
provider client (and any credential validation it does) is deferred to the
``init_chat_model`` call inside ``get_llm``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

__all__ = ["get_llm"]

# Module-level guard so ``load_dotenv`` is invoked at most once per process.
# Tests reset this via ``monkeypatch.setattr(llm, "_DOTENV_LOADED", False)``.
_DOTENV_LOADED: bool = False

# Single source of truth for the default provider:model string. Tests
# reference this constant rather than hard-coding the literal.
_DEFAULT_MODEL: str = "google_genai:gemini-3-flash-preview"


def get_llm(model: str | None = None) -> "BaseChatModel":
    """Return a configured chat model, lazily loading ``.env`` once.

    Resolution precedence for the model string:

    1. Explicit ``model`` keyword argument (truthy wins).
    2. ``BRAIN_LLM_MODEL`` env var (truthy wins).
    3. ``_DEFAULT_MODEL`` fallback.

    Empty-string values fall through (Python's ``or`` treats ``""`` as falsy)
    -- intentional, so a stray ``BRAIN_LLM_MODEL=`` does not blow up.

    Args:
        model: Optional explicit ``provider:model`` string. ``None`` defers
            to env / default.

    Returns:
        A LangChain ``BaseChatModel`` from ``init_chat_model`` with
        ``temperature=0`` (Decision 22).
    """
    global _DOTENV_LOADED
    if not _DOTENV_LOADED:
        load_dotenv(override=False)
        _DOTENV_LOADED = True

    model_string = model or os.getenv("BRAIN_LLM_MODEL") or _DEFAULT_MODEL
    return init_chat_model(model_string, temperature=0)
