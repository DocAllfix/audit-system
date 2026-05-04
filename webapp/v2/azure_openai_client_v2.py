"""
V2 — Azure OpenAI Client (gpt-4.1-mini Azure Foundry v1).

Drop-in replacement per `gemini_client_v2.analyze_batch_streaming` quando
`V2_PROVIDER=gpt-4.1-mini-azure`. Validato in spike (4 pratiche, 0 parse
failures, 0 batch persi col fallback Gemini, GDPR Azure EU).

Caratteristiche chiave:
- Endpoint: https://<resource>.services.ai.azure.com/openai/v1 (Foundry v1
  OpenAI-compatible). NON AzureOpenAI SDK; usa OpenAI SDK con base_url.
- Auto-cache prefix >= 1024 token (sconto 75% input cached).
- Retry: MAX_STREAM_RETRIES=3, backoff exponential, jitter implicito via wait.
- Fallback: solleva `AzureRateLimitExhausted` quando i retry per rate_limit
  (429) sono esauriti. La pipeline cattura l'eccezione per failover a Gemini.

Env var richieste:
    AZURE_OPENAI_API_KEY                    chiave API
    AZURE_OPENAI_ENDPOINT                   https://<resource>.services.ai.azure.com/openai/v1
    AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI     deployment name per gpt-4.1-mini

Riusa da V2 (zero modifiche):
- StreamBuffer, StreamResult, DEFAULT_MAX_CHARS (stream_buffer)
- YamlStreamParser (yaml_stream_parser)
- token_meter.record_call
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from v2.stream_buffer import DEFAULT_MAX_CHARS, StreamBuffer, StreamResult
from v2.yaml_stream_parser import ParsedMarker, YamlStreamParser

from .provider_profiles_v2 import ProviderProfile


# ──────────────────────────────────────────────────────────────────────────────
# Config retry / pacing
# ──────────────────────────────────────────────────────────────────────────────

MAX_STREAM_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 60.0
INTER_CHUNK_TIMEOUT = 90.0


# ──────────────────────────────────────────────────────────────────────────────
# Cap caratteri per documento (scalati dal profile.doc_cap_multiplier)
# ──────────────────────────────────────────────────────────────────────────────

_DOC_CAP_PATTERNS_BASE = (
    (("visura", "camerale", "cciaa", "rea", "registro imprese"), 30_000),
    (("dvr", "valutazione rischi", "valutazione dei rischi"), 25_000),
    (("statuto", "atto costitutivo", "atto notarile"), 25_000),
    (("bilancio", "esg", "sostenibilita", "gri", "esrs", "csrd"), 25_000),
    (("analisi energetica", "iso 50001", "enpi", "see "), 20_000),
    (("ghg", "inventario emissioni", "iso 14064", "carbon"), 20_000),
    (("iso 9001", "iso 14001", "iso 45001", "iso 27001",
      "iso 37001", "iso 39001", "soa ", "rating legalita"), 16_000),
)
_DOC_CAP_DEFAULT_BASE = 12_000


def doc_char_cap_for_profile(filename: str, content: str, multiplier: float) -> int:
    """Cap caratteri per un documento, scalato per il moltiplicatore del profilo."""
    fn = (filename or "").lower().replace("_", " ").replace("-", " ")
    head = (content or "")[:1500].lower().replace("_", " ").replace("-", " ")
    for keywords, cap_base in _DOC_CAP_PATTERNS_BASE:
        if any(k in fn or k in head for k in keywords):
            return int(cap_base * multiplier)
    return int(_DOC_CAP_DEFAULT_BASE * multiplier)


# ──────────────────────────────────────────────────────────────────────────────
# Sanitize + prompt loader (self-contained)
# ──────────────────────────────────────────────────────────────────────────────

_WEBAPP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT_PATH = _WEBAPP_DIR / "prompts" / "universal_evidence_prompt_v3.md"


def _sanitize_text(text: str) -> str:
    """Rimuove caratteri di controllo problematici."""
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = "".join(c for c in text if ord(c) >= 32 or c in "\n\t\r")
    text = text.replace("\x0b", " ").replace("\x0c", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _load_universal_prompt(prompt_path: Optional[Path] = None) -> str:
    """Legge il prompt universale V3. Stringa vuota se non leggibile."""
    path = prompt_path or DEFAULT_PROMPT_PATH
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[V2 AZURE] Impossibile leggere {path}: {e}")
        return ""


def _build_user_prompt(
    batch_docs: List[Dict[str, Any]],
    batch_idx: int,
    total_docs: int,
    doc_cap_multiplier: float,
    compact_mode: bool = False,
) -> str:
    """Costruisce il prompt utente con cap doc scalati dal profilo."""
    parts = []
    for i, d in enumerate(batch_docs):
        fname = d.get("filename", "sconosciuto")
        content = _sanitize_text(d.get("content") or d.get("extracted_text") or "")
        cap = doc_char_cap_for_profile(fname, content, doc_cap_multiplier)
        parts.append(f"### DOCUMENTO {i + 1}: {fname}\n{content[:cap]}")
    docs_text = "\n\n".join(parts)

    if compact_mode:
        n_docs = len(batch_docs)
        compact_directive = (
            "## MODALITÀ COMPATTA (Tier MINIMO) — INDEROGABILE PER QUESTO BATCH\n"
            f"Ricevi {n_docs} file ricorrenti ad evidenza collettiva (attestati, "
            "buste paga, UniLav, fatture). Applica il Tier MINIMO della "
            "REGOLA DI PROPORZIONALITÀ DELL'OUTPUT con header completo 9 campi.\n"
            f"### CONTEGGIO ASSOLUTO: {n_docs} file → ESATTAMENTE {n_docs} schede "
            f"`# ── DOC N ──`. Mai meno, mai più.\n\n"
        )
    else:
        compact_directive = ""

    return (
        f"{compact_directive}"
        f"## DOCUMENTI DA ELABORARE "
        f"({len(batch_docs)} file — Batch {batch_idx + 1}, "
        f"totale progetto {total_docs} doc)\n\n"
        f"{docs_text}\n\n"
        f"---\n\n"
        f"Elabora i {len(batch_docs)} documenti seguendo le 2 FASI "
        f"(CLASSIFICA → ESTRAI). Produci output YAML completo con BLOCCO META "
        f"e tutte le schede documento."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Client wrapper
# ──────────────────────────────────────────────────────────────────────────────

_DEPLOYMENT_ENV = {
    "gpt-4.1-mini": "AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI",
}


class AzureOpenAIClientV2:
    """
    Wrapper minimal per Azure AI Foundry v1 ChatCompletions con streaming.

    Usa l'OpenAI SDK standard (NON AzureOpenAI) perché il nuovo endpoint
    Foundry `services.ai.azure.com/openai/v1` è 100% OpenAI-compatible.
    """

    def __init__(
        self,
        profile: ProviderProfile,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
    ):
        if profile.api_kind != "azure_openai":
            raise ValueError(
                f"AzureOpenAIClientV2 richiede api_kind=azure_openai, ricevuto: {profile.api_kind}"
            )
        self.profile = profile

        api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        endpoint = endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
        if not api_key:
            raise ValueError("AZURE_OPENAI_API_KEY non settato.")
        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT non settato.")

        from openai import OpenAI  # type: ignore
        self._sdk = OpenAI(base_url=endpoint, api_key=api_key)
        self.deployment = self._resolve_deployment(profile)

    @staticmethod
    def _resolve_deployment(profile: ProviderProfile) -> str:
        env_name = _DEPLOYMENT_ENV.get(profile.name)
        if not env_name:
            raise ValueError(
                f"Profilo Azure non riconosciuto: {profile.name}. "
                f"Mapping disponibile: {list(_DEPLOYMENT_ENV.keys())}"
            )
        deployment = os.environ.get(env_name, "").strip()
        if not deployment:
            raise ValueError(
                f"{env_name} non settato. Imposta il nome deployment Azure "
                f"per il modello {profile.name}."
            )
        return deployment

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
    ):
        """Yields stream chunk objects (OpenAI SDK)."""
        return self._sdk.chat.completions.create(
            model=self.deployment,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            temperature=0.0,
            max_tokens=max_tokens or self.profile.max_output_tokens,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Eccezioni
# ──────────────────────────────────────────────────────────────────────────────

class _StreamRetryable(Exception):
    """Errore transient meritevole di retry con backoff."""
    pass


class AzureRateLimitExhausted(Exception):
    """
    Sollevato quando tutti i retry per rate_limit (429) sono falliti.
    La pipeline cattura per failover automatico a Gemini sul singolo batch.
    """

    def __init__(self, batch_idx: int, n_retries: int, last_error: str):
        self.batch_idx = batch_idx
        self.n_retries = n_retries
        self.last_error = last_error
        super().__init__(
            f"Azure rate limit exhausted on batch {batch_idx} after {n_retries} retries: {last_error}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# API streaming principale
# ──────────────────────────────────────────────────────────────────────────────

def analyze_batch_streaming(
    client: AzureOpenAIClientV2,
    batch_docs: List[Dict[str, Any]],
    batch_idx: int = 0,
    total_docs: int = 0,
    universal_prompt: Optional[str] = None,
    cached_content_id: Optional[str] = None,  # ignorato (Azure auto-cache)
    on_token: Optional[Callable[[str], None]] = None,
    on_marker: Optional[Callable[[ParsedMarker], None]] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    enable_retry: bool = True,
    meter_session_id: Optional[str] = None,
    compact_mode: bool = False,
    model_override: Optional[str] = None,
) -> StreamResult:
    """
    Stesso contratto di `gemini_client_v2.analyze_batch_streaming`.
    `cached_content_id` è ignorato (Azure caching automatico).

    Solleva `AzureRateLimitExhausted` se i retry per rate_limit sono esauriti.
    """
    if client is None:
        return StreamResult(text="", error="no_client")
    if not batch_docs:
        return StreamResult(text="", error="empty_batch")

    parser = YamlStreamParser(on_marker=on_marker)

    def buffer_on_chunk(delta: str) -> None:
        parser.feed(delta)
        if on_token is not None:
            try:
                on_token(delta)
            except Exception:
                pass

    buf = StreamBuffer(max_chars=max_chars, on_chunk=buffer_on_chunk)
    user_prompt = _build_user_prompt(
        batch_docs, batch_idx, total_docs,
        doc_cap_multiplier=client.profile.doc_cap_multiplier,
        compact_mode=compact_mode,
    )
    user_prompt = _sanitize_text(user_prompt)

    sys_prompt = _sanitize_text(universal_prompt or _load_universal_prompt())
    messages: List[Dict[str, str]] = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": user_prompt})

    last_error: Optional[str] = None
    batch_label = f"batch_{batch_idx:03d}"
    effective_model = model_override or client.profile.name

    max_attempts = MAX_STREAM_RETRIES + 1 if enable_retry else 1
    for attempt in range(max_attempts):
        call_start = time.monotonic()
        try:
            return _do_streaming_call(
                client=client,
                messages=messages,
                buf=buf,
                parser=parser,
                meter_session_id=meter_session_id,
                batch_id=batch_label,
                retry_count=attempt,
                model=effective_model,
                call_start=call_start,
            )
        except _StreamRetryable as e:
            last_error = str(e)
            print(
                f"[V2 AZURE] Batch {batch_idx} interrotto ({last_error}), "
                f"retry {attempt + 1}/{max_attempts}"
            )
            parser = YamlStreamParser(on_marker=on_marker)
            buf = StreamBuffer(max_chars=max_chars, on_chunk=buffer_on_chunk)
            wait = min(
                RETRY_BASE_DELAY_SECONDS * (2 ** attempt),
                RETRY_MAX_DELAY_SECONDS,
            )
            time.sleep(wait)
        except Exception as e:
            duration = round(time.monotonic() - call_start, 3)
            _record_error_call(
                meter_session_id, effective_model, batch_label, attempt,
                f"non_retryable: {e}", duration,
            )
            return buf.finalize(error=f"non_retryable: {e}")

    _record_error_call(
        meter_session_id, effective_model, batch_label, max_attempts - 1,
        f"all_retries_failed: {last_error}", None,
    )
    if last_error and "rate_limit" in last_error.lower():
        raise AzureRateLimitExhausted(
            batch_idx=batch_idx,
            n_retries=max_attempts,
            last_error=last_error,
        )
    return buf.finalize(error=f"all_retries_failed: {last_error}")


def _record_error_call(
    session_id: Optional[str],
    model: str,
    batch_id: str,
    retry_count: int,
    error: str,
    duration: Optional[float],
) -> None:
    if not session_id:
        return
    try:
        from v2 import token_meter
        kwargs: Dict[str, Any] = dict(
            session_id=session_id,
            model=model,
            kind="analyze",
            retry_count=retry_count,
            error=error,
            batch_id=batch_id,
        )
        if duration is not None:
            kwargs["duration_seconds"] = duration
        token_meter.record_call(**kwargs)
    except Exception:
        pass


def _do_streaming_call(
    client: AzureOpenAIClientV2,
    messages: List[Dict[str, str]],
    buf: StreamBuffer,
    parser: YamlStreamParser,
    meter_session_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    retry_count: int = 0,
    model: str = "",
    call_start: Optional[float] = None,
) -> StreamResult:
    """Singola call streaming. Solleva _StreamRetryable su transient."""
    if call_start is None:
        call_start = time.monotonic()
    last_chunk_time = time.monotonic()
    last_usage = None
    finish_reason: Optional[str] = None

    try:
        from openai import (  # type: ignore
            APIConnectionError,
            APIError,
            APIStatusError,
            RateLimitError,
        )
    except ImportError as e:
        raise RuntimeError(
            "Pacchetto 'openai' non installato — `pip install openai>=1.0`"
        ) from e

    try:
        stream = client.chat_stream(messages=messages)
    except RateLimitError as e:
        raise _StreamRetryable(f"rate_limit: {e}")
    except APIConnectionError as e:
        raise _StreamRetryable(f"connection: {e}")

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
                    if not buf.append_text(content):
                        continue
                fr = getattr(ch, "finish_reason", None)
                if fr:
                    finish_reason = fr

            usage = getattr(chunk, "usage", None)
            if usage:
                last_usage = usage

        parser.finalize()
        duration = round(time.monotonic() - call_start, 3)
        truncated_output = (finish_reason == "length")

        if meter_session_id and last_usage:
            try:
                from v2 import token_meter
                input_tokens = int(getattr(last_usage, "prompt_tokens", 0) or 0)
                output_tokens = int(getattr(last_usage, "completion_tokens", 0) or 0)
                cached_tokens = 0
                pt_details = getattr(last_usage, "prompt_tokens_details", None)
                if pt_details is not None:
                    cached_tokens = int(getattr(pt_details, "cached_tokens", 0) or 0)
                non_cached_input = max(0, input_tokens - cached_tokens)
                token_meter.record_call(
                    session_id=meter_session_id,
                    model=model,
                    kind="analyze",
                    input_tokens=non_cached_input,
                    cached_tokens=cached_tokens,
                    output_tokens=output_tokens,
                    retry_count=retry_count,
                    batch_id=batch_id,
                    duration_seconds=duration,
                )
            except Exception:
                pass

        result = buf.finalize()
        try:
            setattr(result, "truncated_output", bool(truncated_output))
        except Exception:
            pass
        return result

    except RateLimitError as e:
        raise _StreamRetryable(f"rate_limit: {e}")
    except APIConnectionError as e:
        raise _StreamRetryable(f"connection: {e}")
    except APIStatusError as e:
        sc = getattr(e, "status_code", None) or 500
        if sc in (408, 429) or 500 <= sc < 600:
            raise _StreamRetryable(f"api_status_{sc}: {e}")
        raise
    except APIError as e:
        raise _StreamRetryable(f"api_error: {e}")
