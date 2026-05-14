#!/usr/bin/env python3
"""
Test gpt-4.1-mini con prompt v3 su MULTIPLE pratiche in parallelo.
Output organizzato in testllmnew/gpt-multi/<pratica_slug>/.

Usage:
    python scripts/test_gpt_multi_pratiche.py <zip1> <zip2> <zip3> ...
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
except Exception:
    pass


PROVIDER = "gpt-4.1-mini"
PROMPT_VARIANT = os.environ.get("SPIKE_PROMPT_VARIANT", "v3")
_OUTPUT_SUBDIR = os.environ.get("MULTI_OUTPUT_SUBDIR", "gpt-multi")
OUTPUT_ROOT = _REPO_ROOT / "testllmnew" / _OUTPUT_SUBDIR


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
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


def slugify(name: str) -> str:
    s = Path(name).stem
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s


def run_one_pratica(zip_path: Path) -> dict:
    slug = slugify(zip_path.name)
    out_dir = OUTPUT_ROOT / slug
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    docx_dir = out_dir / "docx_outputs"
    docx_dir.mkdir(exist_ok=True)

    session_id = f"gptmulti_{slug}_{int(time.time() * 1000) % 1_000_000_000}"
    log_path = out_dir / "run.log"

    # Cattura stdout in un buffer
    import io
    log_buf = io.StringIO()
    class _Tee:
        def __init__(self, *streams): self.streams = streams
        def write(self, data):
            for s in self.streams:
                try: s.write(data)
                except Exception: pass
        def flush(self):
            for s in self.streams:
                try: s.flush()
                except Exception: pass

    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    sys.stdout = _Tee(orig_stdout, log_buf)
    sys.stderr = _Tee(orig_stderr, log_buf)

    t0 = time.monotonic()
    try:
        # Forza variant v3
        os.environ["SPIKE_PROMPT_VARIANT"] = PROMPT_VARIANT
        from spike_llm.pipeline_spike import process_zip_spike
        zip_bytes = zip_path.read_bytes()
        result = process_zip_spike(
            zip_bytes=zip_bytes,
            session_id=session_id,
            deepseek_api_key=None,
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
            output_dir=docx_dir,
            provider=PROVIDER,
        )
    except Exception as e:
        result = {
            "success": False,
            "error": f"unhandled_exception: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }
    finally:
        sys.stdout, sys.stderr = orig_stdout, orig_stderr

    elapsed = round(time.monotonic() - t0, 2)
    result.setdefault("provider", PROVIDER)
    result.setdefault("session_id", session_id)
    result["zip_name"] = zip_path.name
    result["zip_size_mb"] = round(zip_path.stat().st_size / 1024 / 1024, 1)
    result["wall_clock_seconds"] = elapsed
    result["timestamp"] = datetime.now().isoformat()
    result["prompt_variant_used"] = PROMPT_VARIANT

    log_path.write_text(log_buf.getvalue(), encoding="utf-8", errors="replace")
    (out_dir / "run_report.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_gpt_multi_pratiche.py <zip1> <zip2> ...")
        return 2

    zip_paths = [Path(z) for z in sys.argv[1:]]
    for z in zip_paths:
        if not z.is_file():
            print(f"ERROR: ZIP non trovato: {z}")
            return 2

    load_env()
    if not os.environ.get("AZURE_OPENAI_API_KEY") or not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        print("ERROR: AZURE_OPENAI_API_KEY/ENDPOINT mancanti")
        return 2
    if not os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI"):
        print("ERROR: AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI mancante")
        return 2

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT, ignore_errors=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print(f"TEST gpt-4.1-mini (v3) — {len(zip_paths)} pratiche in parallelo")
    print(f"  Pratiche : {[z.name for z in zip_paths]}")
    print(f"  Output   : {OUTPUT_ROOT}")
    print("=" * 78)
    print()

    t0 = time.monotonic()
    results = {}
    sequential = os.environ.get("MULTI_SEQUENTIAL", "1") == "1"

    if sequential:
        print("Modalità SEQUENZIALE\n")
        for z in zip_paths:
            print(f">>> Inizio {z.name} ...", flush=True)
            try:
                res = run_one_pratica(z)
            except Exception as e:
                res = {"success": False, "error": str(e), "zip_name": z.name}
            results[z.name] = res
            status = "OK" if res.get("success") else f"FAIL ({(res.get('error') or '')[:50]})"
            elapsed = res.get("wall_clock_seconds", "?")
            cost = res.get("cost_eur", 0) or 0
            n_doc = res.get("n_documents", 0) or 0
            n_pf = res.get("n_parse_failures", 0) or 0
            print(f"  [{z.name[:40]:<40}] {status:<25} | {elapsed}s | €{float(cost):.4f} | docs={n_doc} | pfail={n_pf}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=len(zip_paths)) as ex:
            futures = {ex.submit(run_one_pratica, z): z for z in zip_paths}
            for fut in as_completed(futures):
                zip_path = futures[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    res = {"success": False, "error": str(e), "zip_name": zip_path.name}
                results[zip_path.name] = res
                status = "OK" if res.get("success") else f"FAIL ({(res.get('error') or '')[:50]})"
                elapsed = res.get("wall_clock_seconds", "?")
                cost = res.get("cost_eur", 0) or 0
                n_doc = res.get("n_documents", 0) or 0
                n_pf = res.get("n_parse_failures", 0) or 0
                print(f"  [{zip_path.name[:40]:<40}] {status:<25} | {elapsed}s | €{float(cost):.4f} | docs={n_doc} | pfail={n_pf}")

    total = round(time.monotonic() - t0, 2)
    print()
    print("=" * 78)
    print(f"COMPLETATO in {total:.1f}s (parallelo)")
    print("=" * 78)

    # Salva summary
    summary = {
        "provider": PROVIDER,
        "prompt_variant": PROMPT_VARIANT,
        "timestamp": datetime.now().isoformat(),
        "wall_clock_total_seconds": total,
        "results_per_pratica": results,
    }
    (OUTPUT_ROOT / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\nSummary: {OUTPUT_ROOT / 'summary.json'}")

    n_ok = sum(1 for r in results.values() if r.get("success"))
    return 0 if n_ok == len(zip_paths) else 1


if __name__ == "__main__":
    sys.exit(main())
