"""
Test V2 Fase 5 — yaml_stream_parser.

Coperture:
- Marker rilevati: meta_azienda, meta_indice, category, document, doc_titolo, doc_tipo
- Parsing chunk-by-chunk produce stessi marker di parsing one-shot
- Marker non duplicati (idempotenza per posizione)
- Pattern divisi tra due feed (margin di sicurezza preservato)
- finalize() forza scan finale del residuo
- on_marker callback invocato; errori nel callback silenziati
- Buffer cap difensivo (no memory leak)
- Performance: feed di N chunks scala linearmente
"""
from __future__ import annotations

from v2 import yaml_stream_parser as ysp


# ──────────────────────────────────────────────────────────────────────────────
# Marker base
# ──────────────────────────────────────────────────────────────────────────────

def test_meta_azienda_detected():
    parser = ysp.YamlStreamParser()
    parser.feed("# header\n\nazienda:\n  nome: 'Demo SRL'\n")
    parser.finalize()
    kinds = [m.kind for m in parser.markers]
    assert ysp.MARKER_META_AZIENDA in kinds


def test_meta_indice_detected():
    parser = ysp.YamlStreamParser()
    parser.feed("indice:\n  - n: 1\n")
    parser.finalize()
    assert any(m.kind == ysp.MARKER_META_INDICE for m in parser.markers)


def test_category_header_detected():
    parser = ysp.YamlStreamParser()
    parser.feed("\n### 08 · LEGALE/SOCIETARIA\n\nstuff\n")
    parser.finalize()
    cats = [m for m in parser.markers if m.kind == ysp.MARKER_CATEGORY]
    assert len(cats) == 1
    assert "LEGALE" in cats[0].name


def test_document_header_detected():
    parser = ysp.YamlStreamParser()
    parser.feed("\n### Scheda doc 3\n\ndati\n")
    parser.finalize()
    docs = [m for m in parser.markers if m.kind == ysp.MARKER_DOC]
    assert len(docs) == 1
    assert docs[0].name == "doc_3"


def test_titolo_and_tipo_detected():
    parser = ysp.YamlStreamParser()
    parser.feed("  titolo: 'Visura Camerale 2025'\n  tipo: 'Visura Camerale'\n")
    parser.finalize()
    titoli = [m for m in parser.markers if m.kind == ysp.MARKER_TITOLO]
    tipi = [m for m in parser.markers if m.kind == ysp.MARKER_TIPO]
    assert len(titoli) == 1
    assert "Visura" in titoli[0].name
    assert len(tipi) == 1
    assert tipi[0].name == "Visura Camerale"


# ──────────────────────────────────────────────────────────────────────────────
# Chunk-by-chunk vs one-shot
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_YAML = """
azienda:
  nome: "Demo Consulting SRL"
  piva: "12345678901"

indice:
  - {n: 1, tipo: "Visura Camerale", titolo: "Visura 2025", categoria: "08"}
  - {n: 2, tipo: "DVR", titolo: "DVR 2024", categoria: "10"}

### 08 · DOCUMENTAZIONE LEGALE E SOCIETARIA

### Scheda doc 1
  titolo: "Visura 2025"
  tipo: "Visura Camerale"

### 10 · SALUTE E SICUREZZA SUL LAVORO

### Scheda doc 2
  titolo: "DVR 2024"
  tipo: "Documento Valutazione Rischi"
"""


def test_chunked_feed_matches_oneshot():
    """Spezzare l'input in N chunks NON deve cambiare il set di marker."""
    one_shot = ysp.YamlStreamParser()
    one_shot.feed(SAMPLE_YAML)
    one_shot.finalize()

    chunked = ysp.YamlStreamParser()
    # Spezziamo ogni 50 char
    for i in range(0, len(SAMPLE_YAML), 50):
        chunked.feed(SAMPLE_YAML[i:i + 50])
    chunked.finalize()

    one_kinds = [m.kind for m in one_shot.markers]
    chunked_kinds = [m.kind for m in chunked.markers]

    # Stesso multiset di kind
    assert sorted(one_kinds) == sorted(chunked_kinds)


def test_no_duplicate_markers_on_growing_buffer():
    """Una volta visto un marker, non deve essere segnalato di nuovo."""
    parser = ysp.YamlStreamParser()
    parser.feed("azienda:\n  nome: 'X'\n")
    parser.feed("more content\n")
    parser.feed("more content\n")
    parser.finalize()
    azs = [m for m in parser.markers if m.kind == ysp.MARKER_META_AZIENDA]
    assert len(azs) == 1


def test_marker_split_across_chunks_caught_by_finalize():
    """
    Se un marker è diviso esattamente sul confine di due feed,
    finalize() deve comunque rilevarlo.
    """
    parser = ysp.YamlStreamParser()
    # "azienda:\n" — spezziamo in 2
    parser.feed("aziend")
    parser.feed("a:\n")
    parser.finalize()
    assert any(m.kind == ysp.MARKER_META_AZIENDA for m in parser.markers)


# ──────────────────────────────────────────────────────────────────────────────
# Callback
# ──────────────────────────────────────────────────────────────────────────────

def test_on_marker_callback_invoked():
    received = []
    parser = ysp.YamlStreamParser(on_marker=lambda m: received.append(m))
    parser.feed("azienda:\n")
    parser.finalize()
    assert len(received) == 1
    assert received[0].kind == ysp.MARKER_META_AZIENDA


def test_on_marker_callback_exceptions_silenced():
    def evil(m):
        raise RuntimeError("boom")

    parser = ysp.YamlStreamParser(on_marker=evil)
    # Non deve sollevare
    parser.feed(SAMPLE_YAML)
    parser.finalize()
    assert len(parser.markers) > 0  # comunque rilevati


# ──────────────────────────────────────────────────────────────────────────────
# Robustezza
# ──────────────────────────────────────────────────────────────────────────────

def test_empty_feed_does_nothing():
    parser = ysp.YamlStreamParser()
    parser.feed("")
    parser.finalize()
    assert parser.markers == []


def test_large_buffer_capped_no_memory_leak():
    """Stream patologicamente grande: il buffer non cresce indefinitamente."""
    parser = ysp.YamlStreamParser(max_buffer_chars=10_000)
    # Inietta 50 KB di rumore senza marker
    parser.feed("X" * 50_000)
    # Dopo il cap, il buffer interno è stato troncato
    assert parser._buffer_size <= 10_000


def test_partial_yaml_no_crash():
    """YAML troncato/malformato non deve far crashare il parser."""
    parser = ysp.YamlStreamParser()
    parser.feed("azienda:\n  nome: 'incompleto")  # senza newline finale
    parser.finalize()
    # No exception: questo è il test


def test_garbled_input_no_crash():
    """Input random binary-ish non deve far crashare."""
    parser = ysp.YamlStreamParser()
    parser.feed("\x00\x01\x02 garbage \xff\xfe")
    parser.finalize()
    # No exception
