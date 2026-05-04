"""
Fixtures condivise per i test V2.

Genera al volo PDF sintetici per testare text_extractor / file_triage
senza dipendere da un golden set di file binari.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Setup sys.path per consentire `from v2.* import ...`
WEBAPP_DIR = Path(__file__).resolve().parent.parent.parent / "webapp"
if str(WEBAPP_DIR) not in sys.path:
    sys.path.insert(0, str(WEBAPP_DIR))


def _make_native_pdf(out_path: Path, text: str = "Lorem ipsum dolor sit amet. " * 50) -> Path:
    """Crea un PDF con text layer nativo usando pypdfium2 helpers via reportlab."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab non installato — skip generazione PDF nativi")

    c = canvas.Canvas(str(out_path), pagesize=A4)
    c.setFont("Helvetica", 11)
    # Spezza in righe
    y = 800
    for line in text.split("."):
        if not line.strip():
            continue
        c.drawString(50, y, line.strip()[:80])
        y -= 14
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = 800
    c.save()
    return out_path


def _make_corrupted_pdf(out_path: Path) -> Path:
    """File con header PDF malformato — non apribile."""
    out_path.write_bytes(b"%PDF-1.0\nGarbage data not a real pdf\x00\x01\x02")
    return out_path


def _make_image_only_pdf(out_path: Path) -> Path:
    """
    PDF con una sola pagina vuota (no text layer).
    Simula PDF scansionato che pypdfium2 NON può estrarre come testo.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab non installato")

    c = canvas.Canvas(str(out_path), pagesize=A4)
    # Solo un cerchio disegnato — nessun testo
    c.circle(300, 400, 50)
    c.showPage()
    c.save()
    return out_path


@pytest.fixture
def sample_pdfs(tmp_path: Path) -> dict:
    """Crea un set di PDF di test con caratteristiche diverse."""
    return {
        "native_ok": _make_native_pdf(tmp_path / "visura_demo.pdf"),
        "native_short": _make_native_pdf(tmp_path / "short.pdf", text="Solo poco testo qui."),
        "image_only": _make_image_only_pdf(tmp_path / "scansione.pdf"),
        "corrupted": _make_corrupted_pdf(tmp_path / "corrotto.pdf"),
        "missing": tmp_path / "non_esiste.pdf",  # mai creato
    }
