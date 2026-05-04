"""
V2 Spike — Azure OpenAI Client (GPT-4.1-mini via Foundry v1 endpoint).

Replica di `deepseek_client.py` per Azure AI Foundry ChatCompletions usando il
**nuovo endpoint v1 OpenAI-compatible** (services.ai.azure.com/openai/v1).

Differenze chiave vs vecchio AzureOpenAI SDK:
- Endpoint: https://<resource>.services.ai.azure.com/openai/v1 (nuovo Foundry v1)
- SDK: `OpenAI(base_url=..., api_key=...)`, NON `AzureOpenAI(...)`
- Niente `api_version`: il path /openai/v1 lo determina implicitamente
- Auth: api_key Bearer (gestita dall'SDK)
- Caching: AUTOMATICO per prefix >= 1024 token (sconto 75% sul cached input)
- Streaming: chunk objects via SDK
- Truncation detection: finish_reason == "length" → flag in StreamResult
- max_tokens: dal `profile.max_output_tokens` (32K per gpt-4.1-mini)

Env var richieste:
    AZURE_OPENAI_API_KEY                    chiave API
    AZURE_OPENAI_ENDPOINT                   https://<resource>.services.ai.azure.com/openai/v1
    AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI     deployment name per gpt-4.1-mini

Riusa da V2 (zero modifiche):
- StreamBuffer, StreamResult, DEFAULT_MAX_CHARS (stream_buffer)
- YamlStreamParser (yaml_stream_parser)
- token_meter.record_call

Riusa da deepseek_client (helper non-DeepSeek-specifici):
- _build_user_prompt, _sanitize_text, _load_universal_prompt
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

from v2.stream_buffer import DEFAULT_MAX_CHARS, StreamBuffer, StreamResult
from v2.yaml_stream_parser import ParsedMarker, YamlStreamParser

from .deepseek_client import (
    _build_user_prompt,
    _load_universal_prompt,
    _sanitize_text,
)
from .provider_profiles import ProviderProfile


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

# Pacing & retry
MAX_STREAM_RETRIES = 3  # aumentato da 1 a 3 per tollerare meglio rate limit 429 cumulativi
RETRY_BASE_DELAY_SECONDS = 2.0  # aumentato da 0.5 a 2 secondi (backoff più rispettoso)
RETRY_MAX_DELAY_SECONDS = 60.0  # aumentato da 16 a 60 secondi (Azure può richiedere attese lunghe)
INTER_CHUNK_TIMEOUT = 90.0


# ──────────────────────────────────────────────────────────────────────────────
# Cap caratteri per documento — scalati dal profile.doc_cap_multiplier
# ──────────────────────────────────────────────────────────────────────────────

# Cap base = cap V2 PROD attuale. Il moltiplicatore arriva dal ProviderProfile.
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
# Client wrapper
# ──────────────────────────────────────────────────────────────────────────────

_DEPLOYMENT_ENV = {
    "gpt-4.1-mini": "AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI",
}


class AzureOpenAIClient:
    """
    Wrapper minimal per Azure AI Foundry v1 ChatCompletions con streaming.

    Usa l'OpenAI SDK standard (NON AzureOpenAI) perché il nuovo endpoint
    Foundry `services.ai.azure.com/openai/v1` è 100% OpenAI-compatible.

    Compatibilità: nei test, può essere mockato sostituendo il metodo `chat_stream`.
    """

    def __init__(
        self,
        profile: ProviderProfile,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
    ):
        if profile.api_kind != "azure_openai":
            raise ValueError(
                f"AzureOpenAIClient richiede api_kind=azure_openai, ricevuto: {profile.api_kind}"
            )
        self.profile = profile

        api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        endpoint = endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
        if not api_key:
            raise ValueError("AZURE_OPENAI_API_KEY non settato.")
        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT non settato.")

        # Lazy import per non richiedere openai installato se non si usa Azure
        from openai import OpenAI  # type: ignore
        # Foundry v1 endpoint = OpenAI-compatible: usa OpenAI SDK con base_url
        self._sdk = OpenAI(
            base_url=endpoint,
            api_key=api_key,
        )
        self.deployment = self._resolve_deployment(profile)

    @staticmethod
    def _resolve_deployment(profile: ProviderProfile) -> str:
        env_name = _DEPLOYMENT_ENV.get(profile.key)
        if not env_name:
            raise ValueError(
                f"Profilo Azure non riconosciuto: {profile.key}. "
                f"Mapping disponibile: {list(_DEPLOYMENT_ENV.keys())}"
            )
        deployment = os.environ.get(env_name, "").strip()
        if not deployment:
            raise ValueError(
                f"{env_name} non settato. Imposta il nome deployment Azure "
                f"per il modello {profile.key}."
            )
        return deployment

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
    ):
        """
        Yields stream chunk objects (OpenAI SDK).
        Solleva openai.RateLimitError, openai.APIConnectionError, ecc.
        """
        return self._sdk.chat.completions.create(
            model=self.deployment,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            temperature=0.0,
            max_tokens=max_tokens or self.profile.max_output_tokens,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Eccezione interna per retry transient
# ──────────────────────────────────────────────────────────────────────────────

class _StreamRetryable(Exception):
    """Errore transient: meritevole di retry con backoff."""
    pass


class AzureRateLimitExhausted(Exception):
    """
    Sollevato quando tutti i retry per rate_limit (429) sono falliti.
    Il pipeline può catturarla per attivare il fallback a un altro provider
    (es. Gemini baseline).

    Attributes:
        batch_idx: indice del batch
        n_retries: numero di retry tentati
        last_error: ultimo messaggio d'errore Azure
    """

    def __init__(self, batch_idx: int, n_retries: int, last_error: str):
        self.batch_idx = batch_idx
        self.n_retries = n_retries
        self.last_error = last_error
        super().__init__(
            f"Azure rate limit exhausted on batch {batch_idx} after {n_retries} retries: {last_error}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# API streaming principale (drop-in replacement per gemini_client_v2)
# ──────────────────────────────────────────────────────────────────────────────

def analyze_batch_streaming(
    client: AzureOpenAIClient,
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
    Analizza un batch di documenti via streaming Azure OpenAI.

    Stesso contratto di `gemini_client_v2.analyze_batch_streaming` per drop-in
    compat. `cached_content_id` è ignorato (Azure caching automatico).

    Side effect: se finish_reason == "length", il StreamResult ritornato avrà
    attributo `truncated_output=True` (non parte del dataclass V2 originale).
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
        batch_docs, batch_idx, total_docs, compact_mode=compact_mode,
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
                f"[SPIKE Azure] Batch {batch_idx} interrotto ({last_error}), "
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
    # Se l'ultimo errore è un rate_limit, solleva AzureRateLimitExhausted
    # così il pipeline può attivare il fallback a un altro provider.
    if last_error and "rate_limit" in last_error.lower():
        raise AzureRateLimitExhausted(
            batch_idx=batch_idx,
            n_retries=max_attempts,
            last_error=last_error,
        )
    # Per errori non-rate-limit, ritorna StreamResult con error (comportamento legacy)
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
    client: AzureOpenAIClient,
    messages: List[Dict[str, str]],
    buf: StreamBuffer,
    parser: YamlStreamParser,
    meter_session_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    retry_count: int = 0,
    model: str = "",
    call_start: Optional[float] = None,
) -> StreamResult:
    """
    Esegue una singola chiamata streaming. Solleva _StreamRetryable su errori
    transient (429, 503, network), ritorna StreamResult finalizzato altrimenti.
    """
    if call_start is None:
        call_start = time.monotonic()
    last_chunk_time = time.monotonic()
    last_usage = None
    finish_reason: Optional[str] = None

    # Lazy import openai exceptions per non richiedere il pacchetto se non usato
    try:
        from openai import (  # type: ignore
            APIConnectionError,
            APIError,
            APIStatusError,
            BadRequestError,
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
                        # Cap raggiunto, continua a drainare
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
                # Fix: Azure restituisce cached_tokens incluso in prompt_tokens.
                # token_meter pricing assume input_tokens al prezzo full e cached
                # al prezzo cached, quindi sottraggo i cached da input.
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
        # Aggiunge attributo dinamico su StreamResult per propagare il flag
        # truncation. pipeline_spike lo legge per popolare n_truncated_responses.
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
        # Generic — per default consideriamo retryable
        raise _StreamRetryable(f"api_error: {e}")
