"""
V2 — Event schemas (Fase 6).

Modelli Pydantic per gli eventi SSE typed emessi da V2. Ogni evento ha:
- `type`: discriminator string (es. "session.start")
- `ts`: ISO 8601 timestamp UTC
- `session_id`: identificatore della pipeline run
- payload specifico per tipo

12 categorie totali:
1. session.start          — apertura pipeline
2. phase.start            — inizio fase (ingestion, triage, classify, ...)
3. phase.tick             — progresso intra-fase (pct + dettagli)
4. phase.end              — fine fase (con metriche)
5. file.start             — inizio elaborazione singolo file
6. file.warn              — avviso su file specifico (es. >50MB)
7. file.degrade           — fallback applicato (es. OCR fast mode)
8. file.done              — file completato (con metriche)
9. llm.token              — chunk di testo dal modello (streaming UI)
10. error                 — errore tipizzato (kind specifico)
11. heartbeat             — keepalive (PID, RSS, queue depth)
12. done                  — fine pipeline (con risultato finale)

Mai eccezione: validator clamp/coerce, default ragionevoli, extra="ignore".
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _utc_iso_now() -> str:
    """Timestamp ISO 8601 con suffisso Z (UTC)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ──────────────────────────────────────────────────────────────────────────────
# Discriminator enum (per parsing tipo-aware lato client)
# ──────────────────────────────────────────────────────────────────────────────

class EventType(str, Enum):
    SESSION_START = "session.start"
    PHASE_START = "phase.start"
    PHASE_TICK = "phase.tick"
    PHASE_END = "phase.end"
    FILE_START = "file.start"
    FILE_WARN = "file.warn"
    FILE_DEGRADE = "file.degrade"
    FILE_DONE = "file.done"
    LLM_TOKEN = "llm.token"
    ERROR = "error"
    HEARTBEAT = "heartbeat"
    DONE = "done"


# ──────────────────────────────────────────────────────────────────────────────
# Phase enum (le fasi pipeline V2)
# ──────────────────────────────────────────────────────────────────────────────

class PipelinePhase(str, Enum):
    INGESTION = "ingestion"
    TRIAGE = "triage"
    CLASSIFY = "classify"
    OCR = "ocr"
    ANALYZE = "analyze"
    DOCX_BUILD = "docx_build"
    CLEANUP = "cleanup"


# ──────────────────────────────────────────────────────────────────────────────
# Error kind (tassonomia errori specifica V2)
# ──────────────────────────────────────────────────────────────────────────────

class ErrorKind(str, Enum):
    RESPONSE_TOO_LARGE = "response_too_large"     # cap 400k raggiunto
    DOCX_LXML = "docx_lxml"                        # crash python-docx (ricoverato Fase 7)
    WORKER_OOM = "worker_oom"                      # MemoryError catturato
    API_AUTH = "api_auth"                          # 401/403 Gemini
    API_RATE_LIMIT = "api_rate_limit"              # 429
    API_OVERLOAD = "api_overload"                  # 503
    NETWORK = "network"                            # connection error
    TIMEOUT = "timeout"                            # inter-chunk o phase
    DISK_FULL = "disk_full"                        # progress persist failed
    UPLOAD_FAILED = "upload_failed"                # Files API
    OCR_FAILED = "ocr_failed"                      # tutti modelli falliti
    PARSE_FAILED = "parse_failed"                  # YAML malformato
    UNKNOWN = "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Base event
# ──────────────────────────────────────────────────────────────────────────────

