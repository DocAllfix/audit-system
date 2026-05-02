"""
V2 — YAML Parser (Fase 8).

Parser tollerante per il YAML aggregato prodotto dal modello via N batch.

Il prompt universale di V1 produce, per ogni batch, un blocco YAML con:
- meta.azienda (può apparire in 1+ batch — quello che ha la visura/statuto)
- sezioni: [{id, nome, documenti: [...]}, ...]

Aggregazione di N batch:
- meta merge: prendi il primo `meta.azienda` non vuoto da qualsiasi batch
- sezioni concat: dedup per `nome` e merge dei documenti

Caratteristiche:
- Mai eccezione: errori per batch loggati, batch saltato
- Tollerante a YAML malformato (uso pyyaml safe_load_all)
- Dedup sezioni per nome (case-insensitive) → merge documenti
- Estrazione robusta del nome azienda: scarta valori vuoti / placeholder

API pubblica:
    parse_aggregated_yaml(text) -> dict
    extract_company_name(parsed_data) -> str
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    yaml = None  # type: ignore


# Placeholders/valori invalidi per il nome azienda (anti-allucinazione)
_INVALID_COMPANY_VALUES = {
    "", "n.d.", "n/a", "none", "null", "azienda non identificata",
    "[ragione sociale", "ragione sociale", "nome azienda",
    "ragione_sociale", "[ragione sociale — regola inderogabile]",
}


# ──────────────────────────────────────────────────────────────────────────────
# Parsing low-level
# ──────────────────────────────────────────────────────────────────────────────

def _strip_yaml_fences(text: str) -> str:
    """
    Rimuove fences ```yaml ... ``` se presenti (alcuni modelli li aggiungono).
    Gestisce sia i fence di apertura/chiusura ai bordi sia quelli annidati
    in mezzo al testo (modelli a volte mettono fence attorno a singole sezioni).
    """
    if not text:
        return ""
    cleaned = text.strip()
    # Rimuovi qualsiasi linea che è solo ``` o ```yaml (ovunque appaia)
    cleaned = re.sub(
        r"^```(?:yaml)?\s*$",
        "",
        cleaned,
        flags=re.MULTILINE,
    )
    return cleaned.strip()


def _safe_load_yaml(text: str, batch_id: str = "") -> Any:
    """
    yaml.safe_load tollerante con auto-recovery su errori comuni:
    1. Tentativo standard
    2. Se fallisce per block-scalar mal indentato (tabelle Markdown
       all'interno di campi YAML), tenta sanitization e riprova
    3. Se ancora fallisce → None

    Quando il parsing fallisce a tutti i livelli, il batch viene tracciato
    in `_LAST_PARSE_FAILURES` con identificatore + prima riga + errore,
    così il chiamante può recuperare l'informazione invece di scoprire
    "in silenzio" che un batch è scomparso (Leva 3).
    """
    if not HAS_YAML or not text:
        return None
    # Tentativo 1: standard
    try:
        return yaml.safe_load(text)
    except Exception as e:
        first_err = e

    # Tentativo 2: sanitize tabelle Markdown mal indentate
    sanitized = _sanitize_markdown_tables_in_yaml(text)
    if sanitized != text:
        try:
            return yaml.safe_load(sanitized)
        except Exception:
            pass

    # Tentativo 3: rimuovi righe pipe problematiche (best effort)
    stripped = _strip_problematic_pipe_lines(text)
    if stripped != text:
        try:
            return yaml.safe_load(stripped)
        except Exception:
            pass

    # Fallimento definitivo — registra (mai eccezione)
    first_line = (text.split("\n", 1)[0] or "").strip()[:160]
    err_msg = str(first_err)[:200]
    label = batch_id or "<unknown>"
    print(
        f"[V2 YAML] safe_load fallito su batch {label}: {err_msg} "
        f"(prima riga: {first_line!r})"
    )
    try:
        _LAST_PARSE_FAILURES.append({
            "batch_id": batch_id,
            "error": err_msg,
            "first_line": first_line,
            "size_chars": len(text),
        })
    except Exception:
        pass
    return None


# Buffer in-process delle ultime failure di parsing. Volutamente semplice
# (lista globale) — il chiamante è responsabile di leggerla / svuotarla
# all'inizio di ogni invocazione di `parse_aggregated_yaml`.
_LAST_PARSE_FAILURES: List[Dict[str, Any]] = []


def get_last_parse_failures() -> List[Dict[str, Any]]:
    """Ritorna copia delle failure registrate dall'ultima invocazione di parse."""
    return list(_LAST_PARSE_FAILURES)


def _reset_parse_failures() -> None:
    """Svuota il buffer failure. Chiamato all'inizio di parse_aggregated_yaml."""
    _LAST_PARSE_FAILURES.clear()


def _sanitize_markdown_tables_in_yaml(text: str) -> str:
    """
    Trova blocchi `key: |` o `key: >` seguiti da righe che iniziano con `|`
    NON indentate rispetto alla key, e re-indenta le righe del block scalar.

    Esempio fail (yaml lo rifiuta):
        descrizione: |
        | Codice | Desc |
        | A001 | x |

    Output (yaml lo accetta):
        descrizione: |
          | Codice | Desc |
          | A001 | x |
    """
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)

        # Cerca pattern "  key: |" o "  key: >" o "  key: |-"
        m = re.match(r"^(\s*)([\w_\-]+)\s*:\s*[|>][-+]?\s*$", line)
        if m:
            base_indent = len(m.group(1))
            target_indent = base_indent + 2
            # Re-indenta le righe seguenti del block scalar
            j = i + 1
            while j < len(lines):
                child = lines[j]
                if not child.strip():
                    out.append(child)
                    j += 1
                    continue
                # Conta indent della riga
                child_indent = len(child) - len(child.lstrip(" "))
                if child_indent <= base_indent:
                    # Fine block scalar (o riga mal indentata)
                    if child.lstrip().startswith("|") and child_indent <= base_indent:
                        # Tabella Markdown non indentata: re-indento
                        out.append(" " * target_indent + child.lstrip())
                        j += 1
                        continue
                    break
                out.append(child)
                j += 1
            i = j
            continue
        i += 1
    return "\n".join(out)


