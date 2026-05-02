"""
Test V2 Fase 8 — yaml_parser.

Coperture:
- parse_aggregated_yaml: 1 batch, multi-batch (--- separator)
- Merge meta.azienda: primo nome valido vince, fields concatenati
- Sezioni dedup per nome (case-insensitive) + concat documenti
- Strip yaml fences ```yaml ... ```
- YAML malformato: tolleranza, salta batch rotti
- Empty input → stub
- extract_company_name: normalizzazione + fallback
- Placeholder come "[RAGIONE SOCIALE...]" rifiutati
"""
from __future__ import annotations

from v2 import yaml_parser as yp


# ──────────────────────────────────────────────────────────────────────────────
# Single batch
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_BATCH_1 = """
meta:
  azienda:
    nome: "DEMO ALPHA SRL"
    piva: "12345678901"

sezioni:
  - id: "08"
    nome: "08 · DOCUMENTAZIONE LEGALE"
    documenti:
      - tipo: "Visura"
        titolo: "Visura 2025"
"""

SAMPLE_BATCH_2 = """
meta:
  azienda:
    nome: "DEMO ALPHA SRL"
    sede: "Via Roma 1"

sezioni:
  - id: "10"
    nome: "10 · SICUREZZA SUL LAVORO"
    documenti:
      - tipo: "DVR"
        titolo: "DVR 2024"
"""


def test_parse_single_batch():
    result = yp.parse_aggregated_yaml(SAMPLE_BATCH_1)
    assert result["meta"]["azienda"]["nome"] == "DEMO ALPHA SRL"
    assert len(result["sezioni"]) == 1
    assert result["sezioni"][0]["nome"] == "08 · DOCUMENTAZIONE LEGALE"
    assert len(result["sezioni"][0]["documenti"]) == 1


def test_parse_multi_batch_aggregates():
    aggregated = SAMPLE_BATCH_1 + "\n\n---\n\n" + SAMPLE_BATCH_2
    result = yp.parse_aggregated_yaml(aggregated)

    # Azienda: primo non vuoto vince + campi accumulati
    assert result["meta"]["azienda"]["nome"] == "DEMO ALPHA SRL"
    assert result["meta"]["azienda"]["piva"] == "12345678901"
    assert result["meta"]["azienda"]["sede"] == "Via Roma 1"

    # Sezioni distinte per nome
    sezioni_nomi = [s["nome"] for s in result["sezioni"]]
    assert "08 · DOCUMENTAZIONE LEGALE" in sezioni_nomi
    assert "10 · SICUREZZA SUL LAVORO" in sezioni_nomi


def test_parse_dedups_sezioni_by_name():
    """Stessa sezione in 2 batch → un solo entry con documenti concatenati."""
    duplicate = SAMPLE_BATCH_1 + "\n\n---\n\n" + SAMPLE_BATCH_1.replace(
        "Visura 2025", "Visura 2024"
    )
    result = yp.parse_aggregated_yaml(duplicate)
    assert len(result["sezioni"]) == 1  # dedup
    docs = result["sezioni"][0]["documenti"]
    assert len(docs) == 2
    titoli = [d["titolo"] for d in docs]
    assert "Visura 2025" in titoli
    assert "Visura 2024" in titoli


# ──────────────────────────────────────────────────────────────────────────────
# Strip fences
# ──────────────────────────────────────────────────────────────────────────────

def test_strip_yaml_fences():
    fenced = "```yaml\nmeta:\n  azienda:\n    nome: 'X'\nsezioni: []\n```"
    result = yp.parse_aggregated_yaml(fenced)
    assert result["meta"]["azienda"]["nome"] == "X"


def test_strip_generic_code_fences():
    fenced = "```\nmeta:\n  azienda:\n    nome: 'Y'\nsezioni: []\n```"
    result = yp.parse_aggregated_yaml(fenced)
    assert result["meta"]["azienda"]["nome"] == "Y"


# ──────────────────────────────────────────────────────────────────────────────
# Tolleranza errori
# ──────────────────────────────────────────────────────────────────────────────

