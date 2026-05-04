"""
Test V2 Fase 6 — sse_emitter.

Coperture:
- Helper tipizzati popolano session_id automaticamente
- Eventi vengono persisted via store + pushati in queue
- Throttling: drop dei tick eccedenti il rate limit
- NEVER_DROP_TYPES: error/heartbeat/done passano sempre
- Stats riportano dropped_count e dropped_by_type
- serialize_for_sse produce stringa nel formato corretto
- Queue opzionale (None) → solo persistenza, no eccezione
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from v2.progress_store import ProgressStore
from v2.schemas.events import ErrorKind, EventType, PipelinePhase
from v2.sse_emitter import SSEEmitter


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_emitter(tmp_path, session_id="sess1", events_per_sec=5, with_queue=True):
    """Crea SSEEmitter isolato sul tmp_path."""
    store = ProgressStore(session_id, base_dir=tmp_path)
    queue = None
    loop = None
    if with_queue:
        loop = asyncio.new_event_loop()
        # Crea queue dentro il loop (richiesto da asyncio)
        queue = asyncio.Queue()
    emitter = SSEEmitter(
        session_id=session_id,
        store=store,
        queue=queue,
        loop=loop,
        events_per_sec=events_per_sec,
    )
    return emitter, store, queue, loop


# ──────────────────────────────────────────────────────────────────────────────
# Helper tipizzati
# ──────────────────────────────────────────────────────────────────────────────

def test_emit_session_start_persisted(tmp_path):
    emitter, store, _, _ = _make_emitter(tmp_path, with_queue=False)
    ok = emitter.emit_session_start(total_files=100, total_size_mb=50.0)
    assert ok is True
    events = store.replay()
    assert len(events) == 1
    assert events[0]["type"] == EventType.SESSION_START.value
    assert events[0]["session_id"] == "sess1"
    assert events[0]["total_files"] == 100


def test_emit_phase_helpers(tmp_path):
    emitter, store, _, _ = _make_emitter(tmp_path, with_queue=False)
    emitter.emit_phase_start(PipelinePhase.INGESTION, total_items=652)
    emitter.emit_phase_tick(PipelinePhase.INGESTION, 0.3, detail={"unzipped": 200})
    emitter.emit_phase_end(PipelinePhase.INGESTION, duration_seconds=12.4)

    events = store.replay()
    assert len(events) == 3
    assert events[0]["type"] == EventType.PHASE_START.value
    assert events[1]["pct"] == 0.3
    assert events[2]["duration_seconds"] == 12.4


def test_emit_file_helpers(tmp_path):
    emitter, store, _, _ = _make_emitter(tmp_path, with_queue=False)
    emitter.emit_file_start("doc.pdf", size_bytes=1024, strategy="text_layer")
    emitter.emit_file_warn("big.pdf", kind="large", msg=">50MB")
    emitter.emit_file_degrade("zombie.pdf", reason="timeout", fallback="fast_mode")
    emitter.emit_file_done("done.pdf", chars=2934, method="pdfium_native_ok")

    events = store.replay()
    assert len(events) == 4
    assert events[0]["filename"] == "doc.pdf"
    assert events[1]["kind"] == "large"
    assert events[2]["fallback"] == "fast_mode"
    assert events[3]["chars"] == 2934


def test_emit_error_with_kind(tmp_path):
    emitter, store, _, _ = _make_emitter(tmp_path, with_queue=False)
    emitter.emit_error(
        ErrorKind.RESPONSE_TOO_LARGE,
        "Response 1MB > 400k",
        action="truncated_to_400000",
        detail={"batch": 64},
    )
    events = store.replay()
    assert events[0]["type"] == EventType.ERROR.value
    assert events[0]["kind"] == ErrorKind.RESPONSE_TOO_LARGE.value
    assert events[0]["action"] == "truncated_to_400000"


def test_emit_heartbeat_and_done(tmp_path):
    emitter, store, _, _ = _make_emitter(tmp_path, with_queue=False)
    emitter.emit_heartbeat(pid=1234, rss_mb=125.5, queue_depth=12)
    emitter.emit_done(output_filename="audit.docx", duration_seconds=180.5)
    events = store.replay()
    assert events[0]["type"] == EventType.HEARTBEAT.value
    assert events[0]["pid"] == 1234
    assert events[1]["type"] == EventType.DONE.value


# ──────────────────────────────────────────────────────────────────────────────
# session_id auto-popolato
# ──────────────────────────────────────────────────────────────────────────────

def test_session_id_overridden_to_emitter_value(tmp_path):
    """Anche se l'evento ha un session_id diverso, l'emitter forza il proprio."""
    emitter, store, _, _ = _make_emitter(tmp_path, session_id="canonical", with_queue=False)
    # Costruiamo un evento con session_id "fake" — l'emitter dovrebbe sovrascriverlo
    from v2.schemas.events import SessionStartEvent
    fake = SessionStartEvent(session_id="fake", total_files=1)
    emitter.emit(fake)

    events = store.replay()
    assert events[0]["session_id"] == "canonical"


# ──────────────────────────────────────────────────────────────────────────────
# Throttling
# ──────────────────────────────────────────────────────────────────────────────

def test_throttling_drops_tick_events(tmp_path):
    """Oltre rate limit, i phase.tick vengono droppati."""
    emitter, store, _, _ = _make_emitter(
        tmp_path, events_per_sec=3, with_queue=False
    )

    # Emettiamo 10 tick rapidamente: solo i primi 3 passano
    accepted = 0
    for i in range(10):
        if emitter.emit_phase_tick(PipelinePhase.OCR, pct=i / 10):
            accepted += 1

    assert accepted == 3
    stats = emitter.stats()
    assert stats["dropped_count"] == 7
    assert stats["dropped_by_type"][EventType.PHASE_TICK.value] == 7


def test_never_drop_types_pass_always(tmp_path):
    """error/heartbeat/done/session.start passano sempre."""
    emitter, store, _, _ = _make_emitter(tmp_path, events_per_sec=1, with_queue=False)
    # Saturiamo il rate con 1 tick
    emitter.emit_phase_tick(PipelinePhase.OCR, pct=0.1)
    # Ora gli eventi NEVER_DROP_TYPES devono comunque passare
    assert emitter.emit_session_start(total_files=10) is True
    assert emitter.emit_error(ErrorKind.NETWORK, "test") is True
    assert emitter.emit_heartbeat(pid=1) is True
    assert emitter.emit_phase_start(PipelinePhase.INGESTION) is True
    assert emitter.emit_phase_end(PipelinePhase.INGESTION) is True
    assert emitter.emit_file_warn("x.pdf", "large") is True
    assert emitter.emit_done() is True


def test_throttling_window_resets_after_1s(tmp_path):
    emitter, store, _, _ = _make_emitter(
        tmp_path, events_per_sec=2, with_queue=False
    )
    # Emetti 5: i primi 2 passano, gli altri droppati
    for i in range(5):
        emitter.emit_phase_tick(PipelinePhase.OCR, pct=i / 5)
    assert emitter.stats()["dropped_count"] == 3

    # Aspetta che la finestra di 1s scada
    time.sleep(1.1)
    # Ora 1 nuovo tick deve passare
    assert emitter.emit_phase_tick(PipelinePhase.OCR, pct=0.99) is True


# ──────────────────────────────────────────────────────────────────────────────
# Queue (con event loop)
# ──────────────────────────────────────────────────────────────────────────────

def test_emitter_pushes_to_queue(tmp_path):
    """L'emitter mette gli eventi in queue per consumer SSE."""
    loop = asyncio.new_event_loop()

    async def run_test():
        queue = asyncio.Queue()
        store = ProgressStore("qtest", base_dir=tmp_path)
        emitter = SSEEmitter(
            session_id="qtest", store=store, queue=queue,
            loop=asyncio.get_event_loop(),
        )

        # Esegui emit dal loop principale (simulando producer in main thread)
        # Per simulare worker thread esterno useremmo run_in_executor;
        # qui sufficiente verificare il push diretto
        emitter.emit_session_start(total_files=5)

        # Drena la queue (concedi tempo al run_coroutine_threadsafe di completare)
        await asyncio.sleep(0.05)
        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
        return msg

    try:
        msg = loop.run_until_complete(run_test())
        assert msg["type"] == EventType.SESSION_START.value
    finally:
        loop.close()


