"""
Test V2 Fase 6 — schemi eventi.

Coperture:
- Tutti i 12 tipi di evento creabili con i campi minimi richiesti
- ts auto-popolato come ISO 8601 UTC
- enum serializzati come stringhe (use_enum_values=True)
- extra="ignore": campi extra non rompono
- parse_event riconosce ogni tipo via discriminator
- parse_event tollera dict malformato (None invece di eccezione)
"""
from __future__ import annotations

import re

from v2.schemas.events import (
    BaseEvent,
    DoneEvent,
    ErrorEvent,
    ErrorKind,
    EventType,
    FileDegradeEvent,
    FileDoneEvent,
    FileStartEvent,
    FileWarnEvent,
    HeartbeatEvent,
    LlmTokenEvent,
    PhaseEndEvent,
    PhaseStartEvent,
    PhaseTickEvent,
    PipelinePhase,
    SessionStartEvent,
    parse_event,
)


# ──────────────────────────────────────────────────────────────────────────────
# Timestamp
# ──────────────────────────────────────────────────────────────────────────────

def test_ts_is_iso_utc_z():
    e = SessionStartEvent(session_id="abc")
    # Format atteso: 2026-05-01T15:23:45.123456Z
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", e.ts)
    assert e.ts.endswith("Z")


# ──────────────────────────────────────────────────────────────────────────────
# Costruzione di tutti i tipi
# ──────────────────────────────────────────────────────────────────────────────

def test_session_start():
    e = SessionStartEvent(
        session_id="s1", user="DocAllfix", total_files=652, total_size_mb=381.0,
    )
    assert e.type == EventType.SESSION_START.value
    assert e.total_files == 652


def test_phase_start_tick_end():
    s = PhaseStartEvent(session_id="s", phase=PipelinePhase.INGESTION, total_items=652)
    t = PhaseTickEvent(session_id="s", phase=PipelinePhase.INGESTION, pct=0.5,
                       detail={"unzipped": 326})
    n = PhaseEndEvent(session_id="s", phase=PipelinePhase.INGESTION,
                      duration_seconds=12.4, metrics={"files": 652})
    assert s.phase == PipelinePhase.INGESTION.value
    assert t.pct == 0.5
    assert n.duration_seconds == 12.4


def test_phase_tick_clamps_pct():
    """pct fuori range viene rifiutato dal validator."""
    import pytest
    with pytest.raises(Exception):
        PhaseTickEvent(session_id="s", phase=PipelinePhase.OCR, pct=1.5)
    with pytest.raises(Exception):
        PhaseTickEvent(session_id="s", phase=PipelinePhase.OCR, pct=-0.1)


def test_file_events():
    s = FileStartEvent(session_id="s", filename="doc.pdf", size_bytes=1024,
                        strategy="text_layer")
    w = FileWarnEvent(session_id="s", filename="big.pdf", kind="large",
                       msg=">50MB")
    d = FileDegradeEvent(session_id="s", filename="x.pdf", reason="timeout",
                         fallback="fast_mode_3_pages")
    o = FileDoneEvent(session_id="s", filename="done.pdf", chars=2934,
                      method="pdfium_native_ok", success=True)
    assert s.strategy == "text_layer"
    assert w.kind == "large"
    assert d.fallback == "fast_mode_3_pages"
    assert o.chars == 2934


def test_llm_token():
    e = LlmTokenEvent(session_id="s", batch=12, chunk="...testo...")
    assert e.batch == 12
    assert e.chunk == "...testo..."


def test_error_event_with_kind():
    e = ErrorEvent(
        session_id="s", kind=ErrorKind.RESPONSE_TOO_LARGE,
        msg="Response 1MB > 400k", action="truncated_to_400000",
        detail={"batch": 64, "size": 1021244},
    )
    assert e.kind == ErrorKind.RESPONSE_TOO_LARGE.value
    assert e.action == "truncated_to_400000"
    assert e.detail["batch"] == 64


def test_heartbeat():
    e = HeartbeatEvent(session_id="s", pid=1234, rss_mb=125.5,
                       queue_depth=12, workers_busy=5)
    assert e.pid == 1234
    assert e.rss_mb == 125.5


def test_done_event():
    e = DoneEvent(
        session_id="s", output_filename="audit.docx",
        company_name="Demo SRL", duration_seconds=180.5,
        stats={"total_docs": 200, "tokens": 250000},
    )
    assert e.output_filename == "audit.docx"
    assert e.duration_seconds == 180.5


# ──────────────────────────────────────────────────────────────────────────────
# extra="ignore"
# ──────────────────────────────────────────────────────────────────────────────

def test_extra_fields_ignored():
    """Campi extra non documentati non rompono."""
    e = SessionStartEvent(
        session_id="s", total_files=10,
        campo_inventato="nuovo",  # type: ignore
    )
    assert e.total_files == 10
    assert not hasattr(e, "campo_inventato")


# ──────────────────────────────────────────────────────────────────────────────
# parse_event
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_event_dispatches_correctly():
    """parse_event seleziona la classe giusta in base a `type`."""
    raw = {
        "type": "phase.start",
        "session_id": "abc",
        "phase": "ingestion",
        "total_items": 100,
    }
    parsed = parse_event(raw)
    assert isinstance(parsed, PhaseStartEvent)
    assert parsed.phase == PipelinePhase.INGESTION.value
    assert parsed.total_items == 100


def test_parse_event_returns_none_on_unknown_type():
    """Tipo non riconosciuto → None."""
    raw = {"type": "tipo.inesistente", "session_id": "x"}
    assert parse_event(raw) is None


def test_parse_event_returns_none_on_malformed_input():
    assert parse_event(None) is None  # type: ignore
    assert parse_event("not a dict") is None  # type: ignore
    assert parse_event({}) is None
    assert parse_event({"no_type": "field"}) is None


def test_parse_event_returns_none_on_bad_payload():
    """Dict con type valido ma payload sbagliato → None (mai eccezione)."""
    raw = {
        "type": "phase.tick",
        "session_id": "s",
        "phase": "ingestion",
        "pct": "non un numero",  # invalido
    }
    parsed = parse_event(raw)
    assert parsed is None


# ──────────────────────────────────────────────────────────────────────────────
# Serializzazione → JSON-friendly
# ──────────────────────────────────────────────────────────────────────────────

def test_model_dump_json_roundtrip():
    """Roundtrip: model → JSON → parse → stesso model."""
    import json

    original = ErrorEvent(
        session_id="abc",
        kind=ErrorKind.NETWORK,
        msg="connection reset",
    )
    j = original.model_dump_json()
    raw = json.loads(j)
    parsed = parse_event(raw)
    assert isinstance(parsed, ErrorEvent)
    assert parsed.kind == ErrorKind.NETWORK.value
    assert parsed.msg == "connection reset"
