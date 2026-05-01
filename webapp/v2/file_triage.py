"""
V2 — File Triage (Fase 1).

Smista una lista di file estratti dalla ZIP in tre code:
- `native_text`: PDF con text layer leggibile, già estratti via pypdfium2
- `needs_ocr`: PDF/immagini che richiedono OCR Vision (Fase 4)
- `unrecoverable`: file irrecuperabili (password, corrotti, troppo grandi)

Output preserva il formato dei dict V1 con campi aggiuntivi per la pipeline V2:
- `extracted_text`: il testo già estratto (None se il file deve andare in OCR)
- `extraction_method`: stringa identificativa dell'esito
- `extraction_chars`: lunghezza del testo estratto

Nessun side effect oltre alla lettura dei file.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from v2.text_extractor import (
    METHOD_FAILED_NO_PDFIUM,
    extract_native_text,
    is_unrecoverable,
    needs_ocr,
)


# Chiavi della dict di output di triage_files
KEY_NATIVE = "native_text"
KEY_NEEDS_OCR = "needs_ocr"
KEY_UNRECOVERABLE = "unrecoverable"
KEY_NON_PDF = "non_pdf"     # docx/excel/etc → V2 ancora non li gestisce, restano a V1


# Estensioni che la Fase 1 si occupa di triare. Le altre passano dritte come "non_pdf".
PDF_EXTENSIONS = {".pdf"}


def _is_pdf(file_info: Dict[str, Any]) -> bool:
    fname = file_info.get("filename", "")
    ext = os.path.splitext(fname)[1].lower()
    if ext in PDF_EXTENSIONS:
        return True
    # Heuristica fallback: la categoria V1 può segnare "pdf"
    return file_info.get("category") == "pdf"


def _annotate(file_info: Dict[str, Any], text: str, method: str) -> Dict[str, Any]:
    """
    Ritorna una NUOVA dict con i campi V2 aggiunti. Non muta l'originale
    per evitare side effect su V1 nel caso il caller condivida le strutture.
    """
    enriched = dict(file_info)
    enriched["extracted_text"] = text or None
    enriched["extraction_method"] = method
    enriched["extraction_chars"] = len(text) if text else 0
    return enriched


def triage_files(
    files: List[Dict[str, Any]],
    max_chars_per_file: int = 200_000,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Smista i file in code di destinazione applicando l'estrazione nativa.

    Args:
        files: lista di dict con `filename`, `path`, `size`, `category`
               (formato output di `extract_zip` in V1).
        max_chars_per_file: cap sulla dimensione del testo per file.

    Returns:
        Dict con 4 liste (alcune possono essere vuote):
            - "native_text": file con testo nativo OK
            - "needs_ocr": file da mandare a Gemini OCR Vision
            - "unrecoverable": file che non si possono recuperare
            - "non_pdf": file non PDF (docx, excel, ecc.) — passthrough

    Mai solleva eccezioni: errori di estrazione finiscono nelle code corrette.
    """
    out: Dict[str, List[Dict[str, Any]]] = {
        KEY_NATIVE: [],
        KEY_NEEDS_OCR: [],
        KEY_UNRECOVERABLE: [],
        KEY_NON_PDF: [],
    }

    for f in files:
        if not _is_pdf(f):
            # Non-PDF: passthrough (saranno gestiti da V1 o da handler V2 dedicato)
            out[KEY_NON_PDF].append(_annotate(f, "", "non_pdf_passthrough"))
            continue

        path = f.get("path", "")
        if not path or not os.path.isfile(path):
            out[KEY_UNRECOVERABLE].append(_annotate(f, "", "missing_path"))
            continue

        text, method = extract_native_text(path, max_chars=max_chars_per_file)
        enriched = _annotate(f, text, method)

        if is_unrecoverable(method):
            out[KEY_UNRECOVERABLE].append(enriched)
        elif needs_ocr(method):
            out[KEY_NEEDS_OCR].append(enriched)
        else:
            # Include METHOD_NATIVE_OK, METHOD_NATIVE_PARTIAL, METHOD_NATIVE_GARBAGE
            # Garbage finisce ancora in native_text: il chiamante può raffinare
            # il routing sull'attributo `extraction_method`.
            out[KEY_NATIVE].append(enriched)

    return out


def triage_summary(triaged: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
    """
    Riepilogo numerico per logging/SSE.

    Returns:
        Dict {bucket: count, "total": N, "native_pct": float}
    """
    counts = {k: len(v) for k, v in triaged.items()}
    total = sum(counts.values())
    counts["total"] = total
    counts["native_pct"] = (
        round(100.0 * counts.get(KEY_NATIVE, 0) / total, 1) if total else 0.0
    )
    return counts


def split_by_method(
    triaged_native: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Sub-split del bucket `native_text` per granularità telemetria SSE.

    Returns:
        (clean, partial, garbage) — tre liste disgiunte
    """
    from v2.text_extractor import (
        METHOD_NATIVE_GARBAGE,
        METHOD_NATIVE_OK,
        METHOD_NATIVE_PARTIAL,
    )

    clean, partial, garbage = [], [], []
    for f in triaged_native:
        m = f.get("extraction_method", "")
        if m == METHOD_NATIVE_OK:
            clean.append(f)
        elif m == METHOD_NATIVE_PARTIAL:
            partial.append(f)
        elif m == METHOD_NATIVE_GARBAGE:
            garbage.append(f)
    return clean, partial, garbage
