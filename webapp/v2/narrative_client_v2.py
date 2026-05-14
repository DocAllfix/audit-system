"""
V2 — Narrative Client per Azure GPT-4.1-mini.

Implementa il metodo narrativo originale (Fase 1 legacy) adattato al sistema
V2 con tutte le ottimizzazioni consolidate in locale:
- Azure GPT-4.1-mini come LLM principale (GDPR EU, -63% costo vs Gemini)
- Azure Document Intelligence per OCR (già nel pipeline V2)
- Fix immagini → OCR (jpg/png/heic promossi a needs_ocr)
- Fix long path Windows (zip_extractor)
- Smart batching First Fit Decreasing
- Fallback Gemini su AzureRateLimitExhausted
- Token meter integrato
- Parser JSON a 3 livelli robusto (eredita da gemini_client.py)

Output: JSON array narrativo nel formato originale:
  [{"numero": N, "categoria": "...", "sottotitolo": "...",
    "contenuto": "...", "ente_auditato": "..."}]

Il JSON viene poi passato a _parse_json_narrativo_fallback() in
structured_evidence_parser.py → generate_structured_evidence_docx()
per produrre il docx ricco compatibile con Tab 2 / checklist_producer.

Attivato via env var: V2_OUTPUT_MODE=narrative
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from v2.azure_openai_client_v2 import (
    AzureOpenAIClientV2,
    AzureRateLimitExhausted,
    _sanitize_text,
    INTER_CHUNK_TIMEOUT,
    MAX_STREAM_RETRIES,
    RETRY_BASE_DELAY_SECONDS,
    RETRY_MAX_DELAY_SECONDS,
    _record_error_call,
)
from v2.provider_profiles_v2 import ProviderProfile


# ──────────────────────────────────────────────────────────────────────────────
# Prompt narrativo
# ──────────────────────────────────────────────────────────────────────────────

_WEBAPP_DIR = Path(__file__).resolve().parent.parent
_NARRATIVE_PROMPT_PATH = _WEBAPP_DIR / "prompts" / "narrative_evidence_prompt_v2.md"
_NARRATIVE_PROMPT_LEGACY = _WEBAPP_DIR.parent / "legacy" / "fase1_narrative_pipeline" / "api_prompt.md"


def _load_narrative_prompt() -> str:
    """
    Carica il prompt narrativo. Priorità:
    1. webapp/prompts/narrative_evidence_prompt_v2.md (versione aggiornata)
    2. legacy/fase1_narrative_pipeline/api_prompt.md (originale)
    """
    for path in (_NARRATIVE_PROMPT_PATH, _NARRATIVE_PROMPT_LEGACY):
        try:
            text = path.read_text(encoding="utf-8")
            if text.strip():
                print(f"[V2 NARRATIVE] Prompt caricato da: {path.name}")
                return text
        except Exception:
            continue
    print("[V2 NARRATIVE] WARN: prompt narrativo non trovato, uso fallback minimo")
    return _NARRATIVE_PROMPT_FALLBACK_MIN


_NARRATIVE_PROMPT_FALLBACK_MIN = """
Sei un Auditor senior. Per ogni documento ricevuto genera 1 paragrafo di evidenze
oggettive in italiano (200-800 parole), in prosa discorsiva senza liste puntate.
MAI: codice fiscale, P.IVA persona fisica, data/luogo nascita.
Output: JSON array con campi numero, categoria, sottotitolo, contenuto, ente_auditato.
"""


# ──────────────────────────────────────────────────────────────────────────────
# Cap caratteri per documento (identici ad azure_openai_client_v2.py)
# ──────────────────────────────────────────────────────────────────────────────

_DOC_CAP_PATTERNS = (
    (("visura", "camerale", "cciaa", "rea", "registro imprese"), 30_000),
    (("dvr", "valutazione rischi", "valutazione dei rischi"), 25_000),
    (("statuto", "atto costitutivo", "atto notarile"), 25_000),
    (("bilancio", "esg", "sostenibilita", "gri", "esrs", "csrd"), 25_000),
    (("analisi energetica", "iso 50001", "enpi", "see "), 20_000),
    (("ghg", "inventario emissioni", "iso 14064", "carbon"), 20_000),
    (("iso 9001", "iso 14001", "iso 45001", "iso 27001",
      "iso 37001", "iso 39001", "soa ", "rating legalita"), 16_000),
)
_DOC_CAP_DEFAULT = 12_000


def _doc_char_cap(filename: str, content: str, multiplier: float) -> int:
    fn = (filename or "").lower().replace("_", " ").replace("-", " ")
    head = (content or "")[:1500].lower()
    for keywords, cap_base in _DOC_CAP_PATTERNS:
        if any(k in fn or k in head for k in keywords):
            return int(cap_base * multiplier)
    return int(_DOC_CAP_DEFAULT * multiplier)


# ──────────────────────────────────────────────────────────────────────────────
# Verbi narrativi rotativi (stesso set del GeminiClient originale)
# ──────────────────────────────────────────────────────────────────────────────

_VERBS = [
    "Esaminato", "Visionato", "Acquisito", "Verificato",
    "Consultato", "Analizzato", "Preso atto di", "Rilevato",
]


# ──────────────────────────────────────────────────────────────────────────────
# Costruzione prompt utente narrativo
# ──────────────────────────────────────────────────────────────────────────────

def _build_narrative_user_prompt(
    batch_docs: List[Dict[str, Any]],
    batch_idx: int,
    total_docs: int,
    para_start: int,
    verb: str,
    doc_cap_multiplier: float,
) -> str:
    """
    Costruisce il prompt utente nel formato del sistema narrativo originale.
    Mantiene il reminder batch con numero paragrafo e verbo rotativo.
    """
    n_docs = len(batch_docs)
    reminder = (
        f"BATCH {para_start}-{para_start + n_docs - 1} | "
        f"Paragrafo iniziale: {para_start} | Verbo: {verb}\n\n"
        f"REGOLE ESSENZIALI:\n"
        f"• 1 documento = 1 paragrafo (200-800 parole)\n"
        f"• MAI: codice fiscale, P.IVA persona fisica, data/luogo nascita\n"
        f"• Stile: prosa narrativa, NO liste puntate\n"
        f"• Inizia ogni paragrafo con: {verb}\n\n"
        f"OUTPUT RICHIESTO — SOLO JSON ARRAY:\n"
        f'[{{"numero": {para_start}, "categoria": "...", "sottotitolo": "Tipo - Nome", '
        f'"ente_auditato": "NOME AZIENDA", "contenuto": "Testo..."}}, ...]\n\n'
        f"Totale progetto: {total_docs} documenti. Batch corrente: {n_docs} documenti.\n"
    )

    docs_text = ""
    for i, doc in enumerate(batch_docs):
        fname = doc.get("filename", "sconosciuto")
        content = _sanitize_text(doc.get("content") or doc.get("extracted_text") or "")
        cap = _doc_char_cap(fname, content, doc_cap_multiplier)
        docs_text += f"\n\n--- DOCUMENTO {para_start + i} ---\n"
        docs_text += f"Filename: {fname}\n"
        docs_text += f"Contenuto:\n{content[:cap]}"

    return reminder + "DOCUMENTI DA ANALIZZARE:" + docs_text


# ──────────────────────────────────────────────────────────────────────────────
# Parser JSON a 3 livelli (replica del GeminiClient._parse_json_response)
# ──────────────────────────────────────────────────────────────────────────────

def _parse_json_narrative_response(response_text: str, batch_idx: int) -> List[Dict]:
    """
    Parser a 3 livelli per output JSON narrativo:
    1. json.loads() standard
    2. json.loads(strict=False) — tollera apostrofi/newline non escapati
    3. Brace-matching oggetto per oggetto (recovery massimo)
    """
    text = response_text.strip()
    # Rimuovi fence ```json...```
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    text = text.strip()

    # Isola l'array JSON
    if '[' in text:
        try:
            text = text[text.index('['):text.rindex(']') + 1]
        except ValueError:
            pass
    else:
        return []

    # Livello 1: standard
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # Livello 2: strict=False
    try:
        parsed = json.loads(text, strict=False)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # Livello 3: brace-matching
    objects, depth, start_pos = [], 0, None
    for i, char in enumerate(text):
        if char == '{' and depth == 0:
            start_pos, depth = i, 1
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0 and start_pos is not None:
                try:
                    obj = json.loads(text[start_pos:i + 1], strict=False)
                    if isinstance(obj, dict) and 'contenuto' in obj:
                        objects.append(obj)
                except json.JSONDecodeError:
                    pass
                start_pos = None

    if objects:
        print(f"[V2 NARRATIVE] Batch {batch_idx}: recuperati {len(objects)} obj via brace-matching")
        return objects

    preview = response_text[:200].encode('ascii', 'replace').decode('ascii')
    print(f"[V2 NARRATIVE] Batch {batch_idx}: parser JSON fallito. Preview: {preview}")
    return []


# ──────────────────────────────────────────────────────────────────────────────
# Placeholder per documento non elaborabile
# ──────────────────────────────────────────────────────────────────────────────

def _make_placeholder(numero: int, filename: str) -> Dict[str, Any]:
    """Genera paragrafo placeholder per documento che non ha potuto essere elaborato."""
    return {
        "numero": numero,
        "categoria": "ALTRO",
        "sottotitolo": f"{os.path.splitext(filename)[0]} - ELABORAZIONE FALLITA",
        "ente_auditato": "",
        "contenuto": (
            f"Il documento '{filename}' non ha potuto essere elaborato in questo "
            "batch (errore parsing risposta AI). Il file è presente nel fascicolo "
            "ma il contenuto non è stato analizzato."
        ),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Call streaming → testo grezzo (niente YamlStreamParser)
# ──────────────────────────────────────────────────────────────────────────────

class _StreamRetryable(Exception):
    pass


def _do_narrative_streaming_call(
    client: AzureOpenAIClientV2,
    messages: List[Dict[str, str]],
    meter_session_id: Optional[str],
    batch_idx: int,
    retry_count: int,
    model: str,
    max_output_tokens: int,
) -> Tuple[str, bool]:
    """
    Singola call streaming che raccoglie il testo grezzo.
    Ritorna (testo_completo, truncated).
    Solleva _StreamRetryable su errori transienti.
    """
    try:
        from openai import (
            APIConnectionError,
            APIError,
            APIStatusError,
            RateLimitError,
        )
    except ImportError as e:
        raise RuntimeError("pip install openai>=1.0") from e

    try:
        stream = client.chat_stream(messages=messages, max_tokens=max_output_tokens)
    except RateLimitError as e:
        raise _StreamRetryable(f"rate_limit: {e}")
    except APIConnectionError as e:
        raise _StreamRetryable(f"connection: {e}")

    collected: List[str] = []
    last_chunk_time = time.monotonic()
    finish_reason: Optional[str] = None
    last_usage = None
    call_start = time.monotonic()

    try:
        from openai import RateLimitError, APIConnectionError, APIStatusError, APIError
        for chunk in stream:
            now = time.monotonic()
            if now - last_chunk_time > INTER_CHUNK_TIMEOUT:
                raise _StreamRetryable(
                    f"inter_chunk_timeout: nessun chunk per {INTER_CHUNK_TIMEOUT}s"
                )
            last_chunk_time = now

            choices = getattr(chunk, "choices", None) or []
            if choices:
                ch = choices[0]
                delta = getattr(ch, "delta", None)
                content = getattr(delta, "content", None) if delta else None
                if content:
                    collected.append(content)
                fr = getattr(ch, "finish_reason", None)
                if fr:
                    finish_reason = fr

            usage = getattr(chunk, "usage", None)
            if usage:
                last_usage = usage

    except RateLimitError as e:
        raise _StreamRetryable(f"rate_limit: {e}")
    except APIConnectionError as e:
        raise _StreamRetryable(f"connection: {e}")
    except APIStatusError as e:
        sc = getattr(e, "status_code", None) or 500
        if sc in (408, 429) or 500 <= sc < 600:
            raise _StreamRetryable(f"api_status_{sc}: {e}")
        raise

    duration = round(time.monotonic() - call_start, 3)
    truncated = (finish_reason == "length")

    # Token meter
    if meter_session_id and last_usage:
        try:
            from v2 import token_meter
            input_tokens = int(getattr(last_usage, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(last_usage, "completion_tokens", 0) or 0)
            cached_tokens = 0
            pt_details = getattr(last_usage, "prompt_tokens_details", None)
            if pt_details is not None:
                cached_tokens = int(getattr(pt_details, "cached_tokens", 0) or 0)
            token_meter.record_call(
                session_id=meter_session_id,
                model=model,
                kind="analyze_narrative",
                input_tokens=max(0, input_tokens - cached_tokens),
                cached_tokens=cached_tokens,
                output_tokens=output_tokens,
                retry_count=retry_count,
                batch_id=f"batch_{batch_idx:03d}",
                duration_seconds=duration,
            )
        except Exception:
            pass

    return "".join(collected), truncated


# ──────────────────────────────────────────────────────────────────────────────
# API pubblica
# ──────────────────────────────────────────────────────────────────────────────

def analyze_batch_narrative(
    client: AzureOpenAIClientV2,
    batch_docs: List[Dict[str, Any]],
    batch_idx: int,
    total_docs: int,
    para_start: int,
    verb_idx: int,
    narrative_prompt: str,
    meter_session_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Analizza un batch con il metodo narrativo originale via Azure GPT-4.1-mini.

    Args:
        client: AzureOpenAIClientV2 già inizializzato
        batch_docs: lista dict {filename, content/extracted_text}
        batch_idx: indice batch (per logging e token meter)
        total_docs: totale documenti nel progetto
        para_start: numero del primo paragrafo in questo batch
        verb_idx: indice nel ciclo verbi rotativi
        narrative_prompt: system prompt narrativo (da _load_narrative_prompt())
        meter_session_id: session id per token meter

    Returns:
        (paragrafi, fallback_attivato)
        - paragrafi: lista dict narrativi {numero, categoria, sottotitolo,
                     contenuto, ente_auditato}
        - fallback_attivato: True se è stato usato il fallback Gemini
    """
    if not batch_docs:
        return [], False

    verb = _VERBS[verb_idx % len(_VERBS)]
    user_prompt = _build_narrative_user_prompt(
        batch_docs=batch_docs,
        batch_idx=batch_idx,
        total_docs=total_docs,
        para_start=para_start,
        verb=verb,
        doc_cap_multiplier=client.profile.doc_cap_multiplier,
    )
    user_prompt = _sanitize_text(user_prompt)
    sys_prompt = _sanitize_text(narrative_prompt)

    messages: List[Dict[str, str]] = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": user_prompt})

    model = client.profile.name
    last_error: Optional[str] = None
    max_attempts = MAX_STREAM_RETRIES + 1

    for attempt in range(max_attempts):
        try:
            raw_text, truncated = _do_narrative_streaming_call(
                client=client,
                messages=messages,
                meter_session_id=meter_session_id,
                batch_idx=batch_idx,
                retry_count=attempt,
                model=model,
                max_output_tokens=client.profile.max_output_tokens,
            )

            if truncated:
                print(
                    f"[V2 NARRATIVE] Batch {batch_idx} troncato (finish_reason=length). "
                    f"Output parziale conservato per recovery."
                )

            paragraphs = _parse_json_narrative_response(raw_text, batch_idx)

            # Se parsing fallisce → placeholder per ogni documento del batch
            if not paragraphs:
                print(
                    f"[V2 NARRATIVE] Batch {batch_idx}: parsing fallito, "
                    f"genero {len(batch_docs)} placeholder"
                )
                paragraphs = [
                    _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
                    for i, doc in enumerate(batch_docs)
                ]

            # Rinumera paragrafi in base al para_start del batch
            for i, p in enumerate(paragraphs):
                p["numero"] = para_start + i

            print(
                f"[V2 NARRATIVE] Batch {batch_idx}: {len(paragraphs)} paragrafi "
                f"(verb={verb}, para_start={para_start})"
            )
            return paragraphs, False

        except _StreamRetryable as e:
            last_error = str(e)
            print(
                f"[V2 NARRATIVE] Batch {batch_idx} retry {attempt + 1}/{max_attempts}: {last_error}"
            )
            wait = min(
                RETRY_BASE_DELAY_SECONDS * (2 ** attempt),
                RETRY_MAX_DELAY_SECONDS,
            )
            time.sleep(wait)

        except Exception as e:
            _record_error_call(
                meter_session_id, model, f"batch_{batch_idx:03d}",
                attempt, f"non_retryable: {e}", None,
            )
            print(f"[V2 NARRATIVE] Batch {batch_idx} errore non retryable: {e}")
            paragraphs = [
                _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
                for i, doc in enumerate(batch_docs)
            ]
            return paragraphs, False

    # Tutti i retry esauriti
    _record_error_call(
        meter_session_id, model, f"batch_{batch_idx:03d}",
        max_attempts - 1, f"all_retries_failed: {last_error}", None,
    )
    if last_error and "rate_limit" in last_error.lower():
        raise AzureRateLimitExhausted(
            batch_idx=batch_idx,
            n_retries=max_attempts,
            last_error=last_error or "",
        )
    # Fallback: placeholder
    paragraphs = [
        _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
        for i, doc in enumerate(batch_docs)
    ]
    return paragraphs, False


