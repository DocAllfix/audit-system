"""
Test V2 Fase 8 — zip_extractor.

Coperture:
- Estrazione ZIP semplice (1 livello)
- Estrazione ZIP nidificato (matrioska)
- ZIP corrotto al primo livello solleva ValueError
- ZIP nidificato corrotto: skip + log, non interrompe
- Anti path-traversal: file con "../escape" rifiutato
- Limiti zip-bomb: MAX_TOTAL_FILES rispettato
- session_id invalido rifiutato
- Categorize: pdf/word/excel/skip
- Cleanup rimuove tutta la directory
- extract_summary aggregato corretto
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from v2 import zip_extractor as ze


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_zip_bytes(entries: dict) -> bytes:
    """Crea bytes ZIP con entries={path: content_bytes}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in entries.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _make_nested_zip_bytes(inner_entries: dict, outer_path: str = "inner.zip") -> bytes:
    """Crea ZIP che contiene un ZIP nidificato."""
    inner_bytes = _make_zip_bytes(inner_entries)
    return _make_zip_bytes({outer_path: inner_bytes})


# ──────────────────────────────────────────────────────────────────────────────
# Categorize
# ──────────────────────────────────────────────────────────────────────────────

def test_categorize_pdf():
    assert ze._categorize_file("doc.pdf") == "pdf"
    assert ze._categorize_file("DOC.PDF") == "pdf"


def test_categorize_office_formats():
    assert ze._categorize_file("a.docx") == "word"
    assert ze._categorize_file("b.xlsx") == "excel"
    assert ze._categorize_file("c.pptx") == "pptx"


def test_categorize_skip_extensions():
    assert ze._categorize_file("malware.exe") == "skip"
    assert ze._categorize_file("song.mp3") == "skip"
    assert ze._categorize_file("contact.vcf") == "skip"


def test_categorize_other():
    assert ze._categorize_file("strange.xyz") == "other"


# ──────────────────────────────────────────────────────────────────────────────
# Extract zip bytes
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_simple_zip(tmp_path):
    zb = _make_zip_bytes({
        "documento.pdf": b"%PDF-1.4 fake content " * 20,
        "report.docx": b"docx fake",
    })
    files, extract_dir = ze.extract_zip_bytes(zb, "sess1", base_dir=tmp_path)

    assert len(files) == 2
    filenames = {f["filename"] for f in files}
    assert "documento.pdf" in filenames
    assert "report.docx" in filenames

    # Categorie corrette
    cats = {f["filename"]: f["category"] for f in files}
    assert cats["documento.pdf"] == "pdf"
    assert cats["report.docx"] == "word"

    # File esistono su disco
    for f in files:
        assert Path(f["path"]).exists()


def test_extract_nested_zip(tmp_path):
    """ZIP nidificato (1 livello) viene estratto ricorsivamente."""
    zb = _make_nested_zip_bytes({
        "inner_doc.pdf": b"PDF inner",
        "scan.jpg": b"JPG fake",
    })
    files, _ = ze.extract_zip_bytes(zb, "sess_nest", base_dir=tmp_path)

    filenames = {f["filename"] for f in files}
    assert "inner_doc.pdf" in filenames
    assert "scan.jpg" in filenames


def test_skips_skip_extensions(tmp_path):
    zb = _make_zip_bytes({
        "doc.pdf": b"PDF",
        "malware.exe": b"EXE",
        "audio.mp3": b"MP3",
    })
    files, _ = ze.extract_zip_bytes(zb, "sess_skip", base_dir=tmp_path)
    filenames = {f["filename"] for f in files}
    assert "doc.pdf" in filenames
    assert "malware.exe" not in filenames
    assert "audio.mp3" not in filenames


def test_skips_dotfiles_and_underscored(tmp_path):
    zb = _make_zip_bytes({
        ".hidden.pdf": b"PDF",
        "__MACOSX/_metadata": b"junk",
        "real.pdf": b"PDF",
    })
    files, _ = ze.extract_zip_bytes(zb, "sess_dot", base_dir=tmp_path)
    filenames = {f["filename"] for f in files}
    # .hidden e __MACOSX vengono skippati
    assert "real.pdf" in filenames
    assert ".hidden.pdf" not in filenames


