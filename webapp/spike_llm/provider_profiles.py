"""
Spike LLM — Profili per provider.

Ogni `ProviderProfile` cattura i limiti tecnici e i tuning dei batch per un
modello specifico. Il `pipeline_spike.py` legge il profilo per orchestrare
il flow senza conoscere le specifiche del provider sottostante.

I 4 provider attualmente supportati:
- gemini-baseline   → V2 attuale (Gemini 2.5 Flash via wrapper read-only)
- deepseek-v4-flash → DeepSeek V4 Flash via OpenAI compat
- gpt-4.1-mini      → Azure OpenAI GPT-4.1-mini
- gpt-4o-mini       → Azure OpenAI GPT-4o-mini (limiti stretti, batch ridotti)

Tutti i campi sono override-abili via env var:
    SPIKE_LLM_<NAME_NORMALIZED>_<FIELD>
es. SPIKE_LLM_GPT_4O_MINI_BATCH_MAX_FILES=6
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ProviderProfile:
    """Configurazione tecnica di un provider LLM per lo spike."""
    # Identificatori
    key: str                     # es. "gpt-4o-mini" — chiave del dict PROFILES
    name: str                    # es. "gpt-4o-mini" — nome modello in PRICING token_meter
    api_kind: str                # "deepseek" | "azure_openai" | "gemini_v2_wrapper"

    # Limiti tecnici del modello
    context_window: int          # token totali context+output
    max_output_tokens: int       # cap hard del modello (margine sotto il limite)

    # Tuning batch (sovrascrivibili via env var)
    batch_max_files: int
    batch_max_chars: int
    doc_cap_multiplier: float    # vs V2 baseline (1.0 = identico, 2.5 = 2.5× più alto)
    max_workers: int


PROFILES: dict[str, ProviderProfile] = {
    "gemini-baseline": ProviderProfile(
        key="gemini-baseline",
        name="gemini-2.5-flash",
        api_kind="gemini_v2_wrapper",
        context_window=1_000_000,
        max_output_tokens=64_000,
        batch_max_files=4,           # = V2 PROD attuale
        batch_max_chars=50_000,      # = V2 PROD attuale
        doc_cap_multiplier=1.0,      # = V2 PROD attuale
        max_workers=7,               # = V2 PROD attuale
    ),
    "deepseek-v4-flash": ProviderProfile(
        key="deepseek-v4-flash",
        name="deepseek-v4-flash",
        api_kind="deepseek",
        context_window=1_000_000,
        max_output_tokens=64_000,
        batch_max_files=12,
        batch_max_chars=200_000,
        doc_cap_multiplier=2.5,
        max_workers=14,
    ),
    "gpt-4.1-mini": ProviderProfile(
        key="gpt-4.1-mini",
        name="gpt-4.1-mini",
        api_kind="azure_openai",
        context_window=1_000_000,
        max_output_tokens=32_000,
        batch_max_files=10,
        batch_max_chars=180_000,
        doc_cap_multiplier=2.5,
        max_workers=6,  # ridotto da 10 a 6: compromesso velocità/rate-limit. Con retry=3+backoff=60s ZERO batch persi attesi.
    ),
}


def _normalize_env_key(provider_key: str) -> str:
    """gpt-4o-mini -> GPT_4O_MINI per env var lookup."""
    return provider_key.upper().replace("-", "_").replace(".", "_")


def _env_override(provider_key: str, field: str, current_value, cast):
    """Legge override env var per il profilo, ritorna current_value se assente/invalido."""
    env_name = f"SPIKE_LLM_{_normalize_env_key(provider_key)}_{field.upper()}"
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return current_value
    try:
        return cast(raw)
    except (ValueError, TypeError):
        return current_value


def get_profile(provider_key: str) -> ProviderProfile:
    """
    Ritorna il profilo per il provider, applicando eventuali override env var.

    Raises:
        KeyError se provider_key non è in PROFILES.
    """
    if provider_key not in PROFILES:
        raise KeyError(
            f"Provider '{provider_key}' non noto. "
            f"Disponibili: {sorted(PROFILES.keys())}"
        )

    base = PROFILES[provider_key]
    return replace(
        base,
        batch_max_files=_env_override(provider_key, "BATCH_MAX_FILES", base.batch_max_files, int),
        batch_max_chars=_env_override(provider_key, "BATCH_MAX_CHARS", base.batch_max_chars, int),
        max_workers=_env_override(provider_key, "MAX_WORKERS", base.max_workers, int),
        doc_cap_multiplier=_env_override(provider_key, "DOC_CAP_MULTIPLIER", base.doc_cap_multiplier, float),
        max_output_tokens=_env_override(provider_key, "MAX_OUTPUT_TOKENS", base.max_output_tokens, int),
    )


def list_provider_keys() -> list[str]:
    """Lista delle chiavi profilo disponibili (ordine deterministico)."""
    return list(PROFILES.keys())
