"""
Test webapp/v2/provider_profiles_v2.py — 2 profili (Gemini default + Azure).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
sys.path.insert(0, str(_WEBAPP_DIR))

from v2.provider_profiles_v2 import (  # noqa: E402
    DEFAULT_PROVIDER,
    PROFILES,
    get_profile,
    list_provider_keys,
    resolve_provider_key,
)


def test_two_profiles_present():
    keys = list_provider_keys()
    assert "gemini-2.5-flash" in keys
    assert "gpt-4.1-mini-azure" in keys
    assert len(keys) == 2


def test_default_provider_is_gemini():
    assert DEFAULT_PROVIDER == "gemini-2.5-flash"


def test_gemini_profile_matches_v2_prod():
    p = get_profile("gemini-2.5-flash")
    assert p.api_kind == "gemini_v2_native"
    assert p.batch_max_files == 4
    assert p.batch_max_chars == 50_000
    assert p.doc_cap_multiplier == 1.0
    assert p.max_workers == 7


def test_azure_profile_spike_validated():
    """Valori validati nello spike: workers=6, batch=10/180K, cap 2.5x."""
    p = get_profile("gpt-4.1-mini-azure")
    assert p.api_kind == "azure_openai"
    assert p.name == "gpt-4.1-mini"
    assert p.batch_max_files == 10
    assert p.batch_max_chars == 180_000
    assert p.doc_cap_multiplier == 2.5
    assert p.max_workers == 6
    assert p.max_output_tokens == 32_000


def test_unknown_provider_raises():
    with pytest.raises(KeyError):
        get_profile("deepseek-v4-flash")


def test_resolve_provider_explicit_wins(monkeypatch):
    monkeypatch.setenv("V2_PROVIDER", "gpt-4.1-mini-azure")
    assert resolve_provider_key("gemini-2.5-flash") == "gemini-2.5-flash"


def test_resolve_provider_env_used_when_no_arg(monkeypatch):
    monkeypatch.setenv("V2_PROVIDER", "gpt-4.1-mini-azure")
    assert resolve_provider_key(None) == "gpt-4.1-mini-azure"


def test_resolve_provider_default_when_unset(monkeypatch):
    monkeypatch.delenv("V2_PROVIDER", raising=False)
    assert resolve_provider_key(None) == DEFAULT_PROVIDER


def test_env_override_max_workers(monkeypatch):
    monkeypatch.setenv("V2_PROVIDER_GPT_4_1_MINI_AZURE_MAX_WORKERS", "3")
    p = get_profile("gpt-4.1-mini-azure")
    assert p.max_workers == 3


def test_env_override_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("V2_PROVIDER_GPT_4_1_MINI_AZURE_MAX_WORKERS", "not_a_number")
    p = get_profile("gpt-4.1-mini-azure")
    assert p.max_workers == 6  # default
