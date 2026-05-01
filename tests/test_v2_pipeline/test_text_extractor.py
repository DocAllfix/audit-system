"""
Test V2 Fase 1 — text_extractor.
"""
from __future__ import annotations

from v2 import text_extractor as tx


def test_extract_native_ok(sample_pdfs):
    """PDF con text layer ben formato → METHOD_NATIVE_OK."""
    text, method = tx.extract_native_text(str(sample_pdfs["native_ok"]))
    assert method in (tx.METHOD_NATIVE_OK, tx.METHOD_NATIVE_PARTIAL)
    assert "Lorem" in text or len(text) > 200


def test_extract_short_text_routes_to_ocr(sample_pdfs):
    """PDF con poco testo → METHOD_NEEDS_OCR_TOO_SHORT (chars < 200)."""
    text, method = tx.extract_native_text(str(sample_pdfs["native_short"]))
    assert method == tx.METHOD_NEEDS_OCR_TOO_SHORT
    # Il testo è restituito anche se sotto soglia: il chiamante decide
    assert text  # non vuoto, ma sotto MIN_CHARS_NATIVE_OK


def test_extract_image_only_pdf_routes_to_ocr(sample_pdfs):
    """PDF senza text layer → METHOD_NEEDS_OCR_EMPTY."""
    text, method = tx.extract_native_text(str(sample_pdfs["image_only"]))
    assert method == tx.METHOD_NEEDS_OCR_EMPTY
    assert text == ""


def test_extract_corrupted_pdf_returns_failed(sample_pdfs):
    """PDF corrotto → METHOD_FAILED_CORRUPTED, no exception."""
    text, method = tx.extract_native_text(str(sample_pdfs["corrupted"]))
    assert method == tx.METHOD_FAILED_CORRUPTED
    assert text == ""


def test_extract_missing_file_returns_failed(sample_pdfs):
    """File non esistente → METHOD_FAILED_CORRUPTED, no exception."""
    text, method = tx.extract_native_text(str(sample_pdfs["missing"]))
    assert method == tx.METHOD_FAILED_CORRUPTED
    assert text == ""


def test_max_chars_cap_respected(sample_pdfs):
    """Cap su max_chars deve essere rispettato."""
    text, method = tx.extract_native_text(str(sample_pdfs["native_ok"]), max_chars=100)
    assert len(text) <= 100


def test_helpers_routing():
    """Helpers needs_ocr / is_unrecoverable classificano correttamente."""
    assert tx.needs_ocr(tx.METHOD_NEEDS_OCR_EMPTY) is True
    assert tx.needs_ocr(tx.METHOD_NEEDS_OCR_TOO_SHORT) is True
    assert tx.needs_ocr(tx.METHOD_NATIVE_OK) is False
    assert tx.needs_ocr(tx.METHOD_FAILED_GENERIC) is True

    assert tx.is_unrecoverable(tx.METHOD_FAILED_PASSWORD) is True
    assert tx.is_unrecoverable(tx.METHOD_FAILED_CORRUPTED) is True
    assert tx.is_unrecoverable(tx.METHOD_FAILED_TOO_LARGE) is True
    assert tx.is_unrecoverable(tx.METHOD_NATIVE_OK) is False
    assert tx.is_unrecoverable(tx.METHOD_NEEDS_OCR_EMPTY) is False


def test_printable_ratio_garbage_detection():
    """Testo con caratteri non stampabili sotto soglia → ratio basso."""
    garbage = "\x00\x01\x02" * 100 + "ok"
    ratio = tx._printable_ratio(garbage)
    assert ratio < tx.MIN_PRINTABLE_RATIO

    clean = "Testo italiano normale con accenti à è ì ò ù." * 10
    assert tx._printable_ratio(clean) > 0.95
