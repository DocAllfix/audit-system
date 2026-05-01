"""
V2 — File Uploader (Fase 4) — wrapper per Gemini Files API.

Caratteristiche:
- Upload con retry esponenziale (3 tentativi)
- Manifest persistente per session_id su disco (recovery post-crash)
- Dedup via SHA-256: se file con stesso content è già stato uploaded (e URI
  è ancora valido), riuso senza re-upload
- Concorrenza limitata: max 5 upload paralleli
- Atomic write del manifest (.tmp + rename)
- Cleanup esplicito a fine sessione

API pubblica:
    UploadManifest(session_id) — manifest CRUD
    upload_file(client, path, manifest, mime_type=None) -> Optional[str] (file_uri)
    upload_files_parallel(client, paths, manifest) -> Dict[path, file_uri]
    cleanup_session(client, manifest) -> int (count)
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

# Path base manifest (sotto temp/ del progetto)
_WEBAPP_DIR = Path(__file__).resolve().parent.parent
MANIFEST_BASE_DIR = _WEBAPP_DIR.parent / "temp" / "ocr_manifest"

# Hard limit dimensione file (Gemini Files API: 2 GB)
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

# Soglia critica per warning (file molto grande)
WARN_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB

# Retry policy
MAX_UPLOAD_RETRIES = 3
RETRY_BASE_DELAY = 2.0

# Concorrenza max upload paralleli
MAX_PARALLEL_UPLOADS = 5

# MIME guessing
MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class UploadedFile:
    """Voce nel manifest: 1 riga per file uploaded sulla Files API."""
    sha256: str
    file_uri: str
    file_name: str        # Nome interno Gemini (es. "files/abc123")
    mime_type: str
    size_bytes: int
    source_path: str
    created_at: float = field(default_factory=time.time)


# ──────────────────────────────────────────────────────────────────────────────
# Manifest CRUD (atomic + thread-safe)
# ──────────────────────────────────────────────────────────────────────────────

class UploadManifest:
    """
    Manifest persistente per una session_id. Mappa sha256 → UploadedFile.

    Thread-safe per writes; reads lockless dopo snapshot.
    Persistence: write atomic via .tmp + os.replace().
    """

    def __init__(self, session_id: str, base_dir: Optional[Path] = None):
        self.session_id = session_id
        self.base_dir = base_dir or MANIFEST_BASE_DIR
        self.path = self.base_dir / f"{session_id}.json"
        self._lock = threading.Lock()
        self._entries: Dict[str, UploadedFile] = {}
        self._load()

    def _load(self) -> None:
        """Carica manifest esistente da disco se presente."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for sha, entry_dict in data.get("entries", {}).items():
                self._entries[sha] = UploadedFile(**entry_dict)
        except Exception as e:
            print(f"[V2 UPLOADER] Manifest load fallito ({self.path}): {e} — riparto vuoto")
            self._entries = {}

    def _persist_unlocked(self) -> None:
        """Scrittura atomica: dump in .tmp poi rename. Caller deve avere il lock."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        payload = {
            "session_id": self.session_id,
            "version": 1,
            "entries": {sha: asdict(uf) for sha, uf in self._entries.items()},
        }
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic on POSIX e Windows

    def get(self, sha256: str) -> Optional[UploadedFile]:
        """Lookup veloce; lockless (snapshot in tempo costante)."""
        return self._entries.get(sha256)

    def add(self, entry: UploadedFile) -> None:
        with self._lock:
            self._entries[entry.sha256] = entry
            self._persist_unlocked()

    def remove(self, sha256: str) -> Optional[UploadedFile]:
        with self._lock:
            entry = self._entries.pop(sha256, None)
            if entry is not None:
                self._persist_unlocked()
            return entry

    def all_entries(self) -> List[UploadedFile]:
        with self._lock:
            return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


# ──────────────────────────────────────────────────────────────────────────────
# Hashing & MIME helpers
# ──────────────────────────────────────────────────────────────────────────────

def compute_file_sha256(path: str, chunk_size: int = 65536) -> str:
    """SHA-256 streaming del file. Usato per dedup nel manifest."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def guess_mime_type(path: str) -> str:
    """Best-effort MIME type detection da estensione."""
    ext = os.path.splitext(path)[1].lower()
    return MIME_BY_EXT.get(ext, "application/octet-stream")


# ──────────────────────────────────────────────────────────────────────────────
# Validazione URI esistente su Gemini
# ──────────────────────────────────────────────────────────────────────────────

def _verify_uri_still_valid(client, file_name: str) -> bool:
    """
    Chiama client.files.get(name=...) per verificare che l'URI sia ancora vivo.
    Gemini purga i file dopo 48h: il manifest può contenere voci stale.

    Returns:
        True se il file è ancora disponibile, False altrimenti.
    """
    if client is None or not file_name:
        return False
    try:
        info = client.files.get(name=file_name)
        # Alcune SDK ritornano oggetto con state == "ACTIVE", altri con presence
        state = getattr(info, "state", None)
        if state is not None:
            return str(state).upper() in ("ACTIVE", "FILESTATE_ACTIVE", "PROCESSED")
        # Se non c'è stato esposto ma get non ha sollevato → presumibilmente attivo
        return True
    except Exception as e:
        # 404 / not found / qualsiasi errore → considera invalido
        msg = str(e).lower()
        if "not found" in msg or "404" in msg:
            return False
        # Errori di rete: in dubbio, considera valido per non sprecare upload
        # (verrà comunque catturato dalla generate_content successiva)
        print(f"[V2 UPLOADER] verify_uri inconcludente per {file_name}: {e}")
        return True


