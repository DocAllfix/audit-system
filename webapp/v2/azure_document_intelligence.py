"""
V2 — Azure Document Intelligence OCR engine (Read API).

Wrapper sostitutivo di gemini_ocr_v2.py per la fase OCR. Vantaggi vs Gemini
Vision Files API (validati in test del 2026-05-04):

- 2.6s/pagina vs 5-15s/file Gemini (−50% a −80% latenza)
- 1 round-trip HTTP (POST + poll) vs 3 (upload + vision + delete)
- Niente Files API gestione/cleanup
- Niente bug encoding nomi file con accenti (hang silenziosi 240s)
- 15 TPS default + autoscale (vs ~5-8 worker sicuri Gemini)
- €1.28/1000 pagine vs ~€7/1000 Gemini Vision (−82% costo)
- GDPR EU compliant (region Sweden Central)

Mantiene contratto identico al modulo gemini_ocr_v2:
    OCRResult(filename, path, success, text, method, chars, error, ...)
    ocr_extract_files(client, files, session_id, ..., on_progress=None)

Cosi' il pipeline.py puo' switchare engine via env var V2_OCR_ENGINE
senza altre modifiche.

Env var richieste:
    AZURE_DOC_INTEL_ENDPOINT       https://<resource>.cognitiveservices.azure.com/
    AZURE_DOC_INTEL_KEY            chiave API (32+ char)
    AZURE_DOC_INTEL_REGION         (informativo, es. swedencentral)

Env var opzionali:
    V2_AZURE_DI_PARALLEL           worker paralleli (default 12)
    V2_AZURE_DI_TIMEOUT            timeout per singolo file in sec (default 60)
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

# Concorrenza paralleli: Azure DI default 15 TPS, restiamo sotto per safety.
MAX_AZURE_DI_PARALLEL = int(os.environ.get("V2_AZURE_DI_PARALLEL", "12"))

# Timeout per singolo file (Azure DI di norma risponde in 2-10s, 60s e' large margin)
AZURE_DI_TIMEOUT = int(os.environ.get("V2_AZURE_DI_TIMEOUT", "60"))

# Cap output per file (allineato al cap di gemini_ocr_v2 per evitare blob giant)
MAX_OCR_OUTPUT_CHARS = 100_000

# Modello Azure DI: prebuilt-read e' OCR puro (testo), molto piu' economico di
# prebuilt-layout (€1.28 vs €8.55 per 1000 pages). Per AUDIT-OS basta il testo.
AZURE_DI_MODEL = os.environ.get("V2_AZURE_DI_MODEL", "prebuilt-read")


# ──────────────────────────────────────────────────────────────────────────────
# Result type (identico a gemini_ocr_v2.OCRResult per compat drop-in)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AzureDIResult:
    """Esito OCR via Azure Document Intelligence per un singolo file."""
    filename: str
    path: str
    success: bool
    text: str = ""
    method: str = ""           # "azure_di_read", "failed"
    chars: int = 0
    error: Optional[str] = None
    pages: int = 0
    duration_seconds: float = 0.0
    # Campi compat con OCRResult Gemini (sempre None/False per Azure DI)
    file_uri: Optional[str] = None
    used_cached_uri: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Client builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_client():
    """
    Costruisce DocumentIntelligenceClient da env var.
    Lazy import del SDK per non rompere import del modulo se SDK non installato.
    """
    endpoint = os.environ.get("AZURE_DOC_INTEL_ENDPOINT", "").strip()
    key = os.environ.get("AZURE_DOC_INTEL_KEY", "").strip()
    if not endpoint:
        raise ValueError("AZURE_DOC_INTEL_ENDPOINT non settato")
    if not key:
        raise ValueError("AZURE_DOC_INTEL_KEY non settato")

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError as e:
        raise RuntimeError(
            "Pacchetto 'azure-ai-documentintelligence' non installato. "
            "Esegui: pip install azure-ai-documentintelligence"
        ) from e

    return DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key),
    )


# ──────────────────────────────────────────────────────────────────────────────
# OCR singolo file
# ──────────────────────────────────────────────────────────────────────────────

def _ocr_single_file(
    client,
    file_info: Dict[str, Any],
    meter_session_id: Optional[str] = None,
) -> AzureDIResult:
    """
    Processa un singolo file via Azure DI Read API.
    Mai solleva eccezioni: errori finiscono in AzureDIResult(success=False).
    """
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    from azure.core.exceptions import (
        ClientAuthenticationError, HttpResponseError, ServiceRequestError,
    )

    filename = file_info.get("filename", "unknown")
    path = file_info.get("path", "")

    if not path or not os.path.isfile(path):
        return AzureDIResult(
            filename=filename, path=path, success=False,
            method="failed", error="missing_path",
        )

    try:
        size = os.path.getsize(path)
    except OSError as e:
        return AzureDIResult(
            filename=filename, path=path, success=False,
            method="failed", error=f"stat_failed: {e}",
        )

    if size == 0:
        return AzureDIResult(
            filename=filename, path=path, success=False,
            method="failed", error="empty_file",
        )

    # Azure DI Read: limite 500 MB
    if size > 500 * 1024 * 1024:
        return AzureDIResult(
            filename=filename, path=path, success=False,
            method="failed", error=f"file_too_large: {size}",
        )

    t0 = time.monotonic()
    try:
        with open(path, "rb") as f:
            file_bytes = f.read()

        poller = client.begin_analyze_document(
            model_id=AZURE_DI_MODEL,
            body=AnalyzeDocumentRequest(bytes_source=file_bytes),
        )
        result = poller.result()

        text = (result.content or "").strip()
        if len(text) > MAX_OCR_OUTPUT_CHARS:
            text = text[:MAX_OCR_OUTPUT_CHARS] + "\n[OCR TRONCATO PER ECCESSO LUNGHEZZA]"

        n_pages = len(result.pages) if result.pages else 0
        duration = round(time.monotonic() - t0, 3)

        if meter_session_id:
            _maybe_record_meter(
                meter_session_id, AZURE_DI_MODEL, n_pages, duration,
            )

        if not text:
            return AzureDIResult(
                filename=filename, path=path, success=False,
                method="failed", error="empty_ocr_output",
                pages=n_pages, duration_seconds=duration,
            )

        return AzureDIResult(
            filename=filename, path=path, success=True,
            text=text, method="azure_di_read", chars=len(text),
            pages=n_pages, duration_seconds=duration,
        )

    except ClientAuthenticationError as e:
        return AzureDIResult(
            filename=filename, path=path, success=False,
            method="failed", error=f"auth_failed: {e}",
            duration_seconds=round(time.monotonic() - t0, 3),
        )
    except HttpResponseError as e:
        # 400/413/415 ecc — file non processabile, non retry
        sc = getattr(e, "status_code", None)
        return AzureDIResult(
            filename=filename, path=path, success=False,
            method="failed", error=f"http_{sc}: {e}",
            duration_seconds=round(time.monotonic() - t0, 3),
        )
    except ServiceRequestError as e:
        # Network transient
        return AzureDIResult(
            filename=filename, path=path, success=False,
            method="failed", error=f"network: {e}",
            duration_seconds=round(time.monotonic() - t0, 3),
        )
    except Exception as e:
        return AzureDIResult(
            filename=filename, path=path, success=False,
            method="failed", error=f"unexpected: {type(e).__name__}: {e}",
            duration_seconds=round(time.monotonic() - t0, 3),
        )


def _maybe_record_meter(
    session_id: str,
    model: str,
    pages: int,
    duration: float,
) -> None:
    """Best-effort recording su token_meter (Azure DI fattura per pagine, non token)."""
    try:
        from v2 import token_meter
        # Convenzione: registro come 1 page = 100 'unit' fittizie cosi' il
        # report aggregato resta leggibile. Il pricing reale si calcola fuori.
        token_meter.record_call(
            session_id=session_id,
            model=model,
            kind="ocr",
            input_tokens=pages * 100,  # placeholder, Azure DI non usa token
            output_tokens=0,
            duration_seconds=duration,
        )
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# API pubblica — drop-in replacement di gemini_ocr_v2.ocr_extract_files
# ──────────────────────────────────────────────────────────────────────────────

def ocr_extract_files(
    client=None,
    files: Optional[List[Dict[str, Any]]] = None,
    session_id: str = "",
    cleanup_after: bool = True,        # ignorato (Azure DI non ha files API)
    max_workers: int = MAX_AZURE_DI_PARALLEL,
    meter_session_id: Optional[str] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> List[AzureDIResult]:
    """
    Esegue OCR via Azure Document Intelligence su una lista di file.

    Drop-in replacement di gemini_ocr_v2.ocr_extract_files: stessa firma,
    stesso ritorno (AzureDIResult ha campi compat con OCRResult).

    Args:
        client: ignorato (costruito internamente da env var)
        files: lista file_info dict (formato file_triage V2)
        session_id: identificatore sessione (informativo)
        cleanup_after: ignorato (Azure DI non ha files API persistente)
        max_workers: concorrenza paralleli (default 12, max 15 TPS Azure DI)
        meter_session_id: per token_meter
        on_progress: callback (completed_int, total_int, current_filename_str)

    Returns:
        Lista AzureDIResult, una per file di input, ordine preservato.
    """
    files = files or []
    if not files:
        return []

    # Build client lazy (gestisce env var mancanti con error chiaro)
    try:
        di_client = _build_client()
    except (ValueError, RuntimeError) as e:
        # Tutti i file falliscono con stesso errore
        return [
            AzureDIResult(
                filename=f.get("filename", "unknown"),
                path=f.get("path", ""),
                success=False, method="failed",
                error=f"client_init_failed: {e}",
            )
            for f in files
        ]

    workers = max(1, min(max_workers, len(files)))
    results: List[Optional[AzureDIResult]] = [None] * len(files)

    # NB: NON usiamo `with ThreadPoolExecutor(...) as ex` perche' shutdown
    # implicito blocca su thread orfani (lesson learnt da gemini_ocr_v2 Fix 12).
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        future_to_idx = {
            executor.submit(_ocr_single_file, di_client, f, meter_session_id): i
            for i, f in enumerate(files)
        }
        completed = 0
        total = len(files)
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result(timeout=AZURE_DI_TIMEOUT)
            except Exception as e:
                f = files[idx]
                results[idx] = AzureDIResult(
                    filename=f.get("filename", "unknown"),
                    path=f.get("path", ""),
                    success=False, method="failed",
                    error=f"timeout_or_executor_error: {e}",
                )
                try:
                    future.cancel()
                except Exception:
                    pass

            completed += 1
            if on_progress is not None:
                try:
                    cur = results[idx]
                    on_progress(completed, total, cur.filename if cur else "")
                except Exception:
                    pass
    finally:
        try:
            executor.shutdown(wait=False)
        except Exception:
            pass

    return [r for r in results if r is not None]


# ──────────────────────────────────────────────────────────────────────────────
# Summary (compat con gemini_ocr_v2.ocr_summary)
# ──────────────────────────────────────────────────────────────────────────────

def ocr_summary(results: List[AzureDIResult]) -> Dict[str, Any]:
    """Riepilogo per logging/SSE telemetria."""
    if not results:
        return {"total": 0, "success": 0, "failed": 0, "total_chars": 0,
                "total_pages": 0, "engine": "azure_di"}
    success = sum(1 for r in results if r.success)
    total_chars = sum(r.chars for r in results)
    total_pages = sum(r.pages for r in results)
    return {
        "total": len(results),
        "success": success,
        "failed": len(results) - success,
        "success_pct": round(100.0 * success / len(results), 1),
        "total_chars": total_chars,
        "total_pages": total_pages,
        "avg_chars": int(total_chars / max(success, 1)),
        "engine": "azure_di",
    }
