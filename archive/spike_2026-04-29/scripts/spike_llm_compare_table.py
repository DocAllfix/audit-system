#!/usr/bin/env python3
"""
Generatore tabelle comparative per lo spike multi-provider.

Legge i report JSON da `temp/spike_llm/<provider>/reports/` (o un file matrice
raw prodotto dall'orchestratore) e produce tabelle Markdown:

- per_pratica_<zip_name>.md  (1 per pratica)
- summary_all_pratiche.md     (aggregato cross-pratica)

Usage:
    # Da matrice raw (output orchestratore)
    python scripts/spike_llm_compare_table.py --raw temp/spike_llm/comparison/matrix_raw_*.json

    # Da reports/ scansionati (più recenti per provider × pratica)
    python scripts/spike_llm_compare_table.py --auto

    # Tabella per singola pratica (filtra report per zip_name)
    python scripts/spike_llm_compare_table.py --pratica "ALLEGATI MEDIL.zip"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
COMPARISON_DIR = _REPO_ROOT / "temp" / "spike_llm" / "comparison"

PROVIDERS_ORDER = [
    "gemini-baseline",
    "deepseek-v4-flash",
    "gpt-4.1-mini",
    "gpt-4o-mini",
]

GDPR_LABEL = {
    "gemini-baseline": "AI Studio (verificare)",
    "deepseek-v4-flash": "Server CN (rischio)",
    "gpt-4.1-mini": "Azure EU",
    "gpt-4o-mini": "Azure EU",
}


def _load_matrix_raw(raw_path: Path) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Carica una matrice raw {zip_name|||provider: result_dict}."""
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for k, v in raw.items():
        if "|||" in k:
            zn, p = k.split("|||", 1)
            out[(zn, p)] = v
    return out


