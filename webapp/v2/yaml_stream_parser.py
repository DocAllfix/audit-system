"""
V2 — YAML Stream Parser (Fase 5).

Scope ridotto: NON è un parser YAML completo. Riconosce solo i marker
strutturali del prompt universale (`azienda:`, `indice:`, header `### CATEGORIA`,
end-of-document patterns) per emettere eventi SSE precoci.

Il parsing strutturato vero (per generare il docx) avviene in Fase 8 usando
il parser di V1 esistente (`structured_evidence_parser.py`) sul testo finale.

Caratteristiche:
- Stateful: accetta delta testuali, accumula, scansiona patterns
- Mai eccezione: errori → ignorati, lo stream continua
- Idempotente: emettere callback non blocca il parsing
- No regex pesanti: solo `find()` su buffer per performance

API:
    parser = YamlStreamParser(on_marker=lambda kind, name: ...)
    parser.feed(delta_text)
    parser.finalize()
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Marker patterns
# ──────────────────────────────────────────────────────────────────────────────

# Linea che indica inizio del blocco azienda nel meta
RE_META_AZIENDA = re.compile(r"^\s*azienda\s*:\s*$", re.MULTILINE)

# Linea indice
RE_META_INDICE = re.compile(r"^\s*indice\s*:\s*$", re.MULTILINE)

# Heading di sezione/categoria stile "### NN · NOME" oppure "## NN · NOME"
RE_CATEGORY_HEADER = re.compile(
    r"^#{2,6}\s*(\d{1,2})\s*[·\-—]\s*([A-ZÀ-ÚÈÉÌÒÙ][^\n]+)$",
    re.MULTILINE,
)

# Heading scheda documento: "### Scheda doc N" o "## Documento N — Titolo"
RE_DOC_HEADER = re.compile(
    r"^#{2,6}\s*(?:scheda\s+)?(?:doc(?:umento)?)\s*(?:n\.?|nr\.?)?\s*(\d+)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Linea che indica il campo titolo all'interno di una scheda doc
RE_TITOLO = re.compile(r"^\s*titolo\s*:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", re.MULTILINE)

# Linea che indica il campo tipo all'interno di una scheda doc
RE_TIPO = re.compile(r"^\s*tipo\s*:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", re.MULTILINE)


# Tipi di marker che notifichiamo via callback
MARKER_META_AZIENDA = "meta_azienda"
MARKER_META_INDICE = "meta_indice"
MARKER_CATEGORY = "category"
MARKER_DOC = "document"
MARKER_TITOLO = "doc_titolo"
MARKER_TIPO = "doc_tipo"


@dataclass
class ParsedMarker:
    """Singolo marker individuato nello stream."""
    kind: str
    name: str = ""
    extra: dict = field(default_factory=dict)


class YamlStreamParser:
    """
    Parser tolerante a chunks parziali.

    Mantiene un buffer interno con il testo accumulato. Su ogni `feed`,
    scansiona la nuova parte di buffer cercando marker, ed emette callback.

    Per evitare di rilevare lo stesso marker N volte mentre il buffer cresce,
    teniamo traccia della posizione fino a cui abbiamo già scansionato
    (`_scan_offset`).
    """

    def __init__(
        self,
        on_marker: Optional[Callable[[ParsedMarker], None]] = None,
        max_buffer_chars: int = 1_000_000,
    ):
        self._buffer: List[str] = []
        self._buffer_size: int = 0
        self._scan_offset: int = 0
        self._max_buffer_chars = max_buffer_chars
        self._on_marker = on_marker
        self._markers_found: List[ParsedMarker] = []

    def feed(self, delta: str) -> None:
        """Aggiunge testo al buffer e scansiona per nuovi marker."""
        if not delta:
            return

        self._buffer.append(delta)
        self._buffer_size += len(delta)

        # Cap difensivo sul buffer (evita memory leak su stream patologici)
        if self._buffer_size > self._max_buffer_chars:
            # Rimuoviamo le parti più vecchie ma manteniamo l'offset coerente
            joined = "".join(self._buffer)
            keep = joined[-self._max_buffer_chars // 2:]
            consumed = self._buffer_size - len(keep)
            self._buffer = [keep]
            self._buffer_size = len(keep)
            self._scan_offset = max(0, self._scan_offset - consumed)

        self._scan()

    def _emit(self, marker: ParsedMarker) -> None:
        self._markers_found.append(marker)
        if self._on_marker is not None:
            try:
                self._on_marker(marker)
            except Exception:
                pass  # Mai propagare errori del consumer

    def _scan(self) -> None:
        """Scansiona il buffer dal `_scan_offset` in poi."""
        text = "".join(self._buffer)
        # Per evitare di matchare patterns che potrebbero essere divisi tra
        # questo feed e il prossimo, lasciamo un margine non scansionato
        # alla fine. 256 char è sufficiente per tutti i pattern definiti.
        margin = 256
        scan_end = max(self._scan_offset, len(text) - margin)
        if scan_end <= self._scan_offset:
            return

        window = text[self._scan_offset:scan_end]
        offset_base = self._scan_offset

        # Meta azienda (singolo, non si ripete)
        for m in RE_META_AZIENDA.finditer(window):
            self._emit(ParsedMarker(kind=MARKER_META_AZIENDA))

        # Meta indice
        for m in RE_META_INDICE.finditer(window):
            self._emit(ParsedMarker(kind=MARKER_META_INDICE))

        # Category headers
        for m in RE_CATEGORY_HEADER.finditer(window):
            self._emit(ParsedMarker(
                kind=MARKER_CATEGORY,
                name=f"{m.group(1)} · {m.group(2).strip()}",
            ))

        # Document headers
        for m in RE_DOC_HEADER.finditer(window):
            self._emit(ParsedMarker(
                kind=MARKER_DOC,
                name=f"doc_{m.group(1)}",
            ))

        # Titolo + Tipo (campi YAML interni alle schede)
        for m in RE_TITOLO.finditer(window):
            self._emit(ParsedMarker(
                kind=MARKER_TITOLO,
                name=m.group(1).strip()[:200],
            ))
        for m in RE_TIPO.finditer(window):
            self._emit(ParsedMarker(
                kind=MARKER_TIPO,
                name=m.group(1).strip()[:200],
            ))

        self._scan_offset = scan_end

    def finalize(self) -> List[ParsedMarker]:
        """
        Forza una scansione finale sul margine residuo. Da chiamare quando
        lo stream è terminato.
        """
        # Riscansiona INCLUDENDO la coda
        text = "".join(self._buffer)
        if self._scan_offset < len(text):
            window = text[self._scan_offset:]
            for regex, kind in (
                (RE_META_AZIENDA, MARKER_META_AZIENDA),
                (RE_META_INDICE, MARKER_META_INDICE),
            ):
                for _ in regex.finditer(window):
                    self._emit(ParsedMarker(kind=kind))
            for m in RE_CATEGORY_HEADER.finditer(window):
                self._emit(ParsedMarker(
                    kind=MARKER_CATEGORY,
                    name=f"{m.group(1)} · {m.group(2).strip()}",
                ))
            for m in RE_DOC_HEADER.finditer(window):
                self._emit(ParsedMarker(kind=MARKER_DOC, name=f"doc_{m.group(1)}"))
            for m in RE_TITOLO.finditer(window):
                self._emit(ParsedMarker(kind=MARKER_TITOLO, name=m.group(1).strip()[:200]))
            for m in RE_TIPO.finditer(window):
                self._emit(ParsedMarker(kind=MARKER_TIPO, name=m.group(1).strip()[:200]))
            self._scan_offset = len(text)
        return list(self._markers_found)

    @property
    def markers(self) -> List[ParsedMarker]:
        return list(self._markers_found)
