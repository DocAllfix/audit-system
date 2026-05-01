"""
V2 — Text Extractor (Fase 1).

Estrazione testo nativo da PDF tramite pypdfium2 (motore di Google Chrome).
Sostituisce PyPDF2 di V1 dove possibile, evitando di mandare a OCR Vision
documenti che hanno già il text layer. Riduce drasticamente costo e latenza.

Strategia:
1. Tenta estrazione testo nativo via pypdfium2.
2. Calcola un "quality score" sul testo estratto (chars stampabili / total chars).
3. Se quality score basso o testo troppo corto → marca per OCR fallback.
4. Edge case (password, corrotto, troppo grande) gestiti con fallback espliciti.

Mai solleva eccezioni: tutti i fallimenti producono `(text="", method="...")` con
metodo che spiega cosa è successo. Il chiamante decide se routare in OCR.
"""
from __future__ import annotations

import os
from typing import Tuple

try:
    import pypdfium2 as pdfium
    HAS_PDFIUM = True
except ImportError:
    HAS_PDFIUM = False
    pdfium = None  # type: ignore


# Soglie di qualità per accettare il testo come "nativo valido"
MIN_CHARS_NATIVE_OK = 200          # Sotto questa soglia → routing OCR
MIN_PRINTABLE_RATIO = 0.7          # Sotto → testo "garbage" (font mal embedded)
MAX_FILE_SIZE_NATIVE = 100 * 1024 * 1024   # 100 MB hard limit
DEFAULT_MAX_CHARS = 200_000        # Cap output per evitare blob gigantesche


# Metodi possibili (per logging / telemetria SSE)
METHOD_NATIVE_OK = "pdfium_native_ok"
METHOD_NATIVE_PARTIAL = "pdfium_native_partial"
METHOD_NATIVE_GARBAGE = "pdfium_native_garbage"
METHOD_NEEDS_OCR_EMPTY = "needs_ocr_empty"
METHOD_NEEDS_OCR_TOO_SHORT = "needs_ocr_too_short"
METHOD_FAILED_PASSWORD = "failed_password_protected"
METHOD_FAILED_CORRUPTED = "failed_corrupted"
METHOD_FAILED_TOO_LARGE = "failed_too_large"
METHOD_FAILED_NO_PDFIUM = "failed_no_pdfium"
METHOD_FAILED_GENERIC = "failed_generic"


def _printable_ratio(text: str) -> float:
    """
    Ritorna la frazione di caratteri "stampabili" sul totale.
    Stampabili = ASCII printable + accentate latine + whitespace.
    Sotto 0.7 il testo è probabilmente font mal embedded (nostro segnale OCR).
    """
    if not text:
        return 0.0
    total = len(text)
    if total == 0:
        return 0.0
    printable = sum(
        1
        for c in text
        if c.isprintable() or c in "\n\r\t "
    )
    return printable / total


def _extract_with_pdfium(pdf_path: str, max_chars: int) -> str:
    """
    Estrazione cruda con pypdfium2. Solleva PdfiumError o eccezioni native
    su errori di basso livello — il chiamante deve catturare.
    """
    parts = []
    total_chars = 0
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        for page_idx in range(len(pdf)):
            if total_chars >= max_chars:
                break
            page = pdf[page_idx]
            try:
                textpage = page.get_textpage()
                try:
                    page_text = textpage.get_text_range() or ""
                finally:
                    textpage.close()
            finally:
                page.close()

            if page_text:
                parts.append(page_text)
                total_chars += len(page_text)
    finally:
        pdf.close()

    return "".join(parts)[:max_chars]


def extract_native_text(
    pdf_path: str,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Tuple[str, str]:
    """
    Estrae testo nativo da un PDF. Mai solleva eccezioni.

    Args:
        pdf_path: percorso del file PDF
        max_chars: cap sulla dimensione del testo restituito

    Returns:
        Tuple (text, method) dove:
            - text: testo estratto, "" se fallito o vuoto
            - method: identifica esito (vedi METHOD_* costanti)

    I caller devono trattare:
        - method == METHOD_NATIVE_OK         → usa testo direttamente
        - method == METHOD_NATIVE_PARTIAL    → usa testo, magari logga
        - method.startswith("needs_ocr")     → manda in OCR fallback
        - method.startswith("failed")        → file non recuperabile via testo
                                                nativo; valuta OCR su disponibilità
    """
    if not HAS_PDFIUM:
        return "", METHOD_FAILED_NO_PDFIUM

    if not os.path.isfile(pdf_path):
        return "", METHOD_FAILED_CORRUPTED

    # Hard limit dimensione file
    try:
        size = os.path.getsize(pdf_path)
    except OSError:
        return "", METHOD_FAILED_CORRUPTED

    if size > MAX_FILE_SIZE_NATIVE:
        return "", METHOD_FAILED_TOO_LARGE

    # Tentativo estrazione
    try:
        text = _extract_with_pdfium(pdf_path, max_chars)
    except pdfium.PdfiumError as e:  # type: ignore[union-attr]
        msg = str(e).lower()
        # Password protetto: pdfium emette messaggi specifici con "password"
        # o "incorrect password" o codice 4 (FPDF_ERR_PASSWORD)
        if "password" in msg or "incorrect" in msg:
            return "", METHOD_FAILED_PASSWORD
        # Tutti gli altri PdfiumError (data format error, file not found, ecc.) → corrotto
        return "", METHOD_FAILED_CORRUPTED
    except Exception:
        # Cattura tutto: pdfium può sollevare eccezioni di basso livello
        # non sempre tipizzate come PdfiumError.
        return "", METHOD_FAILED_GENERIC

    # Classificazione esito
    if not text or not text.strip():
        return "", METHOD_NEEDS_OCR_EMPTY

    text_clean = text.strip()
    chars = len(text_clean)

    if chars < MIN_CHARS_NATIVE_OK:
        return text_clean, METHOD_NEEDS_OCR_TOO_SHORT

    ratio = _printable_ratio(text_clean)
    if ratio < MIN_PRINTABLE_RATIO:
        # Testo presente ma "garbage" (probabile font mal embedded).
        # Restituiamo comunque il testo: il chiamante può decidere se mandare
        # ulteriormente in OCR o accettare best-effort.
        return text_clean, METHOD_NATIVE_GARBAGE

    # Se ci avviciniamo al cap, segniamo "partial" per trasparenza
    if chars >= max_chars * 0.95:
        return text_clean, METHOD_NATIVE_PARTIAL

    return text_clean, METHOD_NATIVE_OK


def needs_ocr(method: str) -> bool:
    """
    Helper per il routing: data una `method` ritornata da extract_native_text,
    dice se il file deve essere mandato in OCR fallback.
    """
    return method.startswith("needs_ocr") or method == METHOD_FAILED_GENERIC


def is_unrecoverable(method: str) -> bool:
    """
    Helper: il file non è recuperabile né via nativo né via OCR
    (es. password protected, corrotto, troppo grande).
    """
    return method in (
        METHOD_FAILED_PASSWORD,
        METHOD_FAILED_CORRUPTED,
        METHOD_FAILED_TOO_LARGE,
        METHOD_FAILED_NO_PDFIUM,
    )
