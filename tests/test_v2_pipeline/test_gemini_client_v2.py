"""
Test V2 Fase 5 — gemini_client_v2 (analyze_batch_streaming).

Coperture:
- _doc_char_cap: visure 30k, DVR 25k, default 12k
- _sanitize_text rimuove caratteri di controllo
- _build_user_prompt produce stringa con DOCUMENTO N
- analyze_batch_streaming happy path con mock stream
- on_token e on_marker invocati durante streaming
- Cap raggiunto → result.truncated=True + tag
- Stream interrotto da errore retryable → 1 retry
- Errore non-retryable → fail subito senza retry
- Empty batch → ritorna empty result
- None client → ritorna error
- cached_content_id passato a config quando fornito
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from v2 import gemini_client_v2 as gc2


# ──────────────────────────────────────────────────────────────────────────────
# _doc_char_cap
# ──────────────────────────────────────────────────────────────────────────────

def test_doc_cap_visura_via_filename():
    assert gc2._doc_char_cap("VISURA_CCIAA_2025.pdf", "") == 30000


def test_doc_cap_dvr_via_filename():
    assert gc2._doc_char_cap("DVR rev 05.pdf", "") == 25000


def test_doc_cap_dvr_via_content():
    assert gc2._doc_char_cap("documento.pdf", "Valutazione dei rischi aziendali") == 25000


def test_doc_cap_default():
    assert gc2._doc_char_cap("random_file.pdf", "Lorem ipsum") == 12000


def test_doc_cap_iso_certificate():
    assert gc2._doc_char_cap("ISO 9001 certificato.pdf", "") == 18000


# ──────────────────────────────────────────────────────────────────────────────
# Sanitize
# ──────────────────────────────────────────────────────────────────────────────

def test_sanitize_removes_control_chars():
    text = "ok\x00line\x01\x02other"
    result = gc2._sanitize_text(text)
    assert "\x00" not in result
    assert "\x01" not in result


def test_sanitize_normalizes_newlines():
    text = "a\r\nb\rc"
    assert gc2._sanitize_text(text) == "a\nb\nc"


def test_sanitize_empty_string():
    assert gc2._sanitize_text("") == ""
    assert gc2._sanitize_text(None) == ""


# ──────────────────────────────────────────────────────────────────────────────
# Build user prompt
# ──────────────────────────────────────────────────────────────────────────────

def test_build_user_prompt_includes_documents():
    docs = [
        {"filename": "doc1.pdf", "content": "Lorem ipsum"},
        {"filename": "doc2.pdf", "content": "Dolor sit amet"},
    ]
    prompt = gc2._build_user_prompt(docs, batch_idx=2, total_docs=10)
    assert "DOCUMENTO 1: doc1.pdf" in prompt
    assert "DOCUMENTO 2: doc2.pdf" in prompt
    assert "Lorem ipsum" in prompt
    assert "Batch 3" in prompt  # batch_idx+1
    assert "totale progetto 10 doc" in prompt


def test_build_user_prompt_respects_doc_cap():
    huge_content = "X" * 50000
    docs = [{"filename": "DVR.pdf", "content": huge_content}]
    prompt = gc2._build_user_prompt(docs, batch_idx=0, total_docs=1)
    # DVR cap = 25000, quindi non deve apparire 50000 X
    x_count = prompt.count("X")
    assert x_count == 25000


def test_build_user_prompt_compact_mode_off_by_default():
    """Senza compact_mode, niente direttiva 'MODALITÀ COMPATTA' nel prompt."""
    docs = [{"filename": "doc.pdf", "content": "x"}]
    prompt = gc2._build_user_prompt(docs, batch_idx=0, total_docs=1)
    assert "MODALITÀ COMPATTA" not in prompt
    assert "Tier MINIMO" not in prompt


def test_build_user_prompt_compact_mode_on_adds_directive():
    """Con compact_mode=True, la direttiva tier MINIMO è prepended."""
    docs = [
        {"filename": "Attestato_1.pdf", "content": "x"},
        {"filename": "Attestato_2.pdf", "content": "y"},
    ]
    prompt = gc2._build_user_prompt(
        docs, batch_idx=0, total_docs=2, compact_mode=True,
    )
    assert "MODALITÀ COMPATTA" in prompt
    assert "Tier MINIMO" in prompt
    # Regola 2.7 inderogabile sempre richiamata
    assert "Regola 2.7" in prompt
    # I documenti restano nel prompt (1 file = 1 scheda)
    assert "Attestato_1.pdf" in prompt
    assert "Attestato_2.pdf" in prompt


def test_build_user_prompt_compact_mode_mentions_aggregation_table():
    """compact_mode richiama la Regola 2.6 per ≥3 documenti omogenei."""
    docs = [{"filename": f"a_{i}.pdf", "content": "x"} for i in range(3)]
    prompt = gc2._build_user_prompt(
        docs, batch_idx=0, total_docs=3, compact_mode=True,
    )
    assert "Regola 2.6" in prompt
    assert "tabella" in prompt.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Leva 4 — model mix
# ──────────────────────────────────────────────────────────────────────────────

def test_constants_define_lite_model_and_cache_capability_set():
    """ANALYZE_MODEL_LITE esiste e _MODELS_WITH_CACHE è coerente."""
    assert gc2.ANALYZE_MODEL_LITE == "gemini-2.5-flash-lite"
    assert "gemini-2.5-flash" in gc2._MODELS_WITH_CACHE
    # Lite NON supporta caching
    assert "gemini-2.5-flash-lite" not in gc2._MODELS_WITH_CACHE


# ──────────────────────────────────────────────────────────────────────────────
# Mock streaming helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_streaming_client(text_chunks):
    """Mock client la cui generate_content_stream yield-a chunks fittizi."""
    mock = MagicMock()

    def fake_stream(*, model, contents, config):
        for t in text_chunks:
            chunk = MagicMock()
            chunk.text = t
            chunk.candidates = None
            yield chunk

    mock.models = MagicMock()
    mock.models.generate_content_stream = MagicMock(side_effect=fake_stream)
    return mock


# ──────────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────────

def test_streaming_happy_path():
    chunks = ["azienda:\n", "  nome: 'Demo'\n", "indice:\n  - n: 1\n"]
    client = _make_streaming_client(chunks)
    docs = [{"filename": "doc.pdf", "content": "test"}]

    tokens_received = []
    markers_received = []

    result = gc2.analyze_batch_streaming(
        client=client,
        batch_docs=docs,
        batch_idx=0,
        total_docs=1,
        universal_prompt="SYSTEM",
        on_token=lambda t: tokens_received.append(t),
        on_marker=lambda m: markers_received.append(m),
    )

    assert result.text == "azienda:\n  nome: 'Demo'\nindice:\n  - n: 1\n"
    assert result.truncated is False
    assert result.partial is False
    assert result.aborted is False
    assert result.error is None
    assert result.chunks_count == 3

    # Tokens emessi via callback
    assert tokens_received == chunks

    # Almeno un marker (azienda + indice)
    kinds = [m.kind for m in markers_received]
    assert "meta_azienda" in kinds


def test_streaming_passes_cached_content_to_config():
    """Quando cached_content_id è fornito, viene passato in config."""
    client = _make_streaming_client(["chunk"])
    docs = [{"filename": "x.pdf", "content": "y"}]

    gc2.analyze_batch_streaming(
        client=client,
        batch_docs=docs,
        cached_content_id="cachedContents/abc",
    )

    # Verifica che generate_content_stream sia stata chiamata con config che ha cached_content
    call = client.models.generate_content_stream.call_args
    config = call.kwargs.get("config")
    assert getattr(config, "cached_content", None) == "cachedContents/abc"


def test_streaming_uses_system_instruction_when_no_cache():
    """Senza cached_content_id, il prompt va in system_instruction."""
    client = _make_streaming_client(["x"])
    docs = [{"filename": "x.pdf", "content": "y"}]

    gc2.analyze_batch_streaming(
        client=client,
        batch_docs=docs,
        universal_prompt="SYSTEM PROMPT TEXT",
        cached_content_id=None,
    )

    call = client.models.generate_content_stream.call_args
    config = call.kwargs.get("config")
    assert config.system_instruction == "SYSTEM PROMPT TEXT"
    assert getattr(config, "cached_content", None) is None


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────────

def test_none_client_returns_error():
    result = gc2.analyze_batch_streaming(
        client=None,
        batch_docs=[{"filename": "x.pdf", "content": "y"}],
    )
    assert result.error == "no_client"
    assert result.text == ""


def test_empty_batch_returns_error():
    client = _make_streaming_client(["x"])
    result = gc2.analyze_batch_streaming(client=client, batch_docs=[])
    assert result.error == "empty_batch"
    # Mai chiamato lo stream
    client.models.generate_content_stream.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Cap 400k → truncated
# ──────────────────────────────────────────────────────────────────────────────

def test_cap_truncates_huge_response():
    # Genera N chunks da 100k char → totale ~500k > cap 400k
    big = "Y" * 100_000
    chunks = [big] * 5
    client = _make_streaming_client(chunks)
    docs = [{"filename": "x.pdf", "content": "y"}]

    result = gc2.analyze_batch_streaming(
        client=client,
        batch_docs=docs,
        max_chars=400_000,
    )

    assert result.truncated is True
    # Approssimativamente 400k + tag, non 500k
    assert len(result.text) <= 410_000


# ──────────────────────────────────────────────────────────────────────────────
# Errori e retry
# ──────────────────────────────────────────────────────────────────────────────

def test_retryable_error_then_success(monkeypatch):
    """Primo tentativo: 503 transient. Secondo: success."""
    monkeypatch.setattr(gc2.time, "sleep", lambda s: None)

    call_count = {"i": 0}

    def stream_factory(*, model, contents, config):
        call_count["i"] += 1
        if call_count["i"] == 1:
            raise RuntimeError("503 service unavailable")
        # Secondo tentativo: stream OK
        chunk = MagicMock()
        chunk.text = "recovered"
        chunk.candidates = None
        yield chunk

    client = MagicMock()
    client.models = MagicMock()
    client.models.generate_content_stream = MagicMock(side_effect=stream_factory)

    result = gc2.analyze_batch_streaming(
        client=client,
        batch_docs=[{"filename": "x.pdf", "content": "y"}],
        enable_retry=True,
    )
    assert result.text == "recovered"
    assert result.error is None
    assert call_count["i"] == 2


def test_non_retryable_error_no_retry(monkeypatch):
    """Errore tipo 401 (auth) non scatena retry."""
    monkeypatch.setattr(gc2.time, "sleep", lambda s: None)

    call_count = {"i": 0}

    def stream_factory(*, model, contents, config):
        call_count["i"] += 1
        raise RuntimeError("401 unauthorized")
        yield  # mai raggiunto

    client = MagicMock()
    client.models = MagicMock()
    client.models.generate_content_stream = MagicMock(side_effect=stream_factory)

    result = gc2.analyze_batch_streaming(
        client=client,
        batch_docs=[{"filename": "x.pdf", "content": "y"}],
        enable_retry=True,
    )
    assert result.error is not None
    assert "stream_error" in result.error or "401" in result.error
    # Solo 1 chiamata, niente retry
    assert call_count["i"] == 1


def test_all_retries_fail(monkeypatch):
    """Errore retryable persistente → tutti retry esauriti, ritorna parziale."""
    monkeypatch.setattr(gc2.time, "sleep", lambda s: None)

    def stream_factory(*, model, contents, config):
        raise RuntimeError("503 unavailable")
        yield

    client = MagicMock()
    client.models = MagicMock()
    client.models.generate_content_stream = MagicMock(side_effect=stream_factory)

    result = gc2.analyze_batch_streaming(
        client=client,
        batch_docs=[{"filename": "x.pdf", "content": "y"}],
        enable_retry=True,
    )
    assert result.error is not None
    assert "all_retries_failed" in result.error or "503" in result.error


# ──────────────────────────────────────────────────────────────────────────────
# Determinismo
# ──────────────────────────────────────────────────────────────────────────────

def test_streaming_uses_temperature_zero_and_seed():
    """Verifica che la config passata abbia temperature=0, seed=42."""
    client = _make_streaming_client(["x"])
    gc2.analyze_batch_streaming(
        client=client,
        batch_docs=[{"filename": "x.pdf", "content": "y"}],
    )
    call = client.models.generate_content_stream.call_args
    config = call.kwargs["config"]
    assert config.temperature == 0.0
    assert config.seed == 42
    assert config.top_p == 1.0
