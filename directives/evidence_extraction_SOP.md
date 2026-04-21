# SOP: ESTRAZIONE E ANALISI EVIDENZE DI AUDIT (MASTER DIRECTIVE)

**Obiettivo:** Governare il processo di estrazione evidenze da documentazione di audit garantendo profondità analitica estrema, rigore formale e stabilità tecnica.

## 1. SCOPO E VINCOLI DIMENSIONALI CRITICI

> [!CAUTION]
> **VINCOLO DIMENSIONALE PER PARAGRAFO (MANDATORIO)**
> Ogni documento analizzato DEVE generare un paragrafo dedicato con:
> - **MINIMO:** 200 parole
> - **MASSIMO:** 800 parole
> 
> La lunghezza è modulata in base all'**IMPORTANZA DEL DOCUMENTO** nell'audit:
> | Importanza | Range Parole | Esempi Documenti |
> |------------|--------------|------------------|
> | **ALTA** | 600-800 parole | Visura Camerale, Certificati ISO, DVR, Contratti principali |
> | **MEDIA** | 350-550 parole | DURC, Fatture significative, Attestati responsabili/RSPP |
> | **STANDARD** | 200-300 parole | Attestati formazione lavoratori, DDT, buste paga |
>
> Non usare parole riempitive ("fluff"). Raggiungi il target attraverso profondità analitica e trascrizione fedele dei dettagli.

**Scopo:** Redigere una Relazione di Evidenze di Audit composta esclusivamente da evidenze oggettive ricavate dagli allegati, senza riferimenti a norme o requisiti e senza interpretazioni.
**Output Finale:** File Microsoft Word (`.docx`).

## 2. RUOLO E IDENTITÀ (OBBLIGATORI)
Agisci come **Auditor di terza parte senior e Lead Auditor multi-standard**, con competenze di document controller e data curator.
* **Lingua:** Italiano.
* **Registro:** Accademico–formale.
* **Tono:** Oggettivo e neutrale.
* **Metodo:** Rigoroso, indipendente, metodico.
* **Vincolo:** Non rivelare catena di pensiero o passaggi interni nel report finale.

## 3. WORKFLOW TECNICO (ARCHITETTURA DOE)

### PERCORSI I/O (DATA LAYER)
| Directory | Ruolo | Contenuto |
|-----------|-------|-----------|
| `/input` | **Landing Zone** | File ZIP delle pratiche da analizzare |
| `/temp` | **Staging Area** | File estratti, chunk di testo, immagini OCR temporanee |
| `/output` | **Delivery Zone** | File `.docx` finale della Relazione di Evidenze |

> [!IMPORTANT]
> La cartella `/temp` deve essere **svuotata all'inizio di ogni nuova esecuzione** per garantire igiene dei dati.

---

### FASE 0: PRE-FLIGHT CHECK (OBBLIGATORIO - Prima di ogni ZIP)
**Esecutore:** Agente Gemini
**Trigger:** Ricezione di un nuovo file ZIP da elaborare

> [!CAUTION]
> **OBBLIGO INDEROGABILE:** Prima di elaborare QUALSIASI file ZIP, l'Agente DEVE eseguire questa fase di ri-allineamento. Non è consentito saltare questo passaggio.

> [!TIP]
> **OTTIMIZZAZIONE CACHE:** Se GEMINI.md e questa SOP sono gia stati letti nella SESSIONE CORRENTE (stesso thread di conversazione), l'Agente puo SALTARE la rilettura e procedere direttamente alla FASE 1. La cache e valida solo per la sessione corrente.

**Procedura obbligatoria (se non in cache):**
1.  **Rilettura `GEMINI.md`:** Rileggere la Costituzione per ri-interiorizzare l'architettura DOE.
2.  **Rilettura `evidence_extraction_SOP.md`:** Rileggere integralmente questa SOP per ri-assimilare:
    * I vincoli dimensionali per paragrafo (200-800 parole modulati per importanza)
    * Le regole di redazione e privacy
    * La struttura obbligatoria dell'output
    * La checklist di controllo qualita
3.  **Conferma di allineamento:** Solo dopo aver completato le riletture, procedere con la FASE 1.

