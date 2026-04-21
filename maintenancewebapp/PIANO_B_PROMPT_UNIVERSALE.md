# PIANO B — PROMPT UNIVERSALE ADATTIVO v2.1: DOCUMENTO ESECUTIVO
## Analisi Comparativa, Errori Corretti, Ordine di Implementazione

> **Generato**: 2026-04-18  
> **Base**: Enterprise Refactoring Blueprint (sessione 2026-04-18) confrontato riga per riga col codice live  
> **Fonte primaria codice**: `webapp/modules/gemini_client.py`, `report_generator.py`, `app.py`, `gemini_ocr.py`, `checklist_producer.py`

---

## PARTE I — ERRORI CRITICI TROVATI NEL BLUEPRINT (E NEL ROADMAP.md)

Dopo lettura integrale del codice, ho trovato **3 errori critici** che avrebbero causato runtime failure garantita.

---

### ERRORE CRITICO 1 — Contratto di ritorno sbagliato (porterebbe a crash in `app.py`)

**Dove si trova**: Enterprise Blueprint, Sprint 4a / ROADMAP Sprint B-4a  
**Descrizione nel piano**: `_pipeline_strutturata()` "Ritorna `(docx_bytes, filename, nome_azienda)`"

**Contratto REALE** (da `app.py` riga 791-797):
```python
word_bytes, stats, filename = process_zip_and_generate_report(
    input_data,
    api_key,
    progress_callback=update_progress,
    status_callback=update_status,
    input_type=input_type_param
)
```

Il return è `(bytes, stats_dict, filename)` — **NON** `(bytes, filename, string)`.

`app.py` usa poi:
```python
company_name_from_tab1 = stats.get("company_name", "")
failed_files = stats.get("failed_files", [])
stats.get("paragraphs_generated", ...)
stats.get("total_paragraphs", 0)
stats.get("avg_words", 0)
stats.get("unique_verbs", 0)
stats.get("log_summary", {})
```

**CORREZIONE OBBLIGATORIA**: `_pipeline_strutturata()` deve ritornare:
```python
return word_bytes, stats, filename
# dove stats è un dict che contiene ALMENO:
{
    "company_name": str,
    "failed_files": list,
    "total_docs": int,
    "total_paragraphs": int,
    "paragraphs_generated": int,
    "avg_words": float,
    "unique_verbs": int,
    "privacy_violations": int,
    "log_summary": {}
}
```

---

### ERRORE CRITICO 2 — Parametro `norm="GENERICA"` fantasma

**Dove si trova**: Enterprise Blueprint Sprint 4a, ROADMAP Sprint B-4a  
**Firma proposta**: `process_zip_and_generate_report(zip_file, api_key, norm="GENERICA", ...)`

**Firma REALE** (da `report_generator.py` riga 512-518):
```python
def process_zip_and_generate_report(
    input_source,           # ← nome diverso da "zip_file"
    api_key: str,
    progress_callback=None,
    status_callback=None,
    input_type: str = "zip"  # ← parametro ESISTENTE, non nel piano
) -> Tuple[bytes, Dict, str]:
```

Il parametro `norm` non esiste e non viene mai passato da `app.py`.  
Il parametro `input_type` esiste e supporta: `"zip"`, `"folder"`, `"uploaded_files"`.  
Aggiungere `norm` è dead code. Non aggiungere `norm`.

**CORREZIONE OBBLIGATORIA**: La firma corretta con l'aggiunta di `output_mode`:
```python
def process_zip_and_generate_report(
    input_source,                     # ← INVARIATO
    api_key: str,
    progress_callback=None,
    status_callback=None,
    input_type: str = "zip",          # ← INVARIATO - NON RIMUOVERE
    output_mode: str = "narrativo"    # ← NUOVO: "narrativo" | "strutturato"
) -> Tuple[bytes, Dict, str]:
```

---

### ERRORE CRITICO 3 — `extract_company_name()` incompatibile con modalità strutturata

**Dove si trova**: Implicito nel piano, non segnalato come problema  
**Il piano dice**: "Ritorna `nome_azienda`" da `_pipeline_strutturata()` ma non specifica come ottenerlo.

**Il problema**: `extract_company_name()` in `report_generator.py` (riga 1187) cerca:
1. Il file "visura" nei documenti grezzi → regex sui testi
2. Il campo `ente_auditato` nei paragrafi → **questo campo è specifico del formato narrativo JSON**
3. Regex sui testi dei documenti

In modalità strutturata, i paragrafi narrativi non esistono. Il nome azienda è nel blocco META YAML:
```yaml
azienda:
  nome: "[RAGIONE SOCIALE]"
```

**CORREZIONE OBBLIGATORIA**: `_pipeline_strutturata()` deve:
```python
# Usa extract_company_name_from_meta() su parsed_data, NON extract_company_name()
company_name = extract_company_name_from_meta(parsed_data) or "AZIENDA NON IDENTIFICATA"
# Come fallback: usa la stessa extract_company_name() sui documenti grezzi
if company_name == "AZIENDA NON IDENTIFICATA":
    company_name = extract_company_name(documents, logger, zip_filename=input_name)
```

