"""
Spike LLM — Factory che restituisce il modulo client e il client istanziato
per un profilo.

Il `pipeline_spike.py` chiama:
    module = get_client_module(profile)
    client = build_client(profile, **kwargs)
    module.analyze_batch_streaming(client=client, ...)

In modo agnostico al provider sottostante. Tutti i client espongono la stessa
firma logica per `analyze_batch_streaming`.
"""
from __future__ import annotations

from typing import Any, Optional

from .provider_profiles import ProviderProfile


def get_client_module(profile: ProviderProfile):
    """
    Ritorna il modulo Python con l'implementazione `analyze_batch_streaming`
    per il provider del profilo passato.

    Raises:
        ValueError se profile.api_kind non è gestito.
    """
    if profile.api_kind == "deepseek":
        from . import deepseek_client
        return deepseek_client
    if profile.api_kind == "azure_openai":
        from . import azure_openai_client
        return azure_openai_client
    if profile.api_kind == "gemini_v2_wrapper":
        from . import gemini_baseline_client
        return gemini_baseline_client
    raise ValueError(f"Unknown api_kind: {profile.api_kind}")


def build_client(
    profile: ProviderProfile,
    deepseek_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
) -> Any:
    """
    Istanzia il client concreto per il profilo. Usato da pipeline_spike per
    ottenere un client da passare a `analyze_batch_streaming`.

    Args:
        profile: ProviderProfile target
        deepseek_api_key: chiave DeepSeek (solo per profilo DeepSeek)
        gemini_api_key: chiave Gemini (solo per profilo gemini-baseline)

    Per Azure le credenziali vengono lette dalle env var dentro AzureOpenAIClient.
    """
    if profile.api_kind == "deepseek":
        from .deepseek_client import DeepSeekClient
        return DeepSeekClient(api_key=deepseek_api_key)
    if profile.api_kind == "azure_openai":
        from .azure_openai_client import AzureOpenAIClient
        return AzureOpenAIClient(profile=profile)
    if profile.api_kind == "gemini_v2_wrapper":
        from .gemini_baseline_client import build_client as _gemini_build
        return _gemini_build(profile=profile, gemini_api_key=gemini_api_key)
    raise ValueError(f"Unknown api_kind: {profile.api_kind}")
