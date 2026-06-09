# ==============================================================================
# LLM CHECKLIST CLIENT - Astrazione provider per la Tab 2 (Checklist)
# ==============================================================================
# Punto di astrazione UNICO per le chiamate LLM della Tab 2. Permette di usare
# Gemini (default, comportamento storico invariato) oppure Azure OpenAI
# GPT-4.1-mini, selezionabile via env var TAB2_PROVIDER, senza modificare la
# logica di calcolo/rigenerazione clausole in checklist_producer.py.
#
#   TAB2_PROVIDER = "gemini" (default)  -> path Gemini identico a prima
#   TAB2_PROVIDER = "azure"             -> path Azure GPT-4.1-mini
#
# Su errore Azure (429 esauriti / transient), fallback automatico a Gemini sul
# singolo call (disattivabile con TAB2_DISABLE_FALLBACK=1).
#
# Il contratto e' volutamente IDENTICO a `response.text` di Gemini: la funzione
# ritorna SEMPRE una stringa. Per le chiamate JSON la stringa e' il JSON grezzo,
# che il chiamante continua a fare `json.loads(...)` esattamente come oggi.
# ==============================================================================

import os
import threading
from typing import Dict, List, Optional

from config import GEMINI_MODEL_CHECKLIST
from modules.genai_factory import create_genai_client

try:
    from modules.gemini_throttle import gemini_structured_slot
except ImportError:
    from contextlib import contextmanager

    @contextmanager
    def gemini_structured_slot():
        yield


# ──────────────────────────────────────────────────────────────────────────────
# Selezione provider
# ──────────────────────────────────────────────────────────────────────────────

_AZURE_ALIASES = {"azure", "gpt-4.1-mini-azure", "gpt-4.1-mini", "gpt41mini"}
_AZURE_PROVIDER_KEY = "gpt-4.1-mini-azure"  # chiave profilo in provider_profiles_v2


def _active_provider() -> str:
    """Ritorna 'azure' o 'gemini' in base a TAB2_PROVIDER (default gemini)."""
    raw = os.environ.get("TAB2_PROVIDER", "gemini").strip().lower()
    return "azure" if raw in _AZURE_ALIASES else "gemini"


def _fallback_disabled() -> bool:
    """True se il fallback Gemini su errore Azure e' disabilitato via env."""
    return os.environ.get("TAB2_DISABLE_FALLBACK", "0").strip() == "1"


def active_tab2_model() -> str:
    """Nome modello attivo per la Tab 2 (per i metadata del report)."""
    if _active_provider() == "azure":
        return "gpt-4.1-mini (azure)"
    return GEMINI_MODEL_CHECKLIST


# Semaforo leggero per il path Azure: limita solo il numero di socket aperti in
# parallelo (16M TPM rende superfluo un throttle aggressivo). I 6 gruppi
# paralleli della Tab 2 girano comodamente sotto questo cap.
_AZURE_LIMIT = int(os.environ.get("TAB2_AZURE_CONCURRENCY", "8"))
_AZURE_SLOT = threading.BoundedSemaphore(_AZURE_LIMIT)

# Client Azure lazy singleton (creato una sola volta, riusato tra i thread).
_azure_client = None
_azure_client_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────────────────
# Conversione schema Gemini -> Azure strict JSON Schema
# ──────────────────────────────────────────────────────────────────────────────

def to_azure_json_schema(gemini_schema: Dict) -> Dict:
    """
    Converte uno schema in formato Gemini (response_schema) nel formato richiesto
    da Azure OpenAI strict mode.

    Azure strict mode esige:
      - "additionalProperties": false su OGNI nodo di tipo object
      - tutte le proprieta' elencate in "required" (gia' garantito dagli schemi
        Tab 2: build_group_schema / build_response_schema mettono tutte le chiavi
        in required)

    Non muta l'input: lavora su una copia profonda.
    """
    import copy

    schema = copy.deepcopy(gemini_schema)

    def _enforce(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                props = node.get("properties")
                if isinstance(props, dict):
                    # strict: tutte le proprieta' devono essere in required
                    node["required"] = list(props.keys())
                    for child in props.values():
                        _enforce(child)
            elif node.get("type") == "array":
                _enforce(node.get("items"))
        elif isinstance(node, list):
            for item in node:
                _enforce(item)

    _enforce(schema)
    return schema


# ──────────────────────────────────────────────────────────────────────────────
# Path Gemini (comportamento storico invariato)
# ──────────────────────────────────────────────────────────────────────────────

def _gemini_generate(
    prompt: str,
    temperature: float,
    max_output_tokens: int,
    json_schema: Optional[Dict],
    api_key: Optional[str],
    gemini_client,
    gemini_model: Optional[str],
) -> str:
    """Replica ESATTA della chiamata Gemini usata finora nella Tab 2."""
    from google.genai import types

    client = gemini_client or create_genai_client(api_key)
    model = gemini_model or GEMINI_MODEL_CHECKLIST

    config_kwargs = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if json_schema:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = json_schema

    with gemini_structured_slot():
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )

    return (getattr(response, "text", None) or "").strip()


