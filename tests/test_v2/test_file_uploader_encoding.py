"""
Test per webapp/v2/file_uploader._safe_ascii.

Garantisce che il filename con accenti italiani (a' o' e' i' u') non
mandi in eccezione il display_name Gemini Files API ne' il print() su
console Windows cp1252.

Background: in produzione un upload con accento ha causato 4 minuti di
hang aspettando il timeout future di OCR_INFERENCE_TIMEOUT*2 = 240s.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

from v2.file_uploader import _safe_ascii  # noqa: E402


def test_strip_italian_accents():
    assert _safe_ascii("Conformità.pdf") == "Conformita.pdf"
    assert _safe_ascii("Agibilità.pdf") == "Agibilita.pdf"
    assert _safe_ascii("Perchè.pdf") == "Perche.pdf"
    assert _safe_ascii("più.pdf") == "piu.pdf"


def test_strip_other_diacritics():
    assert _safe_ascii("café.pdf") == "cafe.pdf"
    assert _safe_ascii("Mañana.pdf") == "Manana.pdf"
    assert _safe_ascii("Naïve.pdf") == "Naive.pdf"


def test_no_change_on_pure_ascii():
    assert _safe_ascii("simple_file.pdf") == "simple_file.pdf"
    assert _safe_ascii("UPPER_CASE.PDF") == "UPPER_CASE.PDF"


def test_handles_special_chars():
    # Caratteri non-Latin (es. cinese) vengono strippati
    out = _safe_ascii("文档.pdf")
    assert ".pdf" in out
    # I non-mappabili non causano eccezione
    assert isinstance(out, str)


def test_handles_non_string_gracefully():
    # Path object o None devono essere gestiti
    assert _safe_ascii(123) == "123"


def test_output_is_pure_ascii():
    """Garanzia: l'output e' encodable in ASCII strict."""
    s = _safe_ascii("Conformità Eccentrica àèìòù.pdf")
    s.encode("ascii")  # se non fosse ASCII, solleverebbe
    # Anche encodable in cp1252 (il caso che bloccava il print Windows)
    s.encode("cp1252")
