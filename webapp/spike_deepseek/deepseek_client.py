"""
V2 Spike — DeepSeek V4 Flash Client.

Replica di `webapp/v2/gemini_client_v2.py` per DeepSeek V4 Flash via API
OpenAI-ChatCompletions-compat. Usa `requests` per evitare di aggiungere
nuove dipendenze (no SDK openai).

Differenze chiave vs Gemini client:
- Endpoint: https://api.deepseek.com/v1/chat/completions
- Auth: Authorization: Bearer <DEEPSEEK_API_KEY>
- Caching: AUTOMATICO (prefix matching server-side, no API call)
- Streaming: SSE OpenAI format (data: {...}\\n\\n)
- Token usage: response.usage con prompt_cache_hit_tokens / prompt_cache_miss_tokens

Cap doc per documento PIÙ ALTI di V2 (sfrutta pricing 9× più economico):
- Visure 80k char (vs 30k V2)
- DVR/POS/Bilancio 60k (vs 25k V2)
- Default 25k (vs 12k V2)

Riusa da V2 (zero modifiche):
- StreamBuffer, StreamResult, DEFAULT_MAX_CHARS (stream_buffer)
- YamlStreamParser (yaml_stream_parser)
- token_meter.record_call (con model="deepseek-v4-flash")
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from v2.stream_buffer import DEFAULT_MAX_CHARS, StreamBuffer, StreamResult
from v2.yaml_stream_parser import ParsedMarker, YamlStreamParser


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# Pacing & retry (best practice WaveSpeedAI per produzione)
MAX_STREAM_RETRIES = 1
RETRY_BASE_DELAY_SECONDS = 0.5
RETRY_MAX_DELAY_SECONDS = 16.0
INTER_CHUNK_TIMEOUT = 90.0  # leggermente più alto del Gemini (latenza CN)
REQUEST_TIMEOUT_CONNECT = 10.0
REQUEST_TIMEOUT_READ = 600.0  # 10 min, conservativo per long generation

# Cap output dinamico per evitare runaway
DEFAULT_MAX_OUTPUT_TOKENS = 8192

# Path del prompt spike. Variante selezionabile via SPIKE_PROMPT_VARIANT
# ("v1" = base prompt V1 PROD originale + regola PRELIMINARE; "v2" = prompt V2
# con i 6 fix Fase 2 + regola PRELIMINARE). Default: v2.
_WEBAPP_DIR = Path(__file__).resolve().parent.parent


def _resolve_prompt_path() -> Path:
    """Risolve la variante del prompt spike da env."""
    variant = os.environ.get("SPIKE_PROMPT_VARIANT", "v2").strip().lower()
    fname = f"universal_evidence_prompt_spike_deepseek_{variant}.md"
    return _WEBAPP_DIR / "prompts" / fname


DEFAULT_PROMPT_PATH = _resolve_prompt_path()


# ──────────────────────────────────────────────────────────────────────────────
# Cap caratteri per documento — 2.5× più alti di V2 grazie al pricing DeepSeek
# ──────────────────────────────────────────────────────────────────────────────

_DOC_CAP_PATTERNS_SPIKE = (
    (("visura", "camerale", "cciaa", "rea", "registro imprese"), 80_000),
    (("dvr", "valutazione rischi", "valutazione dei rischi"), 60_000),
    (("statuto", "atto costitutivo", "atto notarile"), 60_000),
    (("bilancio", "esg", "sostenibilita", "gri", "esrs", "csrd"), 60_000),
    (("analisi energetica", "iso 50001", "enpi", "see "), 50_000),
    (("ghg", "inventario emissioni", "iso 14064", "carbon"), 50_000),
    (("iso 9001", "iso 14001", "iso 45001", "iso 27001",
      "iso 37001", "iso 39001", "soa ", "rating legalita"), 40_000),
)
_DOC_CAP_DEFAULT_SPIKE = 25_000


def _doc_char_cap_spike(filename: str, content: str) -> int:
    """Cap caratteri per singolo documento — versione SPIKE (cap 2.5× V2)."""
    fn = (filename or "").lower().replace("_", " ").replace("-", " ")
    head = (content or "")[:1500].lower().replace("_", " ").replace("-", " ")
    for patterns, cap in _DOC_CAP_PATTERNS_SPIKE:
        for pat in patterns:
            if pat in fn or pat in head:
                return cap
    return _DOC_CAP_DEFAULT_SPIKE


def _create_smart_batches_spike(
    documents: List[Dict[str, Any]],
    max_files: int = 12,
    max_chars: int = 200_000,
) -> List[List[Dict[str, Any]]]:
    """
    First Fit Decreasing per char count — versione SPIKE con cap più alti.
    Identico algoritmo di V2 ma soglie 3-4× più ampie per sfruttare il
    contesto 1M di DeepSeek e ridurre overhead per call.
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
# Sanitizzazione testo (riusato pattern V2)
# ──────────────────────────────────────────────────────────────────────────────