def test_empty_input_returns_stub():
    result = yp.parse_aggregated_yaml("")
    assert result["meta"]["azienda"] == {}
    assert result["sezioni"] == []


def test_garbage_input_returns_stub():
    result = yp.parse_aggregated_yaml("garbage\nnot: : yaml")
    # Best-effort: sezioni vuote, no eccezione
    assert "sezioni" in result


def test_partial_corruption_skips_bad_batch():
    """Se 1 batch su 2 è rotto, l'altro viene comunque parsato."""
    aggregated = (
        "azienda: { invalid yaml structure"
        + "\n\n---\n\n"
        + SAMPLE_BATCH_1
    )
    result = yp.parse_aggregated_yaml(aggregated)
    # Il batch buono viene parsato
    assert result["meta"]["azienda"].get("nome") == "DEMO ALPHA SRL"


# ──────────────────────────────────────────────────────────────────────────────
# Company name normalizzazione
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_company_name_valid():
    data = {"meta": {"azienda": {"nome": "DEMO SRL"}}}
    assert yp.extract_company_name(data) == "DEMO SRL"


def test_extract_company_name_uppercase():
    data = {"meta": {"azienda": {"nome": "  demo srl  "}}}
    assert yp.extract_company_name(data) == "DEMO SRL"


def test_extract_company_name_empty_falls_back():
    data = {"meta": {"azienda": {"nome": ""}}}
    assert yp.extract_company_name(data) == "AZIENDA NON IDENTIFICATA"


def test_extract_company_name_placeholder_falls_back():
    """Pattern placeholder come '[RAGIONE SOCIALE...]' viene rifiutato."""
    data = {"meta": {"azienda": {"nome": "[RAGIONE SOCIALE — REGOLA INDEROGABILE]"}}}
    assert yp.extract_company_name(data) == "AZIENDA NON IDENTIFICATA"


def test_extract_company_name_invalid_values():
    for invalid in ("n.d.", "N/A", "Azienda non identificata", "null"):
        data = {"meta": {"azienda": {"nome": invalid}}}
        assert yp.extract_company_name(data) == "AZIENDA NON IDENTIFICATA"


def test_extract_company_name_no_meta_key():
    data = {}
    assert yp.extract_company_name(data) == "AZIENDA NON IDENTIFICATA"


def test_extract_company_name_invalid_input():
    assert yp.extract_company_name(None) == "AZIENDA NON IDENTIFICATA"  # type: ignore
    assert yp.extract_company_name("not a dict") == "AZIENDA NON IDENTIFICATA"  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Skip placeholder name in batch ma usa il successivo
# ──────────────────────────────────────────────────────────────────────────────

def test_first_batch_with_placeholder_skipped_for_name():
    """Se batch 1 ha placeholder e batch 2 ha nome reale, vince batch 2."""
    placeholder_batch = """
meta:
  azienda:
    nome: "[RAGIONE SOCIALE — REGOLA INDEROGABILE]"
    piva: ""
sezioni: []
"""
    valid_batch = """
meta:
  azienda:
    nome: "REAL COMPANY SRL"
sezioni: []
"""
    aggregated = placeholder_batch + "\n\n---\n\n" + valid_batch
    result = yp.parse_aggregated_yaml(aggregated)
    assert result["meta"]["azienda"]["nome"] == "REAL COMPANY SRL"