def test_emitter_without_queue_only_persists(tmp_path):
    """Se queue=None, l'emitter persisty solo (no eccezione)."""
    emitter, store, _, _ = _make_emitter(tmp_path, with_queue=False)
    assert emitter.emit_session_start(total_files=1) is True
    assert store.event_count() == 1


# ──────────────────────────────────────────────────────────────────────────────
# SSE serialization
# ──────────────────────────────────────────────────────────────────────────────

def test_serialize_for_sse_format():
    payload = {"type": "phase.tick", "pct": 0.5}
    line = SSEEmitter.serialize_for_sse(payload)
    assert line.startswith("data: ")
    assert line.endswith("\n\n")
    # Roundtrip JSON valido
    json_part = line[len("data: ") : -len("\n\n")]
    parsed = json.loads(json_part)
    assert parsed["type"] == "phase.tick"


def test_serialize_handles_unicode():
    """Caratteri italiani non ASCII passano correttamente."""
    payload = {"type": "error", "msg": "Errore: àèìòù €"}
    line = SSEEmitter.serialize_for_sse(payload)
    assert "àèìòù" in line


def test_serialize_handles_empty_payload():
    """Edge case: dict vuoto → stringa data: {}\\n\\n valida."""
    line = SSEEmitter.serialize_for_sse({})
    assert line == "data: {}\n\n"


# ──────────────────────────────────────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────────────────────────────────────

def test_stats_shape(tmp_path):
    emitter, _, _, _ = _make_emitter(tmp_path, events_per_sec=2, with_queue=False)
    for _ in range(5):
        emitter.emit_phase_tick(PipelinePhase.OCR, pct=0.5)
    s = emitter.stats()
    assert "session_id" in s
    assert "dropped_count" in s
    assert "dropped_by_type" in s
    assert s["events_per_sec_limit"] == 2
