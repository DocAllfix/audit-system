"""
V2 — Section Download Handler (Fase 7).

Helper HTTP-friendly per download di:
- Una sezione parziale specifica: GET /api/v2/report/download/{session_id}/section/{n}
- Il documento finale: GET /api/v2/report/download/{session_id}/final

Caratteristiche:
- Validazione anti path-traversal sul session_id (regex riusata da Fase 6)
- Validazione section_index numerico in [0, 99]
- Lookup robusto: cerca file con prefix `{n:02d}_*.docx` o `{n:04d}_*.docx`
- 404 graceful con messaggio chiaro se file inesistente
- Mai espone path filesystem nei messaggi di errore
- Resolve sicuro: il path finale DEVE essere sotto session_dir (anti-traversal)

API pubblica:
    get_section_path(session_id, section_index) -> Path | None
    get_final_path(session_id, output_dir) -> Path | None
    section_response(session_id, section_index) -> DownloadResponse
    final_response(session_id, output_dir) -> DownloadResponse

Le funzioni `*_response` ritornano una dataclass con tutto il necessario per
costruire una FastAPI Response (status, headers, content, content_type).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from v2.incremental_docx_builder import _section_dir, _validate_session_id


# Mime type DOCX standard
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Pattern accettati per il prefix
_SECTION_FILE_RE = re.compile(r"^(\d{2,4})_[A-Za-z0-9_]+\.docx$")


# ──────────────────────────────────────────────────────────────────────────────
# Output: response dataclass agnostic dal framework HTTP
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DownloadResponse:
    """Esito del download. Costruito agnostic dal framework HTTP."""
    status_code: int
    body: bytes = b""
    content_type: str = "application/json"
    filename: Optional[str] = None
    error: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Validazione section_index
# ──────────────────────────────────────────────────────────────────────────────

def _validate_section_index(n) -> Optional[int]:
    """Valida e converte n in int. None se invalido."""
    try:
        idx = int(n)
    except (TypeError, ValueError):
        return None
    if idx < 0 or idx > 99:
        return None
    return idx


# ──────────────────────────────────────────────────────────────────────────────
# Lookup path sicuro
# ──────────────────────────────────────────────────────────────────────────────

def get_section_path(
    session_id: str,
    section_index: int,
    base_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Risolve il path della sezione N. Ritorna None se non trovato o se il
    path risultante esce dalla session_dir (anti path-traversal).
    """
    try:
        _validate_session_id(session_id)
    except ValueError:
        return None

    idx = _validate_section_index(section_index)
    if idx is None:
        return None

    section_dir = _section_dir(session_id, base_dir)
    if not section_dir.exists():
        return None

    # Cerca pattern {NN}_*.docx
    prefix = f"{idx:02d}_"
    candidates = []
    for path in section_dir.glob("*.docx"):
        m = _SECTION_FILE_RE.match(path.name)
        if not m:
            continue
        try:
            file_idx = int(m.group(1))
        except ValueError:
            continue
        if file_idx == idx:
            candidates.append(path)

    if not candidates:
        return None

    # Containment check: il path deve essere DIRETTAMENTE sotto section_dir
    chosen = candidates[0]
    try:
        # Resolve assoluto e verifica
        resolved = chosen.resolve()
        section_dir_resolved = section_dir.resolve()
        if not str(resolved).startswith(str(section_dir_resolved)):
            return None
    except OSError:
        return None

    return chosen


def get_final_path(
    session_id: str,
    output_dir: Path,
) -> Optional[Path]:
    """
    Risolve il path del file finale prodotto dal merger.
    Il finale ha nome `{session_id}_final.docx` per default.

    Returns:
        Path se file esiste e validato, None altrimenti.
    """
    try:
        _validate_session_id(session_id)
    except ValueError:
        return None

    candidate = output_dir / f"{session_id}_final.docx"
    if not candidate.exists():
        return None

    try:
        resolved = candidate.resolve()
        output_resolved = output_dir.resolve()
        if not str(resolved).startswith(str(output_resolved)):
            return None
    except OSError:
        return None

    return candidate


# ──────────────────────────────────────────────────────────────────────────────
# Response builders
# ──────────────────────────────────────────────────────────────────────────────

def section_response(
    session_id: str,
    section_index,
    base_dir: Optional[Path] = None,
) -> DownloadResponse:
    """Costruisce la response HTTP per il download di una sezione parziale."""

    if not session_id:
        return DownloadResponse(status_code=400, error="missing_session_id")

    # Validazione session_id (riusa quella del builder)
    try:
        _validate_session_id(session_id)
    except ValueError:
        return DownloadResponse(status_code=400, error="invalid_session_id")

    idx = _validate_section_index(section_index)
    if idx is None:
        return DownloadResponse(status_code=400, error="invalid_section_index")

    path = get_section_path(session_id, idx, base_dir)
    if path is None:
        return DownloadResponse(
            status_code=404,
            error=f"section_{idx:02d}_not_found",
            content_type="application/json",
        )

    try:
        body = path.read_bytes()
    except OSError as e:
        return DownloadResponse(
            status_code=500,
            error=f"read_failed: {e}",
            content_type="application/json",
        )

    return DownloadResponse(
        status_code=200,
        body=body,
        content_type=DOCX_MIME,
        filename=path.name,
        headers={
            "Content-Disposition": f'attachment; filename="{path.name}"',
            "Content-Length": str(len(body)),
        },
    )


def final_response(
    session_id: str,
    output_dir: Path,
) -> DownloadResponse:
    """Costruisce la response HTTP per il download del documento finale."""

    if not session_id:
        return DownloadResponse(status_code=400, error="missing_session_id")

    try:
        _validate_session_id(session_id)
    except ValueError:
        return DownloadResponse(status_code=400, error="invalid_session_id")

    path = get_final_path(session_id, output_dir)
    if path is None:
        return DownloadResponse(
            status_code=404,
            error="final_not_found",
            content_type="application/json",
        )

    try:
        body = path.read_bytes()
    except OSError as e:
        return DownloadResponse(
            status_code=500,
            error=f"read_failed: {e}",
            content_type="application/json",
        )

    safe_filename = f"audit_{session_id}.docx"
    return DownloadResponse(
        status_code=200,
        body=body,
        content_type=DOCX_MIME,
        filename=safe_filename,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Content-Length": str(len(body)),
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Listing (utile per UI: "quali sezioni sono pronte?")
# ──────────────────────────────────────────────────────────────────────────────

def list_available_sections(
    session_id: str,
    base_dir: Optional[Path] = None,
) -> list:
    """
    Ritorna lista [{ "section_index": int, "filename": str, "size_bytes": int }]
    delle sezioni attualmente disponibili.

    Mai eccezione; ritorna [] su input invalido.
    """
    try:
        _validate_session_id(session_id)
    except ValueError:
        return []

    section_dir = _section_dir(session_id, base_dir)
    if not section_dir.exists():
        return []

    out = []
    for path in section_dir.glob("*.docx"):
        m = _SECTION_FILE_RE.match(path.name)
        if not m:
            continue
        try:
            idx = int(m.group(1))
            size = path.stat().st_size
        except (ValueError, OSError):
            continue
        out.append({
            "section_index": idx,
            "filename": path.name,
            "size_bytes": size,
        })
    out.sort(key=lambda x: x["section_index"])
    return out
