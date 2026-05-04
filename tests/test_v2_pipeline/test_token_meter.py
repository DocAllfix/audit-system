"""
Test V2 Fase 7.5 — token_meter.

Coperture:
- record_call: validazione input, normalizzazione clamp, persist su disk
- record_from_response: estrazione automatica da usage_metadata, tolleranza
  a campi mancanti / response None / no usage_metadata
- compute_cost_usd: pricing corretto per Flash, Flash Lite, embedding
- Cached tokens scontati separatamente (Flash: 75% off)
- Modello sconosciuto → cost 0, no exception
- get_session_report: aggregati corretti by_model + by_kind
- saved_by_caching: stima risparmio
- format_report_table: stringa human-readable
- Thread-safety: 10 thread record concorrenti tutti registrati
- reset_session: cleanup memoria + disco
- session_id invalido (path traversal): rifiutato
- Persistenza: report leggibile dopo restart simulato
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from v2 import token_meter as tm


# ──────────────────────────────────────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_meter(tmp_path, monkeypatch):
    """Reset state in-memory + persistenza su tmp_path per ogni test."""
    tm.reset_all_sessions()
    monkeypatch.setattr(tm, "TOKEN_USAGE_BASE_DIR", tmp_path / "token_usage")
    yield
    tm.reset_all_sessions()


# ──────────────────────────────────────────────────────────────────────────────
# Pricing helpers
# ──────────────────────────────────────────────────────────────────────────────

def test_pricing_flash_input_only():
    """Solo input, no cached, no output → costo = input_tok * 0.30 / 1M."""
    cost = tm.compute_cost_usd("gemini-2.5-flash", input_tokens=1_000_000, cached_tokens=0, output_tokens=0)
    assert cost == pytest.approx(0.30, abs=0.001)


def test_pricing_flash_with_cached_discount():
    """Cached tokens scontati: Flash cached = 0.075 USD/M = 75% off da 0.30."""
    cost = tm.compute_cost_usd(
        "gemini-2.5-flash",
        input_tokens=1_000_000,
        cached_tokens=800_000,  # 80% del prompt è cached
        output_tokens=0,
    )
    # 200k non-cached × 0.30/M + 800k cached × 0.075/M = 0.06 + 0.06 = 0.12
    assert cost == pytest.approx(0.12, abs=0.001)


def test_pricing_flash_full_chain():
    cost = tm.compute_cost_usd(
        "gemini-2.5-flash",
        input_tokens=100_000,
        cached_tokens=0,
        output_tokens=50_000,
    )
    # 100k * 0.30/M + 50k * 2.50/M = 0.03 + 0.125 = 0.155
    assert cost == pytest.approx(0.155, abs=0.001)


def test_pricing_flash_lite_no_cache_support():
    """Flash Lite: pricing diverso, NO sconto cached anche se passato."""
    cost_no_cache = tm.compute_cost_usd("gemini-2.5-flash-lite", 1_000_000, 0, 0)
    # 1M * 0.10/M = 0.10
    assert cost_no_cache == pytest.approx(0.10, abs=0.001)

    cost_with_cached = tm.compute_cost_usd("gemini-2.5-flash-lite", 1_000_000, 500_000, 0)
    # cached_input=None → ignora sconto. Solo non-cached fattura.
    # non_cached = 500k → 500k * 0.10/M = 0.05
    assert cost_with_cached == pytest.approx(0.05, abs=0.001)


def test_pricing_unknown_model_returns_zero():
    cost = tm.compute_cost_usd("unknown-model-xyz", 1_000_000, 0, 1_000_000)
    assert cost == 0.0


def test_pricing_normalizes_models_prefix():
    """'models/gemini-2.5-flash' → riconosciuto come 'gemini-2.5-flash'."""
    cost1 = tm.compute_cost_usd("models/gemini-2.5-flash", 1000, 0, 0)
    cost2 = tm.compute_cost_usd("gemini-2.5-flash", 1000, 0, 0)
    assert cost1 == cost2


def test_pricing_eur_uses_conversion_rate():
    cost_usd = tm.compute_cost_usd("gemini-2.5-flash", 1_000_000, 0, 0)
    cost_eur = tm.compute_cost_eur("gemini-2.5-flash", 1_000_000, 0, 0)
    assert cost_eur == pytest.approx(cost_usd * tm.USD_TO_EUR, abs=0.001)


# ──────────────────────────────────────────────────────────────────────────────
# record_call
# ──────────────────────────────────────────────────────────────────────────────

def test_record_call_persists_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "TOKEN_USAGE_BASE_DIR", tmp_path / "tu")
    ok = tm.record_call("sess1", "gemini-2.5-flash",
                         input_tokens=1000, cached_tokens=500, output_tokens=200,
                         kind=tm.KIND_ANALYZE)
    assert ok is True

    json_path = tmp_path / "tu" / "sess1.json"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["calls_count"] == 1
    assert data["total_input"] == 1000


def test_record_call_clamps_cached_to_input():
    """cached_tokens > input_tokens viene clampato a input_tokens."""
    tm.record_call("sess2", "gemini-2.5-flash",
                    input_tokens=100, cached_tokens=999, output_tokens=0)
    report = tm.get_session_report("sess2")
    assert report["total_cached"] == 100  # clampato


def test_record_call_invalid_session_id_returns_false():
    assert tm.record_call("../etc", "gemini-2.5-flash", 1, 0, 0) is False
    assert tm.record_call("foo/bar", "gemini-2.5-flash", 1, 0, 0) is False
    assert tm.record_call("", "gemini-2.5-flash", 1, 0, 0) is False


def test_record_call_invalid_kind_falls_to_other():
    tm.record_call("sess3", "gemini-2.5-flash",
                    input_tokens=100, output_tokens=50, kind="invalid_kind")
    report = tm.get_session_report("sess3")
    # Il kind sconosciuto viene mappato a 'other'
    assert tm.KIND_OTHER in report["by_kind"]


def test_record_call_negative_values_clamped_to_zero():
    tm.record_call("sess4", "gemini-2.5-flash",
                    input_tokens=-100, cached_tokens=-50, output_tokens=-10)
    report = tm.get_session_report("sess4")
    assert report["total_input"] == 0
    assert report["total_cached"] == 0
    assert report["total_output"] == 0


def test_record_call_accepts_none_values():
    """input/cached/output=None → trattato come 0."""
    ok = tm.record_call("sess5", "gemini-2.5-flash",
                         input_tokens=None, cached_tokens=None, output_tokens=None)
    assert ok is True


# ──────────────────────────────────────────────────────────────────────────────
# record_from_response (SDK genai usage_metadata)
# ──────────────────────────────────────────────────────────────────────────────

def test_record_from_response_extracts_usage_metadata():
    response = MagicMock()
    response.usage_metadata = MagicMock()
    response.usage_metadata.prompt_token_count = 1500
    response.usage_metadata.cached_content_token_count = 800
    response.usage_metadata.candidates_token_count = 300

    ok = tm.record_from_response("sess_fr", response, "gemini-2.5-flash", kind=tm.KIND_ANALYZE)
    assert ok is True
    report = tm.get_session_report("sess_fr")
    assert report["total_input"] == 1500
    assert report["total_cached"] == 800
    assert report["total_output"] == 300


def test_record_from_response_handles_none():
    """response=None → False, no eccezione."""
    assert tm.record_from_response("sess_x", None, "gemini-2.5-flash") is False


def test_record_from_response_missing_usage_metadata():
    """response senza usage_metadata → False, no eccezione."""
    response = MagicMock(spec=[])  # nessun attributo
    assert tm.record_from_response("sess_y", response, "gemini-2.5-flash") is False


def test_record_from_response_partial_usage_metadata():
    """Alcuni campi None → trattati come 0."""
    response = MagicMock()
    response.usage_metadata = MagicMock()
    response.usage_metadata.prompt_token_count = 1000
    response.usage_metadata.cached_content_token_count = None
    response.usage_metadata.candidates_token_count = 500

    tm.record_from_response("sess_p", response, "gemini-2.5-flash")
    report = tm.get_session_report("sess_p")
    assert report["total_input"] == 1000
    assert report["total_cached"] == 0
    assert report["total_output"] == 500


# ──────────────────────────────────────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────────────────────────────────────

def test_report_aggregates_by_model_and_kind():
    tm.record_call("sess_agg", "gemini-2.5-flash", 100, 50, 30, kind=tm.KIND_ANALYZE)
    tm.record_call("sess_agg", "gemini-2.5-flash", 200, 100, 60, kind=tm.KIND_ANALYZE)
    tm.record_call("sess_agg", "gemini-2.5-flash-lite", 50, 0, 20, kind=tm.KIND_CLASSIFY)

    report = tm.get_session_report("sess_agg")
    assert report["calls_count"] == 3
    assert report["total_input"] == 350
    assert report["total_cached"] == 150
    assert report["total_output"] == 110

    # by_model
    flash = report["by_model"]["gemini-2.5-flash"]
    assert flash["calls"] == 2
    assert flash["input"] == 300

    lite = report["by_model"]["gemini-2.5-flash-lite"]
    assert lite["calls"] == 1
    assert lite["input"] == 50

    # by_kind
    assert report["by_kind"][tm.KIND_ANALYZE]["calls"] == 2
    assert report["by_kind"][tm.KIND_CLASSIFY]["calls"] == 1


def test_report_saved_by_caching_estimate():
    """Caching deve produrre saved_by_caching_usd > 0 sul Flash."""
    tm.record_call("sess_cache", "gemini-2.5-flash",
                    input_tokens=1_000_000, cached_tokens=900_000, output_tokens=0,
                    kind=tm.KIND_ANALYZE)
    report = tm.get_session_report("sess_cache")
    assert report["saved_by_caching_usd"] > 0
    # Risparmio = 900k * (0.30 - 0.075)/M = 0.2025
    assert report["saved_by_caching_usd"] == pytest.approx(0.2025, abs=0.001)


def test_report_empty_session_returns_zeros():
    report = tm.get_session_report("never_recorded")
    assert report["calls_count"] == 0
    assert report["total_cost_usd"] == 0.0
    assert report["by_model"] == {}


def test_report_invalid_session_id_returns_error():
    report = tm.get_session_report("../bad")
    assert "error" in report


# ──────────────────────────────────────────────────────────────────────────────
# format_report_table
# ──────────────────────────────────────────────────────────────────────────────

def test_format_report_table_human_readable():
    tm.record_call("sess_fmt", "gemini-2.5-flash",
                    input_tokens=10_000, cached_tokens=5_000, output_tokens=2_000,
                    kind=tm.KIND_ANALYZE)
    table = tm.format_report_table("sess_fmt")
    assert "TOKEN REPORT" in table
    assert "TOTALE" in table
    assert "gemini-2.5-flash" in table
    assert "analyze" in table
    # Numeri formattati con virgola
    assert "10,000" in table


def test_format_report_table_empty_session():
    table = tm.format_report_table("emptySess")
    assert "Nessuna chiamata" in table


# ──────────────────────────────────────────────────────────────────────────────
# Thread-safety
# ──────────────────────────────────────────────────────────────────────────────

def test_concurrent_records_all_registered():
    """10 thread × 50 record → tutti i 500 record persisted."""
    NUM_THREADS = 10
    RECORDS_PER_THREAD = 50

    def worker(tid):
        for i in range(RECORDS_PER_THREAD):
            tm.record_call("sess_concur", "gemini-2.5-flash",
                            input_tokens=10, cached_tokens=0, output_tokens=5,
                            kind=tm.KIND_ANALYZE)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(NUM_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    report = tm.get_session_report("sess_concur")
    assert report["calls_count"] == NUM_THREADS * RECORDS_PER_THREAD
    assert report["total_input"] == NUM_THREADS * RECORDS_PER_THREAD * 10


# ──────────────────────────────────────────────────────────────────────────────
# Reset
# ──────────────────────────────────────────────────────────────────────────────

def test_reset_session_clears_memory_and_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "TOKEN_USAGE_BASE_DIR", tmp_path / "tu")
    tm.record_call("sess_del", "gemini-2.5-flash", 100, 0, 50)
    json_path = tmp_path / "tu" / "sess_del.json"
    assert json_path.exists()

    tm.reset_session("sess_del")
    assert not json_path.exists()
    assert tm.get_session_report("sess_del")["calls_count"] == 0


def test_reset_invalid_session_no_op():
    """Reset su session_id invalido: no eccezione."""
    tm.reset_session("../bad")  # No exception


def test_reset_all_sessions_clears_global():
    tm.record_call("a", "gemini-2.5-flash", 10, 0, 5)
    tm.record_call("b", "gemini-2.5-flash", 20, 0, 10)
    tm.reset_all_sessions()
    assert tm.get_session_report("a")["calls_count"] == 0
    assert tm.get_session_report("b")["calls_count"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Leva 3 — telemetria estesa per call (duration, retry, error, batch_id)
# ──────────────────────────────────────────────────────────────────────────────

def test_record_call_persists_extended_telemetry():
    """duration/retry/error/batch_id devono comparire nel report."""
    tm.record_call(
        "sess_tel", "gemini-2.5-flash",
        input_tokens=100, cached_tokens=0, output_tokens=50,
        kind="analyze",
        duration_seconds=12.345, retry_count=1,
        error=None, batch_id="batch_007",
    )
    report = tm.get_session_report("sess_tel")
    assert report["calls_count"] == 1
    assert report["total_duration_seconds"] == pytest.approx(12.34, abs=0.02)
    assert report["total_retries"] == 1
    assert report["errors_count"] == 0
    assert report["errors_sample"] == []
    by_kind = report["by_kind"]["analyze"]
    assert by_kind["duration_seconds"] == pytest.approx(12.34, abs=0.02)
    assert by_kind["retries"] == 1
    assert by_kind["errors"] == 0


def test_record_call_with_error_appears_in_sample():
    """Una call con errore deve incrementare errors_count e finire nel sample."""
    tm.record_call(
        "sess_err", "gemini-2.5-flash",
        kind="analyze",
        duration_seconds=2.0, retry_count=2,
        error="non_retryable: 503 service unavailable",
        batch_id="batch_042",
    )
    report = tm.get_session_report("sess_err")
    assert report["errors_count"] == 1
    assert len(report["errors_sample"]) == 1
    sample = report["errors_sample"][0]
    assert sample["batch_id"] == "batch_042"
    assert sample["retry_count"] == 2
    assert "503" in sample["error"]


def test_record_from_response_with_none_records_error_only():
    """response=None ma error fornito: la call deve essere registrata come errore."""
    ok = tm.record_from_response(
        "sess_n", None, "gemini-2.5-flash",
        kind="analyze",
        duration_seconds=1.5,
        error="stream_error: timeout",
        batch_id="batch_009",
    )
    assert ok is True
    report = tm.get_session_report("sess_n")
    assert report["calls_count"] == 1
    assert report["errors_count"] == 1
    # Token a 0 perché non c'è response
    assert report["total_input"] == 0
    assert report["total_output"] == 0


def test_record_from_response_no_telemetry_no_record_when_none():
    """response=None senza error/duration → comportamento legacy: non registrare."""
    ok = tm.record_from_response("sess_skip", None, "gemini-2.5-flash", kind="analyze")
    assert ok is False
    assert tm.get_session_report("sess_skip")["calls_count"] == 0


def test_errors_sample_capped_at_20():
    """errors_sample non deve crescere indefinitamente."""
    for i in range(30):
        tm.record_call(
            "sess_many", "gemini-2.5-flash",
            kind="analyze",
            error=f"err_{i}",
            batch_id=f"b_{i:03d}",
        )
    report = tm.get_session_report("sess_many")
    assert report["errors_count"] == 30
    assert len(report["errors_sample"]) == 20


def test_record_call_clamps_negative_duration_and_retry():
    """duration < 0 → 0, retry < 0 → 0."""
    tm.record_call(
        "sess_clamp", "gemini-2.5-flash",
        kind="analyze",
        duration_seconds=-1.0, retry_count=-3,
    )
    report = tm.get_session_report("sess_clamp")
    assert report["total_duration_seconds"] == 0.0
    assert report["total_retries"] == 0


def test_error_string_truncated_to_200_chars():
    """error stringa molto lunga deve essere troncata a 200 char."""
    long_err = "x" * 500
    tm.record_call(
        "sess_long", "gemini-2.5-flash",
        kind="analyze",
        error=long_err,
        batch_id="b1",
    )
    report = tm.get_session_report("sess_long")
    sample = report["errors_sample"][0]
    assert len(sample["error"]) <= 200
