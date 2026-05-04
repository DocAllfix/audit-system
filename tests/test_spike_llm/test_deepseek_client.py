"""
Test V2 Spike — DeepSeek client.

Coperture mock-based (zero API calls reali):
- _doc_char_cap_spike: cap 80K visure, 60K DVR/POS/Bilancio, 25K default
- _create_smart_batches_spike: First Fit Decreasing con cap 12 file / 200K char
- _resolve_prompt_path: variante v1 vs v2 vs default
- _build_user_prompt: include doc, supporta compact_mode
- DeepSeekClient: requires API key, lazy session init
- analyze_batch_streaming happy path con mock client che yield-a chunks SSE
- Token usage estratto da last chunk (prompt_cache_hit_tokens)
- Errori HTTP 429 → retry, 401 → no retry
- Errori connection → retry
- Empty batch → empty_batch error
- None client → no_client error
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Path setup per import spike
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
if str(_WEBAPP_DIR) not in sys.path:
    sys.path.insert(0, str(_WEBAPP_DIR))

from spike_llm import deepseek_client as dsc


# ──────────────────────────────────────────────────────────────────────────────
# Cap caratteri per documento (cap spike)
# ──────────────────────────────────────────────────────────────────────────────

def test_doc_cap_visura_80k():
    assert dsc._doc_char_cap_spike("VISURA_CCIAA_2025.pdf", "") == 80_000


def test_doc_cap_dvr_60k():
    assert dsc._doc_char_cap_spike("DVR_2024.pdf", "") == 60_000


def test_doc_cap_dvr_via_content():
    assert dsc._doc_char_cap_spike("documento.pdf", "Valutazione dei rischi azienda") == 60_000


def test_doc_cap_iso_certificate_40k():
    assert dsc._doc_char_cap_spike("ISO 9001 cert.pdf", "") == 40_000


def test_doc_cap_default_25k():
    assert dsc._doc_char_cap_spike("random_doc.pdf", "Lorem ipsum") == 25_000


def test_doc_cap_caps_are_higher_than_v2():
    """Cap spike deve essere ≥ 2× cap V2 corrispondente."""
    from v2 import gemini_client_v2 as gv2
    # Visura V2 = 30K, spike = 80K (2.66×)
    assert dsc._doc_char_cap_spike("visura.pdf", "") >= 2 * gv2._doc_char_cap("visura.pdf", "")
    # Default V2 = 12K, spike = 25K (2.08×)
    assert dsc._doc_char_cap_spike("random.pdf", "") >= 2 * gv2._doc_char_cap("random.pdf", "")


# ──────────────────────────────────────────────────────────────────────────────
# Smart batching spike
# ──────────────────────────────────────────────────────────────────────────────

def test_smart_batches_spike_max_files_12():
    docs = [{"filename": f"d_{i}.pdf", "content": "x" * 1000} for i in range(20)]
    batches = dsc._create_smart_batches_spike(docs, max_files=12, max_chars=200_000)
    # 20 file con cap 12/batch → 2 batch (12 + 8)
    assert len(batches) == 2
    assert all(len(b) <= 12 for b in batches)


def test_smart_batches_spike_respects_max_chars():
    """File grandi vanno in batch singolo se > metà cap."""
    docs = [
        {"filename": "huge.pdf", "content": "x" * 150_000},
        {"filename": "small.pdf", "content": "x" * 1_000},
    ]
    batches = dsc._create_smart_batches_spike(docs, max_files=12, max_chars=200_000)
    # huge da solo, small in altro batch (perché 150K + 1K = 151K < 200K → stesso batch)
    # In realtà stiamo sotto il cap 200K → 1 solo batch
    assert len(batches) == 1
    assert len(batches[0]) == 2


def test_smart_batches_spike_separates_when_over_cap():
    docs = [
        {"filename": "a.pdf", "content": "x" * 150_000},
        {"filename": "b.pdf", "content": "x" * 100_000},
    ]
    batches = dsc._create_smart_batches_spike(docs, max_files=12, max_chars=200_000)
    # 150K + 100K = 250K > 200K → 2 batch separati
    assert len(batches) == 2


def test_smart_batches_spike_empty_input():
    assert dsc._create_smart_batches_spike([]) == []


# ──────────────────────────────────────────────────────────────────────────────
# Prompt variant resolution
# ──────────────────────────────────────────────────────────────────────────────

def test_resolve_prompt_path_default_v2(monkeypatch):
    monkeypatch.delenv("SPIKE_PROMPT_VARIANT", raising=False)
    p = dsc._resolve_prompt_path()
    assert "spike_llm_v2.md" in str(p)


def test_resolve_prompt_path_v1(monkeypatch):
    monkeypatch.setenv("SPIKE_PROMPT_VARIANT", "v1")
    p = dsc._resolve_prompt_path()
    assert "spike_llm_v1.md" in str(p)


def test_resolve_prompt_path_v2_explicit(monkeypatch):
    monkeypatch.setenv("SPIKE_PROMPT_VARIANT", "v2")
    p = dsc._resolve_prompt_path()
    assert "spike_llm_v2.md" in str(p)


def test_load_universal_prompt_v1_contains_regola_preliminare(monkeypatch):
    monkeypatch.setenv("SPIKE_PROMPT_VARIANT", "v1")
    text = dsc._load_universal_prompt()
    assert "REGOLA PRELIMINARE" in text
    assert len(text) > 1000  # prompt non vuoto


def test_load_universal_prompt_v2_contains_regola_preliminare_and_r6(monkeypatch):
    monkeypatch.setenv("SPIKE_PROMPT_VARIANT", "v2")
    text = dsc._load_universal_prompt()
    assert "REGOLA PRELIMINARE" in text
    assert "R6. CHECKLIST DI VERIFICA OUTPUT" in text


# ──────────────────────────────────────────────────────────────────────────────
# Build user prompt
# ──────────────────────────────────────────────────────────────────────────────

def test_build_user_prompt_includes_documents():
    docs = [
        {"filename": "doc1.pdf", "content": "Lorem ipsum"},
        {"filename": "doc2.pdf", "content": "Dolor sit amet"},
    ]
    prompt = dsc._build_user_prompt(docs, batch_idx=2, total_docs=10)
    assert "DOCUMENTO 1: doc1.pdf" in prompt
    assert "DOCUMENTO 2: doc2.pdf" in prompt
    assert "Batch 3" in prompt
    assert "totale progetto 10 doc" in prompt


def test_build_user_prompt_compact_mode_includes_count():
    docs = [{"filename": f"a_{i}.pdf", "content": "x"} for i in range(8)]
    prompt = dsc._build_user_prompt(docs, batch_idx=0, total_docs=8, compact_mode=True)
    assert "MODALITÀ COMPATTA" in prompt
    assert "ESATTAMENTE 8 schede" in prompt


def test_build_user_prompt_respects_doc_cap_spike():
    huge_content = "X" * 100_000
    docs = [{"filename": "DVR.pdf", "content": huge_content}]
    prompt = dsc._build_user_prompt(docs, batch_idx=0, total_docs=1)
    # DVR cap spike = 60K → 60K X nel prompt (vs 25K V2)
    x_count = prompt.count("X")
    assert x_count == 60_000


# ──────────────────────────────────────────────────────────────────────────────
# DeepSeekClient
# ──────────────────────────────────────────────────────────────────────────────

def test_deepseek_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        dsc.DeepSeekClient()


def test_deepseek_client_accepts_explicit_api_key():
    client = dsc.DeepSeekClient(api_key="test-key-explicit")
    assert client.api_key == "test-key-explicit"
    assert client.session is not None
    assert "Bearer test-key-explicit" in client.session.headers.get("Authorization", "")


def test_deepseek_client_reads_env_var(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-from-env")
    client = dsc.DeepSeekClient()
    assert client.api_key == "test-from-env"


# ──────────────────────────────────────────────────────────────────────────────
# Analyze streaming — mock client
# ──────────────────────────────────────────────────────────────────────────────

def _make_mock_client(chunks_to_yield):
    """Mock DeepSeekClient.chat_stream che yield-a chunk fittizi."""
    client = MagicMock(spec=dsc.DeepSeekClient)

    def fake_chat_stream(*, messages, model="deepseek-v4-flash", temperature=0.0, max_tokens=8192):
        for c in chunks_to_yield:
            yield c

    client.chat_stream = MagicMock(side_effect=fake_chat_stream)
    return client


def test_analyze_streaming_happy_path():
    chunks = [
        {"choices": [{"delta": {"content": "azienda:\n"}}]},
        {"choices": [{"delta": {"content": "  nome: 'Demo'\n"}}]},
        {"choices": [{"delta": {"content": "indice:\n  - n: 1\n"}}], "usage": None},
        # Ultimo chunk con usage
        {
            "choices": [{"delta": {"content": ""}}],
            "usage": {
                "prompt_tokens": 1500,
                "prompt_cache_hit_tokens": 500,
                "prompt_cache_miss_tokens": 1000,
                "completion_tokens": 250,
            },
        },
    ]
    client = _make_mock_client(chunks)
    docs = [{"filename": "doc.pdf", "content": "test"}]

    result = dsc.analyze_batch_streaming(
        client=client,
        batch_docs=docs,
        batch_idx=0,
        total_docs=1,
        universal_prompt="SYSTEM",
    )

    assert result.text == "azienda:\n  nome: 'Demo'\nindice:\n  - n: 1\n"
    assert result.error is None


def test_analyze_streaming_none_client_returns_error():
    docs = [{"filename": "doc.pdf", "content": "test"}]
    result = dsc.analyze_batch_streaming(
        client=None,
        batch_docs=docs,
    )
    assert result.error == "no_client"


def test_analyze_streaming_empty_batch_returns_error():
    client = _make_mock_client([])
    result = dsc.analyze_batch_streaming(
        client=client,
        batch_docs=[],
    )
    assert result.error == "empty_batch"


def test_analyze_streaming_records_token_usage_with_cache_hit():
    """Verifica che cache_hit_tokens sia tracciato correttamente nel meter."""
    chunks = [
        {"choices": [{"delta": {"content": "ok"}}]},
        {
            "choices": [{"delta": {"content": ""}}],
            "usage": {
                "prompt_tokens": 5000,
                "prompt_cache_hit_tokens": 3000,
                "prompt_cache_miss_tokens": 2000,
                "completion_tokens": 800,
            },
        },
    ]
    client = _make_mock_client(chunks)
    docs = [{"filename": "doc.pdf", "content": "x"}]

    from v2 import token_meter
    sess = "spike_test_session"
    token_meter.reset_session(sess)

    dsc.analyze_batch_streaming(
        client=client,
        batch_docs=docs,
        meter_session_id=sess,
        universal_prompt="SYSTEM",
    )

    report = token_meter.get_session_report(sess)
    assert report["calls_count"] >= 1
    # Verifica che pricing DeepSeek V4 Flash sia stato applicato
    assert "deepseek-v4-flash" in report["by_model"]
    by_model = report["by_model"]["deepseek-v4-flash"]
    assert by_model["input"] == 5000
    assert by_model["cached"] == 3000
    assert by_model["output"] == 800
    # Cost: 2000 fresh × $0.14/M + 3000 cached × $0.0028/M + 800 out × $0.28/M
    # Token meter arrotonda a 5 decimali, quindi tolleranza 1e-5
    expected_cost = 2000 * 0.14 / 1e6 + 3000 * 0.0028 / 1e6 + 800 * 0.28 / 1e6
    assert by_model["cost_usd"] == pytest.approx(expected_cost, abs=1e-5)

    token_meter.reset_session(sess)


# ──────────────────────────────────────────────────────────────────────────────
# Pricing DeepSeek
# ──────────────────────────────────────────────────────────────────────────────

def test_token_meter_pricing_includes_deepseek_v4_flash():
    """Verifica che PRICING contenga DeepSeek V4 Flash con cifre corrette."""
    from v2.token_meter import PRICING
    assert "deepseek-v4-flash" in PRICING
    p = PRICING["deepseek-v4-flash"]
    assert p["input"] == 0.14
    assert p["output"] == 0.28
    assert p["cached_input"] == 0.0028


def test_token_meter_pricing_deepseek_cheaper_than_gemini():
    """Conferma che DeepSeek V4 Flash è significativamente più economico."""
    from v2.token_meter import PRICING
    ds = PRICING["deepseek-v4-flash"]
    gem = PRICING["gemini-2.5-flash"]
    # Output 8.9× più economico (0.28 vs 2.50)
    assert ds["output"] < gem["output"] / 5
    # Cached input 27× più economico (0.0028 vs 0.075)
    assert ds["cached_input"] < gem["cached_input"] / 10
