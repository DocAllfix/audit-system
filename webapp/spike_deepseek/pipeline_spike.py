"""
V2 Spike — Pipeline standalone per DeepSeek V4 Flash.

Versione minimale del pipeline V2 che:
- Riusa zip_extractor, file_triage, text_handlers, document_classifier,
  gemini_ocr_v2, yaml_parser, incremental_docx_builder, docx_merger di V2
  (zero modifiche)
- Bypassa cache_manager (DeepSeek caching automatico)
- Usa spike_deepseek.deepseek_client invece di gemini_client_v2
- Carica il prompt da `universal_evidence_prompt_spike_deepseek_{v1|v2}.md`
- Cap doc + batch + workers parametrici via env var SPIKE_*

Output:
- temp/spike_deepseek/docx_outputs/spike_<sess>_final.docx
- report dict con metriche (passato al runner per persistenza JSON)
"""
from __future__ import annotations

import io
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Costanti spike (sovrascrivibili via env var nel runner)
DEFAULT_BATCH_MAX_FILES = int(os.environ.get("SPIKE_DEEPSEEK_BATCH_MAX_FILES", "12"))
DEFAULT_BATCH_MAX_CHARS = int(os.environ.get("SPIKE_DEEPSEEK_BATCH_MAX_CHARS", "200000"))
DEFAULT_MAX_WORKERS = int(os.environ.get("SPIKE_DEEPSEEK_MAX_WORKERS", "14"))


