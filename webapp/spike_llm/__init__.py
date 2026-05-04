"""
V2 Spike — Multi-provider LLM (sostitutivi sperimentali di Gemini per analyze).

Pacchetto ISOLATO dal resto del codice V2. Importa moduli da `webapp/v2/`
ma non li modifica. Eliminabile in toto senza side-effect.

Provider supportati:
- gemini-baseline   : wrapper read-only su v2.gemini_client_v2 (riferimento)
- deepseek-v4-flash : DeepSeek V4 Flash via OpenAI-compat (server CN)
- gpt-4.1-mini      : Azure OpenAI GPT-4.1-mini (Azure EU)
- gpt-4o-mini       : Azure OpenAI GPT-4o-mini (Azure EU, batch ridotti)

Vedi `C:/Users/user/.claude/plans/synchronous-pondering-teacup.md` per i
dettagli completi del plan.

API pubblica:
    provider_profiles.get_profile(name)
    client_dispatch.get_client_module(profile)
    client_dispatch.build_client(profile, **kwargs)
    pipeline_spike.process_zip_spike(zip_bytes, session_id, provider=..., ...)
    orchestrator.run_matrix(zips, providers, ...)
"""
