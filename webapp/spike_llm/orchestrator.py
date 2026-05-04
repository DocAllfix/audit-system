"""
Spike LLM — Orchestratore matrice (pratica × provider).

Esegue in parallelo i task della matrice (zips × providers). Il default lancia
tutto contemporaneamente (es. 4 pratiche × 4 provider = 16 task concorrenti).
Le 4 chiavi API sono indipendenti → 4 rate-limit pool separati. L'unico
vincolo residuo è la quota TPM interna alla singola chiave quando lo stesso
provider riceve N pratiche contemporanee — mitigabile con `parallel_pratiche`.

Output: per ogni cella (zip_name, provider) ritorna il dict prodotto da
`process_zip_spike`. Ogni cella ha session_id univoco, output dir dedicata,
nessun cross-contamination su `token_meter`.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


def _slugify_zip_name(zip_name: str) -> str:
    """ALLEGATI MEDIL 37001_50001.zip -> ALLEGATI_MEDIL_37001_50001"""
    base = Path(zip_name).stem
    return "".join(c if (c.isalnum() or c == "_") else "_" for c in base)


def run_matrix(
    zips: List[Tuple[str, bytes]],
    providers: List[str],
    variant: str = "v2",
    parallel_pratiche: int = 4,
    deepseek_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    on_task_complete: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Esegue la matrice (pratica × provider) in parallelo.

    Args:
        zips: lista di tuple (zip_name, zip_bytes). zip_name è il nome file
            originale (incluso .zip).
        providers: lista di chiavi profilo (es. ["gemini-baseline", "deepseek-v4-flash",
            "gpt-4.1-mini", "gpt-4o-mini"]).
        variant: "v1" | "v2" — applicato via env var SPIKE_PROMPT_VARIANT.
        parallel_pratiche: quante pratiche eseguire in parallelo (default len(zips),
            cioè tutte). Ridurre a 2 se si osservano 429 ricorrenti su Azure.
        deepseek_api_key, gemini_api_key: chiavi opzionali (altrimenti lette da env).
        on_task_complete: callback per progress UI in tempo reale, chiamato con
            (zip_name, provider, result_dict) per ogni task completato.

    Returns:
        Dict {(zip_name, provider): result_dict}. result_dict ha sempre
        "success" e, in caso di errore non gestito, "error".
    """
    import os
    # Imposta SPIKE_PROMPT_VARIANT a livello processo (i thread lo leggono via env)
    if variant in ("v1", "v2"):
        os.environ["SPIKE_PROMPT_VARIANT"] = variant

    # Lazy import per non caricare V2 stack se l'orchestrator viene solo importato
    from .pipeline_spike import process_zip_spike

    tasks: List[Tuple[str, bytes, str]] = [
        (zip_name, zip_bytes, provider)
        for (zip_name, zip_bytes) in zips
        for provider in providers
    ]
    if not tasks:
        return {}

    # Pool size = parallel_pratiche × len(providers)
    # Default: tutte le celle in parallelo
    n_providers = len(providers)
    parallel_pratiche = max(1, min(parallel_pratiche, len(zips)))
    pool_size = parallel_pratiche * n_providers

    results: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def _run_one(zip_name: str, zip_bytes: bytes, provider: str) -> Dict[str, Any]:
        slug = _slugify_zip_name(zip_name)
        session_id = f"spike_{provider}_{slug}_{int(time.time() * 1000) % 1_000_000_000}"
        try:
            result = process_zip_spike(
                zip_bytes=zip_bytes,
                session_id=session_id,
                deepseek_api_key=deepseek_api_key,
                gemini_api_key=gemini_api_key,
                provider=provider,
            )
            # Aggiunge metadata utili per la tabella comparativa
            result.setdefault("zip_name", zip_name)
            result.setdefault("provider", provider)
            result.setdefault("session_id", session_id)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": f"orchestrator_unhandled: {e}",
                "zip_name": zip_name,
                "provider": provider,
                "session_id": session_id,
            }

    with ThreadPoolExecutor(max_workers=pool_size) as ex:
        futures = {
            ex.submit(_run_one, zn, zb, p): (zn, p)
            for (zn, zb, p) in tasks
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {
                    "success": False,
                    "error": f"orchestrator_future_failed: {e}",
                    "zip_name": key[0],
                    "provider": key[1],
                }
            results[key] = res
            if on_task_complete is not None:
                try:
                    on_task_complete(key[0], key[1], res)
                except Exception:
                    pass

    return results