# ──────────────────────────────────────────────────────────────────────────────
# Upload singolo con retry
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class UploadResult:
    """Esito di upload_file(): success, file_uri, file_name, error, used_cached."""
    success: bool
    file_uri: Optional[str] = None
    file_name: Optional[str] = None
    error: Optional[str] = None
    used_cached: bool = False  # True se riusato da manifest, no upload effettivo


def upload_file(
    client,
    path: str,
    manifest: UploadManifest,
    mime_type: Optional[str] = None,
) -> UploadResult:
    """
    Carica un file su Gemini Files API con dedup via manifest.

    Args:
        client: genai.Client (deve avere `.files.upload`)
        path: percorso file locale
        manifest: UploadManifest della sessione corrente
        mime_type: MIME (auto-detect se None)

    Returns:
        UploadResult con success=True, file_uri, file_name in caso di OK.
        success=False + error se tutti i tentativi falliscono.
    """
    if not os.path.isfile(path):
        return UploadResult(success=False, error=f"file_not_found: {path}")

    try:
        size = os.path.getsize(path)
    except OSError as e:
        return UploadResult(success=False, error=f"stat_failed: {e}")

    if size == 0:
        return UploadResult(success=False, error="empty_file")

    if size > MAX_UPLOAD_BYTES:
        return UploadResult(
            success=False,
            error=f"file_too_large: {size} > {MAX_UPLOAD_BYTES}",
        )

    if size > WARN_UPLOAD_BYTES:
        print(f"[V2 UPLOADER] WARN: file grande {size/1024/1024:.1f}MB → {path}")

    # Dedup: se già nel manifest e URI ancora valido, riuso
    sha = compute_file_sha256(path)
    cached = manifest.get(sha)
    if cached is not None:
        if _verify_uri_still_valid(client, cached.file_name):
            return UploadResult(
                success=True,
                file_uri=cached.file_uri,
                file_name=cached.file_name,
                used_cached=True,
            )
        # URI scaduto: rimuovo dal manifest e procedo all'upload
        manifest.remove(sha)

    mime = mime_type or guess_mime_type(path)

    # Upload con retry
    last_err: Optional[Exception] = None
    for attempt in range(MAX_UPLOAD_RETRIES):
        try:
            from google.genai import types as gtypes
            config = gtypes.UploadFileConfig(
                mime_type=mime,
                display_name=os.path.basename(path)[:128],
            )
            uploaded = client.files.upload(file=path, config=config)
            file_uri = getattr(uploaded, "uri", None)
            file_name = getattr(uploaded, "name", None)
            if not file_uri or not file_name:
                last_err = RuntimeError(f"upload returned no uri/name: {uploaded!r}")
                continue

            # Salva nel manifest
            entry = UploadedFile(
                sha256=sha,
                file_uri=file_uri,
                file_name=file_name,
                mime_type=mime,
                size_bytes=size,
                source_path=path,
            )
            manifest.add(entry)

            return UploadResult(
                success=True,
                file_uri=file_uri,
                file_name=file_name,
                used_cached=False,
            )
        except Exception as e:
            last_err = e
            err_str = str(e).lower()

            # Errori non-retryable: fail subito
            if "401" in err_str or "403" in err_str or "permission" in err_str:
                return UploadResult(success=False, error=f"auth_failed: {e}")
            if "413" in err_str or "too large" in err_str:
                return UploadResult(success=False, error=f"too_large: {e}")

            if attempt < MAX_UPLOAD_RETRIES - 1:
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                print(
                    f"[V2 UPLOADER] Upload fallito ({attempt+1}/{MAX_UPLOAD_RETRIES}) "
                    f"per {os.path.basename(path)}: {e} — retry tra {wait}s"
                )
                time.sleep(wait)

    return UploadResult(success=False, error=f"all_retries_failed: {last_err}")


# ──────────────────────────────────────────────────────────────────────────────
# Upload parallelo
# ──────────────────────────────────────────────────────────────────────────────

def upload_files_parallel(
    client,
    paths: List[str],
    manifest: UploadManifest,
    max_workers: int = MAX_PARALLEL_UPLOADS,
) -> Dict[str, UploadResult]:
    """
    Upload concorrente di N file. Mantiene ordine via mapping path→result.

    Returns:
        Dict {path: UploadResult}, una entry per ogni path richiesto.
    """
    if not paths:
        return {}

    results: Dict[str, UploadResult] = {}
    workers = max(1, min(max_workers, len(paths)))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_path = {
            executor.submit(upload_file, client, p, manifest): p
            for p in paths
        }
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                results[path] = future.result()
            except Exception as e:
                results[path] = UploadResult(success=False, error=f"executor_error: {e}")

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────

def cleanup_session(client, manifest: UploadManifest) -> int:
    """
    Cancella tutti i file Gemini referenziati dal manifest e svuota il manifest.

    Returns:
        Numero di file cancellati con successo.
    """
    count = 0
    for entry in manifest.all_entries():
        try:
            client.files.delete(name=entry.file_name)
            count += 1
        except Exception as e:
            print(f"[V2 UPLOADER] Delete fallito per {entry.file_name}: {e}")
        # Rimuovo dal manifest comunque (best effort)
        manifest.remove(entry.sha256)
    return count


# ──────────────────────────────────────────────────────────────────────────────
# Status reporting
# ──────────────────────────────────────────────────────────────────────────────

def manifest_summary(manifest: UploadManifest) -> dict:
    entries = manifest.all_entries()
    total_bytes = sum(e.size_bytes for e in entries)
    return {
        "session_id": manifest.session_id,
        "files_count": len(entries),
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / 1024 / 1024, 2),
        "manifest_path": str(manifest.path),
    }
