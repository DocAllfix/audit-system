"""
V2 — GenAI Factory (replica leggera di modules/genai_factory.py per isolamento V2).

Crea client `google.genai.Client` con supporto proxy trasparente, identico a V1
ma in namespace V2 per rispettare il confine di isolamento (vedi
tests/test_v2_pipeline/test_v2_isolation.py).

Da server EU (Hetzner DE) il proxy è obbligatorio: senza, le chiamate dirette a
generativelanguage.googleapis.com falliscono con FAILED_PRECONDITION.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

# webapp/ è già nel sys.path quando l'app gira
_WEBAPP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WEBAPP_DIR not in sys.path:
    sys.path.insert(0, _WEBAPP_DIR)

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from config import GEMINI_PROXY_URL, GEMINI_PROXY_SECRET  # noqa: E402

# Log "una volta sola" — singleton di processo
_LOGGED_PROXY_STATE = False


def create_genai_client_v2(api_key: Optional[str] = None) -> genai.Client:
    """
    Crea un client `genai.Client` con supporto proxy trasparente.

    Args:
        api_key: chiave Gemini. Se None, legge da env var `GEMINI_API_KEY`.
                 Se nemmeno l'env var è presente, solleva ValueError esplicito
                 (mai client "muto" che fallirà su prima chiamata).

    Returns:
        Client `genai.Client` pronto all'uso.

    Raises:
        ValueError: se non riesce a determinare l'api_key.
    """
    global _LOGGED_PROXY_STATE

    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise ValueError(
            "create_genai_client_v2: api_key non fornita e GEMINI_API_KEY "
            "non presente in env. Impossibile creare client."
        )

    if GEMINI_PROXY_URL:
        headers = {}
        if GEMINI_PROXY_SECRET:
            headers["X-Proxy-Secret"] = GEMINI_PROXY_SECRET
        http_opts = types.HttpOptions(base_url=GEMINI_PROXY_URL, headers=headers)
        if not _LOGGED_PROXY_STATE:
            print(f"[V2 GENAI] Client via proxy: {GEMINI_PROXY_URL[:60]}...")
            _LOGGED_PROXY_STATE = True
        return genai.Client(api_key=key, http_options=http_opts)

    if not _LOGGED_PROXY_STATE:
        print(
            "[V2 GENAI WARN] GEMINI_PROXY_URL non configurato. Client diretto. "
            "Da server EU causa FAILED_PRECONDITION."
        )
        _LOGGED_PROXY_STATE = True
    return genai.Client(api_key=key)
