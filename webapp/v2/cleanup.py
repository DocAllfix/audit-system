"""
V2 — Cleanup script (Fase 6) — TTL gestione progress JSONL.

Politica:
- File `temp/progress/{session_id}.jsonl` più vecchi di TTL_LIVE_DAYS (7gg)
  vengono compressi (gzip) in `temp/progress_archive/{yyyy-mm}/`
- File in archive più vecchi di TTL_ARCHIVE_DAYS (30gg) vengono cancellati
  definitivamente
- Esecuzione idempotente: ri-runnabile più volte senza effetti collaterali

Uso:
    python -m v2.cleanup            (cron giornaliero)
    python -m v2.cleanup --dry-run  (mostra cosa farebbe senza toccare nulla)

Exit code:
    0 → cleanup completato
    1 → errore durante esecuzione
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple


# Configurazione TTL (giorni). Override via env.
TTL_LIVE_DAYS = int(os.environ.get("V2_PROGRESS_TTL_LIVE_DAYS", "7"))
TTL_ARCHIVE_DAYS = int(os.environ.get("V2_PROGRESS_TTL_ARCHIVE_DAYS", "30"))

# Path base
_WEBAPP_DIR = Path(__file__).resolve().parent.parent
PROGRESS_DIR = _WEBAPP_DIR.parent / "temp" / "progress"
ARCHIVE_DIR = _WEBAPP_DIR.parent / "temp" / "progress_archive"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _file_age_days(path: Path) -> float:
    """Età file in giorni (basata su mtime)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0.0
    return (time.time() - mtime) / 86400.0


def _archive_subdir_for(file_mtime: float) -> Path:
    """Sottocartella archive in formato YYYY-MM in base alla data file."""
    dt = datetime.fromtimestamp(file_mtime, tz=timezone.utc)
    return ARCHIVE_DIR / dt.strftime("%Y-%m")


def _safe_rel(path: Path) -> str:
    """Logging path: relativo al repo se possibile, altrimenti assoluto."""
    try:
        return str(path.relative_to(_WEBAPP_DIR.parent))
    except ValueError:
        return str(path)


# ──────────────────────────────────────────────────────────────────────────────
# Step 1: archive (compress + move)
# ──────────────────────────────────────────────────────────────────────────────

def _archive_old_progress(dry_run: bool = False) -> Tuple[int, int]:
    """
    Comprimi (gzip) e sposta in archive i .jsonl > TTL_LIVE_DAYS.

    Returns:
        (count, bytes_freed)
    """
    if not PROGRESS_DIR.exists():
        return 0, 0

    count = 0
    bytes_freed = 0

    for path in PROGRESS_DIR.glob("*.jsonl"):
        age = _file_age_days(path)
        if age < TTL_LIVE_DAYS:
            continue

        try:
            mtime = path.stat().st_mtime
            size = path.stat().st_size
        except OSError:
            continue

        target_dir = _archive_subdir_for(mtime)
        target_path = target_dir / f"{path.stem}.jsonl.gz"

        action = f"archive {path.name} → {_safe_rel(target_path)}"
        if dry_run:
            print(f"[DRY-RUN] {action} (età {age:.1f}gg, {size}B)")
            count += 1
            bytes_freed += size
            continue

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            # Compressione streaming (memoria costante)
            with open(path, "rb") as src, gzip.open(target_path, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
            # Conserva mtime sull'archivio per debug
            os.utime(target_path, (mtime, mtime))
            # Rimuovi originale solo dopo archiviazione riuscita
            path.unlink()
            count += 1
            bytes_freed += size
            print(f"[V2 CLEANUP] {action} (età {age:.1f}gg, {size}B → compresso)")
        except Exception as e:
            print(f"[V2 CLEANUP] Archive fallito {path.name}: {e}")

    return count, bytes_freed


# ──────────────────────────────────────────────────────────────────────────────
# Step 2: delete archived files older than TTL_ARCHIVE_DAYS
# ──────────────────────────────────────────────────────────────────────────────

def _delete_old_archive(dry_run: bool = False) -> Tuple[int, int]:
    """
    Cancella file in archive più vecchi di TTL_ARCHIVE_DAYS.

    Returns:
        (count, bytes_freed)
    """
    if not ARCHIVE_DIR.exists():
        return 0, 0

    count = 0
    bytes_freed = 0

    for path in ARCHIVE_DIR.rglob("*.jsonl.gz"):
        age = _file_age_days(path)
        if age < TTL_ARCHIVE_DAYS:
            continue

        try:
            size = path.stat().st_size
        except OSError:
            continue

        action = f"delete {_safe_rel(path)}"
        if dry_run:
            print(f"[DRY-RUN] {action} (età {age:.1f}gg, {size}B)")
            count += 1
            bytes_freed += size
            continue

        try:
            path.unlink()
            count += 1
            bytes_freed += size
            print(f"[V2 CLEANUP] {action} (età {age:.1f}gg, {size}B)")
        except Exception as e:
            print(f"[V2 CLEANUP] Delete fallito {path.name}: {e}")

    # Cleanup cartelle vuote nell'archive (best effort)
    if not dry_run:
        for subdir in ARCHIVE_DIR.glob("*/"):
            try:
                if not any(subdir.iterdir()):
                    subdir.rmdir()
            except OSError:
                pass

    return count, bytes_freed


# ──────────────────────────────────────────────────────────────────────────────
# Step 3: cleanup orphan lock files
# ──────────────────────────────────────────────────────────────────────────────

def _cleanup_orphan_locks(dry_run: bool = False) -> int:
    """Rimuove .lock orfani (senza .jsonl associato) > 1 giorno."""
    if not PROGRESS_DIR.exists():
        return 0
    count = 0
    for lock in PROGRESS_DIR.glob("*.lock"):
        if _file_age_days(lock) < 1:
            continue
        jsonl = lock.with_suffix(".jsonl")
        if jsonl.exists():
            continue
        if dry_run:
            print(f"[DRY-RUN] orphan lock {lock.name}")
            count += 1
            continue
        try:
            lock.unlink()
            count += 1
        except OSError:
            pass
    return count


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def run_cleanup(dry_run: bool = False) -> dict:
    """Esegue tutte le fasi di cleanup. Ritorna un summary."""
    print(f"[V2 CLEANUP] Inizio (dry_run={dry_run}, TTL_LIVE={TTL_LIVE_DAYS}gg, TTL_ARCHIVE={TTL_ARCHIVE_DAYS}gg)")
    archived, archived_bytes = _archive_old_progress(dry_run=dry_run)
    deleted, deleted_bytes = _delete_old_archive(dry_run=dry_run)
    locks = _cleanup_orphan_locks(dry_run=dry_run)
    summary = {
        "dry_run": dry_run,
        "archived_count": archived,
        "archived_bytes": archived_bytes,
        "deleted_count": deleted,
        "deleted_bytes": deleted_bytes,
        "orphan_locks_removed": locks,
    }
    print(f"[V2 CLEANUP] Summary: {summary}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="V2 progress cleanup")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra cosa farebbe senza toccare nulla")
    args = parser.parse_args()
    try:
        run_cleanup(dry_run=args.dry_run)
        return 0
    except Exception as e:
        print(f"[V2 CLEANUP] Errore: {e}")
        return 1


if __name__ == "__main__":
    # Setup sys.path se eseguito direttamente
    here = os.path.dirname(os.path.abspath(__file__))
    webapp_dir = os.path.dirname(here)
    if webapp_dir not in sys.path:
        sys.path.insert(0, webapp_dir)
    sys.exit(main())