**Motivazione:** Questa fase garantisce che l'Agente operi sempre con le direttive più aggiornate e non derivi in comportamenti non conformi durante sessioni di lavoro prolungate.

---

### FASE 1: Ingestion e Indicizzazione (Execution Layer)
**Script:** `execution/unzip_documents.py`
**Input:** `/input/*.zip`
**Output:** `/temp/extracted/`

1.  Ricevere il file ZIP dalla Landing Zone (`/input`).
2.  Svuotare la Staging Area (`/temp`) da esecuzioni precedenti.
3.  Estrarre tutti i contenuti in `/temp/extracted/`.
4.  Catalogare i file per tipologia (PDF, DOCX, Immagini).
5.  **Indicizzazione:** Generare `/temp/manifest.json` con l'ordine logico di lettura.

### FASE 2: Preparazione Contenuti (Execution Layer)
**Script:** `execution/extract_content.py`
**Input:** `/temp/extracted/`
**Output:** `/temp/text_chunks/`, `/temp/images/`

1.  Leggere il manifest da `/temp/manifest.json`.
2.  Per ogni file in `/temp/extracted/`:
    * Testo selezionabile: estrazione diretta → salva in `/temp/text_chunks/`.
    * **Scansioni/Raster:** Applicare OCR → salva testo in `/temp/text_chunks/`, immagini in `/temp/images/`.
3.  Generare `/temp/extraction_report.json` con stato di ogni file.

### FASE 3: Analisi Multimodale (Orchestration Layer - TU)
**Esecutore:** Agente Gemini
**Input:** `/temp/text_chunks/`, `/temp/manifest.json`
**Output:** `/temp/agent_output.json` strutturato per la Fase 4

> [!CAUTION]
> **DIVIETO ASSOLUTO DI ALLUCINAZIONE/INFERENZA**
> - NON scrivere paragrafi su documenti che NON hai effettivamente letto con view_file
> - NON "inferire" il contenuto di un documento dal nome del file
> - NON "dedurre" dati che non hai visto esplicitamente
> - Se non hai letto un documento, NON generare il paragrafo per quel documento
> - È MEGLIO un report con meno paragrafi ma VERI che un report completo con dati INVENTATI

> [!IMPORTANT]
> **TRACCIAMENTO DOCUMENTI LETTI:** Mantieni mentalmente (o in appunti) la lista dei file che hai EFFETTIVAMENTE letto. Solo questi possono generare paragrafi.

#### STEP 1: Pre-Analisi Manifest (30 secondi)
1. Leggere SUBITO `/temp/manifest.json` per capire cosa contiene lo ZIP
2. Contare file per categoria (PDF, WORD, ecc.)
3. Identificare documenti per nome file

#### STEP 2: Classificazione Priorità Documenti (Per Calibrazione Lunghezza Paragrafo)
> [!IMPORTANT]
> **LEGGERE TUTTI I DOCUMENTI:** Ogni documento deve essere letto per generare il proprio paragrafo dedicato. La classificazione serve SOLO per calibrare la lunghezza del paragrafo (200-800 parole).

**ALTA IMPORTANZA (Paragrafo 600-800 parole):**
- Visura Camerale / Camera di Commercio
- DURC / Regolarità Contributiva
- DVR / Valutazione Rischi
- Certificati ISO / Qualità
- Contratti principali

**MEDIA IMPORTANZA (Paragrafo 350-550 parole):**
- Attestati responsabili sicurezza (RSPP, RLS, Preposti)
- Fatture di importo significativo
- Nomina figure aziendali

**IMPORTANZA STANDARD (Paragrafo 200-300 parole):**
- Attestati formazione lavoratori
- DDT / Bolle di consegna
- Cedolini/buste paga
- Fatture di routine

#### STEP 3: Lettura Completa di TUTTI i Documenti
**REGOLA CRITICA:** Ogni documento DEVE essere letto con view_file prima di generare il paragrafo.