---

## PARTE II — ANALISI OCR NoneType (R-1) — Posizione Esatta nel Codice

**`gemini_ocr.py` riga 202** (metodo `extract_text_from_image()`, fallback sequenziale):
```python
# PRIMA (vulnerabile):
return response.text.strip()

# DOPO (fix):
raw = getattr(response, 'text', None) or ""
return raw.strip()
```

**NOTE IMPORTANTI sul file `gemini_ocr.py`**:
- Il metodo `extract_text_from_pdf_batch()` è GIÀ PROTETTO (righe 254, 286):
  ```python
  text = response.text.strip() if response.text else ""
  ```
- Solo `extract_text_from_image()` (riga 202) è ancora vulnerabile.
- `extract_text_from_image()` è chiamato da `_extract_sequential()` che è il fallback finale.

**`gemini_client.py` riga 145** (metodo `_call_api()`, branch `USE_NEW_SDK=True`):
```python
# PRIMA (parzialmente protetto ma ancora vulnerabile):
if hasattr(response, 'text'):
    result = response.text.strip()   # response.text può essere None!

# DOPO (fix completo):
if hasattr(response, 'text'):
    result = (response.text or "").strip()
```

---

## PARTE III — ARCHITETTURA CORRETTA DEL PIANO B

### Mappa completa flusso Tab 1 → Tab 2 (REPLACEMENT — decisione 2026-04-18)

> **NOTA ARCHITETTURALE**: il nuovo metodo strutturato SOSTITUISCE la pipeline narrativa
> come comportamento default di Tab 1. Il vecchio codice (`analyze_batch`, `generate_report_word`,
> `api_prompt.md`) rimane nel file senza modifiche come fallback di sicurezza — non viene
> cancellato, ma non viene più chiamato dalla pipeline principale. Nessun radio button,
> nessun parametro `output_mode`.

```
[app.py] → process_zip_and_generate_report(input_source, api_key,
                                           input_type=...)
           ← INVARIATO: stessa firma, stesso call site (riga 791), stesso unpack

[report_generator.py]
  process_zip_and_generate_report() → _pipeline_strutturata(documents, failed_files, api_key, ...)
      → GeminiClient.analyze_batch_structured(batch, universal_prompt)  [batch 4 doc max]
      → accumulazione raw YAML strings
      → structured_evidence_parser.parse_structured_response(accumulated_yaml)
      → structured_evidence_parser.extract_company_name_from_meta(parsed)
        [fallback: extract_company_name(documents, logger, zip_filename=input_name)]
      → structured_evidence_generator.generate_structured_evidence_docx(parsed, ...)
      → return (docx_bytes, stats_dict, filename)

  [DEAD CODE — invariato, non chiamato]:
      analyze_batch() / generate_report_word() / api_prompt.md loader

[app.py]
  word_bytes, stats, filename = ...  # Unpack identico — nessuna modifica
  stats["company_name"] → session_state['nome_azienda_tab1']
  word_bytes → session_state['report_for_tab2']  # Passato a Tab 2

[Tab 2 - checklist_producer.py]
  Legge session_state['report_for_tab2'] (docx bytes)
  Estrae testo del docx → lo passa ai prompt checklist con il testo completo
  ✅ OUTPUT JSON IMMUTABILE: tutti e 10 i prompt checklist producono SEMPRE
     { "norma": "...", "azienda": "...", "data_elaborazione": "...", "clausole": {...} }
     indipendentemente dal formato input (narrativo o strutturato).
  ✅ COMPATIBILE: i prompt checklist sono stati aggiornati (2026-04-18) con la riga:
     "Il documento può essere narrativo o strutturato (YAML cat. 01–18)"
     → Gemini sa gestire entrambi i formati. Nessun cambio di checklist_producer.py.
```

---

### Specifica corretta di `_pipeline_strutturata()`

