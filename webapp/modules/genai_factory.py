# ==============================================================================
# GENAI FACTORY - Creazione centralizzata client Google GenAI
# ==============================================================================
# Tutti i moduli che necessitano di un client genai DEVONO usare questo factory
# per garantire che il proxy (se configurato) venga applicato uniformemente.
# ==============================================================================

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google import genai
from google.genai import types

from config import GEMINI_PROXY_URL, GEMINI_PROXY_SECRET


def create_genai_client(api_key: str) -> genai.Client:
    """
    Crea un client genai.Client con supporto proxy trasparente.

    Se GEMINI_PROXY_URL e configurato, tutte le chiamate API vengono
    instradate tramite il proxy (Cloud Function in regione supportata).
    Altrimenti, connessione diretta a Google (comportamento default).
    """
    if GEMINI_PROXY_URL:
        # Costruisci http_options con proxy
        headers = {}
        if GEMINI_PROXY_SECRET:
            headers["X-Proxy-Secret"] = GEMINI_PROXY_SECRET

        http_opts = types.HttpOptions(
            base_url=GEMINI_PROXY_URL,
            headers=headers
        )
        return genai.Client(api_key=api_key, http_options=http_opts)
    else:
        # Connessione diretta (default, nessuna modifica al comportamento esistente)
        return genai.Client(api_key=api_key)