def process_zip_spike(
    zip_bytes: bytes,
    session_id: str,
    deepseek_api_key: str,
    gemini_api_key: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Pipeline spike DeepSeek V4 Flash standalone.

    Fasi:
    1. Estrazione ZIP (riuso v2.zip_extractor)
    2. Triage native PDF (riuso v2.file_triage)
    3. Text handlers non-PDF (riuso v2.text_handlers)
    4. Classify (riuso v2.document_classifier — SU GEMINI Flash-Lite, non DeepSeek)
    5. OCR (riuso v2.gemini_ocr_v2 — SU GEMINI Vision, non DeepSeek)
    6. Costruzione documents
    7. Smart batching (max_files=12, max_chars=200K)
    8. Analyze su DeepSeek V4 Flash con 14 worker paralleli
    9. Parse YAML aggregato (riuso v2.yaml_parser)
    10. Build docx (riuso v2.incremental_docx_builder)
    11. Merge finale (riuso v2.docx_merger)

    Returns:
        Dict con success, output_path, company_name, stats e metriche.
    """
    import sys
    if "v2" not in sys.modules:
        # Aggiungi webapp al sys.path per import V2
        webapp_dir = Path(__file__).resolve().parent.parent
        if str(webapp_dir) not in sys.path:
            sys.path.insert(0, str(webapp_dir))

    pipeline_start = time.monotonic()

    # ── Lazy imports (V2) ───────────────────────────────────────────────
    from v2.zip_extractor import (
        cleanup_extraction, extract_zip_bytes,
    )
    from v2.file_triage import triage_files, KEY_NEEDS_OCR, KEY_NATIVE, KEY_NON_PDF
    from v2.text_handlers import extract_text_for_category
    from v2.document_classifier import classify_files_batch
    from v2.gemini_ocr_v2 import ocr_extract_files
    from v2.yaml_parser import (
        extract_company_name, get_last_parse_failures, parse_aggregated_yaml,
    )
    from v2.incremental_docx_builder import (
        build_all_sections, builder_summary, cleanup_session_sections,
    )
    from v2.docx_merger import merge_section_partials
    from v2.genai_factory_v2 import create_client as create_gemini_client
    from v2 import token_meter
    from v2.relevance_safetynet import apply_safety_net

    # Spike-specific imports
    from spike_deepseek.deepseek_client import (
        DeepSeekClient, analyze_batch_streaming, _create_smart_batches_spike,
    )

    # Output dir
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent.parent / "temp" / "spike_deepseek" / "docx_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── FASE 1: Ingestion ZIP ───────────────────────────────────────────
    extract_dir, files = extract_zip_bytes(zip_bytes, session_id)
    if not files:
        return {"success": False, "error": "zip_empty_or_no_files"}

    # ── FASE 2: Triage native PDF ──────────────────────────────────────
    triaged = triage_files(files)

    # ── FASE 3: Text handlers per non-PDF ──────────────────────────────
    non_pdf_files = triaged.get(KEY_NON_PDF, [])
    non_pdf_with_text: List[Dict[str, Any]] = []
    for f in non_pdf_files:
        text, method = extract_text_for_category(f)
        if text and len(text.strip()) >= 10:
            f["extracted_text"] = text
            f["extraction_method"] = method
            non_pdf_with_text.append(f)
        else:
            f["extraction_method"] = method or "unsupported_format"

    # ── FASE 4: Classify (Gemini Flash-Lite, riuso V2) ────────────────
    files_for_classify = (
        triaged.get(KEY_NATIVE, [])
        + triaged.get(KEY_NEEDS_OCR, [])
        + non_pdf_with_text
    )
    classified: List = []
    if files_for_classify and gemini_api_key:
        gem_client = create_gemini_client(api_key=gemini_api_key)
        try:
            classified = classify_files_batch(
                files_for_classify,
                api_key=gemini_api_key,
                _client=gem_client,
                meter_session_id=session_id,
            )
        except Exception as e:
            print(f"[SPIKE] classifier_error: {e}")
            classified = []

    # ── FASE 5: OCR (Gemini Vision, riuso V2) ────────────────────────
    needs_ocr_files = triaged.get(KEY_NEEDS_OCR, [])
    if needs_ocr_files and gemini_api_key:
        gem_client = create_gemini_client(api_key=gemini_api_key)
        try:
            ocr_results = ocr_extract_files(
                gem_client,
                needs_ocr_files,
                session_id=session_id,
                cleanup_after=True,
                meter_session_id=session_id,
            )
            ocr_text_by_filename = {
                r.filename: r.text for r in ocr_results if r.success
            }
            for f in needs_ocr_files:
                if f["filename"] in ocr_text_by_filename:
                    f["extracted_text"] = ocr_text_by_filename[f["filename"]]
        except Exception as e:
            print(f"[SPIKE] ocr_pipeline_error: {e}")

    # ── FASE 6: Safety net + costruzione documents ────────────────────
    skipped_filenames: set = set()
    if classified and os.environ.get("SPIKE_DEEPSEEK_SKIP_NOISE", "false").lower() == "true":
        files_index = {
            f["filename"]: f
            for f in (triaged.get(KEY_NATIVE, []) + needs_ocr_files + non_pdf_with_text)
        }
        sn_result = apply_safety_net(classified, files_index)
        skipped_filenames = {cf.filename for cf in sn_result["skipped"]}

    documents = []
    for f in (triaged.get(KEY_NATIVE, []) + needs_ocr_files + non_pdf_with_text):
        if f["filename"] in skipped_filenames:
            continue
        text = (f.get("extracted_text") or "").strip()
        if text:
            documents.append({
                "filename": f["filename"],
                "content": text,
            })

    if not documents:
        cleanup_extraction(extract_dir)
        return {"success": False, "error": "no_extractable_documents"}

    # ── FASE 7: Smart batching (parametri SPIKE) ────────────────────────
    batches = _create_smart_batches_spike(
        documents,
        max_files=DEFAULT_BATCH_MAX_FILES,
        max_chars=DEFAULT_BATCH_MAX_CHARS,
    )

    # ── FASE 8: Analyze su DeepSeek V4 Flash ──────────────────────────
    deepseek_client = DeepSeekClient(api_key=deepseek_api_key)
    print(
        f"[SPIKE] Batch split: docs={len(documents)} → batches={len(batches)} "
        f"(max_files={DEFAULT_BATCH_MAX_FILES}, max_chars={DEFAULT_BATCH_MAX_CHARS}). "
        f"Workers={DEFAULT_MAX_WORKERS}. Prompt variant={os.environ.get('SPIKE_PROMPT_VARIANT', 'v2')}"
    )

    analyze_start = time.monotonic()
    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = min(DEFAULT_MAX_WORKERS, max(1, len(batches)))
    results_by_idx: Dict[int, str] = {}

    def _analyze_one(idx: int, batch_docs: List[Dict[str, Any]]):
        result = analyze_batch_streaming(
            client=deepseek_client,
            batch_docs=batch_docs,
            batch_idx=idx,
            total_docs=len(documents),
            meter_session_id=session_id,
            compact_mode=False,  # spike non usa compact, vuole massimo dettaglio
        )
        return idx, result

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_analyze_one, i, b): i for i, b in enumerate(batches)}
        for fut in as_completed(futures):
            try:
                idx, result = fut.result()
                if result and result.text and not result.error:
                    results_by_idx[idx] = result.text
                else:
                    print(f"[SPIKE] batch {idx} error: {result.error if result else 'unknown'}")
            except Exception as e:
                print(f"[SPIKE] batch_analyze unexpected: {e}")

    raw_yamls = [results_by_idx[i] for i in sorted(results_by_idx.keys())]
    analyze_duration = time.monotonic() - analyze_start

    if not raw_yamls:
        cleanup_extraction(extract_dir)
        return {"success": False, "error": "no_yaml_output"}

    # ── FASE 9: Parse YAML aggregato ──────────────────────────────────
    full_yaml = "\n\n---\n\n".join(raw_yamls)
    parsed_data = parse_aggregated_yaml(full_yaml)
    company_name = extract_company_name(parsed_data)

    parse_failures = get_last_parse_failures()
    if parse_failures:
        print(f"[SPIKE] {len(parse_failures)} batch YAML saltati")

    # ── FASE 10: Build docx + merge ────────────────────────────────────
    docs_estratti = len(documents)
    docs_vuoti = max(0, len(files) - docs_estratti)
    build_results = build_all_sections(
        parsed_data,
        session_id=session_id,
        docs_estratti=docs_estratti,
        docs_vuoti=docs_vuoti,
    )
    build_sum = builder_summary(build_results)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_company = "".join(c for c in (company_name or "AUDIT") if c.isalnum() or c == " ")[:30]
    safe_company = safe_company.replace(" ", "_") or "AUDIT"
    final_filename = f"spike_{session_id}_{safe_company}_{timestamp}.docx"
    final_path = output_dir / final_filename

    merge_result = merge_section_partials(
        session_id=session_id,
        output_path=final_path,
    )

    # Cleanup
    cleanup_session_sections(session_id)
    cleanup_extraction(extract_dir)

    if not merge_result.success:
        return {
            "success": False,
            "error": f"merge_failed: {merge_result.error}",
            "raw_yaml_chars": sum(len(y) for y in raw_yamls),
        }

    total_duration = time.monotonic() - pipeline_start
    output_size_kb = round(final_path.stat().st_size / 1024, 1) if final_path.exists() else 0

    # Telemetria token
    token_report = token_meter.get_session_report(session_id)

    return {
        "success": True,
        "output_path": str(final_path),
        "output_size_kb": output_size_kb,
        "company_name": company_name,
        "duration_seconds": round(total_duration, 2),
        "analyze_duration_seconds": round(analyze_duration, 2),
        "calls_count": token_report.get("calls_count", 0),
        "tokens_input": token_report.get("total_input", 0),
        "tokens_cached": token_report.get("total_cached", 0),
        "tokens_output": token_report.get("total_output", 0),
        "cost_usd": token_report.get("total_cost_usd", 0.0),
        "cost_eur": token_report.get("total_cost_eur", 0.0),
        "saved_by_caching_eur": token_report.get("saved_by_caching_eur", 0.0),
        "n_batches": len(batches),
        "n_documents": len(documents),
        "n_parse_failures": len(parse_failures),
        "build_summary": build_sum,
        "prompt_variant": os.environ.get("SPIKE_PROMPT_VARIANT", "v2"),
        "batch_max_files": DEFAULT_BATCH_MAX_FILES,
        "batch_max_chars": DEFAULT_BATCH_MAX_CHARS,
        "max_workers": DEFAULT_MAX_WORKERS,
    }
