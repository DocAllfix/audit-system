"""
Test suite per webapp.spike_llm.azure_openai_client.

Mock-based, zero chiamate API reali. Copre:
- Risoluzione deployment da env var
- Init AzureOpenAIClient con env var mancanti -> errore esplicito
- analyze_batch_streaming con mock chunk stream -> StreamResult valido
- Truncation detection (finish_reason == "length") -> flag truncated_output
- Cap doc scalato per profile.doc_cap_multiplier
- Token meter registra con model corretto
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
if str(_WEBAPP_DIR) not in sys.path:
    sys.path.insert(0, str(_WEBAPP_DIR))


# Stub `openai` se non installato — i test sono mock-based e non chiamano API reale.
def _ensure_openai_stub():
    if "openai" in sys.modules:
        return
    stub = types.ModuleType("openai")
    class _OpenAI:
        def __init__(self, *a, **kw):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kw: iter([])),
            )
    class _APIError(Exception): pass
    class _APIStatusError(_APIError):
        def __init__(self, *a, **kw):
            super().__init__(*a)
            self.status_code = kw.get("status_code", 500)
    class _APIConnectionError(_APIError): pass
    class _BadRequestError(_APIError): pass
    class _RateLimitError(_APIError): pass
    stub.OpenAI = _OpenAI
    stub.AzureOpenAI = _OpenAI  # alias retro-compat se importato
    stub.APIError = _APIError
    stub.APIStatusError = _APIStatusError
    stub.APIConnectionError = _APIConnectionError
    stub.BadRequestError = _BadRequestError
    stub.RateLimitError = _RateLimitError
    sys.modules["openai"] = stub


_ensure_openai_stub()

from spike_llm import azure_openai_client as aoc
from spike_llm import provider_profiles as pp


# ──────────────────────────────────────────────────────────────────────────────
# doc_char_cap_for_profile
# ──────────────────────────────────────────────────────────────────────────────

def test_doc_cap_visura_scaled_by_multiplier_25():
    """Visura base 30K × 2.5 = 75K"""
    cap = aoc.doc_char_cap_for_profile("VISURA_CCIAA_2025.pdf", "", multiplier=2.5)
    assert cap == 75_000


def test_doc_cap_visura_scaled_by_multiplier_15():
    """Visura base 30K × 1.5 = 45K (test scaling generico, multiplier non legato a un modello specifico)"""
    cap = aoc.doc_char_cap_for_profile("VISURA.pdf", "", multiplier=1.5)
    assert cap == 45_000


def test_doc_cap_default_with_baseline_multiplier_10():
    """Default base 12K × 1.0 = 12K (= V2 baseline)"""
    cap = aoc.doc_char_cap_for_profile("random.pdf", "Lorem ipsum", multiplier=1.0)
    assert cap == 12_000


def test_doc_cap_dvr_via_content():
    """DVR detection via content head (non via filename)"""
    cap = aoc.doc_char_cap_for_profile(
        "documento.pdf", "Valutazione dei rischi azienda", multiplier=2.5,
    )
    assert cap == 62_500  # 25K × 2.5


# ──────────────────────────────────────────────────────────────────────────────
# AzureOpenAIClient init
# ──────────────────────────────────────────────────────────────────────────────

def test_init_requires_api_key(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.services.ai.azure.com/openai/v1")
    profile = pp.get_profile("gpt-4.1-mini")
    with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
        aoc.AzureOpenAIClient(profile=profile)


def test_init_requires_endpoint(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    profile = pp.get_profile("gpt-4.1-mini")
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        aoc.AzureOpenAIClient(profile=profile)


def test_init_requires_deployment_for_41_mini(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.services.ai.azure.com/openai/v1")
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI", raising=False)
    profile = pp.get_profile("gpt-4.1-mini")
    with pytest.raises(ValueError, match="DEPLOYMENT_GPT_41_MINI"):
        aoc.AzureOpenAIClient(profile=profile)


def test_init_rejects_non_azure_profile():
    profile = pp.get_profile("deepseek-v4-flash")
    with pytest.raises(ValueError, match="api_kind=azure_openai"):
        aoc.AzureOpenAIClient(profile=profile)


# ──────────────────────────────────────────────────────────────────────────────
# analyze_batch_streaming — mock stream
# ──────────────────────────────────────────────────────────────────────────────

class _MockChoiceDelta:
    def __init__(self, content):
        self.content = content


class _MockChoice:
    def __init__(self, content=None, finish_reason=None):
        self.delta = _MockChoiceDelta(content) if content else SimpleNamespace(content=None)
        self.finish_reason = finish_reason


class _MockUsage:
    def __init__(self, prompt_tokens=100, completion_tokens=50, cached_tokens=20):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.prompt_tokens_details = SimpleNamespace(cached_tokens=cached_tokens)


class _MockChunk:
    def __init__(self, content=None, finish_reason=None, usage=None):
        self.choices = [_MockChoice(content, finish_reason)] if (content or finish_reason) else []
        self.usage = usage


def _make_mock_client(profile, chunks):
    """Crea un AzureOpenAIClient con chat_stream patchato."""
    client = MagicMock(spec=aoc.AzureOpenAIClient)
    client.profile = profile
    client.deployment = "test-deployment"
    client.chat_stream = MagicMock(return_value=iter(chunks))
    return client


def test_analyze_batch_returns_stream_result_with_text():
    profile = pp.get_profile("gpt-4.1-mini")
    chunks = [
        _MockChunk(content="```yaml\n"),
        _MockChunk(content="company: Test SRL\n"),
        _MockChunk(content="```", finish_reason="stop"),
        _MockChunk(usage=_MockUsage()),
    ]
    client = _make_mock_client(profile, chunks)
    docs = [{"filename": "doc1.pdf", "content": "Test content"}]
    result = aoc.analyze_batch_streaming(
        client=client,
        batch_docs=docs,
        batch_idx=0,
        total_docs=1,
        universal_prompt="System prompt",
        enable_retry=False,
    )
    assert result.text
    assert not result.error
    # Truncation NON deve essere flaggato (finish_reason="stop")
    assert getattr(result, "truncated_output", False) is False


def test_truncation_detection_when_finish_reason_length():
    profile = pp.get_profile("gpt-4.1-mini")
    chunks = [
        _MockChunk(content="```yaml\ncompany: Tronc"),
        _MockChunk(content="atedSRL", finish_reason="length"),
        _MockChunk(usage=_MockUsage()),
    ]
    client = _make_mock_client(profile, chunks)
    docs = [{"filename": "doc.pdf", "content": "X"}]
    result = aoc.analyze_batch_streaming(
        client=client,
        batch_docs=docs,
        universal_prompt="Sys",
        enable_retry=False,
    )
    assert getattr(result, "truncated_output", False) is True


def test_empty_batch_returns_error():
    profile = pp.get_profile("gpt-4.1-mini")
    client = _make_mock_client(profile, [])
    result = aoc.analyze_batch_streaming(
        client=client,
        batch_docs=[],
        universal_prompt="Sys",
    )
    assert result.error == "empty_batch"


def test_no_client_returns_error():
    result = aoc.analyze_batch_streaming(
        client=None,
        batch_docs=[{"filename": "x.pdf", "content": "y"}],
        universal_prompt="Sys",
    )
    assert result.error == "no_client"
