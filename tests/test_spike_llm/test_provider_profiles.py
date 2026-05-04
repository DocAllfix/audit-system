"""
Test suite per webapp.spike_llm.provider_profiles.

Verifica i 4 profili (gemini-baseline, deepseek-v4-flash, gpt-4.1-mini,
gpt-4o-mini), i loro vincoli tecnici e gli override via env var.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Path setup per import spike
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
if str(_WEBAPP_DIR) not in sys.path:
    sys.path.insert(0, str(_WEBAPP_DIR))

from spike_llm import provider_profiles as pp


def test_all_4_profiles_present():
    keys = pp.list_provider_keys()
    assert "gemini-baseline" in keys
    assert "deepseek-v4-flash" in keys
    assert "gpt-4.1-mini" in keys
    # gpt-4o-mini rimosso: deprecato in Azure Foundry per nuovi account.


def test_gemini_baseline_matches_v2_prod_params():
    p = pp.get_profile("gemini-baseline")
    assert p.api_kind == "gemini_v2_wrapper"
    assert p.name == "gemini-2.5-flash"
    assert p.batch_max_files == 4
    assert p.batch_max_chars == 50_000
    assert p.doc_cap_multiplier == 1.0
    assert p.max_workers == 7


def test_deepseek_uses_aggressive_batches():
    p = pp.get_profile("deepseek-v4-flash")
    assert p.api_kind == "deepseek"
    assert p.batch_max_files == 12
    assert p.batch_max_chars == 200_000
    assert p.doc_cap_multiplier == 2.5
    assert p.max_workers == 14
    assert p.context_window == 1_000_000


def test_gpt_41_mini_profile():
    p = pp.get_profile("gpt-4.1-mini")
    assert p.api_kind == "azure_openai"
    assert p.context_window == 1_000_000
    assert p.max_output_tokens == 32_000
    assert p.batch_max_files == 10
    assert p.doc_cap_multiplier == 2.5


def test_unknown_provider_raises():
    with pytest.raises(KeyError):
        pp.get_profile("nonexistent-provider")


def test_env_override_batch_max_files(monkeypatch):
    monkeypatch.setenv("SPIKE_LLM_GPT_4_1_MINI_BATCH_MAX_FILES", "5")
    p = pp.get_profile("gpt-4.1-mini")
    assert p.batch_max_files == 5


def test_env_override_max_workers(monkeypatch):
    monkeypatch.setenv("SPIKE_LLM_DEEPSEEK_V4_FLASH_MAX_WORKERS", "20")
    p = pp.get_profile("deepseek-v4-flash")
    assert p.max_workers == 20


def test_env_override_doc_cap_multiplier_float(monkeypatch):
    monkeypatch.setenv("SPIKE_LLM_GPT_4_1_MINI_DOC_CAP_MULTIPLIER", "3.0")
    p = pp.get_profile("gpt-4.1-mini")
    assert p.doc_cap_multiplier == 3.0


def test_env_override_invalid_falls_back_to_default(monkeypatch):
    """Override invalido (non numerico) deve essere ignorato silenziosamente."""
    monkeypatch.setenv("SPIKE_LLM_GPT_4_1_MINI_BATCH_MAX_FILES", "not-a-number")
    p = pp.get_profile("gpt-4.1-mini")
    assert p.batch_max_files == 10  # default