def _sanitize_text(text: str) -> str:
    """Rimuove caratteri di controllo problematici."""
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = "".join(c for c in text if ord(c) >= 32 or c in "\n\t\r")
    text = text.replace("\x0b", " ").replace("\x0c", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


# ──────────────────────────────────────────────────────────────────────────────
# Prompt loader
# ──────────────────────────────────────────────────────────────────────────────

def _load_universal_prompt(prompt_path: Optional[Path] = None) -> str:
    """
    Legge il prompt universale spike. Stringa vuota se non leggibile.
    Ricalcola la variante a ogni call per supportare env var dinamico.
    """
    path = prompt_path or _resolve_prompt_path()
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[V2 SPIKE] Impossibile leggere {path}: {e}")
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# Prompt builder (cap doc spike)
# ──────────────────────────────────────────────────────────────────────────────

def _build_user_prompt(
    batch_docs: List[Dict[str, Any]],
    batch_idx: int,
    total_docs: int,
    compact_mode: bool = False,
) -> str:
    """Costruisce il prompt utente per DeepSeek con cap doc spike."""
    parts = []
    for i, d in enumerate(batch_docs):
        fname = d.get("filename", "sconosciuto")
        content = _sanitize_text(d.get("content") or d.get("extracted_text") or "")
        cap = _doc_char_cap_spike(fname, content)
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
# DeepSeek client (lazy session per riuso connection pool)
# ──────────────────────────────────────────────────────────────────────────────

class DeepSeekClient:
    """
    Wrapper minimal per DeepSeek V4 Flash API ChatCompletions-compat.

    Compatibilità: nei test, può essere mockato sostituendo il metodo `chat_stream`.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: str = DEEPSEEK_BASE_URL):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY non settato. Aggiungi la chiave a "
                "ENV o passa api_key esplicitamente."
            )
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = DEEPSEEK_MODEL,
        temperature: float = 0.0,
        max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        """
        Yields stream chunks (dict from SSE data lines).
        Solleva requests.HTTPError per errori HTTP, ConnectionError per network.
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        with self.session.post(
            url,
            json=payload,
            stream=True,
            timeout=(REQUEST_TIMEOUT_CONNECT, REQUEST_TIMEOUT_READ),
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith(": "):
                    # SSE keep-alive comment, skip
                    continue
                if line.startswith("data: "):
                    payload_str = line[6:]
                    if payload_str.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(payload_str)
                    except json.JSONDecodeError:
                        # Malformed chunk, skip rather than die
                        continue
                    yield chunk


# ──────────────────────────────────────────────────────────────────────────────
# Eccezione interna per retry transient
# ──────────────────────────────────────────────────────────────────────────────

class _StreamRetryable(Exception):
    """Errore transient: meritevole di retry con backoff."""
    pass


# ──────────────────────────────────────────────────────────────────────────────
# API streaming principale (drop-in replacement per gemini_client_v2)
# ──────────────────────────────────────────────────────────────────────────────

def analyze_batch_streaming(
    client: DeepSeekClient,
    batch_docs: List[Dict[str, Any]],
    batch_idx: int = 0,
    total_docs: int = 0,
    universal_prompt: Optional[str] = None,
    cached_content_id: Optional[str] = None,  # ignorato (DeepSeek auto-cache)
    on_token: Optional[Callable[[str], None]] = None,
    on_marker: Optional[Callable[[ParsedMarker], None]] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    enable_retry: bool = True,
    meter_session_id: Optional[str] = None,
    compact_mode: bool = False,
    model_override: Optional[str] = None,
) -> StreamResult:
    """
    Analizza un batch di documenti via streaming DeepSeek V4 Flash.

    Stesso contratto di `gemini_client_v2.analyze_batch_streaming` per drop-in
    compat. `cached_content_id` è ignorato (DeepSeek caching automatico).
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
    messages = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": user_prompt})

    last_error: Optional[str] = None
    batch_label = f"batch_{batch_idx:03d}"
    effective_model = model_override or DEEPSEEK_MODEL

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
                f"[V2 SPIKE] Batch {batch_idx} interrotto ({last_error}), "
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
            if meter_session_id:
                try:
                    from v2 import token_meter
                    token_meter.record_call(
                        session_id=meter_session_id,
                        model=effective_model,
                        kind="analyze",
                        retry_count=attempt,
                        error=f"non_retryable: {e}",
                        batch_id=batch_label,
                        duration_seconds=duration,
                    )
                except Exception:
                    pass
            return buf.finalize(error=f"non_retryable: {e}")

    # Tutti i retry falliti
    if meter_session_id:
        try:
            from v2 import token_meter
            token_meter.record_call(
                session_id=meter_session_id,
                model=effective_model,
                kind="analyze",
                retry_count=max_attempts - 1,
                error=f"all_retries_failed: {last_error}",
                batch_id=batch_label,
            )
        except Exception:
            pass
    return buf.finalize(error=f"all_retries_failed: {last_error}")


def _do_streaming_call(
    client: DeepSeekClient,
    messages: List[Dict[str, str]],
    buf: StreamBuffer,
    parser: YamlStreamParser,
    meter_session_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    retry_count: int = 0,
    model: str = DEEPSEEK_MODEL,
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

    try:
        for chunk in client.chat_stream(messages=messages, model=model):
            now = time.monotonic()
            if now - last_chunk_time > INTER_CHUNK_TIMEOUT:
                raise _StreamRetryable(
                    f"inter_chunk_timeout: nessun chunk per {INTER_CHUNK_TIMEOUT}s"
                )
            last_chunk_time = now

            # OpenAI SSE format: chunk = {choices: [{delta: {content: "..."}}], usage: ...}
            choices = chunk.get("choices") or []
            if choices:
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if delta:
                    can_continue = buf.append_text(delta)
                    if not can_continue:
                        # Cap raggiunto, continua a drainare lo stream
                        continue
            # Usage solitamente nell'ultimo chunk con stream_options.include_usage=True
            if chunk.get("usage"):
                last_usage = chunk["usage"]

        parser.finalize()
        duration = round(time.monotonic() - call_start, 3)

        # Token metering
        if meter_session_id and last_usage:
            try:
                from v2 import token_meter
                # DeepSeek usage fields:
                # - prompt_tokens: total input
                # - prompt_cache_hit_tokens: cached read
                # - prompt_cache_miss_tokens: fresh read (= prompt - cache_hit)
                # - completion_tokens: output
                input_tokens = int(last_usage.get("prompt_tokens", 0) or 0)
                cache_hit = int(last_usage.get("prompt_cache_hit_tokens", 0) or 0)
                output_tokens = int(last_usage.get("completion_tokens", 0) or 0)
                token_meter.record_call(
                    session_id=meter_session_id,
                    model=model,
                    kind="analyze",
                    input_tokens=input_tokens,
                    cached_tokens=cache_hit,
                    output_tokens=output_tokens,
                    duration_seconds=duration,
                    retry_count=retry_count,
                    batch_id=batch_id,
                )
            except Exception as e:
                print(f"[V2 SPIKE] meter record fallito: {e}")
        return buf.finalize()

    except _StreamRetryable:
        raise
    except requests.HTTPError as e:
        # HTTP error (429, 5xx → retry; 4xx altri → no retry)
        status = e.response.status_code if e.response is not None else 0
        if status in (429, 502, 503, 504):
            raise _StreamRetryable(f"http_{status}: {e}") from e
        # Auth/config error (400, 401, 403, 404) → no retry
        parser.finalize()
        duration = round(time.monotonic() - call_start, 3)
        if meter_session_id:
            try:
                from v2 import token_meter
                token_meter.record_call(
                    session_id=meter_session_id,
                    model=model,
                    kind="analyze",
                    duration_seconds=duration,
                    retry_count=retry_count,
                    error=f"http_{status}: {e}",
                    batch_id=batch_id,
                )
            except Exception:
                pass
        return buf.finalize(error=f"http_{status}: {e}")
    except (requests.ConnectionError, requests.Timeout) as e:
        # Network transient → retry
        raise _StreamRetryable(f"network: {e}") from e
    except Exception as e:
        # Unknown exception → finalize partial + record error
        parser.finalize()
        duration = round(time.monotonic() - call_start, 3)
        if meter_session_id:
            try:
                from v2 import token_meter
                token_meter.record_call(
                    session_id=meter_session_id,
                    model=model,
                    kind="analyze",
                    duration_seconds=duration,
                    retry_count=retry_count,
                    error=f"stream_error: {e}",
                    batch_id=batch_id,
                )
            except Exception:
                pass
        return buf.finalize(error=f"stream_error: {e}")
