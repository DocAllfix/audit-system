# AUDIT-OS Pipeline V2

Implementazione del **Metodo A — Triage Funnel** in namespace isolato.

## Regole di ingaggio

1. **Nessun file in `webapp/modules/` può importare da `webapp/v2/*`**.
2. **`webapp/v2/*.py` può importare solo da**: stdlib, dipendenze installate, `webapp/config.py`.
3. **Endpoint produzione `/api/report/process` resta su V1**. V2 risponde su `/api/v2/report/process`.
4. **Feature flag `USE_V2_PIPELINE`** + whitelist utenti in `config.py` controllano l'attivazione.

## Struttura

```
webapp/v2/
├── __init__.py
├── README.md                    (questo file)
├── pipeline.py                  (orchestrator end-to-end, Fase 8)
├── text_extractor.py            (pypdfium2 wrapper, Fase 1)
├── file_triage.py               (routing native vs OCR, Fase 1)
├── document_classifier.py       (Gemini Flash Lite, Fase 2)
├── schemas/
│   └── classification.py        (modelli Pydantic, Fase 2)
├── cache_manager.py             (context caching Gemini, Fase 3)
├── cache_refresher.py           (cron refresh, Fase 3)
├── gemini_ocr_v2.py             (Files API OCR, Fase 4)
├── file_uploader.py             (upload retry, Fase 4)
├── gemini_client_v2.py          (streaming + cap, Fase 5)
├── stream_buffer.py             (cap response, Fase 5)
├── yaml_stream_parser.py        (parser YAML incrementale, Fase 5)
├── sse_emitter.py               (eventi SSE typed, Fase 6)
├── watchdog.py                  (heartbeat, Fase 6)
├── progress_store.py            (persistenza JSONL, Fase 6)
├── recovery_handler.py          (resume endpoint, Fase 6)
├── otel_tracer.py               (OpenTelemetry, Fase 6)
├── cleanup.py                   (TTL progress + archive, Fase 6)
├── incremental_docx_builder.py  (sezioni .docx, Fase 7)
├── docx_merger.py               (docxcompose merge, Fase 7)
├── section_download_handler.py  (download anticipato, Fase 7)
├── orchestrator.py              (state machine, Fase 8)
└── subprocess_runner.py         (isolation opzionale, Fase 8.5)
```

## Stato corrente

Fase 0 completata: scaffolding + endpoint stub funzionante.
Vedi `docs/V2_EXECUTION_TRACKER.md` per stato dettagliato.