def _load_latest_per_cell(reports_root: Path) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Scansiona temp/spike_llm/<provider>/reports/*.json e per ogni
    (zip_name, provider) tiene solo il report più recente.
    """
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if not reports_root.exists():
        return out
    for provider_dir in reports_root.iterdir():
        if not provider_dir.is_dir() or provider_dir.name == "comparison":
            continue
        reports = provider_dir / "reports"
        if not reports.exists():
            continue
        # Ordina per mtime desc, prendo il primo per ogni zip_name
        sorted_reports = sorted(reports.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        seen_zips: set = set()
        for rp in sorted_reports:
            try:
                d = json.loads(rp.read_text(encoding="utf-8"))
            except Exception:
                continue
            zn = d.get("zip_name") or rp.stem
            if zn in seen_zips:
                continue
            seen_zips.add(zn)
            out[(zn, provider_dir.name)] = d
    return out


def _fmt_cost(v: Any) -> str:
    try:
        return f"€{float(v):.3f}"
    except Exception:
        return "—"


def _fmt_int(v: Any) -> str:
    try:
        return f"{int(v):,}"
    except Exception:
        return "—"


def _fmt_seconds(v: Any) -> str:
    try:
        return f"{float(v):.1f}"
    except Exception:
        return "—"


def _delta_vs_baseline(current: Optional[float], baseline: Optional[float]) -> str:
    if current is None or baseline is None or not baseline:
        return "—"
    delta_pct = (current - baseline) / baseline * 100
    sign = "+" if delta_pct > 0 else ""
    return f"{sign}{delta_pct:.0f}%"


def build_per_pratica_table(
    zip_name: str,
    cells: Dict[str, Dict[str, Any]],
) -> str:
    """
    Costruisce una tabella Markdown per una singola pratica.

    Args:
        zip_name: nome ZIP della pratica
        cells: dict {provider: result_dict} per quella pratica
    """
    lines: List[str] = []
    lines.append(f"# Pratica: {zip_name}")

    # Metadata di base (preso dal primo provider che ha success)
    sample = next((c for c in cells.values() if c.get("success")), None)
    if sample:
        lines.append(
            f"N. doc analizzati: {sample.get('n_documents', '?')} — "
            f"Variant prompt: {sample.get('prompt_variant', '?')}"
        )
    lines.append("")

    providers_present = [p for p in PROVIDERS_ORDER if p in cells]
    if not providers_present:
        lines.append("(nessun provider con dati)")
        return "\n".join(lines)

    headers = ["Metrica"] + providers_present

    def row(label: str, fn) -> str:
        vals = [fn(cells.get(p, {})) for p in providers_present]
        return "| " + " | ".join([label] + vals) + " |"

    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    lines.append(row("Success", lambda c: "YES" if c.get("success") else f"NO ({c.get('error', 'unknown')[:30]})"))
    lines.append(row("Tempo wall-clock (s)", lambda c: _fmt_seconds(c.get("duration_seconds"))))
    lines.append(row("Tempo analyze (s)", lambda c: _fmt_seconds(c.get("analyze_duration_seconds"))))
    lines.append(row("N. batch", lambda c: _fmt_int(c.get("n_batches"))))
    lines.append(row("N. calls", lambda c: _fmt_int(c.get("calls_count"))))
    lines.append(row("Token input", lambda c: _fmt_int(c.get("tokens_input"))))
    lines.append(row("Token cached", lambda c: _fmt_int(c.get("tokens_cached"))))
    lines.append(row("Token output", lambda c: _fmt_int(c.get("tokens_output"))))
    lines.append(row("Cost USD", lambda c: f"${float(c.get('cost_usd', 0)):.3f}" if c.get("cost_usd") is not None else "—"))
    lines.append(row("Cost EUR", lambda c: _fmt_cost(c.get("cost_eur"))))

    # Delta cost vs gemini-baseline
    baseline_cost = cells.get("gemini-baseline", {}).get("cost_eur")
    lines.append(row(
        "Δ costo vs baseline",
        lambda c: _delta_vs_baseline(c.get("cost_eur"), baseline_cost),
    ))

    lines.append(row("N. parse failures", lambda c: _fmt_int(c.get("n_parse_failures"))))
    lines.append(row("N. truncated responses", lambda c: _fmt_int(c.get("n_truncated_responses"))))
    lines.append(row("Output docx (KB)", lambda c: f"{float(c.get('output_size_kb', 0)):.1f}" if c.get("output_size_kb") else "—"))
    lines.append(row("GDPR EU", lambda c: GDPR_LABEL.get(c.get("provider") or "", "—")))
    lines.append(row("Batch max files", lambda c: _fmt_int(c.get("batch_max_files"))))
    lines.append(row("Batch max chars", lambda c: _fmt_int(c.get("batch_max_chars"))))
    lines.append(row("Max workers", lambda c: _fmt_int(c.get("max_workers"))))

    return "\n".join(lines) + "\n"


def build_summary_table(matrix: Dict[Tuple[str, str], Dict[str, Any]]) -> str:
    """Costruisce la tabella summary cross-pratica."""
    by_zip: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for (zn, p), d in matrix.items():
        by_zip[zn][p] = d

    zip_names = sorted(by_zip.keys())
    providers_present = [p for p in PROVIDERS_ORDER if any(p in by_zip[zn] for zn in zip_names)]

    lines: List[str] = []
    lines.append(f"# Summary Spike LLM — {len(zip_names)} pratiche × {len(providers_present)} provider\n")

    def avg_or_dash(values: List[float]) -> str:
        valid = [v for v in values if v is not None]
        return f"{sum(valid) / len(valid):.3f}" if valid else "—"

    # Sezione costi
    lines.append("## Costo per pratica (€)\n")
    headers = ["Provider"] + zip_names + ["Media", "Δ vs baseline"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")

    baseline_avg: Optional[float] = None
    if "gemini-baseline" in providers_present:
        baseline_costs = [by_zip[zn].get("gemini-baseline", {}).get("cost_eur") for zn in zip_names]
        bv = [c for c in baseline_costs if c is not None]
        baseline_avg = sum(bv) / len(bv) if bv else None

    for p in providers_present:
        row_costs = []
        cell_costs: List[float] = []
        for zn in zip_names:
            c = by_zip[zn].get(p, {}).get("cost_eur")
            row_costs.append(_fmt_cost(c) if c is not None else "—")
            if c is not None:
                cell_costs.append(c)
        avg = sum(cell_costs) / len(cell_costs) if cell_costs else None
        delta = _delta_vs_baseline(avg, baseline_avg) if avg is not None else "—"
        lines.append(
            "| " + " | ".join(
                [p] + row_costs + [_fmt_cost(avg) if avg is not None else "—", delta]
            ) + " |"
        )
    lines.append("")

    # Sezione tempi
    lines.append("## Tempo per pratica (s)\n")
    lines.append("| " + " | ".join(["Provider"] + zip_names + ["Media"]) + " |")
    lines.append("|" + "|".join(["---"] * (len(zip_names) + 2)) + "|")
    for p in providers_present:
        row_times = []
        cell_times: List[float] = []
        for zn in zip_names:
            t = by_zip[zn].get(p, {}).get("duration_seconds")
            row_times.append(_fmt_seconds(t))
            if t is not None:
                cell_times.append(t)
        avg = sum(cell_times) / len(cell_times) if cell_times else None
        lines.append("| " + " | ".join([p] + row_times + [_fmt_seconds(avg) if avg is not None else "—"]) + " |")
    lines.append("")

    # Sezione truncation
    lines.append("## N. truncated responses per pratica\n")
    lines.append("| " + " | ".join(["Provider"] + zip_names + ["Totale"]) + " |")
    lines.append("|" + "|".join(["---"] * (len(zip_names) + 2)) + "|")
    for p in providers_present:
        row_t = []
        total = 0
        for zn in zip_names:
            n = by_zip[zn].get(p, {}).get("n_truncated_responses", 0) or 0
            row_t.append(str(n))
            total += n
        lines.append("| " + " | ".join([p] + row_t + [str(total)]) + " |")
    lines.append("")

    # Decisione informata
    lines.append("## Decisione informata\n")
    lines.append("| Vincolo prioritario | Vincitore atteso | Note |")
    lines.append("|---|---|---|")
    lines.append("| Costo minimo | deepseek-v4-flash | Ma server CN (rischio GDPR) |")
    lines.append("| GDPR + costo | gpt-4o-mini | Verificare truncation < 10% |")
    lines.append("| GDPR + qualità | gpt-4.1-mini | Sweet spot saving/qualità |")
    lines.append("| Status quo | gemini-baseline | Nessuna migrazione, eventuale Vertex AI EU |")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generatore tabelle comparative spike multi-provider")
    parser.add_argument("--raw", type=str, default=None, help="Path matrice raw da orchestratore")
    parser.add_argument("--auto", action="store_true", help="Scansiona temp/spike_llm/<provider>/reports/")
    parser.add_argument("--pratica", type=str, default=None, help="Filtra per zip_name (solo quella)")
    parser.add_argument("--summary", action="store_true", help="Genera solo summary cross-pratica")
    args = parser.parse_args()

    matrix: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if args.raw:
        matrix = _load_matrix_raw(Path(args.raw))
    else:
        # default = auto
        matrix = _load_latest_per_cell(_REPO_ROOT / "temp" / "spike_llm")

    if not matrix:
        print("ERROR: nessun report trovato.", file=sys.stderr)
        return 1

    COMPARISON_DIR.mkdir(parents=True, exist_ok=True)

    # Per-pratica tables
    by_zip: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for (zn, p), d in matrix.items():
        by_zip[zn][p] = d

    target_zips = [args.pratica] if args.pratica else sorted(by_zip.keys())
    for zn in target_zips:
        if zn not in by_zip:
            print(f"WARN: pratica '{zn}' non trovata nei report", file=sys.stderr)
            continue
        md = build_per_pratica_table(zn, by_zip[zn])
        slug = "".join(c if (c.isalnum() or c == "_") else "_" for c in Path(zn).stem)
        out_path = COMPARISON_DIR / f"per_pratica_{slug}.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"  Tabella per-pratica: {out_path}")

    # Summary
    if not args.pratica or args.summary:
        summary_md = build_summary_table(matrix)
        summary_path = COMPARISON_DIR / "summary_all_pratiche.md"
        summary_path.write_text(summary_md, encoding="utf-8")
        print(f"  Summary cross-pratica: {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
