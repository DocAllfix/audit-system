"""
V2 — SSE Emitter (Fase 6).

Emette eventi tipizzati verso:
1. Una queue asincrona (per il consumer SSE)
2. ProgressStore JSONL (per resume post-crash)

Caratteristiche:
- Single writer pattern: l'emitter è l'UNICO writer di eventi della pipeline
- Thread-safe: lock interno consente uso da watchdog + main thread + worker
- Throttling: max EVENTS_PER_SEC eventi/sec, drop dei `phase.tick` se in eccesso
- Eventi mai droppabili: error, heartbeat, done, session.start, phase.start/end
- Backpressure: se la queue è piena (slow consumer), drop dei tick non critici
- Encoding SSE: linee `data: <json>\n\n` pronte per StreamingResponse

API:
    emitter = SSEEmitter(session_id, store=ProgressStore(...), queue=asyncio.Queue())
    emitter.emit_session_start(...)
    emitter.emit_phase_tick(phase, pct)
    emitter.emit_error(kind, msg, action=...)
    ...
    sse_text = emitter.serialize_for_sse(event_dict)
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Dict, List, Optional

from v2.progress_store import ProgressStore
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
)


# ──────────────────────────────────────────────────────────────────────────────
# Throttling
# ──────────────────────────────────────────────────────────────────────────────

# Max eventi/sec verso il client (rate limiter sliding window)
EVENTS_PER_SEC = 5

# Tipi che NON vengono mai droppati (anche con queue piena o rate exceeded)
NEVER_DROP_TYPES = {
    EventType.SESSION_START.value,
    EventType.PHASE_START.value,
    EventType.PHASE_END.value,
    EventType.ERROR.value,
    EventType.HEARTBEAT.value,
    EventType.DONE.value,
    EventType.FILE_WARN.value,
    EventType.FILE_DEGRADE.value,
}


# ──────────────────────────────────────────────────────────────────────────────
# Emitter
# ──────────────────────────────────────────────────────────────────────────────

class SSEEmitter:
    """
    Emette eventi tipizzati verso queue + persist store.

    Uso tipico (dentro endpoint FastAPI SSE):
        store = ProgressStore(session_id)
        queue = asyncio.Queue()
        loop = asyncio.get_event_loop()
        emitter = SSEEmitter(session_id, store=store, queue=queue, loop=loop)

        # Da qualunque thread:
        emitter.emit_phase_start(PipelinePhase.INGESTION, total_items=652)

        # Nel handler async:
        async for sse_chunk in emitter.consume():
            yield sse_chunk
    """

    def __init__(
        self,
        session_id: str,
        store: Optional[ProgressStore] = None,
        queue: Optional[asyncio.Queue] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        events_per_sec: int = EVENTS_PER_SEC,
    ):
        self.session_id = session_id
        self.store = store or ProgressStore(session_id)
        self.queue = queue
        self.loop = loop
        self._lock = threading.Lock()
        self._events_per_sec = events_per_sec
        self._recent_emit_times: List[float] = []
        self._dropped_count = 0
        self._dropped_by_type: Dict[str, int] = {}

    # ──────────────────────────────────────────────────────────────────────
    # Core: emit() generico
    # ──────────────────────────────────────────────────────────────────────

    def emit(self, event: BaseEvent) -> bool:
        """
        Emette un evento: persistenza disco + queue SSE.

        Returns:
            True se l'evento è stato emesso (sia su disco che queue).
            False se la queue era piena E il tipo è droppable.
        """
        # Forza session_id corretto (anti-mistake)
        try:
            payload = event.model_dump(mode="json")
            payload["session_id"] = self.session_id
        except Exception as e:
            print(f"[V2 SSE] Serializzazione evento fallita: {e}")
            return False

        with self._lock:
            event_type = payload.get("type", "")

            # Throttling: rate limit sliding window
            if event_type not in NEVER_DROP_TYPES:
                if not self._can_emit_now():
                    self._dropped_count += 1
                    self._dropped_by_type[event_type] = (
                        self._dropped_by_type.get(event_type, 0) + 1
                    )
                    return False

            # Persistenza su disco (sempre, anche per gli eventi droppabili
            # se passano il rate limit — vogliamo audit trail completo).
            self.store.append(payload)

            # Push verso queue async (best effort; se fail e tipo droppable, OK)
            self._push_to_queue(payload, event_type)

            # Track timestamp per rate limiter (solo se non droppato)
            self._recent_emit_times.append(time.monotonic())
            return True

    def _can_emit_now(self) -> bool:
        """Sliding window 1s. Se eventi recenti >= EVENTS_PER_SEC → drop."""
        now = time.monotonic()
        cutoff = now - 1.0
        # Rimuovi timestamps vecchi > 1s
        self._recent_emit_times = [t for t in self._recent_emit_times if t >= cutoff]
        return len(self._recent_emit_times) < self._events_per_sec

    def _push_to_queue(self, payload: Dict[str, Any], event_type: str) -> None:
        """Push thread-safe verso asyncio.Queue."""
        if self.queue is None or self.loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.queue.put(payload), self.loop
            )
        except Exception as e:
            # Queue chiusa o loop morto: log ma non rompere il producer
            if event_type in NEVER_DROP_TYPES:
                print(f"[V2 SSE] Push critico fallito ({event_type}): {e}")

    # ──────────────────────────────────────────────────────────────────────
    # Helpers tipizzati per chiamata pulita dai callers
    # ──────────────────────────────────────────────────────────────────────

    def emit_session_start(self, **kwargs) -> bool:
        return self.emit(SessionStartEvent(session_id=self.session_id, **kwargs))

    def emit_phase_start(self, phase: PipelinePhase, **kwargs) -> bool:
        return self.emit(PhaseStartEvent(session_id=self.session_id, phase=phase, **kwargs))

    def emit_phase_tick(self, phase: PipelinePhase, pct: float, **kwargs) -> bool:
        return self.emit(PhaseTickEvent(
            session_id=self.session_id, phase=phase, pct=pct, **kwargs
        ))

    def emit_phase_end(self, phase: PipelinePhase, duration_seconds: float = 0.0, **kwargs) -> bool:
        return self.emit(PhaseEndEvent(
            session_id=self.session_id, phase=phase,
            duration_seconds=duration_seconds, **kwargs,
        ))

    def emit_file_start(self, filename: str, **kwargs) -> bool:
        return self.emit(FileStartEvent(
            session_id=self.session_id, filename=filename, **kwargs
        ))

    def emit_file_warn(self, filename: str, kind: str, msg: str = "") -> bool:
        return self.emit(FileWarnEvent(
            session_id=self.session_id, filename=filename, kind=kind, msg=msg
        ))

    def emit_file_degrade(self, filename: str, reason: str, fallback: str) -> bool:
        return self.emit(FileDegradeEvent(
            session_id=self.session_id, filename=filename,
            reason=reason, fallback=fallback,
        ))

    def emit_file_done(self, filename: str, **kwargs) -> bool:
        return self.emit(FileDoneEvent(
            session_id=self.session_id, filename=filename, **kwargs
        ))

    def emit_llm_token(self, batch: int, chunk: str) -> bool:
        return self.emit(LlmTokenEvent(
            session_id=self.session_id, batch=batch, chunk=chunk
        ))

    def emit_error(
        self,
        kind: ErrorKind,
        msg: str,
        action: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return self.emit(ErrorEvent(
            session_id=self.session_id, kind=kind, msg=msg,
            action=action, detail=detail or {},
        ))

    def emit_heartbeat(self, **kwargs) -> bool:
        return self.emit(HeartbeatEvent(session_id=self.session_id, **kwargs))

    def emit_done(self, **kwargs) -> bool:
        return self.emit(DoneEvent(session_id=self.session_id, **kwargs))

    # ──────────────────────────────────────────────────────────────────────
    # SSE serialization
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def serialize_for_sse(payload: Dict[str, Any]) -> str:
        """Costruisce la riga `data: <json>\\n\\n` per StreamingResponse."""
        try:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception:
            return ""

    # ──────────────────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.session_id,
                "dropped_count": self._dropped_count,
                "dropped_by_type": dict(self._dropped_by_type),
                "recent_emit_window_size": len(self._recent_emit_times),
                "events_per_sec_limit": self._events_per_sec,
            }
