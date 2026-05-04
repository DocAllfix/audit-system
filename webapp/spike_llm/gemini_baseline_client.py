"""
V2 Spike — Gemini Baseline Client (wrapper read-only su v2.gemini_client_v2).

Permette di includere il provider "gemini-baseline" nella matrice spike usando
ESATTAMENTE lo stesso client e prompt del flow V2 PROD attuale, senza modifiche
a `webapp/v2/`. È un wrapper read-only: importa `analyze_batch_streaming` di V2
e lo richiama come-è. Il prompt universale di V2 viene caricato internamente da
V2 (NON il prompt spike), per mantenere la baseline pulita e confrontabile con
la PROD attuale.

Nessun side effect su V2:
- session_id univoco dello spike (`spike_gemini-baseline_<zip>_<ts>`)
- output dir dedicata (`temp/spike_llm/gemini-baseline/`)
- token_meter già conosce `gemini-2.5-flash` in PRICING
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from v2.gemini_client_v2 import (
    analyze_batch_streaming as _v2_analyze,
)
from v2.stream_buffer import DEFAULT_MAX_CHARS, StreamResult
from v2.yaml_stream_parser import ParsedMarker

from .provider_profiles import ProviderProfile


def build_client(profile: ProviderProfile, gemini_api_key: Optional[str] = None):
    """
    Costruisce un client Gemini riusando la factory V2.

    Per il profilo gemini-baseline il "client" è una `genai.Client` standard.
    """
    if profile.api_kind != "gemini_v2_wrapper":
        raise ValueError(
            f"gemini_baseline_client richiede api_kind=gemini_v2_wrapper, "
            f"ricevuto: {profile.api_kind}"
        )
    # Lazy import per non forzare presenza google-genai se non si usa baseline
    from v2.genai_factory_v2 import create_genai_client_v2
    return create_genai_client_v2(api_key=gemini_api_key)


def analyze_batch_streaming(
    client,
    batch_docs: List[Dict[str, Any]],
    batch_idx: int = 0,
    total_docs: int = 0,
    universal_prompt: Optional[str] = None,
    cached_content_id: Optional[str] = None,
    on_token: Optional[Callable[[str], None]] = None,
    on_marker: Optional[Callable[[ParsedMarker], None]] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    enable_retry: bool = True,
    meter_session_id: Optional[str] = None,
    compact_mode: bool = False,
    model_override: Optional[str] = None,
) -> StreamResult:
    """
    Wrapper read-only su `v2.gemini_client_v2.analyze_batch_streaming`.

    Tutti i parametri vengono inoltrati invariati. Il prompt universale viene
    caricato da V2 internamente (NON dal prompt spike), per ottenere una
    baseline confrontabile con PROD V2 attuale.

    Side effect su V2: ZERO. session_id e output dir sono spike-specifici.
    """
    return _v2_analyze(
        client=client,
        batch_docs=batch_docs,
        batch_idx=batch_idx,
        total_docs=total_docs,
        universal_prompt=universal_prompt,  # se None, V2 carica il suo prompt PROD
        cached_content_id=cached_content_id,
        on_token=on_token,
        on_marker=on_marker,
        max_chars=max_chars,
        enable_retry=enable_retry,
        meter_session_id=meter_session_id,
        compact_mode=compact_mode,
        model_override=model_override,
    )
