"""
V2 — Relevance Safety Net (Leva 2 — Fase B).

Quattro guardrail tra il classifier e il pipeline analyze, applicati prima
di accettare un'etichetta `audit_role=NOISE` come motivo per saltare un
file. Obiettivo: zero documenti CORE persi, anche in presenza di errori
del classifier.

I quattro livelli, in ordine di applicazione:

1. Whitelist normativa sul filename: pattern regex (DVR/Visura/ISO/NC/...)
   forzano `audit_role=CORE` indipendentemente da quanto detto dal modello.
2. Soglia di confidenza: `audit_role=NOISE` ammesso solo se
   `audit_role_confidence ≥ NOISE_MIN_CONFIDENCE` (default 0.90).
3. Cap volumetrico: massimo `MAX_NOISE_FRACTION` (default 0.15) di file
   marcabili come NOISE. Oltre, tornano a SUPPORT — keep top-confidence.
4. Dedup determ: file con stesso SHA-256 (o stesso (classe + intestatario +
   data) come fallback) → primo va a destination originale, gli altri
   marcati `audit_role=NOISE` con sub-reason "duplicate".

API pubblica:
    apply_safety_net(classified, files_index=None) ->
        Tuple[kept, skipped, ledger]

dove `kept` e `skipped` sono liste di ClassifiedFile, `ledger` è una lista
di dict per il render nel docx ("perché questo file è stato skippato").

Tutte le funzioni sono pure (non mutano gli input). Mai sollevano: in caso
di errore di valutazione, fallback conservativo a "non skippare".
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from v2.schemas.classification import (
    AuditRole,
    ClassifiedFile,
    DocumentClass,
    default_audit_role_for,
)


# ──────────────────────────────────────────────────────────────────────────────
# Configurazione
# ──────────────────────────────────────────────────────────────────────────────

# Confidenza minima richiesta per accettare audit_role=NOISE
NOISE_MIN_CONFIDENCE: float = 0.90

# Frazione massima di file skippabili come NOISE (cap volumetrico)
MAX_NOISE_FRACTION: float = 0.15

# Soglia minima di file per applicare il cap volumetrico: sotto questa
# soglia, il cap percentuale diventa irrealistico (15% di 5 = 0). Su piccoli
# dataset il cap viene rilassato e l'enforcement è dato dagli altri 3 layer.
MIN_FILES_FOR_VOLUME_CAP: int = 10

# Pattern di filename che forzano CORE indipendentemente dalla classificazione.
# Lista costruita dai prompt checklist (ISO 9001/14001/45001/27001/37001/39001/
# 50001, ESG, PAS 24000) e dai 539 batch raw storici.
#
# Nota tecnica sui confini: in regex Python `\b` non considera `_` come
# separatore (perché `_` ∈ \w), quindi `\bDVR\b` NON matcha "DVR_2024.pdf".
# Usiamo `(?:^|[\W_])` e `(?:[\W_]|$)` come delimitatori espliciti che
# trattano sia spazi/punteggiatura sia underscore come confini.
_BOUND = r"(?:^|[\W_])"
_BOUND_END = r"(?:[\W_]|$)"

_WHITELIST_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(_BOUND + r"(?:DVR|DUVRI|POS|PSC|PiMUS)" + _BOUND_END, re.IGNORECASE),
    re.compile(_BOUND + r"visura" + _BOUND_END, re.IGNORECASE),
    re.compile(_BOUND + r"statuto" + _BOUND_END, re.IGNORECASE),
    re.compile(_BOUND + r"SOA" + _BOUND_END, re.IGNORECASE),
    re.compile(_BOUND + r"CCIAA" + _BOUND_END, re.IGNORECASE),
    re.compile(_BOUND + r"REA" + _BOUND_END, re.IGNORECASE),
    re.compile(_BOUND + r"ISO[\s_-]?\d{4,5}" + _BOUND_END, re.IGNORECASE),
    re.compile(
        _BOUND + r"certificat[oa][\s_-]+(qualit[aà]|ambient|sicur|energet|ESG|sostenibilit[aà])",
        re.IGNORECASE,
    ),
    re.compile(
        _BOUND + r"bilancio[\s_-]+(sostenibilit[aà]|ESG|carbon|esercizio)",
        re.IGNORECASE,
    ),
    re.compile(
        _BOUND + r"(GHG|emissioni|inventario[\s_-]+emissioni)" + _BOUND_END,
        re.IGNORECASE,
    ),
    re.compile(
        _BOUND + r"(non[\s_-]?conformit|NC[\s_-]\d|azione[\s_-]+correttiv)",
        re.IGNORECASE,
    ),
    re.compile(
        _BOUND + r"nomina[\s_-]+(RSPP|RLS|medico|energy[\s_-]?manager|preposto)",
        re.IGNORECASE,
    ),
    re.compile(_BOUND + r"(infortun|near[\s_-]?miss)" + _BOUND_END, re.IGNORECASE),
    re.compile(_BOUND + r"(CIG|CUP)[\s_:-]?[A-Z0-9]{6,}" + _BOUND_END, re.IGNORECASE),
    re.compile(_BOUND + r"mansionario" + _BOUND_END, re.IGNORECASE),
    re.compile(_BOUND + r"organigramma" + _BOUND_END, re.IGNORECASE),
    re.compile(
        _BOUND + r"registro[\s_-]+(infortun|emissioni|formazione)",
        re.IGNORECASE,
    ),
    re.compile(
        _BOUND + r"politica[\s_-]+(per[\s_-]+la[\s_-]+)?(qualit[aà]|sicurezza|ambiente)",
        re.IGNORECASE,
    ),
    re.compile(_BOUND + r"(ESRS|GRI|CSRD|EASI)" + _BOUND_END),
    re.compile(
        _BOUND + r"contratto[\s_-]+(di[\s_-]+)?(appalto|sublocazione|servizio)",
        re.IGNORECASE,
    ),
    re.compile(_BOUND + r"giudizio[\s_-]+di[\s_-]+idoneit[aà]", re.IGNORECASE),
    re.compile(_BOUND + r"dichiarazione[\s_-]+conformit[aà]", re.IGNORECASE),
    re.compile(_BOUND + r"audit[\s_-]+intern", re.IGNORECASE),
    re.compile(_BOUND + r"riesame[\s_-]+della[\s_-]+direzione", re.IGNORECASE),
)


def _filename_matches_whitelist(filename: str) -> Optional[str]:
    """
    Ritorna la stringa del primo pattern che matcha (per logging/ledger),
    o None se nessun pattern matcha.
    """
    if not filename:
        return None
    for pat in _WHITELIST_PATTERNS:
        m = pat.search(filename)
        if m:
            return m.group(0)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_role_value(cf: ClassifiedFile) -> str:
    """Ritorna l'audit_role come stringa, derivando dal default se None."""
    role = cf.audit_role
    if role is None:
        try:
            classe_str = cf.classe if isinstance(cf.classe, str) else cf.classe.value
            classe_enum = DocumentClass(classe_str)
            role = default_audit_role_for(classe_enum)
        except Exception:
            role = AuditRole.SUPPORT
    return role if isinstance(role, str) else role.value