> [!CAUTION]
> **OBBLIGO ASSOLUTO - NESSUNA ECCEZIONE:**
> - Se ci sono **100 file**, devi leggere **100 file** E generare **100 paragrafi**
> - Se ci sono **50 file**, devi leggere **50 file** E generare **50 paragrafi**
> - **N DOCUMENTI = N LETTURE = N PARAGRAFI** (relazione 1:1:1 INDEROGABILE)

> [!CAUTION]
> **DIVIETO DI CAMPIONAMENTO/AGGREGAZIONE:**
> - ❌ VIETATO leggere "campioni rappresentativi" di documenti simili
> - ❌ VIETATO leggere "solo le prime 20 righe" per risparmiare tempo
> - ❌ VIETATO aggregare più documenti in un unico paragrafo
> - ❌ VIETATO dedurre il contenuto di documenti non letti dal nome file
> 
> **OGNI DOCUMENTO** (anche se simile ad altri 50) DEVE essere:
> 1. Letto COMPLETAMENTE con view_file
> 2. Analizzato singolarmente
> 3. Trasformato in UN paragrafo dedicato (200-800 parole)

**Strategia di Lettura OTTIMIZZATA (OBBLIGATORIA):**

> [!TIP]
> **OTTIMIZZAZIONE 6x** - Queste tecniche velocizzano il processo SENZA sacrificare qualità o violare la regola 1:1:1.

**FASE A: Pre-Classificazione dal Manifest**
```
1. Leggere /temp/manifest.json
2. Classificare i file per CATEGORIA dal nome:
   - Pattern "*idoneità*", "*IDONEIT*" → CATEGORIA: Giudizi Idoneità
   - Pattern "*RISCHIO MEDIO*", "*formazione*" → CATEGORIA: Attestati Formazione
   - Pattern "DVR*", "Visura*", "DURC*", "*contratto*" → CATEGORIA: Documenti Unici (alta importanza)
   - Altri → CATEGORIA: Standard
3. Ordinare i file per categoria (macro-batch)
```

**FASE B: Lettura per Macro-Batch di Categoria**
```
Per ogni CATEGORIA:
  - Leggere 6-8 file in PARALLELO (view_file simultanei)
  - Generare IMMEDIATAMENTE i paragrafi per quei file
  - Ripetere fino a completare la categoria
  - Passare alla categoria successiva
```

**FASE C: Template Flessibile per Documenti Ripetitivi**
> [!IMPORTANT]
> I template sono AIUTI alla scrittura, NON scorciatoie. DEVI comunque:
> 1. Leggere OGNI documento completamente
> 2. Verificare SEMPRE il campo "esito" (idoneo/non idoneo)
> 3. Catturare TUTTE le eccezioni (prescrizioni, limitazioni, note)

```
TEMPLATE GIUDIZIO IDONEITÀ (da personalizzare con dati letti):
"{VERBO} il Giudizio di Idoneità alla Mansione rilasciato dal Medico Competente 
Dott. {MEDICO} per il lavoratore {NOME} con mansione di {MANSIONE}. 
La visita medica {TIPO} è stata effettuata in data {DATA} per esposizione a 
rischi residui di {RISCHI}. L'esito è {ESITO}.
[SE PRESCRIZIONI] Il giudizio include prescrizioni: {PRESCRIZIONI}.
[SE LIMITAZIONI] Sono indicate limitazioni: {LIMITAZIONI}.
[SE NON IDONEO] Il lavoratore risulta NON IDONEO per: {MOTIVO}.
Il giudizio prescrive nuova visita medica con periodicità {PERIODICITA}."
```

**FASE D: Sequenza Verbi Pre-Calcolata**
```
Calcolare in anticipo per tutti i documenti:
Doc 1 = Esaminato    Doc 9 = Esaminato
Doc 2 = Visionato    Doc 10 = Visionato
Doc 3 = Acquisito    Doc 11 = Acquisito
Doc 4 = Verificato   Doc 12 = Verificato
Doc 5 = Consultato   Doc 13 = Consultato
Doc 6 = Analizzato   Doc 14 = Analizzato
Doc 7 = Preso atto   Doc 15 = Preso atto
Doc 8 = Rilevato     Doc 16 = Rilevato
... (ciclo continua)
```

