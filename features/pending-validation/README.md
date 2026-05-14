# Features Pending Validation

Cartella per feature in sviluppo che NON sono ancora in PROD.

Quando una feature viene validata e deployata sul server `/opt/auditos/`,
il codice si sposta nel flow runtime corretto (`webapp/v2/` o `webapp/modules/`)
e i file qui dentro vengono rimossi o spostati.

## Convenzione

Ogni feature ha la propria sotto-cartella `<nome-feature>/`:
- prompt MD
- client Python
- test Python
- README spiegazione

Esempio: `features/pending-validation/schematic-output-mode/` (nuova modalita'
output prosa schematica telegrafica richiesta da cliente PROD, da validare
in worktree isolato `../audit-schematic-test/`).

## Workflow promozione a PROD

1. Sviluppo + test isolato (worktree separato + porta 8001)
2. Validazione cliente
3. Decisione utente: deploy manuale via pscp/plink al server
4. Spostamento file da `features/pending-validation/<X>/` a `webapp/v2/` o altro
5. Cleanup `features/pending-validation/<X>/`
