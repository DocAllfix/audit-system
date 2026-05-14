import json, os, sys

files = [
    "/opt/auditos/temp/progress/20260506_081624_egisto.jsonl",
    "/opt/auditos/temp/progress/20260506_095407_valerio.jsonl",
]

for f in files:
    lines = open(f).readlines()
    events = [json.loads(l) for l in lines if l.strip()]
    start = next((e for e in events if e["type"] == "session.start"), {})
    done = next((e for e in events if e["type"] == "done"), None)
    err = next((e for e in events if e["type"] == "error"), None)
    print("---")
    print("FILE:", os.path.basename(f))
    print("USER:", start.get("user"))
    print("SIZE_MB:", start.get("total_size_mb"))
    print("INIZIO:", start.get("ts", "?")[:19])
    if done:
        s = done.get("stats", {})
        t = s.get("tokens", {})
        print("STATUS: COMPLETATO")
        print("AZIENDA:", done.get("company_name"))
        print("FINE:", done.get("ts", "?")[:19])
        print("DURATA:", done.get("duration_seconds"), "s")
        print("FILES in ZIP:", s.get("total_files_in_zip"), "/ docs con testo:", s.get("documents_with_text"))
        print("PARAGRAFI:", s.get("n_paragraphs"))
        print("TOKENS input:", t.get("input_total"), "/ output:", t.get("output_total"), "/ costo EUR:", t.get("cost_eur"))
        print("FALLBACK BATCHES:", s.get("n_fallback_batches"), s.get("fallback_batch_idxs"))
        print("OUTPUT:", done.get("output_filename"))
    elif err:
        print("STATUS: ERRORE -", err.get("message"))
    else:
        last = events[-1] if events else {}
        print("STATUS: SCONOSCIUTO, ultimo evento:", last.get("type"), last.get("ts", "")[:19])
