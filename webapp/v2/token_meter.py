"""
V2 — Token Meter (Fase 7.5).

Singleton process-level che raccoglie il consumo di token Gemini per session_id
e calcola il costo stimato in USD/EUR.

Origine dati: `response.usage_metadata` esposto dal SDK `google-genai`. Tre
campi rilevanti:
- prompt_token_count          → input tokens (full price)
- cached_content_token_count  → input tokens letti da cache (sconto)
- candidates_token_count      → output tokens

Caratteristiche:
- Persistenza JSON sync su `temp/token_usage/{session_id}.json` ad ogni record
- Thread-safe (lock per session_id)
- Pricing module-level facilmente aggiornabile se Google cambia tariffe
- Mai eccezione: errori di accesso a usage_metadata loggati e ignorati
- Helper `record_from_response(response, ...)` che estrae i campi automaticamente
- Report human-readable + report JSON-friendly per dashboard

API pubblica:
    record_call(session_id, model, input_tokens, cached_tokens, output_tokens, kind=...)
    record_from_response(session_id, response, model, kind=...)
    get_session_report(session_id) -> dict
    format_report_table(session_id) -> str
    reset_session(session_id) -> None
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Pricing (USD per 1M tokens) — aggiornato 2026
# ──────────────────────────────────────────────────────────────────────────────

# Per ognuno: {input, output, cached_input}. cached_input=None → modello non
# supporta caching.
PRICING: Dict[str, Dict[str, Optional[float]]] = {
    # Gemini 2.5 Flash (analyzer + OCR V2)
    "gemini-2.5-flash": {
        "input": 0.30,
        "output": 2.50,
        "cached_input": 0.075,   # 75% sconto sul cached read
    },
    # Gemini 2.5 Flash Lite (classifier V2 + OCR fallback)
    "gemini-2.5-flash-lite": {
        "input": 0.10,
        "output": 0.40,
        "cached_input": None,    # non supporta caching
    },
    # Gemini 2.0 Flash (legacy, possibile usage)
    "gemini-2.0-flash": {
        "input": 0.10,
        "output": 0.40,
        "cached_input": 0.025,
    },
    # text-embedding-004 (eventuale uso futuro per RAG)
    "text-embedding-004": {
        "input": 0.025,
        "output": 0.0,
        "cached_input": None,
    },
    # DeepSeek V4 Flash — usato dallo spike `webapp/spike_deepseek/`.
    # Pricing ufficiale 2026/04/26 (cache hit ridotto a 1/10 del prezzo lancio).
    # Ref: https://api-docs.deepseek.com/quick_start/pricing
    "deepseek-v4-flash": {
        "input": 0.14,
        "output": 0.28,
        "cached_input": 0.0028,  # 50× più economico di Gemini Flash cached
    },
    # DeepSeek V4 Pro — disponibile per spike futuri (qualità top, 1.6T params).
    # Pricing scontato del 75% fino a 2026/05/31 (poi torna a $1.74/M out).
    "deepseek-v4-pro": {
        "input": 0.435,
        "output": 0.87,
        "cached_input": 0.003625,
    },
}


# Tasso di cambio USD → EUR (configurabile via env). Default ragionevole 2026.
USD_TO_EUR = float(os.environ.get("V2_USD_TO_EUR", "0.93"))


# Categorie di uso (per breakdown nel report)
KIND_CLASSIFY = "classify"
KIND_ANALYZE = "analyze"
KIND_OCR = "ocr"
KIND_EMBEDDING = "embedding"
KIND_OTHER = "other"
VALID_KINDS = {KIND_CLASSIFY, KIND_ANALYZE, KIND_OCR, KIND_EMBEDDING, KIND_OTHER}


# Path base dei report on disk
_WEBAPP_DIR = Path(__file__).resolve().parent.parent
TOKEN_USAGE_BASE_DIR = _WEBAPP_DIR.parent / "temp" / "token_usage"


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TokenCall:
    """Singola chiamata API tracciata."""
    model: str
    kind: str
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    # Telemetria estesa (Leva 3): nessun campo è obbligatorio per retro-compat,
    # ma quando popolati permettono debug per-call senza caricare lo storage
    duration_seconds: float = 0.0
    retry_count: int = 0
    error: Optional[str] = None
    batch_id: Optional[str] = None


@dataclass
class SessionMeter:
    """Aggregato token per una session."""
    session_id: str
    calls: List[TokenCall] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Storage in memoria + lock
# ──────────────────────────────────────────────────────────────────────────────

_sessions: Dict[str, SessionMeter] = {}
_global_lock = threading.Lock()
_session_locks: Dict[str, threading.Lock] = {}


def _get_session_lock(session_id: str) -> threading.Lock:
    """Lock dedicato per una session (created on demand)."""
    with _global_lock:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        return _session_locks[session_id]


def _get_or_create_meter(session_id: str) -> SessionMeter:
    if session_id not in _sessions:
        _sessions[session_id] = SessionMeter(session_id=session_id)
    return _sessions[session_id]


# ──────────────────────────────────────────────────────────────────────────────
# Pricing helpers
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_model_name(model: str) -> str:
    """
    Normalizza nomi modello che possono arrivare con prefissi diversi:
    'models/gemini-2.5-flash' o 'gemini-2.5-flash' → 'gemini-2.5-flash'.
    """
    if not model:
        return ""
    name = model.split("/")[-1].strip()
    return name


def compute_cost_usd(
    model: str,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
) -> float:
    """
    Calcola costo USD per una singola chiamata.

    cached_tokens sono SOTTRATTI da input_tokens (Gemini fattura
    full_input = cached_part + non_cached_part separately).
    """
    name = _normalize_model_name(model)
    pricing = PRICING.get(name)
    if pricing is None:
        # Modello sconosciuto: ritorna 0, non solleva
        return 0.0

    in_p = pricing.get("input") or 0.0
    out_p = pricing.get("output") or 0.0
    cached_p = pricing.get("cached_input")

    non_cached_input = max(0, input_tokens - cached_tokens)
    cost = (non_cached_input * in_p) / 1_000_000
    cost += (output_tokens * out_p) / 1_000_000
    if cached_p is not None and cached_tokens > 0:
        cost += (cached_tokens * cached_p) / 1_000_000
    return cost


def compute_cost_eur(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    return compute_cost_usd(model, input_tokens, cached_tokens, output_tokens) * USD_TO_EUR


# ──────────────────────────────────────────────────────────────────────────────
# Record API
# ──────────────────────────────────────────────────────────────────────────────

def _validate_session_id(session_id: str) -> bool:
    """Validation light (riusa convention V2)."""
    if not session_id or not isinstance(session_id, str):
        return False
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        return False
    return len(session_id) <= 200


def _persist_meter(meter: SessionMeter) -> None:
    """Scrivi snapshot JSON. Mai solleva."""
    try:
        TOKEN_USAGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
        path = TOKEN_USAGE_BASE_DIR / f"{meter.session_id}.json"
        report = compute_session_report(meter)
        # Atomic write
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as e:
        print(f"[V2 TOKEN] Persist fallito per {meter.session_id}: {e}")


def record_call(
    session_id: str,
    model: str,
    input_tokens: int = 0,
    cached_tokens: int = 0,
    output_tokens: int = 0,
    kind: str = KIND_OTHER,
    duration_seconds: float = 0.0,
    retry_count: int = 0,
    error: Optional[str] = None,
    batch_id: Optional[str] = None,
) -> bool:
    """
    Registra una chiamata API. Mai solleva eccezione.

    Args:
        session_id: identificatore sessione
        model: nome modello (es. 'gemini-2.5-flash')
        input_tokens: prompt_token_count
        cached_tokens: cached_content_token_count (sottoinsieme di input)
        output_tokens: candidates_token_count
        kind: categoria d'uso (classify/analyze/ocr/embedding/other)
        duration_seconds: tempo wall-clock della singola call (Leva 3)
        retry_count: numero retry effettuati (0 = primo tentativo riuscito)
        error: stringa breve d'errore se la call non è andata a buon fine
        batch_id: identificatore opzionale del batch/file (debug per-call)

    Returns:
        True se registrato, False se input invalido.
    """
    if not _validate_session_id(session_id):
        return False
    if kind not in VALID_KINDS:
        kind = KIND_OTHER

    # Normalizza valori: niente negativi, accetta solo int
    input_tokens = max(0, int(input_tokens or 0))
    cached_tokens = max(0, int(cached_tokens or 0))
    output_tokens = max(0, int(output_tokens or 0))
    # cached_tokens non può eccedere input_tokens (vincolo Gemini)
    cached_tokens = min(cached_tokens, input_tokens)
    duration_seconds = max(0.0, float(duration_seconds or 0.0))
    retry_count = max(0, int(retry_count or 0))

    call = TokenCall(
        model=_normalize_model_name(model),
        kind=kind,
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        output_tokens=output_tokens,
        duration_seconds=round(duration_seconds, 3),
        retry_count=retry_count,
        error=(str(error)[:200] if error else None),
        batch_id=(str(batch_id)[:100] if batch_id else None),
    )

    with _get_session_lock(session_id):
        meter = _get_or_create_meter(session_id)
        meter.calls.append(call)
        _persist_meter(meter)
    return True


def record_from_response(
    session_id: str,
    response: Any,
    model: str,
    kind: str = KIND_OTHER,
    duration_seconds: float = 0.0,
    retry_count: int = 0,
    error: Optional[str] = None,
    batch_id: Optional[str] = None,
) -> bool:
    """
    Estrae automaticamente i token da `response.usage_metadata` del SDK genai.
    Tollerante: se i campi non ci sono, registra 0 (mai eccezione).

    I parametri di telemetria estesa (duration/retry/error/batch_id) sono
    opzionali e non incidono sul calcolo dei token.
    """
    if response is None:
        # Anche senza response, se ci hanno passato un errore lo registriamo
        if error or duration_seconds > 0:
            return record_call(
                session_id=session_id,
                model=model,
                kind=kind,
                duration_seconds=duration_seconds,
                retry_count=retry_count,
                error=error,
                batch_id=batch_id,
            )
        return False
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        # Alcuni stream chunk non hanno usage_metadata: non è un errore.
        # Se però c'è telemetria extra, la registriamo comunque.
        if error or duration_seconds > 0:
            return record_call(
                session_id=session_id,
                model=model,
                kind=kind,
                duration_seconds=duration_seconds,
                retry_count=retry_count,
                error=error,
                batch_id=batch_id,
            )
        return False

    try:
        in_t = getattr(usage, "prompt_token_count", 0) or 0
        cached = getattr(usage, "cached_content_token_count", 0) or 0
        out_t = getattr(usage, "candidates_token_count", 0) or 0
    except Exception:
        return False

    return record_call(
        session_id=session_id,
        model=model,
        input_tokens=in_t,
        cached_tokens=cached,
        output_tokens=out_t,
        kind=kind,
        duration_seconds=duration_seconds,
        retry_count=retry_count,
        error=error,
        batch_id=batch_id,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────────────────────────────────────

def compute_session_report(meter: SessionMeter) -> Dict[str, Any]:
    """
    Calcola il report completo per una session.

    Output structure:
    {
        "session_id": "...",
        "calls_count": N,
        "total_input": int, "total_cached": int, "total_output": int,
        "total_cost_usd": float, "total_cost_eur": float,
        "saved_by_caching_usd": float,
        "by_model": { "gemini-2.5-flash": { calls, input, cached, output, cost_usd, cost_eur } },
        "by_kind": { "classify": {...}, "analyze": {...} },
    }
    """
    if not meter.calls:
        return {
            "session_id": meter.session_id,
            "calls_count": 0,
            "total_input": 0, "total_cached": 0, "total_output": 0,
            "total_cost_usd": 0.0, "total_cost_eur": 0.0,
            "saved_by_caching_usd": 0.0,
            "total_duration_seconds": 0.0,
            "total_retries": 0,
            "errors_count": 0,
            "errors_sample": [],
            "by_model": {},
            "by_kind": {},
        }

    by_model: Dict[str, Dict[str, Any]] = {}
    by_kind: Dict[str, Dict[str, Any]] = {}
    total_in = total_cached = total_out = 0
    total_cost_usd = 0.0
    saved_by_caching_usd = 0.0
    total_duration = 0.0
    total_retries = 0
    errors_sample: List[Dict[str, Any]] = []

    for call in meter.calls:
        cost_usd = compute_cost_usd(
            call.model, call.input_tokens, call.cached_tokens, call.output_tokens,
        )
        # Se non ci fosse caching, il costo sarebbe più alto: stima il risparmio
        cost_no_cache_usd = compute_cost_usd(
            call.model, call.input_tokens, 0, call.output_tokens,
        )
        saved_by_caching_usd += max(0.0, cost_no_cache_usd - cost_usd)

        total_in += call.input_tokens
        total_cached += call.cached_tokens
        total_out += call.output_tokens
        total_cost_usd += cost_usd
        total_duration += call.duration_seconds
        total_retries += call.retry_count
        if call.error:
            if len(errors_sample) < 20:
                errors_sample.append({
                    "kind": call.kind,
                    "model": call.model,
                    "batch_id": call.batch_id,
                    "retry_count": call.retry_count,
                    "duration_seconds": call.duration_seconds,
                    "error": call.error,
                })

        # by_model
        m = by_model.setdefault(call.model, {
            "calls": 0, "input": 0, "cached": 0, "output": 0, "cost_usd": 0.0,
            "duration_seconds": 0.0, "retries": 0, "errors": 0,
        })
        m["calls"] += 1
        m["input"] += call.input_tokens
        m["cached"] += call.cached_tokens
        m["output"] += call.output_tokens
        m["cost_usd"] += cost_usd
        m["duration_seconds"] += call.duration_seconds
        m["retries"] += call.retry_count
        if call.error:
            m["errors"] += 1

        # by_kind
        k = by_kind.setdefault(call.kind, {
            "calls": 0, "input": 0, "cached": 0, "output": 0, "cost_usd": 0.0,
            "duration_seconds": 0.0, "retries": 0, "errors": 0,
        })
        k["calls"] += 1
        k["input"] += call.input_tokens
        k["cached"] += call.cached_tokens
        k["output"] += call.output_tokens
        k["cost_usd"] += cost_usd
        k["duration_seconds"] += call.duration_seconds
        k["retries"] += call.retry_count
        if call.error:
            k["errors"] += 1

    # Aggiungi cost_eur + arrotonda durations ai breakdowns
    for d in (by_model, by_kind):
        for v in d.values():
            v["cost_eur"] = round(v["cost_usd"] * USD_TO_EUR, 5)
            v["cost_usd"] = round(v["cost_usd"], 5)
            v["duration_seconds"] = round(v["duration_seconds"], 2)

    errors_count = sum(1 for c in meter.calls if c.error)

    return {
        "session_id": meter.session_id,
        "calls_count": len(meter.calls),
        "total_input": total_in,
        "total_cached": total_cached,
        "total_output": total_out,
        "total_cost_usd": round(total_cost_usd, 5),
        "total_cost_eur": round(total_cost_usd * USD_TO_EUR, 5),
        "saved_by_caching_usd": round(saved_by_caching_usd, 5),
        "saved_by_caching_eur": round(saved_by_caching_usd * USD_TO_EUR, 5),
        "total_duration_seconds": round(total_duration, 2),
        "total_retries": total_retries,
        "errors_count": errors_count,
        "errors_sample": errors_sample,
        "by_model": by_model,
        "by_kind": by_kind,
    }


def get_session_report(session_id: str) -> Dict[str, Any]:
    """Snapshot del report per una session (mai eccezione)."""
    if not _validate_session_id(session_id):
        return {"error": "invalid_session_id"}

    with _get_session_lock(session_id):
        meter = _sessions.get(session_id)
        if meter is None:
            return {
                "session_id": session_id,
                "calls_count": 0,
                "total_input": 0, "total_cached": 0, "total_output": 0,
                "total_cost_usd": 0.0, "total_cost_eur": 0.0,
                "total_duration_seconds": 0.0,
                "total_retries": 0,
                "errors_count": 0,
                "errors_sample": [],
                "by_model": {}, "by_kind": {},
            }
        return compute_session_report(meter)


def format_report_table(session_id: str) -> str:
    """Report human-readable in formato tabellare per logging/SSE."""
    report = get_session_report(session_id)

    if report.get("calls_count", 0) == 0:
        return f"=== TOKEN REPORT — session {session_id} ===\nNessuna chiamata registrata."

    lines = [
        f"=== AUDIT V2 TOKEN REPORT — session {session_id} ===",
        f"{'Modello (kind)':<40}{'Calls':>7}{'In tok':>10}{'Cached':>10}{'Out tok':>10}{'Costo €':>11}",
        "─" * 88,
    ]

    # Aggrega per (model, kind) per leggibilità
    combined: Dict[str, Dict[str, Any]] = {}
    with _get_session_lock(session_id):
        meter = _sessions.get(session_id)
        if meter:
            for c in meter.calls:
                key = f"{c.model} ({c.kind})"
                e = combined.setdefault(key, {
                    "calls": 0, "input": 0, "cached": 0, "output": 0, "cost_usd": 0.0,
                })
                e["calls"] += 1
                e["input"] += c.input_tokens
                e["cached"] += c.cached_tokens
                e["output"] += c.output_tokens
                e["cost_usd"] += compute_cost_usd(
                    c.model, c.input_tokens, c.cached_tokens, c.output_tokens
                )

    for key in sorted(combined.keys()):
        e = combined[key]
        cost_eur = e["cost_usd"] * USD_TO_EUR
        lines.append(
            f"{key[:40]:<40}"
            f"{e['calls']:>7}"
            f"{e['input']:>10,}"
            f"{e['cached']:>10,}"
            f"{e['output']:>10,}"
            f"{cost_eur:>11.4f}"
        )

    lines.append("─" * 88)
    lines.append(
        f"{'TOTALE':<40}"
        f"{report['calls_count']:>7}"
        f"{report['total_input']:>10,}"
        f"{report['total_cached']:>10,}"
        f"{report['total_output']:>10,}"
        f"{report['total_cost_eur']:>11.4f}"
    )

    if report.get("saved_by_caching_eur", 0) > 0:
        lines.append("")
        lines.append(
            f"Risparmio caching:           "
            f"{report['saved_by_caching_eur']:>11.4f} €"
        )

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Reset (test + cleanup)
# ──────────────────────────────────────────────────────────────────────────────

def reset_session(session_id: str) -> None:
    """Cancella tutti i dati in memoria E su disco per una session."""
    if not _validate_session_id(session_id):
        return
    with _get_session_lock(session_id):
        _sessions.pop(session_id, None)
        path = TOKEN_USAGE_BASE_DIR / f"{session_id}.json"
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def reset_all_sessions() -> None:
    """Reset globale (utile per test)."""
    with _global_lock:
        _sessions.clear()
        _session_locks.clear()
