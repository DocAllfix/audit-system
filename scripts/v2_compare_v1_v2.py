"""
Script confronto V1 vs V2 sulla stessa pratica.

Esegue la stessa ZIP su:
1. V1 (modules/report_generator) — con monkey-patch per token instrumentation
2. V2 (v2/pipeline) — già strumentato nativamente

Misura per ognuno:
- Tempo totale (secondi)
- Token input/cached/output
- Costo stimato (USD/EUR)
- Dimensione output Word (KB)
- Success/failure

Output: tabella side-by-side stampata + JSON dump in temp/comparison/.

Uso:
    python scripts/v2_compare_v1_v2.py /path/to/practica.zip
    python scripts/v2_compare_v1_v2.py /path/to/practica.zip --skip-v1
    python scripts/v2_compare_v1_v2.py /path/to/practica.zip --skip-v2

Richiede:
- GEMINI_API_KEY in env (o webapp/.env)
- Pratica ZIP locale leggibile
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


# Setup sys.path per webapp
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))


def _load_env_file():
    """Carica webapp/.env se presente, popola os.environ."""
    env_path = _WEBAPP_DIR / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as e:
        print(f"[load_env] errore: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# V1 instrumentation via monkey patch
# ──────────────────────────────────────────────────────────────────────────────

def _instrument_v1_for_token_metering(session_id: str):
    """
    Monkey-patcha le chiamate Gemini di V1 per loggare i token consumati.

    Intercetta:
    - Models.generate_content (sync, blocking)
    - Models.generate_content_stream (streaming chunks)

    Salva i risultati nel token_meter sotto session_id fornito.
    """
    from google.genai import models as gmodels

    from v2 import token_meter

    original_gen = gmodels.Models.generate_content
    original_stream = gmodels.Models.generate_content_stream

    def wrapped_gen(self, *, model, contents, config=None, **kw):
        response = original_gen(self, model=model, contents=contents, config=config, **kw)
        try:
            # Inferisco kind dal modello
            mname = str(model).lower()
            if "lite" in mname:
                kind = "classify"
            else:
                kind = "analyze"
            token_meter.record_from_response(session_id, response, str(model), kind=kind)
        except Exception as e:
            print(f"[V1 INSTRUMENT] meter fallito: {e}")
        return response

    def wrapped_stream(self, *, model, contents, config=None, **kw):
        # Wrap the iterator per cattura ultimo chunk con usage_metadata
        last_chunk = [None]

        def gen_wrapper():
            for chunk in original_stream(self, model=model, contents=contents, config=config, **kw):
                last_chunk[0] = chunk
                yield chunk
            # Fine stream: registra
            if last_chunk[0] is not None:
                try:
                    token_meter.record_from_response(
                        session_id, last_chunk[0], str(model), kind="analyze"
                    )
                except Exception as e:
                    print(f"[V1 INSTRUMENT stream] meter fallito: {e}")

        return gen_wrapper()

    gmodels.Models.generate_content = wrapped_gen
    gmodels.Models.generate_content_stream = wrapped_stream

    return (original_gen, original_stream)


def _restore_v1_instrumentation(originals):
    """Ripristina i metodi originali."""
    from google.genai import models as gmodels
    gmodels.Models.generate_content = originals[0]
    gmodels.Models.generate_content_stream = originals[1]


# ──────────────────────────────────────────────────────────────────────────────
# Run V1
# ──────────────────────────────────────────────────────────────────────────────

def run_v1(zip_bytes: bytes, zip_filename: str, api_key: str) -> Dict[str, Any]:
    """Esegue pipeline V1 con instrumentation. Ritorna metriche."""
    print("\n" + "=" * 70)
    print("RUN V1 (modules/report_generator)")
    print("=" * 70)

    from v2 import token_meter
    session_v1 = f"v1_compare_{int(time.time())}"
    token_meter.reset_session(session_v1)
    originals = _instrument_v1_for_token_metering(session_v1)

    t0 = time.monotonic()
    try:
        from modules.report_generator import process_zip_and_generate_report

        word_bytes, stats, filename = process_zip_and_generate_report(
            input_source=zip_bytes,
            api_key=api_key,
            progress_callback=None,
            status_callback=None,
            input_type="zip",
            filename=zip_filename,
        )
        elapsed = time.monotonic() - t0

        # Salva il Word su disco per ispezione
        out_path = _REPO_ROOT / "temp" / "comparison" / f"v1_{filename}"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(word_bytes)

        token_report = token_meter.get_session_report(session_v1)
        return {
            "version": "V1",
            "success": True,
            "duration_seconds": round(elapsed, 2),
            "output_path": str(out_path),
            "output_size_kb": round(len(word_bytes) / 1024, 1),
            "company_name": stats.get("company_name"),
            "tokens_input": token_report["total_input"],
            "tokens_cached": token_report["total_cached"],
            "tokens_output": token_report["total_output"],
            "cost_usd": token_report["total_cost_usd"],
            "cost_eur": token_report["total_cost_eur"],
            "calls_count": token_report["calls_count"],
        }
    except Exception as e:
        elapsed = time.monotonic() - t0
        return {
            "version": "V1",
            "success": False,
            "duration_seconds": round(elapsed, 2),
            "error": str(e)[:500],
        }
    finally:
        _restore_v1_instrumentation(originals)


# ──────────────────────────────────────────────────────────────────────────────
# Run V2
# ──────────────────────────────────────────────────────────────────────────────

def run_v2(zip_bytes: bytes, api_key: str) -> Dict[str, Any]:
    """Esegue pipeline V2. Ritorna metriche."""
    print("\n" + "=" * 70)
    print("RUN V2 (v2/pipeline.process_zip_v2)")
    print("=" * 70)

    from v2 import token_meter
    from v2.pipeline import process_zip_v2

    session_v2 = f"v2_compare_{int(time.time())}"
    token_meter.reset_session(session_v2)
    out_dir = _REPO_ROOT / "temp" / "comparison"
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    result = process_zip_v2(
        zip_bytes=zip_bytes,
        session_id=session_v2,
        api_key=api_key,
        emitter=None,
        dry_run=False,
        output_dir=out_dir,
    )
    elapsed = time.monotonic() - t0

    if not result.get("success"):
        return {
            "version": "V2",
            "success": False,
            "duration_seconds": round(elapsed, 2),
            "error": result.get("error", "unknown"),
        }

    output_path = Path(result["output_path"])
    size_kb = round(output_path.stat().st_size / 1024, 1) if output_path.exists() else 0

    token_report = token_meter.get_session_report(session_v2)
    return {
        "version": "V2",
        "success": True,
        "duration_seconds": round(elapsed, 2),
        "output_path": str(output_path),
        "output_size_kb": size_kb,
        "company_name": result.get("company_name"),
        "tokens_input": token_report["total_input"],
        "tokens_cached": token_report["total_cached"],
        "tokens_output": token_report["total_output"],
        "cost_usd": token_report["total_cost_usd"],
        "cost_eur": token_report["total_cost_eur"],
        "calls_count": token_report["calls_count"],
        "saved_by_caching_eur": token_report.get("saved_by_caching_eur", 0.0),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Report side-by-side
# ──────────────────────────────────────────────────────────────────────────────

def print_comparison(v1: Dict[str, Any], v2: Dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print("CONFRONTO V1 vs V2")
    print("=" * 70)

    def _fmt_int(v):
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return "n.d."

    def _fmt_float(v, prec=4):
        try:
            return f"{float(v):.{prec}f}"
        except (TypeError, ValueError):
            return "n.d."

    rows = [
        ("Success", v1.get("success", False), v2.get("success", False)),
        ("Tempo (s)", _fmt_float(v1.get("duration_seconds"), 2),
         _fmt_float(v2.get("duration_seconds"), 2)),
        ("Output (KB)", _fmt_float(v1.get("output_size_kb", 0), 1),
         _fmt_float(v2.get("output_size_kb", 0), 1)),
        ("Azienda", v1.get("company_name", "n.d."), v2.get("company_name", "n.d.")),
        ("Calls Gemini", _fmt_int(v1.get("calls_count")), _fmt_int(v2.get("calls_count"))),
        ("Token input", _fmt_int(v1.get("tokens_input")), _fmt_int(v2.get("tokens_input"))),
        ("Token cached", _fmt_int(v1.get("tokens_cached", 0)), _fmt_int(v2.get("tokens_cached", 0))),
        ("Token output", _fmt_int(v1.get("tokens_output")), _fmt_int(v2.get("tokens_output"))),
        ("Costo USD", _fmt_float(v1.get("cost_usd")), _fmt_float(v2.get("cost_usd"))),
        ("Costo EUR", _fmt_float(v1.get("cost_eur")), _fmt_float(v2.get("cost_eur"))),
    ]

    width_label = 18
    width_col = 22
    print(f"{'Metrica':<{width_label}}{'V1':<{width_col}}{'V2':<{width_col}}{'Diff':<15}")
    print("─" * (width_label + width_col * 2 + 15))
    for label, v1_val, v2_val in rows:
        diff = ""
        try:
            v1f = float(str(v1_val).replace(",", ""))
            v2f = float(str(v2_val).replace(",", ""))
            if v1f and v1f != 0:
                pct = ((v2f - v1f) / v1f) * 100
                sign = "+" if pct > 0 else ""
                diff = f"{sign}{pct:.1f}%"
        except (TypeError, ValueError):
            pass
        print(f"{label:<{width_label}}{str(v1_val):<{width_col}}{str(v2_val):<{width_col}}{diff:<15}")

    if v1.get("error"):
        print(f"\nV1 ERROR: {v1['error']}")
    if v2.get("error"):
        print(f"\nV2 ERROR: {v2['error']}")

    if v1.get("success") and v2.get("success"):
        # Risparmio token
        v1_in = int(v1.get("tokens_input", 0) or 0)
        v2_in = int(v2.get("tokens_input", 0) or 0)
        if v1_in > 0:
            token_saved_pct = ((v1_in - v2_in) / v1_in) * 100
            print(f"\n*** Risparmio token input V2 vs V1: {token_saved_pct:+.1f}% ***")
        v1_cost = float(v1.get("cost_eur", 0) or 0)
        v2_cost = float(v2.get("cost_eur", 0) or 0)
        if v1_cost > 0:
            cost_saved_pct = ((v1_cost - v2_cost) / v1_cost) * 100
            print(f"*** Risparmio costo V2 vs V1:        {cost_saved_pct:+.1f}% ***")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Confronto V1 vs V2 stessa pratica")
    parser.add_argument("zip_path", help="Path del ZIP da elaborare")
    parser.add_argument("--skip-v1", action="store_true", help="Skip run V1")
    parser.add_argument("--skip-v2", action="store_true", help="Skip run V2")
    args = parser.parse_args()

    _load_env_file()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("ERRORE: GEMINI_API_KEY non trovata in env o webapp/.env")
        return 1

    zip_path = Path(args.zip_path)
    if not zip_path.is_file():
        print(f"ERRORE: file ZIP non trovato: {zip_path}")
        return 1

    print(f"Pratica di test: {zip_path.name}")
    print(f"Dimensione: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")

    zip_bytes = zip_path.read_bytes()

    v1_result: Dict[str, Any] = {"version": "V1", "skipped": True}
    v2_result: Dict[str, Any] = {"version": "V2", "skipped": True}

    if not args.skip_v1:
        v1_result = run_v1(zip_bytes, zip_path.name, api_key)
    if not args.skip_v2:
        v2_result = run_v2(zip_bytes, api_key)

    print_comparison(v1_result, v2_result)

    # Salva JSON report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = _REPO_ROOT / "temp" / "comparison" / f"report_{timestamp}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "input_zip": str(zip_path),
        "input_size_bytes": zip_path.stat().st_size,
        "timestamp": timestamp,
        "v1": v1_result,
        "v2": v2_result,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport salvato: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