def analyze_batch_narrative_gemini(
    gemini_client,
    batch_docs: List[Dict[str, Any]],
    batch_idx: int,
    total_docs: int,
    para_start: int,
    verb_idx: int,
    narrative_prompt: str,
    meter_session_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Variante Gemini di analyze_batch_narrative.
    Usata come fallback quando Azure va in 429 in modalità narrative.
    Stessa struttura prompt/output, API Gemini generate_content (non streaming).
    """
    if not batch_docs:
        return [], False

    verb = _VERBS[verb_idx % len(_VERBS)]

    # Gemini non ha profilo doc_cap_multiplier — usa 1.0
    class _FakeProfile:
        doc_cap_multiplier = 1.0

    class _FakeClient:
        profile = _FakeProfile()

    user_prompt = _build_narrative_user_prompt(
        batch_docs=batch_docs,
        batch_idx=batch_idx,
        total_docs=total_docs,
        para_start=para_start,
        verb=verb,
        doc_cap_multiplier=1.0,
    )
    user_prompt = _sanitize_text(user_prompt)
    sys_prompt = _sanitize_text(narrative_prompt)

    full_prompt = f"{sys_prompt}\n\n{user_prompt}" if sys_prompt else user_prompt

    try:
        from google.genai import types as _gtypes
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
            config=_gtypes.GenerateContentConfig(
                max_output_tokens=32000,
                temperature=0.3,
            ),
        )
        raw_text = response.text or ""
    except Exception as e:
        print(f"[V2 NARRATIVE GEMINI] Batch {batch_idx} errore: {e}")
        return [
            _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
            for i, doc in enumerate(batch_docs)
        ], False

    paragraphs = _parse_json_narrative_response(raw_text, batch_idx)
    if not paragraphs:
        paragraphs = [
            _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
            for i, doc in enumerate(batch_docs)
        ]

    for i, p in enumerate(paragraphs):
        p["numero"] = para_start + i

    print(
        f"[V2 NARRATIVE GEMINI] Batch {batch_idx}: {len(paragraphs)} paragrafi "
        f"(fallback, verb={verb})"
    )
    return paragraphs, True
