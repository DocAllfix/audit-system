#!/usr/bin/env python3
"""
Orchestratore spike multi-provider.

Esegue la matrice (pratica × provider) in parallelo. Default: tutte le celle
in contemporanea. Output: per ogni cella un docx + report JSON, più tabelle
comparative per-pratica e summary cross-pratica.

Usage:
    # Default: 4 provider × N pratiche, tutto in parallelo
    python scripts/spike_llm_orchestrate.py \\
        "ALLEGATI MEDIL.zip" \\
        "ALLEGATI SIRIH.zip" \\
        "ALLEGATI Pratica3.zip" \\
        "ALLEGATI Pratica4.zip"

    # Solo 2 pratiche in parallelo (mitigazione 429 Azure)
    python scripts/spike_llm_orchestrate.py --parallel-pratiche 2 \\
        "ALLEGATI MEDIL.zip" "ALLEGATI SIRIH.zip"

    # Sottoinsieme di provider
    python scripts/spike_llm_orchestrate.py \\
        --providers gpt-4.1-mini gpt-4o-mini \\
        "ALLEGATI MEDIL.zip"

Env var richieste (per i provider scelti):
    DEEPSEEK_API_KEY                    [deepseek-v4-flash]
    AZURE_OPENAI_API_KEY                [gpt-4.1-mini, gpt-4o-mini]
    AZURE_OPENAI_ENDPOINT               [gpt-4.1-mini, gpt-4o-mini]
    AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI [gpt-4.1-mini]
    AZURE_OPENAI_DEPLOYMENT_GPT_4O_MINI [gpt-4o-mini]
    GEMINI_API_KEY                      [gemini-baseline, sempre — anche per
                                         classify+OCR su altri provider]

Output:
    temp/spike_llm/<provider>/reports/<zip_slug>_<ts>.json   (per ogni cella)
    temp/spike_llm/<provider>/docx_outputs/spike_*.docx       (per ogni cella)
    temp/spike_llm/comparison/per_pratica_<zip_name>.md       (1 per pratica)
    temp/spike_llm/comparison/summary_all_pratiche.md         (aggregato)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Path setup
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

# Encoding stdout su Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
except Exception:
    pass


ALL_PROVIDERS_DEFAULT = [
    "gemini-baseline",
    "deepseek-v4-flash",
    "gpt-4.1-mini",
    "gpt-4o-mini",
]


def _check_env_for_providers(providers: list[str]) -> list[str]:
    """Ritorna lista di errori (vuota se tutto ok)."""
    errors: list[str] = []
    if "deepseek-v4-flash" in providers and not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        errors.append("DEEPSEEK_API_KEY non settato (richiesto per deepseek-v4-flash)")

    azure_providers = [p for p in providers if p in ("gpt-4.1-mini", "gpt-4o-mini")]
    if azure_providers:
        if not os.environ.get("AZURE_OPENAI_API_KEY", "").strip():
            errors.append("AZURE_OPENAI_API_KEY non settato (richiesto per " + ", ".join(azure_providers) + ")")
        if not os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip():
            errors.append("AZURE_OPENAI_ENDPOINT non settato")
        if "gpt-4.1-mini" in azure_providers and not os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI", "").strip():
            errors.append("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI non settato")
        if "gpt-4o-mini" in azure_providers and not os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT_4O_MINI", "").strip():
            errors.append("AZURE_OPENAI_DEPLOYMENT_GPT_4O_MINI non settato")

    # Gemini API key è sempre richiesta (per classify + OCR su tutti i provider,
    # e come "client" per gemini-baseline)
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        errors.append("GEMINI_API_KEY non settato (richiesto sempre per classify+OCR)")

    return errors


def _save_cell_report(result: dict, repo_root: Path) -> Path:
    """Salva il report JSON di una cella in temp/spike_llm/<provider>/reports/."""
    provider = result.get("provider") or "unknown"
    zip_name = result.get("zip_name") or "unknown.zip"
    slug = "".join(c if (c.isalnum() or c == "_") else "_" for c in Path(zip_name).stem)
    ts = time.strftime("%Y%m%d_%H%M%S")
    report_dir = repo_root / "temp" / "spike_llm" / provider / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{slug}_{ts}.json"
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Orchestratore spike multi-provider (matrice pratica × provider in parallelo)",
    )
    parser.add_argument("zips", nargs="+", help="Path ZIP da elaborare (1+)")
    parser.add_argument(
        "--providers", nargs="+", default=ALL_PROVIDERS_DEFAULT,
        help=f"Lista provider (default: {' '.join(ALL_PROVIDERS_DEFAULT)})",
    )
    parser.add_argument(
        "--variant", choices=("v1", "v2"), default="v2",
        help="Variante prompt (default v2). Applicato a tutti i provider tranne gemini-baseline (che usa il prompt V2 ufficiale).",
    )
    parser.add_argument(
        "--parallel-pratiche", type=int, default=None,
        help="Quante pratiche in parallelo (default = tutte). Ridurre a 2 se 429 Azure ricorrenti.",
    )
    parser.add_argument(
        "--skip-baseline", action="store_true",
        help="Esclude gemini-baseline dai provider (shortcut)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Mostra cosa lancerebbe senza chiamare API",
    )
    args = parser.parse_args()

    # Risolve providers
    providers = list(args.providers)
    if args.skip_baseline:
        providers = [p for p in providers if p != "gemini-baseline"]
    if not providers:
        print("ERROR: lista providers vuota", file=sys.stderr)
        return 2

    # Carica ZIP in memoria
    zip_paths = [Path(p) for p in args.zips]
    for p in zip_paths:
        if not p.is_file():
            print(f"ERROR: ZIP non trovato: {p}", file=sys.stderr)
            return 2

    parallel_pratiche = args.parallel_pratiche or len(zip_paths)

    # Banner
    print("=" * 78)
    print(f"SPIKE LLM ORCHESTRATE — matrice {len(zip_paths)} pratiche × {len(providers)} provider")
    print(f"  Pratiche       : {[p.name for p in zip_paths]}")
    print(f"  Provider       : {providers}")
    print(f"  Variant prompt : {args.variant}")
    print(f"  Parallel       : {parallel_pratiche} pratiche × {len(providers)} provider = "
          f"{parallel_pratiche * len(providers)} task concorrenti")
    print("=" * 78)

    # Pre-flight env check
    env_errors = _check_env_for_providers(providers)
    if env_errors and not args.dry_run:
        print("\nERRORI PRE-FLIGHT:")
        for e in env_errors:
            print(f"  - {e}")
        return 2

    if args.dry_run:
        print("\nDRY-RUN: nessuna chiamata API verrà eseguita.")
        return 0

    # Carica byte ZIP
    zips = [(p.name, p.read_bytes()) for p in zip_paths]

    # Progress callback
    completed_count = [0]
    total_count = len(zips) * len(providers)

    def on_done(zip_name: str, provider: str, result: dict) -> None:
        completed_count[0] += 1
        save_path = _save_cell_report(result, _REPO_ROOT)
        status = "OK" if result.get("success") else f"FAIL ({result.get('error', 'unknown')[:60]})"
        elapsed = result.get("duration_seconds", "?")
        cost = result.get("cost_eur", 0.0)
        print(
            f"  [{completed_count[0]:2d}/{total_count}] {provider:<22} | {zip_name[:35]:<35} | "
            f"{status:<35} | {elapsed}s | €{cost:.3f}"
        )

    # Lancia matrice
    print(f"\nAvvio matrice ({total_count} task)...\n")
    t0 = time.monotonic()

    from spike_llm.orchestrator import run_matrix
    results = run_matrix(
        zips=zips,
        providers=providers,
        variant=args.variant,
        parallel_pratiche=parallel_pratiche,
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        on_task_complete=on_done,
    )

    elapsed_total = time.monotonic() - t0

    # Riepilogo
    print()
    print("=" * 78)
    print(f"MATRICE COMPLETATA in {elapsed_total:.1f}s")
    print("=" * 78)
    n_ok = sum(1 for r in results.values() if r.get("success"))
    n_fail = len(results) - n_ok
    total_cost = sum(r.get("cost_eur", 0.0) for r in results.values())
    print(f"  Task OK   : {n_ok}/{len(results)}")
    print(f"  Task FAIL : {n_fail}/{len(results)}")
    print(f"  Costo totale: €{total_cost:.3f}")

    # Genera tabelle comparative
    try:
        from scripts_helpers_compare import build_per_pratica_table, build_summary_table  # type: ignore
    except ImportError:
        # Fallback: chiama compare_table come sottoprocesso
        compare_dir = _REPO_ROOT / "temp" / "spike_llm" / "comparison"
        compare_dir.mkdir(parents=True, exist_ok=True)
        # Salva la matrice raw per uso da compare_table.py
        raw_path = compare_dir / f"matrix_raw_{int(time.time())}.json"
        raw_path.write_text(
            json.dumps(
                {f"{k[0]}|||{k[1]}": v for k, v in results.items()},
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\n  Matrice raw salvata: {raw_path}")
        print(f"  Genera tabelle con: python scripts/spike_llm_compare_table.py --raw {raw_path}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
