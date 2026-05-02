"""
V2 — Pipeline Orchestrator (Fase 8).

Cuce insieme le Fasi 1-7 in un'unica pipeline end-to-end:
    ZIP → estrazione → triage → classifier → cache prompt → OCR → analyze
        → parse YAML → builder docx incrementale → merge → output

Caratteristiche:
- API uniforme: process_zip_v2(zip_bytes, api_key, ...) -> dict
- SSE typed events emessi attraverso ogni fase (Fase 6)
- Token meter integrato (Fase 7.5)
- Dry-run mode: process_zip_v2(..., dry_run=True) → nessuna chiamata Gemini,
  pipeline produce comunque docx valido per smoke E2E
- Cleanup automatico delle risorse (sezioni partial, OCR manifest, file
  uploaded a Gemini Files API)
- Mai eccezione propagata: errori finiscono in event SSE error + return dict
  con success=False
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Stub Fase 0 — mantenuto per compat con /api/v2/health
# ──────────────────────────────────────────────────────────────────────────────

def process_v2_stub() -> Dict[str, Any]:
    """Stub originale (Fase 0). Ora la pipeline reale è process_zip_v2."""
    return {
        "status": "v2_stub_alive",
        "version": "0.8.0-alpha",
        "phase": "8_orchestrator",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": "Pipeline V2 orchestrator attivo. Endpoint reale: /api/v2/report/process",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Auto-tuning leve V2 (Leva 2C compact + Leva 4 model mix)
# ──────────────────────────────────────────────────────────────────────────────
#
# Le leve compact_mode (Fase 2C) e model_mix (Leva 4) ottimizzano i costi
# consolidando i documenti AGGREGABLE in batch dedicati con tier MINIMO +
# flash-lite. Sono efficaci solo quando il volume aggregable è alto.
#
# Su pratiche piccole (es. ZIP ISO 27001 con poche decine di file dove ogni
# documento è una procedura SGSI individuale), il consolidamento penalizza la
# qualità dell'output (vedi confronto SIRIH 28 MB: V1 93 schede vs V2 con leve
# attive solo 30 schede).
#
# La logica auto-tuning:
# - Se classified contiene >= MIN_AGGREGABLE_FOR_COMPACT file con audit_role
#   AGGREGABLE → leve abilitate (comportamento ottimizzato)
# - Altrimenti → leve disabilitate (comportamento V1-like, qualità preservata)
#
# Override manuale via env var:
#   V2_LEVA2_AGGREGABLE_COMPACT={true|false|auto}  (default "auto")
#   V2_LEVA4_MODEL_MIX={true|false|auto}            (default "auto")

# Soglia minima di file AGGREGABLE per attivazione auto delle leve compact/lite
DEFAULT_MIN_AGGREGABLE_FOR_COMPACT = 50


def _resolve_leva_flag(env_name: str, auto_default: bool) -> Tuple[bool, str]:
    """
    Risolve flag leva tri-stato: 'true' / 'false' / 'auto' (default).

    Args:
        env_name: nome variabile ambiente (es. "V2_LEVA2_AGGREGABLE_COMPACT")
        auto_default: valore di default quando il flag è 'auto' o non settato

    Returns:
        (enabled, source) dove source ∈ {"manual_on", "manual_off", "auto_on",
        "auto_off"}. Utile per logging.
    """
    raw = os.environ.get(env_name, "auto").strip().lower()
    if raw == "true":
        return (True, "manual_on")
    if raw == "false":
        return (False, "manual_off")
    # "auto" o valore non riconosciuto → applica auto_default
    return (auto_default, "auto_on" if auto_default else "auto_off")


def _count_aggregable_documents(
    documents: List[Dict[str, Any]],
    role_by_filename: Dict[str, str],
) -> int:
    """
    Conta i documenti effettivamente eligibili per il compact_mode.

    Un documento è "aggregable" se:
    - è presente nei `documents` (post triage + OCR + dedup safety net)
    - il suo audit_role mappato è "AGGREGABLE"

    Documenti con role None, CORE, SUPPORT, NOISE non contano.
    """
    n = 0
    for d in documents:
        fname = d.get("filename")
        if fname and role_by_filename.get(fname) == "AGGREGABLE":
            n += 1
    return n


def _build_role_by_filename(
    classified: List[Any],
    skipped_filenames: set,
) -> Dict[str, str]:
    """
    Costruisce mappa filename → audit_role (stringa) dai classified, escludendo
    i file già marcati come skipped dalla safety net (Leva 2 Fase B).

    Quando audit_role è None nel ClassifiedFile, viene derivato dal default
    deterministico (CLASS_TO_DEFAULT_ROLE in schemas/classification.py).
    """
    out: Dict[str, str] = {}
    if not classified:
        return out
    from v2.schemas.classification import (
        DocumentClass,
        default_audit_role_for,
    )
    for cf in classified:
        if cf.filename in skipped_filenames:
            continue
        role = cf.audit_role
        if role is None:
            try:
                classe_str = cf.classe if isinstance(cf.classe, str) else cf.classe.value
                role = default_audit_role_for(DocumentClass(classe_str)).value
            except Exception:
                role = "SUPPORT"
        role_str = role if isinstance(role, str) else role.value
        out[cf.filename] = role_str
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Smart batching (replica V1 First Fit Decreasing)
# ──────────────────────────────────────────────────────────────────────────────

def _create_smart_batches(
    documents: List[Dict[str, Any]],
    max_files: int = 4,
    max_chars: int = 50_000,
) -> List[List[Dict[str, Any]]]:
    """
    First Fit Decreasing per char count, replica V1 senza importare da V1.
    Documents con `content` (o `extracted_text`) come testo da contare.
    """
    def _content_len(d: Dict[str, Any]) -> int:
        return len(d.get("content") or d.get("extracted_text") or "")

    sorted_docs = sorted(documents, key=_content_len, reverse=True)
    batches: List[List[Dict[str, Any]]] = []
    batch_chars: List[int] = []

    for doc in sorted_docs:
        cl = _content_len(doc)
        placed = False
        for i, batch in enumerate(batches):
            if len(batch) < max_files and (batch_chars[i] + cl) <= max_chars:
                batch.append(doc)
                batch_chars[i] += cl
                placed = True
                break
        if not placed:
            batches.append([doc])
            batch_chars.append(cl)
    return batches


# ──────────────────────────────────────────────────────────────────────────────
# Dry-run mock data
# ──────────────────────────────────────────────────────────────────────────────

_DRY_RUN_YAML = """
meta:
  azienda:
    nome: "DRY RUN COMPANY SRL"
    piva: "00000000000"
    sede: "Via Test 1"
  audit:
    data_estrazione: "01/05/2026"
  indice:
    - {n: 1, tipo: "Visura Camerale", titolo: "Visura demo", categoria: "08 Legale"}

