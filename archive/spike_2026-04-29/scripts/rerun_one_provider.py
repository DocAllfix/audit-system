#!/usr/bin/env python3
"""
Re-esegue UN provider su una pratica, sovrascrivendo testllmnew/<provider>/.
Lascia intatti gli altri provider. Output identico a test_llm_new.py per cella.

Usage:
    python scripts/rerun_one_provider.py <provider> <zip>
    python scripts/rerun_one_provider.py deepseek-v4-flash "ALLEGATI MEDIL 37001_50001.zip"

Variant prompt:
    SPIKE_PROMPT_VARIANT=v1 python scripts/rerun_one_provider.py deepseek-v4-flash "ALLEGATI MEDIL.zip"
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
except Exception:
    pass


def load_env():
    p = _REPO_ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/rerun_one_provider.py <provider> <zip>")
        return 2

    provider = sys.argv[1]
    zip_path = Path(sys.argv[2])
    if not zip_path.is_file():
        print(f"ERROR: ZIP non trovato: {zip_path}")
        return 2

    if provider not in ("gemini-baseline", "deepseek-v4-flash", "gpt-4.1-mini"):
        print(f"ERROR: provider sconosciuto: {provider}")
        return 2

    load_env()

    out_dir = _REPO_ROOT / "testllmnew" / provider
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    docx_dir = out_dir / "docx_outputs"
    docx_dir.mkdir(exist_ok=True)

    provider_slug = provider.replace(".", "_").replace("/", "_")
    session_id = f"testllmnew_{provider_slug}_rerun_{int(time.time() * 1000) % 1_000_000_000}"

    variant = os.environ.get("SPIKE_PROMPT_VARIANT", "v2")

    print("=" * 70)
    print(f"Re-run {provider}")
    print(f"  ZIP            : {zip_path.name}")
    print(f"  Out            : {out_dir}")
    print(f"  Session        : {session_id}")
    print(f"  SPIKE_PROMPT_VARIANT : {variant}")
    print("=" * 70)

    from spike_llm.pipeline_spike import process_zip_spike

    zip_bytes = zip_path.read_bytes()
    t0 = time.monotonic()
    try:
        result = process_zip_spike(
            zip_bytes=zip_bytes,
            session_id=session_id,
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
            output_dir=docx_dir,
            provider=provider,
        )
    except Exception as e:
        import traceback
        result = {
            "success": False,
            "error": f"unhandled_exception: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }

    elapsed = round(time.monotonic() - t0, 2)
    result.setdefault("provider", provider)
    result.setdefault("zip_name", zip_path.name)
    result.setdefault("session_id", session_id)
    result["wall_clock_seconds"] = elapsed
    result["timestamp"] = datetime.now().isoformat()
    result["prompt_variant_used"] = variant

    report_path = out_dir / "run_report.json"
    report_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print()
    if result.get("success"):
        print(f"✅ OK in {elapsed}s | Cost €{result.get('cost_eur', 0):.4f} | "
              f"docs={result.get('n_documents')} batches={result.get('n_batches')} "
              f"parse_failures={result.get('n_parse_failures')}")
    else:
        print(f"❌ FAIL in {elapsed}s: {result.get('error', 'unknown')}")

    print(f"\nReport     : {report_path}")
    print(f"Output docx: {result.get('output_path', 'n/a')}")
    print(f"Raw YAMLs  : {out_dir.parent / 'raw_yamls'}")
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