```python
def _pipeline_strutturata(
    documents: List[Dict],
    failed_files: List[Dict],
    api_key: str,
    input_name: str,
    total_files: int,
    progress_callback=None,
    status_callback=None,
    logger=None
) -> Tuple[bytes, Dict, str]:
    """Pipeline per modalità strutturata (PROMPT UNIVERSALE ADATTIVO)."""
    import time
    from modules.structured_evidence_parser import (
        parse_structured_response,
        extract_company_name_from_meta
    )
    from modules.structured_evidence_generator import generate_structured_evidence_docx
    from io import BytesIO
    import tempfile
    
    # Carica universal prompt
    client = GeminiClient(api_key)
    universal_prompt = client._load_universal_prompt(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                     'prompts', 'universal_evidence_prompt.md')
    )
    
    # BATCH SIZE ridotto: max 4 doc (YAML output è verboso)
    STRUCTURED_BATCH_SIZE = 4
    batches = [
        documents[i:i+STRUCTURED_BATCH_SIZE]
        for i in range(0, len(documents), STRUCTURED_BATCH_SIZE)
    ]
    num_batches = len(batches)
    
    raw_outputs = []
    for i, batch in enumerate(batches):
        if status_callback:
            status_callback(f"🤖 Analisi strutturata batch {i+1}/{num_batches}...")
        if progress_callback:
            progress_callback(0.30 + (i/num_batches)*0.55, f"Batch strutturato {i+1}/{num_batches}...")
        
        raw = client.analyze_batch_structured(batch, i, len(documents), universal_prompt)
        if raw:
            raw_outputs.append(raw)
    
    # Parse YAML accumulato
    full_yaml = "\n\n---\n\n".join(raw_outputs)
    parsed_data = parse_structured_response(full_yaml)
    
    if not parsed_data:
        raise ValueError("Il PROMPT UNIVERSALE non ha prodotto output parsabile. "
                        "Verifica universal_evidence_prompt.md e riprova.")
    
    # Estrai nome azienda
    company_name = extract_company_name_from_meta(parsed_data)
    if company_name == "AZIENDA NON IDENTIFICATA":
        company_name = extract_company_name(documents, logger, zip_filename=input_name)
    
    # Conta documenti per stats
    docs_estratti = len(documents)
    docs_vuoti = total_files - docs_estratti
    
    # Genera docx
    if status_callback:
        status_callback("📄 Generazione documento strutturato Word...")
    if progress_callback:
        progress_callback(0.95, "Generazione Word strutturato...")
    
    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
        tmp_path = tmp.name
    
    generate_structured_evidence_docx(
        parsed_data, tmp_path, docs_estratti, docs_vuoti
    )
    
    with open(tmp_path, 'rb') as f:
        word_bytes = f.read()
    os.unlink(tmp_path)
    
    # Costruisci stats dict compatibile con app.py
    stats = {
        "company_name": company_name,
        "failed_files": failed_files,
        "total_docs": total_files,
        "docs_with_text": docs_estratti,
        "total_paragraphs": docs_estratti,
        "paragraphs_generated": docs_estratti,
        "avg_words": 0,       # N/A per modalità strutturata
        "unique_verbs": 0,    # N/A
        "privacy_violations": 0,
        "log_summary": logger.get_summary() if logger else {},
        "output_mode": "strutturato"
    }
    
    # Filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_company = "".join(c for c in company_name if c.isalnum() or c == " ")[:30]
    safe_company = safe_company.replace(" ", "_") if safe_company else "AUDIT"
    filename = f"Evidenze_Strutturate_{safe_company}_{timestamp}.docx"
    
    if progress_callback:
        progress_callback(1.0, "Completato!")
    if status_callback:
        status_callback("✅ Evidenze strutturate generate con successo!")
    
    return word_bytes, stats, filename
```

---

## PARTE IV — ORDINE DI ESECUZIONE CORRETTO (DEFINITIVO)

### Principio ordinatore

```
R-2 → B-3 (dipendenza positiva: _parse_json_response è riusabile in structured)
R-5 → DOPO B-3 (i hook devono coprire anche analyze_batch_structured)
Piano A completo → Piano B (sistemi stabili prima di nuove feature)
Piano B completo → Migrazione React (non si spreca nulla: tutto sopravvive alla migrazione)
```

### Ordine di settimana in settimana

