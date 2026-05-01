"""
Test V2 Fase 1 — file_triage.
"""
from __future__ import annotations

from pathlib import Path

from v2 import file_triage as ft


def _file_info(path: Path, category: str = "pdf") -> dict:
    """Costruisce un file_info dict del formato V1."""
    return {
        "filename": path.name,
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "category": category,
    }


def test_triage_routes_native_ok(sample_pdfs):
    """PDF con testo nativo → bucket native_text."""
    files = [_file_info(sample_pdfs["native_ok"])]
    result = ft.triage_files(files)

    assert len(result[ft.KEY_NATIVE]) == 1
    assert len(result[ft.KEY_NEEDS_OCR]) == 0
    assert len(result[ft.KEY_UNRECOVERABLE]) == 0
    f = result[ft.KEY_NATIVE][0]
    assert f["extracted_text"] is not None
    assert f["extraction_chars"] > 200


def test_triage_routes_image_only_to_ocr(sample_pdfs):
    """PDF image-only → bucket needs_ocr."""
    files = [_file_info(sample_pdfs["image_only"])]
    result = ft.triage_files(files)

    assert len(result[ft.KEY_NEEDS_OCR]) == 1
    f = result[ft.KEY_NEEDS_OCR][0]
    assert f["extraction_method"] == "needs_ocr_empty"


def test_triage_routes_corrupted_to_unrecoverable(sample_pdfs):
    """PDF corrotto → bucket unrecoverable."""
    files = [_file_info(sample_pdfs["corrupted"])]
    result = ft.triage_files(files)

    assert len(result[ft.KEY_UNRECOVERABLE]) == 1
    f = result[ft.KEY_UNRECOVERABLE][0]
    assert f["extraction_method"] == "failed_corrupted"


def test_triage_handles_missing_file(sample_pdfs):
    """File con path inesistente → unrecoverable, no crash."""
    files = [_file_info(sample_pdfs["missing"])]
    result = ft.triage_files(files)

    assert len(result[ft.KEY_UNRECOVERABLE]) == 1
    f = result[ft.KEY_UNRECOVERABLE][0]
    assert f["extraction_method"] == "missing_path"


def test_triage_passes_non_pdf_through():
    """File non-PDF → bucket non_pdf (passthrough, V2 non li gestisce in Fase 1)."""
    files = [{"filename": "report.docx", "path": "/fake.docx", "size": 1000, "category": "word"}]
    result = ft.triage_files(files)

    assert len(result[ft.KEY_NON_PDF]) == 1
    assert len(result[ft.KEY_NATIVE]) == 0


def test_triage_mixed_input(sample_pdfs):
    """Input misto: tutti i bucket popolati correttamente."""
    files = [
        _file_info(sample_pdfs["native_ok"]),
        _file_info(sample_pdfs["image_only"]),
        _file_info(sample_pdfs["corrupted"]),
        {"filename": "report.docx", "path": "/fake.docx", "size": 1000, "category": "word"},
    ]
    result = ft.triage_files(files)

    assert len(result[ft.KEY_NATIVE]) == 1
    assert len(result[ft.KEY_NEEDS_OCR]) == 1
    assert len(result[ft.KEY_UNRECOVERABLE]) == 1
    assert len(result[ft.KEY_NON_PDF]) == 1


def test_triage_does_not_mutate_input(sample_pdfs):
    """Le dict in input NON devono essere mutate (stesso file_info usato altrove)."""
    f = _file_info(sample_pdfs["native_ok"])
    original_keys = set(f.keys())
    ft.triage_files([f])
    # La dict originale non deve essere stata arricchita
    assert set(f.keys()) == original_keys


def test_triage_summary(sample_pdfs):
    """Summary fornisce conteggi e percentuale corretti."""
    files = [
        _file_info(sample_pdfs["native_ok"]),
        _file_info(sample_pdfs["native_ok"]),
        _file_info(sample_pdfs["image_only"]),
    ]
    result = ft.triage_files(files)
    summary = ft.triage_summary(result)

    assert summary["total"] == 3
    assert summary[ft.KEY_NATIVE] == 2
    assert summary[ft.KEY_NEEDS_OCR] == 1
    assert summary["native_pct"] == 66.7


def test_split_by_method(sample_pdfs):
    """split_by_method separa il bucket native in clean/partial/garbage."""
    files = [_file_info(sample_pdfs["native_ok"])]
    result = ft.triage_files(files)
    clean, partial, garbage = ft.split_by_method(result[ft.KEY_NATIVE])

    # Il PDF è abbondantemente sopra MIN_CHARS_NATIVE_OK → clean
    assert len(clean) + len(partial) == 1
    assert len(garbage) == 0