def _strip_problematic_pipe_lines(text: str) -> str:
    """
    Ultima chance: rimuove righe top-level che iniziano con `|` e che non sono
    parte di un block scalar valido. Best effort: scarta info ma non rompe
    il parsing.
    """
    lines = text.split("\n")
    out = []
    in_block_scalar = False
    block_scalar_indent = 0
    for line in lines:
        # Block scalar marker
        if re.match(r"^(\s*)[\w_\-]+\s*:\s*[|>][-+]?\s*$", line):
            in_block_scalar = True
            block_scalar_indent = len(line) - len(line.lstrip(" "))
            out.append(line)
            continue

        if in_block_scalar:
            stripped = line.lstrip(" ")
            line_indent = len(line) - len(stripped)
            if not stripped:
                out.append(line)
                continue
            if line_indent <= block_scalar_indent:
                in_block_scalar = False
                # falltrough a check normale
            else:
                out.append(line)
                continue

        # Riga top-level che inizia con `|` → scarta (tabella Markdown stand-alone)
        if line.lstrip().startswith("|") and not re.match(r"^\s+", line):
            continue
        out.append(line)
    return "\n".join(out)


def _split_by_separator(text: str) -> List[str]:
    """
    Split per `\\n---\\n` separator (con eventuali whitespace).
    Tollerante a separatori a inizio/fine.
    """
    import re as _re
    # Match: newline + '---' + newline (whitespace consentito)
    parts = _re.split(r"\n\s*---\s*\n", text)
    return [p for p in parts if p.strip()]


def _normalize_doc_entry(d: Any) -> Dict[str, Any]:
    """Normalizza un'entry documento, restituisce dict pulito o {}."""
    if not isinstance(d, dict):
        return {}
    # Strip valori string-only
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = v.strip()
        else:
            out[k] = v
    return out


# Chiavi top-level del YAML batch che NON appartengono al documento singolo
# (sono gestite separatamente): meta, azienda, indice, audit, sezioni
_NON_DOC_TOP_KEYS = {"meta", "azienda", "indice", "audit", "sezioni"}


