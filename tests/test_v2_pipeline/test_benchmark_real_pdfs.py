"""
Benchmark V2 Fase 1 su PDF reali (se disponibili).

Lo skip automatico se non trova un set di PDF reali nel filesystem locale.
Serve a documentare le metriche di performance:
- velocità media per PDF nativo
- routing accuracy (% file → native_text vs needs_ocr)

Soglie attese (basate su audit reali):
- Avg latency < 100ms per PDF nativo
- Almeno 50% dei PDF reali finisce in native_text
"""
from __future__ import annotations

import glob
import time
from pathlib import Path

import pytest

from v2 import file_triage as ft
from v2.text_extractor import extract_native_text


# Cerca PDF reali in posizioni note del workspace
PDF_SEARCH_GLOBS = [
    "temp/extract_*/**/*.pdf",
    "tests/test_v2_pipeline/golden/*.pdf",
]


def _find_real_pdfs(limit: int = 20) -> list:
    repo_root = Path(__file__).resolve().parents[2]
    pdfs = []
    for pattern in PDF_SEARCH_GLOBS:
        pdfs.extend(glob.glob(str(repo_root / pattern), recursive=True))
        if len(pdfs) >= limit:
            break
    return pdfs[:limit]


@pytest.mark.benchmark
def test_benchmark_extraction_speed():
    """Benchmark: estrazione nativa < 100ms/file medio su set reale."""
    pdfs = _find_real_pdfs(limit=20)
    if len(pdfs) < 3:
        pytest.skip(f"Servono almeno 3 PDF reali per il benchmark, trovati {len(pdfs)}")

    t0 = time.time()
    for p in pdfs:
        extract_native_text(p)
    elapsed = time.time() - t0
    avg_ms = (elapsed / len(pdfs)) * 1000

    print(f"\n[bench] {len(pdfs)} PDF in {elapsed:.2f}s, avg {avg_ms:.1f}ms/file")
    assert avg_ms < 100, f"Estrazione troppo lenta: {avg_ms:.1f}ms > 100ms target"


@pytest.mark.benchmark
def test_benchmark_routing_accuracy():
    """
    Benchmark: ≥ 50% dei PDF reali finisce in native_text.
    Se la percentuale è bassa significa che molti PDF audit sono scansionati,
    e l'ottimizzazione ha meno effetto. Soglia 50% è prudente.
    """
    pdfs = _find_real_pdfs(limit=20)
    if len(pdfs) < 5:
        pytest.skip(f"Servono almeno 5 PDF reali, trovati {len(pdfs)}")

    files = [
        {
            "filename": Path(p).name,
            "path": p,
            "size": Path(p).stat().st_size,
            "category": "pdf",
        }
        for p in pdfs
    ]
    result = ft.triage_files(files)
    summary = ft.triage_summary(result)

    print(f"\n[bench] Routing summary: {summary}")
    assert summary["native_pct"] >= 50.0, (
        f"Solo {summary['native_pct']}% dei PDF è andato in native_text — "
        "verifica che pypdfium2 sia funzionante e che i PDF non siano tutti scansionati"
    )


@pytest.mark.benchmark
def test_benchmark_zero_crashes_on_real_set():
    """Robustezza: nessun PDF reale deve causare eccezione non gestita."""
    pdfs = _find_real_pdfs(limit=50)
    if len(pdfs) < 3:
        pytest.skip("Servono almeno 3 PDF reali")

    crashes = []
    for p in pdfs:
        try:
            extract_native_text(p)
        except Exception as e:
            crashes.append(f"{p}: {e}")

    assert not crashes, f"PDF che hanno crashato: {crashes}"
