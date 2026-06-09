# Tab 2 — Ottimizzazione futura: ridurre le clausole per gruppo

> Nota di lavoro **per dopo**. Non urgente: il problema delle clausole corte è già
> risolto in produzione dalla rete di sicurezza di rigenerazione (vedi
> `checklist_producer.py`, `REGEN_TRIGGER_RATIO`, `regenerate_short_clauses`).
> Questa è un'ottimizzazione di **qualità al primo passaggio + velocità + costo**,
> non una correzione di bug.

## Contesto

La Tab 2 (Azure GPT-4.1-mini) divide le clausole di una norma in `PARALLEL_GROUPS = 6`
gruppi elaborati in parallelo. Per ISO 9001 (76 clausole) significa ~13 clausole per
gruppo, generate in **un'unica risposta JSON strutturata** per chiamata.

**Osservazione (validata in prod):** dovendo produrre ~13 clausole in una sola
risposta, GPT-4.1-mini scrive ciascuna clausola più breve (~130-165 parole) rispetto
al target (150-350). Risultato: su ISO 9001 ~40 clausole su 76 finiscono sotto la
soglia trigger (142) e vengono rigenerate una per una. La rigenerazione è parallela e
veloce (run prod ~139s, zero 429), ma sono ~40 chiamate Azure extra per run.

Il **footer rinforzato dei prompt (Fix B)** da solo NON ha spostato l'ago: il limite è
strutturale (troppe clausole per chiamata), non di istruzione.

## Idea

Ridurre il numero di clausole per gruppo → il modello ha più "spazio/attenzione" per
clausola → clausole più lunghe già al primo passaggio → **meno rigenerazioni**
(più veloce, meno costo, migliore qualità first-pass).

Opzioni implementative (in `checklist_producer.py`):
- Introdurre `MAX_CLAUSES_PER_GROUP` (es. 6-8) e calcolare `num_groups = ceil(len(clausole)/MAX_CLAUSES_PER_GROUP)` invece del fisso `PARALLEL_GROUPS = 6`. Per ISO 9001 → ~10-13 gruppi da 6-8 clausole.
- In alternativa, alzare `PARALLEL_GROUPS` in funzione della numerosità della norma.
- Punto di intervento: la funzione che divide le clausole in gruppi + `process_clause_group`.

## Trade-off
- **Pro:** meno rigenerazioni sequenziali-per-clausola, first-pass più a norma, meno chiamate totali nel caso medio.
- **Contro:** più chiamate di *gruppo* in parallelo (ma Azure 16M TPM le regge senza 429; e il calo delle rigenerazioni compensa). Da tarare per non frammentare troppo (gruppi troppo piccoli = overhead per-chiamata).

## Come validare (quando si farà)
1. Misurare, su ISO 9001 con un report reale, il conteggio di clausole `< 142` **pre-rigenerazione** con `PARALLEL_GROUPS=6` (baseline attuale).
2. Ripetere con `MAX_CLAUSES_PER_GROUP=6-8` e confrontare: atteso un crollo del conteggio pre-rigenerazione e quindi delle rigenerazioni.
3. Verificare tempo totale e assenza di 429.
4. Controllare che la qualità della prosa non degradi (no padding incoerente).

## Stato attuale (baseline da battere)
ISO 9001 prod, ratio 0.95: min 144 / median 205 / max 340, 5 clausole a 144-149,
**41 rigenerazioni** parallele, 139s, zero 429.