```
════ SETTIMANA 1: FIX ZERO RISCHIO ════════════════════════════════════════════
R-1   Fix OCR NoneType                              30 min
      • gemini_ocr.py riga 202: response.text.strip() → (response.text or "").strip()
      • gemini_client.py riga 145: stessa fix

R-3   Fix Conflitto Nome Azienda                    20 min
      • report_generator.py: aggiungi NOMI_GENERICI_ZIP e _resolve_company_name()

QUICK MuPDF stderr silence                          10 min
      • report_generator.py: contextlib.redirect_stderr() su extract_text_from_pdf()

→ Deploy + restart obbligatorio
→ Verifica 48h log: zero "NoneType" e zero "Conflitto Azienda" con ZIP generici

════ SETTIMANA 2: RELIABILITY CORE ════════════════════════════════════════════
R-4   Error Observability DB                        4h
      • db_manager.py: migration colonne + save_partial_error() + get_error_dashboard()

R-2   JSON Parser Resiliente                        2h
      • gemini_client.py: nuovo metodo _parse_json_response() + placeholder batch loss

→ Deploy + restart obbligatorio
→ Verifica: error_log in DB inizia a popolarsi dopo ogni sessione

════ SETTIMANA 3: PREPARAZIONE PIANO B ════════════════════════════════════════
B-0   Creazione file nuovi (zero imports, zero effetti)   1h
      • webapp/prompts/universal_evidence_prompt.md
      • webapp/modules/structured_evidence_parser.py  (stub iniziale)
      • webapp/modules/structured_evidence_generator.py (stub iniziale)

B-1   Parser YAML → Python dict                     3h
      • Implementa parse_structured_response() e extract_company_name_from_meta()
      • Test locale con fixture YAML manuale prima di integrare

B-2   Generatore .docx Strutturato                  4h
      • Implementa generate_structured_evidence_docx()
      • Test locale: genera docx apribile e con heading compatibili Tab 2

B-3   GeminiClient: analyze_batch_structured()      2h
      • Aggiunge metodo senza toccare analyze_batch()
      • Aggiunge _load_universal_prompt()
      • USA _parse_json_response() interno se presente (bonus resilienza)

→ NESSUN DEPLOY ancora — i nuovi file non sono importati da nessuno

════ SETTIMANA 4: INTEGRAZIONE E DEPLOY ═══════════════════════════════════════
R-5   Hook save_partial_error() nei moduli critici  2h
      • gemini_client.py: hook in analyze_batch_structured()
        [hook in analyze_batch() opzionale — dead code ma non fa male tenerlo]
      • gemini_ocr.py: hook post-OCR fallback
      • DIPENDE DA R-4 completato

B-4    report_generator.py: wiring _pipeline_strutturata()   2h (semplificato)
      • NON aggiungere output_mode (non serve — nessun radio button)
      • Preserva input_type esistente INVARIATO
      • process_zip_and_generate_report() chiama direttamente _pipeline_strutturata()
      • Il vecchio codice (analyze_batch loop + generate_report_word) rimane nel file
        come dead code — NON cancellare, NON commentare
      • app.py: ZERO MODIFICHE — stessa firma, stesso call site

~~B-4b~~ ELIMINATO — nessun radio button, nessuna modifica a app.py

→ Deploy tutto in blocco + restart
→ Test con ZIP reale: Tab 1 → docx strutturato con schede YAML generato
→ Test Tab 2 dopo strutturato: JSON clausole generato, nome azienda estratto OK

════ POST-SETTIMANA 4: AGGIORNAMENTO DIRETTIVE ════════════════════════════════
Aggiorna evidence_extraction_SOP.md:
  Aggiungi Sezione 7: NUOVO PARADIGMA — PROMPT UNIVERSALE ADATTIVO v2.1
  Dichiara il metodo strutturato come pipeline principale di Tab 1
  Documenta che il metodo narrativo rimane nel codice come fallback ma non è attivo
  Documenta che regola 1:1:1 è sostituita da regola 2.7 per serie omogenee

════ POST-TUTTO: MIGRAZIONE REACT ══════════════════════════════════════════════
Inizia solo quando Piano A + Piano B sono stabili in produzione per almeno 2 settimane.
FastAPI + React (Base44). Tutti i moduli sopravvivono. Solo app.py viene riscritto.
```

---

## PARTE V — CHECKLIST PER OGNI SPRINT (VERSIONE DEFINITIVA)

### CHECKLIST PRELIMINARE — Prima di iniziare qualsiasi sprint

```
AMBIENTE:
[ ] Verificare stato servizio: plink "systemctl status auditos"
[ ] Leggere ultimi 50 righe log: plink "journalctl -u auditos -n 50"
[ ] Backup file da modificare: plink "cp modulo.py modulo.py.bak"
[ ] Zero elaborazioni in corso degli utenti prima del deploy
```

---

### CHECKLIST R-1 — Fix OCR NoneType

**File**: `webapp/modules/gemini_ocr.py` + `webapp/modules/gemini_client.py`

**Prima di modificare — verifica posizioni esatte**:
```
[ ] grep "response.text.strip()" gemini_ocr.py → DEVE trovare riga ~202
    (altre occorrenze a righe 254, 286 sono già protette con 'if response.text')
[ ] grep "response.text.strip()" gemini_client.py → DEVE trovare riga ~145-148
```

**Modifiche**:
```python
# gemini_ocr.py riga 202 — in extract_text_from_image():
# PRIMA: return response.text.strip()
# DOPO:  return (getattr(response, 'text', None) or "").strip()

# gemini_client.py riga 145 — in _call_api(), branch USE_NEW_SDK:
# PRIMA: result = response.text.strip()
# DOPO:  result = (response.text or "").strip()
```

**Checklist post-deploy**:
```
[ ] grep confermato: nessun .text.strip() non protetto rimasto
[ ] Deploy + restart
[ ] Test con file PDF vuoto/corrotto → nessun crash, ritorna ""
[ ] 48h log produzione: zero righe "NoneType: 'NoneType' object has no attribute 'strip'"
```

---

### CHECKLIST R-3 — Fix Conflitto Nome Azienda

**File**: `webapp/modules/report_generator.py`

**Prima di modificare — verifica**:
```
[ ] grep "NOMI_GENERICI_ZIP" report_generator.py → NON deve trovare nulla (non esiste ancora)
[ ] grep "zip_candidate" report_generator.py → riga ~1226-1229 contiene la logica esistente
[ ] Comprendi il flusso attuale in extract_company_name() righe 1187-1360
```

**Modifiche** (aggiungere subito dopo gli import, prima di MACROAREA_ORDER):
```python
NOMI_GENERICI_ZIP = frozenset({
    'allegati', 'documenti', 'files', 'doc', 'docs', 'archive',
    'archivio', 'cartella', 'folder', 'zip', 'upload', 'pratica',
    'materiale', 'materiali', 'tutto', 'vari', 'misc', 'allegato',
    'folder upload', 'cartella selezionata'
})
```

Modificare in `extract_company_name()` la sezione PRIORITÀ 0:
```python
# Dopo aver calcolato clean (riga ~1224):
if len(clean) > 3 and "UPLOAD" not in clean.upper() and "CARTELLA" not in clean.upper():
    if clean.lower() not in NOMI_GENERICI_ZIP:  # ← AGGIUNTA
        zip_candidate = clean.upper()
```