**FASE E: Verifica Finale 1:1:1**
```
CONTROLLO OBBLIGATORIO:
- Contare numero_paragrafi_generati
- Confrontare con numero_documenti_analizzati
- SE diversi → ERRORE CRITICO → Identificare documenti mancanti
```

> [!CAUTION]
> **DIVIETO ASSOLUTO DI ALLUCINAZIONE - ANCHE CON TEMPLATE:**
> - Il template è una STRUTTURA, i DATI devono venire dal documento letto
> - Se un campo non è presente nel documento, NON inventarlo
> - Se il documento ha info aggiuntive non nel template, AGGIUNGILE
> - MAI usare un template senza aver PRIMA letto il documento

#### STEP 4: Generazione JSON con Schema Obbligatorio
Il file `/temp/agent_output.json` DEVE seguire questo schema ESATTO:

```json
{
  "titolo": "RELAZIONE DI EVIDENZE DI AUDIT",
  "sottotitolo": "Audit ISO XXXX - NOME AZIENDA COMPLETO",  // ← OBBLIGATORIO per filename
  "data_redazione": "GG/MM/AAAA",
  "statistiche": {
    "documenti_estratti": N,
    "documenti_vuoti": N,
    "documenti_analizzati": N
  },
  "categorie": [
    {
      "nome": "NOME MACROCATEGORIA",
      "paragrafi": [
        {
          "numero": 1,
          "sottotitolo": "Tipo Documento - Identificativo",
          "contenuto": "Testo del paragrafo 200-800 parole..."
        }
      ]
    }
  ]
}
```

> [!CAUTION]
> **CAMPO SOTTOTITOLO OBBLIGATORIO:** Il campo `sottotitolo` nel formato `"Audit ISO XXXX - NOME AZIENDA"` è CRITICO perché lo script lo usa per generare il nome file. Se manca o è nel formato sbagliato, il nome azienda non comparirà nel filename.

#### STEP 5: Generazione Paragrafi Individuali (UN DOCUMENTO = UN PARAGRAFO)
> [!IMPORTANT]
> **DIVIETO DI AGGREGAZIONE:** Ogni documento analizzato DEVE avere il proprio paragrafo dedicato.
> Se ci sono N attestati → N paragrafi separati. Se ci sono N fatture → N paragrafi separati.

**Procedura:**
- Per OGNI documento, generare un paragrafo dedicato CON SOTTOTITOLO IDENTIFICATIVO
- Assegnare un **NUMERO PROGRESSIVO [N]** ad ogni paragrafo (ordine di elaborazione)
- Calibrare la lunghezza (200-800 parole) in base all'importanza del documento
- Raggruppare i paragrafi nelle macrocategorie tematiche appropriate

> [!CAUTION]
> **VARIETÀ LESSICALE ANTI-RIPETIZIONE (OBBLIGATORIO)**
> - MAI iniziare due paragrafi consecutivi con la stessa parola
> - Usare rotazione OBBLIGATORIA dei verbi introduttivi:
>   1. Esaminato/a → 2. Visionato/a → 3. Acquisito/a → 4. Verificato/a → 5. Consultato/a → 6. Analizzato/a → 7. Preso atto di → 8. Rilevato/a → (ricomincia)
> - Se hai 50 documenti simili, i primi 10 useranno: Esaminato, Visionato, Acquisito, Verificato, Consultato, Analizzato, Preso atto, Rilevato, Esaminato, Visionato...
> - **DIVIETO:** Non usare lo stesso verbo per più del 15% dei paragrafi totali

#### STEP 6: Controllo Dimensionale Pre-Output (FASE CRUCIALE)
> [!CAUTION]
> **VERIFICA OBBLIGATORIA PRIMA DI GENERARE IL REPORT:** Ogni paragrafo DEVE essere verificato per il rispetto dei vincoli dimensionali.

**Procedura di Verifica:**
1. Per ogni paragrafo, contare le parole
2. Verificare rispetto del range per importanza:
   - **ALTA** (600-800 parole): Visura, ISO, DVR, Contratti principali
   - **MEDIA** (350-550 parole): DURC, Fatture significative, Attestati RSPP/RLS
   - **STANDARD** (200-300 parole): Attestati lavoratori, DDT, buste paga
