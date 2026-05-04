"""
V2 — Progress Store (Fase 6).

Persistenza JSONL append-only per session_id. Permette:
- Recovery post-crash: replay degli eventi al riavvio
- Audit trail: ogni evento è loggato a disco
- Compliance: archive compresso > 7 giorni

Design:
- File path: temp/progress/{session_id}.jsonl
- Append-only: 1 riga JSON per evento
- Lock cross-process (filelock) per safety se più worker uvicorn scrivessero
  sulla stessa session (caso teorico, non dovrebbe accadere)
- Atomic line write con flush + os.fsync per durability
- Replay tollerante: salta righe malformate ma continua

Mai eccezione: errori di scrittura → log warning + flag in stato.
Test offline: nessuna dipendenza esterna oltre filelock.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

try:
    from filelock import FileLock, Timeout as _FilelockTimeout
    HAS_FILELOCK = True
except ImportError:
    HAS_FILELOCK = False
    FileLock = None  # type: ignore
    _FilelockTimeout = Exception  # type: ignore


# Path base store
_WEBAPP_DIR = Path(__file__).resolve().parent.parent
PROGRESS_BASE_DIR = _WEBAPP_DIR.parent / "temp" / "progress"

# Timeout acquisizione filelock (seconds)
LOCK_ACQUIRE_TIMEOUT = 5.0


def _ensure_base_dir() -> None:
    PROGRESS_BASE_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# Store
# ──────────────────────────────────────────────────────────────────────────────

class ProgressStore:
    """
    Append-only JSONL persistence per session_id.

    Thread-safe (lock interno per singolo processo) + cross-process safe
    (filelock per multi-worker uvicorn, anche se in pratica session_id è
    unico per request quindi non c'è race cross-process).
    """

    def __init__(self, session_id: str, base_dir: Optional[Path] = None):
        if not session_id or "/" in session_id or "\\" in session_id:
            raise ValueError(f"session_id non valido: {session_id!r}")

        self.session_id = session_id
        self.base_dir = base_dir or PROGRESS_BASE_DIR
        self.path = self.base_dir / f"{session_id}.jsonl"
        self._lock_path = self.base_dir / f"{session_id}.lock"
        self._thread_lock = threading.Lock()
        self._disk_full_warning_emitted = False

    # ──────────────────────────────────────────────────────────────────────
    # Append
    # ──────────────────────────────────────────────────────────────────────

    def _acquire_filelock(self):
        """Restituisce un context manager. No-op se filelock non disponibile."""
        if HAS_FILELOCK:
            return FileLock(str(self._lock_path), timeout=LOCK_ACQUIRE_TIMEOUT)
        # Fallback: niente filelock (un worker singolo è OK)
        from contextlib import nullcontext
        return nullcontext()

    def append(self, event_payload: Dict[str, Any]) -> bool:
        """
        Appende un evento al JSONL.

        Args:
            event_payload: dict serializzabile JSON (tipicamente da
                           BaseEvent.model_dump())

        Returns:
            True se la scrittura è riuscita, False altrimenti.
            Mai solleva eccezione.
        """
        if not isinstance(event_payload, dict):
            return False

        try:
            line = json.dumps(event_payload, ensure_ascii=False) + "\n"
        except (TypeError, ValueError):
            # Payload non serializzabile: skip
            return False

        try:
            _ensure_base_dir()
        except OSError as e:
            self._warn_disk_full(e)
            return False

        with self._thread_lock:
            try:
                with self._acquire_filelock():
                    # Append + flush + fsync per durability (safe se crashiamo
                    # subito dopo la scrittura)
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(line)
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except (OSError, ValueError):
                            # fsync può fallire su filesystem speciali — non bloccante
                            pass
                return True
            except _FilelockTimeout:
                print(f"[V2 PROGRESS] Lock timeout per session {self.session_id}")
                return False
            except OSError as e:
                self._warn_disk_full(e)
                return False
            except Exception as e:
                print(f"[V2 PROGRESS] Append fallita ({self.session_id}): {e}")
                return False

    def _warn_disk_full(self, e: Exception) -> None:
        """Emette UN solo warning per session su disk full / OS error."""
        msg = str(e).lower()
        if any(k in msg for k in ("no space", "full", "disk")):
            if not self._disk_full_warning_emitted:
                print(f"[V2 PROGRESS] DISK FULL su {self.path}: {e}")
                self._disk_full_warning_emitted = True

    # ──────────────────────────────────────────────────────────────────────
    # Replay
    # ──────────────────────────────────────────────────────────────────────

    def replay(self) -> List[Dict[str, Any]]:
        """
        Legge tutti gli eventi dal JSONL. Skippa righe malformate.

        Returns:
            Lista di dict in ordine cronologico. Lista vuota se file
            inesistente o vuoto.
        """
        return list(self.iter_events())

    def iter_events(self) -> Iterator[Dict[str, Any]]:
        """
        Iteratore lazy sugli eventi (utile per replay incrementale).
        Tollerante a righe rotte (skip silenzioso).
        """
        if not self.path.exists():
            return

        try:
            with self._acquire_filelock():
                with open(self.path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            # Riga rotta (write interrotta a metà) → skip
                            continue
        except Exception as e:
            print(f"[V2 PROGRESS] Replay fallito ({self.session_id}): {e}")
            return

    def event_count(self) -> int:
        """Conta righe nel JSONL (eventi totali persisted)."""
        if not self.path.exists():
            return 0
        try:
            with self._acquire_filelock():
                with open(self.path, "r", encoding="utf-8") as f:
                    return sum(1 for _ in f)
        except Exception:
            return 0

    # ──────────────────────────────────────────────────────────────────────
    # Cleanup
    # ──────────────────────────────────────────────────────────────────────

    def delete(self) -> bool:
        """Cancella file JSONL e lock. Mai eccezione."""
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass
        try:
            if self._lock_path.exists():
                self._lock_path.unlink()
        except OSError:
            pass
        return True

    @property
    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0
