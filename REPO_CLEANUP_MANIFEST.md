# REPO CLEANUP MANIFEST — AUDIT-OS

**Data:** 2026-04-21
**Obiettivo:** Ripulire il repo locale in preparazione alla pubblicazione su GitHub come prodotto verticale distribuibile.
**Autore decisioni:** Alessandro (user) + Claude
**Linked memory:** `~/.claude/projects/c--Users-user-AUDITORSEMI/memory/project_cleanup_plan.md`

---

## 1 · STRATEGIA GENERALE

- **GitHub main = verità** → CI (test locale) → deploy manuale su server cliente
- **Secrets** mai committati — `.env` / `users.json` / `sessions.json` restano solo sul server, nel repo ci vanno `.example`
- **Fase 1 narrativa (vecchio approccio)** preservata come dead code in `report_generator.py` + snapshot in `legacy/fase1_narrative_pipeline/` per rollback futuro
- **i18n** rinviata (nessuna azione adesso)

---

## 2 · DECISIONI FILE-PER-FILE

### Root

| Path | Azione | Motivo |
|------|--------|--------|
| `CLAUDE.md` | **KEEP** | Costituzione agente attiva |
| `GEMINI.md` | **DELETE** | Superata da CLAUDE.md |
| `PROMPT_UNIVERSALE_ADATTIVO_v2.md` | **DELETE** | Superato — il prompt attivo vive in `webapp/prompts/universal_evidence_prompt.md` |
| `Programma Fincantieri-6322 (1).mpp` | **DELETE** | Scratch MS Project |
| `requirements.txt` | **KEEP** | Root deps (venv setup) |
| `sample_log.json` / `sample_log_jan.json` | **DELETE** | Scratch di analisi |
| `discrepanze_analisi.json` | **DELETE** | Scratch di analisi |
| `mpp_*.txt` (4 file) | **DELETE** | Scratch |
| `analyze_*.py` (4 file) | **DELETE** | Script scratch obsoleti |
| `verify_*.py` (3 file) | **DELETE** | Script scratch obsoleti |
| `test_api.py` / `test_imports.py` | **DELETE** | Script scratch obsoleti |
| `debug_pas.py` | **DELETE** | Script scratch |
| `probe_cam_mpp.py` | **DELETE** | Script scratch |
| `recover_report.py` | **DELETE** | Script scratch |
| `generate_report_from_api.py` | **DELETE** | Script scratch |
| `generate_users.py` | **DELETE** | Script one-shot già eseguito |
| `create_test_files.py` | **DELETE** | Script scratch |

### Root — Directory

| Path | Azione | Motivo |
|------|--------|--------|
| `_server_sync/` | **DELETE** | Scratch di sincronizzazione |
| `errorcomp/` | **DELETE** | Scratch |
| `input/` | **DELETE** | Scratch |
| `output/` | **DELETE** | Scratch |
| `results_test/` | **DELETE** | Scratch |
| `test_files/` | **DELETE** | Scratch |
| `test_fixtures/` | **DELETE** | Scratch |
| `tools/` | **DELETE** | Scratch |
| `temp/` | **DELETE** | Scratch di extract/debug |
| `venv/` | **KEEP localmente / GITIGNORE** | Virtualenv locale |
| `directives/` | **KEEP** | SOP operative (documentazione attiva) |
| `execution/` | **KEEP** | Script deterministici attivi |
| `testlocalresults/` | **KEEP** | Output regression test |
| `maintenancewebapp/` | **KEEP** | Cartella docs (ARCHITECTURE, DEPLOY_GUIDE, ROADMAP, TROUBLESHOOTING, SERVER_ACCESS, README, PIANO_B) |
| `cloud_function/` | **KEEP** | Proxy Gemini (deploy indipendente, codice versionato) |
| `base frontend/` | **RENAME → `frontend/`** | Nome con spazio problematico per tooling Unix |
| `webapp/` | **KEEP** (con pulizie interne) | Backend FastAPI attivo |

### `webapp/`

| Path | Azione | Motivo |
|------|--------|--------|
| `webapp/api_server.py` | **KEEP** | Entry point FastAPI attivo |
| `webapp/config.py` | **KEEP** | Config paths attivi |
| `webapp/requirements.txt` | **KEEP** | Deps webapp |
| `webapp/app.py` | **DELETE** | Streamlit legacy — funzioni migrate a api_server.py |
| `webapp/.streamlit/` | **DELETE** | Config Streamlit legacy (secrets.toml + config.toml non più usati) |
| `webapp/static/` | **DELETE** | Vuota |
| `webapp/resultstoanalize/` | **DELETE** | Scratch di analisi |
| `webapp/__pycache__/` | **DELETE + GITIGNORE** | Build Python |
| `webapp/scripts/` | **KEEP** | `backup_db.sh`, `temp_cleanup.sh` usati sul server |
| `webapp/templates/` | **KEEP** | Template .docx/.xlsx delle checklist |
| `webapp/prompts/api_prompt.md` | **KEEP** | ⚠️ Eager-loaded da `GeminiClient.__init__` — non rimuovere |
| `webapp/prompts/universal_evidence_prompt.md` | **KEEP** | Prompt attivo Fase 1 strutturata |
| `webapp/prompts/checklist/` | **KEEP** | Prompt checklist attivi |
| `webapp/prompts/checklist_schemas/` | **KEEP** | Schemi checklist |
| `webapp/config/users.json` | **GITIGNORE** (file resta sul server, non sul repo) | Credenziali reali con bcrypt |
| `webapp/config/sessions.json` | **GITIGNORE** | Sessioni runtime |
| `webapp/data/audit.db` | **GITIGNORE** | Database runtime |

