# Architecture — Struttura dell'Applicazione

> **Ultimo aggiornamento**: 2026-04-20
> **Migrazione FastAPI + React COMPLETATA** — Streamlit rimosso dal server.

## Overview

AUDIT-OS è una **web application multi-tier** per l'automazione di audit documentali. Stack di produzione:

- **Reverse proxy**: nginx (TLS Let's Encrypt, dominio `auditos.duckdns.org`)
- **Backend**: FastAPI + uvicorn (`127.0.0.1:8000`, 2 workers) — espone API REST + SSE
- **Frontend**: React + Vite SPA (build statico servito da nginx)
- **Persistenza**: SQLite (`/opt/auditos/webapp/data/audit.db`)
- **Proxy API Gemini**: Google Cloud Function `gemini-proxy` (bypass blocco geografico Germany→Gemini)

Tre funzionalità principali (ora esposte come view React distinte, precedentemente Tab Streamlit):

1. **Genera Report** — estrae evidenze da ZIP/cartella e genera report Word
2. **Produci Checklist** — genera JSON strutturato con clausole compilate
3. **Compila Checklist** — riempie template Word a partire dal JSON

## Topologia di Rete

```
Internet
   │ HTTPS (443, cert Let's Encrypt)
   ▼
┌──────────────────────────────────────────┐
│  nginx  (auditos.duckdns.org)            │
│  - SPA routing (try_files)               │
│  - /api/*  → proxy_pass 127.0.0.1:8000   │
│  - SSE:   proxy_buffering off, 600s tmo  │
└───────────────────┬──────────────────────┘
                    │ HTTP
                    ▼
┌──────────────────────────────────────────┐
│  uvicorn (systemd: auditos.service)      │
│  workers=2, 127.0.0.1:8000               │
│  → api_server.py (FastAPI app)           │
│     ├─ /api/report/*   (Tab 1)           │
│     ├─ /api/checklist/*(Tab 2/3)         │
│     ├─ /api/admin/*    (osservabilità)   │
│     └─ /api/health                       │
└───────────────────┬──────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────┐
│  Moduli Python (webapp/modules/)         │
│  report_generator · gemini_client        │
│  gemini_ocr · checklist_producer         │
│  checklist_filler · db_manager           │
│  auth_manager                            │
└───────────────────┬──────────────────────┘
                    │
      ┌─────────────┼──────────────┐
      ▼             ▼              ▼
  audit.db    Gemini (via CF)   /opt/auditos/temp/
                                  └─ logs/  (audit trail, 30d)
```

## Struttura Directory (Server)

```
/opt/auditos/
├── webapp/
│   ├── api_server.py           # Entry point FastAPI
│   ├── config.py
│   ├── .env                    # GEMINI_API_KEY + env (G3)
│   ├── modules/
│   │   ├── report_generator.py     # Pipeline report (strutturata + narrativa)
│   │   ├── gemini_client.py        # Client Gemini (batch + structured)
│   │   ├── gemini_ocr.py           # OCR PyMuPDF (MuPDF silenced)
│   │   ├── checklist_producer.py   # Genera JSON clausole
│   │   ├── checklist_filler.py     # Compila template Word
│   │   ├── auth_manager.py
│   │   └── db_manager.py           # SQLite + error_log + migrazioni
│   ├── prompts/
│   │   ├── checklist/              # ISO 9001/27001/37001/39001/50001 + altri
│   │   ├── report/
│   │   └── universal_evidence_prompt.md  # Prompt B-3/B-4
│   ├── templates/
│   ├── data/
│   │   └── audit.db                # 1.065 pratiche al 2026-04-20
│   └── venv/                       # Python virtualenv
├── frontend/                       # React SPA build (owner: auditos:auditos — G2)
│   ├── index.html
│   └── assets/
├── scripts/
│   ├── backup_db.sh                # G1 — cron 03:15
│   └── temp_cleanup.sh             # G5 — cron 03:30
├── backups/                        # Retention 30 daily + 12 monthly
│   ├── daily_YYYYMMDD.db.gz
│   ├── monthly_YYYYMM.db.gz
│   └── backup.log
└── temp/
    └── logs/                       # Audit trail JSON, 30d retention
```

## Struttura Directory (Locale Canonico)

```
c:\Users\user\AUDITORSEMI\webapp\   # Allineato 1:1 con /opt/auditos/webapp/
├── api_server.py
├── modules/
├── prompts/
├── scripts/
│   ├── backup_db.sh
│   └── temp_cleanup.sh
└── _server_sync/                   # Fixture per test pre-deploy
```

## File Chiave

### `api_server.py`
- Entry point FastAPI; registra router per report/checklist/admin
- Carica `.env` via `python-dotenv` (`override=False` per rispettare env di systemd)
- **Modifica quando**: nuovi endpoint, middleware, auth, CORS

### `modules/report_generator.py`
- `process_zip_and_generate_report(input_source, api_key, progress_cb, status_cb, input_type)` — firma invariante (call site in `api_server.py`)
- `_pipeline_strutturata()` (riga 568) — pipeline unica attiva
- `NOMI_GENERICI_ZIP` (R-3) — risoluzione conflitto nome azienda
- **Contratto ritorno**: `(docx_bytes, stats_dict, filename)` con `stats_dict["company_name"]`

### `modules/gemini_client.py`
- `analyze_batch()` (narrativa, fallback) + `analyze_batch_structured()` (B-3, default)
- `_parse_json_response()` (R-2) — parser a 3 livelli
- `(response.text or "").strip()` (R-1) — guardia NoneType

### `modules/gemini_ocr.py`
- OCR via PyMuPDF
- `fitz.TOOLS.mupdf_display_errors(False)` (G6/G7) — silenzia stderr MuPDF globalmente dopo import

### `modules/db_manager.py`
- Migrazioni idempotenti via `ALTER TABLE` + try/except
- Colonne osservabilità: `batch_index`, `docs_involved`, `error_subtype`, `auto_recovered`, `recovery_details`, `resolved_by`, `resolved_at`
- `save_partial_error()` (R-4) — hook per batch parziali
- `mark_error_resolved(error_id, resolved_by)` (B1) — chiusura errori dal pannello admin

### Frontend (`/opt/auditos/frontend/`)
- Build Vite+React statico
- Consuma `/api/*` su stesso origin (niente CORS)
- SSE via `EventSource` per progress report

## Servizio Systemd

```
/etc/systemd/system/auditos.service
```

Contenuto essenziale:
```
[Service]
User=auditos
WorkingDirectory=/opt/auditos/webapp
Environment=PATH=/opt/auditos/webapp/venv/bin
ExecStart=/opt/auditos/webapp/venv/bin/uvicorn api_server:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
```

Comandi:
- `systemctl status auditos`
- `sudo systemctl restart auditos` — **obbligatorio** dopo modifiche `.py` o prompt `.md`
- `journalctl -u auditos -f` — log live

## Automazioni Cron (utente `auditos`)

| Orario | Comando | Scopo |
|--------|---------|-------|
| 03:15 | `/opt/auditos/scripts/backup_db.sh` | Backup SQLite giornaliero (G1) |
| 03:30 | `/opt/auditos/scripts/temp_cleanup.sh` | Cleanup temp GDPR-aware (G5) |

Output in `/opt/auditos/backups/backup.log` e `/opt/auditos/temp/cleanup.log`.

## Cache in Memoria

I prompt vengono precaricati all'avvio di uvicorn (`prefetch_all_prompts()` in `checklist_producer.py`). **Modificare un prompt `.md` sul server non ha effetto finché `auditos.service` non viene riavviato.**

## Deploy

- **Upload**: `pscp` (mai `plink + cat` — corrompe UTF-8)
- **Restart obbligatorio** dopo modifiche a `.py` o prompt `.md`
- **Canonical locale**: `c:\Users\user\AUDITORSEMI\webapp\` — allineare con `_server_sync\` dopo ogni modifica server-side

## Invarianti di Sistema (MAI toccare senza analisi)

| Componente | Motivo |
|-----------|--------|
| Firma `process_zip_and_generate_report(input_source, api_key, progress_callback, status_callback, input_type)` | API contract con `api_server.py` |
| Contratto ritorno `(docx_bytes, stats_dict, filename)` | Pagine Checklist/Compilazione leggono `stats_dict["company_name"]` |
| `MACROAREA_ORDER` (10 categorie documenti) | Documenti già categorizzati nel DB |
| Schema `pratiche` (1.065 record) | Migrazioni solo additive via `ALTER TABLE … IF NOT EXISTS`-style |
| `prefetch_all_prompts()` | Cache in-memory: richiede restart |

## Osservabilità

- **Log servizio**: `journalctl -u auditos [-f]`
- **Error log DB**: tabella `error_log` (endpoint admin React)
- **Backup log**: `/opt/auditos/backups/backup.log`
- **Cleanup log**: `/opt/auditos/temp/cleanup.log`
- **Audit trail JSON**: `/opt/auditos/temp/logs/audit_log_*.json` (30d retention)
- **Health check**: `GET /api/health`
