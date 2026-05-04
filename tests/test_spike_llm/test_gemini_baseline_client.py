"""
Test suite per webapp.spike_llm.gemini_baseline_client.

Verifica che il wrapper non modifichi il comportamento di V2 e che inoltri
correttamente parametri e ritorno.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP_DIR = _REPO_ROOT / "webapp"
if str(_WEBAPP_DIR) not in sys.path:
    sys.path.insert(0, str(_WEBAPP_DIR))

from spike_llm import gemini_baseline_client as gbc
from spike_llm import provider_profiles as pp


def test_build_client_rejects_non_gemini_profile():
    profile = pp.get_profile("gpt-4.1-mini")
    with pytest.raises(ValueError, match="api_kind=gemini_v2_wrapper"):
        gbc.build_client(profile=profile)


def test_analyze_batch_streaming_forwards_to_v2():
    """Il wrapper deve essere puro: chiama _v2_analyze con gli stessi args."""
    sentinel_result = object()

    with patch("spike_llm.gemini_baseline_client._v2_analyze", return_value=sentinel_result) as mock_v2:
        result = gbc.analyze_batch_streaming(
            client="dummy_client",
            batch_docs=[{"filename": "a.pdf", "content": "x"}],
            batch_idx=2,
            total_docs=10,
            universal_prompt=None,
            meter_session_id="sess123",
            compact_mode=True,
            model_override="gemini-2.5-flash",
        )

    assert result is sentinel_result
    assert mock_v2.called
    call_kwargs = mock_v2.call_args.kwargs
    assert call_kwargs["client"] == "dummy_client"
    assert call_kwargs["batch_idx"] == 2
    assert call_kwargs["total_docs"] == 10
    assert call_kwargs["meter_session_id"] == "sess123"
    assert call_kwargs["compact_mode"] is True
    assert call_kwargs["model_override"] == "gemini-2.5-flash"


def test_analyze_passes_none_universal_prompt_to_v2():
    """Quando universal_prompt è None, V2 deve riceverlo None per caricare il PROD."""
    with patch("spike_llm.gemini_baseline_client._v2_analyze") as mock_v2:
        gbc.analyze_batch_streaming(
            client="c",
            batch_docs=[{"filename": "a.pdf", "content": "x"}],
            universal_prompt=None,
        )
    assert mock_v2.call_args.kwargs["universal_prompt"] is None
