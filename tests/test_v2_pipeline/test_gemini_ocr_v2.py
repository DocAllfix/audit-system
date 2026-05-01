"""
Test V2 Fase 4 — gemini_ocr_v2.

Coperture:
- Pipeline completa OCR su lista file (mock client)
- Ordine preservato in output
- Cleanup automatico a fine sessione
- Fallback al modello lite se primario non produce testo
- Gestione file con path mancante
- Gestione client None
- Cap output anti-blob
- Riuso URI cached (no re-upload)
- ocr_summary aggregato
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from v2 import gemini_ocr_v2 as ocr


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_pdf(tmp_path: Path, name: str, content: bytes = b"PDF" * 200) -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def _file_info(path: Path) -> dict:
    return {
        "filename": path.name,
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "category": "pdf",
    }


def _make_mock_client(text_response: str = "Testo estratto dal documento " * 5):
    """Mock client con files.upload + files.get + models.generate_content."""
    mock = MagicMock()

    fake_file = MagicMock()
    fake_file.uri = "files/upload_uri"
    fake_file.name = "files/upload_name"
    mock.files = MagicMock()
    mock.files.upload = MagicMock(return_value=fake_file)
    mock.files.delete = MagicMock(return_value=None)

    fake_get = MagicMock()
    fake_get.state = "ACTIVE"
    mock.files.get = MagicMock(return_value=fake_get)

    fake_response = MagicMock()
    fake_response.text = text_response
    mock.models = MagicMock()
    mock.models.generate_content = MagicMock(return_value=fake_response)

    return mock


# ──────────────────────────────────────────────────────────────────────────────
# Edge case input
# ──────────────────────────────────────────────────────────────────────────────

def test_empty_files_list_returns_empty():
    client = _make_mock_client()
    result = ocr.ocr_extract_files(client, [], session_id="empty")
    assert result == []


def test_none_client_marks_all_failed(tmp_path):
    files = [_file_info(_make_pdf(tmp_path, "x.pdf"))]
    result = ocr.ocr_extract_files(None, files, session_id="noclient")
    assert len(result) == 1
    assert result[0].success is False
    assert result[0].error == "no_client"


def test_missing_path_handled_gracefully(tmp_path):
    files = [{
        "filename": "ghost.pdf",
        "path": "/non/esiste/ghost.pdf",
        "size": 0,
        "category": "pdf",
    }]
    client = _make_mock_client()
    result = ocr.ocr_extract_files(
        client, files, session_id="ghost", cleanup_after=False,
    )
    assert len(result) == 1
    assert result[0].success is False
    assert result[0].error == "missing_path"


# ──────────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────────

def test_single_file_ocr_success(tmp_path):
    p = _make_pdf(tmp_path, "doc.pdf")
    client = _make_mock_client(text_response="Contenuto del documento estratto")

    # Manifest base_dir personalizzato per non sporcare temp/
    from v2 import file_uploader as fu
    fu.MANIFEST_BASE_DIR = tmp_path / "manifest"

    result = ocr.ocr_extract_files(
        client, [_file_info(p)], session_id="single", cleanup_after=True,
    )
    assert len(result) == 1
    r = result[0]
    assert r.success is True
    assert r.text == "Contenuto del documento estratto"
    assert r.method == "files_api_native"
    assert r.chars > 0
    assert r.file_uri == "files/upload_uri"


def test_multiple_files_order_preserved(tmp_path):
    files = [_file_info(_make_pdf(tmp_path, f"f_{i}.pdf", content=f"X{i}".encode() * 200))
             for i in range(5)]
    client = _make_mock_client()

    from v2 import file_uploader as fu
    fu.MANIFEST_BASE_DIR = tmp_path / "manifest"

    result = ocr.ocr_extract_files(
        client, files, session_id="multi", cleanup_after=False, max_workers=3,
    )
    assert len(result) == 5
    # Ordine: index i del result corrisponde a files[i]
    for i, r in enumerate(result):
        assert r.filename == f"f_{i}.pdf"


# ──────────────────────────────────────────────────────────────────────────────
# Fallback al modello lite
# ──────────────────────────────────────────────────────────────────────────────

def test_fallback_to_lite_model_when_primary_returns_nothing(tmp_path):
    p = _make_pdf(tmp_path, "tricky.pdf")
    client = _make_mock_client()

    # Primario ritorna risposta vuota; secondaria OK
    empty_resp = MagicMock()
    empty_resp.text = ""
    full_resp = MagicMock()
    full_resp.text = "Recuperato via lite"
    client.models.generate_content = MagicMock(side_effect=[empty_resp, full_resp])

    from v2 import file_uploader as fu
    fu.MANIFEST_BASE_DIR = tmp_path / "manifest"

    result = ocr.ocr_extract_files(
        client, [_file_info(p)], session_id="fallback", cleanup_after=False,
    )
    assert result[0].success is True
    assert result[0].text == "Recuperato via lite"
    assert result[0].method == "files_api_native_fallback"
    assert client.models.generate_content.call_count == 2


def test_both_models_fail_marks_failed(tmp_path):
    p = _make_pdf(tmp_path, "broken.pdf")
    client = _make_mock_client()

    empty_resp = MagicMock()
    empty_resp.text = ""
    client.models.generate_content = MagicMock(return_value=empty_resp)

    from v2 import file_uploader as fu
    fu.MANIFEST_BASE_DIR = tmp_path / "manifest"

    result = ocr.ocr_extract_files(
        client, [_file_info(p)], session_id="bothfail", cleanup_after=False,
    )
    assert result[0].success is False
    assert result[0].error == "all_models_failed"


# ──────────────────────────────────────────────────────────────────────────────
# Inferenza che solleva eccezione
# ──────────────────────────────────────────────────────────────────────────────

def test_inference_exception_marks_failed(tmp_path):
    p = _make_pdf(tmp_path, "exc.pdf")
    client = _make_mock_client()
    client.models.generate_content = MagicMock(side_effect=RuntimeError("API timeout"))

    from v2 import file_uploader as fu
    fu.MANIFEST_BASE_DIR = tmp_path / "manifest"

    result = ocr.ocr_extract_files(
        client, [_file_info(p)], session_id="excfail", cleanup_after=False,
    )
    assert result[0].success is False
    assert "all_models_failed" in (result[0].error or "")


# ──────────────────────────────────────────────────────────────────────────────
# Cap anti-blob
# ──────────────────────────────────────────────────────────────────────────────

def test_huge_response_truncated(tmp_path):
    p = _make_pdf(tmp_path, "huge.pdf")
    huge_text = "A" * (ocr.MAX_OCR_OUTPUT_CHARS + 50_000)
    client = _make_mock_client(text_response=huge_text)

    from v2 import file_uploader as fu
    fu.MANIFEST_BASE_DIR = tmp_path / "manifest"

    result = ocr.ocr_extract_files(
        client, [_file_info(p)], session_id="huge", cleanup_after=False,
    )
    assert result[0].success is True
    # Output troncato alla soglia + tag esplicito
    assert "OCR TRONCATO" in result[0].text
    # Soglia rispettata (con un piccolo margine per il tag aggiunto)
    assert len(result[0].text) <= ocr.MAX_OCR_OUTPUT_CHARS + 60


# ──────────────────────────────────────────────────────────────────────────────
# Riuso URI cached (dedup)
# ──────────────────────────────────────────────────────────────────────────────

def test_cached_uri_reused_no_reupload(tmp_path):
    """File identico processato 2 volte: 2° volta usa URI cached."""
    p = _make_pdf(tmp_path, "shared.pdf")
    client = _make_mock_client()

    from v2 import file_uploader as fu
    fu.MANIFEST_BASE_DIR = tmp_path / "manifest"

    files = [_file_info(p), _file_info(p)]  # stesso file 2 volte
    result = ocr.ocr_extract_files(
        client, files, session_id="dedup", cleanup_after=False, max_workers=1,
    )
    assert len(result) == 2
    # 1 sola upload (dedup), 2 inferenze
    assert client.files.upload.call_count == 1
    assert client.models.generate_content.call_count == 2
    # Almeno una delle 2 result ha used_cached_uri=True
    cached_count = sum(1 for r in result if r.used_cached_uri)
    assert cached_count >= 1


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────

def test_cleanup_called_after_session(tmp_path):
    p = _make_pdf(tmp_path, "cleanup.pdf")
    client = _make_mock_client()

    from v2 import file_uploader as fu
    fu.MANIFEST_BASE_DIR = tmp_path / "manifest"

    ocr.ocr_extract_files(
        client, [_file_info(p)], session_id="cleanup", cleanup_after=True,
    )
    # delete chiamato almeno 1 volta sul file uploaded
    assert client.files.delete.call_count >= 1


def test_cleanup_skipped_when_disabled(tmp_path):
    p = _make_pdf(tmp_path, "nocleanup.pdf")
    client = _make_mock_client()

    from v2 import file_uploader as fu
    fu.MANIFEST_BASE_DIR = tmp_path / "manifest"

    ocr.ocr_extract_files(
        client, [_file_info(p)], session_id="nocleanup", cleanup_after=False,
    )
    client.files.delete.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────

def test_ocr_summary_aggregates():
    results = [
        ocr.OCRResult(filename="a.pdf", path="/a", success=True, text="aaa", chars=3),
        ocr.OCRResult(filename="b.pdf", path="/b", success=True, text="bb", chars=2, used_cached_uri=True),
        ocr.OCRResult(filename="c.pdf", path="/c", success=False, error="x"),
    ]
    s = ocr.ocr_summary(results)
    assert s["total"] == 3
    assert s["success"] == 2
    assert s["failed"] == 1
    assert s["total_chars"] == 5
    assert s["success_pct"] == round(100 * 2 / 3, 1)
    assert s["cached_uri_count"] == 1


def test_ocr_summary_empty():
    s = ocr.ocr_summary([])
    assert s["total"] == 0
    assert s["success"] == 0