**Checklist post-deploy**:
```
[ ] Test: ZIP="ALLEGATI" + visura="SAGER S.R.L." → usa "SAGER S.R.L."
[ ] Test: ZIP="TECOSIM_2026" + visura="TE.COS.IM. S.R.L." → usa ZIP (specifica)
[ ] Test: ZIP="DOCUMENTI" → nessun zip_candidate (non usato)
[ ] 48h log: zero "WARNING: Conflitto Azienda" con ZIP da lista NOMI_GENERICI_ZIP
```

---

### CHECKLIST R-2 — JSON Parser Resiliente

**File**: `webapp/modules/gemini_client.py`

**Prima di modificare**:
```
[ ] Leggi analyze_batch() righe 263-399 per capire il punto di intercettazione
[ ] Il parse JSON attuale è a riga ~312-326 (try: json.loads, except: return [])
[ ] Verifica che _parse_json_response() non esista ancora (non dev'esserci)
```

**Metodo da aggiungere** (nella classe GeminiClient, dopo `_sanitize_text()`):
```python
def _parse_json_response(self, response_text: str, batch_index: int) -> list:
    """Parser a 3 livelli: standard → strict=False → regex per oggetto."""
    import re
    text = (response_text or "").strip()
    
    # Rimuovi code fence se presente
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    text = text.strip()
    
    # Estrai blocco array
    if '[' not in text:
        print(f"[JSON PARSER] Batch {batch_index}: nessun array trovato")
        return []
    text = text[text.index('['):text.rindex(']') + 1]
    
    # Livello 1: parse standard
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Livello 2: tolera newline non escapati (apostrofi italiani)
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
                    if isinstance(obj, dict) and ('contenuto' in obj or 'content' in obj):
                        objects.append(obj)
                except json.JSONDecodeError:
                    pass
                start_pos = None
    
    if objects:
        print(f"[JSON PARSER] Batch {batch_index}: recuperati {len(objects)} oggetti via brace-matching")
        return objects
    
    print(f"[JSON PARSER] Batch {batch_index}: FALLIMENTO TOTALE. Preview: {response_text[:200]}")
    return []
```

**In `analyze_batch()`, sostituire** il blocco parse esistente (righe ~311-349) con:
```python
# Parse JSON array — usa parser resiliente a 3 livelli
paragraphs_raw = self._parse_json_response(response_text, batch_index)

if not paragraphs_raw:
    # Genera placeholder per ogni documento perso
    for doc in documents:
        fname = doc.get("filename", "sconosciuto")
        all_paragraphs_placeholder = {
            "numero": self.last_paragraph_number + 1,
            "sottotitolo": f"{os.path.splitext(fname)[0]} - ELABORAZIONE FALLITA",
            "categoria": "ALTRO",
            "contenuto": f"Il documento '{fname}' non ha potuto essere elaborato "
                         f"in questo batch (errore parsing risposta AI)."
        }
        # NOTA: qui non aggiungiamo ai paragrafi finali, 
        # lo facciamo nel chiamante se si decide di includere i placeholder
        print(f"[BATCH LOSS] {fname} nel batch {batch_index}")
    return []

paragraphs = paragraphs_raw
```

**Checklist post-deploy**:
```
[ ] Test con JSON valido → comportamento identico al precedente
[ ] Test con JSON con apostrofo: {"contenuto": "dell'azienda"} → Livello 2 gestisce
[ ] Test con risposta parzialmente troncata → Livello 3 recupera gli oggetti completi
[ ] Test con risposta completamente invalida → return [], log "FALLIMENTO TOTALE"
[ ] Verifica: nessun batch silenzioso — ogni failure ha log identificabile
```

---

### CHECKLIST R-4 — Error Observability DB

**File**: `webapp/modules/db_manager.py`

**Prima di modificare**:
```
[ ] Verifica schema attuale error_log:
    plink "sqlite3 /opt/auditos/webapp/data/audit.db '.schema error_log'"
[ ] Conferma che save_error_log() esiste e non viene toccata
[ ] Backup: plink "cp data/audit.db data/audit.db.bak"
```

**Migrazione colonne** (in `init_database()`, metodo idempotente):
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
        pass  # Colonna già esistente
```

**Checklist post-deploy**:
```
[ ] Migration è idempotente: eseguire init_database() due volte → nessun errore
[ ] Schema aggiornato: plink "sqlite3 data/audit.db '.schema error_log'"
[ ] save_partial_error() non crasha mai (tutto in try/except esterno)
[ ] Test: eseguire una pratica → error_log si popola con record parziali
[ ] get_error_dashboard() ritorna dict con aggregati
```

---

### CHECKLIST B-0 — Preparazione File Nuovi

**Verifica**:
```
[ ] I 3 file non esistono ancora:
    ls webapp/prompts/universal_evidence_prompt.md → NOT FOUND
    ls webapp/modules/structured_evidence_parser.py → NOT FOUND
    ls webapp/modules/structured_evidence_generator.py → NOT FOUND
