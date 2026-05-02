#!/usr/bin/env python3
"""
Spike runner: V2 pipeline su DeepSeek V4 Flash.

Usage:
    # Variante prompt V2 (default, 6 fix Fase 2)
    python scripts/spike_deepseek_v4_flash.py "ALLEGATI MEDIL.zip"

    # Variante prompt V1 (PROD originale, niente fix V2)
    SPIKE_PROMPT_VARIANT=v1 python scripts/spike_deepseek_v4_flash.py "ALLEGATI SIRIH.zip"

    # Override soglie spike
    SPIKE_DEEPSEEK_MAX_WORKERS=20 SPIKE_DEEPSEEK_BATCH_MAX_FILES=16 \\
        python scripts/spike_deepseek_v4_flash.py "ZIP.zip"

Env var richieste:
    DEEPSEEK_API_KEY    chiave DeepSeek (https://platform.deepseek.com/)
    GEMINI_API_KEY      chiave Gemini (per classifier + OCR, riusati da V2)

Output:
    temp/spike_deepseek/reports/spike_<timestamp>.json
    temp/spike_deepseek/docx_outputs/spike_<sess>_<company>_<ts>.docx

Il report JSON ha campi compatibili con `temp/comparison/report_*.json`
per facilitare il confronto con le run V2/V1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Path setup
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

# Encoding stdout per evitare UnicodeEncodeError su Windows cp1252
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
except Exception:
    pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Spike test: V2 pipeline su DeepSeek V4 Flash"
    )
    parser.add_argument("zip_path", help="Path ZIP da elaborare")
    parser.add_argument(
        "--variant",
        choices=("v1", "v2"),
        default=None,
        help="Variante prompt: v1 (PROD originale + REGOLA PRELIMINARE) o "
             "v2 (V2 fix Fase 2 + REGOLA PRELIMINARE). Default: v2 (o env "
             "SPIKE_PROMPT_VARIANT).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Override numero worker paralleli (default 14, env "
             "SPIKE_DEEPSEEK_MAX_WORKERS).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Override max files per batch (default 12, env "
             "SPIKE_DEEPSEEK_BATCH_MAX_FILES).",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Override max chars per batch (default 200000, env "
             "SPIKE_DEEPSEEK_BATCH_MAX_CHARS).",
    )
    args = parser.parse_args()

    # Override env var via CLI (precedono le env)
    if args.variant:
        os.environ["SPIKE_PROMPT_VARIANT"] = args.variant
    if args.max_workers:
        os.environ["SPIKE_DEEPSEEK_MAX_WORKERS"] = str(args.max_workers)
    if args.max_files:
        os.environ["SPIKE_DEEPSEEK_BATCH_MAX_FILES"] = str(args.max_files)
    if args.max_chars:
        os.environ["SPIKE_DEEPSEEK_BATCH_MAX_CHARS"] = str(args.max_chars)

    zip_path = Path(args.zip_path)
    if not zip_path.is_file():
        print(f"ERROR: ZIP non trovato: {zip_path}")
        return 2

    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not deepseek_key:
        print("ERROR: DEEPSEEK_API_KEY non settato. "
              "Aggiungi la chiave a env o ottienila da https://platform.deepseek.com/")
        return 2

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        print("WARN: GEMINI_API_KEY non settato — classifier e OCR saranno disabilitati. "
              "Pratiche con PDF scansionati avranno output incompleto.")

    print("=" * 70)
    print(f"SPIKE DeepSeek V4 Flash")
    print(f"  ZIP: {zip_path.name} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  Variant prompt: {os.environ.get('SPIKE_PROMPT_VARIANT', 'v2')}")
    print(f"  Workers: {os.environ.get('SPIKE_DEEPSEEK_MAX_WORKERS', '14')}")
    print(f"  Max files/batch: {os.environ.get('SPIKE_DEEPSEEK_BATCH_MAX_FILES', '12')}")
    print(f"  Max chars/batch: {os.environ.get('SPIKE_DEEPSEEK_BATCH_MAX_CHARS', '200000')}")
    print("=" * 70)

    from spike_deepseek.pipeline_spike import process_zip_spike
    from v2 import token_meter

    session_id = f"spike_{int(time.time())}"
    token_meter.reset_session(session_id)

    zip_bytes = zip_path.read_bytes()

    t0 = time.monotonic()
    try:
        result = process_zip_spike(
            zip_bytes=zip_bytes,
            session_id=session_id,
            deepseek_api_key=deepseek_key,
            gemini_api_key=gemini_key or None,
        )
    except Exception as e:
        elapsed = time.monotonic() - t0
        result = {
            "success": False,
            "error": f"unexpected: {e}",
            "duration_seconds": round(elapsed, 2),
        }
    elapsed = time.monotonic() - t0

    # Salva report JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = _REPO_ROOT / "temp" / "spike_deepseek" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "input_zip": zip_path.name,
        "input_size_bytes": zip_path.stat().st_size,
        "timestamp": timestamp,
        "session_id": session_id,
        "spike": {
            "model": "deepseek-v4-flash",
            "prompt_variant": os.environ.get("SPIKE_PROMPT_VARIANT", "v2"),
            "max_workers": int(os.environ.get("SPIKE_DEEPSEEK_MAX_WORKERS", "14")),
            "batch_max_files": int(os.environ.get("SPIKE_DEEPSEEK_BATCH_MAX_FILES", "12")),
            "batch_max_chars": int(os.environ.get("SPIKE_DEEPSEEK_BATCH_MAX_CHARS", "200000")),
            **result,
            "wall_clock_seconds": round(elapsed, 2),
        },
    }
    report_path = report_dir / f"spike_{timestamp}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Stampa riepilogo
    print()
    print("=" * 70)
    print(f"RISULTATO SPIKE")
    print("=" * 70)
    if result.get("success"):
        print(f"  Success            : YES")
        print(f"  Company name       : {result.get('company_name', 'n.d.')}")
        print(f"  Duration (s)       : {result.get('duration_seconds', 0):.1f}")
        print(f"  Calls              : {result.get('calls_count', 0)}")
        print(f"  Token input        : {result.get('tokens_input', 0):,}")
        print(f"  Token cached       : {result.get('tokens_cached', 0):,}")
        print(f"  Token output       : {result.get('tokens_output', 0):,}")
        print(f"  Cost USD           : {result.get('cost_usd', 0):.4f}")
        print(f"  Cost EUR           : {result.get('cost_eur', 0):.4f}")
        print(f"  Saved by caching   : {result.get('saved_by_caching_eur', 0):.4f} EUR")
        print(f"  N. batches         : {result.get('n_batches', 0)}")
        print(f"  N. documents       : {result.get('n_documents', 0)}")
        print(f"  Docx output        : {result.get('output_path', 'n.d.')}")
        print(f"  Docx size (KB)     : {result.get('output_size_kb', 0):.1f}")
        print(f"  Parse failures     : {result.get('n_parse_failures', 0)}")
    else:
        print(f"  Success            : NO")
        print(f"  Error              : {result.get('error', 'unknown')}")
    print()
    print(f"Report salvato: {report_path}")
    print("=" * 70)

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