def _extract_top_level_doc(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Riconosce la struttura YAML "piatta" prodotta dal modello quando il
    batch contiene un solo documento. Ritorna il dict del documento se
    rilevato, None altrimenti.

    Struttura piatta tipica:
        azienda: {...}
        indice: [...]
        tipo: "Visura Camerale"          ← top-level
        categoria: "08 · LEGALE"
        titolo: "..."
        emesso_da: "..."
        soggetto: "..."
        ... (altri campi del documento)

    Distinzione: se è presente `sezioni` (struttura annidata), questa
    funzione ritorna None — la logica esistente la gestisce.

    Heuristica: serve almeno `tipo` o `titolo` al top-level perché sia
    riconosciuto come documento valido (evita falsi positivi su batch
    che hanno solo meta/azienda/indice).
    """
    if not isinstance(d, dict):
        return None
    # Se ha già una struttura annidata, non è "piatto"
    if d.get("sezioni"):
        return None
    has_tipo = bool(str(d.get("tipo", "")).strip())
    has_titolo = bool(str(d.get("titolo", "")).strip())
    if not (has_tipo or has_titolo):
        return None

    # Costruisci dict documento estraendo TUTTE le chiavi che non sono meta-level
    doc: Dict[str, Any] = {}
    for k, v in d.items():
        if k in _NON_DOC_TOP_KEYS:
            continue
        doc[k] = v
    return _normalize_doc_entry(doc) or None


def _section_key_from_categoria(categoria: Any) -> Optional[tuple]:
    """
    Estrae (id, nome) di sezione dal campo `categoria` di un documento.

    Esempi:
      "08 · DOCUMENTAZIONE LEGALE E SOCIETARIA" -> ("08", "08 · DOCUMENTAZIONE LEGALE E SOCIETARIA")
      "10 · SSL"                                 -> ("10", "10 · SSL")
      "" o non-string                            -> None
    """
    if not isinstance(categoria, str):
        return None
    cat = categoria.strip()
    if not cat:
        return None
    # Estrai prefix numerico (id sezione)
    m = re.match(r"^(\d{1,2})\s*[·\-—]?\s*", cat)
    sec_id = m.group(1) if m else ""
    return (sec_id, cat)


def _normalize_company_name(name: Any) -> str:
    """Pulisce e valida il nome azienda. '' se invalido."""
    if not isinstance(name, str):
        return ""
    cleaned = name.strip()
    if not cleaned:
        return ""
    # Lowercase per il check
    if cleaned.lower() in _INVALID_COMPANY_VALUES:
        return ""
    # Rimuovi placeholders parziali tipo "[..]"
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return ""
    return cleaned


def _score_company_source(block_tipi: List[str]) -> int:
    """
    Scoring V1-style per qualità della fonte del nome azienda.

    Replica esattamente la logica di V1 structured_evidence_parser:
    - Visura camerale / CCIAA / registro imprese: +100 (massima affidabilità)
    - Statuto / atto costitutivo: +80
    - Attestazione SOA / certificato ISO / rating legalità: +60
    - Fattura / bilancio: +30
    - DVR / curriculum / attestato formazione / registro presenze: -50
      (penalità: il "soggetto" estratto è probabilmente consulente/formatore
      esterno, NON l'azienda audita)

    Il batch con score più alto vince — questo evita di scegliere come
    "azienda" il subappaltatore o il consulente RSPP citato nel DVR.
    """
    if not block_tipi:
        return 0
    tipi_joined = " ".join(block_tipi).lower()
    score = 0
    if re.search(r"visura|camerale|cciaa|registro imprese", tipi_joined):
        score += 100
    if re.search(r"statuto|atto costitutivo|atto notarile", tipi_joined):
        score += 80
    if re.search(r"attestazione soa|certificato iso|rating legalit", tipi_joined):
        score += 60
    if re.search(r"fattura|bilancio", tipi_joined):
        score += 30
    if re.search(
        r"\bdvr\b|curriculum|cv |attestato.{0,30}formazione|registro.{0,5}presenze",
        tipi_joined,
    ):
        score -= 50
    return score


# ──────────────────────────────────────────────────────────────────────────────
# Aggregazione batch
# ──────────────────────────────────────────────────────────────────────────────

def parse_aggregated_yaml(text: str) -> Dict[str, Any]:
    """
    Parse il YAML aggregato di N batch (separati da `\\n\\n---\\n\\n` o
    direttamente come multi-document YAML).

    Returns:
        Dict normalizzato:
        {
            "meta": {"azienda": {...}, "indice": [...], "audit": {...}},
            "sezioni": [{"id", "nome", "documenti": [...]}, ...]
        }

        Se input vuoto o totalmente malformato, ritorna stub con sezioni vuote.
    """
    # Resetta sempre il buffer failure all'inizio (Leva 3): il chiamante
    # potrà leggere `get_last_parse_failures()` per sapere quali batch
    # sono stati saltati.
    _reset_parse_failures()

    if not text or not HAS_YAML:
        return {"meta": {"azienda": {}, "indice": [], "audit": {}}, "sezioni": []}

    cleaned = _strip_yaml_fences(text)
    if not cleaned:
        return {"meta": {"azienda": {}, "indice": [], "audit": {}}, "sezioni": []}

    # Split manuale per `\n---\n` separator: più tollerante di safe_load_all
    # (un batch corrotto non blocca il parsing degli altri)
    chunks = _split_by_separator(cleaned)
    documents: List[Any] = []
    for chunk_idx, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        d = _safe_load_yaml(chunk, batch_id=f"chunk_{chunk_idx:03d}")
        if isinstance(d, dict):
            documents.append(d)

    # Aggrega i documenti
    merged_indice: List[Dict[str, Any]] = []
    merged_audit: Dict[str, Any] = {}
    sezioni_by_name: Dict[str, Dict[str, Any]] = {}
    # Candidate per il nome azienda con scoring V1-style
    azienda_candidates: List[tuple] = []  # (score, azienda_dict)
    # Merge accumulativo dei campi azienda secondari (piva/sede/REA/...)
    # da tutti i batch — primo non-vuoto vince. Solo `nome` usa lo score.
    merged_secondary_fields: Dict[str, Any] = {}

    for batch_idx, d in enumerate(documents):
        if not isinstance(d, dict):
            continue

        # Tipi documento del batch corrente — usato per scoring azienda.
        # Cerca SIA dentro sezioni → documenti SIA al top-level (struttura piatta).
        block_tipi: List[str] = []
        sezioni_in_batch = d.get("sezioni") or []
        if isinstance(sezioni_in_batch, list):
            for sez in sezioni_in_batch:
                if not isinstance(sez, dict):
                    continue
                docs_list = sez.get("documenti") or []
                if isinstance(docs_list, list):
                    for doc in docs_list:
                        if isinstance(doc, dict):
                            tipo = str(doc.get("tipo", "")).lower().strip()
                            if tipo:
                                block_tipi.append(tipo)

        # Documento al top-level (struttura "piatta" → 1 doc per batch)
        top_level_doc = _extract_top_level_doc(d)
        if top_level_doc is not None:
            tipo_top = str(top_level_doc.get("tipo", "")).lower().strip()
            if tipo_top:
                block_tipi.append(tipo_top)

        # Meta
        meta = d.get("meta") or d
        if isinstance(meta, dict):
            azienda = meta.get("azienda") or d.get("azienda")
            if isinstance(azienda, dict):
                az_nome = _normalize_company_name(azienda.get("nome"))
                if az_nome:
                    # Scoring V1-style per qualità della fonte (solo per `nome`)
                    score = _score_company_source(block_tipi)
                    candidate = dict(azienda)
                    candidate["nome"] = az_nome
                    azienda_candidates.append((score, candidate))
                    print(
                        f"[V2 PARSER] Batch #{batch_idx}: candidato azienda="
                        f"'{az_nome}' score={score} (tipi={block_tipi[:3]})"
                    )
                # Merge campi secondari (piva/sede/REA/capitale/...) da TUTTI
                # i batch — primo non-vuoto vince. Indipendente dal score.
                for k, v in azienda.items():
                    if k == "nome":
                        continue  # gestito via score
                    if v in (None, "", {}, []):
                        continue
                    if k not in merged_secondary_fields:
                        merged_secondary_fields[k] = v

            indice = meta.get("indice") or d.get("indice")
            if isinstance(indice, list):
                for entry in indice:
                    if isinstance(entry, dict):
                        merged_indice.append(entry)

            audit = meta.get("audit") or d.get("audit")
            if isinstance(audit, dict):
                for k, v in audit.items():
                    if k not in merged_audit and v not in (None, "", {}, []):
                        merged_audit[k] = v

        # Sezioni — struttura annidata
        if isinstance(sezioni_in_batch, list):
            for sez in sezioni_in_batch:
                if not isinstance(sez, dict):
                    continue
                nome = str(sez.get("nome", "")).strip()
                if not nome:
                    continue
                key = nome.upper()
                if key not in sezioni_by_name:
                    sezioni_by_name[key] = {
                        "id": sez.get("id", ""),
                        "nome": nome,
                        "documenti": [],
                    }
                docs = sez.get("documenti")
                if isinstance(docs, list):
                    for doc in docs:
                        norm = _normalize_doc_entry(doc)
                        if norm:
                            sezioni_by_name[key]["documenti"].append(norm)

        # Documento top-level → ricostruisci la sua sezione dal campo `categoria`
        if top_level_doc is not None:
            sec_info = _section_key_from_categoria(top_level_doc.get("categoria"))
            if sec_info is not None:
                sec_id, sec_nome = sec_info
                key = sec_nome.upper()
                if key not in sezioni_by_name:
                    sezioni_by_name[key] = {
                        "id": sec_id,
                        "nome": sec_nome,
                        "documenti": [],
                    }
                sezioni_by_name[key]["documenti"].append(top_level_doc)

    # Selezione finale azienda: nome dal vincitore score, altri campi
    # dal merge accumulativo (best of both worlds vs V1).
    merged_meta_azienda: Dict[str, Any] = {}
    if azienda_candidates:
        azienda_candidates.sort(key=lambda t: t[0], reverse=True)
        best_score, best_azienda = azienda_candidates[0]
        # Parti dai campi accumulati (piva/sede/...) e sovrascrivi solo
        # con quelli del vincitore se ha più info
        merged_meta_azienda = dict(merged_secondary_fields)
        merged_meta_azienda["nome"] = best_azienda.get("nome", "")
        # Aggiungi gli altri campi del vincitore se mancano
        for k, v in best_azienda.items():
            if k == "nome":
                continue
            if v in (None, "", {}, []):
                continue
            if k not in merged_meta_azienda:
                merged_meta_azienda[k] = v
        print(
            f"[V2 PARSER] Nome azienda scelto: "
            f"'{merged_meta_azienda.get('nome', '')}' (score={best_score})"
        )

    # Assembla output finale
    return {
        "meta": {
            "azienda": merged_meta_azienda,
            "indice": merged_indice,
            "audit": merged_audit,
        },
        "sezioni": list(sezioni_by_name.values()),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def extract_company_name(parsed_data: Dict[str, Any]) -> str:
    """
    Estrae il nome azienda dal parsed_data. Fallback a "AZIENDA NON IDENTIFICATA".
    """
    if not isinstance(parsed_data, dict):
        return "AZIENDA NON IDENTIFICATA"
    meta = parsed_data.get("meta") or {}
    azienda = meta.get("azienda") or {}
    if not isinstance(azienda, dict):
        return "AZIENDA NON IDENTIFICATA"
    name = _normalize_company_name(azienda.get("nome"))
    if not name:
        return "AZIENDA NON IDENTIFICATA"
    return name.upper()


def parsing_summary(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot per logging/SSE."""
    if not isinstance(parsed_data, dict):
        return {"sezioni_count": 0, "documenti_total": 0, "company": "n.d."}
    sezioni = parsed_data.get("sezioni") or []
    total_docs = sum(
        len(s.get("documenti", []) or [])
        for s in sezioni if isinstance(s, dict)
    )
    return {
        "sezioni_count": len(sezioni),
        "documenti_total": total_docs,
        "company": extract_company_name(parsed_data),
    }
