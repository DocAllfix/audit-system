"""
Test suite per webapp.spike_llm.orchestrator.

Verifica:
- Generazione corretta della matrice (zips × providers)
- Session ID univoci per cella
- Errori in cella non bloccano le altre celle
- Callback on_task_complete chiamato per ogni cella
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
if str(_WEBAPP_DIR) not in sys.path:
    sys.path.insert(0, str(_WEBAPP_DIR))

from spike_llm import orchestrator


def _fake_process_zip_spike(*, zip_bytes, session_id, deepseek_api_key, gemini_api_key, provider):
    """Mock pipeline_spike: ritorna result deterministico per assert."""
    return {
        "success": True,
        "session_id": session_id,
        "provider": provider,
        "duration_seconds": 1.0,
        "cost_eur": 0.1,
        "_zip_size": len(zip_bytes),
    }


def test_run_matrix_executes_all_cells():
    zips = [
        ("ALLEGATI A.zip", b"x" * 100),
        ("ALLEGATI B.zip", b"y" * 200),
    ]
    providers = ["deepseek-v4-flash", "gpt-4.1-mini"]

    with patch("spike_llm.pipeline_spike.process_zip_spike", side_effect=_fake_process_zip_spike):
        results = orchestrator.run_matrix(
            zips=zips,
            providers=providers,
            variant="v2",
            parallel_pratiche=2,
        )

    # 2 zip × 2 provider = 4 celle
    assert len(results) == 4
    assert ("ALLEGATI A.zip", "deepseek-v4-flash") in results
    assert ("ALLEGATI A.zip", "gpt-4.1-mini") in results
    assert ("ALLEGATI B.zip", "deepseek-v4-flash") in results
    assert ("ALLEGATI B.zip", "gpt-4.1-mini") in results


def test_run_matrix_session_ids_are_unique():
    zips = [
        ("Z1.zip", b"x"),
        ("Z2.zip", b"y"),
    ]
    providers = ["deepseek-v4-flash", "gpt-4.1-mini"]

    with patch("spike_llm.pipeline_spike.process_zip_spike", side_effect=_fake_process_zip_spike):
        results = orchestrator.run_matrix(
            zips=zips,
            providers=providers,
            parallel_pratiche=2,
        )

    session_ids = [r.get("session_id") for r in results.values()]
    assert len(set(session_ids)) == len(session_ids), "session_id duplicati!"


def test_run_matrix_failure_in_cell_does_not_block_others():
    def maybe_fail(*, zip_bytes, session_id, deepseek_api_key, gemini_api_key, provider):
        if provider == "deepseek-v4-flash":
            raise RuntimeError("simulated failure")
        return _fake_process_zip_spike(
            zip_bytes=zip_bytes, session_id=session_id,
            deepseek_api_key=deepseek_api_key, gemini_api_key=gemini_api_key,
            provider=provider,
        )

    zips = [("A.zip", b"x")]
    providers = ["deepseek-v4-flash", "gpt-4.1-mini", "gpt-4o-mini"]

    with patch("spike_llm.pipeline_spike.process_zip_spike", side_effect=maybe_fail):
        results = orchestrator.run_matrix(zips=zips, providers=providers)

    assert results[("A.zip", "deepseek-v4-flash")]["success"] is False
    assert "simulated failure" in results[("A.zip", "deepseek-v4-flash")].get("error", "")
    assert results[("A.zip", "gpt-4.1-mini")]["success"] is True
    assert results[("A.zip", "gpt-4o-mini")]["success"] is True


def test_run_matrix_calls_on_task_complete_for_each_cell():
    zips = [("A.zip", b"x"), ("B.zip", b"y")]
    providers = ["deepseek-v4-flash", "gpt-4.1-mini"]
    callback_calls = []

    def cb(zip_name, provider, result):
        callback_calls.append((zip_name, provider, bool(result.get("success"))))

    with patch("spike_llm.pipeline_spike.process_zip_spike", side_effect=_fake_process_zip_spike):
        orchestrator.run_matrix(
            zips=zips,
            providers=providers,
            on_task_complete=cb,
        )

    # 4 callback, una per cella
    assert len(callback_calls) == 4
    # Ognuna è OK
    assert all(ok for (_, _, ok) in callback_calls)


def test_run_matrix_empty_inputs():
    assert orchestrator.run_matrix(zips=[], providers=["deepseek-v4-flash"]) == {}
    assert orchestrator.run_matrix(zips=[("a.zip", b"x")], providers=[]) == {}


def test_slugify_zip_name_strips_extension_and_specials():
    assert orchestrator._slugify_zip_name("ALLEGATI MEDIL 37001_50001.zip") == "ALLEGATI_MEDIL_37001_50001"
    assert orchestrator._slugify_zip_name("file (with) parens.zip") == "file__with__parens"
