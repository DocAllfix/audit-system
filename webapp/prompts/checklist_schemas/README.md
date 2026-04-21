# Schema JSON per Norma

Questa cartella contiene le "chiavi JSON" che definiscono la struttura dell'output.
Ogni file descrive quali campi l'API deve generare per quella norma specifica.

## File da Caricare

Carica qui i tuoi file di chiavi (formato TXT o JSON):

- `ISO_9001_keys.txt` o `ISO_9001_schema.json`
- `ISO_14001_keys.txt` o `ISO_14001_schema.json`
- `ISO_45001_keys.txt` o `ISO_45001_schema.json`
- `ISO_37001_keys.txt` o `ISO_37001_schema.json`
- `SA_8000_keys.txt` o `SA_8000_schema.json`
- `PAS_24000_keys.txt` o `PAS_24000_schema.json`

## Note

- Questi file verranno usati per validare l'output dell'AI
- Verranno anche integrati nei prompt per istruire l'AI sulla struttura attesa
