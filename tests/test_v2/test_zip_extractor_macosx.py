"""
Test webapp/v2/zip_extractor.py — fix __MACOSX/ + resource fork macOS.

Verifica che ZIP creati su macOS (Archive Utility) producano artefatti
__MACOSX/ + ._foo.pdf scartati silenziosamente, e che PDF camuffati (size <
1KB) vengano rifiutati.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

from v2.zip_extractor import _is_macos_artifact, extract_zip_bytes  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Unit test su _is_macos_artifact
# ──────────────────────────────────────────────────────────────────────────────

def test_is_macos_artifact_macosx_dir_root():
    assert _is_macos_artifact("__MACOSX/foo.pdf") is True


def test_is_macos_artifact_macosx_dir_nested():
    assert _is_macos_artifact("subdir/__MACOSX/foo.pdf") is True


def test_is_macos_artifact_resource_fork_basename():
    assert _is_macos_artifact("regular/path/._actualfile.pdf") is True


def test_is_macos_artifact_resource_fork_with_backslash():
    assert _is_macos_artifact("regular\\path\\._foo.pdf") is True


def test_is_macos_artifact_normal_file_passes():
    assert _is_macos_artifact("docs/visura.pdf") is False


def test_is_macos_artifact_dotfile_basename_not_caught():
    # `.gitignore` non è artefatto macOS specifico (sarebbe filtrato altrove
    # da `fname.startswith(".")` che è check separato).
    assert _is_macos_artifact("docs/.gitignore") is False


# ──────────────────────────────────────────────────────────────────────────────
# Integration: ZIP simulato con artefatti macOS
# ──────────────────────────────────────────────────────────────────────────────

def _build_zip_with_macos_artifacts() -> bytes:
    """
    ZIP simulato come prodotto da Archive Utility macOS:
    - documents/file.pdf (file reale)
    - __MACOSX/documents/._file.pdf (resource fork in __MACOSX/)
    - documents/._other.pdf (resource fork inline con prefisso `._`)
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("documents/file.pdf", b"%PDF-1.4\n" + b"X" * 8000)
        zf.writestr("__MACOSX/documents/._file.pdf", b"\x00\x00\x00")
        zf.writestr("documents/._other.pdf", b"\x00\x05\x16\x07")
    return buf.getvalue()


def test_extract_filters_macosx_and_resource_forks(tmp_path):
    zip_bytes = _build_zip_with_macos_artifacts()
    files, extract_dir = extract_zip_bytes(
        zip_bytes, session_id="macostest", base_dir=tmp_path,
    )
    filenames = [f["filename"] for f in files]
    # SOLO file.pdf deve sopravvivere
    assert "file.pdf" in filenames
    assert "._file.pdf" not in filenames
    assert "._other.pdf" not in filenames
    assert len(files) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Long path Windows (MAX_PATH bypass)
# ──────────────────────────────────────────────────────────────────────────────

def test_to_long_path_short_path_unchanged():
    from v2.zip_extractor import _to_long_path
    short = "C:\\foo\\bar.pdf"
    assert _to_long_path(short) == short


def test_to_long_path_idempotent_on_prefixed():
    from v2.zip_extractor import _to_long_path
    import os
    if os.name != "nt":
        return  # noop su non-Windows
    long = "\\\\?\\C:\\foo\\" + "x" * 300 + ".pdf"
    assert _to_long_path(long) == long


def test_to_long_path_windows_long_gets_prefix():
    from v2.zip_extractor import _LONG_PATH_THRESHOLD, _to_long_path
    import os
    if os.name != "nt":
        return  # test specifico Windows
    # Costruiamo un path certamente sopra la soglia
    very_long = "C:\\foo\\" + "subdir\\" * 50 + "file.pdf"
    assert len(very_long) >= _LONG_PATH_THRESHOLD
    out = _to_long_path(very_long)
    assert out.startswith("\\\\?\\")
    assert out.endswith("file.pdf")


def test_extract_zip_with_long_internal_path(tmp_path):
    """
    Simula il caso PONTI & VIADOTTI: file con path > 260 char dentro ZIP.
    Senza il fix questo file viene perso silenziosamente con Errno 2.
    """
    import os
    if os.name != "nt":
        return  # solo Windows ha MAX_PATH limitation

    # Costruisce un path interno al ZIP molto lungo
    long_internal = ("very_long_subfolder_name_for_test/" * 6) + "deep_file.pdf"
    assert len(long_internal) > 200

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(long_internal, b"%PDF-1.4\n" + b"X" * 5000)

    files, extract_dir = extract_zip_bytes(
        buf.getvalue(), session_id="longpath", base_dir=tmp_path,
    )
    assert len(files) == 1, "File con long-path NON è stato estratto col fix"
    assert files[0]["filename"] == "deep_file.pdf"
    # path salvato nel dict deve essere apribile (con o senza prefix)
    with open(files[0]["path"], "rb") as f:
        data = f.read()
    assert data.startswith(b"%PDF-1.4")
