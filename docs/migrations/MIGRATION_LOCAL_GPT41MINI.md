# Migrazione locale: gpt-4.1-mini Azure + prompt v3 + fallback Gemini

Documento di onboarding per testare la pipeline V2 in **LOCALE** col provider
`gpt-4.1-mini-azure` validato negli spike (4 pratiche, 0 parse failures, 0
batch persi col fallback Gemini, GDPR Azure EU).

PROD non è toccato: il default `V2_PROVIDER=gemini-2.5-flash` riproduce
identicamente il comportamento attuale.

---

## Cosa è stato cambiato

### File NUOVI (porting)

- `webapp/v2/azure_openai_client_v2.py` — client Azure Foundry v1 con retry +
  eccezione `AzureRateLimitExhausted` per fallback
- `webapp/v2/provider_profiles_v2.py` — 2 profili: `gemini-2.5-flash` (default
  PROD) + `gpt-4.1-mini-azure` (workers=6, batch=10/180K, cap 2.5×, output 32K)
- `webapp/v2/llm_dispatch.py` — factory `build_dispatch(provider)` + helper
  `fallback_disabled()`
- `webapp/prompts/universal_evidence_prompt_v3.md` — prompt V3 (copia di v3.1
  validato in spike, header aggiornato a "V3 PROD")
- `webapp/v2/_legacy/pipeline_pre_azure_2026_05_04.py.bak` — snapshot del
  pipeline.py pre-porting per audit retroattivo
- `tests/test_v2/test_provider_profiles_v2.py` (11 test)
- `tests/test_v2/test_azure_openai_client_v2.py` (14 test)
- `tests/test_v2/test_pipeline_dispatch.py` (7 test)
- `tests/test_v2/test_zip_extractor_macosx.py` (7 test)

### File MODIFICATI

- `webapp/v2/pipeline.py` — kwarg `provider: Optional[str]`, dispatch tra
  Gemini e Azure, fallback automatico Gemini su `AzureRateLimitExhausted`,
  `n_fallback_batches`/`fallback_batch_idxs`/`provider` nel return dict
- `webapp/v2/zip_extractor.py` — filtro `__MACOSX/` + basename `._*` (resource
  fork macOS) tramite helper `_is_macos_artifact()`
- `webapp/.env.example` — sezione "V2 PIPELINE — Provider LLM" con Azure vars
  + `V2_PROVIDER` + `V2_DISABLE_FALLBACK`

### File LASCIATI INVARIATI (esplicitamente)

- `webapp/v2/gemini_client_v2.py` — resta il client Gemini default e
  fallback runtime
- `webapp/v2/yaml_parser.py`, `file_triage.py`, `text_handlers.py`,
  `document_classifier.py`, `gemini_ocr_v2.py`, `incremental_docx_builder.py`,
  `docx_merger.py`, `relevance_safetynet.py`, `genai_factory_v2.py`,
  `cache_manager.py`, `token_meter.py`
- `webapp/prompts/universal_evidence_prompt.md` (V1 legacy)
- `webapp/prompts/universal_evidence_prompt_v2.md` (V2 PROD attuale Gemini)
- `frontend/` (zero modifiche UI)
- `webapp/api_server.py`, `webapp/modules/*` (V1 legacy)
- Tutti gli `scripts/test_*.py`, `scripts/spike_*`, `webapp/spike_llm/`
  (artefatti spike, restano nel branch)

### Branch separati creati

- `feat/v1-gemini-throttle` — fix throttling Gemini per V1 legacy
  (`gemini_throttle.py` + integrazione in 6 moduli V1) committato in branch
  isolato per non contaminare la migrazione Azure
- `feature/v2-azure-gpt41mini-port` — porting Azure (questo branch)
- Tag git `spike-pre-prod-port-2026-05-04` — snapshot del branch
  `spike-deepseek-v4-flash` prima del porting

---

## Come avviare LOCALE con gpt-4.1-mini Azure

### 1. Installazione dipendenza

```bash
pip install "openai>=1.0"
```

(Già presente in `webapp/requirements.txt` se è stato installato lo spike;
altrimenti aggiungere riga `openai>=1.0`.)

### 2. Configurazione `.env` (copia da `.env.example`)

In `webapp/.env`:

