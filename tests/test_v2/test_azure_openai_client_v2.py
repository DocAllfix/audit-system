"""
Test webapp/v2/azure_openai_client_v2.py — wrapper Azure Foundry v1 + retry +
fallback exception. Mock dello SDK OpenAI per evitare chiamate reali.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

from v2.azure_openai_client_v2 import (  # noqa: E402
    AzureOpenAIClientV2,
    AzureRateLimitExhausted,
    _build_user_prompt,
    _sanitize_text,
    analyze_batch_streaming,
    doc_char_cap_for_profile,
)
from v2.provider_profiles_v2 import get_profile  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

class _DeltaObj:
    def __init__(self, content):
        self.content = content


class _ChoiceObj:
    def __init__(self, content, finish_reason=None):
        self.delta = _DeltaObj(content)
        self.finish_reason = finish_reason


class _UsageObj:
    def __init__(self, prompt=100, completion=50, cached=0):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        if cached:
            self.prompt_tokens_details = MagicMock(cached_tokens=cached)
        else:
            self.prompt_tokens_details = None


class _ChunkObj:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


def _make_stream(content_chunks, finish_reason="stop", usage=None):
    """Costruisce un iteratore di chunk SSE-like."""
    for content in content_chunks:
        yield _ChunkObj(choices=[_ChoiceObj(content=content)])
    yield _ChunkObj(choices=[_ChoiceObj(content=None, finish_reason=finish_reason)],
                    usage=usage or _UsageObj())


# ──────────────────────────────────────────────────────────────────────────────
# Tests pure helpers (no network)
# ──────────────────────────────────────────────────────────────────────────────

def test_sanitize_text_strips_control_chars():
    txt = "ciao\x00mondo\x0bcrlf\r\n"
    out = _sanitize_text(txt)
    assert "\x00" not in out
    assert "\x0b" not in out
    assert "\r\n" not in out
    assert "ciao" in out


def test_doc_char_cap_visura_uses_max_pattern():
    cap = doc_char_cap_for_profile("Visura_Camerale_2025.pdf", "", multiplier=2.5)
    assert cap == 75_000  # 30_000 * 2.5


def test_doc_char_cap_default_when_no_pattern():
    cap = doc_char_cap_for_profile("file_random.pdf", "no special content", multiplier=2.5)
    assert cap == 30_000  # 12_000 * 2.5


def test_build_user_prompt_includes_compact_directive():
    docs = [{"filename": "x.pdf", "content": "test"}]
    p = _build_user_prompt(
        docs, batch_idx=0, total_docs=1,
        doc_cap_multiplier=2.5, compact_mode=True,
    )
    assert "MODALITÀ COMPATTA" in p
    assert "1 schede" in p


def test_build_user_prompt_skips_compact_when_off():
    docs = [{"filename": "x.pdf", "content": "test"}]
    p = _build_user_prompt(
        docs, batch_idx=0, total_docs=1,
        doc_cap_multiplier=2.5, compact_mode=False,
    )
    assert "MODALITÀ COMPATTA" not in p


# ──────────────────────────────────────────────────────────────────────────────
# Tests AzureOpenAIClientV2 init
# ──────────────────────────────────────────────────────────────────────────────

def test_client_init_requires_azure_kind():
    gemini_profile = get_profile("gemini-2.5-flash")
    with pytest.raises(ValueError, match="api_kind=azure_openai"):
        AzureOpenAIClientV2(profile=gemini_profile)


def test_client_init_requires_api_key(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI", "gpt-4.1-mini")
    with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
        AzureOpenAIClientV2(profile=get_profile("gpt-4.1-mini-azure"))


def test_client_init_requires_endpoint(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake")
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        AzureOpenAIClientV2(profile=get_profile("gpt-4.1-mini-azure"))


def test_client_init_requires_deployment(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x/openai/v1")
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI", raising=False)
    with patch("openai.OpenAI"):
        with pytest.raises(ValueError, match="DEPLOYMENT"):
            AzureOpenAIClientV2(profile=get_profile("gpt-4.1-mini-azure"))


# ──────────────────────────────────────────────────────────────────────────────
# Tests analyze_batch_streaming — mocked client
# ──────────────────────────────────────────────────────────────────────────────

def _build_mock_client():
    profile = get_profile("gpt-4.1-mini-azure")
    client = MagicMock(spec=AzureOpenAIClientV2)
    client.profile = profile
    return client


def test_analyze_returns_no_client_on_none():
    docs = [{"filename": "x.pdf", "content": "test"}]
    result = analyze_batch_streaming(client=None, batch_docs=docs)
    assert result.error == "no_client"


def test_analyze_returns_empty_batch():
    client = _build_mock_client()
    result = analyze_batch_streaming(client=client, batch_docs=[])
    assert result.error == "empty_batch"


def test_analyze_happy_path():
    client = _build_mock_client()
    client.chat_stream.return_value = _make_stream(
        ["hello", " world"], finish_reason="stop",
    )
    docs = [{"filename": "x.pdf", "content": "test"}]
    result = analyze_batch_streaming(
        client=client, batch_docs=docs, batch_idx=0, total_docs=1,
        universal_prompt="SYSTEM",
    )
    assert "hello world" in result.text
    assert result.error is None


def test_analyze_truncated_flag_propagates():
    client = _build_mock_client()
    client.chat_stream.return_value = _make_stream(
        ["partial"], finish_reason="length",
    )
    docs = [{"filename": "x.pdf", "content": "test"}]
    result = analyze_batch_streaming(
        client=client, batch_docs=docs, universal_prompt="SYSTEM",
    )
    assert getattr(result, "truncated_output", False) is True


def test_analyze_raises_rate_limit_after_retries():
    """Su 429 ripetuti, dopo 3+1 retry la funzione solleva AzureRateLimitExhausted."""
    from openai import RateLimitError

    client = _build_mock_client()

    err = RateLimitError(
        message="rate_limit_exceeded",
        response=MagicMock(status_code=429),
        body=None,
    )
    client.chat_stream.side_effect = err

    docs = [{"filename": "x.pdf", "content": "test"}]
    with patch("v2.azure_openai_client_v2.time.sleep"):  # speed up
        with pytest.raises(AzureRateLimitExhausted) as exc_info:
            analyze_batch_streaming(
                client=client, batch_docs=docs, universal_prompt="SYSTEM",
                enable_retry=True,
            )
        assert exc_info.value.batch_idx == 0
        assert "rate_limit" in exc_info.value.last_error.lower()
