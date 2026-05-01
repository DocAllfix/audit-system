"""
V2 — ZIP Extractor (Fase 8).

Estrae ZIP bytes (anche nidificati fino a max_depth=10) in una directory
temporanea isolata, ritornando lista file con metadati standard V2.

Replica minimal della logica V1 senza importare da modules/. Differenze
principali:
- Output dict ha già i campi attesi da file_triage.triage_files()
  (filename, path, size, category)
- Mai eccezione: errori → log + skip file. Solo input ZIP corrotto al primo
  livello solleva ValueError esplicito (caller decide se abortire)
- Anti path-traversal: i file estratti vengono normalizzati e contenuti
  dentro extract_dir (rifiutati path con ".." o assoluti)

API pubblica:
    extract_zip_bytes(zip_bytes, session_id) -> Tuple[List[Dict], Path]
    cleanup_extraction(extract_dir) -> int
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

_WEBAPP_DIR = Path(__file__).resolve().parent.parent
EXTRACT_BASE_DIR = _WEBAPP_DIR.parent / "temp" / "v2_extract"

# Profondità massima ZIP nidificati (anti zip-bomb)
MAX_NESTED_DEPTH = 10

# Hard limit sul numero file estratti (anti zip-bomb)
MAX_TOTAL_FILES = 5000

# Hard limit dimensione cumulativa estrazione (anti zip-bomb)
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

# Validazione anti path-traversal session_id
_VALID_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,200}$")


# ──────────────────────────────────────────────────────────────────────────────
# Categorize per estensione (replica minimal V1)
# ──────────────────────────────────────────────────────────────────────────────

# Estensioni che V2 (Fase 8) sa gestire: solo PDF per ora.
# Per altri formati, V2 li include ma marca come "non_pdf" e file_triage
# li mette nel bucket relativo (skipped).
_CATEGORY_BY_EXT = {
    ".pdf": "pdf",
    # NOTA: doc/xlsx/ecc. sono mappati a categorie ma il triage V2 Fase 1
    # li tratterà come non_pdf passthrough.
    ".doc": "word", ".docx": "word",
    ".xls": "excel", ".xlsx": "excel", ".xlsm": "excel",
    ".jpg": "image", ".jpeg": "image", ".png": "image",
    ".gif": "image", ".bmp": "image", ".tiff": "image",
    ".heic": "heic", ".heif": "heic",
    ".txt": "text", ".csv": "text",
    ".rtf": "rtf",
    ".p7m": "p7m",
    ".msg": "email", ".eml": "eml",
    ".html": "html", ".htm": "html",
    ".xml": "xml",
    ".odt": "odt", ".ods": "ods",
    ".pptx": "pptx", ".ppt": "pptx",
    ".zip": "zip",
}

# Estensioni da SKIPPARE completamente
_SKIP_EXTENSIONS = {
    ".vcf", ".exe", ".dll", ".bat", ".cmd", ".msi", ".com",
    ".sys", ".ini", ".log", ".tmp", ".bak",
    ".lnk", ".url", ".db", ".sqlite", ".mdb",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
    ".psd", ".ai", ".sketch",
    ".dmg", ".iso", ".tar", ".gz", ".rar", ".7z",
}


def _categorize_file(filename: str) -> str:
    """Ritorna categoria 'pdf','word','excel',... o 'skip','other'."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in _SKIP_EXTENSIONS:
        return "skip"
    return _CATEGORY_BY_EXT.get(ext, "other")


# ──────────────────────────────────────────────────────────────────────────────
# Anti path-traversal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_extract_path(target_root: Path, member_name: str) -> Path:
    """
    Costruisce il path di destinazione verificando il containment.
    Rifiuta nomi con .. o path assoluti.
    """
    # Normalizza separatori e rimuovi prefissi assoluti
    cleaned = member_name.replace("\\", "/").lstrip("/")
    # Risolvi candidato
    candidate = (target_root / cleaned).resolve()
    target_root_resolved = target_root.resolve()
    # Containment check
    if not str(candidate).startswith(str(target_root_resolved)):
        raise ValueError(f"path_traversal_detected: {member_name!r}")
    return candidate


# ──────────────────────────────────────────────────────────────────────────────
# Estrazione singolo ZIP
# ──────────────────────────────────────────────────────────────────────────────

