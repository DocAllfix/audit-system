"""
V2 — Stream Buffer (Fase 5).

Accumula chunks da `generate_content_stream` con:
- Hard cap 400k chars (configurabile via env V2_MAX_RESPONSE_CHARS)
- Detection truncation con flag `truncated=True`
- Detection stream interrotto con flag `partial=True`
- Cancellazione esplicita via `abort()`
- Callback per emettere chunks via SSE in tempo reale
- Mai eccezione: errori vengono catturati e segnalati nei flag

Uso tipico:
    buf = StreamBuffer(on_chunk=lambda txt: emitter.emit_token(batch_idx, txt))
    for chunk in client.models.generate_content_stream(...):
        if not buf.append_chunk(chunk):
            break  # cap raggiunto, smetti di accumulare ma continua a drain
    result = buf.finalize()
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# Cap di sicurezza: oltre questa soglia, trunchiamo per evitare crash lxml
DEFAULT_MAX_CHARS = int(os.environ.get("V2_MAX_RESPONSE_CHARS", "400000"))

# Soglia per "slow consumer": se il buffer cresce oltre per troppo tempo
# senza essere consumato dal caller, emettiamo warning
SLOW_CONSUMER_WARN_CHARS = 100_000

# Tag esplicito di troncamento (visibile nei log e nell'output finale)
TRUNCATION_TAG = "\n[V2 STREAM TRONCATO PER CAP DI SICUREZZA]\n"


@dataclass
class StreamResult:
    """Esito finale dello stream, restituito da StreamBuffer.finalize()."""
    text: str
    truncated: bool = False        # True se hard cap raggiunto
    partial: bool = False          # True se stream interrotto prematuramente
    aborted: bool = False          # True se chiamato abort() esplicitamente
    error: Optional[str] = None    # Eccezione catturata, se presente
    chunks_count: int = 0
    duration_seconds: float = 0.0


class StreamBuffer:
    """
    Buffer che accumula chunks di testo con cap di sicurezza.

    Thread-safety: progettato per essere usato da UN thread che fa drain
    dello stream. Il flag `_aborted` può essere settato da un altro thread
    per cancellazione cooperativa.
    """

    def __init__(
        self,
        max_chars: int = DEFAULT_MAX_CHARS,
        on_chunk: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            max_chars: cap totale sul buffer accumulato (default 400k)
            on_chunk: callback opzionale invocata per ogni chunk ricevuto
                      (utile per SSE streaming in tempo reale).
                      Riceve il testo del chunk (delta).
                      Errori nel callback vengono ignorati per non rompere lo stream.
        """
        self.max_chars = max_chars
        self._on_chunk = on_chunk
        self._parts: List[str] = []
        self._chars: int = 0
        self._chunks_count: int = 0
        self._truncated: bool = False
        self._aborted: bool = False
        self._error: Optional[str] = None
        self._started_at: float = time.monotonic()

    # ──────────────────────────────────────────────────────────────────────
    # Append API
    # ──────────────────────────────────────────────────────────────────────

    def append_chunk(self, chunk) -> bool:
        """
        Accumula un chunk (oggetto `GenerateContentResponse` o stringa).

        Returns:
            True se possiamo continuare ad accumulare, False se cap raggiunto
            o abort esplicito (caller dovrebbe drain lo stream ma non più
            chiamare append).
        """
        if self._aborted:
            return False

        # Estrai testo dal chunk (tolleranza ai vari formati SDK)
        text = self._extract_text_from_chunk(chunk)
        if not text:
            self._chunks_count += 1
            return True  # chunk vuoto, ok continuare

        return self._append_text(text)

    def append_text(self, text: str) -> bool:
        """Variante diretta per test: accumula stringa pre-estratta."""
        if self._aborted:
            return False
        return self._append_text(text)

    def _append_text(self, text: str) -> bool:
        if self._truncated:
            # Una volta truncato, scartiamo tutto il resto silenziosamente
            self._chunks_count += 1
            return False

        # Cap check: se l'aggiunta supererebbe il limite, taglia + flag truncated
        remaining = self.max_chars - self._chars
        if remaining <= 0:
            self._truncated = True
            self._chunks_count += 1
            return False

        if len(text) > remaining:
            # Tronca l'ultimo chunk al limite esatto
            text = text[:remaining]
            self._truncated = True

        self._parts.append(text)
        self._chars += len(text)
        self._chunks_count += 1

        # Callback SSE (best-effort, errori silenziati)
        if self._on_chunk is not None:
            try:
                self._on_chunk(text)
            except Exception:
                # Mai propagare errori del consumer al producer
                pass

        return not self._truncated

    # ──────────────────────────────────────────────────────────────────────
    # Estrazione testo dal chunk SDK genai
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_text_from_chunk(chunk) -> str:
        """
        I chunks SDK genai possono avere `.text` o `.candidates[0].content.parts`.
        Tollerante: ritorna "" se nessun formato corrisponde.
        """
        if isinstance(chunk, str):
            return chunk

        # Path 1: chunk.text
        text = getattr(chunk, "text", None)
        if isinstance(text, str) and text:
            return text

        # Path 2: chunk.candidates[0].content.parts[*].text
        candidates = getattr(chunk, "candidates", None)
        if candidates:
            try:
                cand0 = candidates[0]
                content = getattr(cand0, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if parts:
                    out = []
                    for p in parts:
                        ptext = getattr(p, "text", None)
                        if isinstance(ptext, str) and ptext:
                            out.append(ptext)
                    if out:
                        return "".join(out)
            except Exception:
                pass

        return ""

    # ──────────────────────────────────────────────────────────────────────
    # Controllo
    # ──────────────────────────────────────────────────────────────────────

    def abort(self) -> None:
        """Cancella cooperativamente: il prossimo append_chunk ritornerà False."""
        self._aborted = True

    def mark_partial(self, error: Optional[str] = None) -> None:
        """Segna che lo stream è stato interrotto prematuramente."""
        self._error = error

    # ──────────────────────────────────────────────────────────────────────
    # Status
    # ──────────────────────────────────────────────────────────────────────

    @property
    def chars(self) -> int:
        return self._chars

    @property
    def truncated(self) -> bool:
        return self._truncated

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def is_slow_consumer(self) -> bool:
        """True se il buffer è cresciuto oltre soglia warning."""
        return self._chars >= SLOW_CONSUMER_WARN_CHARS

    # ──────────────────────────────────────────────────────────────────────
    # Finalize
    # ──────────────────────────────────────────────────────────────────────

    def finalize(self, error: Optional[str] = None) -> StreamResult:
        """
        Costruisce il risultato finale. Aggiunge tag di troncamento se serve.

        Args:
            error: messaggio errore se lo stream è stato interrotto da eccezione

        Returns:
            StreamResult immutabile.
        """
        text = "".join(self._parts)
        if self._truncated:
            text += TRUNCATION_TAG

        is_partial = bool(error) or self._aborted
        return StreamResult(
            text=text,
            truncated=self._truncated,
            partial=is_partial and not self._truncated,
            aborted=self._aborted,
            error=error or self._error,
            chunks_count=self._chunks_count,
            duration_seconds=round(time.monotonic() - self._started_at, 3),
        )
