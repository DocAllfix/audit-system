"""
V2 — Recovery Handler (Fase 6).

Endpoint per ricostruire lo stato di una pipeline V2 dopo crash o disconnessione.
Legge il JSONL di ProgressStore e replay-a tutti gli eventi al client come
stream SSE one-shot (no live updates, solo replay storico).

Uso (registrato in api_server.py come endpoint additivo):
    GET /api/v2/report/resume/{session_id}
        → SSE stream con tutti gli eventi noti per quella sessione

Il client può combinare:
1. Connessione iniziale a /api/v2/report/process (live)
2. Se disconnesso → /api/v2/report/resume/{session_id} (replay)
3. Riprende da dove era arrivato (può anche dedup-are se ha cache locale)

Caratteristiche:
- No-op safe se session_id inesistente: ritorna SSE vuoto + evento `not_found`
- Mai espone path filesystem
- Validazione session_id (alphanumerici + - _)
- Streaming chunk-per-chunk (memoria costante anche con JSONL grandi)
"""
from __future__ import annotations

import re
from typing import AsyncIterator, Iterator

from v2.progress_store import ProgressStore
from v2.sse_emitter import SSEEmitter


# Pattern session_id ammesso (anti-path-traversal)
_VALID_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,200}$")


def _is_valid_session_id(session_id: str) -> bool:
    """Validazione difensiva contro path traversal."""
    return bool(_VALID_SESSION_ID_RE.match(session_id or ""))


# ──────────────────────────────────────────────────────────────────────────────
# Replay sync (per compatibilità con test e CLI)
# ──────────────────────────────────────────────────────────────────────────────

def replay_session_sse(session_id: str) -> Iterator[str]:
    """
    Genera linee SSE (`data: ...\\n\\n`) per replay degli eventi di una session.

    Args:
        session_id: identificatore sessione validato

    Yields:
        Stringhe già formattate per SSE: `data: <json>\\n\\n`
        Se la sessione non esiste, yields un singolo evento `error.not_found`.
    """
    if not _is_valid_session_id(session_id):
        yield SSEEmitter.serialize_for_sse({
            "type": "error",
            "kind": "invalid_session_id",
            "msg": "session_id non valido",
        })
        return

    store = ProgressStore(session_id)
    if not store.path.exists():
        yield SSEEmitter.serialize_for_sse({
            "type": "error",
            "kind": "session_not_found",
            "session_id": session_id,
            "msg": "Nessun progress trovato per questa sessione",
        })
        return

    # Replay tutti gli eventi
    yielded = 0
    for event_dict in store.iter_events():
        line = SSEEmitter.serialize_for_sse(event_dict)
        if line:
            yielded += 1
            yield line

    # Marker di fine replay (così il client sa che il replay è completo)
    yield SSEEmitter.serialize_for_sse({
        "type": "replay_complete",
        "session_id": session_id,
        "events_replayed": yielded,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Replay async (per FastAPI StreamingResponse)
# ──────────────────────────────────────────────────────────────────────────────

async def replay_session_sse_async(session_id: str) -> AsyncIterator[str]:
    """
    Versione async di replay_session_sse (richiesta da FastAPI StreamingResponse).
    """
    for line in replay_session_sse(session_id):
        yield line


# ──────────────────────────────────────────────────────────────────────────────
# Status check (sync, JSON-friendly)
# ──────────────────────────────────────────────────────────────────────────────

def session_status(session_id: str) -> dict:
    """
    Ritorna un riepilogo sync della sessione (utile per /api/v2/report/status).

    Returns:
        Dict con: exists, event_count, size_bytes, last_event_type
    """
    if not _is_valid_session_id(session_id):
        return {"exists": False, "error": "invalid_session_id"}

    store = ProgressStore(session_id)
    if not store.path.exists():
        return {"exists": False, "session_id": session_id}

    last_type = None
    count = 0
    for event in store.iter_events():
        count += 1
        last_type = event.get("type")

    return {
        "exists": True,
        "session_id": session_id,
        "event_count": count,
        "size_bytes": store.size_bytes,
        "last_event_type": last_type,
    }
