# AUDIT-OS — ROADMAP TECNICA ATTIVA
## Piano di Evoluzione, Risanamento e Upgrade Architetturale

> **Ultimo aggiornamento**: 2026-04-20
> **Stato sistema**: Live e attivo in produzione — **migrazione FastAPI+React COMPLETATA**
> **Sessioni di riferimento**: [Refactoring Blueprint 2026-04-18] + [Reliability Report 2026-04-18] + [Gap Infrastrutturali 2026-04-20]

---

## STATO 2026-04-20 — POST MIGRAZIONE

**Architettura attiva in produzione** (sostituisce il "§1 Stato Attuale" storico):
- **nginx** (TLS Let's Encrypt, `auditos.duckdns.org`) →
- **FastAPI + uvicorn** su `127.0.0.1:8000` (2 workers) →
- Moduli Python in `/opt/auditos/webapp/modules/`
- **Frontend React SPA** servito da `/opt/auditos/frontend/`
- **systemd unit**: `auditos.service` → `AUDIT-OS FastAPI Application`
- `app.py` Streamlit **rimosso dal server** (conservato storicamente in repo locale).

### Sprint Piano A e Piano B — CHIUSI (verificati nel codice live 2026-04-20)

| Sprint | Stato | Verifica |
|--------|-------|----------|
| R-1 OCR NoneType | ✅ CHIUSO | `(response.text or "").strip()` in `gemini_client.py:147,165` + guardie `gemini_ocr.py:254,286` |
| R-2 JSON parser 3 livelli | ✅ CHIUSO | `_parse_json_response()` in `gemini_client.py:267` |
| R-3 Conflitto nome azienda | ✅ CHIUSO | `NOMI_GENERICI_ZIP` in `report_generator.py:38` |
| R-4 Observability DB | ✅ CHIUSO | Colonne `batch_index/docs_involved/error_subtype/auto_recovered/recovery_details` + `save_partial_error()` in `db_manager.py:538` |
| R-5 Hook critici | ✅ CHIUSO | `save_partial_error()` chiamato da `analyze_batch_structured` |
| Quick Win MuPDF | ✅ CHIUSO | `contextlib.redirect_stderr` in `report_generator.py:394,1147` |
| B-3 GeminiClient strutturato | ✅ CHIUSO | `analyze_batch_structured()` in `gemini_client.py:456` |
| B-4 Pipeline strutturata | ✅ CHIUSO | `_pipeline_strutturata()` in `report_generator.py:568`, wired a 872 |

### Gap infrastrutturali risolti 2026-04-20

| Gap | Descrizione | Implementazione |
|-----|-------------|-----------------|
| **B1** | `mark_error_resolved()` crash admin | Firma estesa `(error_id, resolved_by)`; DB migrato con `resolved_by/resolved_at` in `db_manager.py` |
| **G1** | Backup DB assente (rischio perdita 1.065 pratiche) | `/opt/auditos/scripts/backup_db.sh` via `sqlite3.Connection.backup()`, cron 03:15, retention 30 daily + 12 monthly |
| **G2** | Ownership frontend errato (root:root) | `chown -R auditos:auditos /opt/auditos/frontend/` |
| **G3** | API key residua in `secrets.toml` (path Streamlit legacy) | `GEMINI_API_KEY` spostata in `.env`; `load_dotenv(override=False)` in `api_server.py`; `secrets.toml` archiviato come `.deprecated.20260420` |
| **G5** | Cleanup temp eliminava log (perdita audit trail) | `/opt/auditos/scripts/temp_cleanup.sh` GDPR-aware, preserva `temp/logs/` 30d, cron 03:30 |
| **G6/G7** | Rumore MuPDF in stderr (log sporchi) | `fitz.TOOLS.mupdf_display_errors(False)` globale dopo import in `gemini_ocr.py` |

### Gap esplicitamente esclusi dallo scope (decisione utente 2026-04-20)
- **G4** — Telegram `CHAT_ID` vuoto (bot configurato, nessun destinatario). Da completare se/quando si deciderà il canale notifiche.
- **G8** — Credenziali SSH in chiaro in `SERVER_ACCESS.md` / `DEPLOY_GUIDE.md`. Da ripulire in un passaggio dedicato di security hygiene.

### Baseline errori — confronto

| Metrica | Baseline 2026-04-18 | Post-fix 2026-04-20 |
|---------|---------------------|---------------------|
| Righe in `error_log` DB | 1 | 5 (R-4 attivo, errori vengono loggati) |
| Pratiche totali | 1.049 | 1.065 (sistema continua a lavorare in produzione) |
| Sprint pendenti | 8 | 0 |

---

## INDICE STORICO (contenuto sotto mantenuto come reference)

1. [Stato Attuale del Sistema](#1-stato-attuale-del-sistema) *(storico — vedi sezione "STATO 2026-04-20" sopra)*
2. [Piano A — Reliability & Error Eradication](#2-piano-a--reliability--error-eradication) *(tutti gli sprint CHIUSI — contenuto utile come documentazione del fix)*
3. [Piano B — PROMPT UNIVERSALE ADATTIVO v2.1](#3-piano-b--prompt-universale-adattivo-v21) *(B-3 e B-4 CHIUSI — contenuto utile per contesto Piano B)*
4. [Ordine di Esecuzione Globale](#4-ordine-di-esecuzione-globale) *(completato)*
5. [Statistiche Errori di Riferimento](#5-statistiche-errori-di-riferimento)
6. [Invarianti di Sistema (Mai Toccare)](#6-invarianti-di-sistema)

---

## 1. STATO ATTUALE DEL SISTEMA

### Infrastruttura
- **Server**: Hetzner Germany, IP 49.13.153.117, utente `auditos`
- **Servizio**: systemd `auditos.service` → Streamlit su porta 8501
- **Venv**: `/opt/auditos/webapp/venv/`
- **DB**: `/opt/auditos/webapp/data/audit.db` (SQLite)
- **Proxy API**: Google Cloud Function `gemini-proxy` (us-central1, progetto `audit-os-489815`) — bypassa blocco geografico Germany→Gemini

### Volume Produzione (al 2026-04-18)
- **1.049 pratiche** completate (report + checklist JSON + Word compilati)
- **371 report Tab 1** | **388 checklist JSON Tab 2** | **290 Word Tab 3**
- Norme supportate: ISO 9001, 14001, 45001, 39001, 27001, 37001, 50001, 14064, ESG, PAS 24000

### Librerie chiave installate in venv
- `extract-msg==0.55.0` — email Outlook .msg (installato 2026-04-15)
- `openpyxl` — già presente, gestisce .xlsm
- `PyMuPDF` — estrazione PDF veloce
- `python-docx` — generazione Word

### Estensioni supportate (post 2026-04-15)
`.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.xlsm`, `.txt`, `.csv`, `.rtf`, `.p7m`, `.jpg/.png/...`, `.msg` (email Outlook)

---

## 2. PIANO A — RELIABILITY & ERROR ERADICATION

### Mappa degli Errori (da eliminare in ordine di priorità)

| ID | Classe Errore | Occorrenze | Priorità | Status |
|----|---------------|------------|----------|--------|
| E-01 | `FAILED_PRECONDITION` blocco geografico API | 2.104 (tutti Apr 8) | RISOLTO | ✅ proxy attivo |
| E-02 | `Errore parsing JSON batch` (apostrofi/troncamento) | 252 | ALTA | ⚠️ da fare |
| E-03 | MuPDF errors ICC/stream (rumore log) | ~620 | BASSA | ⚠️ silenziate |
| E-04 | `OCR NoneType: .strip()` | 59 | MEDIA | ⚠️ da fare |
| E-05 | `Conflitto Azienda` (ZIP generico batte visura) | 35 | MEDIA | ⚠️ da fare |
| E-06 | Security probes `.git/config`, `.env` | 21 | ESTERNO | ℹ️ ignorare |
| E-07 | DB `error_log` non popolato (admin cieco) | 1 riga/1049 | CRITICO | ⚠️ da fare |

---

### SPRINT R-1 — Fix OCR NoneType
**File**: `webapp/modules/gemini_ocr.py`
**Tempo**: 30 minuti | **Rischio**: Zero

**Problema**: `response.text.strip()` crasha quando `response.text` è `None` (pagina vuota/errore soft API).

**Fix**:
```python
# PRIMA:
result = response.text.strip()

# DOPO:
raw = getattr(response, 'text', None)
if not raw:
    return ""  # pagina vuota — non è un errore bloccante
result = raw.strip()
```
Verificare TUTTI i punti dove si accede a `response.text` nel file.

**Checklist**:
- [ ] Grep: nessun `.text.strip()` non protetto
- [ ] Test fixture pagina vuota → ritorna `""`, no crash
- [ ] 48h log prod: zero `NoneType` errors

---

### SPRINT R-2 — JSON Parser Resiliente a 3 Livelli
**File**: `webapp/modules/gemini_client.py` — metodo `analyze_batch()`
**Tempo**: 1-2 ore | **Rischio**: Basso

**Problema**: Il parse JSON fallisce su apostrofi italiani non escapati (93% dei casi) e su risposte troncate a 32K token (5%). Fallimento silenzioso → batch perso → documenti mancanti nel report senza avviso.

**Fix — nuovo metodo `_parse_json_response()`**:
```python
def _parse_json_response(self, response_text: str, batch_index: int) -> list:
    """Parser a 3 livelli: standard → strict=False → regex per oggetto."""
    import re
    text = response_text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    text = text.strip()
    if '[' in text:
        text = text[text.index('['):text.rindex(']') + 1]
    else:
        return []

    # Livello 1
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Livello 2
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass

    # Livello 3: estrazione oggetto per oggetto con brace matching
    objects, depth, start_pos = [], 0, None
    for i, char in enumerate(text):
        if char == '{' and depth == 0:
            start_pos, depth = i, 1
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0 and start_pos is not None:
                try:
                    obj = json.loads(text[start_pos:i+1], strict=False)
                    if isinstance(obj, dict) and 'contenuto' in obj:
                        objects.append(obj)
                except json.JSONDecodeError:
                    pass
                start_pos = None

    if objects:
        print(f"[JSON PARSER] Batch {batch_index}: recuperati {len(objects)} obj via regex")
        return objects

    print(f"[JSON PARSER] Batch {batch_index}: FALLIMENTO TOTALE. Preview: {response_text[:200]}")
    return []
```

**Placeholder per documenti persi** (aggiungere dopo ritorno `[]`):
```python
if not paragraphs:
    for doc in documents:
        paragraphs.append({
            "numero": self.last_paragraph_number + 1,
            "sottotitolo": f"{os.path.splitext(doc.get('filename','sconosciuto'))[0]} - ELABORAZIONE FALLITA",
            "categoria": "ALTRO",
            "contenuto": f"Il documento '{doc.get('filename','')}' non ha potuto essere elaborato in questo batch (errore parsing risposta AI)."
        })
        self.last_paragraph_number += 1
```

**Checklist**:
- [ ] Test JSON valido → comportamento identico
- [ ] Test JSON troncato → Livello 3 recupera oggetti
- [ ] Test apostrofi → `strict=False` li gestisce
- [ ] Test risposta invalida → placeholder generati, no crash
- [ ] Prod: nessun batch silenzioso, solo "BATCH LOSS" con nomi file

---

### SPRINT R-3 — Fix Conflitto Nome Azienda
**File**: `webapp/modules/report_generator.py`
**Tempo**: 20 minuti | **Rischio**: Zero

**Problema**: ZIP denominato "ALLEGATI" vince sul nome estratto dalla visura (35 casi).

**Fix**:
```python
NOMI_GENERICI_ZIP = frozenset({
    'allegati', 'documenti', 'files', 'doc', 'docs', 'archive',
    'archivio', 'cartella', 'folder', 'zip', 'upload', 'pratica',
    'materiale', 'materiali', 'tutto', 'vari', 'misc', 'allegato'
})

def _resolve_company_name(zip_name: str, visura_name: str) -> tuple:
    zip_clean = (zip_name or "").strip().lower()
    visura_clean = (visura_name or "").strip()
    if visura_clean and zip_clean in NOMI_GENERICI_ZIP:
        return visura_clean, "visura"
    if visura_clean and len(visura_clean) > len(zip_name or ""):
        return visura_clean, "visura"
    chosen = zip_name or visura_clean or "AZIENDA"
    return chosen, "zip" if zip_name else "visura"
```

**Checklist**:
- [ ] ZIP="ALLEGATI" + visura="SAGER S.R.L." → usa "SAGER S.R.L."
- [ ] ZIP="TECOSIM_2026" + visura="TE.COS.IM. S.R.L." → usa ZIP
- [ ] ZIP assente → usa visura
- [ ] Zero `WARNING: Conflitto Azienda` con ZIP generici

---

### SPRINT R-4 — Error Observability DB
**File**: `webapp/modules/db_manager.py`
**Tempo**: 4 ore | **Rischio**: Medio

**Problema**: `error_log` ha 1 riga su 1.049 pratiche. Admin completamente cieco agli errori parziali.

**Migrazioni colonne** (in `init_database()`):
```python
migration_cols = [
    ("batch_index", "INTEGER DEFAULT -1"),
    ("docs_involved", "TEXT"),
    ("error_subtype", "TEXT"),
    ("auto_recovered", "INTEGER DEFAULT 0"),
    ("recovery_details", "TEXT"),
]
for col_name, col_def in migration_cols:
    try:
        cursor.execute(f"ALTER TABLE error_log ADD COLUMN {col_name} {col_def}")
    except sqlite3.OperationalError:
        pass
```

**Nuova funzione `save_partial_error()`**:
```python
def save_partial_error(user_id, azienda, error_subtype, error_message,
                       batch_index=-1, docs_involved=None,
                       auto_recovered=False, recovery_details="", tab_source="tab1"):
    # error_subtype valori: "json_parse" | "ocr_none" | "name_conflict" | "mupdf_warn" | "batch_loss"
    # Sempre wrapped in try/except — il logging non deve mai bloccare la pipeline
```

**Nuova funzione `get_error_dashboard(days=30)`** per pannello admin.

**Checklist**:
- [ ] Migration idempotente (ALTER TABLE IF NOT EXISTS tramite try/except)
- [ ] `save_partial_error()` sempre in try/except nel chiamante
- [ ] `get_error_dashboard()` restituisce aggregati per subtype e trend giornaliero
- [ ] Dopo deploy: error_log cresce con ogni sessione, non rimane a 1 riga

---

### SPRINT R-5 — Hook nei Punti Critici
**File**: `webapp/modules/gemini_client.py`, `webapp/modules/gemini_ocr.py`
**Tempo**: 2 ore | **Dipendenza**: R-4 completato

Collegare i punti di errore a `save_partial_error()`. Pattern obbligatorio:
```python
try:
    from modules.db_manager import save_partial_error
    save_partial_error(user_id="system", azienda="", error_subtype="batch_loss", ...)
except Exception:
    pass  # Il logging secondario NON deve mai bloccare la pipeline
```

---

### QUICK WIN — MuPDF stderr silence
**File**: `webapp/modules/report_generator.py`
**Tempo**: 10 minuti

```python
import contextlib, io
with contextlib.redirect_stderr(io.StringIO()):
    result = extract_text_from_pdf(filepath)
```
Silenzia `MuPDF error: syntax error: invalid ICC colorspace` che è warning di rendering, non di estrazione.

---

## 3. PIANO B — PROMPT UNIVERSALE ADATTIVO v2.1

### Documento di riferimento
`c:\Users\user\AUDITORSEMI\PROMPT_UNIVERSALE_ADATTIVO_v2.md`

### Paradigma
Il PROMPT UNIVERSALE introduce un cambio da **Report Narrativo** (prosa 200-800 parole/doc) a **Evidence Card Strutturate** (YAML machine-readable, 3 fasi: Classifica→Estrai→Annota, norm-agnostic, 18 categorie ISO).

### Principio di integrazione: ADDITIVO, non sostitutivo
La modalità narrativa rimane invariata e default. Si aggiunge selettore UI in Tab 1.

---

### SPRINT B-0 — Preparazione (zero modifiche a esistenti)
Creare senza importare:
- `webapp/prompts/universal_evidence_prompt.md` — il PROMPT_UNIVERSALE_ADATTIVO adattato
- `webapp/modules/structured_evidence_parser.py` — parser YAML→dict Python
- `webapp/modules/structured_evidence_generator.py` — generatore .docx da card YAML

---

### SPRINT B-1 — Parser YAML
**File nuovo**: `webapp/modules/structured_evidence_parser.py`

**Funzioni pubbliche**:
- `parse_structured_response(raw_text: str) -> dict | None`
- `extract_company_name_from_meta(parsed: dict) -> str`

**Schema output**:
```python
{
    "meta": {"audit": {...}, "azienda": {...}, "indice": [...], "abbrev_aggiunte": [...]},
    "sezioni": [
        {
            "id": "08", "nome": "LEGALE/SOCIETARIA",
            "documenti": [
                {"tipo": "VIS", "categoria": "08 · LEGALE/SOCIETARIA",
                 "cluster": {"Identificativi": {"campo": "valore"}},
                 "firme": {...}, "note_audit": ""}
            ]
        }
    ]
}
```

**Checklist**:
- [ ] `parse_structured_response(fixture)` → dict non vuoto
- [ ] `parse_structured_response("")` → None (no exception)
- [ ] `extract_company_name_from_meta({})` → "AZIENDA NON IDENTIFICATA"
- [ ] Import senza PyYAML → no crash (graceful degradation)

---

### SPRINT B-2 — Generatore .docx Strutturato
**File nuovo**: `webapp/modules/structured_evidence_generator.py`

**Funzione principale**: `generate_structured_evidence_docx(parsed_data, output_path, docs_estratti, docs_vuoti) -> str`

**Struttura .docx**:
1. Intestazione identica al report narrativo (compatibilità Tab 2)
2. Blocco META come tabella
3. Per ogni sezione: Heading 1 + per ogni doc: Heading 2 + tabella cluster YAML
4. Box giallo per `note_audit` non vuoto

---

### SPRINT B-3 — GeminiClient: metodo aggiuntivo
**File**: `webapp/modules/gemini_client.py`

**Aggiungere** (NON toccare `analyze_batch()`):
- `analyze_batch_structured(batch_docs, batch_idx, total_docs, universal_prompt) -> str | None`
- `_load_universal_prompt(path: str) -> str`

**BATCH SIZE per modalità strutturata**: max 4 doc/batch (vs 8 narrativo) — output YAML verboso.

---

### SPRINT B-4 — report_generator.py: wiring _pipeline_strutturata() (REPLACEMENT)
**File**: `webapp/modules/report_generator.py`

> ⚠️ DECISIONE 2026-04-18: il metodo strutturato SOSTITUISCE il narrativo come default.
> Nessun `output_mode`, nessun radio button, app.py INVARIATO.
> Il vecchio codice (analyze_batch loop + generate_report_word) resta nel file come dead code.

Firma invariata (nessuna modifica alla firma):
```python
def process_zip_and_generate_report(
    input_source,
    api_key: str,
    progress_callback=None,
    status_callback=None,
    input_type: str = "zip"   # INVARIATO — NON TOCCARE
)
```

Wiring (sostituisce il corpo della pipeline, dopo STEP 2):
```python
# Chiama direttamente la pipeline strutturata
return _pipeline_strutturata(
    documents, failed_files, api_key, input_name,
    total_files, progress_callback, status_callback, logger
)
# Il vecchio codice sotto (analyze_batch loop + generate_report_word) diventa dead code.
# NON cancellare: è il fallback di sicurezza.
```

`_pipeline_strutturata()` ritorna `(word_bytes, stats_dict, filename)` — STESSO contratto.
`stats_dict` deve contenere: `company_name`, `failed_files`, `total_docs`,
`paragraphs_generated`, `avg_words`, `unique_verbs`, `privacy_violations`, `log_summary`.

---

### ~~SPRINT B-4b~~ — ELIMINATO
> Nessun radio button. Nessuna modifica a `app.py`. Decisione 2026-04-18.

---

### SPRINT B-5 — Deploy e test
Stessa procedura di deploy standard (pscp + riavvio servizio). `app.py` NON viene uploadato.

**Verifica**:
- [ ] Tab 1 con ZIP reale → .docx strutturato con schede YAML generato correttamente
- [ ] Tab 2 dopo output strutturato → JSON clausole generato, nome azienda estratto OK
- [ ] Tab 3 → non coinvolta, funziona invariata
- [ ] app.py call site invariato (word_bytes, stats, filename = ... funziona)

---

## 4. ORDINE DI ESECUZIONE GLOBALE

```
SETTIMANA 1 — Fix immediati (zero rischi):
  R-1  OCR NoneType              30 min
  R-3  Conflitto nome azienda    20 min
  MuPDF silence                  10 min
  → Deploy + restart

SETTIMANA 2 — Parser e DB:
  R-4  Error observability DB    4h
  R-2  JSON parser resiliente    2h
  → Deploy + restart

SETTIMANA 3 — Hook e osservabilità:
  R-5  Hook punti critici        2h
  → Deploy + verifica dashboard admin

SETTIMANA 3 — Preparazione Piano B (zero deploy):
  B-0  Preparazione file nuovi (nessun import, zero effetti live)
  B-1  Parser YAML structured_evidence_parser.py
  B-2  Generatore .docx structured_evidence_generator.py
  B-3  GeminiClient: analyze_batch_structured() + _load_universal_prompt()

SETTIMANA 4 — Integrazione e deploy:
  R-5  Hook save_partial_error() → DOPO B-3 (deve coprire analyze_batch_structured)
  B-4  report_generator.py: _pipeline_strutturata() come pipeline unica (app.py INVARIATO)
  B-5  Deploy tutto in blocco + test completo

POST-TUTTO:
  Aggiornare directives/evidence_extraction_SOP.md
  Sezione 7: NUOVO PARADIGMA — metodo strutturato come pipeline unica Tab 1
  Il metodo narrativo rimane nel codice come fallback, non attivo
```

---

## 5. STATISTICHE ERRORI DI RIFERIMENTO

*Baseline al 2026-04-18 — usare per misurare miglioramento post-fix*

| Metrica | Valore baseline |
|---------|----------------|
| Pratiche totali | 1.049 |
| Report Tab 1 | 371 |
| `Errore parsing JSON` (gen-apr) | 252 |
| `OCR NoneType` (gen-apr) | 59 |
| `Conflitto Azienda` (gen-apr) | 35 |
| Righe in `error_log` DB | 1 |
| MuPDF warnings (solo aprile) | ~620 |
| Security probes `.git/config` | 19 |

---

## 6. INVARIANTI DI SISTEMA (MAI TOCCARE)

Componenti che non devono MAI essere modificati senza analisi approfondita:

| Componente | Motivo |
|-----------|--------|
| `analyze_batch()` firma e tipo ritorno | Tab 1 pipeline narrativa dipende da esso |
| `generate_word_report()` | Generatore Word narrativo live |
| `MACROAREA_ORDER` (10 categorie) | Documenti esistenti già categorizzati |
| `data/audit.db` schema esistente | 1.049 pratiche salvate |
| `save_error_log()` funzione esistente | Chiamata da `app.py` per crash catastrofici |
| `prefetch_all_prompts()` in app.py | Cache in-memory, richiede riavvio se cambia |
| Contratto di ritorno `(docx_bytes, stats, filename)` | Tab 2 legge `session_state` popolato da Tab 1 |

---

## NOTE OPERATIVE

- **Deploy**: sempre con `pscp` (non `plink + cat` — corrompe UTF-8)
- **Restart**: obbligatorio dopo ogni modifica a `.py` o `.md` in webapp/
- **Test prima del deploy**: verificare con fixture locali in `_server_sync/`
- **Cache prompt**: `api_prompt.md` e `universal_evidence_prompt.md` letti UNA VOLTA all'avvio
- **Canonical locale**: `c:\Users\user\AUDITORSEMI\webapp\` — sincronizzare con `_server_sync\` dopo ogni modifica server-side
