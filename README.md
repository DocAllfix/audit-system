# AUDIT-OS

**Piattaforma di automazione per Audit di Terza Parte** — estrazione evidenze, compilazione checklist e generazione documentale guidata da LLM (Google Gemini).

> Prodotto proprietario — versione cliente + base per sviluppo verticale internazionale.

---

## Architettura

Framework **DOE** a tre livelli:

| Livello | Cartella | Responsabilità |
|---------|----------|----------------|
| **Directives** | `directives/` | SOP operative (Markdown) — regole e formati |
| **Orchestration** | agente LLM | Router decisionale (CLAUDE.md) |
| **Execution** | `execution/`, `webapp/modules/` | Script Python deterministici |

### Pipeline operativa (3 fasi)

1. **Fase 1 — Estrazione evidenze strutturate**
   ZIP documenti → parsing → `PROMPT UNIVERSALE ADATTIVO v2.1` → relazione `.docx`
2. **Fase 2 — Checklist Producer**
   Evidenze → schema JSON di checklist valorizzata (norm-agnostic)
3. **Fase 3 — Checklist Filler**
   JSON + template `.docx/.xlsx` → checklist compilata finale

---

## Stack

- **Backend:** FastAPI + Uvicorn (systemd `auditos.service`, 2 worker)
- **Frontend:** React + Vite + Zustand
- **LLM:** Google Gemini 2.5 Flash via Cloud Function proxy
- **Database:** SQLite (runtime, non versionato)
- **OCR:** Tesseract + Poppler (fallback da Gemini OCR)

---

## Struttura repository

```
├── directives/          SOP operative (Markdown)
├── execution/           Script deterministici Python
├── webapp/              Backend FastAPI
│   ├── api_server.py
│   ├── modules/         auth, checklist, evidence, gemini, logger, report
│   ├── prompts/         Prompt attivi (universal + checklist)
│   └── templates/       Template .docx/.xlsx per ogni norma supportata
├── frontend/            React + Vite app
├── cloud_function/      Proxy Google Cloud Function per Gemini
├── maintenancewebapp/   Documentazione (ARCHITECTURE, ROADMAP, DEPLOY)
├── legacy/              Snapshot pipeline Fase 1 narrativa (rollback)
└── testlocalresults/    Output regression test
```

---

## Setup locale

### Backend

```bash
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r webapp/requirements.txt
cp webapp/.env.example webapp/.env   # compila i valori
cp webapp/config/users.example.json webapp/config/users.json   # genera hash bcrypt
uvicorn webapp.api_server:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env    # imposta VITE_API_BASE_URL
npm run dev             # dev server :5173
```

---

## Norme supportate

ISO 9001 · ISO 14001 · ISO 45001 · ISO 14064 · ISO 27001 · ISO 37001 · ISO 39001 · ISO 50001 (ESQ + CERTIS) · PAS 24000 · ESG

---

## Deploy

Deploy manuale su server cliente via workflow GitHub Actions `deploy.yml` (trigger `workflow_dispatch`). Dettagli in [`maintenancewebapp/DEPLOY_GUIDE.md`](maintenancewebapp/DEPLOY_GUIDE.md).

---

## Documentazione

- [`CLAUDE.md`](CLAUDE.md) — Costituzione agente AI (instructions per Claude/LLM)
- [`maintenancewebapp/ARCHITECTURE.md`](maintenancewebapp/ARCHITECTURE.md) — Architettura sistema
- [`maintenancewebapp/ROADMAP.md`](maintenancewebapp/ROADMAP.md) — Roadmap tecnica
- [`maintenancewebapp/TROUBLESHOOTING.md`](maintenancewebapp/TROUBLESHOOTING.md) — Troubleshooting comune
- [`legacy/fase1_narrative_pipeline/README.md`](legacy/fase1_narrative_pipeline/README.md) — Rollback Fase 1 narrativa

---

## Licenza

**Proprietario.** Tutti i diritti riservati. Distribuzione soggetta a contratto.
