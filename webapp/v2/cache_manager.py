"""
V2 — Cache Manager (Fase 3).

Gestisce il context caching del universal_evidence_prompt su Gemini API.
Il prompt (~6100 token) viene caricato una sola volta e riusato attraverso
N batch successivi con sconto 90% sui token cached → −80% costo input/run.

Caratteristiche:
- Singleton per-process (2 worker uvicorn = 2 cache indipendenti, niente shared state)
- Lock concorrenti (threading.Lock + double-check pattern)
- Hash del prompt come display_name → ricreazione automatica se il file cambia
- TTL 1h, cron refresh ogni 30 min (overlap → mai gap)
- Fallback inline se V2_CACHE_DISABLED=true o se l'API rifiuta il caching
- Recovery automatica su "cache not found" runtime

API pubblica:
    get_cached_prompt(client) -> Optional[str]
        Ritorna `cached_content_id` (es. "cachedContents/abc123") usabile in
        GenerateContentConfig(cached_content=...). Se None: caller deve usare
        prompt inline come prima.

    refresh_cache(client) -> bool
        Forza la ricreazione (per cron). Ritorna True se cache valida disponibile.

    invalidate_cache() -> None
        Marca la cache locale come stale (la prossima chiamata la ricrea).
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Optional

# Path del prompt universale V2 (isolato dal prompt V1 in PROD).
# V1 in `webapp/modules/` legge `universal_evidence_prompt.md` (originale).
# V2 legge la sua versione `universal_evidence_prompt_v2.md` con i fix
# applicati per allineare nomi categoria, header obbligatorio e checklist
# verifica conteggio schede.
_WEBAPP_DIR = Path(__file__).resolve().parent.parent
UNIVERSAL_PROMPT_PATH = _WEBAPP_DIR / "prompts" / "universal_evidence_prompt_v2.md"

# Modello target per il caching (deve supportare context caching)
CACHE_MODEL = "gemini-2.5-flash"

# TTL default in secondi (1h). Cron refresh ogni 30 min → overlap.
CACHE_TTL_SECONDS = int(os.environ.get("V2_CACHE_TTL_SECONDS", "3600"))

# Disabilita caching globalmente (debug / disaster recovery)
CACHE_DISABLED = os.environ.get("V2_CACHE_DISABLED", "false").lower() == "true"

# Lock per sincronizzare creazione/refresh tra thread dello stesso processo
_cache_lock = threading.Lock()

# Stato cache (per-process)
_cache_state = {
    "name": None,          # cachedContents/abc123
    "prompt_hash": None,   # hash del prompt al momento della creazione
    "created_at": 0.0,     # epoch creazione
    "model": None,         # modello usato
    "failed_attempts": 0,  # contatore fallimenti (per circuit breaker)
}

# Soglia oltre la quale interrompiamo i tentativi (circuit breaker)
MAX_CONSECUTIVE_FAILURES = 3


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_prompt_text() -> str:
    """
    Legge il universal_evidence_prompt.md. Ritorna stringa vuota se file
    non leggibile (mai eccezione — comportamento difensivo).
    """
    try:
        return UNIVERSAL_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[V2 CACHE] Impossibile leggere {UNIVERSAL_PROMPT_PATH}: {e}")
        return ""


def _compute_prompt_hash(prompt: str) -> str:
    """SHA-256 troncato del prompt per detection di modifiche."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _is_cache_stale(prompt_hash: str) -> bool:
    """
    True se la cache locale non è più valida:
      - non esiste
      - hash del prompt è cambiato (file modificato)
      - TTL scaduto considerando un margine di sicurezza
    """
    if _cache_state["name"] is None:
        return True
    if _cache_state["prompt_hash"] != prompt_hash:
        return True
    age = time.time() - _cache_state["created_at"]
    # Considera stale 5 minuti prima della scadenza per evitare race con refresh
    if age > (CACHE_TTL_SECONDS - 300):
        return True
    return False


def _reset_state() -> None:
    """
    Reset interno (mai esportare — usato da invalidate e dopo failure).
    Pulisce anche `failed_attempts`: il caller è responsabile di chiamare
    `invalidate_cache` solo quando vuole ripartire pulito (cron refresh,
    invalidate manuale, switch tra test).
    """
    _cache_state["name"] = None
    _cache_state["prompt_hash"] = None
    _cache_state["created_at"] = 0.0
    _cache_state["model"] = None
    _cache_state["failed_attempts"] = 0


# ──────────────────────────────────────────────────────────────────────────────
# Creazione cache su Gemini
# ──────────────────────────────────────────────────────────────────────────────