# ──────────────────────────────────────────────────────────────────────────────
# Parsing summary
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_top_level_document_visura():
    """
    Bug MEDIL: il modello produce batch a struttura piatta quando contiene
    un solo documento. La visura va riconosciuta + score 100 + sezione popolata.
    """
    flat_batch = """
azienda:
  nome: "CONSORZIO STABILE MEDIL S.C.P.A."
  piva: "01483060628"
  sede: "VIA VITTORIO VENETO 29 BENEVENTO"

indice:
  - {n: 1, tipo: "Visura Camerale", titolo: "VISURA ORDINARIA"}

tipo: "Visura Camerale"
categoria: "08 · DOCUMENTAZIONE LEGALE E SOCIETARIA"
titolo: "VISURA ORDINARIA SOCIETA' DI CAPITALE"
emesso_da: "CCIAA Irpinia Sannio"
soggetto: "CONSORZIO STABILE MEDIL S.C.P.A."
data_doc: "10/02/2026"
"""
    result = yp.parse_aggregated_yaml(flat_batch)
    # Nome azienda riconosciuto correttamente
    assert result["meta"]["azienda"]["nome"] == "CONSORZIO STABILE MEDIL S.C.P.A."
    # Sezione "08 · DOCUMENTAZIONE LEGALE..." popolata col documento
    assert len(result["sezioni"]) == 1
    sez = result["sezioni"][0]
    assert "DOCUMENTAZIONE LEGALE" in sez["nome"]
    assert sez["id"] == "08"
    assert len(sez["documenti"]) == 1
    doc = sez["documenti"][0]
    assert doc["tipo"] == "Visura Camerale"
    assert "VISURA ORDINARIA" in doc["titolo"]


def test_top_level_doc_categoria_estrae_sezione():
    """Sezione viene derivata correttamente dal campo `categoria` del documento top-level."""
    flat = """
azienda:
  nome: "TEST SRL"
tipo: "DVR"
titolo: "Documento Valutazione Rischi"
categoria: "10 · SALUTE E SICUREZZA SUL LAVORO"
"""
    result = yp.parse_aggregated_yaml(flat)
    assert len(result["sezioni"]) == 1
    sez = result["sezioni"][0]
    assert sez["id"] == "10"
    assert "SALUTE E SICUREZZA" in sez["nome"]


def test_mixed_batches_top_level_and_nested():
    """Aggregazione di batch eterogenei: alcuni piatti, altri annidati."""
    flat_visura = """
azienda:
  nome: "MEDIL SRL"
tipo: "Visura Camerale"
categoria: "08 · LEGALE"
titolo: "Visura"
"""
    nested_dvr = """
meta:
  azienda:
    nome: "STUDIO RSPP"

sezioni:
  - id: "10"
    nome: "10 · SSL"
    documenti:
      - tipo: "DVR"
        titolo: "DVR cliente"
"""
    aggregated = flat_visura + "\n\n---\n\n" + nested_dvr
    result = yp.parse_aggregated_yaml(aggregated)
    # MEDIL vince per score visura (+100) vs DVR (-50)
    assert result["meta"]["azienda"]["nome"] == "MEDIL SRL"
    # Entrambe le sezioni presenti
    sezioni_nomi = {s["nome"] for s in result["sezioni"]}
    assert any("LEGALE" in n for n in sezioni_nomi)
    assert any("SSL" in n for n in sezioni_nomi)
    # Visura nel batch flat e DVR nel batch nested entrambi presenti
    visura_sez = next(s for s in result["sezioni"] if "LEGALE" in s["nome"])
    assert any(d["tipo"] == "Visura Camerale" for d in visura_sez["documenti"])
    dvr_sez = next(s for s in result["sezioni"] if "SSL" in s["nome"])
    assert any(d["tipo"] == "DVR" for d in dvr_sez["documenti"])


def test_score_visura_wins_over_dvr_only_batch():
    """
    Il batch con visura camerale deve vincere sul batch che ha SOLO DVR/attestati.
    Replica del comportamento V1 (essenziale per non scegliere consulenti
    esterni come "azienda audita").
    """
    yaml_dvr_only = """
meta:
  azienda:
    nome: "STUDIO RSPP CONSULENZE SRL"
sezioni:
  - id: "10"
    nome: "10 · SSL"
    documenti:
      - tipo: "DVR"
        titolo: "DVR azienda cliente"
"""
    yaml_visura = """
meta:
  azienda:
    nome: "AZIENDA REALE SPA"
sezioni:
  - id: "08"
    nome: "08 · LEGALE"
    documenti:
      - tipo: "Visura camerale"
        titolo: "Visura 2025"
"""
    # Aggrega con DVR primo (ordine non importa, deve vincere visura per score)
    aggregated = yaml_dvr_only + "\n\n---\n\n" + yaml_visura
    result = yp.parse_aggregated_yaml(aggregated)
    # AZIENDA REALE vince (score +100 visura), STUDIO RSPP perde (score -50 DVR)
    assert result["meta"]["azienda"]["nome"] == "AZIENDA REALE SPA"


