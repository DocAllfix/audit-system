# METODO A — V2 EXECUTION TRACKER

> Master plan operativo per l'implementazione zero-regression del **Metodo A — Triage Funnel**.
> Versione: 1.0 · Stato: in attesa di OK Fase 1
> Riferimento spec: documento "Metodo A — Specifica operativa per il cliente"

---

## §0. STRATEGIA DI ISOLAMENTO (LOCAL-FIRST)

**Modello operativo deciso il 2026-05-01**: tutto lo sviluppo e il testing V2 avvengono **in ambiente locale** (workstation Windows). La produzione Hetzner (`auditos.service`) **non viene toccata** finché V2 non è completamente validato sul golden set locale. Deploy in prod = step finale, controllato, dopo passaggio Fase 9.

L'intero sviluppo V2 vive **in parallelo a V1**, mai sopra. Tre livelli di separazione:

### 0.1 Branch git
- Branch `main` = produzione V1, **intoccato**.
- Branch nuovo `v2-experimental` = sviluppo V2. Si mergia in `main` solo dopo passaggio del golden-set.

### 0.2 Namespace codice
- V1 vive in `webapp/modules/*.py` — **nessuna modifica strutturale**.
- V2 vive in **`webapp/v2/*.py`** — nuovo namespace, import indipendenti.
- Endpoint V1 `/api/report/process` → invariato.
- Endpoint V2 nuovo `/api/v2/report/process` → handler dedicato in `api_server.py` (modifica additiva, non sostitutiva).

### 0.3 Feature flag
- Variabile d'ambiente `USE_V2_PIPELINE` (default `false`).
- Quando `false`: V1 risponde a `/api/report/process`, V2 risponde solo se chiamato esplicitamente su `/api/v2/...`.
- Quando `true` per uno specifico utente (whitelist in `config.py`): V1 fa redirect interno a V2 sull'endpoint storico.
- Rollback istantaneo: settare `USE_V2_PIPELINE=false` + restart servizio = ritorno V1 in 30 secondi.

### 0.4 Test isolation
- Golden set in `tests/v2/golden/` con coppie `{input.zip, expected_output.docx}` da audit storici.
- Suite test in `tests/v2/` eseguita su CI prima di ogni merge in `main`.
- Confronto output con metriche specifiche (vedi §10).

---

## §1. MASTER EXECUTION TRACKER (9 FASI)

Ordinamento per **criticità + testabilità indipendente**: ogni fase è validabile in isolamento prima di passare alla successiva.

---

### FASE 0 · SETUP AMBIENTE V2 (½ giorno)

**Obiettivo**: creare lo scheletro V2 senza alcuna logica funzionale, per validare l'isolamento.

