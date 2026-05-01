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

def test_parsing_summary():
    aggregated = SAMPLE_BATCH_1 + "\n\n---\n\n" + SAMPLE_BATCH_2
    parsed = yp.parse_aggregated_yaml(aggregated)
    summary = yp.parsing_summary(parsed)
    assert summary["sezioni_count"] == 2
    assert summary["documenti_total"] == 2
    assert summary["company"] == "DEMO ALPHA SRL"