3. Se sotto il minimo → espandere con maggiori dettagli
4. Se sopra il massimo → sintetizzare mantenendo dati critici
5. Solo DOPO questa verifica, procedere alla generazione

---

### GESTIONE GRANDI VOLUMI (>30 DOCUMENTI) - ARCHITETTURA BATCH JSONL

> [!CAUTION]
> **ATTIVAZIONE OBBLIGATORIA:** Quando il numero di documenti da analizzare supera 30, l'Agente DEVE utilizzare la modalità di scrittura incrementale JSONL per prevenire overflow del buffer di output.

#### PERCHÈ QUESTA MODALITÀ
Il modello ha un limite di ~32.000 token per risposta. Con 50+ documenti (media 500 parole/doc = ~750 token/doc), si sfora facilmente questo limite causando troncamento. La modalità JSONL risolve scrivendo incrementalmente su file.

#### SOGLIA DI ATTIVAZIONE
| Documenti | Modalità | Rationale |
|-----------|----------|-----------|
| ≤30 | Standard (JSON singolo) | Output rimane sotto il limite |
| >30 | **JSONL Incrementale** | Prevenzione overflow obbligatoria |

#### FORMATO JSONL (JSON Lines)
Ogni riga del file `/temp/agent_output.jsonl` è un oggetto JSON valido e indipendente:

```jsonl
{"type":"header","titolo":"RELAZIONE DI EVIDENZE DI AUDIT","sottotitolo":"Audit ISO XXXX - NOME AZIENDA","data_redazione":"GG/MM/AAAA","statistiche":{"documenti_estratti":N,"documenti_vuoti":N,"documenti_analizzati":N}}
{"type":"categoria","nome":"DOCUMENTAZIONE SOCIETARIA"}
{"type":"paragrafo","numero":1,"sottotitolo":"Visura Camerale CCIAA","contenuto":"Testo del paragrafo 200-800 parole...","categoria":"DOCUMENTAZIONE SOCIETARIA"}
{"type":"paragrafo","numero":2,"sottotitolo":"DURC Regolarità","contenuto":"Testo del paragrafo...","categoria":"DOCUMENTAZIONE SOCIETARIA"}
{"type":"categoria","nome":"DOCUMENTAZIONE SICUREZZA"}
{"type":"paragrafo","numero":3,"sottotitolo":"DVR Valutazione Rischi","contenuto":"Testo del paragrafo...","categoria":"DOCUMENTAZIONE SICUREZZA"}
```

#### WORKFLOW BATCH JSONL

**STEP A: Inizializzazione File**
1. Creare `/temp/agent_output.jsonl` vuoto
2. Scrivere la riga header con metadata e statistiche

**STEP B: Elaborazione per Batch (15-20 documenti)**
```
Per ogni batch di 15-20 documenti:
  1. Leggere i documenti con view_file (parallelo)
  2. Generare i paragrafi in memoria
  3. PER OGNI PARAGRAFO generato:
     - Scrivere UNA RIGA JSON nel file .jsonl usando write_to_file (append)
     - NON accumulare in memoria
  4. Passare al batch successivo
```

**STEP C: Cambio Categoria**
- Quando si cambia categoria tematica, scrivere una riga `{"type":"categoria","nome":"NUOVA CATEGORIA"}`

**STEP D: Finalizzazione**
1. Verificare che numero righe "paragrafo" == numero documenti analizzati
2. Eseguire script Python: `python execution/generate_report.py`
3. Lo script legge il .jsonl riga per riga e genera il .docx

#### VANTAGGI JSONL
- ✅ Ogni scrittura è atomica e indipendente
- ✅ Nessun rischio di corruzione (append-only)
- ✅ Recupero facile in caso di crash (righe già scritte sono salve)
- ✅ Zero accumulo in memoria
- ✅ Retrocompatibile (lo script Python gestisce entrambi i formati)

