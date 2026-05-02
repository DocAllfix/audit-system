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


def _safe_load_yaml(text: str) -> Any:
    """
    yaml.safe_load tollerante con auto-recovery su errori comuni:
    1. Tentativo standard
    2. Se fallisce per block-scalar mal indentato (tabelle Markdown
       all'interno di campi YAML), tenta sanitization e riprova
    3. Se ancora fallisce → None
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

    print(f"[V2 YAML] safe_load fallito definitivamente: {first_err}")
    return None


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
    if not text or not HAS_YAML:
        return {"meta": {"azienda": {}, "indice": [], "audit": {}}, "sezioni": []}

    cleaned = _strip_yaml_fences(text)
    if not cleaned:
        return {"meta": {"azienda": {}, "indice": [], "audit": {}}, "sezioni": []}

    # Split manuale per `\n---\n` separator: più tollerante di safe_load_all
    # (un batch corrotto non blocca il parsing degli altri)
    chunks = _split_by_separator(cleaned)
    documents: List[Any] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        d = _safe_load_yaml(chunk)
        if isinstance(d, dict):
            documents.append(d)

    # Aggrega i documenti
    merged_meta_azienda: Dict[str, Any] = {}
    merged_indice: List[Dict[str, Any]] = []
    merged_audit: Dict[str, Any] = {}
    sezioni_by_name: Dict[str, Dict[str, Any]] = {}

    for d in documents:
        if not isinstance(d, dict):
            continue

        # Meta
        meta = d.get("meta") or d  # alcuni batch potrebbero non wrappare in 'meta'
        if isinstance(meta, dict):
            azienda = meta.get("azienda") or d.get("azienda")
            if isinstance(azienda, dict):
                # Merge campi solo se mancanti o vuoti in merged
                for k, v in azienda.items():
                    if v in (None, "", {}, []):
                        continue
                    if k == "nome":
                        cleaned_name = _normalize_company_name(v)
                        if cleaned_name and not merged_meta_azienda.get("nome"):
                            merged_meta_azienda["nome"] = cleaned_name
                    elif k not in merged_meta_azienda:
                        merged_meta_azienda[k] = v

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

        # Sezioni
        sezioni = d.get("sezioni")
        if isinstance(sezioni, list):
            for sez in sezioni:
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
                # Concat documenti
                docs = sez.get("documenti")
                if isinstance(docs, list):
                    for doc in docs:
                        norm = _normalize_doc_entry(doc)
                        if norm:
                            sezioni_by_name[key]["documenti"].append(norm)

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
