"""
Test V2 Fase 6 — progress_store.

Coperture:
- Append singolo + replay
- Append concorrente da N thread → tutti gli eventi salvati
- Replay tollerante a righe malformate (skip senza crash)
- File inesistente → replay vuoto, no eccezione
- delete() pulisce file + lock
- session_id invalido (path traversal) rifiutato
- Persistenza durable (file esiste anche dopo del store)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from v2.progress_store import ProgressStore


# ──────────────────────────────────────────────────────────────────────────────
# Validazione session_id
# ──────────────────────────────────────────────────────────────────────────────

def test_session_id_with_path_separator_rejected(tmp_path):
    with pytest.raises(ValueError):
        ProgressStore("../../etc/passwd", base_dir=tmp_path)
    with pytest.raises(ValueError):
        ProgressStore("foo/bar", base_dir=tmp_path)
    with pytest.raises(ValueError):
        ProgressStore("foo\\bar", base_dir=tmp_path)


def test_empty_session_id_rejected(tmp_path):
    with pytest.raises(ValueError):
        ProgressStore("", base_dir=tmp_path)


# ──────────────────────────────────────────────────────────────────────────────
# Append + replay
# ──────────────────────────────────────────────────────────────────────────────

def test_append_single_event(tmp_path):
    store = ProgressStore("test1", base_dir=tmp_path)
    ok = store.append({"type": "session.start", "session_id": "test1"})
    assert ok is True
    assert store.event_count() == 1
    assert store.path.exists()


def test_replay_returns_events_in_order(tmp_path):
    store = ProgressStore("test2", base_dir=tmp_path)
    store.append({"type": "phase.start", "phase": "ingestion"})
    store.append({"type": "phase.tick", "pct": 0.5})
    store.append({"type": "phase.end", "duration_seconds": 12.0})

    events = store.replay()
    assert len(events) == 3
    assert events[0]["type"] == "phase.start"
    assert events[1]["type"] == "phase.tick"
    assert events[2]["type"] == "phase.end"


def test_iter_events_lazy(tmp_path):
    store = ProgressStore("test3", base_dir=tmp_path)
    for i in range(10):
        store.append({"type": "phase.tick", "i": i})
    # iter_events è lazy: prendiamo solo i primi 3
    first_three = []
    for ev in store.iter_events():
        first_three.append(ev)
        if len(first_three) == 3:
            break
    assert len(first_three) == 3
    assert first_three[0]["i"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Tolleranza a errori
# ──────────────────────────────────────────────────────────────────────────────

def test_non_serializable_payload_returns_false(tmp_path):
    store = ProgressStore("ns", base_dir=tmp_path)
    # set non è JSON-serializable
    ok = store.append({"data": {1, 2, 3}})
    assert ok is False
    # File non creato
    assert store.event_count() == 0


def test_non_dict_payload_returns_false(tmp_path):
    store = ProgressStore("nd", base_dir=tmp_path)
    assert store.append("not a dict") is False  # type: ignore
    assert store.append(None) is False  # type: ignore
    assert store.append(123) is False  # type: ignore


def test_replay_skips_malformed_lines(tmp_path):
    """Linee malformate nel JSONL vengono skippate, non causano crash."""
    store = ProgressStore("mal", base_dir=tmp_path)
    store.append({"type": "session.start"})
    # Iniettiamo una linea rotta a mano
    with open(store.path, "a", encoding="utf-8") as f:
        f.write("{garbage not json\n")
        f.write('{"type": "phase.tick", "ok": true}\n')

    events = store.replay()
    # Deve esserci solo session.start + phase.tick (la riga rotta skippata)
    types = [e["type"] for e in events]
    assert "session.start" in types
    assert "phase.tick" in types
    # event_count conta TUTTE le righe del file (incluso garbage)
    assert store.event_count() == 3


def test_replay_nonexistent_file_returns_empty(tmp_path):
    store = ProgressStore("never_written", base_dir=tmp_path)
    assert store.replay() == []
    assert store.event_count() == 0


# ──────────────────────────────────────────────────────────────────────────────
# Concorrenza
# ──────────────────────────────────────────────────────────────────────────────

def test_concurrent_appends_all_persisted(tmp_path):
    """N thread scrivono → tutti gli eventi sono nel JSONL."""
    store = ProgressStore("concurrent", base_dir=tmp_path)
    NUM_THREADS = 8
    EVENTS_PER_THREAD = 25

    def worker(tid: int):
        for i in range(EVENTS_PER_THREAD):
            store.append({"type": "phase.tick", "thread": tid, "i": i})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(NUM_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    events = store.replay()
    assert len(events) == NUM_THREADS * EVENTS_PER_THREAD
    # Verifica che tutti i thread hanno avuto i loro eventi
    threads_seen = {e["thread"] for e in events}
    assert threads_seen == set(range(NUM_THREADS))


# ──────────────────────────────────────────────────────────────────────────────
# Delete
# ──────────────────────────────────────────────────────────────────────────────

def test_delete_removes_files(tmp_path):
    store = ProgressStore("del", base_dir=tmp_path)
    store.append({"type": "session.start"})
    assert store.path.exists()
    ok = store.delete()
    assert ok is True
    assert not store.path.exists()


def test_delete_idempotent(tmp_path):
    store = ProgressStore("del2", base_dir=tmp_path)
    # Non scriviamo nulla → file inesistente
    assert store.delete() is True


# ──────────────────────────────────────────────────────────────────────────────
# Size & path
# ──────────────────────────────────────────────────────────────────────────────

def test_size_bytes_grows(tmp_path):
    store = ProgressStore("size", base_dir=tmp_path)
    assert store.size_bytes == 0
    store.append({"type": "session.start"})
    assert store.size_bytes > 0


def test_path_under_base_dir(tmp_path):
    store = ProgressStore("loc", base_dir=tmp_path)
    assert store.path.parent == tmp_path
    assert store.path.suffix == ".jsonl"
