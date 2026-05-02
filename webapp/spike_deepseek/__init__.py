"""
V2 Spike — DeepSeek V4 Flash (sostitutivo sperimentale di Gemini per analyze).

Pacchetto ISOLATO dal resto del codice V2. Importa moduli da `webapp/v2/`
ma non li modifica. Eliminabile in toto senza side-effect.

Vedi `C:/Users/user/.claude/plans/synchronous-pondering-teacup.md` per i
dettagli completi del plan.

API pubblica:
    deepseek_client.analyze_batch_streaming(...)
    pipeline_spike.process_zip_spike(...)
"""
