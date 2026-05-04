"""
V2 — Cache Refresher (Fase 3) — script standalone per cron.

Esegue una refresh della cache Gemini una volta sola (esce subito dopo).
Da schedulare via cron Linux o Task Scheduler Windows ogni 30 minuti
nelle ore lavorative (08:00-20:00).

Utilizzo:
    python -m v2.cache_refresher

oppure:
    cd webapp && python -c "from v2.cache_refresher import main; main()"

Exit code:
    0 → cache disponibile dopo refresh
    1 → refresh fallito (l'app continuerà con fallback inline)
    2 → caching disabilitato globalmente

Da V2 production (Fase 9), schedulare con cron:
    */30 8-20 * * * /opt/auditos/venv/bin/python -m v2.cache_refresher >> /var/log/auditos/cache_refresh.log 2>&1
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    """Entry point del refresher. Ritorna exit code POSIX."""
    # Setup sys.path (script eseguibile da qualsiasi cwd)
    here = os.path.dirname(os.path.abspath(__file__))
    webapp_dir = os.path.dirname(here)
    if webapp_dir not in sys.path:
        sys.path.insert(0, webapp_dir)

    # Import lazy (dopo sys.path)
    from v2.cache_manager import CACHE_DISABLED, refresh_cache
    from v2.genai_factory_v2 import create_genai_client_v2

    if CACHE_DISABLED:
        print("[CACHE REFRESHER] V2_CACHE_DISABLED=true, skip")
        return 2

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[CACHE REFRESHER] GEMINI_API_KEY non impostata, abort")
        return 1

    try:
        client = create_genai_client_v2(api_key=api_key)
    except Exception as e:
        print(f"[CACHE REFRESHER] Impossibile creare client: {e}")
        return 1

    ok = refresh_cache(client)
    if ok:
        print("[CACHE REFRESHER] Cache refreshed OK")
        return 0
    print("[CACHE REFRESHER] Refresh fallito")
    return 1


if __name__ == "__main__":
    sys.exit(main())