# ──────────────────────────────────────────────────────────────────────────────
# Path Azure GPT-4.1-mini
# ──────────────────────────────────────────────────────────────────────────────

def _get_azure_client():
    """Crea/riusa il client Azure (lazy singleton thread-safe)."""
    global _azure_client
    if _azure_client is not None:
        return _azure_client
    with _azure_client_lock:
        if _azure_client is None:
            from v2.provider_profiles_v2 import get_profile
            from v2.azure_openai_client_v2 import AzureOpenAIClientV2

            profile = get_profile(_AZURE_PROVIDER_KEY)
            _azure_client = AzureOpenAIClientV2(profile=profile)
    return _azure_client


def _azure_generate(
    prompt: str,
    temperature: float,
    max_output_tokens: int,
    json_schema: Optional[Dict],
    schema_name: str,
    batch_idx: int,
) -> str:
    """Chiamata Azure GPT-4.1-mini (non-streaming, blocking)."""
    client = _get_azure_client()

    # Il prompt Tab 2 e' monolitico (prompt-norma + report + istruzioni gruppo):
    # lo passiamo come singolo user message, senza alterarlo.
    messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]

    azure_schema = to_azure_json_schema(json_schema) if json_schema else None

    with _AZURE_SLOT:
        text, _usage = client.chat_complete(
            messages=messages,
            max_tokens=max_output_tokens,
            temperature=temperature,
            json_schema=azure_schema,
            schema_name=schema_name,
            batch_idx=batch_idx,
        )

    return (text or "").strip()


# ──────────────────────────────────────────────────────────────────────────────
# API pubblica: dispatch provider
# ──────────────────────────────────────────────────────────────────────────────

def checklist_llm_generate(
    prompt: str,
    temperature: float = 0.0,
    max_output_tokens: int = 4000,
    json_schema: Optional[Dict] = None,
    api_key: Optional[str] = None,
    gemini_client=None,
    gemini_model: Optional[str] = None,
    schema_name: str = "checklist",
    batch_idx: int = 0,
) -> str:
    """
    Genera testo/JSON per la Tab 2 usando il provider attivo (TAB2_PROVIDER).

    Ritorna SEMPRE una stringa (equivalente a `response.text` di Gemini): per le
    chiamate JSON e' il JSON grezzo, che il chiamante continua a parsare come oggi.

    Args:
        prompt: prompt completo (monolitico) da inviare al modello.
        temperature: temperatura di sampling (0.0 deterministico).
        max_output_tokens: cap output.
        json_schema: schema in formato Gemini; se presente forza output JSON
                     strutturato (convertito per Azure se necessario).
        api_key: chiave Gemini (per creare il client se gemini_client e' None).
        gemini_client: client Gemini gia' istanziato (riuso).
        gemini_model: override modello Gemini (default GEMINI_MODEL_CHECKLIST).
        schema_name: nome logico schema (richiesto da Azure strict).
        batch_idx: indice per logging/eccezioni.
    """
    if _active_provider() == "azure":
        try:
            return _azure_generate(
                prompt=prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                json_schema=json_schema,
                schema_name=schema_name,
                batch_idx=batch_idx,
            )
        except Exception as azure_err:  # noqa: BLE001
            if _fallback_disabled():
                raise
            print(
                f"[TAB2] Azure fallito (batch {batch_idx}): {azure_err}. "
                "Fallback a Gemini per questo call."
            )
            # Fallback trasparente: stesso comportamento storico Gemini.
            return _gemini_generate(
                prompt=prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                json_schema=json_schema,
                api_key=api_key,
                gemini_client=gemini_client,
                gemini_model=gemini_model,
            )

    return _gemini_generate(
        prompt=prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        json_schema=json_schema,
        api_key=api_key,
        gemini_client=gemini_client,
        gemini_model=gemini_model,
    )
