"""
AUDIT-OS Pipeline V2 — Triage Funnel architecture.

Namespace isolato dal sistema V1 in `webapp/modules/`. Nessun import da V2 verso V1
(eccetto tramite il config principale). Attivabile via env var USE_V2_PIPELINE.

Vedi `docs/V2_EXECUTION_TRACKER.md` per la spec operativa completa.
"""

__version__ = "0.1.0-alpha"
