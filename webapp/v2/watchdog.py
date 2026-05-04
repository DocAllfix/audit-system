"""
V2 — Heartbeat Watchdog (Fase 6).

Thread separato (daemon) che ogni N secondi emette un evento `heartbeat` con:
- pid del processo
- RSS memoria in MB (via psutil se disponibile)
- queue depth della coda SSE

Detection lato client:
- Frontend riceve heartbeat ogni ~5s
- Se nessun heartbeat per > 15s → "Worker died, recupero stato in corso..."
- Endpoint `/api/v2/report/resume/{session_id}` permette ricostruzione

Caratteristiche:
- Thread daemon → muore con il processo principale (no orfani)
- Stop esplicito via `stop()` → ferma il thread entro `interval`
- psutil opzionale: degrada a "alive only" senza metriche
- Mai eccezione: errori loggati ma non propagati
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    psutil = None  # type: ignore

from v2.sse_emitter import SSEEmitter


# Intervallo di default tra heartbeat (secondi)
DEFAULT_INTERVAL = 5.0


class HeartbeatWatchdog:
    """
    Watchdog thread che emette heartbeat periodici via SSEEmitter.

    Uso:
        wd = HeartbeatWatchdog(emitter)
        wd.start()
        try:
            # ... pipeline lavoro ...
        finally:
            wd.stop()
    """

    def __init__(
        self,
        emitter: SSEEmitter,
        interval_seconds: float = DEFAULT_INTERVAL,
        get_queue_depth=None,
        get_workers_busy=None,
    ):
        """
        Args:
            emitter: SSEEmitter già configurato
            interval_seconds: cadenza heartbeat (default 5s)
            get_queue_depth: callable() -> int. Se None, ritorna 0.
            get_workers_busy: callable() -> int. Se None, ritorna 0.
        """
        self._emitter = emitter
        self._interval = max(0.5, float(interval_seconds))
        self._get_queue_depth = get_queue_depth
        self._get_workers_busy = get_workers_busy
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._heartbeats_emitted = 0

    # ──────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Avvia il thread daemon. No-op se già running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"v2-watchdog-{self._emitter.session_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Ferma il watchdog. Aspetta `timeout` secondi per il join."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def heartbeats_emitted(self) -> int:
        return self._heartbeats_emitted

    # ──────────────────────────────────────────────────────────────────────
    # Loop interno
    # ──────────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Loop heartbeat. Ferma quando stop_event è settato."""
        # Emetti subito un heartbeat al startup (così il client sa subito che siamo vivi)
        self._emit_one()

        while not self._stop_event.is_set():
            # Wait con interruzione anticipata se stop richiesto
            if self._stop_event.wait(timeout=self._interval):
                break
            self._emit_one()

    def _emit_one(self) -> None:
        """Emette un singolo heartbeat. Mai eccezione."""
        try:
            rss_mb = self._compute_rss_mb()
            queue_depth = self._safe_call(self._get_queue_depth, default=0)
            workers_busy = self._safe_call(self._get_workers_busy, default=0)
            ok = self._emitter.emit_heartbeat(
                pid=os.getpid(),
                rss_mb=rss_mb,
                queue_depth=int(queue_depth),
                workers_busy=int(workers_busy),
            )
            if ok:
                self._heartbeats_emitted += 1
        except Exception as e:
            # Heartbeat NON deve mai crashare il watchdog
            print(f"[V2 WATCHDOG] Errore in _emit_one: {e}")

    @staticmethod
    def _compute_rss_mb() -> float:
        """Memoria RSS in MB. 0.0 se psutil non disponibile o errore."""
        if not HAS_PSUTIL:
            return 0.0
        try:
            proc = psutil.Process(os.getpid())
            return round(proc.memory_info().rss / (1024 * 1024), 1)
        except Exception:
            return 0.0

    @staticmethod
    def _safe_call(fn, default=0):
        """Chiama fn() catturando eccezioni, ritorna default se fallisce."""
        if fn is None:
            return default
        try:
            return fn()
        except Exception:
            return default
