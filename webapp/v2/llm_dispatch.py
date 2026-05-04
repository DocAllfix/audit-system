"""
V2 — LLM dispatcher: factory che restituisce client + funzione analyze
in base al provider scelto (V2_PROVIDER env var o kwarg pipeline).

I 2 provider supportati:
- gemini-2.5-flash    → wrappa il client genai esistente + gemini_client_v2.analyze_batch_streaming
- gpt-4.1-mini-azure  → AzureOpenAIClientV2 + azure_openai_client_v2.analyze_batch_streaming

Il pipeline.py chiama:
    dispatch = build_dispatch(provider="gpt-4.1-mini-azure", api_key=...)
    result = dispatch.analyze(batch_docs, batch_idx=N, ...)

E in caso di AzureRateLimitExhausted:
    fallback = build_dispatch(provider="gemini-2.5-flash", api_key=GEMINI_API_KEY)
    result = fallback.analyze(batch_docs, batch_idx=N, ...)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .provider_profiles_v2 import ProviderProfile, get_profile


@dataclass
class LLMDispatch:
    """Bundle profile + client + funzione analyze per un provider."""
    profile: ProviderProfile
    client: Any
    analyze: Callable[..., Any]


def build_dispatch(
    provider: str,
    api_key: Optional[str] = None,
    gemini_client=None,
) -> LLMDispatch:
    """
    Costruisce dispatch per il provider richiesto.

    Args:
        provider: chiave profilo ("gemini-2.5-flash" o "gpt-4.1-mini-azure")
        api_key: per Gemini, la GEMINI_API_KEY. Per Azure ignorato (env var).
        gemini_client: client genai pre-istanziato. Se None per gemini, lo crea.

    Raises:
        KeyError se provider non noto.
        ValueError se manca configurazione (env vars Azure, api_key Gemini, ecc.).
    """
    profile = get_profile(provider)

    if profile.api_kind == "azure_openai":
        from .azure_openai_client_v2 import (
            AzureOpenAIClientV2,
            analyze_batch_streaming as azure_analyze,
        )
        client = AzureOpenAIClientV2(profile=profile)
        return LLMDispatch(profile=profile, client=client, analyze=azure_analyze)

    if profile.api_kind == "gemini_v2_native":
        from .gemini_client_v2 import analyze_batch_streaming as gemini_analyze
        client = gemini_client
        if client is None:
            from .genai_factory_v2 import create_genai_client_v2
            client = create_genai_client_v2(api_key=api_key)
        return LLMDispatch(profile=profile, client=client, analyze=gemini_analyze)

    raise ValueError(f"api_kind non gestito: {profile.api_kind}")


def fallback_disabled() -> bool:
    """True se il fallback Gemini su 429 Azure è disabilitato via env."""
    return os.environ.get("V2_DISABLE_FALLBACK", "0").strip() == "1"
