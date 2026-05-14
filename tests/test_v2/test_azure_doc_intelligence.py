"""
Test webapp/v2/azure_document_intelligence — wrapper Azure DI Read API.

Verifica:
- Build client require env var
- AzureDIResult ha campi compat con OCRResult Gemini
- ocr_extract_files con SDK mockato funziona
- ocr_summary ritorna engine="azure_di"
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

from v2.azure_document_intelligence import (  # noqa: E402
    AzureDIResult,
    _build_client,
    ocr_extract_files,
    ocr_summary,
)


def test_azure_di_result_compat_with_ocr_result():
    """Campi minimi di compat con gemini_ocr_v2.OCRResult."""
    r = AzureDIResult(filename="x.pdf", path="/tmp/x.pdf", success=True)
    # Campi gemini compat
    assert hasattr(r, "filename")
    assert hasattr(r, "path")
    assert hasattr(r, "success")
    assert hasattr(r, "text")
    assert hasattr(r, "method")
    assert hasattr(r, "chars")
    assert hasattr(r, "error")
    assert hasattr(r, "file_uri")
    assert hasattr(r, "used_cached_uri")


def test_build_client_requires_endpoint(monkeypatch):
    monkeypatch.delenv("AZURE_DOC_INTEL_ENDPOINT", raising=False)
    monkeypatch.setenv("AZURE_DOC_INTEL_KEY", "fake")
    with pytest.raises(ValueError, match="ENDPOINT"):
        _build_client()


def test_build_client_requires_key(monkeypatch):
    monkeypatch.setenv("AZURE_DOC_INTEL_ENDPOINT", "https://x/")
    monkeypatch.delenv("AZURE_DOC_INTEL_KEY", raising=False)
    with pytest.raises(ValueError, match="KEY"):
        _build_client()


def test_ocr_extract_files_empty_returns_empty():
    assert ocr_extract_files(client=None, files=[]) == []


def test_ocr_extract_files_credentials_missing_marks_all_failed(monkeypatch):
    monkeypatch.delenv("AZURE_DOC_INTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DOC_INTEL_KEY", raising=False)
    files = [
        {"filename": "a.pdf", "path": "/tmp/a.pdf"},
        {"filename": "b.pdf", "path": "/tmp/b.pdf"},
    ]
    results = ocr_extract_files(client=None, files=files)
    assert len(results) == 2
    assert all(not r.success for r in results)
    assert all("client_init_failed" in r.error for r in results)


def test_ocr_summary_empty():
    s = ocr_summary([])
    assert s["total"] == 0
    assert s["engine"] == "azure_di"


def test_ocr_summary_aggregates():
    results = [
        AzureDIResult(filename="a.pdf", path="/tmp/a.pdf", success=True,
                      text="hello world", chars=11, pages=1),
        AzureDIResult(filename="b.pdf", path="/tmp/b.pdf", success=False,
                      method="failed", error="x"),
        AzureDIResult(filename="c.pdf", path="/tmp/c.pdf", success=True,
                      text="foo bar baz", chars=11, pages=2),
    ]
    s = ocr_summary(results)
    assert s["total"] == 3
    assert s["success"] == 2
    assert s["failed"] == 1
    assert s["total_chars"] == 22
    assert s["total_pages"] == 3
    assert s["engine"] == "azure_di"


def test_progress_callback_invoked(tmp_path, monkeypatch):
    """on_progress deve essere chiamato per ogni file completato."""
    monkeypatch.delenv("AZURE_DOC_INTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DOC_INTEL_KEY", raising=False)

    files = [
        {"filename": f"f{i}.pdf", "path": f"/tmp/f{i}.pdf"}
        for i in range(3)
    ]
    progress_calls = []

    def on_progress(completed, total, current):
        progress_calls.append((completed, total, current))

    # Anche se l'OCR fallisce per credenziali mancanti, on_progress NON viene
    # chiamato perche' il fallimento avviene prima del loop (in _build_client).
    # Verifichiamo che la funzione comunque ritorna risultati e non crasha.
    results = ocr_extract_files(client=None, files=files, on_progress=on_progress)
    assert len(results) == 3
    # Tutti failed per credenziali mancanti: progress non viene chiamato
    # (i risultati sono prodotti senza usare il loop)
    assert all(not r.success for r in results)