### `webapp/modules/`

| Path | Azione | Motivo |
|------|--------|--------|
| `__init__.py` | **KEEP** | Package marker |
| `__pycache__/` | **DELETE + GITIGNORE** | Build Python |
| `auth_manager.py` | **KEEP** | Auth attiva |
| `checklist_filler.py` | **KEEP** | Fase 3 attiva |
| `checklist_producer.py` | **KEEP** | Fase 2 attiva |
| `db_manager.py` | **KEEP** | DB attivo |
| `gemini_client.py` | **KEEP** | Client LLM attivo |
| `gemini_ocr.py` | **KEEP** | OCR attivo |
| `genai_factory.py` | **KEEP** | Factory provider |
| `logger.py` | **KEEP** | Logging attivo |
| `performance_logger.py` | **KEEP** | Perf logging attivo |
| `report_generator.py` | **KEEP** | ⚠️ Contiene Fase 1 narrativa come dead code preservato (righe 431-770 e 877+). NON toccare |
| `structured_evidence_generator.py` | **KEEP** | Fase 1 strutturata attiva |
| `structured_evidence_parser.py` | **KEEP** | Parser attivo |
| `support_wizard.py` | **DELETE** | Streamlit FAQ legacy — già migrato a React `Supporto.jsx` |

### `base frontend/` (→ `frontend/`)

| Path | Azione | Motivo |
|------|--------|--------|
| `src/`, `index.html`, `package.json`, `vite.config.js`, configs | **KEEP** | Codice React attivo |
| `base44/` | **KEEP** (verify) | Directory componenti |
| `README.md` | **KEEP** | Docs |
| `dist/` | **GITIGNORE** (not delete: artefatto deploy locale) | Build output |
| `dist_deploy.zip` | **DELETE** | Artefatto deploy |
| `node_modules/` | **GITIGNORE** | Deps |

---

## 3 · NUOVA STRUTTURA DA CREARE

### `legacy/fase1_narrative_pipeline/`
- `README.md` — istruzioni per rollback al metodo narrativo
- `report_generator.original.py` — snapshot completo pre-pipeline-strutturata
- `api_prompt.md` — copia (l'originale rimane in `webapp/prompts/`, eager-loaded)

### File infrastruttura repo
- `.gitignore` (root)
- `webapp/.env.example`
- `frontend/.env.example` (dopo rinomina)
- `webapp/config/users.example.json` (template)
- `webapp/config/sessions.example.json` (template)

---

## 4 · CONTROANALISI CRITICHE

1. **`api_prompt.md` eager-loaded**: `GeminiClient.__init__` (gemini_client.py:44) chiama `_load_system_prompt()` che apre il file. Anche se `self.system_prompt` è poi usato solo da `analyze_batch` (dead code), il file DEVE esistere al percorso `webapp/prompts/api_prompt.md` altrimenti la classe rompe all'istanziazione. **→ NON rimuovere originale, solo copiare in `legacy/`.**

2. **`optimize_text_content` funzione condivisa** (report_generator.py:507): usata sia dalla pipeline strutturata (attiva) sia dalla narrativa (dead). **→ Non estraibile; `report_generator.py` resta indivisibile.**

3. **Rinomina `base frontend/` → `frontend/`**: grep completo per `base.frontend|base_frontend|basefrontend` → zero riferimenti hardcoded nel codice. **→ Sicuro.**

4. **`users.json` / `sessions.json` reali**: versioni locale e server differiscono. Il deploy NON deve sovrascriverli. **→ Entrambi in `.gitignore`, creare solo gli `.example`.**

---

## 5 · ORDINE DI ESECUZIONE

1. ✅ Salvare piano in memoria
2. ✅ Creare questo MANIFEST
3. Creare `legacy/fase1_narrative_pipeline/` + README + snapshot + prompt copia
4. Creare `.gitignore`, `.env.example` (x2), `users.example.json`, `sessions.example.json`
5. Eliminare file/dir root obsoleti
6. Eliminare `webapp/app.py`, `webapp/modules/support_wizard.py`, `webapp/.streamlit/`, `webapp/static/`, `webapp/resultstoanalize/`, `__pycache__/` (x2), `base frontend/dist_deploy.zip`
7. Rinominare `base frontend/` → `frontend/`
8. Verifica import chain `api_server.py` (smoke test import)
9. Conferma utente → passaggio a GitHub setup
