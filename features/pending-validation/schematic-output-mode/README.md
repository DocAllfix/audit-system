# Schematic Output Mode — Pending Validation

Modalita' output alternativa richiesta da cliente che usa AUDIT-OS in produzione.
**NON in PROD attualmente** — feature in test isolato.

## Cos'e' la "Prosa Schematica Telegrafica"

Stile intermedio tra YAML strutturato (abbandonato) e prosa narrativa (PROD attuale):

| Aspetto | Narrative PROD | Schematic (qui) |
|---|---|---|
| Stile | prosa discorsiva, accademica | telegrafico, key:value |
| Lunghezza scheda | 200-800 parole | 50-400 parole |
| Struttura | paragrafo continuo | `Etichetta: Valore.` + sezioni MAIUSCOLE |
| Machine-readable | bassa | alta |
| Token output | 8-16K/batch | 4-9K/batch (-40%) |
| Costo /run RPC TECH | €0.18 | atteso €0.12 (-33%) |
| Tab 2 estrazione | OK | da verificare |

Regole formali (R0-R4 dal docx cliente):
- **R0**: `contenuto` inizia con `Tipologia: <NOME DOC>.`
- **R1**: una info per frase, S-V-O atomico
- **R2**: format `Etichetta: Valore.` (capitalizzata, punto finale)
- **R3**: numeri/ID/date trascritti ESATTI come compaiono
- **R4**: elenchi piatti con `-` (no annidamento)
- **R5** (estensione): sezioni MAIUSCOLE dinamiche per documenti complessi

## File qui

| File | Scopo |
|---|---|
| `schematic_evidence_prompt.md` | System prompt per Azure gpt-4.1-mini con R0-R5 + esempi prima/dopo |
| `schematic_client_v2.py` | Client clone narrative_client_v2 con prompt schematic + token meter kind separato (`analyze_schematic`) |
| `test_schematic_client.py` | Pytest smoke: prompt loaded, builder reminder, firma compat narrative |
| `README.md` | Questo file |

## Come testare in isolamento (senza toccare PROD)

Il sistema PROD (`/opt/auditos/` su `auditos.duckdns.org`) **resta intoccato**.
Il test gira in un worktree separato su porta diversa.

### 1. Worktree

Gia' creato da Step C1 del piano:
```bash
git worktree add ../audit-schematic-test test/output-mode-schematic main
```

### 2. Setup env nel worktree

```bash
cd ../audit-schematic-test
cp ../AUDITORSEMI/webapp/.env webapp/.env
# Cambia il valore V2_OUTPUT_MODE da 'narrative' a 'schematic'
sed -i 's/V2_OUTPUT_MODE=narrative/V2_OUTPUT_MODE=schematic/' webapp/.env

# Frontend punta a backend test 8001 (PROD locale resta 8000)
echo "VITE_API_BASE_URL=http://127.0.0.1:8001" > frontend/.env.local
```

### 3. Avvio backend test su porta 8001

```bash
cd webapp
PYTHONIOENCODING=utf-8 python -c "
import sys; sys.path.insert(0, '.')
import uvicorn
uvicorn.run('api_server:app', host='127.0.0.1', port=8001, reload=True)
"
```

### 4. Avvio frontend test su porta 5174

```bash
cd ../audit-schematic-test/frontend
npm install   # se serve
npm run dev -- --port 5174
```

### 5. Test pytest

```bash
cd ../audit-schematic-test
PYTHONPATH=webapp pytest features/pending-validation/schematic-output-mode/test_schematic_client.py -v
```

### 6. Test E2E

Browser → `http://127.0.0.1:5174/` → carica una pratica (es. RPC TECH).
Confronto vs PROD: scarica il docx, apri e confronta stile/dimensione/coverage.

## Verifica Tab 2 (importante)

Il docx schematico deve essere processabile dal `checklist_producer` di Tab 2.
Carica il docx schematico nel Tab 2 dello stesso backend test (8001) e
verifica che venga generato il JSON checklist popolato.

Se Tab 2 fallisce, opzioni:
- Adattare il parser checklist a riconoscere il pattern key:value
- Tornare al default `narrative` (vincitore baseline)

## Promozione a PROD (se validato)

Quando il cliente approva la qualita' output schematic:
1. Spostare `schematic_client_v2.py` da `features/pending-validation/schematic-output-mode/` a `webapp/v2/`
2. Spostare `schematic_evidence_prompt.md` a `webapp/prompts/`
3. Mantenere il gating env var (`V2_OUTPUT_MODE=schematic`) cosi' che PROD possa switchare runtime
4. Deploy manuale via pscp a `/opt/auditos/`
5. Cleanup `features/pending-validation/schematic-output-mode/`

## Pricing & metriche attese

Run RPC TECH (69 file, baseline narrative = €0.18 / 4m 5s):
- Schematic atteso: €0.12 / ~3m 30s
- Saving ~33% costo, ~15% tempo

Run MEDIL (181 file, baseline narrative = €0.35 / 9m 0s):
- Schematic atteso: €0.24 / ~7m 30s

Da validare con run reale (Step D del piano).