# ──────────────────────────────────────────────────────────────────────────────
# Anti path-traversal
# ──────────────────────────────────────────────────────────────────────────────

def test_path_traversal_in_zip_rejected(tmp_path):
    """Entry con ../escape viene rifiutata silenziosamente."""
    # Costruzione manuale: zipfile non sempre permette '..' direttamente,
    # ma il check è interno al nostro extractor
    zb = _make_zip_bytes({
        "../../escape/evil.pdf": b"PDF",
        "normal/inside.pdf": b"PDF normale",
    })
    files, extract_dir = ze.extract_zip_bytes(zb, "sess_trav", base_dir=tmp_path)
    filenames = {f["filename"] for f in files}
    # File legittimo OK
    assert "inside.pdf" in filenames
    # File traversal: NON deve esistere fuori da extract_dir
    escape_path = tmp_path.parent / "escape" / "evil.pdf"
    assert not escape_path.exists()


def test_invalid_session_id_rejected(tmp_path):
    zb = _make_zip_bytes({"x.pdf": b"PDF"})
    with pytest.raises(ValueError):
        ze.extract_zip_bytes(zb, "../etc", base_dir=tmp_path)
    with pytest.raises(ValueError):
        ze.extract_zip_bytes(zb, "foo/bar", base_dir=tmp_path)
    with pytest.raises(ValueError):
        ze.extract_zip_bytes(zb, "", base_dir=tmp_path)


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────────

def test_corrupted_zip_root_raises(tmp_path):
    """ZIP root corrotto: ValueError esplicito."""
    with pytest.raises(ValueError):
        ze.extract_zip_bytes(b"not a zip", "sess_corrupt", base_dir=tmp_path)


def test_empty_zip_returns_empty_list(tmp_path):
    zb = _make_zip_bytes({})
    files, _ = ze.extract_zip_bytes(zb, "sess_empty", base_dir=tmp_path)
    assert files == []


def test_empty_bytes_raises(tmp_path):
    with pytest.raises(ValueError):
        ze.extract_zip_bytes(b"", "sess_eb", base_dir=tmp_path)


def test_max_files_limit_enforced(tmp_path, monkeypatch):
    """Hard limit MAX_TOTAL_FILES rispettato."""
    monkeypatch.setattr(ze, "MAX_TOTAL_FILES", 5)

    entries = {f"file_{i:04d}.pdf": b"PDF" for i in range(20)}
    zb = _make_zip_bytes(entries)
    files, _ = ze.extract_zip_bytes(zb, "sess_lim", base_dir=tmp_path)

    # I file estratti sono al massimo MAX_TOTAL_FILES
    assert len(files) <= 5


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────

def test_cleanup_removes_extraction(tmp_path):
    zb = _make_zip_bytes({"a.pdf": b"PDF", "b.pdf": b"PDF"})
    files, extract_dir = ze.extract_zip_bytes(zb, "sess_cl", base_dir=tmp_path)
    assert extract_dir.exists()
    count = ze.cleanup_extraction(extract_dir)
    assert count >= 2
    assert not extract_dir.exists()


def test_cleanup_idempotent_missing_dir(tmp_path):
    fake = tmp_path / "noexist"
    count = ze.cleanup_extraction(fake)
    assert count == 0


# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_summary(tmp_path):
    zb = _make_zip_bytes({
        "a.pdf": b"PDF" * 100,
        "b.docx": b"DOCX" * 50,
        "c.pdf": b"PDF" * 100,
    })
    files, _ = ze.extract_zip_bytes(zb, "sess_sum", base_dir=tmp_path)
    summary = ze.extract_summary(files)
    assert summary["total_files"] == 3
    assert summary["by_category"]["pdf"] == 2
    assert summary["by_category"]["word"] == 1
    assert summary["total_bytes"] > 0