```env
# Provider attivo
V2_PROVIDER=gpt-4.1-mini-azure

# Azure OpenAI Foundry v1 (NON il vecchio Azure OpenAI con api-version)
AZURE_OPENAI_API_KEY=<la tua chiave>
AZURE_OPENAI_ENDPOINT=https://<resource>.services.ai.azure.com/openai/v1
AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI=gpt-4.1-mini

# Fallback Gemini su 429 cumulativi (default 0 = ATTIVO)
V2_DISABLE_FALLBACK=0

# Gemini sempre richiesto (per OCR + classifier + fallback)
GEMINI_API_KEY=<la tua chiave>
```

### 3. Avvio webapp + frontend

Backend:
```bash
cd webapp
python api_server.py
```

Frontend (in un altro terminale):
```bash
cd frontend
npm run dev
```

### 4. Test via UI

Caricare un ZIP di pratica nella UI standard. La pipeline V2 userà
automaticamente Azure se `V2_PROVIDER=gpt-4.1-mini-azure`.

Il return JSON dell'endpoint `/api/v2/report/process` includerà ora:

```json
{
  "success": true,
  "provider": "gpt-4.1-mini-azure",
  "n_fallback_batches": 0,
  "fallback_batch_idxs": [],
  "stats": {
    "provider": "gpt-4.1-mini-azure",
    "tokens": { ... }
  }
}
```

### 5. Rollback istantaneo a Gemini

Cambiare in `.env`:

```env
V2_PROVIDER=gemini-2.5-flash
```

E riavviare. Il comportamento torna identico al PROD attuale.

---

## Risultati attesi (dallo spike)

| Pratica | Provider | Tempo | Costo | Schede | Parse failures |
|---|---|---|---|---|---|
| SIRIH 27001 (62 file) | gpt-4.1-mini-azure | ~3 min | ~€0.20 | ~62 | 0 |
| MEDIL 37001 (163 file) | gpt-4.1-mini-azure | ~6 min | ~€0.35 | ~163 | 0 |
| Stesse pratiche | gemini-2.5-flash | +15% tempo | +63% costo | uguale | 0 |

Cross-provider validato: **−63% costo medio**, **−15% tempo medio**, regola
1:1 (1 file = 1 scheda) rispettata in entrambi.

---

## Test programmatico (smoke)

### Smoke 1 — Gemini default invariato

```python
import os
os.environ["V2_PROVIDER"] = "gemini-2.5-flash"
from v2.pipeline import process_zip_v2

result = process_zip_v2(
    zip_bytes=open("ALLEGATI SIRIH 27001.zip", "rb").read(),
    session_id="local_smoke_gemini",
    api_key=os.environ["GEMINI_API_KEY"],
)
assert result["success"]
assert result["provider"] == "gemini-2.5-flash"
assert result["n_fallback_batches"] == 0
```

### Smoke 2 — Azure happy path

```python
os.environ["V2_PROVIDER"] = "gpt-4.1-mini-azure"
result = process_zip_v2(
    zip_bytes=open("ALLEGATI SIRIH 27001.zip", "rb").read(),
    session_id="local_smoke_azure",
    api_key=os.environ["GEMINI_API_KEY"],  # Gemini per OCR/classifier
)
assert result["success"]
assert result["provider"] == "gpt-4.1-mini-azure"
assert result.get("n_documents", 0) >= 60
```

### Smoke 3 — Fallback su 429

Lanciare due ZIP grandi (MEDIL + SIRIH) in parallelo da 2 thread con provider
Azure. Almeno qualche batch dovrebbe attivare il fallback Gemini, visibile via
`result["n_fallback_batches"] > 0` e log `[V2 PIPELINE] Batch N Azure 429
esaurito → fallback Gemini`.

---

## Test pytest

```bash
pytest tests/test_v2/ -v
# 38 test nuovi tutti verdi

pytest tests/test_v2_pipeline/ -v
# 484 test esistenti tutti verdi (zero regressione)
```

---

## Stato

- **Locale**: PRONTO per test UI (richiede webapp avviato + chiavi configurate)
- **PROD**: SCOPE SEPARATO — go-live PROD si valuta DOPO i test locali

Il rollback è banale (cambio di env var). Nessuna migrazione DB. Nessuna
breaking change al frontend. Il flow Gemini esistente è bit-per-bit invariato
quando `V2_PROVIDER=gemini-2.5-flash`.
