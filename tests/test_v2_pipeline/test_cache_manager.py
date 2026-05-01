"""
Test V2 Fase 3 — cache_manager.

Coperture:
- Singleton: ripetute chiamate riusano la stessa cache (no API call duplicate)
- Lock: 5 thread concorrenti creano UNA sola cache
- Stale detection: se il prompt_hash cambia, ricreazione automatica
- TTL: cache "vecchia" viene considerata stale
- Fallback graceful: API fallisce → ritorna None senza crash
- Circuit breaker: dopo N failure consecutivi smette di provare
- Recovery: handle_cache_miss_runtime ricostruisce cache
- Disabled mode: V2_CACHE_DISABLED=true → sempre None
- Prompt sotto soglia → niente cache (return None)
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from v2 import cache_manager as cm


# ──────────────────────────────────────────────────────────────────────────────
# Reset stato tra i test
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_cache_state():
    """Reset state interno e disable flag tra ogni test (singleton sporco)."""
    cm.invalidate_cache()
    # Reset CACHE_DISABLED al valore di default per ogni test
    original = cm.CACHE_DISABLED
    cm.CACHE_DISABLED = False
    yield
    cm.CACHE_DISABLED = original
    cm.invalidate_cache()


# ──────────────────────────────────────────────────────────────────────────────
# Mock client helper
# ──────────────────────────────────────────────────────────────────────────────

def _make_mock_client(cache_name: str = "cachedContents/test_abc123"):
    """Mock client con caches.create() che ritorna un cache_name fisso."""
    mock = MagicMock()
    mock.caches = MagicMock()

    fake_cache = MagicMock()
    fake_cache.name = cache_name

    mock.caches.create = MagicMock(return_value=fake_cache)
    return mock


def _make_failing_client():
    """Mock client la cui caches.create() solleva sempre."""
    mock = MagicMock()
    mock.caches = MagicMock()
    mock.caches.create = MagicMock(side_effect=RuntimeError("API down"))
    return mock


# ──────────────────────────────────────────────────────────────────────────────
# Path felice — singleton
# ──────────────────────────────────────────────────────────────────────────────

def test_get_cached_prompt_creates_once_then_reuses():
    """Due chiamate consecutive → 1 sola caches.create()."""
    client = _make_mock_client()
    name1 = cm.get_cached_prompt(client)
    name2 = cm.get_cached_prompt(client)

    assert name1 == "cachedContents/test_abc123"
    assert name1 == name2
    assert client.caches.create.call_count == 1


def test_invalidate_forces_recreation():
    """Dopo invalidate, la chiamata successiva ricrea la cache."""
    client = _make_mock_client()
    cm.get_cached_prompt(client)
    cm.invalidate_cache()
    cm.get_cached_prompt(client)
    assert client.caches.create.call_count == 2


def test_handle_cache_miss_runtime_recreates():
    """handle_cache_miss_runtime invalida e ricrea."""
    client = _make_mock_client()
    cm.get_cached_prompt(client)  # 1° create
    cm.handle_cache_miss_runtime(client)  # 2° create
    assert client.caches.create.call_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# Stale detection
# ──────────────────────────────────────────────────────────────────────────────

def test_changed_prompt_hash_triggers_recreation():
    """Se il prompt_hash cambia (file modificato), ricreazione automatica."""
    client = _make_mock_client()

    # Prima chiamata con prompt A
    with patch.object(cm, "_load_prompt_text", return_value="Prompt A " * 200):
        cm.get_cached_prompt(client)
    assert client.caches.create.call_count == 1

    # Seconda chiamata con prompt B (hash diverso)
    with patch.object(cm, "_load_prompt_text", return_value="Prompt B " * 200):
        cm.get_cached_prompt(client)
    assert client.caches.create.call_count == 2


def test_aged_cache_considered_stale():
    """Cache più vecchia di TTL-margin viene considerata stale."""
    client = _make_mock_client()
    cm.get_cached_prompt(client)
    assert client.caches.create.call_count == 1

    # Simula passaggio di tempo: imposta created_at vecchio
    cm._cache_state["created_at"] = time.time() - (cm.CACHE_TTL_SECONDS - 100)

    cm.get_cached_prompt(client)
    assert client.caches.create.call_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# Fallback e disable
# ──────────────────────────────────────────────────────────────────────────────

def test_disabled_returns_none():
    """V2_CACHE_DISABLED=true → get_cached_prompt ritorna None senza chiamate."""
    cm.CACHE_DISABLED = True
    client = _make_mock_client()
    result = cm.get_cached_prompt(client)
    assert result is None
    client.caches.create.assert_not_called()


def test_none_client_returns_none():
    """Client None → ritorna None senza crash."""
    assert cm.get_cached_prompt(None) is None


def test_api_failure_returns_none():
    """Se caches.create solleva, get_cached_prompt ritorna None gracefully."""
    client = _make_failing_client()
    result = cm.get_cached_prompt(client)
    assert result is None


def test_circuit_breaker_after_n_failures():
    """Dopo MAX_CONSECUTIVE_FAILURES, smette di chiamare l'API."""
    client = _make_failing_client()

    for _ in range(cm.MAX_CONSECUTIVE_FAILURES + 2):
        cm.get_cached_prompt(client)

    # L'API è stata chiamata MAX_CONSECUTIVE_FAILURES volte, poi più
    assert client.caches.create.call_count == cm.MAX_CONSECUTIVE_FAILURES