class BaseEvent(BaseModel):
    """Campi comuni a tutti gli eventi."""

    model_config = ConfigDict(
        extra="ignore",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    type: EventType
    ts: str = Field(default_factory=_utc_iso_now)
    session_id: str = Field(default="", max_length=200)


# ──────────────────────────────────────────────────────────────────────────────
# Session lifecycle
# ──────────────────────────────────────────────────────────────────────────────

class SessionStartEvent(BaseEvent):
    type: EventType = EventType.SESSION_START
    user: Optional[str] = None
    total_files: int = 0
    total_size_mb: float = 0.0
    input_kind: str = "zip"  # zip | folder
    preflight_warnings: List[str] = Field(default_factory=list)


class DoneEvent(BaseEvent):
    type: EventType = EventType.DONE
    output_filename: Optional[str] = None
    company_name: Optional[str] = None
    download_url: Optional[str] = None
    duration_seconds: float = 0.0
    stats: Dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Phase lifecycle
# ──────────────────────────────────────────────────────────────────────────────

class PhaseStartEvent(BaseEvent):
    type: EventType = EventType.PHASE_START
    phase: PipelinePhase
    total_items: Optional[int] = None  # es. n. file da processare


class PhaseTickEvent(BaseEvent):
    type: EventType = EventType.PHASE_TICK
    phase: PipelinePhase
    pct: float = Field(default=0.0, ge=0.0, le=1.0)
    detail: Dict[str, Any] = Field(default_factory=dict)


class PhaseEndEvent(BaseEvent):
    type: EventType = EventType.PHASE_END
    phase: PipelinePhase
    duration_seconds: float = 0.0
    metrics: Dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# File lifecycle
# ──────────────────────────────────────────────────────────────────────────────

class FileStartEvent(BaseEvent):
    type: EventType = EventType.FILE_START
    filename: str
    size_bytes: int = 0
    strategy: Optional[str] = None  # es. "text_layer" | "ocr"


class FileWarnEvent(BaseEvent):
    type: EventType = EventType.FILE_WARN
    filename: str
    kind: str = "generic"           # "large" | "encrypted" | ecc.
    msg: str = ""


class FileDegradeEvent(BaseEvent):
    type: EventType = EventType.FILE_DEGRADE
    filename: str
    reason: str = ""
    fallback: str = ""               # es. "fast_mode_3_pages"


class FileDoneEvent(BaseEvent):
    type: EventType = EventType.FILE_DONE
    filename: str
    chars: int = 0
    method: str = ""                 # es. "pdfium_native_ok"
    success: bool = True


# ──────────────────────────────────────────────────────────────────────────────
# LLM streaming
# ──────────────────────────────────────────────────────────────────────────────

class LlmTokenEvent(BaseEvent):
    type: EventType = EventType.LLM_TOKEN
    batch: int = 0
    chunk: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Error
# ──────────────────────────────────────────────────────────────────────────────

class ErrorEvent(BaseEvent):
    type: EventType = EventType.ERROR
    kind: ErrorKind = ErrorKind.UNKNOWN
    msg: str = ""
    detail: Dict[str, Any] = Field(default_factory=dict)
    action: Optional[str] = None     # es. "truncated_to_400000", "retry"


# ──────────────────────────────────────────────────────────────────────────────
# Heartbeat (watchdog)
# ──────────────────────────────────────────────────────────────────────────────

class HeartbeatEvent(BaseEvent):
    type: EventType = EventType.HEARTBEAT
    pid: int = 0
    rss_mb: float = 0.0
    queue_depth: int = 0
    workers_busy: int = 0


# ──────────────────────────────────────────────────────────────────────────────
# Helper: union type per parsing client-side
# ──────────────────────────────────────────────────────────────────────────────

EVENT_CLASS_BY_TYPE = {
    EventType.SESSION_START.value: SessionStartEvent,
    EventType.PHASE_START.value: PhaseStartEvent,
    EventType.PHASE_TICK.value: PhaseTickEvent,
    EventType.PHASE_END.value: PhaseEndEvent,
    EventType.FILE_START.value: FileStartEvent,
    EventType.FILE_WARN.value: FileWarnEvent,
    EventType.FILE_DEGRADE.value: FileDegradeEvent,
    EventType.FILE_DONE.value: FileDoneEvent,
    EventType.LLM_TOKEN.value: LlmTokenEvent,
    EventType.ERROR.value: ErrorEvent,
    EventType.HEARTBEAT.value: HeartbeatEvent,
    EventType.DONE.value: DoneEvent,
}


def parse_event(raw: Dict[str, Any]) -> Optional[BaseEvent]:
    """
    Parsing tipo-aware: data un dict, costruisce la sottoclasse giusta in
    base al `type`. Ritorna None se il tipo non è riconosciuto o il payload
    è malformato. Mai eccezione.
    """
    if not isinstance(raw, dict):
        return None
    t = raw.get("type")
    if not isinstance(t, str):
        return None
    cls = EVENT_CLASS_BY_TYPE.get(t)
    if cls is None:
        return None
    try:
        return cls.model_validate(raw)
    except Exception:
        return None
