"""
V2 Spike — Pipeline standalone per DeepSeek V4 Flash.

Versione minimale del pipeline V2 che:
- Riusa zip_extractor, file_triage, text_handlers, document_classifier,
  gemini_ocr_v2, yaml_parser, incremental_docx_builder, docx_merger di V2
  (zero modifiche)
- Bypassa cache_manager (DeepSeek caching automatico)
- Usa spike_llm.deepseek_client invece di gemini_client_v2
- Carica il prompt da `universal_evidence_prompt_spike_llm_{v1|v2}.md`
- Cap doc + batch + workers parametrici via env var SPIKE_*

Output:
- temp/spike_llm/<provider>/docx_outputs/spike_<sess>_final.docx
- report dict con metriche (passato al runner per persistenza JSON)
"""
from __future__ import annotations

import io
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def process_zip_spike(
    zip_bytes: bytes,
    session_id: str,
    deepseek_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    output_dir: Optional[Path] = None,
    provider: str = "deepseek-v4-flash",
) -> Dict[str, Any]:
    """
    Pipeline spike multi-provider standalone.

    Fasi:
    1. Estrazione ZIP (riuso v2.zip_extractor)
    2. Triage native PDF (riuso v2.file_triage)
    3. Text handlers non-PDF (riuso v2.text_handlers)
    4. Classify (riuso v2.document_classifier — SU GEMINI Flash-Lite, sempre)
    5. OCR (riuso v2.gemini_ocr_v2 — SU GEMINI Vision, sempre)
    6. Costruzione documents
    7. Smart batching (parametri da ProviderProfile)
    8. Analyze sul provider scelto via client_dispatch
    9. Parse YAML aggregato (riuso v2.yaml_parser)
    10. Build docx (riuso v2.incremental_docx_builder)
    11. Merge finale (riuso v2.docx_merger)

    Args:
        provider: chiave ProviderProfile da usare per analyze. Default
            "deepseek-v4-flash" per backward compat.
        deepseek_api_key: chiave DeepSeek (richiesta solo se provider=deepseek-v4-flash).
        gemini_api_key: chiave Gemini (sempre richiesta per classify+OCR; e
            obbligatoria anche come "client" per provider=gemini-baseline).

    Returns:
        Dict con success, output_path, company_name, stats e metriche
        (incluso provider, batch params, n_truncated_responses).
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
    from v2.docx_merger import merge_session_sections
    from v2.genai_factory_v2 import create_genai_client_v2 as create_gemini_client
    from v2 import token_meter
    from v2.relevance_safetynet import apply_safety_net

    # Spike-specific imports
    from spike_llm.deepseek_client import _create_smart_batches_spike
    from spike_llm.provider_profiles import get_profile
    from spike_llm.client_dispatch import build_client, get_client_module

    # Risolve profilo provider
    profile = get_profile(provider)
    profile_batch_max_files = profile.batch_max_files
    profile_batch_max_chars = profile.batch_max_chars
    profile_max_workers = profile.max_workers

    # Output dir per-provider
    if output_dir is None:
        output_dir = (
            Path(__file__).resolve().parent.parent.parent
            / "temp" / "spike_llm" / profile.key / "docx_outputs"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── FASE 1: Ingestion ZIP ───────────────────────────────────────────
    files, extract_dir = extract_zip_bytes(zip_bytes, session_id)
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
    if classified and os.environ.get("SPIKE_LLM_SKIP_NOISE", os.environ.get("SPIKE_DEEPSEEK_SKIP_NOISE", "false")).lower() == "true":
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

    # ── FASE 7: Smart batching (parametri da ProviderProfile) ──────────
    batches = _create_smart_batches_spike(
        documents,
        max_files=profile_batch_max_files,
        max_chars=profile_batch_max_chars,
    )

    # ── FASE 8: Analyze sul provider scelto (dispatch + fallback Gemini su 429) ────
    analyze_client = build_client(
        profile,
        deepseek_api_key=deepseek_api_key,
        gemini_api_key=gemini_api_key,
    )
    client_module = get_client_module(profile)

    # Fallback: se il provider primario è Azure e Gemini key è disponibile,
    # prepariamo un secondo client Gemini per i batch che esauriscono i retry 429.
    fallback_enabled = (
        profile.api_kind == "azure_openai"
        and gemini_api_key
        and os.environ.get("SPIKE_LLM_DISABLE_FALLBACK", "0") != "1"
    )
    fallback_client = None
    fallback_module = None
    if fallback_enabled:
        try:
            from spike_llm.provider_profiles import get_profile as _get_profile
            from spike_llm.client_dispatch import build_client as _build, get_client_module as _get_module
            _fb_profile = _get_profile("gemini-baseline")
            fallback_client = _build(_fb_profile, gemini_api_key=gemini_api_key)
            fallback_module = _get_module(_fb_profile)
            print(f"[SPIKE/{profile.key}] Fallback Gemini abilitato (su 429 esauriti)")
        except Exception as e:
            print(f"[SPIKE/{profile.key}] Fallback Gemini non inizializzabile: {e}")
            fallback_enabled = False

    print(
        f"[SPIKE/{profile.key}] Batch split: docs={len(documents)} → batches={len(batches)} "
        f"(max_files={profile_batch_max_files}, max_chars={profile_batch_max_chars}). "
        f"Workers={profile_max_workers}. Prompt variant={os.environ.get('SPIKE_PROMPT_VARIANT', 'v2')}"
    )

    analyze_start = time.monotonic()
    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = min(profile_max_workers, max(1, len(batches)))
    results_by_idx: Dict[int, str] = {}
    n_truncated_responses = 0
    fallback_batches: List[int] = []  # idx dei batch ricorsi a Gemini

    def _analyze_one(idx: int, batch_docs: List[Dict[str, Any]]):
        # Tentativo primario sul provider scelto
        try:
            result = client_module.analyze_batch_streaming(
                client=analyze_client,
                batch_docs=batch_docs,
                batch_idx=idx,
                total_docs=len(documents),
                meter_session_id=session_id,
                compact_mode=False,
            )
            return idx, result, False  # fallback_used=False
        except Exception as e:
            # Detect AzureRateLimitExhausted (sollevata solo dal client Azure).
            # Se è 429 esaurito e fallback è abilitato → ritenta su Gemini.
            from spike_llm.azure_openai_client import AzureRateLimitExhausted
            if isinstance(e, AzureRateLimitExhausted) and fallback_enabled:
                print(
                    f"[SPIKE/{profile.key}] batch {idx} esaurito su Azure (429), "
                    f"FALLBACK → gemini-baseline"
                )
                try:
                    fb_result = fallback_module.analyze_batch_streaming(
                        client=fallback_client,
                        batch_docs=batch_docs,
                        batch_idx=idx,
                        total_docs=len(documents),
                        meter_session_id=session_id,
                        compact_mode=False,
                    )
                    return idx, fb_result, True  # fallback_used=True
                except Exception as fb_exc:
                    print(f"[SPIKE/{profile.key}] FALLBACK GEMINI fallito su batch {idx}: {fb_exc}")
                    # Ritorno StreamResult vuoto con error
                    from v2.stream_buffer import StreamResult as _SR
                    return idx, _SR(text="", error=f"primary_429_fallback_failed: {fb_exc}"), True
            # Errore non rate-limit o fallback disabilitato → propaga come error result
            from v2.stream_buffer import StreamResult as _SR
            return idx, _SR(text="", error=f"unhandled_exception: {e}"), False

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_analyze_one, i, b): i for i, b in enumerate(batches)}
        for fut in as_completed(futures):
            try:
                idx, result, used_fallback = fut.result()
                if used_fallback:
                    fallback_batches.append(idx)
                if result and result.text and not result.error:
                    results_by_idx[idx] = result.text
                    if getattr(result, "truncated_output", False):
                        n_truncated_responses += 1
                        print(f"[SPIKE/{profile.key}] batch {idx} TRUNCATED (output cap raggiunto)")
                else:
                    print(f"[SPIKE/{profile.key}] batch {idx} error: {result.error if result else 'unknown'}")
            except Exception as e:
                print(f"[SPIKE/{profile.key}] batch_analyze unexpected: {e}")

    if fallback_batches:
        print(
            f"[SPIKE/{profile.key}] FALLBACK Gemini usato per "
            f"{len(fallback_batches)}/{len(batches)} batch: {sorted(fallback_batches)}"
        )

    raw_yamls = [results_by_idx[i] for i in sorted(results_by_idx.keys())]
    analyze_duration = time.monotonic() - analyze_start

    if not raw_yamls:
        cleanup_extraction(extract_dir)
        return {"success": False, "error": "no_yaml_output"}

    # ── FASE 8.5: Dump raw YAML su disco (debug malformations) ─────────
    # Ogni batch viene salvato come file separato in <output_dir_parent>/raw_yamls/.
    # Permette analisi post-mortem dei batch droppati dal parser.
    try:
        raw_dump_dir = output_dir.parent / "raw_yamls"
        raw_dump_dir.mkdir(parents=True, exist_ok=True)
        for idx, raw in enumerate(raw_yamls):
            (raw_dump_dir / f"batch_{idx:03d}.yaml").write_text(raw, encoding="utf-8")
        print(f"[SPIKE/{profile.key}] {len(raw_yamls)} raw YAML salvati in {raw_dump_dir}")
    except Exception as e:
        print(f"[SPIKE/{profile.key}] raw_yaml_dump failed (non-blocking): {e}")

    # ── FASE 9: Parse YAML aggregato ──────────────────────────────────
    full_yaml = "\n\n---\n\n".join(raw_yamls)
    parsed_data = parse_aggregated_yaml(full_yaml)
    company_name = extract_company_name(parsed_data)

    parse_failures = get_last_parse_failures()
    if parse_failures:
        print(f"[SPIKE] {len(parse_failures)} batch YAML saltati")
        # Salva anche la lista dei batch falliti
        try:
            (raw_dump_dir / "_parse_failures.txt").write_text(
                "\n".join(str(f) for f in parse_failures),
                encoding="utf-8",
            )
        except Exception:
            pass

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
    final_filename = f"spike_{profile.key}_{safe_company}_{timestamp}.docx"
    final_path = output_dir / final_filename

    merge_result = merge_session_sections(
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
        "provider": profile.key,
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
        "n_truncated_responses": n_truncated_responses,
        "build_summary": build_sum,
        "prompt_variant": os.environ.get("SPIKE_PROMPT_VARIANT", "v2"),
        "batch_max_files": profile_batch_max_files,
        "batch_max_chars": profile_batch_max_chars,
        "max_workers": profile_max_workers,
        # Telemetria fallback Gemini (S3 — 429 recovery)
        "fallback_enabled": fallback_enabled,
        "n_fallback_batches": len(fallback_batches),
        "fallback_batch_idxs": sorted(fallback_batches),
        "fallback_provider": "gemini-baseline" if fallback_enabled else None,
    }
