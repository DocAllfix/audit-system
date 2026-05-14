#!/usr/bin/env python3
"""
Test parallelo 3 provider (gemini-baseline + deepseek-v4-flash + gpt-4.1-mini)
su una singola pratica ZIP. Output strutturato in `testllmnew/<provider>/`.

Usage:
    python scripts/test_llm_new.py "ALLEGATI MEDIL 37001_50001.zip"

Per ogni provider salva in testllmnew/<provider>/:
- run_report.json     → metriche complete (tempo, token, costo, batch, etc.)
- output.docx         → docx prodotto dal pipeline
- run.log             → stdout/stderr del task

Plus testllmnew/comparison_report.md → tabella comparativa finale.

Pre-requisito: file `.env` nella root con DEEPSEEK_API_KEY, GEMINI_API_KEY,
AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Path setup
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

# Encoding stdout su Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
except Exception:
    pass


PROVIDERS = ["gemini-baseline", "deepseek-v4-flash", "gpt-4.1-mini"]

# Output root
TEST_OUTPUT_ROOT = _REPO_ROOT / "testllmnew"


def load_env():
    """Carica .env nella root del repo."""
    p = _REPO_ROOT / ".env"
    if not p.exists():
        print(f"WARN: .env non trovato in {p}")
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v:
            os.environ[k] = v  # forza override


def check_env(providers):
    """Verifica env var richieste, ritorna lista errori."""
    errors = []
    if "deepseek-v4-flash" in providers and not os.environ.get("DEEPSEEK_API_KEY"):
        errors.append("DEEPSEEK_API_KEY mancante")
    if "gemini-baseline" in providers and not os.environ.get("GEMINI_API_KEY"):
        errors.append("GEMINI_API_KEY mancante")
    if "gpt-4.1-mini" in providers:
        if not os.environ.get("AZURE_OPENAI_API_KEY"):
            errors.append("AZURE_OPENAI_API_KEY mancante")
        if not os.environ.get("AZURE_OPENAI_ENDPOINT"):
            errors.append("AZURE_OPENAI_ENDPOINT mancante")
        if not os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI"):
            errors.append("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI mancante")
    # Per classify+OCR (sempre richiesta dal pipeline)
    if not os.environ.get("GEMINI_API_KEY"):
        errors.append("GEMINI_API_KEY mancante (richiesta sempre per classify+OCR)")
    return list(set(errors))


def run_one_provider(
    provider: str,
    zip_bytes: bytes,
    zip_name: str,
    output_dir: Path,
) -> Dict[str, Any]:
    """
    Esegue il pipeline_spike per un provider, salva docx + report in output_dir.
    Cattura stdout/stderr in run.log.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "run.log"

    # Forza il pipeline_spike a scrivere il docx in output_dir
    docx_dir = output_dir / "docx_outputs"
    docx_dir.mkdir(exist_ok=True)

    # session_id deve matchare regex ^[A-Za-z0-9_\-]+$ → slugifica il provider
    provider_slug = provider.replace(".", "_").replace("/", "_")
    session_id = f"testllmnew_{provider_slug}_{int(time.time() * 1000) % 1_000_000_000}"

    # Wrappa stdout/stderr per catturarli su file
    import io
    log_buf = io.StringIO()

    class _Tee:
        def __init__(self, *streams):
            self.streams = streams
        def write(self, data):
            for s in self.streams:
                try:
                    s.write(data)
                except Exception:
                    pass
        def flush(self):
            for s in self.streams:
                try:
                    s.flush()
                except Exception:
                    pass

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = _Tee(original_stdout, log_buf)
    sys.stderr = _Tee(original_stderr, log_buf)

    t0 = time.monotonic()
    result: Dict[str, Any] = {}
    try:
        from spike_llm.pipeline_spike import process_zip_spike
        result = process_zip_spike(
            zip_bytes=zip_bytes,
            session_id=session_id,
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
            output_dir=docx_dir,
            provider=provider,
        )
    except Exception as e:
        result = {
            "success": False,
            "error": f"unhandled_exception: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr

    elapsed = round(time.monotonic() - t0, 2)
    result.setdefault("provider", provider)
    result.setdefault("zip_name", zip_name)
    result.setdefault("session_id", session_id)
    result["wall_clock_seconds"] = elapsed
    result["timestamp"] = datetime.now().isoformat()

    # Salva log su disco
    log_path.write_text(log_buf.getvalue(), encoding="utf-8", errors="replace")

    # Salva report JSON
    report_path = output_dir / "run_report.json"
    report_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return result


def fmt_int(v):
    try:
        return f"{int(v):,}"
    except Exception:
        return "—"


def fmt_cost(v):
    try:
        return f"€{float(v):.4f}"
    except Exception:
        return "—"


def fmt_seconds(v):
    try:
        return f"{float(v):.1f}"
    except Exception:
        return "—"


def build_comparison_report(
    zip_name: str,
    results: Dict[str, Dict[str, Any]],
    total_wall_clock: float,
) -> str:
    """Costruisce report markdown comparativo."""
    lines = []
    lines.append(f"# Test LLM New — Comparison Report")
    lines.append("")
    lines.append(f"**Pratica:** `{zip_name}`")
    lines.append(f"**Eseguito:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Wall-clock totale (parallelo):** {total_wall_clock:.1f}s")
    lines.append("")

    providers_present = [p for p in PROVIDERS if p in results]

    # Tabella metriche principali
    lines.append("## Metriche per provider")
    lines.append("")
    headers = ["Metrica"] + providers_present
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")

    def row(label: str, fn):
        vals = [fn(results.get(p, {})) for p in providers_present]
        return "| " + " | ".join([label] + vals) + " |"

    def status(c):
        if c.get("success"):
            return "✅ OK"
        err = c.get("error", "unknown")
        return f"❌ FAIL ({err[:40]})"

    lines.append(row("Esito", status))
    lines.append(row("Wall-clock totale (s)", lambda c: fmt_seconds(c.get("wall_clock_seconds"))))
    lines.append(row("Pipeline duration (s)", lambda c: fmt_seconds(c.get("duration_seconds"))))
    lines.append(row("Analyze duration (s)", lambda c: fmt_seconds(c.get("analyze_duration_seconds"))))
    lines.append(row("N. documenti analizzati", lambda c: fmt_int(c.get("n_documents"))))
    lines.append(row("N. batch", lambda c: fmt_int(c.get("n_batches"))))
    lines.append(row("N. calls API totali", lambda c: fmt_int(c.get("calls_count"))))
    lines.append(row("Token input (totale)", lambda c: fmt_int(c.get("tokens_input"))))
    lines.append(row("Token cached", lambda c: fmt_int(c.get("tokens_cached"))))
    lines.append(row("Token output", lambda c: fmt_int(c.get("tokens_output"))))
    lines.append(row("Costo USD", lambda c: f"${float(c.get('cost_usd', 0) or 0):.4f}" if c.get("cost_usd") is not None else "—"))
    lines.append(row("Costo EUR", lambda c: fmt_cost(c.get("cost_eur"))))
    lines.append(row("Risparmio caching (€)", lambda c: fmt_cost(c.get("saved_by_caching_eur"))))
    lines.append(row("N. parse failures", lambda c: fmt_int(c.get("n_parse_failures"))))
    lines.append(row("N. truncated responses", lambda c: fmt_int(c.get("n_truncated_responses"))))
    lines.append(row("Output docx (KB)", lambda c: f"{float(c.get('output_size_kb', 0) or 0):.1f}" if c.get("output_size_kb") else "—"))
    lines.append(row("Company estratta", lambda c: c.get("company_name") or "—"))
    lines.append("")

    # Delta vs gemini-baseline
    baseline_cost = (results.get("gemini-baseline") or {}).get("cost_eur")
    if baseline_cost is not None:
        lines.append("## Δ Costo vs gemini-baseline")
        lines.append("")
        lines.append("| Provider | Costo €/pratica | Δ assoluto | Δ % |")
        lines.append("|---|---|---|---|")
        for p in providers_present:
            c = results.get(p, {}).get("cost_eur")
            if c is None:
                lines.append(f"| {p} | — | — | — |")
                continue
            delta_abs = c - baseline_cost
            delta_pct = ((c - baseline_cost) / baseline_cost * 100) if baseline_cost else 0
            sign = "+" if delta_abs >= 0 else ""
            lines.append(
                f"| {p} | €{c:.4f} | {sign}€{delta_abs:.4f} | {sign}{delta_pct:.1f}% |"
            )
        lines.append("")

    # Errori
    errors_section = []
    for p in providers_present:
        r = results.get(p, {})
        if not r.get("success"):
            errors_section.append(f"### {p}\n```\n{r.get('error', 'unknown')}\n```")
            tb = r.get("traceback")
            if tb:
                errors_section.append(f"\n```\n{tb}\n```")
    if errors_section:
        lines.append("## ⚠️ Errori")
        lines.append("")
        lines.extend(errors_section)
        lines.append("")

    # File prodotti
    lines.append("## File prodotti")
    lines.append("")
    for p in providers_present:
        out_path = (results.get(p, {}) or {}).get("output_path") or ""
        if out_path:
            lines.append(f"- **{p}**: `{out_path}`")
        else:
            lines.append(f"- **{p}**: (nessun output)")
    lines.append("")
    lines.append("Per ogni provider, in `testllmnew/<provider>/`:")
    lines.append("- `run_report.json` — metriche complete")
    lines.append("- `docx_outputs/*.docx` — documento estratto")
    lines.append("- `run.log` — stdout/stderr del task")

    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_llm_new.py <path_to_zip>")
        return 2

    zip_path = Path(sys.argv[1])
    if not zip_path.is_file():
        print(f"ERROR: ZIP non trovato: {zip_path}")
        return 2

    load_env()
    env_errors = check_env(PROVIDERS)
    if env_errors:
        print("ERRORI PRE-FLIGHT:")
        for e in env_errors:
            print(f"  - {e}")
        return 2

    # Pulisci output dir e ricrea pulita
    if TEST_OUTPUT_ROOT.exists():
        print(f"Rimuovo output dir precedente: {TEST_OUTPUT_ROOT}")
        shutil.rmtree(TEST_OUTPUT_ROOT, ignore_errors=True)
    TEST_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print(f"TEST LLM NEW — Pratica: {zip_path.name}")
    print(f"  Provider in parallelo : {PROVIDERS}")
    print(f"  ZIP size              : {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  Output root           : {TEST_OUTPUT_ROOT}")
    print("=" * 78)

    zip_bytes = zip_path.read_bytes()
    zip_name = zip_path.name

    t0 = time.monotonic()
    results: Dict[str, Dict[str, Any]] = {}

    sequential = os.environ.get("SPIKE_LLM_TEST_SEQUENTIAL", "").strip().lower() in ("1", "true", "yes")

    if sequential:
        print(f"\nModalità SEQUENZIALE — eseguo {len(PROVIDERS)} provider uno alla volta\n")
        for provider in PROVIDERS:
            print(f"\n>>> Inizio {provider} ...")
            sys.stdout.flush()
            try:
                res = run_one_provider(provider, zip_bytes, zip_name, TEST_OUTPUT_ROOT / provider)
            except Exception as e:
                res = {
                    "success": False,
                    "error": f"top_level_exception: {e}",
                    "provider": provider,
                }
            results[provider] = res
            status = "OK" if res.get("success") else f"FAIL ({(res.get('error') or '')[:50]})"
            elapsed = res.get("wall_clock_seconds", "?")
            cost = res.get("cost_eur", 0) or 0
            print(f"  [{provider:<22}] {status:<55} | {elapsed}s | €{float(cost):.4f}")
            sys.stdout.flush()
    else:
        print(f"\nLancio {len(PROVIDERS)} task in parallelo...\n")
        with ThreadPoolExecutor(max_workers=len(PROVIDERS)) as ex:
            futures = {
                ex.submit(
                    run_one_provider,
                    provider,
                    zip_bytes,
                    zip_name,
                    TEST_OUTPUT_ROOT / provider,
                ): provider
                for provider in PROVIDERS
            }
            for fut in as_completed(futures):
                provider = futures[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    res = {
                        "success": False,
                        "error": f"top_level_exception: {e}",
                        "provider": provider,
                        "wall_clock_seconds": round(time.monotonic() - t0, 2),
                    }
                results[provider] = res
                status = "OK" if res.get("success") else f"FAIL ({(res.get('error') or '')[:50]})"
                elapsed = res.get("wall_clock_seconds", "?")
                cost = res.get("cost_eur", 0) or 0
                print(f"  [{provider:<22}] {status:<55} | {elapsed}s | €{float(cost):.4f}")

    total_wall_clock = round(time.monotonic() - t0, 2)

    print()
    print("=" * 78)
    print(f"COMPLETATO in {total_wall_clock:.1f}s")
    print("=" * 78)

    # Genera report comparativo
    report_md = build_comparison_report(zip_name, results, total_wall_clock)
    report_path = TEST_OUTPUT_ROOT / "comparison_report.md"
    report_path.write_text(report_md, encoding="utf-8")

    # Salva anche aggregato JSON
    summary_path = TEST_OUTPUT_ROOT / "matrix_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "zip_name": zip_name,
                "timestamp": datetime.now().isoformat(),
                "wall_clock_total_seconds": total_wall_clock,
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print(f"\nReport comparativo: {report_path}")
    print(f"Summary JSON      : {summary_path}")
    print()

    n_ok = sum(1 for r in results.values() if r.get("success"))
    return 0 if n_ok == len(PROVIDERS) else 1


if __name__ == "__main__":
    sys.exit(main())
