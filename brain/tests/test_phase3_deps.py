"""Smoke test: verify Phase 3 dependency imports resolve cleanly.

No network calls, no model instantiation, no env var reads.
"""

import langgraph  # noqa: F401
import langchain_google_genai  # noqa: F401
import dotenv  # noqa: F401
from langchain.chat_models import init_chat_model


def test_phase3_imports():
    """All four Phase 3 packages plus init_chat_model symbol are importable."""
    assert init_chat_model is not None