[ ] PyYAML installato nel venv:
    plink "/opt/auditos/webapp/venv/bin/pip show pyyaml"
    SE NON INSTALLATO: plink "/opt/auditos/webapp/venv/bin/pip install pyyaml"
```

**File da creare**:
1. `webapp/prompts/universal_evidence_prompt.md` — copia adattata di `PROMPT_UNIVERSALE_ADATTIVO_v2.md`
2. `webapp/modules/structured_evidence_parser.py` — stub con import guard
3. `webapp/modules/structured_evidence_generator.py` — stub con import guard

**Checklist**:
```
[ ] Nessun file esistente modificato
[ ] Test import manuale: python -c "from modules.structured_evidence_parser import parse_structured_response"
[ ] Zero effetti sul sistema live (non ancora importati da nessuno)
[ ] PyYAML verificato installato
```

---

### CHECKLIST B-1 — Parser YAML

**File**: `webapp/modules/structured_evidence_parser.py`

**Vincoli inderogabili**:
- Zero import da altri moduli del progetto (stdlib + yaml/json solo)
- Zero side effects (no scrittura disco)
- Graceful degradation se PyYAML non installato (`HAS_YAML = False`)

**Schema output atteso**:
```python
{
    "meta": {
        "audit": {"data_estrazione": "...", "norma_principale": "...", ...},
        "azienda": {"nome": "...", "cf": "...", ...},
        "indice": [...],
        "abbrev_aggiunte": [...]
    },
    "sezioni": [
        {
            "id": "08",
            "nome": "LEGALE/SOCIETARIA",
            "documenti": [
                {
                    "tipo": "VIS",
                    "categoria": "08 · LEGALE/SOCIETARIA",
                    "titolo": "...",
                    "cluster": {"Identificativi": {"campo": "valore"}},
                    "note_audit": ""
                }
            ]
        }
    ]
}
```

**Checklist**:
```
[ ] parse_structured_response(fixture_yaml) → dict non vuoto con chiavi "meta" e "sezioni"
[ ] parse_structured_response("") → None (NO exception)
[ ] parse_structured_response("testo completamente invalido") → None
[ ] extract_company_name_from_meta({"meta": {"azienda": {"nome": "TEST SRL"}}}) → "TEST SRL"
[ ] extract_company_name_from_meta({}) → "AZIENDA NON IDENTIFICATA"
[ ] Import senza PyYAML installato → nessun crash (HAS_YAML = False, ritorna None)
```

---

### CHECKLIST B-2 — Generatore .docx Strutturato

**File**: `webapp/modules/structured_evidence_generator.py`

**Vincoli inderogabili**:
- Non modificare `generate_report_word()` esistente
- Il .docx prodotto deve essere apribile da Tab 2 senza modifiche
- La PRIMA riga significativa del docx deve contenere il nome azienda (compatibilità Tab 2)
- Se `parsed_data` è None o malformato → `ValueError` con messaggio chiaro

**Struttura obbligatoria del .docx**:
1. Titolo: "RELAZIONE DI EVIDENZE STRUTTURATE - AUDIT-OS"
2. Subtitolo: "Audit - {company_name}" (OBBLIGATORIO per compatibilità Tab 2)
3. Intestazione: Data | Estratti | Vuoti | Analizzati
4. Heading 1 "META — AUDIT E AZIENDA" + tabella campi
5. Per ogni sezione: Heading 1 "XX · NOME" → per ogni doc: Heading 2 + tabelle cluster
6. Se `note_audit` non vuoto: paragrafo con sfondo giallo (WD_COLOR_INDEX.YELLOW)

**Checklist**:
```
[ ] generate_structured_evidence_docx(fixture, "/tmp/test.docx", 10, 2) → file creato
[ ] File apre in Word/LibreOffice senza errori
[ ] Heading 1 per ogni sezione presente
[ ] Tabelle formattate (header grigio, dati bianchi)
[ ] Con parsed_data=None → ValueError sollevato con messaggio leggibile
[ ] Seconda riga del documento: "Audit - NOME AZIENDA" (Tab 2 compatibilità)
[ ] generate_report_word() narrativo: INTOCCATO e funzionante
```

---

### CHECKLIST B-3 — GeminiClient: analyze_batch_structured()

**File**: `webapp/modules/gemini_client.py`

**Vincoli inderogabili**:
- `analyze_batch()` INTOCCABILE — nessuna modifica
- `_call_api()` INTOCCABILE — nessuna modifica
- Nessuna modifica agli import di testa del file
- Il metodo deve funzionare con entrambi USE_NEW_SDK=True e False

**Firma corretta**:
```python
def analyze_batch_structured(
    self,
    batch_docs: List[Dict],
    batch_idx: int,
    total_docs: int,
    universal_prompt: str
) -> Optional[str]:
    """Versione strutturata. Ritorna testo grezzo YAML, None se fallisce."""

def _load_universal_prompt(self, path: str) -> str:
    """Legge universal_evidence_prompt.md. Fallback: stringa vuota."""
