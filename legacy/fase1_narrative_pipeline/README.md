# Fase 1 — Pipeline Narrativa (Legacy Snapshot)

Snapshot del vecchio approccio alla generazione della Relazione di Evidenze Oggettive, sostituito il **2026-04-18** dalla **Pipeline Strutturata v2.1** (PROMPT UNIVERSALE ADATTIVO).

Questo snapshot serve solo come **rollback di sicurezza**: se l'approccio strutturato dovesse fallire in modo sistemico, si può ripristinare rapidamente la versione narrativa.

## Contenuto

| File | Descrizione |
|------|-------------|
| `report_generator.original.py` | Copia integrale di `webapp/modules/report_generator.py` all'ultimo commit in cui la pipeline narrativa era il default |
| `api_prompt.md` | Copia del prompt narrativo caricato da `GeminiClient._load_system_prompt()` |

## Stato attuale del codice in produzione

Il file `webapp/modules/report_generator.py` **contiene ancora** le funzioni narrative come *dead code*:

- `generate_report_word()` — generatore .docx narrativo (righe ~431-505)
- `analyze_batch()` in `gemini_client.py` — analisi narrativa tramite Gemini
- STEP 3 narrativo + STEP 4 — dopo il `return _pipeline_strutturata(...)` (righe 877+)

Il dead code è **intenzionalmente preservato** nel file attivo come secondo livello di sicurezza; questo snapshot è il **terzo livello**.

## Come ripristinare la pipeline narrativa

### Opzione A — Rollback in-place (rapida)

Modificare `webapp/modules/report_generator.py`:

1. Cancellare la riga `return _pipeline_strutturata(...)` all'interno di `process_zip_and_generate_report()` (circa riga 872)
2. Il codice sottostante (STEP 3 narrativo + STEP 4) riprenderà ad essere eseguito
3. Riavviare `systemctl restart auditos` sul server

### Opzione B — Ripristino da snapshot (completo)

```bash
cp legacy/fase1_narrative_pipeline/report_generator.original.py webapp/modules/report_generator.py
systemctl restart auditos
```

## Perché è stata sostituita

La pipeline narrativa generava paragrafi discorsivi lunghi (200-800 parole) basati su un batch di documenti. La pipeline strutturata v2.1 genera invece blocchi di evidenze granulari norm-agnostic, più facili da mappare in Fase 2 (checklist producer) e più deterministici.

Decisione di sostituzione documentata in `maintenancewebapp/PIANO_B_PROMPT_UNIVERSALE.md` e `maintenancewebapp/ROADMAP.md`.

## Attenzione

- **NON rimuovere** `webapp/prompts/api_prompt.md` — anche se usato solo dal dead code, è eager-loaded da `GeminiClient.__init__` e la sua mancanza rompe l'istanziazione della classe
- **NON rimuovere** la funzione `optimize_text_content()` da `report_generator.py` — è condivisa tra pipeline attiva e legacy