sezioni:
  - id: "08"
    nome: "08 · DOCUMENTAZIONE LEGALE E SOCIETARIA"
    documenti:
      - tipo: "Visura Camerale"
        titolo: "Visura demo"
        categoria: "08 · LEGALE"
        riferimento: "DRY-RUN"
        data_doc: "01/01/2025"
        emesso_da: "DRY-RUN"
        soggetto: "DRY RUN COMPANY SRL"
"""


# ──────────────────────────────────────────────────────────────────────────────
# Leva 2 — dry-run audit_role persistence
# ──────────────────────────────────────────────────────────────────────────────

def _persist_audit_role_dryrun(
    session_id: str,
    classified: List[Any],
    classify_metrics: Dict[str, Any],
) -> None:
    """
    Persiste in `temp/audit_role_dryrun/{session_id}.json` la distribuzione
    audit_role del classifier + l'elenco dei candidati NOISE con i loro
    metadati. Non altera alcun comportamento del pipeline (Fase A è solo
    osservazione).
    """
    import json as _json

    base_dir = Path(__file__).resolve().parent.parent.parent / "temp" / "audit_role_dryrun"
    base_dir.mkdir(parents=True, exist_ok=True)

    candidates_noise: List[Dict[str, Any]] = []
    candidates_aggregable: List[Dict[str, Any]] = []
    candidates_support: List[Dict[str, Any]] = []
    role_with_low_arc: List[Dict[str, Any]] = []
    for cf in classified:
        try:
            classe_str = cf.classe if isinstance(cf.classe, str) else cf.classe.value
            role = cf.audit_role
            if role is None:
                from v2.schemas.classification import (
                    DocumentClass,
                    default_audit_role_for,
                )
                role = default_audit_role_for(DocumentClass(classe_str)).value
            role_str = role if isinstance(role, str) else role.value
            arc = cf.audit_role_confidence
            entry = {
                "filename": cf.filename,
                "classe": classe_str,
                "audit_role": role_str,
                "audit_role_confidence": arc,
                "confidence": cf.confidence,
            }
            if role_str == "NOISE":
                candidates_noise.append(entry)
                if arc is None or arc < 0.90:
                    role_with_low_arc.append(entry)
            elif role_str == "AGGREGABLE":
                candidates_aggregable.append(entry)
            elif role_str == "SUPPORT":
                candidates_support.append(entry)
        except Exception:
            continue

    payload = {
        "session_id": session_id,
        "summary": classify_metrics,
        "noise_candidates": candidates_noise,
        "aggregable_candidates": candidates_aggregable,
        "support_candidates": candidates_support,
        "noise_with_low_audit_role_confidence": role_with_low_arc,
    }
    out = base_dir / f"{session_id}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline orchestrator
# ──────────────────────────────────────────────────────────────────────────────

def process_zip_v2(
    zip_bytes: bytes,
    session_id: str,
    api_key: Optional[str] = None,
    emitter=None,
    dry_run: bool = False,
    output_dir: Optional[Path] = None,
    _client=None,  # injectable per test
) -> Dict[str, Any]:
    """
    Pipeline V2 completa.

    Args:
        zip_bytes: contenuto ZIP da elaborare
        session_id: identificatore univoco run (alphanumerico_-)
        api_key: chiave Gemini. Se None, legge da env GEMINI_API_KEY.
                 In dry_run è ignorata.
        emitter: SSEEmitter istanziato dal caller (None per uso programmatico)
        dry_run: se True, NESSUNA chiamata Gemini reale; usa mock pre-canned
        output_dir: directory per il docx finale (default temp/v2_output/)
        _client: genai.Client injectable (per test); altrimenti costruito da api_key

    Returns:
        Dict con success/error e metadati (output_path, company_name, stats).
        Mai eccezione propagata.
    """
    from v2 import token_meter
    from v2.docx_merger import merge_session_sections
    from v2.incremental_docx_builder import (
        build_all_sections, builder_summary, cleanup_session_sections,
    )
    from v2.schemas.events import (
        DoneEvent, ErrorKind, PipelinePhase,
    )
    from v2.yaml_parser import (
        extract_company_name,
        get_last_parse_failures,
        parse_aggregated_yaml,
    )
    from v2.zip_extractor import (
        cleanup_extraction, extract_summary, extract_zip_bytes,
    )

    pipeline_start = time.monotonic()

    # Default output dir
    if output_dir is None:
        webapp_dir = Path(__file__).resolve().parent.parent
        output_dir = webapp_dir.parent / "temp" / "v2_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # No-op emitter se non fornito (rende la chiamata sicura senza SSE)
    class _NoopEmitter:
        def __getattr__(self, name):
            return lambda *a, **kw: True
        session_id = ""

    if emitter is None:
        emitter = _NoopEmitter()
        emitter.session_id = session_id  # type: ignore

    # ── Validazione iniziale ─────────────────────────────────────────────
    if not isinstance(zip_bytes, (bytes, bytearray)) or not zip_bytes:
        emitter.emit_error(ErrorKind.UNKNOWN, "zip_bytes vuoto o non bytes")
        return {"success": False, "error": "invalid_zip_bytes"}

    # ── FASE: ingestion (estrazione ZIP) ─────────────────────────────────
    extract_dir = None
    files: List[Dict[str, Any]] = []
    try:
        emitter.emit_phase_start(PipelinePhase.INGESTION)
        files, extract_dir = extract_zip_bytes(zip_bytes, session_id)
        ext_summary = extract_summary(files)
        emitter.emit_phase_end(
            PipelinePhase.INGESTION,
            duration_seconds=round(time.monotonic() - pipeline_start, 2),
            metrics=ext_summary,
        )
        if not files:
            emitter.emit_error(ErrorKind.UNKNOWN, "ZIP vuoto o nessun file estratto")
            return {"success": False, "error": "empty_zip"}
    except ValueError as e:
        emitter.emit_error(ErrorKind.UNKNOWN, f"estrazione_zip_fallita: {e}")
        return {"success": False, "error": f"extraction_failed: {e}"}
    except Exception as e:
        emitter.emit_error(ErrorKind.UNKNOWN, f"errore_imprevisto: {e}")
        return {"success": False, "error": f"unexpected_extraction: {e}"}

    # ── Client Gemini (skip in dry_run) ─────────────────────────────────
    client = _client
    if not dry_run and client is None:
        try:
            from v2.genai_factory_v2 import create_genai_client_v2
            client = create_genai_client_v2(api_key=api_key)
        except Exception as e:
            emitter.emit_error(ErrorKind.API_AUTH, f"client_creation: {e}")
            cleanup_extraction(extract_dir)
            return {"success": False, "error": f"no_client: {e}"}

    # ── FASE: triage (Fase 1) ────────────────────────────────────────────
    from v2.file_triage import triage_files, triage_summary
    phase_start = time.monotonic()
    emitter.emit_phase_start(PipelinePhase.TRIAGE, total_items=len(files))
    triaged = triage_files(files)
    triage_sum = triage_summary(triaged)
    emitter.emit_phase_end(
        PipelinePhase.TRIAGE,
        duration_seconds=round(time.monotonic() - phase_start, 2),
        metrics=triage_sum,
    )

    # ── FASE: estrazione testo non-PDF (Limitazione 1) ──────────────────
    # Per file docx/xlsx/txt/etc., estraggo testo qui prima del classifier
    from v2.text_handlers import extract_text_for_category
    non_pdf_files = triaged.get("non_pdf", [])
    non_pdf_with_text: List[Dict[str, Any]] = []
    for f in non_pdf_files:
        text, method = extract_text_for_category(f)
        if text and len(text.strip()) >= 10:
            f["extracted_text"] = text
            f["extraction_method"] = method
            non_pdf_with_text.append(f)
        else:
            # Niente testo estraibile → resta "non_pdf" senza contenuto
            f["extraction_method"] = method or "unsupported_format"

    # ── FASE: classify (Fase 2) ──────────────────────────────────────────
    # Tutti i file con o senza testo (anche pre-OCR) vengono classificati
    files_for_classify = (
        triaged.get("native_text", [])
        + triaged.get("needs_ocr", [])
        + non_pdf_with_text
    )

    classified: List = []
    if files_for_classify and not dry_run:
        from v2.document_classifier import classify_files_batch, classifier_summary
        phase_start = time.monotonic()
        emitter.emit_phase_start(PipelinePhase.CLASSIFY, total_items=len(files_for_classify))
        try:
            classified = classify_files_batch(
                files_for_classify,
                api_key=api_key,
                _client=client,
                meter_session_id=session_id,
            )
        except Exception as e:
            emitter.emit_error(ErrorKind.UNKNOWN, f"classifier_error: {e}")
            classified = []
        classify_metrics = classifier_summary(classified) if classified else {}
        emitter.emit_phase_end(
            PipelinePhase.CLASSIFY,
            duration_seconds=round(time.monotonic() - phase_start, 2),
            metrics=classify_metrics,
        )

        # Leva 2 — Fase A (dry-run audit_role): persisti la distribuzione e
        # i candidati NOISE per ispezione successiva. NIENTE filtraggio attivo.
        if classified:
            try:
                _persist_audit_role_dryrun(session_id, classified, classify_metrics)
            except Exception as e:
                print(f"[V2 PIPELINE] dry-run audit_role persist fallito: {e}")

    # ── FASE: OCR (Fase 4) ───────────────────────────────────────────────
    needs_ocr_files = triaged.get("needs_ocr", [])
    ocr_results: List = []
    if needs_ocr_files and not dry_run:
        from v2.gemini_ocr_v2 import ocr_extract_files, ocr_summary
        phase_start = time.monotonic()
        emitter.emit_phase_start(PipelinePhase.OCR, total_items=len(needs_ocr_files))
        try:
            ocr_results = ocr_extract_files(
                client,
                needs_ocr_files,
                session_id=session_id,
                cleanup_after=True,
                meter_session_id=session_id,
            )
            # Aggiorna i file con il testo estratto
            ocr_text_by_filename = {
                r.filename: r.text for r in ocr_results if r.success
            }
            for f in needs_ocr_files:
                if f["filename"] in ocr_text_by_filename:
                    f["extracted_text"] = ocr_text_by_filename[f["filename"]]
        except Exception as e:
            emitter.emit_error(ErrorKind.OCR_FAILED, f"ocr_pipeline: {e}")
        emitter.emit_phase_end(
            PipelinePhase.OCR,
            duration_seconds=round(time.monotonic() - phase_start, 2),
            metrics=ocr_summary(ocr_results) if ocr_results else {},
        )

    # ── Leva 2 Fase B: applica safety net ai classified ────────────────
    # Filtra i file marcati audit_role=NOISE (con 4 layer di safety net) PRIMA
    # di costruire i documents per analyze. Attivata via env var
    # `V2_LEVA2_SKIP_NOISE=true`. Quando spenta, comportamento invariato.
    skipped_filenames: set = set()
    relevance_ledger: List[Dict[str, Any]] = []
    relevance_stats: Dict[str, Any] = {}
    if (
        classified
        and os.environ.get("V2_LEVA2_SKIP_NOISE", "false").lower() == "true"
        and not dry_run
    ):
        from v2.relevance_safetynet import apply_safety_net

        # files_index serve al dedup hash: mappa filename → file_info con
        # extracted_text. Lo costruiamo dai 3 set di file processati.
        files_index = {
            f["filename"]: f
            for f in (triaged.get("native_text", []) + needs_ocr_files + non_pdf_with_text)
        }
        sn_result = apply_safety_net(classified, files_index)
        skipped_filenames = {cf.filename for cf in sn_result["skipped"]}
        relevance_ledger = sn_result["ledger"]
        relevance_stats = sn_result["stats"]
        if skipped_filenames:
            print(
                f"[V2 PIPELINE] Leva 2 Fase B: {len(skipped_filenames)} file "
                f"marcati NOISE e skippati (cap {relevance_stats.get('skipped_pct', 0)}%). "
                f"Whitelist override: {relevance_stats.get('whitelist_overrides_to_core', 0)}, "
                f"dedup: {relevance_stats.get('duplicates_marked_noise', 0)}"
            )
        # Persisti il ledger su disco (il rendering nel docx arriverà in Fase C)
        try:
            import json as _json
            ledger_dir = Path(__file__).resolve().parent.parent.parent / "temp" / "relevance_ledger"
            ledger_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "session_id": session_id,
                "stats": relevance_stats,
                "ledger": relevance_ledger,
                "details": sn_result.get("details", {}),
            }
            out_path = ledger_dir / f"{session_id}.json"
            tmp = out_path.with_suffix(".json.tmp")
            tmp.write_text(_json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, out_path)
        except Exception as e:
            print(f"[V2 PIPELINE] relevance_ledger persist fallito: {e}")

    # ── Costruisci documents finali per analyze ─────────────────────────
    # Includiamo tutti i file con extracted_text non vuoto:
    # PDF nativi + OCR PDF + non-PDF (Word, Excel, ecc.)
    # Esclusi: file in skipped_filenames (Leva 2 Fase B).
    documents = []
    for f in (triaged.get("native_text", []) + needs_ocr_files + non_pdf_with_text):
        if f["filename"] in skipped_filenames:
            continue
        text = (f.get("extracted_text") or "").strip()
        if text:
            documents.append({
                "filename": f["filename"],
                "content": text,
            })

    if not documents and not dry_run:
        emitter.emit_error(ErrorKind.UNKNOWN, "Nessun documento con testo estratto")
        cleanup_extraction(extract_dir)
        return {"success": False, "error": "no_extractable_documents"}

    # ── FASE: cache prompt + analyze (Fase 3 + 5) ───────────────────────
    raw_yamls: List[str] = []
    if dry_run:
        # Dry-run: usa mock YAML pre-canned
        raw_yamls = [_DRY_RUN_YAML]
    else:
        from v2.cache_manager import get_cached_prompt
        from v2.gemini_client_v2 import analyze_batch_streaming

        cached_id = get_cached_prompt(client)

        # ── AUTO-TUNING LEVE 2C + 4 ─────────────────────────────────────────
        # Le leve compact_mode + model_mix sono efficaci solo quando ci sono
        # molti file AGGREGABLE da consolidare. Su pratiche piccole/specifiche
        # (es. ISO 27001 con procedure SGSI individuali) il consolidamento
        # penalizza la qualità dell'output. Quindi:
        # - Calcoliamo SEMPRE role_by_filename (zero costo, in-memory)
        # - Contiamo gli AGGREGABLE effettivi in `documents`
        # - Decidiamo auto-default ON/OFF in base alla soglia
        # - Override manuale possibile via env var (true/false/auto)
        role_by_filename = _build_role_by_filename(classified, skipped_filenames)
        n_aggregable = _count_aggregable_documents(documents, role_by_filename)

        threshold = int(
            os.environ.get(
                "V2_MIN_AGGREGABLE_THRESHOLD",
                str(DEFAULT_MIN_AGGREGABLE_FOR_COMPACT),
            )
        )
        auto_should_compact = (
            bool(classified) and n_aggregable >= threshold
        )

        aggregable_compact_enabled, compact_source = _resolve_leva_flag(
            "V2_LEVA2_AGGREGABLE_COMPACT", auto_default=auto_should_compact
        )
        # `bool(classified)` è una pre-condizione strutturale: se il classifier
        # non è girato (test, dry-run) NON possiamo sapere quali file siano
        # AGGREGABLE → forziamo OFF per sicurezza
        aggregable_compact_enabled = aggregable_compact_enabled and bool(classified)

        # Model mix (Leva 4): ha senso SOLO se compact è attivo (è un routing
        # sui batch aggregable). Auto-default segue la stessa soglia di compact.
        model_mix_enabled, model_mix_source = _resolve_leva_flag(
            "V2_LEVA4_MODEL_MIX", auto_default=auto_should_compact
        )
        model_mix_enabled = model_mix_enabled and aggregable_compact_enabled

        print(
            f"[V2 PIPELINE] Auto-tuning leve: aggregable_count={n_aggregable} "
            f"(soglia={threshold}). "
            f"compact_mode={'ON' if aggregable_compact_enabled else 'OFF'} "
            f"({compact_source}), "
            f"model_mix={'ON' if model_mix_enabled else 'OFF'} "
            f"({model_mix_source})"
        )

        # Split documenti in 2 pool secondo decisione finale
        documents_standard: List[Dict[str, Any]] = []
        documents_aggregable: List[Dict[str, Any]] = []
        if aggregable_compact_enabled:
            for d in documents:
                if role_by_filename.get(d["filename"]) == "AGGREGABLE":
                    documents_aggregable.append(d)
                else:
                    documents_standard.append(d)
        else:
            documents_standard = documents

        batches_standard = _create_smart_batches(
            documents_standard, max_files=4, max_chars=50_000,
        )
        # Per gli aggregable un batch più grande è sensato: l'output è
        # piccolo per file e si avvantaggia della tabella riepilogativa
        # Regola 2.6 (≥3 documenti omogenei).
        batches_aggregable = (
            _create_smart_batches(documents_aggregable, max_files=8, max_chars=50_000)
            if documents_aggregable
            else []
        )

        from v2.gemini_client_v2 import ANALYZE_MODEL_LITE
        lite_model_for_aggregable = (
            ANALYZE_MODEL_LITE if model_mix_enabled else None
        )

        # Lista finale di tutti i batch con (compact_mode, model_override)
        all_batches: List[Tuple[List[Dict[str, Any]], bool, Optional[str]]] = (
            [(b, False, None) for b in batches_standard]
            + [(b, True, lite_model_for_aggregable) for b in batches_aggregable]
        )

        # Log batch split per debugging
        print(
            f"[V2 PIPELINE] Batch split: docs_total={len(documents)}, "
            f"standard={len(documents_standard)}, aggregable={len(documents_aggregable)}, "
            f"batches_standard={len(batches_standard)}, "
            f"batches_aggregable={len(batches_aggregable)}, "
            f"model_aggregable={lite_model_for_aggregable or 'flash'}"
        )

        phase_start = time.monotonic()
        emitter.emit_phase_start(PipelinePhase.ANALYZE, total_items=len(all_batches))

        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = min(7, max(1, len(all_batches)))
        completed = 0
        results_by_idx: Dict[int, str] = {}

        def _analyze_one(idx: int, batch_docs: List[Dict[str, Any]],
                          compact: bool, model_override: Optional[str]):
            result = analyze_batch_streaming(
                client=client,
                batch_docs=batch_docs,
                batch_idx=idx,
                total_docs=len(documents),
                cached_content_id=cached_id,
                meter_session_id=session_id,
                compact_mode=compact,
                model_override=model_override,
            )
            return idx, result

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_analyze_one, i, b, c, m): i
                for i, (b, c, m) in enumerate(all_batches)
            }
            for fut in as_completed(futures):
                try:
                    idx, result = fut.result()
                    if result and result.text and not result.error:
                        results_by_idx[idx] = result.text
                except Exception as e:
                    emitter.emit_error(ErrorKind.UNKNOWN, f"batch_analyze: {e}")
                completed += 1
                emitter.emit_phase_tick(
                    PipelinePhase.ANALYZE,
                    pct=completed / max(len(all_batches), 1),
                    detail={"completed": completed, "total": len(all_batches)},
                )

        # Mantieni ordine batch
        raw_yamls = [results_by_idx[i] for i in sorted(results_by_idx.keys())]

        emitter.emit_phase_end(
            PipelinePhase.ANALYZE,
            duration_seconds=round(time.monotonic() - phase_start, 2),
            metrics={
                "batches_total": len(all_batches),
                "batches_ok": len(raw_yamls),
                "batches_standard": len(batches_standard),
                "batches_aggregable_compact": len(batches_aggregable),
                "model_mix_active": model_mix_enabled,
            },
        )

    if not raw_yamls:
        emitter.emit_error(ErrorKind.UNKNOWN, "Nessun batch ha prodotto YAML utile")
        cleanup_extraction(extract_dir)
        return {"success": False, "error": "no_yaml_output"}

    # ── Parse YAML aggregato ─────────────────────────────────────────────
    full_yaml = "\n\n---\n\n".join(raw_yamls)
    parsed_data = parse_aggregated_yaml(full_yaml)
    company_name = extract_company_name(parsed_data)

    # Leva 3 — segnala batch persi durante il parse YAML (errori non più
    # silenziosi). Ogni batch fallito diventa un evento PARSE_FAILED con
    # batch_id e prima riga.
    parse_failures = get_last_parse_failures()
    for failure in parse_failures:
        try:
            emitter.emit_error(
                ErrorKind.PARSE_FAILED,
                f"yaml_batch_skipped: {failure.get('batch_id')} → "
                f"{failure.get('error')}",
            )
        except Exception:
            pass
    if parse_failures:
        print(
            f"[V2 PIPELINE] {len(parse_failures)} batch YAML saltati "
            f"durante l'aggregazione (vedi eventi PARSE_FAILED)"
        )

    # ── FASE: docx_build (Fase 7) ────────────────────────────────────────
    phase_start = time.monotonic()
    emitter.emit_phase_start(PipelinePhase.DOCX_BUILD)
    docs_estratti = len(documents)
    docs_vuoti = max(0, len(files) - docs_estratti)
    build_results = build_all_sections(
        parsed_data,
        session_id=session_id,
        docs_estratti=docs_estratti,
        docs_vuoti=docs_vuoti,
    )
    build_sum = builder_summary(build_results)
    emitter.emit_phase_end(
        PipelinePhase.DOCX_BUILD,
        duration_seconds=round(time.monotonic() - phase_start, 2),
        metrics=build_sum,
    )

    # ── Merge finale ─────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_company = "".join(c for c in company_name if c.isalnum() or c == " ")[:30]
    safe_company = safe_company.replace(" ", "_") or "AUDIT"
    final_filename = f"Audit_V2_{safe_company}_{timestamp}.docx"
    final_path = output_dir / f"{session_id}_final.docx"

    merge_result = merge_session_sections(session_id, final_path)
    if not merge_result.success:
        emitter.emit_error(ErrorKind.UNKNOWN, f"merge_failed: {merge_result.error}")
        cleanup_session_sections(session_id)
        cleanup_extraction(extract_dir)
        return {"success": False, "error": f"merge_failed: {merge_result.error}"}

    # ── Cleanup ──────────────────────────────────────────────────────────
    phase_start = time.monotonic()
    emitter.emit_phase_start(PipelinePhase.CLEANUP)
    cleanup_session_sections(session_id)
    cleanup_extraction(extract_dir)
    emitter.emit_phase_end(
        PipelinePhase.CLEANUP,
        duration_seconds=round(time.monotonic() - phase_start, 2),
    )

    # ── Token report finale ──────────────────────────────────────────────
    token_report = token_meter.get_session_report(session_id)

    total_duration = round(time.monotonic() - pipeline_start, 2)
    stats = {
        "total_files_in_zip": len(files),
        "documents_with_text": docs_estratti,
        "duration_seconds": total_duration,
        "company_name": company_name,
        "tokens": {
            "input_total": token_report.get("total_input", 0),
            "cached_total": token_report.get("total_cached", 0),
            "output_total": token_report.get("total_output", 0),
            "cost_eur": token_report.get("total_cost_eur", 0.0),
            "saved_by_caching_eur": token_report.get("saved_by_caching_eur", 0.0),
        },
        "dry_run": dry_run,
    }

    emitter.emit_done(
        output_filename=final_filename,
        company_name=company_name,
        duration_seconds=total_duration,
        stats=stats,
    )

    return {
        "success": True,
        "output_path": str(final_path),
        "output_filename": final_filename,
        "company_name": company_name,
        "stats": stats,
        "merge_used_fallback": merge_result.used_fallback,
    }