**File nuovi**
- `webapp/v2/__init__.py` (vuoto)
- `webapp/v2/README.md` (regole d'ingaggio, isolamento)
- `webapp/v2/pipeline.py` (stub: `def process_v2() -> dict: return {"status": "v2_stub"}`)
- `tests/v2/__init__.py`
- `tests/v2/golden/.gitkeep`
- `tests/v2/test_v2_isolation.py` (verifica che V1 non importi da V2)

**Modifiche additive**
- `webapp/api_server.py`: aggiunge handler `@app.post("/api/v2/report/process")` che chiama solo lo stub. Endpoint V1 invariato.
- `webapp/config.py`: aggiunge `USE_V2_PIPELINE = os.environ.get("USE_V2_PIPELINE", "false") == "true"` e whitelist `V2_USER_WHITELIST`.

**Dipendenze nuove**: nessuna.

**Fallback**: nessuno necessario (è solo scaffolding).

**Test di validazione**
- `pytest tests/v2/test_v2_isolation.py` → V1 non deve avere import da `webapp.v2`.
- Chiamata `curl POST /api/v2/report/process` → ritorna stub JSON.
- Chiamata `curl POST /api/report/process` → comportamento V1 invariato (smoke test).

**Criterio di successo**: V1 funziona come prima, V2 risponde con stub.

---

### FASE 1 · TRIAGE FUNNEL — pypdfium2 + text-layer detection (1-2 giorni)

**Obiettivo**: sostituire `PyPDF2` con `pypdfium2` per estrazione testo nativo veloce. Saltare OCR sui PDF già digitali.

**File nuovi**
- `webapp/v2/text_extractor.py`
  - `extract_native_text(pdf_path: str, max_chars: int = 100_000) -> Tuple[str, str]`
  - Ritorna `(text, method)` con method ∈ `{"pdfium_native", "pdfium_partial", "pdfium_failed"}`
- `webapp/v2/file_triage.py`
  - `triage_files(files: List[Dict]) -> Dict[str, List[Dict]]`
  - Smista ogni file in `{"native_text": [...], "needs_ocr": [...], "skipped": [...]}`
  - Soglia: `len(text) >= 200` chars utili → native; altrimenti → OCR.
- `tests/v2/test_text_extractor.py`
- `tests/v2/test_file_triage.py`

**Dipendenze nuove**
```
pypdfium2>=4.30.0
```
(da aggiungere in `webapp/requirements.txt` solo nel branch v2-experimental)

**Edge case e fallback**
| Edge case | Comportamento |
|---|---|
| PDF protetto da password | `pypdfium2.PdfDocument` solleva `PdfiumError` → catch → fallback OCR Vision |
| PDF corrotto (header invalido) | catch `PdfiumError` → marca `extraction_failed`, NON va in OCR (non recuperabile) |
| PDF con solo immagini (scansione pura) | `pypdfium2` ritorna `""` o < 200 chars → routing automatico verso `needs_ocr` |
| PDF con testo "garbage" (font mal embedded) | controllo qualitativo: ratio chars stampabili > 0.7 → accept; else → OCR fallback |
| File > 100 MB | hard limit: log warning, marca per OCR fast-mode (max 12 pagine) |

**Test di non-regressione**
- Golden set `tests/v2/golden/triage/` con 30 PDF etichettati (10 nativi, 10 scansionati, 5 firmati P7M, 3 protetti, 2 corrotti).
- `pytest tests/v2/test_file_triage.py::test_routing_accuracy` → accuracy > 95% sul routing native vs OCR.
- Benchmark: `pytest tests/v2/bench/test_extraction_speed.py` → media < 0.05s per PDF nativo.
- Confronto chars estratti V1 vs V2 sui PDF nativi: V2 deve produrre ≥ 95% dei chars di V1 (tipicamente di più).

**Criterio di successo**: su un sample di 30 PDF reali, V2 ha latenza < 1/30 di V1 sui PDF nativi e routing OCR corretto al 95%+.

---

### FASE 2 · CLASSIFICATORE DOCUMENTI via Gemini Flash Lite (1-2 giorni)

**Obiettivo**: classificare ogni file in 1 di ~12 classi note. Sostituisce `_doc_char_cap` patterns fragili.

**File nuovi**
- `webapp/v2/document_classifier.py`
  - `classify_files_batch(files: List[Dict]) -> Dict[filename, ClassifiedFile]`
  - Classi: VISURA, STATUTO, DVR, POS, BILANCIO, CCNL, ATTESTATO, CERTIFICATO_ISO, CONTRATTO, FATTURA, IDENTITA, ALTRO
  - Output schema Pydantic: `ClassifiedFile{ filename, class, confidence, suggested_cap_chars }`
- `webapp/v2/schemas/classification.py` (modelli Pydantic)
- `tests/v2/test_classifier.py`
- `tests/v2/golden/classification/labeled_50_files.json`

**Dipendenze nuove**
```
pydantic>=2.5.0  (probabilmente già presente come transitiva)
```
Modello Gemini: `gemini-2.5-flash-lite` (già supportato dal client esistente).

**Edge case e fallback**
| Edge case | Comportamento |
|---|---|
| API Gemini down | catch eccezione → tutti i file → classe ALTRO + cap default 12 000 |
| Risposta malformata | retry 1× → fallback ALTRO |
| Confidence < 0.6 | classe = INCERTO → cap default + log warning |
| File senza testo (immagini pure) | classe = IMMAGINE_OCR → bypass classifier, va direttamente in OCR queue |
| Batch > 200 file | spezza in sottobatch da 100 (rate limit safety) |

**Test di non-regressione**
- Golden set `labeled_50_files.json`: 50 file con classe etichettata manualmente.
- `pytest tests/v2/test_classifier.py::test_accuracy` → accuracy > 90%.
- Benchmark costo: < 6 000 token totali per batch da 100 file = ~0,001 €.
- Test fallback: simula API down → tutti finiscono in ALTRO senza crash.

**Criterio di successo**: 90%+ accuracy su golden set, costo < 0,002 € per ZIP da 200 file.

---

### FASE 3 · CONTEXT CACHING del prompt universale (1 giorno)

**Obiettivo**: caricare `universal_evidence_prompt.md` (24.5k chars / 6.1k tok) **una sola volta** in cache Gemini, ricondurre i token cached al 10% del costo standard.

**File nuovi**
- `webapp/v2/cache_manager.py`
  - `get_or_create_cached_prompt() -> str` (ritorna `cache_id`)
  - TTL 1h, refresh automatico
  - Singleton per processo, lock su creazione concorrente
- `webapp/v2/cache_refresher.py` (script standalone per cron)
- `tests/v2/test_cache_manager.py`

**Dipendenze nuove**: nessuna (`google-genai` ≥ 0.6 già installato).

**Edge case e fallback**
| Edge case | Comportamento |
|---|---|
| Cache API non supportata da modello | fallback inline: prompt concatenato come oggi (V1 behavior) |
| Cache scaduta a metà run | rilevazione su errore "cache not found" → ricreazione + retry batch |
| Race condition (2 worker creano cache contemporaneamente) | `threading.Lock` + check-and-create atomico |
| Cache TTL troppo corto | env var `V2_CACHE_TTL_SECONDS` (default 3600) |
| Cache cost > savings (caso patologico) | telemetria: se cache_hit_ratio < 5x storage cost → alert |

**Test di non-regressione**
- `pytest tests/v2/test_cache_manager.py::test_token_reduction` → response usage_metadata mostra `cached_token_count > 5000`.
- Test concorrenza: 5 thread chiamano `get_or_create_cached_prompt()` simultaneamente → 1 sola cache creata.
- Test ricreazione: forza scadenza → seconda chiamata ricrea senza errori.
- Confronto costo: 10 batch identici V1 vs V2 → V2 deve mostrare ≥ 80% riduzione token input.

**Criterio di successo**: token cached visibili in `usage_metadata`, riduzione ≥ 80% sul prompt input verificata su 10 batch.

---

### FASE 4 · FILES API per OCR (2 giorni)

**Obiettivo**: sostituire l'upload base64 inline con `client.files.upload()`. Riduce payload, abilita riuso, sblocca PDF > 100 MB.

**File nuovi**
- `webapp/v2/gemini_ocr_v2.py`
  - `OCRClientV2` class che usa Files API
  - `extract_text_from_pdf_v2(pdf_path: str) -> Tuple[str, str]`
  - Caricamento parallelo via `asyncio.gather` con concorrenza 5
- `webapp/v2/file_uploader.py`
  - `upload_with_retry(path: str, max_retries: int = 3) -> str` (ritorna `file_uri`)
- `tests/v2/test_files_api.py`

**Dipendenze nuove**: nessuna (Files API è in `google-genai` esistente).

**Edge case e fallback**
| Edge case | Comportamento |
|---|---|
| Upload fallisce (network) | retry 3× con backoff esponenziale → fallback su base64 inline V1 |
| File > 2 GB | hard reject + warning all'utente |
| File scaduto durante run (>48h) | impossibile in pratica (run dura minuti), ma catch "file not found" → re-upload |
| Quota storage Files API esaurita (20 GB) | cleanup batch immediato dei file usati → retry |
| Upload concorrente di 60 file | rate limit interno: max 5 upload paralleli (semaforo dedicato) |

**Test di non-regressione**
- `pytest tests/v2/test_files_api.py::test_upload_reuse` → 1 upload + 3 inferenze stesso file = 1 sola chiamata upload visibile in network.
- Test fallback: mocka API upload come 503 → fallback base64 funziona, OCR completa.
- Confronto qualità: 30 PDF scansionati estratti V1 (base64) vs V2 (Files API) → variazione chars < 2%.
- Test PDF grande: PDF da 60 MB (RELAZIONE_POS reale) → V2 estrae > 12 pagine in < 90 secondi.

**Criterio di successo**: upload riusabile verificato, fallback automatico funziona, file > 50 MB gestiti senza crash.

---

### FASE 5 · STREAMING AI + cap risposta hardlimit (2 giorni)

**Obiettivo**: sostituire `generate_content` blocking con `generate_content_stream`. Cap a 400 000 chars per evitare il caso "Batch 64 boss" (1 MB → lxml segfault).

**File nuovi**
- `webapp/v2/gemini_client_v2.py`
  - `analyze_batch_streaming(batch_docs, batch_idx, ...) -> Iterator[StreamChunk]`
  - Yield chunks incrementali
  - Hard cap 400 000 chars con evento `error.response_too_large`
- `webapp/v2/stream_buffer.py`
  - `StreamBuffer` class: accumula chunks, applica cap, espone callback per SSE
- `tests/v2/test_streaming.py`

**Dipendenze nuove**: nessuna.

**Edge case e fallback**
| Edge case | Comportamento |
|---|---|
| Stream interrotto a metà (network) | catch `StopIteration` prematura → buffer parziale conservato, batch marcato `partial`, retry 1× |
| Modello produce > 400k chars | trunca buffer, emette `error.response_too_large` SSE, prosegue |
| Stream lentissimo (no progress per 60s) | timeout per-chunk: 60s senza nuovi tokens → abort batch, retry intero |
| Stream-API fallisce a livello SDK | fallback su `generate_content` blocking (V1 behavior) con stesso cap |
| Cap raggiunto su universal_prompt cached | preserva il troncamento + log: utile per capire quale batch è anomalo |

**Test di non-regressione**
- `pytest tests/v2/test_streaming.py::test_chunks_emitted` → ricezione chunks incrementali entro 2s dal primo token.
- Test cap: simula response 1.5 MB → buffer si ferma a 400k, evento `error` emesso.
- Test fallback blocking: forza streaming non disponibile → comportamento V1 con cap funziona.
- Test latency: confronto V1 blocking vs V2 streaming su 5 batch → primo token visibile a < 3s in V2 vs ~25s in V1.

**Criterio di successo**: nessun batch può causare crash da risposta gigante; primo feedback < 3s.

---

### FASE 6 · SSE TYPED EVENTS + Heartbeat watchdog + State persistence (3 giorni)

**Obiettivo**: telemetria typed (12 categorie eventi), heartbeat ogni 5s, persistenza progress su disco per recovery post-crash.

**File nuovi**
- `webapp/v2/sse_emitter.py`
  - `SSEEmitter` class con metodi tipizzati: `emit_session_start`, `emit_phase_tick`, `emit_file_done`, `emit_error`, ecc.
  - Throttling lato server: max 5 eventi/sec, raggruppamento eventi simili (`file.done` × 10 → 1 batched)
- `webapp/v2/watchdog.py`
  - `HeartbeatWatchdog` thread separato, emette ogni 5s con `pid`, `rss_mb`, `queue_depth`
  - Auto-stop a fine pipeline
- `webapp/v2/progress_store.py`
  - `ProgressStore` append-only su `temp/progress/{session_id}.jsonl`
  - File lock con `filelock` per evitare race conditions tra thread
  - `replay(session_id) -> List[Event]` per recovery
- `webapp/v2/recovery_handler.py`
  - Endpoint `/api/v2/report/resume/{session_id}`
  - Legge `temp/progress/{session_id}.jsonl` e ricostruisce stato
- `tests/v2/test_sse_emitter.py`
- `tests/v2/test_watchdog.py`
- `tests/v2/test_progress_store.py`

**Dipendenze nuove**
```
filelock>=3.13.0
psutil>=5.9.0  (per RSS memoria)
```

**Edge case e fallback**
| Edge case | Comportamento |
|---|---|
| Disco pieno (no spazio per progress) | emit `error.disk_full`, prosegue senza persistenza, log warning |
| Crash worker durante write | `filelock` garantisce no corruption; replay legge fino all'ultimo evento valido |
| 2 client che riprendono lo stesso session_id | secondo client riceve solo replay, non duplicate stream |
| `psutil` non installato | watchdog degrada a "alive only" senza metriche RSS |
| Coda eventi piena (overflow) | drop dei `file.done` (batchabili), mai dei `error` |
| Eventi malformati | catch JSON encode error → log + skip, mai crash |

**Test di non-regressione**
- `pytest tests/v2/test_progress_store.py::test_replay_after_kill` → kill -9 worker, replay ricostruisce stato.
- Test watchdog: simula hang 30s → heartbeat continua, frontend rileva (mock client).
- Test throttling: emit 1000 eventi in 1s → solo ~5 raggiunti realmente al client.
- Test typed events: ogni tipo ha schema validato, eventi malformati respinti.
- Test concurrent write: 5 thread scrivono progress → no race condition (verifica con `filelock`).

**Criterio di successo**: `kill -9` su pipeline a metà → resume ricostruisce stato visualmente coerente, zero data loss.

---

### FASE 7 · COSTRUZIONE INCREMENTALE WORD via docxcompose (2-3 giorni)

**Obiettivo**: 1 sezione = 1 .docx parziale. Merge finale con `docxcompose`. Niente più `doc.save()` atomico → niente più lxml segfault.

**File nuovi**
- `webapp/v2/incremental_docx_builder.py`
  - `SectionBuilder` class: produce 1 .docx parziale per sezione (legale, contributiva, sicurezza, ecc.)
  - Path: `temp/sections/{session_id}/{NN}_{section_name}.docx`
- `webapp/v2/docx_merger.py`
  - `merge_sections(session_id: str) -> bytes` usa `docxcompose.composer.Composer`
  - Mantiene formattazione, indici, header
- `webapp/v2/section_download_handler.py`
  - Endpoint `/api/v2/report/download/{session_id}/section/{n}` per download anticipato
- `tests/v2/test_section_builder.py`
- `tests/v2/test_docx_merger.py`

**Dipendenze nuove**
```
docxcompose>=1.4.0
```

**Edge case e fallback**
| Edge case | Comportamento |
|---|---|
| docxcompose merge fallisce | fallback su `python-docx` atomico (V1) **ma** con cap YAML 6 MB applicato |
| Sezione vuota (0 documenti) | skip section, log info, indice finale ricostruito senza buchi |
| Stili inconsistenti tra sezioni | template comune `templates/v2_section_base.docx` per garantire stile uniforme |
| Sezione con > 100 documenti | sub-split automatico in N sotto-sezioni paginate |
| Disco pieno durante save sezione | retry su `temp/sections_fallback/`, in extremis abort con error chiaro |
| Cleanup file parziali | dopo download finale o dopo TTL 24h |

**Test di non-regressione**
- `pytest tests/v2/test_docx_merger.py::test_merge_88_sections` → merge di 88 sezioni stub, nessun crash, output Word valido.
- Test apertura output: il .docx mergiato apre correttamente in MS Word, LibreOffice, Google Docs.
- Test confronto V1 vs V2: stesso input → output Word con strutture equivalenti (heading, tabelle, contenuti).
- Test fallback: forza errore docxcompose → V1 builder produce comunque output (con warning).
- Test download anticipato: dopo Fase 6 (sezione 3/10), endpoint section/3 funziona, sezione 10 non esiste ancora (404).

**Criterio di successo**: 88-section merge senza crash, output Word visivamente equivalente a V1, nessuna regressione di formattazione.

---

### FASE 8 · PIPELINE V2 ORCHESTRATOR + endpoint completo (2 giorni)

**Obiettivo**: cucire insieme le Fasi 1-7 in un'unica pipeline. Sostituire lo stub di Fase 0.

**File nuovi/modificati**
- `webapp/v2/pipeline.py`
  - `process_zip_v2(zip_bytes, api_key, sse_emitter, ...) -> dict`
  - Orchestrazione end-to-end: ingestion → triage → classify → cache → ocr → analyze → docx
- `webapp/v2/orchestrator.py`
  - `PipelineOrchestrator` class con stati e transizioni esplicite
- Modifica `webapp/api_server.py` (additiva)
  - Sostituzione handler `/api/v2/report/process` con chiamata a `process_zip_v2`
  - Feature flag check: se `USE_V2_PIPELINE=true` e user in whitelist, redirect interno da `/api/report/process` a V2
- `tests/v2/test_pipeline_e2e.py`

**Dipendenze nuove**: nessuna (tutte già installate nelle fasi precedenti).

**Edge case e fallback**
| Edge case | Comportamento |
|---|---|
| Una fase fallisce (es. classifier API down) | pipeline continua con strategia degradata: classifier → ALTRO + default cap |
| Feature flag attivo ma user non in whitelist | usa V1 (no-op) |
| Errore irrecuperabile a metà | emit `error.pipeline_aborted` + persist progress + cleanup files temporanei |
| 2 chiamate concorrenti su stesso session_id | rifiutata seconda con 409 Conflict |
| Memoria insufficiente (RSS > 80%) | watchdog emette warning, pipeline rallenta concorrenza |

**Test di non-regressione**
- `pytest tests/v2/test_pipeline_e2e.py::test_full_run_small_zip` → ZIP 20 file → output completo.
- Test ZIP boss-size: ZIP 600+ file → no crash, no silent failure.
- Test feature flag: con `USE_V2_PIPELINE=false`, `/api/report/process` resta V1.
- Test feature flag user-specific: utente in whitelist riceve V2, altro utente riceve V1.
- Test golden set completo: 10 ZIP storici → V2 produce output entro tolleranza definita di V1.

**Criterio di successo**: end-to-end ZIP boss in < 9 minuti, golden set passa al ≥ 95%.

---

### FASE 9 · RUNBOOK, MONITORING, ROLLOUT (1-2 giorni)

**Obiettivo**: documentazione operativa e telemetria production-ready per il rollout graduale.

**File nuovi**
- `docs/V2_RUNBOOK.md` — manuale operativo (start, stop, troubleshooting)
- `docs/V2_METRICS.md` — KPI e thresholds di alert
- `webapp/v2/metrics_collector.py` — colleziona metriche per ogni run, scrive in `temp/metrics/v2_runs.jsonl`
- `scripts/v2_compare_runs.py` — compara N run V1 vs V2 da log
- `scripts/v2_rollout_canary.py` — script per attivare gradualmente whitelist user-by-user

**KPI tracciati per ogni run**
- `latency_p50`, `latency_p99`
- `tokens_input_total`, `tokens_cached`, `cache_hit_ratio`
- `ocr_calls_count`, `ocr_skipped_count` (PDF nativi salvati)
- `crashes`, `silent_failures` (target: 0)
- `cost_estimated_eur`

**Procedura di rollout**
1. Branch `v2-experimental` mergiato in `main` solo dopo Fase 8 con golden set ≥ 95%.
2. Whitelist iniziale: solo `DocAllfix` (test su nostro account).
3. Dopo 1 settimana stabile, espansione a 3 utenti pilot.
4. Dopo 2 settimane stabili, rollout 100%.
5. Dopo 1 mese di stabilità, deprecation warning per V1 (ma codice resta).
6. Mai cancellare V1 senza ≥ 3 mesi di V2 in produzione.

**Criterio di successo**: dashboard live, rollout canary documentato, procedura di rollback < 30s.

---

## §2. RIEPILOGO TEMPORALE

| Fase | Giorni | Cumulativo | Output validabile |
|---|---|---|---|
| 0 — Setup | 0.5 | 0.5 | endpoint stub V2 risponde |
| 1 — Triage | 1.5 | 2 | PDF nativi estratti senza OCR |
| 2 — Classifier | 1.5 | 3.5 | 90%+ accuracy su 50 file |
| 3 — Caching | 1 | 4.5 | -80% token su prompt verificato |
| 4 — Files API | 2 | 6.5 | OCR via files API funzionante |
| 5 — Streaming | 2 | 8.5 | primo token < 3s |
| 6 — Telemetria | 3 | 11.5 | resume post-crash funziona |
| 7 — Word incrementale | 3 | 14.5 | 88-section merge senza crash |
| 8 — Orchestrator | 2 | 16.5 | E2E golden set ≥ 95% |
| 9 — Rollout | 1.5 | 18 | dashboard + canary attivi |

**Totale: 18 giorni-uomo** (~4 settimane lavorative).

---

## §3. CONTROLLI DI CONGRUENZA TRASVERSALI

Questi controlli devono passare **dopo ogni fase**, non solo alla fine:

1. **Smoke test V1**: `curl POST /api/report/process` con ZIP test → output identico a baseline.
2. **Diff codice V1**: `git diff main webapp/modules/` deve essere **vuoto** durante tutte le fasi 0-8.
3. **Import check**: nessun file in `webapp/modules/` deve importare da `webapp.v2.*`.
4. **Feature flag default**: `USE_V2_PIPELINE` resta `false` di default fino a Fase 9.
5. **Test V1 esistenti**: tutti i test esistenti continuano a passare.
6. **Performance V1**: latenza V1 invariata (entro ±5%) durante tutto lo sviluppo V2.

---

## §4. DECISIONI VINCOLATE (decise il 2026-05-01, potenziate il 2026-05-01)

1. **`docxcompose` accettato + Fase 0.5 di PoC standalone**.
   *Motivazione*: libreria usata da Plone CMS da anni, ma per ridurre rischio Fase 7 facciamo un PoC isolato su 5 sezioni di test (`tests/v2/poc_docxcompose/`) prima di committare l'architettura. Valida edge case: stili divergenti, footer, indici, tabelle dinamiche.

2. **Cache refresh: cron 30 min (08-20) + on-demand fallback**.
   *Motivazione*: costo storage ~€1,80/mese trascurabile. Doppio meccanismo: cron mantiene cache caldo, on-demand al primo request del giorno se cron salta o ha avuto problemi. Zero downtime sul caching.

3. **Whitelist V2: `DocAllfix` + `shadow_test_user` automatizzato**.
   *Motivazione*: il primo è il nostro account interno. Il secondo è uno script (`scripts/v2_shadow_replay.py`) che ogni notte replay-a 10 ZIP storici tramite `/api/v2/report/process` per regression continua. Niente clienti reali fino a Fase 9.

4. **TTL `temp/progress/*.jsonl` = 7 giorni live + 30 giorni archiviati compressi**.
   *Motivazione*: live per recovery operativo. Archive compresso (gzip ~10×) in `temp/progress_archive/{yyyy-mm}/` per audit trail compliance e debugging post-mortem profondo. Spazio totale: ~80 MB/mese.

5. **Classifier dual-stage: `flash-lite` + `flash` double-check su confidence < 0.6**.
   *Motivazione*: flash-lite per il 95% dei casi (€0,001/ZIP). Per i casi a bassa confidenza (~5%), secondo passaggio con `flash` 2.5 standard. Accuracy attesa 97-98% vs 90% del solo lite. Costo extra: ~€0,0005/ZIP.

6. **Threading di default + Fase 8.5: subprocess isolation OPZIONALE production**.
   *Motivazione*: cause segfault eliminate a monte (Fasi 5+7). MA aggiungiamo `V2_USE_SUBPROCESS=true` come env var (default OFF in dev, ON in prod) per cintura definitiva. Implementazione `webapp/v2/subprocess_runner.py` con `multiprocessing.Process` + `Pipe` per IPC. Costo: ~50ms overhead per run, accettabile.

## §4-bis. OTTIMIZZAZIONI AGGIUNTIVE (cross-cutting)

Ogni Fase è arricchita con questi miglioramenti, non più tagliati per tempo:

| # | Miglioramento | Fase host | Implementazione |
|---|---|---|---|
| 7 | **Caching anche del prompt classificatore** | 3 | `cache_manager.py` gestisce 2 cache: universal_prompt + classifier_prompt |
| 8 | **Streaming parser YAML incrementale** | 5 | `webapp/v2/yaml_stream_parser.py`: emette `file.done` SSE appena un doc è completo nel YAML in arrivo, non a fine batch |
| 9 | **Manifest OCR persistente** | 4 | `temp/ocr_manifest/{session_id}.json` traccia file_uri Gemini Files API per resume granulare |
| 10 | **OpenTelemetry tracing** | 6 | `webapp/v2/otel_tracer.py` con span per ogni fase. Export OTLP per Grafana/Prometheus quando il cliente vorrà |
| 11 | **Template Word configurabile** | 7 | `webapp/templates/v2_audit_template.docx` con tag Jinja `{{ azienda.nome }}`. Layout modificabile in MS Word senza toccare codice |
| 12 | **Dry-run mode** | 8 | Query param `?dry_run=true` simula pipeline con risposte mock pre-canned. Zero token consumati |
| 13 | **A/B comparison automation** | 9 | `scripts/v2_compare_v1_v2.py` esegue lo stesso input su V1 e V2, produce report con diff testuale strutturato + metriche tokens/latency/qualità |
| 14 | **Signal markers extraction nel classifier** | 2 | Schema `ClassifiedFile` esteso con `data_doc_estimate`, `tipo_soggetto`, `lingua_documento`. Riduce 10-15% token nei prompt successivi |

## §5. CRONOPROGRAMMA AGGIORNATO

| Fase | Giorni | Cumulativo | Output validabile |
|---|---|---|---|
| 0 — Setup | 0.5 | 0.5 | endpoint stub V2 risponde |
| **0.5 — PoC docxcompose** | **1** | **1.5** | **PoC merge 5 sezioni → Word valido** |
| 1 — Triage | 1.5 | 3 | PDF nativi estratti senza OCR |
| 2 — Classifier (con dual-stage + signal markers) | 2 | 5 | 97%+ accuracy su 50 file |
| 3 — Caching (universal + classifier) | 1.5 | 6.5 | -90% token su entrambi i prompt |
| 4 — Files API + manifest persistente | 2.5 | 9 | OCR resume granulare funzionante |
| 5 — Streaming + parser incrementale | 2.5 | 11.5 | primo `file.done` < 5s |
| 6 — Telemetria + OTel + archiviazione | 4 | 15.5 | resume post-crash + Grafana-ready |
| 7 — Word incrementale + template configurabile | 3.5 | 19 | 88-section merge + template editable |
| 8 — Orchestrator + dry-run | 2.5 | 21.5 | E2E golden set ≥ 95% + dry-run testabile |
| 8.5 — Subprocess isolation | 1 | 22.5 | env var `V2_USE_SUBPROCESS` funzionante |
| 9 — Rollout + A/B comparison automation | 2 | 24.5 | dashboard + canary + report A/B |

**Totale: ~25 giorni-uomo (~5 settimane lavorative).**

---

## §5. AUTORIZZAZIONE A PROCEDERE

Stato corrente: **piano completato, in attesa di OK del cliente per Fase 1**.

Comando atteso: `OK, inizia a programmare la Fase 1`.

Dopo l'OK, l'agente procederà nell'ordine: Fase 0 (scaffolding) → Fase 1 (triage), con commit atomici per ogni step e PR di merge in `v2-experimental` dopo ogni criterio di successo verificato.
