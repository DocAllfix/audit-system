"""
Test V2 Fase 6 — watchdog + recovery + cleanup + otel.

Coperture:
- HeartbeatWatchdog start/stop e thread daemon
- Heartbeat emessi a intervalli configurati
- get_queue_depth / get_workers_busy callback chiamati con safe fallback
- Stop interrompe il thread entro timeout
- recovery_handler.replay_session_sse legge JSONL e produce SSE
- session_id invalido rifiutato (anti path traversal)
- session_status fornisce metadata corretti
- cleanup.run_cleanup archive + delete + dry_run
- otel_tracer no-op quando disabilitato
- otel_span context manager non solleva mai
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from v2 import cleanup as cleanup_mod
from v2 import otel_tracer
from v2 import recovery_handler as rh
from v2.progress_store import ProgressStore
from v2.sse_emitter import SSEEmitter
from v2.watchdog import HeartbeatWatchdog


# ──────────────────────────────────────────────────────────────────────────────
# Watchdog
# ──────────────────────────────────────────────────────────────────────────────

def _make_emitter(tmp_path, session_id="wd1"):
    store = ProgressStore(session_id, base_dir=tmp_path)
    return SSEEmitter(session_id=session_id, store=store), store


def test_watchdog_emits_initial_heartbeat(tmp_path):
    """Al start, il watchdog emette subito un heartbeat (warm-up)."""
    emitter, store = _make_emitter(tmp_path)
    wd = HeartbeatWatchdog(emitter, interval_seconds=10.0)
    wd.start()
    # Diamo un piccolo lasso di tempo per l'esecuzione del primo emit
    time.sleep(0.1)
    wd.stop(timeout=1.0)

    events = store.replay()
    assert len(events) >= 1
    assert events[0]["type"] == "heartbeat"
    assert events[0]["pid"] == os.getpid()


def test_watchdog_periodic_heartbeats(tmp_path):
    emitter, store = _make_emitter(tmp_path, session_id="wd2")
    wd = HeartbeatWatchdog(emitter, interval_seconds=0.15)
    wd.start()
    time.sleep(0.6)  # ~3-4 heartbeat aggiuntivi (timing Windows-tolerant)
    wd.stop(timeout=1.0)

    events = store.replay()
    # Almeno 2 heartbeat (1 iniziale + 1 periodico) — soglia tollerante a Windows
    assert len(events) >= 2
    assert all(e["type"] == "heartbeat" for e in events)


def test_watchdog_stop_interrupts_thread(tmp_path):
    emitter, _ = _make_emitter(tmp_path, session_id="wd3")
    wd = HeartbeatWatchdog(emitter, interval_seconds=10.0)
    wd.start()
    assert wd.is_running is True
    wd.stop(timeout=1.0)
    assert wd.is_running is False


def test_watchdog_thread_is_daemon(tmp_path):
    emitter, _ = _make_emitter(tmp_path, session_id="wd4")
    wd = HeartbeatWatchdog(emitter, interval_seconds=10.0)
    wd.start()
    assert wd._thread.daemon is True
    wd.stop(timeout=1.0)


def test_watchdog_callbacks_invoked(tmp_path):
    emitter, store = _make_emitter(tmp_path, session_id="wd5")
    queue_depth = {"v": 42}
    workers_busy = {"v": 7}

    wd = HeartbeatWatchdog(
        emitter,
        interval_seconds=10.0,
        get_queue_depth=lambda: queue_depth["v"],
        get_workers_busy=lambda: workers_busy["v"],
    )
    wd.start()
    time.sleep(0.05)
    wd.stop(timeout=1.0)

    events = store.replay()
    assert events[0]["queue_depth"] == 42
    assert events[0]["workers_busy"] == 7


def test_watchdog_callbacks_safe_on_exception(tmp_path):
    """Eccezioni nei callback non rompono il watchdog."""
    emitter, store = _make_emitter(tmp_path, session_id="wd6")

    def boom():
        raise RuntimeError("explosion")

    wd = HeartbeatWatchdog(
        emitter,
        interval_seconds=10.0,
        get_queue_depth=boom,
        get_workers_busy=boom,
    )
    wd.start()
    time.sleep(0.05)
    wd.stop(timeout=1.0)

    events = store.replay()
    # Heartbeat emesso comunque (con default 0)
    assert events[0]["queue_depth"] == 0
    assert events[0]["workers_busy"] == 0


def test_watchdog_double_start_no_op(tmp_path):
    emitter, _ = _make_emitter(tmp_path, session_id="wd7")
    wd = HeartbeatWatchdog(emitter, interval_seconds=10.0)
    wd.start()
    first_thread = wd._thread
    wd.start()  # No-op
    assert wd._thread is first_thread
    wd.stop(timeout=1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Recovery handler
# ──────────────────────────────────────────────────────────────────────────────

def _seed_session(tmp_path, session_id, n_events=3):
    """Pre-popola un JSONL per test recovery."""
    store = ProgressStore(session_id, base_dir=tmp_path)
    for i in range(n_events):
        store.append({"type": "phase.tick", "session_id": session_id, "i": i})
    return store


def test_replay_returns_all_events(tmp_path, monkeypatch):
    """replay_session_sse rilegge tutti gli eventi + marker finale."""
    monkeypatch.setattr(rh, "ProgressStore",
                        lambda sid: ProgressStore(sid, base_dir=tmp_path))
    _seed_session(tmp_path, "rep1", n_events=3)

    lines = list(rh.replay_session_sse("rep1"))
    # 3 eventi originali + 1 replay_complete
    assert len(lines) == 4
    # Tutti formato SSE valido
    for line in lines:
        assert line.startswith("data: ")
        assert line.endswith("\n\n")

    # Ultima linea = replay_complete
    last = json.loads(lines[-1][len("data: "): -len("\n\n")])
    assert last["type"] == "replay_complete"
    assert last["events_replayed"] == 3


def test_replay_invalid_session_id_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(rh, "ProgressStore",
                        lambda sid: ProgressStore(sid, base_dir=tmp_path))
    lines = list(rh.replay_session_sse("../../etc/passwd"))
    assert len(lines) == 1
    payload = json.loads(lines[0][len("data: "): -len("\n\n")])
    assert payload["kind"] == "invalid_session_id"


def test_replay_unknown_session_returns_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(rh, "ProgressStore",
                        lambda sid: ProgressStore(sid, base_dir=tmp_path))
    lines = list(rh.replay_session_sse("does_not_exist"))
    payload = json.loads(lines[0][len("data: "): -len("\n\n")])
    assert payload["kind"] == "session_not_found"


def test_session_status_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(rh, "ProgressStore",
                        lambda sid: ProgressStore(sid, base_dir=tmp_path))
    _seed_session(tmp_path, "stat1", n_events=4)
    s = rh.session_status("stat1")
    assert s["exists"] is True
    assert s["event_count"] == 4
    assert s["last_event_type"] == "phase.tick"
    assert s["size_bytes"] > 0


def test_session_status_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(rh, "ProgressStore",
                        lambda sid: ProgressStore(sid, base_dir=tmp_path))
    s = rh.session_status("unknown")
    assert s["exists"] is False


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────

def test_cleanup_archives_old_files(tmp_path, monkeypatch):
    """File > TTL_LIVE giorni → archiviato (gzip + spostato)."""
    monkeypatch.setattr(cleanup_mod, "PROGRESS_DIR", tmp_path / "progress")
    monkeypatch.setattr(cleanup_mod, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(cleanup_mod, "TTL_LIVE_DAYS", 7)
    monkeypatch.setattr(cleanup_mod, "TTL_ARCHIVE_DAYS", 30)

    progress = tmp_path / "progress"
    progress.mkdir()
    old_file = progress / "old_session.jsonl"
    old_file.write_text('{"type":"session.start"}\n')

    # Imposta mtime a 10 giorni fa
    ten_days_ago = time.time() - (10 * 86400)
    os.utime(old_file, (ten_days_ago, ten_days_ago))

    summary = cleanup_mod.run_cleanup(dry_run=False)
    assert summary["archived_count"] == 1
    assert not old_file.exists()  # sostituito dall'archive
    # Verifica file gzip presente in archive
    archives = list((tmp_path / "archive").rglob("*.jsonl.gz"))
    assert len(archives) == 1


def test_cleanup_keeps_fresh_files(tmp_path, monkeypatch):
    """File < TTL_LIVE giorni → NON toccato."""
    monkeypatch.setattr(cleanup_mod, "PROGRESS_DIR", tmp_path / "progress")
    monkeypatch.setattr(cleanup_mod, "ARCHIVE_DIR", tmp_path / "archive")

    progress = tmp_path / "progress"
    progress.mkdir()
    fresh = progress / "fresh.jsonl"
    fresh.write_text('{"x":1}\n')
    # mtime di default = ora → fresh

    summary = cleanup_mod.run_cleanup(dry_run=False)
    assert summary["archived_count"] == 0
    assert fresh.exists()


def test_cleanup_deletes_old_archive(tmp_path, monkeypatch):
    """Archive > TTL_ARCHIVE giorni → cancellato."""
    monkeypatch.setattr(cleanup_mod, "PROGRESS_DIR", tmp_path / "progress")
    monkeypatch.setattr(cleanup_mod, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(cleanup_mod, "TTL_LIVE_DAYS", 7)
    monkeypatch.setattr(cleanup_mod, "TTL_ARCHIVE_DAYS", 30)

    archive_subdir = tmp_path / "archive" / "2025-01"
    archive_subdir.mkdir(parents=True)
    old_archived = archive_subdir / "ancient.jsonl.gz"
    old_archived.write_bytes(b"\x1f\x8b\x08\x00")  # gzip header valido + niente
    # mtime 60 giorni fa
    sixty_days_ago = time.time() - (60 * 86400)
    os.utime(old_archived, (sixty_days_ago, sixty_days_ago))

    summary = cleanup_mod.run_cleanup(dry_run=False)
    assert summary["deleted_count"] == 1
    assert not old_archived.exists()


def test_cleanup_dry_run_no_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup_mod, "PROGRESS_DIR", tmp_path / "progress")
    monkeypatch.setattr(cleanup_mod, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(cleanup_mod, "TTL_LIVE_DAYS", 7)

    progress = tmp_path / "progress"
    progress.mkdir()
    old_file = progress / "old.jsonl"
    old_file.write_text("{}\n")
    os.utime(old_file, (time.time() - 10 * 86400, time.time() - 10 * 86400))

    summary = cleanup_mod.run_cleanup(dry_run=True)
    # In dry-run il count è popolato ma il file resta in place
    assert summary["dry_run"] is True
    assert summary["archived_count"] == 1
    assert old_file.exists()  # NON spostato


def test_cleanup_handles_missing_dirs(tmp_path, monkeypatch):
    """run_cleanup non crasha se le directory non esistono."""
    monkeypatch.setattr(cleanup_mod, "PROGRESS_DIR", tmp_path / "no_progress")
    monkeypatch.setattr(cleanup_mod, "ARCHIVE_DIR", tmp_path / "no_archive")
    summary = cleanup_mod.run_cleanup(dry_run=False)
    assert summary["archived_count"] == 0
    assert summary["deleted_count"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# OTel tracer
# ──────────────────────────────────────────────────────────────────────────────

def test_otel_disabled_by_default():
    """V2_OTEL_ENABLED non impostato → is_enabled=False."""
    if "V2_OTEL_ENABLED" in os.environ:
        # In ambiente test pulito
        os.environ.pop("V2_OTEL_ENABLED")
    # Re-import per refresh _ENABLED_ENV
    import importlib
    importlib.reload(otel_tracer)
    assert otel_tracer.is_enabled() is False


def test_otel_span_no_op_when_disabled():
    """otel_span è no-op quando OTel disabilitato — yields None."""
    with otel_tracer.otel_span("test.span") as span:
        assert span is None


def test_otel_span_never_raises():
    """Errori interni del tracing non propagati al business code."""
    with otel_tracer.otel_span("test", attributes={"k": "v"}) as span:
        # Anche se span è None, il blocco esegue
        result = 1 + 1
    assert result == 2


def test_otel_init_idempotent():
    """init_tracer chiamato due volte → idempotente."""
    # Disabilitato → ritorna False entrambe le volte
    assert otel_tracer.init_tracer() is False
    assert otel_tracer.init_tracer() is False


def test_otel_add_event_no_op_when_disabled():
    otel_tracer.add_event("test_event", {"foo": "bar"})  # No exception