def _extract_single_zip(
    zip_path: Path,
    extract_dir: Path,
    depth: int,
    state: Dict[str, int],
) -> List[Dict[str, Any]]:
    """
    Estrae un ZIP. Aggiorna lo state condiviso (counter file/bytes/depth) per
    enforcement dei limiti anti zip-bomb. Mai eccezione (logging + skip).

    Returns:
        Lista di dict file estratti (esclusi gli zip nidificati che vengono
        ricorsivamente estratti dal caller).
    """
    if depth > MAX_NESTED_DEPTH:
        print(f"[V2 ZIP] max_depth={MAX_NESTED_DEPTH} raggiunta, skip {zip_path.name}")
        return []

    extracted: List[Dict[str, Any]] = []
    nested_zips: List[Path] = []

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if state["files"] >= MAX_TOTAL_FILES:
                    print(f"[V2 ZIP] limite MAX_TOTAL_FILES={MAX_TOTAL_FILES} raggiunto")
                    break
                if state["bytes"] >= MAX_TOTAL_BYTES:
                    print(f"[V2 ZIP] limite MAX_TOTAL_BYTES={MAX_TOTAL_BYTES} raggiunto")
                    break

                fname = os.path.basename(info.filename)
                if not fname or fname.startswith(".") or fname.startswith("__"):
                    continue

                # Categorize prima di scrivere su disco
                category = _categorize_file(fname)
                if category == "skip":
                    continue

                # Anti path-traversal
                try:
                    target = _safe_extract_path(extract_dir, info.filename)
                except ValueError as e:
                    print(f"[V2 ZIP] {e}, skip")
                    continue

                # Ensure parent dir
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    print(f"[V2 ZIP] mkdir fallito {target.parent}: {e}")
                    continue

                # Scrivi file in streaming (memoria costante)
                try:
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                except (OSError, zipfile.BadZipFile) as e:
                    print(f"[V2 ZIP] estrazione {info.filename} fallita: {e}")
                    continue

                size = info.file_size
                state["files"] += 1
                state["bytes"] += size

                if category == "zip":
                    nested_zips.append(target)
                else:
                    extracted.append({
                        "filename": fname,
                        "path": str(target),
                        "size": size,
                        "category": category,
                    })
    except zipfile.BadZipFile as e:
        # Solo per ZIP root il caller può decidere; per nested logghiamo
        if depth == 0:
            raise
        print(f"[V2 ZIP] ZIP nidificato corrotto {zip_path.name}: {e}")

    # Estrazione ricorsiva nested
    for nested in nested_zips:
        nested_extract_dir = extract_dir / f"{nested.stem}_unzipped"
        try:
            nested_extract_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        nested_files = _extract_single_zip(nested, nested_extract_dir, depth + 1, state)
        extracted.extend(nested_files)
        # Rimuovi il ZIP nested dopo l'estrazione (evita che venga incluso come file)
        try:
            nested.unlink()
        except OSError:
            pass

    return extracted


# ──────────────────────────────────────────────────────────────────────────────
# API pubblica
# ──────────────────────────────────────────────────────────────────────────────

def extract_zip_bytes(
    zip_bytes: bytes,
    session_id: str,
    base_dir: Path = None,
) -> Tuple[List[Dict[str, Any]], Path]:
    """
    Estrae bytes ZIP in directory temporanea isolata per session_id.

    Args:
        zip_bytes: contenuto del file ZIP
        session_id: identificatore validato anti-traversal
        base_dir: opzionale per test

    Returns:
        (files_list, extract_dir)
        files_list: lista dict {filename, path, size, category}
        extract_dir: Path della directory creata (usare per cleanup)

    Raises:
        ValueError: session_id non valido o ZIP root corrotto
    """
    if not _VALID_SESSION_ID_RE.match(session_id or ""):
        raise ValueError(f"session_id non valido: {session_id!r}")

    if not zip_bytes or not isinstance(zip_bytes, (bytes, bytearray)):
        raise ValueError("zip_bytes vuoto o non bytes")

    base = base_dir or EXTRACT_BASE_DIR
    extract_dir = base / session_id
    extract_dir.mkdir(parents=True, exist_ok=True)

    # Salva il ZIP root su disco prima di estrarlo (zipfile lavora meglio su file)
    zip_path = extract_dir / "_root.zip"
    try:
        zip_path.write_bytes(zip_bytes)
    except OSError as e:
        raise ValueError(f"Impossibile scrivere ZIP temporaneo: {e}")

    state = {"files": 0, "bytes": 0}
    try:
        files = _extract_single_zip(zip_path, extract_dir, depth=0, state=state)
    except zipfile.BadZipFile as e:
        # Cleanup parziale e propaga
        try:
            shutil.rmtree(extract_dir, ignore_errors=True)
        except OSError:
            pass
        raise ValueError(f"ZIP corrotto: {e}")
    finally:
        # Rimuovi il file ZIP root (non parte degli "estratti")
        try:
            zip_path.unlink()
        except OSError:
            pass

    print(f"[V2 ZIP] Estratti {len(files)} file ({state['bytes']/1024/1024:.1f} MB) in {extract_dir}")
    return files, extract_dir


def cleanup_extraction(extract_dir: Path) -> int:
    """
    Rimuove directory di estrazione. Mai eccezione.

    Returns:
        Numero file rimossi (approssimato).
    """
    if not extract_dir or not extract_dir.exists():
        return 0
    try:
        count = sum(1 for _ in extract_dir.rglob("*") if _.is_file())
        shutil.rmtree(extract_dir, ignore_errors=True)
        return count
    except OSError as e:
        print(f"[V2 ZIP] Cleanup fallito {extract_dir}: {e}")
        return 0


def extract_summary(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Riepilogo aggregato per logging/SSE."""
    total = len(files)
    by_cat: Dict[str, int] = {}
    total_bytes = 0
    for f in files:
        cat = f.get("category", "other")
        by_cat[cat] = by_cat.get(cat, 0) + 1
        total_bytes += f.get("size", 0)
    return {
        "total_files": total,
        "by_category": by_cat,
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / 1024 / 1024, 1),
    }
