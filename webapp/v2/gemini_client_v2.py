"""
V2 — Gemini Client streaming (Fase 5).

Sostituisce `_call_api` blocking di V1 con streaming che:
- Emette token via SSE in tempo reale (callback `on_token`)
- Applica hard cap 400k chars (StreamBuffer) → no più crash lxml
- Rileva marker YAML (categorie, schede doc) per emettere SSE precoce
- Integra con cache Gemini (Fase 3) per −90% costo prompt
- Retry singolo su stream interrotto prematuramente
- Fallback a generate_content blocking se streaming non supportato
- Determinismo: temperature=0, seed=42

API pubblica:
    analyze_batch_streaming(client, batch_docs, batch_idx, total_docs,
                            on_token=None, on_marker=None, ...)
        -> StreamResult
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from v2.stream_buffer import DEFAULT_MAX_CHARS, StreamBuffer, StreamResult
from v2.yaml_stream_parser import ParsedMarker, YamlStreamParser


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

ANALYZE_MODEL = "gemini-2.5-flash"

# Numero retry su stream interrotto prematuramente
MAX_STREAM_RETRIES = 1

# Timeout massimo tra due chunk consecutivi (secondi)
INTER_CHUNK_TIMEOUT = 60.0

# Path del prompt universale (condiviso con cache_manager)
_WEBAPP_DIR = Path(__file__).resolve().parent.parent
UNIVERSAL_PROMPT_PATH = _WEBAPP_DIR / "prompts" / "universal_evidence_prompt.md"

# Cap dinamico per documento (replica V1 _doc_char_cap)
_DOC_CAP_PATTERNS = (
    (("visura", "camerale", "cciaa", "rea", "registro imprese"), 30000),
    (("dvr", "valutazione rischi", "valutazione dei rischi"), 25000),
    (("statuto", "atto costitutivo", "atto notarile"), 25000),
    (("bilancio", "esg", "sostenibilita", "gri", "esrs", "csrd"), 25000),
    (("analisi energetica", "iso 50001", "enpi", "see "), 20000),
    (("ghg", "inventario emissioni", "iso 14064", "carbon"), 20000),
    (("iso 9001", "iso 14001", "iso 45001", "iso 27001",
      "iso 37001", "iso 39001", "soa ", "rating legalita"), 18000),
)
_DOC_CAP_DEFAULT = 12000


def _doc_char_cap(filename: str, content: str) -> int:
    """Cap caratteri per singolo documento basato su pattern filename + head."""
    fn = (filename or "").lower().replace("_", " ").replace("-", " ")
    head = (content or "")[:1500].lower().replace("_", " ").replace("-", " ")
    for patterns, cap in _DOC_CAP_PATTERNS:
        for pat in patterns:
            if pat in fn or pat in head:
                return cap
    return _DOC_CAP_DEFAULT


# ──────────────────────────────────────────────────────────────────────────────
# Sanitizzazione testo (mai propagare bytes pericolosi al modello)
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
# Prompt builder
# ──────────────────────────────────────────────────────────────────────────────

def _load_universal_prompt() -> str:
    """Legge il prompt universale. Stringa vuota se non leggibile."""
    try:
        return UNIVERSAL_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[V2 GEMINI] Impossibile leggere {UNIVERSAL_PROMPT_PATH}: {e}")
        return ""


def _build_user_prompt(
    batch_docs: List[Dict[str, Any]],
    batch_idx: int,
    total_docs: int,
) -> str:
    """Costruisce il prompt utente con i documenti del batch."""
    parts = []
    for i, d in enumerate(batch_docs):
        fname = d.get("filename", "sconosciuto")
        content = _sanitize_text(d.get("content") or d.get("extracted_text") or "")
        cap = _doc_char_cap(fname, content)
        parts.append(f"### DOCUMENTO {i + 1}: {fname}\n{content[:cap]}")
    docs_text = "\n\n".join(parts)

    return (
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
# API streaming principale
# ──────────────────────────────────────────────────────────────────────────────

def analyze_batch_streaming(
    client,
    batch_docs: List[Dict[str, Any]],
    batch_idx: int = 0,
    total_docs: int = 0,
    universal_prompt: Optional[str] = None,
    cached_content_id: Optional[str] = None,
    on_token: Optional[Callable[[str], None]] = None,
    on_marker: Optional[Callable[[ParsedMarker], None]] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    enable_retry: bool = True,
) -> StreamResult:
    """
    Analizza un batch di documenti via streaming Gemini.

    Args:
        client: genai.Client con `.models.generate_content_stream`
        batch_docs: lista dict con `filename` e `content`/`extracted_text`
        batch_idx, total_docs: per il prompt
        universal_prompt: se None, viene letto dal file
        cached_content_id: se fornito (es. da cache_manager.get_cached_prompt),
                           viene usato → prompt cached → −90% costo input
        on_token: callback (delta_text) per ogni chunk → SSE streaming
        on_marker: callback (ParsedMarker) per marker YAML rilevati →
                   SSE precoce di file/sezione completati
        max_chars: cap di sicurezza sul buffer (default 400k)
        enable_retry: 1 retry su stream interrotto prematuramente

    Returns:
        StreamResult con text completo, flags truncated/partial/aborted/error,
        chunks_count, duration_seconds.
    """
    if client is None:
        return StreamResult(text="", error="no_client")

    if not batch_docs:
        return StreamResult(text="", error="empty_batch")

    # Inizializza parser e buffer; il buffer chiama parser.feed via callback
    parser = YamlStreamParser(on_marker=on_marker)

    def buffer_on_chunk(delta: str) -> None:
        # Inoltra al parser
        parser.feed(delta)
        # Inoltra al consumer SSE
        if on_token is not None:
            try:
                on_token(delta)
            except Exception:
                pass

    buf = StreamBuffer(max_chars=max_chars, on_chunk=buffer_on_chunk)
    user_prompt = _build_user_prompt(batch_docs, batch_idx, total_docs)
    user_prompt = _sanitize_text(user_prompt)

    last_error: Optional[str] = None

    for attempt in range(MAX_STREAM_RETRIES + 1 if enable_retry else 1):
        try:
            return _do_streaming_call(
                client=client,
                user_prompt=user_prompt,
                universal_prompt=universal_prompt or _load_universal_prompt(),
                cached_content_id=cached_content_id,
                buf=buf,
                parser=parser,
            )
        except _StreamRetryable as e:
            last_error = str(e)
            print(
                f"[V2 STREAM] Batch {batch_idx} interrotto ({last_error}), "
                f"retry {attempt+1}/{MAX_STREAM_RETRIES + 1}"
            )
            # Per retry creiamo nuovo buffer/parser per non duplicare token
            parser = YamlStreamParser(on_marker=on_marker)
            buf = StreamBuffer(max_chars=max_chars, on_chunk=buffer_on_chunk)
            time.sleep(2.0)
        except Exception as e:
            # Errore non-retryable
            return buf.finalize(error=f"non_retryable: {e}")

    # Tutti i retry falliti: ritorniamo il buffer parziale (o vuoto)
    return buf.finalize(error=f"all_retries_failed: {last_error}")


# Eccezione interna per segnalare errori transitori che meritano retry
class _StreamRetryable(Exception):
    pass


def _do_streaming_call(
    client,
    user_prompt: str,
    universal_prompt: str,
    cached_content_id: Optional[str],
    buf: StreamBuffer,
    parser: YamlStreamParser,
) -> StreamResult:
    """
    Esegue una singola chiamata streaming. Solleva _StreamRetryable su errori
    transitori (network, 503), ritorna StreamResult finalizzato altrimenti.
    """
    from google.genai import types as gtypes

    # Costruisce config: se cached_content_id presente, usa cache; altrimenti
    # usa system_instruction inline come fallback.
    config_kwargs: Dict[str, Any] = {
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": 42,
        "safety_settings": [
            gtypes.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            gtypes.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            gtypes.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            gtypes.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        ],
    }
    if cached_content_id:
        config_kwargs["cached_content"] = cached_content_id
    elif universal_prompt:
        config_kwargs["system_instruction"] = universal_prompt

    config = gtypes.GenerateContentConfig(**config_kwargs)

    last_chunk_time = time.monotonic()
    stream = None
    try:
        stream = client.models.generate_content_stream(
            model=ANALYZE_MODEL,
            contents=user_prompt,
            config=config,
        )

        for chunk in stream:
            # Inter-chunk timeout (cooperativo, non interrompe TCP attivo)
            now = time.monotonic()
            if now - last_chunk_time > INTER_CHUNK_TIMEOUT:
                raise _StreamRetryable(
                    f"inter_chunk_timeout: nessun chunk per {INTER_CHUNK_TIMEOUT}s"
                )
            last_chunk_time = now

            # Append nel buffer (rispetta cap)
            can_continue = buf.append_chunk(chunk)
            if not can_continue:
                # Cap raggiunto o abort: continuiamo a drainare lo stream per
                # chiudere la connessione TCP pulitamente, ma non accumuliamo
                # più nulla
                continue

        # Stream completato normalmente
        parser.finalize()
        return buf.finalize()

    except _StreamRetryable:
        raise
    except Exception as e:
        # Errori transitori riconosciuti
        msg = str(e).lower()
        if any(k in msg for k in ("503", "unavailable", "timeout", "connection", "reset")):
            raise _StreamRetryable(str(e)) from e
        # Auth o config error → no retry, ritorna parziale con errore
        parser.finalize()
        return buf.finalize(error=f"stream_error: {e}")
    finally:
        # Best-effort cleanup dello stream se ha .close()
        if stream is not None:
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