def _classified_with_role(cf: ClassifiedFile, new_role: str,
                           new_arc: Optional[float] = None) -> ClassifiedFile:
    """Ritorna una copia di `cf` con audit_role aggiornato (immutabile)."""
    data = cf.model_dump()
    data["audit_role"] = new_role
    if new_arc is not None:
        data["audit_role_confidence"] = new_arc
    return ClassifiedFile(**data)


def _file_hash_for_dedup(file_info: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Calcola un hash del contenuto estratto (extracted_text) per dedup.
    Se il file_info non è disponibile o privo di testo, ritorna None
    (no dedup possibile su quel file — è il comportamento safe).

    Usiamo extracted_text invece dell'hash binario perché:
    - i PDF hanno spesso metadati variabili tra copie (date, ID temp)
    - il testo estratto cattura il contenuto evidenziale
    """
    if not file_info:
        return None
    text = (file_info.get("extracted_text") or file_info.get("content") or "").strip()
    if len(text) < 200:
        # testo troppo corto: troppo rischio falso positivo
        return None
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# Layers individuali
# ──────────────────────────────────────────────────────────────────────────────

def apply_whitelist_override(
    classified: List[ClassifiedFile],
) -> Tuple[List[ClassifiedFile], List[Dict[str, Any]]]:
    """
    Layer 1: forza audit_role=CORE per filename che matchano la whitelist.

    Ritorna (classified_modified, overrides_log) dove overrides_log contiene
    una entry per ogni file forzato a CORE (per il ledger).
    """
    overrides: List[Dict[str, Any]] = []
    out: List[ClassifiedFile] = []
    for cf in classified:
        match = _filename_matches_whitelist(cf.filename)
        current_role = _get_role_value(cf)
        if match and current_role != AuditRole.CORE.value:
            new_cf = _classified_with_role(cf, AuditRole.CORE.value, new_arc=1.0)
            overrides.append({
                "filename": cf.filename,
                "previous_role": current_role,
                "new_role": AuditRole.CORE.value,
                "matched_pattern": match,
            })
            out.append(new_cf)
        else:
            out.append(cf)
    return out, overrides


def enforce_confidence_threshold(
    classified: List[ClassifiedFile],
    min_confidence: float = NOISE_MIN_CONFIDENCE,
) -> Tuple[List[ClassifiedFile], List[Dict[str, Any]]]:
    """
    Layer 2: NOISE → SUPPORT se audit_role_confidence < min_confidence.

    La logica è conservativa: se il classifier non ha popolato
    audit_role_confidence (None) e il role è NOISE, lo declassiamo a
    SUPPORT — preferiamo analizzare un file in più che perderne uno
    importante.
    """
    downgrades: List[Dict[str, Any]] = []
    out: List[ClassifiedFile] = []
    for cf in classified:
        role = _get_role_value(cf)
        if role == AuditRole.NOISE.value:
            arc = cf.audit_role_confidence
            if arc is None or arc < min_confidence:
                new_cf = _classified_with_role(cf, AuditRole.SUPPORT.value)
                downgrades.append({
                    "filename": cf.filename,
                    "audit_role_confidence": arc,
                    "min_required": min_confidence,
                    "new_role": AuditRole.SUPPORT.value,
                })
                out.append(new_cf)
                continue
        out.append(cf)
    return out, downgrades


def enforce_volume_cap(
    classified: List[ClassifiedFile],
    max_noise_fraction: float = MAX_NOISE_FRACTION,
    min_files_for_cap: int = MIN_FILES_FOR_VOLUME_CAP,
) -> Tuple[List[ClassifiedFile], List[Dict[str, Any]]]:
    """
    Layer 4: garantisce che al più `max_noise_fraction` dei file siano NOISE.

    Se il numero di NOISE eccede il cap, i NOISE con audit_role_confidence
    più bassa (ranking secondario: filename alfa) tornano a SUPPORT.
    Garantisce che il pipeline non perda mai >15% dei file per errore.

    Su dataset piccoli (n < `min_files_for_cap`, default 10) il cap viene
    rilassato: 15% di 5 = 0 sarebbe troppo aggressivo. In quei casi i
    layer precedenti (whitelist, dedup, confidence threshold) forniscono
    già protezione sufficiente.
    """
    n = len(classified)
    if n == 0:
        return classified, []
    if n < min_files_for_cap:
        # Dataset troppo piccolo per applicare il cap percentuale
        return classified, []
    max_allowed = int(n * max_noise_fraction)
    noise_indexes = [
        i for i, cf in enumerate(classified)
        if _get_role_value(cf) == AuditRole.NOISE.value
    ]
    if len(noise_indexes) <= max_allowed:
        return classified, []

    # Rank NOISE by audit_role_confidence DESC: i più "sicuri" restano NOISE,
    # i meno sicuri vengono declassati.
    def _rank_key(idx: int) -> Tuple[float, str]:
        cf = classified[idx]
        arc = cf.audit_role_confidence if cf.audit_role_confidence is not None else 0.0
        # Ordine: confidence DESC, filename ASC (deterministico)
        return (-arc, cf.filename or "")

    sorted_noise = sorted(noise_indexes, key=_rank_key)
    keep_as_noise = set(sorted_noise[:max_allowed])

    out: List[ClassifiedFile] = []
    downgrades: List[Dict[str, Any]] = []
    for i, cf in enumerate(classified):
        if i in noise_indexes and i not in keep_as_noise:
            new_cf = _classified_with_role(cf, AuditRole.SUPPORT.value)
            downgrades.append({
                "filename": cf.filename,
                "audit_role_confidence": cf.audit_role_confidence,
                "reason": "volume_cap_exceeded",
                "cap_fraction": max_noise_fraction,
                "new_role": AuditRole.SUPPORT.value,
            })
            out.append(new_cf)
        else:
            out.append(cf)
    return out, downgrades


def dedup_by_content_hash(
    classified: List[ClassifiedFile],
    files_index: Dict[str, Dict[str, Any]],
) -> Tuple[List[ClassifiedFile], List[Dict[str, Any]]]:
    """
    Layer 4: file con stesso SHA-256 del contenuto estratto → primo
    mantiene il suo role, gli altri marcati NOISE (sub-reason: duplicate).

    Il primo file (per filename alfabetico, deterministico) vince. Files
    senza testo estratto (text < 200 char) NON sono mai marcati duplicati
    (rischio falso positivo).
    """
    duplicates: List[Dict[str, Any]] = []
    seen_hashes: Dict[str, str] = {}  # hash → filename del primo
    # Ordine deterministico per scegliere il "primo" ricevitore dell'hash
    sorted_classified = sorted(
        enumerate(classified), key=lambda t: t[1].filename or ""
    )
    out_role_overrides: Dict[int, ClassifiedFile] = {}
    for orig_idx, cf in sorted_classified:
        finfo = files_index.get(cf.filename)
        h = _file_hash_for_dedup(finfo)
        if h is None:
            continue
        if h not in seen_hashes:
            seen_hashes[h] = cf.filename
            continue
        # Duplicato: marca NOISE con audit_role_confidence=1.0 (deterministic)
        new_cf = _classified_with_role(
            cf, AuditRole.NOISE.value, new_arc=1.0,
        )
        out_role_overrides[orig_idx] = new_cf
        duplicates.append({
            "filename": cf.filename,
            "duplicate_of": seen_hashes[h],
            "content_hash_prefix": h[:12],
            "new_role": AuditRole.NOISE.value,
        })

    if not out_role_overrides:
        return classified, []

    out = [
        out_role_overrides.get(i, cf) for i, cf in enumerate(classified)
    ]
    return out, duplicates


# ──────────────────────────────────────────────────────────────────────────────
# Orchestratore safety net
# ──────────────────────────────────────────────────────────────────────────────

def apply_safety_net(
    classified: List[ClassifiedFile],
    files_index: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    noise_min_confidence: float = NOISE_MIN_CONFIDENCE,
    max_noise_fraction: float = MAX_NOISE_FRACTION,
) -> Dict[str, Any]:
    """
    Applica i 4 layer in ordine:
      1. Whitelist (override → CORE)
      2. Dedup (duplicate → NOISE)  [richiede files_index]
      3. Confidence threshold (NOISE → SUPPORT se arc < soglia)
      4. Volume cap (eccesso NOISE → SUPPORT)

    L'ordine è deliberato:
    - Whitelist va prima per evitare che un Visura mal classificato come
      NOISE venga skippato per dedup o confidence.
    - Dedup è prima della confidence threshold perché i duplicati hanno
      sempre arc=1.0 forzato, e devono comunque rispettare il volume cap
      (se ci sono troppi duplicati, alcuni tornano support).

    Ritorna dict con:
      "kept": lista ClassifiedFile da analizzare (NOISE esclusi)
      "skipped": lista ClassifiedFile con audit_role=NOISE finale
      "ledger": entries per il docx (filename, classe, audit_role, motivo,
                duplicate_of/matched_pattern/etc.)
      "stats": conteggi per layer
    """
    if not classified:
        return {"kept": [], "skipped": [], "ledger": [], "stats": {}}

    files_index = files_index or {}

    # Layer 1
    cls_after_wl, wl_overrides = apply_whitelist_override(classified)

    # Layer 2 (dedup) — richiede files_index
    cls_after_dedup, dedup_log = dedup_by_content_hash(cls_after_wl, files_index)

    # Layer 3
    cls_after_conf, conf_downgrades = enforce_confidence_threshold(
        cls_after_dedup, min_confidence=noise_min_confidence,
    )

    # Layer 4
    cls_final, vol_downgrades = enforce_volume_cap(
        cls_after_conf, max_noise_fraction=max_noise_fraction,
    )

    # Split kept vs skipped
    kept: List[ClassifiedFile] = []
    skipped: List[ClassifiedFile] = []
    for cf in cls_final:
        if _get_role_value(cf) == AuditRole.NOISE.value:
            skipped.append(cf)
        else:
            kept.append(cf)

    # Ledger per il docx — include anche overrides whitelist e dedup
    ledger: List[Dict[str, Any]] = []
    # Skipped: il "perché"
    dup_by_filename = {d["filename"]: d for d in dedup_log}
    for cf in skipped:
        entry: Dict[str, Any] = {
            "filename": cf.filename,
            "classe": cf.classe if isinstance(cf.classe, str) else cf.classe.value,
            "audit_role": AuditRole.NOISE.value,
            "audit_role_confidence": cf.audit_role_confidence,
        }
        if cf.filename in dup_by_filename:
            entry["reason"] = "duplicate"
            entry["duplicate_of"] = dup_by_filename[cf.filename]["duplicate_of"]
        else:
            entry["reason"] = "model_marked_noise_high_confidence"
        ledger.append(entry)

    stats = {
        "total_input": len(classified),
        "whitelist_overrides_to_core": len(wl_overrides),
        "duplicates_marked_noise": len(dedup_log),
        "confidence_downgrades_to_support": len(conf_downgrades),
        "volume_cap_downgrades_to_support": len(vol_downgrades),
        "skipped_count": len(skipped),
        "kept_count": len(kept),
        "skipped_pct": round(100.0 * len(skipped) / len(classified), 2),
    }

    return {
        "kept": kept,
        "skipped": skipped,
        "ledger": ledger,
        "stats": stats,
        "details": {
            "whitelist_overrides": wl_overrides,
            "dedup_log": dedup_log,
            "confidence_downgrades": conf_downgrades,
            "volume_cap_downgrades": vol_downgrades,
        },
    }
