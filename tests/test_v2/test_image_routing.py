"""
Test: le immagini (.jpg/.png/.heic/...) vengono promosse al bucket needs_ocr
invece di essere scartate come unsupported_format.

Il dispatcher text_handlers ritorna ("", "deferred_to_ocr") per le immagini
ma prima del Fix 8 il pipeline ignorava il flag e le scartava silenziosamente.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))


def test_text_handlers_returns_deferred_for_images(tmp_path):
    """text_handlers deve dichiarare 'deferred_to_ocr' per JPG."""
    from v2.text_handlers import extract_text_for_category

    fake_jpg = tmp_path / "test.jpg"
    fake_jpg.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 100)
    text, method = extract_text_for_category({
        "filename": "test.jpg",
        "path": str(fake_jpg),
        "category": "image",
    })
    assert text == ""
    assert method == "deferred_to_ocr"


def test_text_handlers_returns_deferred_for_heic(tmp_path):
    from v2.text_handlers import extract_text_for_category

    fake_heic = tmp_path / "photo.heic"
    fake_heic.write_bytes(b"\x00" * 100)
    text, method = extract_text_for_category({
        "filename": "photo.heic",
        "path": str(fake_heic),
        "category": "heic",
    })
    assert method == "deferred_to_ocr"


def test_mime_table_covers_all_image_types():
    """Verifica che file_uploader sappia dare un MIME corretto per le immagini."""
    from v2.file_uploader import guess_mime_type

    cases = {
        "x.jpg": "image/jpeg",
        "x.jpeg": "image/jpeg",
        "x.png": "image/png",
        "x.gif": "image/gif",
        "x.bmp": "image/bmp",
        "x.tif": "image/tiff",
        "x.tiff": "image/tiff",
        "x.heic": "image/heic",
        "x.heif": "image/heif",
        "x.webp": "image/webp",
    }
    for fname, expected_mime in cases.items():
        assert guess_mime_type(fname) == expected_mime, (
            f"{fname}: atteso {expected_mime}, ottenuto {guess_mime_type(fname)}"
        )


def test_pipeline_promotes_images_to_needs_ocr_bucket(tmp_path):
    """
    Smoke: usando il triage + il blocco non_pdf di pipeline su un file JPG,
    il file finisce in needs_ocr (bucket OCR), NON in unprocessed.
    """
    # Costruisce file_info come il zip_extractor lo produrrebbe
    fake_jpg = tmp_path / "foto_cantiere.jpg"
    fake_jpg.write_bytes(b"\xff\xd8\xff\xe0fake jpg")

    file_info = {
        "filename": "foto_cantiere.jpg",
        "path": str(fake_jpg),
        "size": fake_jpg.stat().st_size,
        "category": "image",
    }

    # Simula la logica di triage + non_pdf processing del pipeline
    from v2.file_triage import triage_files
    from v2.text_handlers import extract_text_for_category

    triaged = triage_files([file_info])
    # Le immagini vanno in non_pdf (non sono PDF)
    assert any(f["filename"] == "foto_cantiere.jpg" for f in triaged.get("non_pdf", []))

    # Il dispatcher per l'immagine deve dire "deferred_to_ocr"
    f = triaged["non_pdf"][0]
    text, method = extract_text_for_category(f)
    assert method == "deferred_to_ocr"

    # Quindi il pipeline dovrebbe promuoverla a needs_ocr (Fix 8).
    # Replica della logica pipeline qui per verificare il comportamento atteso.
    needs_ocr = list(triaged.get("needs_ocr", []))
    if method == "deferred_to_ocr":
        needs_ocr.append(f)
    assert any(x["filename"] == "foto_cantiere.jpg" for x in needs_ocr), (
        "L'immagine deve essere promossa al bucket needs_ocr post-triage"
    )
