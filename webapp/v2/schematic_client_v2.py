"""
V2 — Schematic Client per Azure GPT-4.1-mini.

Implementa la modalita' "Prosa Schematica Telegrafica" richiesta da cliente
PROD esistente. NON in PROD attualmente — file in features/pending-validation/
da validare in worktree isolato prima di promuovere.

Output: stesso JSON narrativo {numero, categoria, sottotitolo, contenuto,
ente_auditato} per compatibilita' col parser narrative esistente. Il campo
`contenuto` cambia stile interno:
- Tipologia: <DOC>. all'inizio
- Key-Value `Etichetta: Valore.` per dati strutturali
- Sezioni MAIUSCOLE dinamiche per documenti complessi (DATI GENERALI, ANALISI
  GAP, AZIONI OPERATIVE, ecc.)
- Elenchi piatti con `-`
- Frasi atomiche Soggetto-Verbo-Oggetto

Pattern: gating in pipeline.py via env var V2_OUTPUT_MODE=schematic
(accanto a narrative).

Beneficio atteso vs narrative (8-16K token output/batch):
- -30/40% token output → -33% costo
- -15% tempo streaming
- Output piu' machine-readable (Tab 2 piu' robusto)

Riusa da narrative_client_v2 (zero duplicazione algoritmica):
- _VERBS (rotativi)
- _parse_json_narrative_response (3 livelli parser robusto)
- _make_placeholder
- _StreamRetryable, INTER_CHUNK_TIMEOUT
- Costanti retry/timeout
- AzureOpenAIClientV2, AzureRateLimitExhausted
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Path bootstrap: il client vive in webapp/v2/ accanto a narrative_client_v2.py;
# il prompt vive in webapp/prompts/schematic_evidence_prompt_v2.md.
# ──────────────────────────────────────────────────────────────────────────────

_THIS_FILE = Path(__file__).resolve()
_WEBAPP_DIR = _THIS_FILE.parent.parent  # webapp/

from v2.azure_openai_client_v2 import (  # noqa: E402
    AzureOpenAIClientV2,
    AzureRateLimitExhausted,
    INTER_CHUNK_TIMEOUT,
    MAX_STREAM_RETRIES,
    RETRY_BASE_DELAY_SECONDS,
    RETRY_MAX_DELAY_SECONDS,
    _record_error_call,
    _sanitize_text,
)
from v2.narrative_client_v2 import (  # noqa: E402
    _VERBS,
    _StreamRetryable,
    _doc_char_cap,
    _make_placeholder,
    _parse_json_narrative_response,
)


# ──────────────────────────────────────────────────────────────────────────────
# Prompt schematic loader
# ──────────────────────────────────────────────────────────────────────────────

_SCHEMATIC_PROMPT_PATH = _WEBAPP_DIR / "prompts" / "schematic_evidence_prompt_v2.md"

_SCHEMATIC_PROMPT_FALLBACK_MIN = """
Sei un motore di trasformazione testuale per documenti di audit.
Per ogni documento genera un oggetto JSON con campo `contenuto` in prosa
schematica telegrafica (key:value + sezioni MAIUSCOLE per doc complessi).
MAI: codice fiscale, P.IVA persona fisica, IBAN, data nascita.
REGOLA 1:1:1 — N documenti = N oggetti JSON.
Output JSON array con campi: numero, categoria, sottotitolo, contenuto, ente_auditato.
""".strip()


def _load_schematic_prompt() -> str:
    """
    Carica il prompt schematic dal file MD nella stessa cartella feature.
    Fallback minimo se il file non esiste (es. test isolato).
    """
    try:
        text = _SCHEMATIC_PROMPT_PATH.read_text(encoding="utf-8")
        if text.strip():
            print(f"[V2 SCHEMATIC] Prompt caricato da: {_SCHEMATIC_PROMPT_PATH.name}")
            return text
    except Exception:
        pass
    print(
        f"[V2 SCHEMATIC] WARN: prompt non trovato a {_SCHEMATIC_PROMPT_PATH}, "
        "uso fallback minimo"
    )
    return _SCHEMATIC_PROMPT_FALLBACK_MIN


# ──────────────────────────────────────────────────────────────────────────────
# Prompt builder utente (formato batch + REGOLE essenziali schematic)
# ──────────────────────────────────────────────────────────────────────────────

def _build_schematic_user_prompt(
    batch_docs: List[Dict[str, Any]],
    batch_idx: int,
    total_docs: int,
    para_start: int,
    verb: str,  # mantenuto per compat firma narrative, NON usato in reminder
    doc_cap_multiplier: float,
) -> str:
    """
    Costruisce il prompt utente per la modalita' schematic.
    Differenze chiave vs narrative:
    - No "verbo iniziale" (in schematic ogni scheda inizia con 'Tipologia: ...')
    - Reminder rinforza R0-R4 e cita esempi
    - Target lunghezza: <400 parole/doc (vs 200-800 narrative)
    """
    n_docs = len(batch_docs)
    reminder = (
        f"BATCH {para_start}-{para_start + n_docs - 1} | "
        f"Schede da generare: {n_docs}\n\n"
        f"REGOLE ESSENZIALI (schematic — vedi system prompt per dettaglio):\n"
        f"• 1 documento = 1 oggetto JSON\n"
        f"• `contenuto` inizia SEMPRE con: 'Tipologia: <NOME DOC>.'\n"
        f"• Format Key-Value: 'Etichetta: Valore.' (capitalizzata, punto finale)\n"
        f"• Frasi atomiche S-V-O (NO subordinate, NO incisi)\n"
        f"• Numeri/ID/date trascritti ESATTI come compaiono\n"
        f"• Elenchi: trattino piatto '-' (NO annidamento)\n"
        f"• Sezioni MAIUSCOLE solo per documenti complessi (manuali, piani)\n"
        f"• MAI: codice fiscale persone, P.IVA persona fisica, IBAN, data nascita\n"
        f"• Target lunghezza: <400 parole/scheda\n\n"
        f"OUTPUT RICHIESTO — SOLO JSON ARRAY:\n"
        f'[{{"numero": {para_start}, "categoria": "...", '
        f'"sottotitolo": "Tipo - Nome", "ente_auditato": "NOME AZIENDA", '
        f'"contenuto": "Tipologia: ...\\nDenominazione: ...\\n..."}}, ...]\n\n'
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
# Streaming call con kind="analyze_schematic" per token meter separato
# ──────────────────────────────────────────────────────────────────────────────

def _do_schematic_streaming_call(
    client: AzureOpenAIClientV2,
    messages: List[Dict[str, str]],
    meter_session_id: Optional[str],
    batch_idx: int,
    retry_count: int,
    model: str,
    max_output_tokens: int,
) -> Tuple[str, bool]:
    """
    Singola call streaming. Identica a _do_narrative_streaming_call
    eccetto kind="analyze_schematic" sul token_meter.
    """
    try:
        from openai import (
            APIConnectionError,
            APIError,  # noqa: F401
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

    # Token meter con kind="analyze_schematic" per separare metriche da narrative
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
                kind="analyze_schematic",
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

def analyze_batch_schematic(
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
    Analizza un batch con il metodo schematic via Azure GPT-4.1-mini.
    Firma e contratto IDENTICI ad analyze_batch_narrative per drop-in compat.

    Args:
        narrative_prompt: il system prompt schematic
          (passato dal caller — la pipeline carica via _load_schematic_prompt)

    Returns:
        (schede, fallback_attivato) — fallback_attivato sempre False qui;
        AzureRateLimitExhausted sollevato per attivare fallback Gemini.
    """
    if not batch_docs:
        return [], False

    verb = _VERBS[verb_idx % len(_VERBS)]  # non usato nel reminder, solo per compat
    user_prompt = _build_schematic_user_prompt(
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
            raw_text, truncated = _do_schematic_streaming_call(
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
                    f"[V2 SCHEMATIC] Batch {batch_idx} troncato "
                    f"(finish_reason=length). Output parziale conservato."
                )

            schede = _parse_json_narrative_response(raw_text, batch_idx)

            if not schede:
                print(
                    f"[V2 SCHEMATIC] Batch {batch_idx}: parsing fallito, "
                    f"genero {len(batch_docs)} placeholder"
                )
                schede = [
                    _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
                    for i, doc in enumerate(batch_docs)
                ]

            for i, p in enumerate(schede):
                p["numero"] = para_start + i

            print(
                f"[V2 SCHEMATIC] Batch {batch_idx}: {len(schede)} schede "
                f"(para_start={para_start}, mode=schematic)"
            )
            return schede, False

        except _StreamRetryable as e:
            last_error = str(e)
            print(
                f"[V2 SCHEMATIC] Batch {batch_idx} retry {attempt + 1}/{max_attempts}: "
                f"{last_error}"
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
            print(f"[V2 SCHEMATIC] Batch {batch_idx} errore non retryable: {e}")
            schede = [
                _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
                for i, doc in enumerate(batch_docs)
            ]
            return schede, False

    # Retry esauriti
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
    schede = [
        _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
        for i, doc in enumerate(batch_docs)
    ]
    return schede, False


def analyze_batch_schematic_gemini(
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
    Variante Gemini di analyze_batch_schematic. Fallback quando Azure va in 429.
    Stessa firma narrative gemini, stesso prompt schematic, output JSON narrativo.
    """
    if not batch_docs:
        return [], False

    verb = _VERBS[verb_idx % len(_VERBS)]

    class _FakeProfile:
        doc_cap_multiplier = 1.0

    class _FakeClient:
        profile = _FakeProfile()

    user_prompt = _build_schematic_user_prompt(
        batch_docs=batch_docs,
        batch_idx=batch_idx,
        total_docs=total_docs,
        para_start=para_start,
        verb=verb,
        doc_cap_multiplier=1.0,
    )
    user_prompt = _sanitize_text(user_prompt)
    sys_prompt = _sanitize_text(narrative_prompt)

    full_prompt = f"{sys_prompt}\n\n---\n\n{user_prompt}" if sys_prompt else user_prompt

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
        )
        raw_text = getattr(response, "text", "") or ""
    except Exception as e:
        print(f"[V2 SCHEMATIC GEMINI] Batch {batch_idx} errore: {e}")
        schede = [
            _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
            for i, doc in enumerate(batch_docs)
        ]
        return schede, False

    schede = _parse_json_narrative_response(raw_text, batch_idx)
    if not schede:
        schede = [
            _make_placeholder(para_start + i, doc.get("filename", f"doc_{i}"))
            for i, doc in enumerate(batch_docs)
        ]

    for i, p in enumerate(schede):
        p["numero"] = para_start + i

    # Token meter Gemini
    if meter_session_id:
        try:
            from v2 import token_meter
            usage = getattr(response, "usage_metadata", None)
            if usage:
                input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
                output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
                token_meter.record_call(
                    session_id=meter_session_id,
                    model="gemini-2.5-flash",
                    kind="analyze_schematic_gemini_fallback",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    batch_id=f"batch_{batch_idx:03d}",
                )
        except Exception:
            pass

    print(
        f"[V2 SCHEMATIC GEMINI] Batch {batch_idx} fallback: {len(schede)} schede"
    )
    return schede, True