def test_refresh_resets_circuit_breaker():
    """refresh_cache resetta il contatore failed_attempts."""
    client = _make_failing_client()
    for _ in range(cm.MAX_CONSECUTIVE_FAILURES + 1):
        cm.get_cached_prompt(client)
    assert cm._cache_state["failed_attempts"] >= cm.MAX_CONSECUTIVE_FAILURES

    # Cron refresh: cliente "guarito"
    healthy_client = _make_mock_client()
    ok = cm.refresh_cache(healthy_client)
    assert ok is True
    assert cm._cache_state["failed_attempts"] == 0


def test_short_prompt_not_cached():
    """Prompt sotto soglia 1000 char → ritorna None senza chiamare API."""
    client = _make_mock_client()
    with patch.object(cm, "_load_prompt_text", return_value="Too short"):
        result = cm.get_cached_prompt(client)
    assert result is None
    client.caches.create.assert_not_called()


def test_empty_prompt_not_cached():
    """Prompt vuoto (file mancante) → ritorna None."""
    client = _make_mock_client()
    with patch.object(cm, "_load_prompt_text", return_value=""):
        result = cm.get_cached_prompt(client)
    assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# Concurrency
# ──────────────────────────────────────────────────────────────────────────────

def test_concurrent_calls_create_one_cache():
    """5 thread che chiamano get_cached_prompt → 1 sola caches.create()."""
    client = _make_mock_client()

    # Aggiungi una piccola latenza nel mock per favorire collisione
    real_create = client.caches.create
    def slow_create(*args, **kwargs):
        time.sleep(0.05)
        return real_create.return_value
    client.caches.create = MagicMock(side_effect=slow_create)

    results = []
    threads = []

    def worker():
        results.append(cm.get_cached_prompt(client))

    for _ in range(5):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    # Tutti devono aver ricevuto lo stesso cache_name
    assert all(r == "cachedContents/test_abc123" for r in results)
    # Solo 1 chiamata creazione
    assert client.caches.create.call_count == 1


# ──────────────────────────────────────────────────────────────────────────────
# Status reporting
# ──────────────────────────────────────────────────────────────────────────────

def test_status_disabled():
    cm.CACHE_DISABLED = True
    s = cm.cache_status()
    assert s["enabled"] is False


def test_status_active():
    client = _make_mock_client()
    cm.get_cached_prompt(client)
    s = cm.cache_status()
    assert s["enabled"] is True
    assert s["cache_name"] == "cachedContents/test_abc123"
    assert s["age_seconds"] is not None
    assert s["age_seconds"] >= 0
    assert s["ttl_seconds"] == cm.CACHE_TTL_SECONDS
    assert s["model"] == cm.CACHE_MODEL


def test_status_before_first_create():
    """Status prima di qualsiasi creazione."""
    s = cm.cache_status()
    assert s["enabled"] is True
    assert s["cache_name"] is None
    assert s["age_seconds"] is None


# ──────────────────────────────────────────────────────────────────────────────
# Hashing prompt
# ──────────────────────────────────────────────────────────────────────────────

def test_compute_prompt_hash_deterministic():
    h1 = cm._compute_prompt_hash("identical prompt content")
    h2 = cm._compute_prompt_hash("identical prompt content")
    assert h1 == h2


def test_compute_prompt_hash_different_for_different_input():
    h1 = cm._compute_prompt_hash("prompt A")
    h2 = cm._compute_prompt_hash("prompt B")
    assert h1 != h2


def test_compute_prompt_hash_truncated_to_16():
    h = cm._compute_prompt_hash("any text")
    assert len(h) == 16