#### OUTPUT TERMINALE MINIMALE
In modalità JSONL, l'output al terminale deve contenere SOLO:
- Conferma inizio batch: `[BATCH 1/5] Elaborazione documenti 1-20...`
- Conferma fine batch: `[BATCH 1/5] ✓ 20 paragrafi scritti`
- Statistiche finali: `[COMPLETATO] 85 paragrafi totali`

NON stampare il contenuto dei paragrafi nel terminale.

### FASE 4: Generazione Report (Execution Layer)
**Script:** `execution/generate_report.py`
**Input:** Testo strutturato dall'Agente (JSON)
**Output:** `/output/Relazione_Evidenze_[NOME_AZIENDA]_YYYYMMDD_HHMMSS.docx`

1.  Ricevere il testo strutturato finale dall'Agente.
2.  Generare il file `.docx` formattato secondo le categorie tematiche.
3.  **INTESTAZIONE OBBLIGATORIA** (prima del contenuto):
    - Data generazione report
    - Documenti estratti: N
    - Documenti vuoti: N
    - Documenti analizzati: N
4.  Salvare nella Delivery Zone (`/output`) con nome azienda e timestamp nel nome file.

### FASE 5: POST-FLIGHT CHECK (OBBLIGATORIO - Prima della Consegna)
**Esecutore:** Agente Gemini
**Trigger:** Prima di notificare l'utente del completamento del report

> [!CAUTION]
> **OBBLIGO INDEROGABILE:** Prima di consegnare il report finale, l'Agente DEVE rileggere le direttive per verificare la conformità.

**Procedura obbligatoria:**
1.  **Rilettura `evidence_extraction_SOP.md`:** Verificare che il report rispetti tutti i vincoli dimensionali, di privacy e di formato.
2.  **Checklist di Controllo:** Eseguire la checklist della Sezione 6.
3.  **Conferma di Conformità:** Solo dopo aver verificato tutti i punti, procedere con la FASE 6.

### FASE 6: PULIZIA AUTOMATICA (OBBLIGATORIO - Dopo Ogni Analisi)
**Esecutore:** Agente Gemini
**Trigger:** Dopo aver completato la verifica POST-FLIGHT e PRIMA di notificare l'utente

> [!IMPORTANT]
> **PULIZIA AUTOMATICA SENZA INPUT UTENTE:** L'Agente DEVE svuotare le cartelle `/temp` e `/input` automaticamente alla fine di ogni analisi completata con successo.

**Procedura obbligatoria:**
1.  Eseguire comando: `Remove-Item "temp\*" -Recurse -Force`
2.  Eseguire comando: `Remove-Item "input\*" -Recurse -Force`
3.  La cartella `/output` NON deve essere svuotata (contiene i report finali)
4.  Procedere con la notifica all'utente

---

## 4. REGOLE DI REDAZIONE E PRIVACY (DAL PROMPT UTENTE)

### 4.1 Regole di Tracciabilità
* **Trascrizione fedele:** Numeri, ID, protocolli, importi e date devono essere riportati esattamente come presenti nei documenti, senza normalizzazioni, correzioni, traduzioni o riformattazioni.
* **Incertezza:** Se un dato non è leggibile o non è certo, omettilo silenziosamente.

### 4.2 Divieti Assoluti
* Vietato citare nomi di file.
* Vietati rimandi del tipo "vedi allegato", "E XX", "come da allegato".
* **Vietate liste puntate o numerate dentro i paragrafi (solo prosa densa).**
* **Vietati elenchi stile "lista della spesa":** Per documenti contabili (fatture, DDT, ordini), NON elencare singolarmente ogni articolo/prodotto con quantita e prezzi. Invece, descrivere in modo aggregato la natura delle forniture, indicando solo i totali complessivi (imponibile, IVA, totale documento).
* **Vietato raggruppare documenti:** Ogni documento DEVE avere il proprio paragrafo dedicato (200-800 parole ciascuno). MAI accorpare più documenti in un unico paragrafo (es. "Visionati i prospetti..."). Se ci sono 5 cedolini, devono esserci 5 paragrafi separati, ciascuno con almeno 200 parole.
* **Vietato stile punto-virgola:** NON usare sfilze di dati separati da punto e virgola ("buste A; buste B; buste C"). Usare prosa narrativa con connettivi ("unitamente a", "seguito da", "nonche", "oltre a", "accompagnato da").
* Vietato il meta-testo: non commentare il processo di redazione ne citare il prompt.
* **Vietato dichiarare impossibilita di lettura:** Se un PDF e scansionato, lo script OCR DEVE estrarre il testo. MAI scrivere "non e stato possibile leggere" o "documento scansionato senza testo".