```

**Costruzione prompt per `analyze_batch_structured()`**:
```python
docs_text = "\n\n".join(
    f"### DOCUMENTO {i+1}: {d['filename']}\n{self._sanitize_text(d.get('content', '')[:8000])}"
    for i, d in enumerate(batch_docs)
)
prompt = (
    f"{universal_prompt}\n\n---\n\n"
    f"## DOCUMENTI DA ELABORARE ({len(batch_docs)} file — Batch {batch_idx+1}/{total_docs})\n\n"
    f"{docs_text}\n\n---\n\n"
    f"Elabora i {len(batch_docs)} documenti sopra seguendo le 3 FASI. "
    f"Produci output YAML completo con BLOCCO META e tutte le schede."
)
```

**Checklist**:
```
[ ] Import del file invariato (nessun nuovo import globale)
[ ] analyze_batch() ancora funzionante (test di non regressione con ZIP reale)
[ ] analyze_batch_structured() esiste con firma corretta
[ ] _load_universal_prompt() ritorna stringa (anche vuota) mai None
[ ] Con API key reale: analyze_batch_structured() ritorna stringa non vuota
[ ] Con API key invalida: ritorna None senza crash, log errore stampato
[ ] Test USE_NEW_SDK=False: il metodo usa self._call_api() che gestisce il branch interno
```

---

### CHECKLIST B-4a — report_generator.py: parametro output_mode

**File**: `webapp/modules/report_generator.py`

**Vincoli ASSOLUTI** (violazione = regressione in produzione):
- `MACROAREA_ORDER`: NON TOCCARE
- `generate_report_word()`: NON TOCCARE
- `extract_company_name()`: NON TOCCARE
- `input_type` parametro: PRESERVARE
- `norm` parametro: NON AGGIUNGERE (non esiste, non serve)

**Firma corretta post-modifica**:
```python
def process_zip_and_generate_report(
    input_source,                     # INVARIATO
    api_key: str,
    progress_callback=None,
    status_callback=None,
    input_type: str = "zip",          # INVARIATO - FONDAMENTALE
    output_mode: str = "narrativo"    # NUOVO
) -> Tuple[bytes, Dict, str]:
```

**Branch da aggiungere** (subito dopo STEP 2 — dopo aver ottenuto `documents, failed_files`):
```python
# BRANCH MODALITÀ OUTPUT (DOPO STEP 2, PRIMA DI STEP 3)
if output_mode == "strutturato":
    return _pipeline_strutturata(
        documents, failed_files, api_key, input_name,
        total_files, progress_callback, status_callback, logger
    )
# Altrimenti: continua con pipeline narrativa invariata (STEP 3 in poi)
```

**Import da aggiungere** nella sezione `try:` degli import locali in `process_zip_and_generate_report()`:
```python
# Importa moduli strutturati solo se necessario (lazy import)
if output_mode == "strutturato":
    from modules.structured_evidence_parser import (
        parse_structured_response, extract_company_name_from_meta
    )
    from modules.structured_evidence_generator import generate_structured_evidence_docx
```

**Checklist**:
```
[ ] Firma aggiornata: input_type PRESENTE, norm ASSENTE, output_mode PRESENTE
[ ] process_zip_and_generate_report() chiama _pipeline_strutturata() direttamente (nessun if/else)
[ ] Firma invariata: nessun output_mode aggiunto, input_type preservato
[ ] _pipeline_strutturata() ritorna (bytes, stats_dict, filename) - NON (bytes, str, str)
[ ] stats_dict contiene: company_name, failed_files, total_docs, paragraphs_generated
[ ] MACROAREA_ORDER invariato (grep confermato — non toccato)
[ ] generate_report_word() e analyze_batch() presenti nel file ma non chiamati (dead code)
[ ] app.py: NESSUNA modifica — call site invariato
```

---

### ~~CHECKLIST B-4b~~ — ELIMINATA (decisione 2026-04-18)

> Il metodo strutturato è il nuovo default di Tab 1. Nessun radio button, nessuna modifica
> a `app.py`. Il file `app.py` non viene toccato in nessuno sprint del Piano B.
>
> Se in futuro si volesse ripristinare la scelta utente (narrativo vs strutturato),
> il codice del vecchio metodo è intatto in `report_generator.py` e può essere
> riattivato aggiungendo il parametro `output_mode` e il radio button.

---

### CHECKLIST B-5 — Deploy Finale e Test Completo

**Sequenza upload** (ordine obbligatorio):
```bash
# Nuovi file
MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/pscp.exe" -pw "PASSWORD" \
    modules/structured_evidence_parser.py \
    auditos@49.13.153.117:/opt/auditos/webapp/modules/

MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/pscp.exe" -pw "PASSWORD" \
    modules/structured_evidence_generator.py \
    auditos@49.13.153.117:/opt/auditos/webapp/modules/

MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/pscp.exe" -pw "PASSWORD" \
    prompts/universal_evidence_prompt.md \
    auditos@49.13.153.117:/opt/auditos/webapp/prompts/

# File modificati
MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/pscp.exe" -pw "PASSWORD" \
    modules/gemini_client.py \
    auditos@49.13.153.117:/opt/auditos/webapp/modules/

MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/pscp.exe" -pw "PASSWORD" \
    modules/report_generator.py \
    auditos@49.13.153.117:/opt/auditos/webapp/modules/

# app.py NON viene uploadato — nessuna modifica (decisione 2026-04-18)

# Riavvio obbligatorio (cache in-memory universal_prompt)
MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/plink.exe" -pw "PASSWORD" \
    auditos@49.13.153.117 "echo 'PASSWORD' | sudo -S systemctl restart auditos"
```

**Checklist post-deploy**:
```
[ ] systemctl status auditos → active (running)
[ ] journalctl -u auditos -n 20 → nessun ImportError
[ ] Test 1 — REGRESSIONE NARRATIVO:
    Upload ZIP reale → modalità "Narrativo" → report .docx generato
    Compara: stesso numero paragrafi, stessa struttura macroaree
[ ] Test 2 — MODALITÀ STRUTTURATA:
    Upload stesso ZIP → modalità "Strutturato" → .docx con card YAML generato
    Verifica: heading 1 per categoria, tabelle cluster per documento
[ ] Test 3 — TAB 2 DOPO STRUTTURATO:
    Usa il report strutturato in Tab 2 → genera JSON → nome azienda estratto OK
[ ] Test 4 — TAB 3:
    Tab 3 non coinvolta: apri una checklist precedente → funziona invariata
[ ] Test 5 — FOLDER UPLOAD:
    Upload tramite selezione cartella (input_type="uploaded_files") + narrativo → OK
[ ] 5 minuti log senza errori dopo test completo
```

---

## PARTE VI — ANALISI RISCHI AGGIORNATA (POST ANALISI CODICE)

| Rischio | Fonte | Severità | Mitigazione applicata |
|---------|-------|----------|-----------------------|
| Return contract sbagliato | Blueprint originale | CRITICO → RISOLTO | Spec corretta in PARTE III |
| Parametro `norm` fantasma | Blueprint + ROADMAP | ALTO → RISOLTO | Rimosso dalla spec corretta |
| `input_type` perso | Blueprint + ROADMAP | ALTO → RISOLTO | Esplicitamente preservato |
| `extract_company_name()` incompatibile | Non identificato | ALTO → RISOLTO | Fallback a meta YAML + docs grezzi |
| R-5 hook mancante su nuovo metodo | ROADMAP ordering | MEDIO → RISOLTO | R-5 spostato dopo B-3 |
| PyYAML non installato | Non identificato | MEDIO → RISOLTO | Checklist B-0 verifica e installa |
| Cache in-memory universal_prompt | Blueprint corretto | MEDIO → RISOLTO | Restart documentato post-deploy |
| Token budget YAML verboso | Blueprint corretto | MEDIO → MITIGATO | STRUCTURED_BATCH_SIZE = 4 |
| Tab 2 testo YAML vs prosa | Non identificato | BASSO → **RISOLTO** | Output JSON Tab 2 è immutabile. Tutti i 10 prompt checklist aggiornati con nota dual-format (2026-04-18). checklist_producer.py invariato. |
| ABBREV dictionary non persistente | Blueprint corretto | BASSO → ACCETTABILE | Ogni output è auto-contenuto |

---

## PARTE VII — SOPRAVVIVENZA ALLA MIGRAZIONE REACT

| Componente | Sopravvive? | Note |
|-----------|-------------|------|
| R-1 fix in gemini_ocr.py | ✅ Sì | Python puro |
| R-2 parser in gemini_client.py | ✅ Sì | Python puro |
| R-3 fix in report_generator.py | ✅ Sì | Python puro |
| R-4 DB schema + save_partial_error() | ✅ Sì | SQLite è backend |
| R-5 hook nei moduli | ✅ Sì | Python puro |
| B-0/B-1/B-2/B-3 nuovi moduli Python | ✅ Sì | Zero dipendenze UI |
| B-4a output_mode in report_generator.py | ✅ Sì | Parametro backend |
| B-4b radio button in app.py | ❌ No | Unico componente Streamlit specifico |
| Logica _pipeline_strutturata() | ✅ Sì | Diventa endpoint FastAPI |

**Conclusione**: 99% del lavoro sopravvive. L'unico artefatto da ricostruire è il radio button in `app.py` — che Base44 ricostruisce in React in 5 minuti.

---

## PARTE VIII — AGGIORNAMENTI DA FARE A ROADMAP.md

Aggiornare `maintenancewebapp/ROADMAP.md` con le seguenti correzioni:

1. **Sezione 3, Sprint B-4a** — Rimuovere `norm: str = "GENERICA"` dalla firma
2. **Sezione 3, Sprint B-4a** — Aggiungere `input_type: str = "zip"` alla firma (PRESERVATO)
3. **Sezione 3, Sprint B-4a** — Correggere contratto ritorno `_pipeline_strutturata()`: `(bytes, stats_dict, filename)` non `(docx_bytes, filename, nome_azienda)`
4. **Sezione 4, Ordine Esecuzione** — R-5 spostato dopo B-3
5. **Sezione 6, Invarianti** — Aggiungere: `input_type` parametro in `process_zip_and_generate_report()`
