import json, os, glob

progress_dir = "/opt/auditos/temp/progress"
files = sorted(glob.glob(f"{progress_dir}/20260505_*.jsonl") + glob.glob(f"{progress_dir}/20260506_*.jsonl"))

runs = []
for f in files:
    lines = open(f).readlines()
    events = [json.loads(l) for l in lines if l.strip()]
    start = next((e for e in events if e["type"] == "session.start"), {})
    done = next((e for e in events if e["type"] == "done"), None)
    err = next((e for e in events if e["type"] == "error"), None)

    user = start.get("user", "?")
    size_mb = start.get("total_size_mb", 0)
    ts_start = start.get("ts", "")[:16].replace("T", " ")

    if done:
        s = done.get("stats", {})
        t = s.get("tokens", {})
        runs.append({
            "file": os.path.basename(f),
            "user": user,
            "start": ts_start,
            "end": done.get("ts", "")[:16].replace("T", " "),
            "status": "OK",
            "azienda": done.get("company_name", "?"),
            "size_mb": size_mb,
            "files_zip": s.get("total_files_in_zip", 0),
            "docs": s.get("documents_with_text", 0),
            "paragraphs": s.get("n_paragraphs", 0),
            "duration": done.get("duration_seconds", 0),
            "tok_in": t.get("input_total", 0),
            "tok_out": t.get("output_total", 0),
            "cost": t.get("cost_eur", 0),
            "fallback": s.get("n_fallback_batches", 0),
            "output": done.get("output_filename", "?"),
        })
    elif err:
        runs.append({
            "file": os.path.basename(f),
            "user": user,
            "start": ts_start,
            "end": err.get("ts", "")[:16].replace("T", " "),
            "status": f"ERRORE: {err.get('message', '?')[:80]}",
            "azienda": "—",
            "size_mb": size_mb,
            "files_zip": 0, "docs": 0, "paragraphs": 0,
            "duration": 0, "tok_in": 0, "tok_out": 0, "cost": 0,
            "fallback": 0, "output": "—",
        })
    else:
        last = events[-1] if events else {}
        runs.append({
            "file": os.path.basename(f),
            "user": user,
            "start": ts_start,
            "end": last.get("ts", "")[:16].replace("T", " "),
            "status": f"INCOMPLETO (ultimo: {last.get('type','?')})",
            "azienda": "—",
            "size_mb": size_mb,
            "files_zip": 0, "docs": 0, "paragraphs": 0,
            "duration": 0, "tok_in": 0, "tok_out": 0, "cost": 0,
            "fallback": 0, "output": "—",
        })

print(f"{'#':<3} {'UTENTE':<10} {'INIZIO':<17} {'FINE':<17} {'AZIENDA':<35} {'MB':>6} {'DOC':>4} {'PARA':>5} {'SEC':>6} {'TOK_IN':>7} {'COSTO€':>7} {'FB':>3} {'STATUS'}")
print("-" * 155)
for i, r in enumerate(runs, 1):
    azienda = r["azienda"][:34] if r["azienda"] else "—"
    status = r["status"]
    flag = "⚠" if "NON IDENT" in r["azienda"] or "ERRORE" in status or "INCOMPLETO" in status else "✓"
    print(f"{i:<3} {r['user']:<10} {r['start']:<17} {r['end']:<17} {azienda:<35} {r['size_mb']:>6.1f} {r['docs']:>4} {r['paragraphs']:>5} {r['duration']:>6.0f} {r['tok_in']:>7} {r['cost']:>7.4f} {r['fallback']:>3} {flag} {status if flag=='⚠' else ''}")

print()
total_cost = sum(r["cost"] for r in runs)
total_tok_in = sum(r["tok_in"] for r in runs)
total_tok_out = sum(r["tok_out"] for r in runs)
ok = sum(1 for r in runs if r["status"] == "OK")
print(f"TOTALE: {len(runs)} run | {ok} OK | Token in: {total_tok_in:,} | Token out: {sum(r['tok_out'] for r in runs):,} | Costo totale: €{total_cost:.4f}")
