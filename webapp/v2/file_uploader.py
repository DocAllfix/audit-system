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
import shutil
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _safe_ascii(s: str) -> str:
    """
    Strip caratteri non-ASCII per uso in:
    - display_name di Gemini Files API (header HTTP RFC 7230 vuole ASCII)
    - print() su Windows console cp1252 (in produzione un filename con
      accenti puo' bloccare un thread durante il print, generando un hang
      di 240s in attesa del timeout future)

    Esempio: "Conformità.pdf" -> "Conformita.pdf".
    NON cambia il nome del file su disco ne' la chiave di dedup (SHA256 sul
    contenuto). Solo la rappresentazione testuale negli header e nei log.
    """
    if not isinstance(s, str):
        return str(s)
    nfkd = unicodedata.normalize("NFKD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii")


def _path_is_ascii_safe(path: str) -> bool:
    """True se il path completo e' encodable in ASCII strict."""
    try:
        path.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _copy_to_ascii_temp(src_path: str) -> Tuple[str, Optional[str]]:
    """
    Se ``src_path`` contiene caratteri non-ASCII (es. accenti italiani),
    crea una copia in temp/ con nome solo-ASCII e ritorna (temp_path, temp_path).
    Altrimenti ritorna (src_path, None) senza copiare.

    Il caller usa il primo elemento per l'upload SDK Gemini, e il secondo
    (se non None) per il cleanup nel finally.

    Motivazione: il SDK google-genai legge il path internamente e in alcuni
    code path (es. costruzione header HTTP per l'upload resumable) lo encoda
    in ASCII strict, sollevando UnicodeEncodeError. Il fix `display_name` da
    solo non basta: serve un path effettivamente ASCII.

    Nome temp: hash MD5 del path originale (16 char) + estensione, cosi':
    - Deterministico (idempotente per retry sullo stesso file)
    - Univoco (no collisioni inter-file in concorrenza thread)
    - ASCII per costruzione
    """
    if _path_is_ascii_safe(src_path):
        return src_path, None

    ext = os.path.splitext(src_path)[1].lower()
    digest = hashlib.md5(src_path.encode("utf-8")).hexdigest()[:16]
    tmp_dir = tempfile.gettempdir()
    safe_path = os.path.join(tmp_dir, f"v2upload_{digest}{ext}")

    try:
        shutil.copyfile(src_path, safe_path)
    except OSError as e:
        # Se la copia fallisce per qualunque motivo, ritorno comunque il
        # safe_path: il try/except dell'upload poi ritornera' UploadResult
        # success=False, e il file finira' in DOCUMENTI NON ELABORATI.
        print(f"[V2 UPLOADER] copy_to_ascii_temp fallito per {_safe_ascii(src_path)}: {e}")
        return safe_path, safe_path

    return safe_path, safe_path


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
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
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
        print(f"[V2 UPLOADER] WARN: file grande {size/1024/1024:.1f}MB - {_safe_ascii(path)}")

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

    display_name_safe = _safe_ascii(os.path.basename(path))[:128]
    log_name = _safe_ascii(os.path.basename(path))

    # FIX 9: il SDK google-genai esegue ASCII-strict encoding del path
    # internamente (negli header HTTP dell'upload resumable). Passare un path
    # con accenti causa UnicodeEncodeError + hang del thread del worker.
    # Soluzione: copia ASCII-safe in temp/, upload da li', cleanup garantito.
    upload_path, cleanup_temp = _copy_to_ascii_temp(path)

    last_err: Optional[Exception] = None
    try:
        for attempt in range(MAX_UPLOAD_RETRIES):
            try:
                from google.genai import types as gtypes
                config = gtypes.UploadFileConfig(
                    mime_type=mime,
                    display_name=display_name_safe,
                )
                uploaded = client.files.upload(file=upload_path, config=config)
                file_uri = getattr(uploaded, "uri", None)
                file_name = getattr(uploaded, "name", None)
                if not file_uri or not file_name:
                    last_err = RuntimeError(f"upload returned no uri/name: {uploaded!r}")
                    continue

                entry = UploadedFile(
                    sha256=sha,
                    file_uri=file_uri,
                    file_name=file_name,
                    mime_type=mime,
                    size_bytes=size,
                    source_path=path,  # path ORIGINALE (no temp) per traceability
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
                err_str = _safe_ascii(str(e)).lower()

                if "401" in err_str or "403" in err_str or "permission" in err_str:
                    return UploadResult(success=False, error=f"auth_failed: {_safe_ascii(str(e))}")
                if "413" in err_str or "too large" in err_str:
                    return UploadResult(success=False, error=f"too_large: {_safe_ascii(str(e))}")

                if attempt < MAX_UPLOAD_RETRIES - 1:
                    wait = RETRY_BASE_DELAY * (2 ** attempt)
                    print(
                        f"[V2 UPLOADER] Upload fallito ({attempt+1}/{MAX_UPLOAD_RETRIES}) "
                        f"per {log_name}: {_safe_ascii(str(e))} - retry tra {wait}s"
                    )
                    time.sleep(wait)

        return UploadResult(success=False, error=f"all_retries_failed: {_safe_ascii(str(last_err))}")
    finally:
        # Cleanup garantito della copia ASCII temp, anche su exception
        if cleanup_temp and os.path.isfile(cleanup_temp):
            try:
                os.unlink(cleanup_temp)
            except OSError:
                pass


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

CLEANUP_PARALLEL_WORKERS = int(os.environ.get("V2_OCR_DELETE_PARALLEL", "5"))


def cleanup_session(client, manifest: UploadManifest) -> int:
    """
    Cancella tutti i file Gemini referenziati dal manifest e svuota il manifest.
    Le DELETE sono indipendenti, idempotenti (404 se gia' cancellato), e
    parallelizzate con ThreadPoolExecutor per ridurre il tempo di cleanup.
    Saving osservato: ~25s -> ~5s su 19 file.

    Returns:
        Numero di file cancellati con successo.
    """
    entries = manifest.all_entries()
    if not entries:
        return 0

    counter_lock = threading.Lock()
    count_holder = [0]

    def _delete_one(entry: "UploadedFile") -> None:
        try:
            client.files.delete(name=entry.file_name)
            with counter_lock:
                count_holder[0] += 1
        except Exception as e:
            # 404 / file gia' cancellato / scaduto: best-effort, niente alarm
            print(f"[V2 UPLOADER] Delete fallito per {entry.file_name}: {_safe_ascii(str(e))}")
        finally:
            # Rimuovo dal manifest comunque (best effort)
            manifest.remove(entry.sha256)

    workers = max(1, min(CLEANUP_PARALLEL_WORKERS, len(entries)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_delete_one, e) for e in entries]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass  # gia' loggato dentro _delete_one

    return count_holder[0]


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
