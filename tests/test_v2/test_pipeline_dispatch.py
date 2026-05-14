"""
Test webapp/v2/llm_dispatch.py — factory provider + smoke pipeline dispatch.

NB: i test pieni end-to-end della pipeline con provider Azure stanno nei test
manuali (Step 4 della migrazione). Qui validiamo solo il dispatch correttamente.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

from v2.llm_dispatch import build_dispatch, fallback_disabled  # noqa: E402


def test_build_dispatch_unknown_provider_raises():
    with pytest.raises(KeyError):
        build_dispatch("not-a-real-provider", api_key="x")


def test_build_dispatch_azure_requires_env(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    with pytest.raises(ValueError):
        build_dispatch("gpt-4.1-mini-azure")


def test_build_dispatch_azure_returns_correct_callable(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI", "gpt-4.1-mini")
    with patch("openai.OpenAI"):
        d = build_dispatch("gpt-4.1-mini-azure")
        assert d.profile.api_kind == "azure_openai"
        assert d.profile.name == "gpt-4.1-mini"
        # analyze deve essere la funzione del modulo Azure
        from v2.azure_openai_client_v2 import analyze_batch_streaming as azure_fn
        assert d.analyze is azure_fn


def test_build_dispatch_gemini_uses_native_client():
    """Gemini path: se passo gemini_client, lo usa (no genai_factory)."""
    fake_client = object()
    d = build_dispatch("gemini-2.5-flash", gemini_client=fake_client)
    assert d.profile.api_kind == "gemini_v2_native"
    assert d.client is fake_client
    from v2.gemini_client_v2 import analyze_batch_streaming as gemini_fn
    assert d.analyze is gemini_fn


def test_fallback_disabled_default_false(monkeypatch):
    monkeypatch.delenv("V2_DISABLE_FALLBACK", raising=False)
    assert fallback_disabled() is False


def test_fallback_disabled_when_set(monkeypatch):
    monkeypatch.setenv("V2_DISABLE_FALLBACK", "1")
    assert fallback_disabled() is True


def test_fallback_disabled_zero_is_active(monkeypatch):
    monkeypatch.setenv("V2_DISABLE_FALLBACK", "0")
    assert fallback_disabled() is False
