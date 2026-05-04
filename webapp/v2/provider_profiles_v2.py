"""
V2 — Profili provider LLM per la pipeline V2.

Ogni `ProviderProfile` cattura i limiti tecnici e i tuning dei batch per un
modello specifico. La `pipeline.py` legge il profilo per orchestrare il flow
senza conoscere le specifiche del provider sottostante.

I 2 provider supportati in PROD locale:
- gemini-2.5-flash    → default V2 (Gemini 2.5 Flash via gemini_client_v2)
- gpt-4.1-mini-azure  → Azure OpenAI GPT-4.1-mini (Foundry v1, EU region)

Tutti i campi sono override-abili via env var:
    V2_PROVIDER_<KEY_NORMALIZED>_<FIELD>
es. V2_PROVIDER_GPT_4_1_MINI_AZURE_BATCH_MAX_FILES=8
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ProviderProfile:
    """Configurazione tecnica di un provider LLM per la pipeline V2."""
    key: str                     # es. "gpt-4.1-mini-azure" — chiave PROFILES
    name: str                    # es. "gpt-4.1-mini" — nome modello in PRICING token_meter
    api_kind: str                # "azure_openai" | "gemini_v2_native"

    context_window: int          # token totali context+output
    max_output_tokens: int       # cap hard del modello

    batch_max_files: int
    batch_max_chars: int
    doc_cap_multiplier: float    # vs V2 baseline (1.0 = identico, 2.5 = 2.5x più alto)
    max_workers: int


PROFILES: dict[str, ProviderProfile] = {
    "gemini-2.5-flash": ProviderProfile(
        key="gemini-2.5-flash",
        name="gemini-2.5-flash",
        api_kind="gemini_v2_native",
        context_window=1_000_000,
        max_output_tokens=64_000,
        batch_max_files=4,
        batch_max_chars=50_000,
        doc_cap_multiplier=1.0,
        max_workers=7,
    ),
    "gpt-4.1-mini-azure": ProviderProfile(
        key="gpt-4.1-mini-azure",
        name="gpt-4.1-mini",
        api_kind="azure_openai",
        context_window=1_000_000,
        max_output_tokens=32_000,
        batch_max_files=10,
        batch_max_chars=180_000,
        doc_cap_multiplier=2.5,
        max_workers=6,
    ),
}


def _normalize_env_key(provider_key: str) -> str:
    """gpt-4.1-mini-azure -> GPT_4_1_MINI_AZURE per env var lookup."""
    return provider_key.upper().replace("-", "_").replace(".", "_")


def _env_override(provider_key: str, field: str, current_value, cast):
    """Legge override env var per il profilo, ritorna current_value se assente/invalido."""
    env_name = f"V2_PROVIDER_{_normalize_env_key(provider_key)}_{field.upper()}"
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return current_value
    try:
        return cast(raw)
    except (ValueError, TypeError):
        return current_value


def get_profile(provider_key: str) -> ProviderProfile:
    """
    Ritorna il profilo applicando eventuali override env var.

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


DEFAULT_PROVIDER = "gemini-2.5-flash"


def resolve_provider_key(explicit: str | None = None) -> str:
    """
    Risolve la chiave provider effettiva con questa priorità:
    1. argomento esplicito (se non None)
    2. env var V2_PROVIDER
    3. DEFAULT_PROVIDER (gemini-2.5-flash)
    """
    if explicit:
        return explicit
    raw = os.environ.get("V2_PROVIDER", "").strip()
    return raw or DEFAULT_PROVIDER
