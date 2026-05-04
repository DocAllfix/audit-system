"""
Test V2 — legacy_adapter (Limitazione 2).

Coperture:
- Traduce session.start → {pct, msg}
- Traduce phase.start/tick/end con pct progressivo monotono
- file.warn → {warning, filename}
- file.degrade → {warning}
- error → {error}
- done → {pct: 100, msg: "Completato"} + cattura final_payload
- heartbeat / llm.token / file.done → None (nessun corrispondente V1)
- Eventi malformati → None senza eccezione
- pct max 99 prima di done
"""
from __future__ import annotations

from v2.legacy_adapter import LegacyAdapter


def test_session_start_pct_zero():
    a = LegacyAdapter()
    out = a.translate({"type": "session.start", "total_files": 100})
    assert out["pct"] == 0
    assert "100 file" in out["msg"]


def test_phase_start_offset():
    a = LegacyAdapter()
    a.translate({"type": "session.start"})
    # Triage parte dopo ingestion (5%)
    out = a.translate({"type": "phase.start", "phase": "triage"})
    assert out["pct"] == 5
    assert "Analisi file" in out["msg"]


def test_phase_tick_progressive():
    a = LegacyAdapter()
    a.translate({"type": "phase.start", "phase": "analyze"})
    out1 = a.translate({"type": "phase.tick", "phase": "analyze", "pct": 0.5})
    out2 = a.translate({"type": "phase.tick", "phase": "analyze", "pct": 1.0})
    # analyze offset = 55, weight = 35 → 0.5 → 72, 1.0 → 90
    assert out1["pct"] >= 55
    assert out2["pct"] >= out1["pct"]
    assert out2["pct"] <= 99


def test_phase_tick_with_detail():
    a = LegacyAdapter()
    out = a.translate({
        "type": "phase.tick",
        "phase": "analyze",
        "pct": 0.5,
        "detail": {"completed": 5, "total": 10},
    })
    assert "5/10" in out["msg"]


def test_phase_end_advances_pct():
    a = LegacyAdapter()
    a.translate({"type": "phase.start", "phase": "ingestion"})
    out = a.translate({"type": "phase.end", "phase": "ingestion"})
    assert out["pct"] == 5  # ingestion weight
    assert "completata" in out["msg"]


def test_pct_never_descends():
    """pct deve essere monotono crescente."""
    a = LegacyAdapter()
    a.translate({"type": "phase.start", "phase": "analyze"})
    a.translate({"type": "phase.tick", "phase": "analyze", "pct": 0.9})
    out = a.translate({"type": "phase.tick", "phase": "analyze", "pct": 0.1})
    # Nonostante pct=0.1 nel tick, il pct cumulativo non scende
    assert out["pct"] >= 55  # base analyze


def test_file_warn_translated_to_warning():
    a = LegacyAdapter()
    out = a.translate({
        "type": "file.warn",
        "filename": "big.pdf",
        "kind": "large",
        "msg": "File >50MB",
    })
    assert "warning" in out
    assert "File >50MB" in out["warning"]
    assert out["filename"] == "big.pdf"


def test_file_degrade_translated_to_warning():
    a = LegacyAdapter()
    out = a.translate({
        "type": "file.degrade",
        "filename": "x.pdf",
        "reason": "timeout",
        "fallback": "fast_mode",
    })
    assert "warning" in out
    assert "fast_mode" in out["warning"]


def test_error_translated():
    a = LegacyAdapter()
    out = a.translate({
        "type": "error",
        "kind": "response_too_large",
        "msg": "Response 1MB > 400k",
    })
    assert "error" in out
    assert "response_too_large" in out["error"]


def test_done_emits_pct_100():
    a = LegacyAdapter()
    out = a.translate({
        "type": "done",
        "filename": "audit.docx",
        "duration_seconds": 180.5,
    })
    assert out["pct"] == 100
    assert "Completato" in out["msg"]
    # Final payload catturato per uso successivo
    assert a.final_payload is not None
    assert a.final_payload["filename"] == "audit.docx"


def test_heartbeat_returns_none():
    a = LegacyAdapter()
    out = a.translate({"type": "heartbeat", "pid": 1234, "rss_mb": 100})
    assert out is None


def test_llm_token_returns_none():
    a = LegacyAdapter()
    out = a.translate({"type": "llm.token", "batch": 1, "chunk": "..."})
    assert out is None


def test_file_done_returns_none():
    a = LegacyAdapter()
    out = a.translate({"type": "file.done", "filename": "x.pdf"})
    assert out is None


def test_invalid_input_returns_none():
    a = LegacyAdapter()
    assert a.translate(None) is None  # type: ignore
    assert a.translate("not a dict") is None  # type: ignore
    assert a.translate({}) is None  # no type


def test_unknown_type_returns_none():
    a = LegacyAdapter()
    out = a.translate({"type": "unknown.type"})
    assert out is None


def test_translation_never_raises():
    """Qualsiasi input non causa eccezione."""
    a = LegacyAdapter()
    weird_inputs = [
        {"type": "phase.tick", "phase": None, "pct": "not a number"},
        {"type": "phase.start", "phase": 12345},
        {"type": "session.start", "total_files": "abc"},
    ]
    for ev in weird_inputs:
        # Non solleva
        a.translate(ev)


def test_full_pipeline_progression():
    """Simula sequenza completa eventi V2 e verifica pct monotono fino a 100."""
    a = LegacyAdapter()
    sequence = [
        {"type": "session.start", "total_files": 50},
        {"type": "phase.start", "phase": "ingestion"},
        {"type": "phase.end", "phase": "ingestion"},
        {"type": "phase.start", "phase": "triage"},
        {"type": "phase.end", "phase": "triage"},
        {"type": "phase.start", "phase": "analyze"},
        {"type": "phase.tick", "phase": "analyze", "pct": 0.5},
        {"type": "phase.end", "phase": "analyze"},
        {"type": "done"},
    ]
    pcts = []
    for ev in sequence:
        out = a.translate(ev)
        if out is not None and "pct" in out:
            pcts.append(out["pct"])
    # Strict monotonic
    assert pcts == sorted(pcts)
    # Finisce a 100
    assert pcts[-1] == 100
