"""
GEMINI THROTTLE - Semafori globali per limitare concorrenza chiamate Gemini API.

Motivazione: la pipeline lancia fino a 25 chiamate Gemini in parallelo (10 OCR +
10 narrative + 5 structured). I burst sopra 8-10 chiamate concorrenti saturano
il proxy Cloud Functions e causano errori 429 a cascata.

Strategia: due semafori per fase + cap globale.
  - SEM_OCR = 5     (OCR è image-heavy, payload grandi, OOM risk)
  - SEM_STRUCTURED = 7 (analisi testo, payload piccoli)
  - SEM_GLOBAL = 8  (cap globale di sicurezza)

Uso:
    from modules.gemini_throttle import gemini_ocr_slot, gemini_structured_slot

    with gemini_ocr_slot():
        response = client.models.generate_content(...)

    with gemini_structured_slot():
        response = client.models.generate_content(...)

Disable per dev/test: settare env GEMINI_THROTTLE_DISABLED=1.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager

# ──────────────────────────────────────────────────────────────────────────────
# Configurazione
# ──────────────────────────────────────────────────────────────────────────────

_DISABLED = os.environ.get("GEMINI_THROTTLE_DISABLED", "0") == "1"

# Limiti tunabili via env (default ottimizzati per Tier 2 + proxy Cloud Functions)
_OCR_LIMIT = int(os.environ.get("GEMINI_OCR_LIMIT", "5"))
_STRUCTURED_LIMIT = int(os.environ.get("GEMINI_STRUCTURED_LIMIT", "7"))
_GLOBAL_LIMIT = int(os.environ.get("GEMINI_GLOBAL_LIMIT", "12"))

# ──────────────────────────────────────────────────────────────────────────────
# Semafori globali (per-process)
# ──────────────────────────────────────────────────────────────────────────────

# I semafori vivono a livello di modulo → condivisi tra tutti i thread del
# processo Python. Con uvicorn --workers 2, ogni worker ha la propria copia.

_SEM_OCR = threading.BoundedSemaphore(_OCR_LIMIT)
_SEM_STRUCTURED = threading.BoundedSemaphore(_STRUCTURED_LIMIT)
_SEM_GLOBAL = threading.BoundedSemaphore(_GLOBAL_LIMIT)


# ──────────────────────────────────────────────────────────────────────────────
# Context manager per OCR
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def gemini_ocr_slot():
    """
    Acquisisce uno slot OCR + uno globale.
    Esce dal context anche su eccezione (try/finally garantito).
    """
    if _DISABLED:
        yield
        return

    _SEM_GLOBAL.acquire()
    try:
        _SEM_OCR.acquire()
        try:
            yield
        finally:
            _SEM_OCR.release()
    finally:
        _SEM_GLOBAL.release()


# ──────────────────────────────────────────────────────────────────────────────
# Context manager per Structured / Checklist
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def gemini_structured_slot():
    """
    Acquisisce uno slot strutturato + uno globale.
    Usare per: analisi documenti, generazione checklist, qualsiasi chiamata
    Gemini che NON sia OCR di immagini.
    """
    if _DISABLED:
        yield
        return

    _SEM_GLOBAL.acquire()
    try:
        _SEM_STRUCTURED.acquire()
        try:
            yield
        finally:
            _SEM_STRUCTURED.release()
    finally:
        _SEM_GLOBAL.release()


# ──────────────────────────────────────────────────────────────────────────────
# Diagnostica (utile per logging in caso di analisi performance)
# ──────────────────────────────────────────────────────────────────────────────

def adaptive_delay(attempt: int, error_kind: str = "rate_limit") -> float:
    """
    Calcola delay con exponential backoff + jitter.

    Args:
        attempt: numero tentativo (0-based)
        error_kind:
          - "rate_limit" (429): backoff aggressivo, base 1s, max 30s
          - "overload"   (503): backoff conservativo, base 5s, max 60s

    Returns:
        Secondi da attendere prima del prossimo retry.
    """
    import random

    if error_kind == "overload":
        # Google overloaded: dare tempo al servizio di recuperare
        base = 5.0
        max_d = 60.0
    else:
        # Rate limit nostro: retry rapidi
        base = 1.0
        max_d = 30.0

    delay = base * (2 ** attempt)
    jitter = random.uniform(0, delay * 0.5)
    return min(delay + jitter, max_d)


def get_status() -> dict:
    """
    Ritorna stato attuale dei semafori (numero slot disponibili).
    Utile per logging/diagnostica.
    NOTA: il valore `_value` è privato di threading.Semaphore ma stabile;
    se Python cambia API è solo metrica, non rompe la pipeline.
    """
    if _DISABLED:
        return {"disabled": True}

    try:
        return {
            "ocr_available": _SEM_OCR._value,
            "ocr_limit": _OCR_LIMIT,
            "structured_available": _SEM_STRUCTURED._value,
            "structured_limit": _STRUCTURED_LIMIT,
            "global_available": _SEM_GLOBAL._value,
            "global_limit": _GLOBAL_LIMIT,
        }
    except AttributeError:
        return {"introspection_unavailable": True}