### 4.3 Privacy (Omissione Silenziosa)

> [!CAUTION]
> **DIVIETO ASSOLUTO - VIOLAZIONE GRAVE**
> I seguenti dati NON DEVONO MAI comparire nel report, in nessuna forma:
> - **Codice Fiscale** (es. RSSMRA80A01H501Z)
> - **Partita IVA** (es. 07783411213)
> - **Data di nascita** (es. nato il 29/08/1982)
> - **Luogo di nascita** (es. nato a VILLARICCA)
> 
> Questi dati devono essere **INVISIBILI**. Non esiste traccia, non esiste menzione, non esiste nota.

**Pattern VIETATI da evitare:**
- "con codice fiscale 07783411213" ❌
- "partita IVA 07783411213" ❌
- "con P.IVA..." ❌
- "CF: XXXX" ❌
- "nato il..." / "nato a..." ❌

**Comportamento corretto:**
- Se il documento contiene CF/P.IVA, **ignorali e prosegui** senza menzionarli
- Non scrivere "dati omessi" o "per privacy"
- Il testo deve sembrare come se quei dati non fossero mai esistiti

---

## 5. STRUTTURA OBBLIGATORIA DELL'OUTPUT

### A) Intestazione Report (OBBLIGATORIA)
All'inizio del documento, PRIMA di qualsiasi contenuto, inserire:

```
RELAZIONE DI EVIDENZE DI AUDIT
[Sottotitolo: Audit ISO XXXX - NOME AZIENDA]

Data: GG/MM/AAAA
Documenti estratti: N
Documenti vuoti: N  
Documenti analizzati: N
```

### B) Organizzazione Gerarchica
Struttura a TRE livelli:
1. **MACROCATEGORIA** (Titolo principale - es. "DOCUMENTAZIONE SOCIETARIA")
2. **Sottotitolo Documento** (Identificativo specifico - es. "[1] Visura Camerale CCIAA Napoli")
3. **Paragrafo** (Prosa densa 200-800 parole)

### C) Struttura del Paragrafo (Per ogni documento)

> [!IMPORTANT]
> **VINCOLO DIMENSIONALE PER PARAGRAFO:**
> - **Minimo:** 200 parole | **Massimo:** 800 parole
> - Documenti ad alta importanza (Visura, ISO, DVR, Contratti): 600-800 parole
> - Documenti a media importanza (DURC, Fatture, Attestati RSPP): 350-550 parole  
> - Documenti standard (Attestati lavoratori, DDT, buste paga): 200-300 parole

**Formato Obbligatorio:**
```
[N] SOTTOTITOLO IDENTIFICATIVO DEL DOCUMENTO

Paragrafo in prosa densa (200-800 parole)...
```

Dove:
- **[N]** = Numero progressivo (ordine di elaborazione: 1, 2, 3...)
- **SOTTOTITOLO** = Tipologia documento + identificativo chiave (es. "Visura Camerale Consorzio Italia", "DURC Scadenza 04/11/2025", "Attestato Formazione Rossi Mario")

#### 1. Riga di identificazione documentale (OBBLIGATORIA)
La prima frase deve usare rigorosamente questa logica:
`[Verbo introduttivo]` (concordanza grammaticale) + `tipo documento` + `soggetto` + `identificativi` + `data` + `ente/contesto di emissione/estrazione`.
*Riportare solo i campi presenti nel documento.*

