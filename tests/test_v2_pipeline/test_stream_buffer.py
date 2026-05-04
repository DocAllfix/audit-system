"""
Test V2 Fase 5 — stream_buffer.

Coperture:
- Append text/chunk basico, contatore chunks
- Cap 400k chars: troncamento esatto al limite + flag `truncated`
- Una volta truncato, scartiamo silenziosamente i chunk successivi
- Chunk vuoti non incrementano chars ma sì chunks_count
- Estrazione testo da chunk con .text, .candidates, e da stringa
- Cancellazione cooperativa via abort()
- Callback on_chunk invocato con il delta giusto
- Errori nel callback non propagati al producer
- Tag di troncamento aggiunto al text finale solo se truncated
- Slow consumer detection
- finalize() con error → flag partial
"""
from __future__ import annotations

from unittest.mock import MagicMock

from v2 import stream_buffer as sb


# ──────────────────────────────────────────────────────────────────────────────
# Append basico
# ──────────────────────────────────────────────────────────────────────────────

def test_append_text_accumulates():
    buf = sb.StreamBuffer(max_chars=1000)
    assert buf.append_text("hello ") is True
    assert buf.append_text("world") is True
    result = buf.finalize()
    assert result.text == "hello world"
    assert result.truncated is False
    assert result.partial is False


def test_chunks_count_includes_empty_chunks():
    buf = sb.StreamBuffer(max_chars=1000)
    buf.append_chunk("data")
    buf.append_chunk("")  # vuoto
    buf.append_chunk("more")
    result = buf.finalize()
    assert result.chunks_count == 3
    assert result.text == "datamore"


# ──────────────────────────────────────────────────────────────────────────────
# Cap 400k → troncamento
# ──────────────────────────────────────────────────────────────────────────────

def test_cap_truncates_at_exact_limit():
    buf = sb.StreamBuffer(max_chars=100)
    buf.append_text("A" * 80)
    can_continue = buf.append_text("B" * 50)  # supererebbe → tronca a 20
    assert can_continue is False

    result = buf.finalize()
    assert result.truncated is True
    # Il text contiene esattamente 100 char + il tag di troncamento
    assert result.text.startswith("A" * 80 + "B" * 20)
    assert sb.TRUNCATION_TAG in result.text


def test_cap_silent_drop_after_truncation():
    """Una volta truncato, chunk successivi sono scartati silenziosamente."""
    buf = sb.StreamBuffer(max_chars=10)
    buf.append_text("0123456789X")  # >10 → tronca a 10
    assert buf.truncated is True
    # Append successivi non aggiungono nulla
    buf.append_text("ignored")
    buf.append_text("also ignored")
    result = buf.finalize()
    # Solo i primi 10 char + tag
    assert result.text.startswith("0123456789")
    assert "ignored" not in result.text


def test_chars_property_tracks_accumulated():
    buf = sb.StreamBuffer(max_chars=1000)
    buf.append_text("12345")
    assert buf.chars == 5
    buf.append_text("67890")
    assert buf.chars == 10


# ──────────────────────────────────────────────────────────────────────────────
# Estrazione testo dai chunk SDK
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_text_from_string():
    assert sb.StreamBuffer._extract_text_from_chunk("plain string") == "plain string"


def test_extract_text_from_text_attr():
    chunk = MagicMock()
    chunk.text = "from text attr"
    chunk.candidates = None
    assert sb.StreamBuffer._extract_text_from_chunk(chunk) == "from text attr"


def test_extract_text_from_candidates_parts():
    """Caso fallback: chunk con candidates[0].content.parts[*].text."""
    chunk = MagicMock()
    chunk.text = None
    part1 = MagicMock()
    part1.text = "Part1 "
    part2 = MagicMock()
    part2.text = "Part2"
    cand = MagicMock()
    cand.content.parts = [part1, part2]
    chunk.candidates = [cand]
    assert sb.StreamBuffer._extract_text_from_chunk(chunk) == "Part1 Part2"


def test_extract_text_returns_empty_for_unknown_format():
    chunk = MagicMock()
    chunk.text = None
    chunk.candidates = None
    assert sb.StreamBuffer._extract_text_from_chunk(chunk) == ""


# ──────────────────────────────────────────────────────────────────────────────
# Abort cooperativo
# ──────────────────────────────────────────────────────────────────────────────

def test_abort_blocks_further_appends():
    buf = sb.StreamBuffer(max_chars=1000)
    buf.append_text("before")
    buf.abort()
    can_continue = buf.append_text("after")
    assert can_continue is False
    result = buf.finalize()
    assert result.text == "before"
    assert result.aborted is True
    assert result.partial is True


# ──────────────────────────────────────────────────────────────────────────────
# Callback on_chunk
# ──────────────────────────────────────────────────────────────────────────────

def test_on_chunk_callback_receives_deltas():
    deltas = []
    buf = sb.StreamBuffer(max_chars=1000, on_chunk=lambda t: deltas.append(t))
    buf.append_text("aaa")
    buf.append_text("bbb")
    assert deltas == ["aaa", "bbb"]


def test_on_chunk_exceptions_silenced():
    """Errori nel callback non interrompono il producer."""
    def evil_callback(text):
        raise RuntimeError("explosion")

    buf = sb.StreamBuffer(max_chars=1000, on_chunk=evil_callback)
    # Non deve sollevare
    assert buf.append_text("ok") is True
    assert buf.chars == 2


def test_on_chunk_receives_truncated_text():
    """Anche quando troncato, il callback riceve solo i char effettivamente accumulati."""
    deltas = []
    buf = sb.StreamBuffer(max_chars=10, on_chunk=lambda t: deltas.append(t))
    buf.append_text("hello world!")  # 12 char → tronca a 10

    # Il callback ha ricevuto "hello worl" (10 char), non "hello world!"
    assert deltas == ["hello worl"]


# ──────────────────────────────────────────────────────────────────────────────
# Slow consumer
# ──────────────────────────────────────────────────────────────────────────────

def test_slow_consumer_property():
    buf = sb.StreamBuffer(max_chars=1_000_000)
    assert buf.is_slow_consumer is False
    buf.append_text("X" * (sb.SLOW_CONSUMER_WARN_CHARS + 10))
    assert buf.is_slow_consumer is True


# ──────────────────────────────────────────────────────────────────────────────
# Finalize
# ──────────────────────────────────────────────────────────────────────────────

def test_finalize_with_error_marks_partial():
    buf = sb.StreamBuffer(max_chars=1000)
    buf.append_text("partial data")
    result = buf.finalize(error="connection reset")
    assert result.partial is True
    assert result.error == "connection reset"
    assert result.text == "partial data"
    assert result.truncated is False


def test_finalize_clean_no_truncation_tag():
    """Output sotto cap non ha il tag di troncamento."""
    buf = sb.StreamBuffer(max_chars=1000)
    buf.append_text("clean output")
    result = buf.finalize()
    assert sb.TRUNCATION_TAG not in result.text


def test_finalize_includes_duration():
    buf = sb.StreamBuffer(max_chars=1000)
    buf.append_text("x")
    result = buf.finalize()
    assert result.duration_seconds >= 0.0