def _create_cache_on_gemini(client, prompt_text: str, prompt_hash: str) -> Optional[str]:
    """
    Chiama client.caches.create() e popola lo state. Ritorna il cache name
    oppure None se fallisce (con log).
    """
    try:
        from google.genai import types as gtypes
    except ImportError:
        print("[V2 CACHE] google.genai non disponibile")
        return None

    try:
        config = gtypes.CreateCachedContentConfig(
            system_instruction=prompt_text,
            ttl=f"{CACHE_TTL_SECONDS}s",
            display_name=f"audit_universal_v2_{prompt_hash}",
        )
        cache = client.caches.create(model=CACHE_MODEL, config=config)
        cache_name = getattr(cache, "name", None)
        if not cache_name:
            print(f"[V2 CACHE] caches.create non ha ritornato un .name valido: {cache!r}")
            return None
        _cache_state["name"] = cache_name
        _cache_state["prompt_hash"] = prompt_hash
        _cache_state["created_at"] = time.time()
        _cache_state["model"] = CACHE_MODEL
        _cache_state["failed_attempts"] = 0
        print(
            f"[V2 CACHE] Cache creata: {cache_name} "
            f"(hash={prompt_hash}, ttl={CACHE_TTL_SECONDS}s, model={CACHE_MODEL})"
        )
        return cache_name
    except Exception as e:
        _cache_state["failed_attempts"] += 1
        print(
            f"[V2 CACHE] Creazione fallita "
            f"(tentativo {_cache_state['failed_attempts']}/{MAX_CONSECUTIVE_FAILURES}): {e}"
        )
        return None


# ──────────────────────────────────────────────────────────────────────────────
# API pubblica
# ──────────────────────────────────────────────────────────────────────────────

def get_cached_prompt(client) -> Optional[str]:
    """
    Ritorna il `cached_content` id da usare in GenerateContentConfig.
    Se None viene ritornato, il caller deve usare il prompt inline come prima
    (fallback graceful).

    Args:
        client: istanza `google.genai.Client` (deve esporre `.caches.create()`).

    Returns:
        Stringa "cachedContents/..." oppure None se caching non disponibile.
    """
    if CACHE_DISABLED:
        return None

    if client is None:
        return None

    # Circuit breaker: dopo N fallimenti consecutivi, smette di provare per
    # questa esecuzione. Verrà resettato dal cron refresher al prossimo ciclo.
    if _cache_state["failed_attempts"] >= MAX_CONSECUTIVE_FAILURES:
        return None

    prompt_text = _load_prompt_text()
    if not prompt_text or len(prompt_text) < 1000:
        # Prompt sotto soglia minima Gemini (1024 token ≈ 4000 char) → niente cache
        return None

    prompt_hash = _compute_prompt_hash(prompt_text)

    # Fast path: cache valida già pronta
    if not _is_cache_stale(prompt_hash):
        return _cache_state["name"]

    # Slow path: serve creazione (con lock + double-check)
    with _cache_lock:
        if not _is_cache_stale(prompt_hash):
            return _cache_state["name"]
        # Lo state è stale: ricreiamo
        return _create_cache_on_gemini(client, prompt_text, prompt_hash)


def refresh_cache(client) -> bool:
    """
    Forza la ricreazione della cache. Usato dal cron refresher.

    Returns:
        True se la cache è disponibile dopo il refresh, False altrimenti.
    """
    if CACHE_DISABLED:
        return False

    prompt_text = _load_prompt_text()
    if not prompt_text:
        return False
    prompt_hash = _compute_prompt_hash(prompt_text)

    with _cache_lock:
        # Reset failed_attempts: il cron è il punto in cui ridiamo una chance
        _cache_state["failed_attempts"] = 0
        cache_name = _create_cache_on_gemini(client, prompt_text, prompt_hash)
        return cache_name is not None


def invalidate_cache() -> None:
    """Marca la cache locale come stale. Prossima chiamata la ricrea."""
    with _cache_lock:
        _reset_state()
        print("[V2 CACHE] Cache invalidata manualmente")


def handle_cache_miss_runtime(client) -> Optional[str]:
    """
    Da chiamare quando una `generate_content` ritorna errore "cache not found"
    (caso possibile: Gemini ha purgato la cache prima del TTL atteso).

    Forza invalidate + ricreazione + ritorna il nuovo cache_name (o None).
    """
    invalidate_cache()
    return get_cached_prompt(client)


def cache_status() -> dict:
    """Snapshot dello state per logging/SSE telemetria."""
    if CACHE_DISABLED:
        return {"enabled": False, "reason": "V2_CACHE_DISABLED=true"}
    age = (
        time.time() - _cache_state["created_at"]
        if _cache_state["created_at"] else None
    )
    return {
        "enabled": True,
        "cache_name": _cache_state["name"],
        "prompt_hash": _cache_state["prompt_hash"],
        "age_seconds": int(age) if age is not None else None,
        "ttl_seconds": CACHE_TTL_SECONDS,
        "failed_attempts": _cache_state["failed_attempts"],
        "model": _cache_state["model"],
    }