def test_score_visura_wins_when_first_batch():
    """Stessa logica anche se la visura è nel primo batch."""
    yaml_visura = """
meta:
  azienda:
    nome: "MEDIL CONSORZIO SPA"
sezioni:
  - id: "08"
    nome: "08 · LEGALE"
    documenti:
      - tipo: "Visura camerale"
        titolo: "Visura"
"""
    yaml_attestato = """
meta:
  azienda:
    nome: "ENTE FORMATORE SRL"
sezioni:
  - id: "04"
    nome: "04 · FORMAZIONE"
    documenti:
      - tipo: "Attestato di formazione"
        titolo: "Antincendio"
"""
    aggregated = yaml_visura + "\n\n---\n\n" + yaml_attestato
    result = yp.parse_aggregated_yaml(aggregated)
    assert result["meta"]["azienda"]["nome"] == "MEDIL CONSORZIO SPA"


def test_score_function_directly():
    """Test diretto della funzione di scoring."""
    assert yp._score_company_source(["visura camerale"]) == 100
    assert yp._score_company_source(["statuto"]) == 80
    assert yp._score_company_source(["attestazione soa"]) == 60
    assert yp._score_company_source(["fattura"]) == 30
    assert yp._score_company_source(["dvr"]) == -50
    assert yp._score_company_source(["attestato di formazione antincendio"]) == -50
    # Combinato: visura batte tutto
    assert yp._score_company_source(["visura camerale", "dvr"]) == 50  # 100 - 50
    # Nessun match: 0
    assert yp._score_company_source(["sconosciuto"]) == 0


def test_recovery_markdown_table_with_bad_indent():
    """
    Recovery: il modello produce tabelle Markdown senza indentazione corretta.
    Il parser ora deve sanificare e parsare comunque.
    """
    bad_yaml = """
meta:
  azienda:
    nome: "RECOVERY SRL"

sezioni:
  - id: "08"
    nome: "08 · DOCUMENTAZIONE LEGALE"
    documenti:
      - tipo: "Visura"
        titolo: "Visura"
        descrizione_estesa: |
| Codice articolo | Descrizione | Quantita |
| A001 | Pippo | 10 |
| A002 | Pluto | 20 |
"""
    result = yp.parse_aggregated_yaml(bad_yaml)
    # Il parsing deve riuscire (almeno parzialmente)
    assert result["meta"]["azienda"]["nome"] == "RECOVERY SRL"
    # Almeno la sezione viene preservata
    assert len(result["sezioni"]) >= 1


def test_recovery_orphan_pipe_lines_stripped():
    """Linee pipe orfane (non in block scalar) vengono scartate gracefully."""
    bad_yaml = """
meta:
  azienda:
    nome: "ORPHAN SRL"
sezioni:
  - id: "10"
    nome: "10 · SSL"
    documenti:
      - tipo: "DVR"
        titolo: "DVR"
| this | is | random | markdown |
"""
    result = yp.parse_aggregated_yaml(bad_yaml)
    assert result["meta"]["azienda"]["nome"] == "ORPHAN SRL"


def test_parsing_summary():
    aggregated = SAMPLE_BATCH_1 + "\n\n---\n\n" + SAMPLE_BATCH_2
    parsed = yp.parse_aggregated_yaml(aggregated)
    summary = yp.parsing_summary(parsed)
    assert summary["sezioni_count"] == 2
    assert summary["documenti_total"] == 2
    assert summary["company"] == "DEMO ALPHA SRL"
