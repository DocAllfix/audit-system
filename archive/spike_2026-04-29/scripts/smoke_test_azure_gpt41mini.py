"""
Smoke test minimo: verifica che il deployment Azure gpt-4.1-mini sia
raggiungibile via il nuovo Foundry v1 endpoint (OpenAI-compatible).

Output: stampa esito + pochi token di response + usage tokens.
"""
import os
import sys
from pathlib import Path


def load_env():
    """Carica .env nella cwd se esiste."""
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v:
            os.environ.setdefault(k, v)


def main() -> int:
    load_env()

    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI", "").strip()

    print("=" * 70)
    print("SMOKE TEST Azure gpt-4.1-mini (Foundry v1 endpoint)")
    print("=" * 70)
    print(f"  Endpoint   : {endpoint}")
    print(f"  Deployment : {deployment}")
    print(f"  Key prefix : {api_key[:8]}... (len={len(api_key)})")
    print()

    missing = []
    if not api_key:
        missing.append("AZURE_OPENAI_API_KEY")
    if not endpoint:
        missing.append("AZURE_OPENAI_ENDPOINT")
    if not deployment:
        missing.append("AZURE_OPENAI_DEPLOYMENT_GPT_41_MINI")
    if missing:
        print("ERROR missing env vars:", missing)
        return 2

    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR openai SDK not installed: pip install openai>=1.0")
        return 2

    # Foundry v1 = OpenAI-compatible endpoint, NO AzureOpenAI SDK
    client = OpenAI(base_url=endpoint, api_key=api_key)

    print("Sending non-streaming test prompt...")
    print()
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": "Sei un assistente conciso. Rispondi solo in italiano."},
                {"role": "user", "content": "Dimmi in una frase cosa sei e che modello sei."},
            ],
            temperature=0.0,
            max_tokens=100,
        )
    except Exception as e:
        print(f"FAIL non-streaming: {type(e).__name__}: {e}")
        return 1

    msg = resp.choices[0].message.content
    finish = resp.choices[0].finish_reason
    usage = resp.usage

    print("Response (text):")
    print(f"  {msg!r}")
    print()
    print(f"  finish_reason : {finish}")
    print(f"  prompt_tokens : {usage.prompt_tokens}")
    print(f"  completion_t. : {usage.completion_tokens}")
    print(f"  total_tokens  : {usage.total_tokens}")
    if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", None)
        print(f"  cached_tokens : {cached}")
    print()

    # Test 2: streaming (è quello che useremo nel pipeline_spike)
    print("Sending streaming test prompt...")
    chunks_received = 0
    text_acc = []
    finish_reason_stream = None
    usage_stream = None
    try:
        stream = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": "Sei un assistente conciso."},
                {"role": "user", "content": "Conta da 1 a 5 in italiano."},
            ],
            temperature=0.0,
            max_tokens=80,
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            chunks_received += 1
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                text_acc.append(chunk.choices[0].delta.content)
            if chunk.choices and chunk.choices[0].finish_reason:
                finish_reason_stream = chunk.choices[0].finish_reason
            if hasattr(chunk, "usage") and chunk.usage:
                usage_stream = chunk.usage
    except Exception as e:
        print(f"FAIL streaming: {type(e).__name__}: {e}")
        return 1

    print(f"  Chunks received : {chunks_received}")
    print(f"  Text accumulated: {''.join(text_acc)!r}")
    print(f"  finish_reason   : {finish_reason_stream}")
    if usage_stream:
        print(f"  Stream usage    : in={usage_stream.prompt_tokens} out={usage_stream.completion_tokens}")
    print()
    print("=" * 70)
    print("SMOKE TEST OK — gpt-4.1-mini funziona via Foundry v1 endpoint")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
