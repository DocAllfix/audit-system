# SOP: Compilazione Automatica Checklist di Audit

**Versione:** 1.0  
**Data:** 2025-12-29  
**Obiettivo:** Definire il processo per la compilazione automatica della Checklist di Audit a partire da un input JSON strutturato.

---

## 1. SCOPO

Questa procedura operativa standard governa il processo di:
1. Ricezione e validazione dell'input JSON contenente le evidenze strutturate
2. Mappatura dei dati JSON nei campi della Checklist di Audit
3. Generazione della Checklist compilata nel formato richiesto

---

## 2. CONTESTO DEL WORKFLOW

Questa SOP si attiva **dopo** il completamento del "Loop Umano", ovvero quando:
1. La "Relazione di Evidenze di Audit" (Word) è stata generata
2. Un processo esterno ha convertito la relazione in un JSON strutturato
3. Il JSON viene fornito come input al sistema

---

## 3. FORMATO INPUT JSON ATTESO

> [!NOTE]
> La struttura esatta del JSON sarà definita dopo aver ricevuto il template della Checklist di Audit dall'utente. Di seguito una struttura indicativa.

```json
{
  "metadata": {
    "data_audit": "YYYY-MM-DD",
    "auditor": "Nome Auditor",
    "organizzazione": "Nome Organizzazione"
  },
  "evidenze": [
    {
      "id": "EVD-001",
      "categoria": "Categoria Evidenza",
      "descrizione": "Descrizione dettagliata dell'evidenza",
      "documento_sorgente": "nome_documento.pdf",
      "pagina": 5
    }
  ]
}
```

---

## 4. WORKFLOW OPERATIVO

### FASE 1: Validazione Input (Execution Layer)
**Script:** `execution/validate_json.py`

1. Ricevere il percorso del file JSON in input
2. Validare la struttura JSON contro lo schema atteso
3. Verificare la presenza di tutti i campi obbligatori
4. Segnalare eventuali anomalie o dati mancanti

### FASE 2: Caricamento Template (Execution Layer)
**Script:** `execution/load_checklist_template.py`

1. Caricare il template della Checklist di Audit
2. Identificare i campi compilabili e la loro posizione
3. Creare una mappa campo -> posizione

### FASE 3: Mappatura Dati (Orchestration Layer)
**Esecutore:** Agente Gemini

1. Analizzare il JSON delle evidenze
2. Per ogni campo della checklist:
   - Identificare quale evidenza (o combinazione di evidenze) corrisponde
   - Determinare il valore da inserire
3. Generare le istruzioni di mappatura per lo script di compilazione

### FASE 4: Compilazione Checklist (Execution Layer)
**Script:** `execution/fill_checklist.py`

1. Ricevere le istruzioni di mappatura dall'Agente
2. Aprire il template della Checklist
3. Popolare ogni campo con il valore corrispondente
4. Preservare la formattazione originale del template
5. Salvare la Checklist compilata

---

## 5. FORMATI SUPPORTATI PER LA CHECKLIST

| Formato | Libreria Python | Note |
|---------|-----------------|------|
| Excel (.xlsx) | `openpyxl` | Formato preferito per manipolazione celle |
| Word (.docx) | `python-docx` | Per checklist basate su tabelle Word |
| PDF Form | `PyPDF2` / `pdfrw` | Solo per PDF con campi form compilabili |

---

## 6. REGOLE DI MAPPATURA

> [!IMPORTANT]
> Le regole di mappatura specifiche saranno definite dopo aver ricevuto il template della Checklist. Questa sezione verrà aggiornata di conseguenza.

### 6.1 Principi Generali
- Ogni campo della checklist deve essere mappato a uno o più campi JSON
- Se un dato non è disponibile, il campo deve essere lasciato vuoto (non inserire "N/A" o placeholder)
- Preservare il formato data/numero richiesto dalla checklist

---

## 7. GESTIONE ERRORI

| Tipo Errore | Azione |
|-------------|--------|
| JSON malformato | Interrompere e segnalare l'errore con dettagli parsing |
| Campo obbligatorio mancante | Loggare il warning, continuare con gli altri campi |
| Template checklist non trovato | Interrompere e richiedere il percorso corretto |
| Formato checklist non supportato | Aggiornare SOP e implementare nuovo handler |

---

## 8. OUTPUT ATTESO

- File Checklist compilata nel medesimo formato del template
- Log JSON delle operazioni di mappatura effettuate
- Report delle anomalie riscontrate (se presenti)

---

## 9. DIPENDENZE E PREREQUISITI

- Template Checklist di Audit (da ricevere dall'utente)
- Schema JSON validato
- Ambiente Python con librerie: `openpyxl`, `python-docx`, `json`

---

## 10. CHANGELOG

| Data | Versione | Modifica |
|------|----------|----------|
| 2025-12-29 | 1.0 | Creazione iniziale SOP - In attesa template checklist |