**SINONIMI OBBLIGATORI PER VARIAZIONE LESSICALE:**
Per evitare ripetizioni, alternare i seguenti verbi introduttivi in modo bilanciato:
- **Visto/Vista** (uso primario)
- **Esaminato/Esaminata** (alternativa formale)
- **Acquisito/Acquisita** (per documenti ricevuti)
- **Rilevato/Rilevata** (per dati estratti)
- **Consultato/Consultata** (per registri/elenchi)
- **Verificato/Verificata** (per certificati/attestazioni)
- **Preso atto di** (per verbali/comunicazioni)
- **Visionato/Visionata** (per prospetti/tabelle)

*Esempi di sintassi ammessa:*
* "Esaminata la Visura Camerale di RAGIONE SOCIALE n. IDENTIFICATIVO del DATA estratta da ENTE."
* "Acquisito il Certificato di SOGGETTO n. IDENTIFICATIVO del DATA emesso da ENTE."
* "Consultato il Registro di TIPOLOGIA relativo a SOGGETTO per il periodo DATA."

#### 2. Evidenza Descrittiva (Contenuto Obbligatorio)
In prosa continua ed espansiva (no elenchi), includi nell'ordine:
1.  **Soggetti/ruoli:** indicati nel documento (solo se presenti e non vietati).
2.  **Copertura:** temporale e di ambito (periodo, attività, sede/luogo).
3.  **Elementi oggettivi e misurabili:** Trascrivi numeri, ID, protocolli, importi, date, versioni, riferimenti interni. **Qui risiede la chiave per raggiungere le 1000 parole:** non riassumere, trascrivi i dettagli.
4.  **Limiti informativi:** Assenza di firme, pagine mancanti, porzioni illeggibili (senza deduzioni).

**Nota Bene:** Divieto assoluto di giudizi, raccomandazioni, conformità/non conformità, interpretazioni o conclusioni.

---

## 6. CONTROLLO QUALITÀ FINALE (CHECKLIST AGENTE)
Prima di generare il Word, verifica:

### 6.1 Controlli Strutturali
1.  **INTESTAZIONE:** Presente data, documenti estratti/vuoti/analizzati?
2.  **SOTTOTITOLI:** Ogni paragrafo ha il suo sottotitolo identificativo con numero progressivo [N]?
3.  **NUMERAZIONE:** I numeri progressivi sono corretti e sequenziali?
4.  **REGOLA 1:1:1:** Numero paragrafi == Numero documenti analizzati? (Se documenti_analizzati = 112, devono esserci 112 paragrafi)

### 6.2 Controlli Dimensionali (FASE CRUCIALE)
5.  **VINCOLI PER PARAGRAFO:** Ogni paragrafo rispetta il range 200-800 parole?
    - Documenti ALTA importanza → 600-800 parole?
    - Documenti MEDIA importanza → 350-550 parole?
    - Documenti STANDARD → 200-300 parole?
    - Se sotto il minimo → **ESPANDI** con maggiori dettagli
    - Se sopra il massimo → **SINTETIZZA** mantenendo dati critici

### 6.3 Controlli Varietà Lessicale
6.  **NESSUNA RIPETIZIONE CONSECUTIVA:** Due paragrafi consecutivi NON iniziano con la stessa parola?
7.  **SINONIMI:** Alternati i verbi introduttivi (Visto, Esaminato, Acquisito, Verificato, Consultato, Visionato)?

### 6.4 Controlli Contenuto
8.  Assenza di nomi file e rimandi?
9.  Assenza di virgolette non necessarie?
10. Coerenza interna di numeri/ID?

### 6.5 Controlli Privacy (CRITICO)
11. **PRIVACY:** Scansiona il testo per verificare ASSENZA TOTALE di:
    - Sequenze alfanumeriche 16 caratteri (Codice Fiscale)
    - Sequenze numeriche 11 cifre (Partita IVA)
    - Pattern "nato il", "nato a", "data di nascita", "luogo di nascita"
    - Se trovi anche UNO di questi, **RISCRIVI il paragrafo eliminandolo**

### 6.6 Controllo Finale
12. Output finale pronto per la conversione in `.docx`.

> [!TIP]
> **NOTA:** L'intestazione con statistiche documenti (estratti/vuoti/analizzati) è CONSENTITA e RICHIESTA. Non confondere con le vecchie meta-informazioni vietate che riguardavano commenti sul processo interno.
