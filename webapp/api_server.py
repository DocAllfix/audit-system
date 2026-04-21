# ==============================================================================
# AUDIT-OS — FastAPI REST Backend
# ==============================================================================
# Espone tutti i moduli Python (report_generator, checklist_producer, ecc.)
# come API REST per il frontend React.
#
# Avvio:
#   cd webapp
#   uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
#
# Oppure:
#   python api_server.py
# ==============================================================================

from __future__ import annotations

import os
import sys
import json
import traceback
import logging
import base64
from datetime import datetime
from io import BytesIO
from typing import Optional, Dict, List, Any

# ── Percorsi ──────────────────────────────────────────────────────────────────
WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WEBAPP_DIR)

# ── Caricamento .env (rispetta env vars già impostate da systemd) ─────────────
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(WEBAPP_DIR, ".env"), override=False)
except ImportError:
    pass

# ── FastAPI ────────────────────────────────────────────────────────────────────
from fastapi import (
    FastAPI, UploadFile, File, Form, Header,
    HTTPException, Depends, Query, Body
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import asyncio
import concurrent.futures

# ── Moduli applicazione ────────────────────────────────────────────────────────
from config import (
    CHECKLIST_TEMPLATES, TEMPLATES_DIR, SUPPORTED_NORMS,
    GEMINI_MODEL, PROMPTS_CHECKLIST_DIR
)
from modules.auth_manager import (
    authenticate,
    create_persistent_session,
    validate_session_token,
    invalidate_session_token,
    load_users,
)
from modules.db_manager import (
    save_pratica,
    get_pratiche_utente,
    get_all_pratiche_admin,
    save_error_log,
    get_errors_for_admin,
    mark_error_resolved,
    get_error_stats,
    get_statistiche_utente,
    get_statistiche_globali,
)
from modules.checklist_filler import fill_checklist, generate_checklist_filename, detect_standard
from modules.checklist_producer import (
    produce_checklist_json_parallel,
    generate_json_filename,
    recover_incomplete_clauses,
    extract_text_from_word,
)

# log_activity opzionale (non tutti i db_manager la espongono)
try:
    from modules.db_manager import log_activity as _log_activity
except ImportError:
    def _log_activity(*args, **kwargs):
        pass

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("audit-os-api")

# ── GEMINI API KEY ─────────────────────────────────────────────────────────────
def _load_api_key() -> str:
    """Legge GEMINI_API_KEY: variabile ambiente → secrets.toml."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    secrets_path = os.path.join(WEBAPP_DIR, ".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        try:
            with open(secrets_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("GEMINI_API_KEY"):
                        _, _, val = stripped.partition("=")
                        return val.strip().strip('"').strip("'")
        except Exception:
            pass
    return ""

GEMINI_API_KEY = _load_api_key()

# ── Helper: estrazione testo da DOCX o PDF ────────────────────────────────────
def _extract_report_text(file_bytes: bytes, filename: str):
    """
    Estrae testo grezzo da un file DOCX o PDF.
    Ritorna (text: str, error: str|None).
    """
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(BytesIO(file_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p for p in pages if p.strip())
            if not text.strip():
                return None, (
                    "Il PDF non contiene testo estraibile. "
                    "Se è scansionato usa il file Word (.docx) del report."
                )
            return text, None
        except Exception as e:
            return None, f"Errore lettura PDF: {e}"
    else:
        # DOCX / DOC — usa il modulo dedicato
        return extract_text_from_word(file_bytes)



# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AUDIT-OS API",
    version="1.0.0",
    description="REST backend per il frontend React di AUDIT-OS",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "*",  # override in produzione
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helper: mapping campi DB → API ─────────────────────────────────────────────
def _map_pratica(p: Dict) -> Dict:
    """Rinomina i campi DB SQLite nei nomi attesi dal frontend React."""
    return {
        "id": p.get("id"),
        "type": p.get("tipo"),
        "company_name": p.get("azienda"),
        "norm": p.get("norma"),
        "created_date": p.get("data_creazione"),
        "created_by": p.get("user_id"),
        "status": p.get("status", "completed"),
        "processing_time_seconds": p.get("processing_time_seconds"),
        "filename": p.get("file_output_name"),
        "file_size": p.get("file_size"),
        "note": p.get("note"),
    }


def _map_error(e: Dict) -> Dict:
    """Rinomina i campi DB degli errori nei nomi attesi dal frontend."""
    return {
        "id": e.get("id"),
        "created_date": e.get("created_at"),
        "created_by": e.get("user_id"),
        "tab": e.get("tab_source"),
        "error_type": e.get("error_type"),
        "company_name": e.get("azienda"),
        "message": e.get("error_message"),
        "stack_trace": e.get("stack_trace"),
        "auto_recovered": bool(e.get("auto_recovered")),
        "resolved": bool(e.get("resolved")),
        "resolved_by": e.get("resolved_by"),
        "resolved_at": e.get("resolved_at"),
    }

# ── Autenticazione ─────────────────────────────────────────────────────────────
def _get_current_user(authorization: Optional[str] = Header(None)) -> Dict:
    """Dependency: valida Bearer token → restituisce dict utente."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token non fornito")
    token = authorization.removeprefix("Bearer ").strip()
    # validate_session_token restituisce Optional[str] (username), non un dict
    username = validate_session_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Token non valido o scaduto")
    # Carica il dict completo dell'utente da users.json
    users = load_users()
    user_data = users.get(username.lower(), users.get(username, {}))
    return {
        "username": username,
        "role": user_data.get("role", "auditor"),
        "email": "",                                  # users.json non ha campo email
        "display_name": user_data.get("name", username),
        "name": user_data.get("name", username),
    }


def _require_admin(user: Dict = Depends(_get_current_user)) -> Dict:
    """Dependency: richiede ruolo admin."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accesso riservato agli amministratori")
    return user

# ── Modelli Pydantic ───────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class CreatePraticaRequest(BaseModel):
    type: str
    company_name: Optional[str] = ""
    norm: Optional[str] = ""
    status: Optional[str] = "completed"
    processing_time_seconds: Optional[int] = None
    clauses_total: Optional[int] = None
    clauses_complete: Optional[int] = None
    filename: Optional[str] = None


class ResolveErrorRequest(BaseModel):
    resolved_by: Optional[str] = ""
    resolved: Optional[bool] = True
    resolved_date: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "api_key_configured": bool(GEMINI_API_KEY),
        "templates_dir": TEMPLATES_DIR,
        "supported_norms": SUPPORTED_NORMS,
        "gemini_model": GEMINI_MODEL,
    }


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/login")
async def login(body: LoginRequest):
    # authenticate() restituisce (bool, Optional[str]) — NON un dict utente
    success, error_msg = authenticate(body.username, body.password)
    if not success:
        raise HTTPException(status_code=401, detail=error_msg or "Credenziali non valide")
    token = create_persistent_session(body.username)
    # Carica i dati utente da users.json per costruire la risposta
    users = load_users()
    user_data = users.get(body.username.lower(), users.get(body.username, {}))
    return {
        "token": token,
        "user": {
            "username": body.username,
            "email": "",                                       # non presente in users.json
            "role": user_data.get("role", "auditor"),
            "display_name": user_data.get("name", body.username),
        },
    }


@app.get("/api/auth/me")
async def me(user: Dict = Depends(_get_current_user)):
    return {
        "username": user.get("username", ""),
        "email": user.get("email", ""),
        "role": user.get("role", "auditor"),
        "display_name": user.get("display_name", user.get("username", "")),
    }


@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        try:
            invalidate_session_token(token)
        except Exception:
            pass
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# PRATICHE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/pratiche")
async def list_pratiche(
    limit: int = Query(50),
    sort: Optional[str] = Query(None),
    user: Dict = Depends(_get_current_user),
):
    """Lista pratiche.
    - Admin: vede tutte le pratiche del sistema.
    - Auditor: vede solo le sue.
    """
    if user.get("role") == "admin":
        pratiche = get_all_pratiche_admin()
    else:
        pratiche = get_pratiche_utente(user["username"], limit=limit)

    # Applica limite
    if limit and limit > 0:
        pratiche = pratiche[:limit]

    # Ordina per data (i DB già ordinano DESC, ma rispetta richiesta frontend)
    if sort and sort.lstrip("-") in ("created_date", "data_creazione"):
        reverse = sort.startswith("-")
        pratiche = sorted(
            pratiche,
            key=lambda p: p.get("data_creazione") or "",
            reverse=reverse,
        )

    return [_map_pratica(p) for p in pratiche]


@app.post("/api/pratiche")
async def create_pratica(
    body: CreatePraticaRequest,
    user: Dict = Depends(_get_current_user),
):
    """Crea manualmente una pratica (usato dal frontend per i flussi mock/fallback)."""
    try:
        save_pratica(
            user_id=user["username"],
            tipo=body.type,
            file_output_path="",
            file_output_name=body.filename or "",
            azienda=body.company_name or "",
            norma=body.norm or "",
            file_size=0,
            processing_time=body.processing_time_seconds or 0,
        )
        return {"ok": True}
    except Exception as e:
        logger.error(f"Errore creazione pratica: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — LOG ERRORI
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/errors")
async def list_errors(
    resolved: Optional[str] = Query(None),
    limit: int = Query(200),
    user: Dict = Depends(_get_current_user),   # tutti possono leggere per il badge
):
    """
    Lista errori. Query param `resolved=false` per soli non risolti (badge sidebar).
    Solo admin vede la lista completa; per gli auditor restituisce solo il count.
    """
    errors = get_errors_for_admin(limit=limit)

    # Filtra per stato se richiesto
    if resolved == "false":
        errors = [e for e in errors if not e.get("resolved")]
    elif resolved == "true":
        errors = [e for e in errors if e.get("resolved")]

    # Gli auditor ottengono solo il count (non i dettagli)
    if user.get("role") != "admin":
        return {"count": len(errors)}

    return [_map_error(e) for e in errors]


@app.patch("/api/admin/errors/{error_id}")
async def resolve_error(
    error_id: int,
    body: ResolveErrorRequest,
    user: Dict = Depends(_require_admin),
):
    """Segna un errore come risolto."""
    try:
        resolved_by = body.resolved_by or user.get("email", user.get("username", ""))
        mark_error_resolved(error_id, resolved_by)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Errore resoluzione error_id={error_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — STATISTICHE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/stats")
async def admin_stats(user: Dict = Depends(_require_admin)):
    stats = get_statistiche_globali()
    return {
        "total_practices": stats.get("totale", 0),
        "avg_time_seconds": stats.get("tempo_medio_secondi", 0),
        "success_rate": stats.get("tasso_successo", 0),
        "today_count": stats.get("oggi", 0),
        "per_user": stats.get("per_utente", {}),
    }


@app.get("/api/admin/error-stats")
async def admin_error_stats(user: Dict = Depends(_require_admin)):
    return get_error_stats()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — GENERA REPORT WORD da ZIP  (SSE streaming)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/report/process")
async def process_report(
    file: UploadFile = File(...),
    user: Dict = Depends(_get_current_user),
):
    """
    Riceve file ZIP, processa con Gemini, streamma il progresso reale via SSE.

    Stream di eventi SSE:
      data: {"pct": 12, "msg": "Estrazione documenti..."}
      data: {"pct": 45, "msg": "Analisi AI batch 3/8..."}
      data: {"done": true, "filename": "...", "word_base64": "...", "stats": {...}, "company_name": "..."}
      data: {"error": "messaggio errore"}
    """
    from modules.report_generator import process_zip_and_generate_report

    api_key = GEMINI_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Chiave API Gemini non configurata nel server")

    file_bytes = await file.read()

    if len(file_bytes) > 1 * 1024 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File troppo grande (limite 1 GB)")

    original_filename = file.filename or "upload.zip"
    username = user["username"]
    logger.info(f"[Tab1] {username} → {original_filename} ({len(file_bytes)/1024/1024:.1f} MB)")

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress_cb(pct_raw, msg: str):
        """Bridge sincrono → async queue. pct_raw può essere 0-1 o 0-100."""
        pct = int(pct_raw * 100) if pct_raw <= 1.0 else int(pct_raw)
        asyncio.run_coroutine_threadsafe(
            queue.put({"pct": pct, "msg": msg}), loop
        )

    async def event_stream():
        def _run():
            return process_zip_and_generate_report(
                input_source=file_bytes,
                api_key=api_key,
                progress_callback=progress_cb,
                status_callback=None,
                input_type="zip",
                filename=original_filename,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = loop.run_in_executor(pool, _run)

            # Drena la queue mentre il thread lavora
            while not future.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.3)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"   # evita timeout nginx/proxy

            # Svuota eventi residui
            while not queue.empty():
                event = queue.get_nowait()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # Risultato
            try:
                word_bytes, stats, filename = future.result()
                company_name = stats.get("company_name", "")

                try:
                    save_pratica(
                        user_id=username, tipo="report",
                        file_output_path="", file_output_name=filename,
                        azienda=company_name, norma="",
                        file_size=len(word_bytes),
                        processing_time=int(stats.get("total_time", 0)),
                    )
                    _log_activity(username, "report_generated", f"Azienda: {company_name}")
                except Exception:
                    pass

                logger.info(f"[Tab1] OK → {filename} ({len(word_bytes)//1024} KB)")
                done_event = {
                    "done": True,
                    "filename": filename,
                    "word_base64": base64.b64encode(word_bytes).decode(),
                    "stats": stats,
                    "company_name": company_name,
                }
                yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"

            except Exception as e:
                tb = traceback.format_exc()
                logger.error(f"[Tab1] ERRORE: {e}\n{tb}")
                try:
                    save_error_log(
                        user_id=username, error_type="generation",
                        error_message=str(e)[:500], tab_source="tab1",
                        azienda="", stack_trace=tb[:2000],
                    )
                except Exception:
                    pass
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PRODUCI CHECKLIST JSON da Report Word  (SSE streaming)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/checklist/produce")
async def produce_checklist(
    file: UploadFile = File(...),
    norm: str = Form(...),
    company_name: Optional[str] = Form(""),
    user: Dict = Depends(_get_current_user),
):
    """
    Riceve Report Word + norma, genera JSON clausole, streamma il progresso via SSE.

    Stream di eventi SSE:
      data: {"pct": 15, "msg": "Estrazione testo dal Report..."}
      data: {"pct": 60, "msg": "✓ Gruppo 3/6 completato (8 clausole)"}
      data: {"done": true, "json": {...}, "filename": "..."}
      data: {"error": "messaggio errore"}
    """
    api_key = GEMINI_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Chiave API Gemini non configurata nel server")

    if norm not in SUPPORTED_NORMS:
        logger.warning(f"[Tab2] Norma non standard: '{norm}'")

    report_bytes = await file.read()
    username = user["username"]
    logger.info(f"[Tab2] {username} → norma={norm} ({len(report_bytes)//1024} KB)")

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress_cb(pct_raw, msg: str):
        """produce_checklist_json_parallel chiama con int 0-100."""
        pct = int(pct_raw) if pct_raw > 1 else int(pct_raw * 100)
        asyncio.run_coroutine_threadsafe(
            queue.put({"pct": pct, "msg": msg}), loop
        )

    async def event_stream():
        def _run():
            return produce_checklist_json_parallel(
                report_input=report_bytes,
                norma=norm,
                api_key=api_key,
                progress_callback=progress_cb,
                company_name_override=company_name or "",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = loop.run_in_executor(pool, _run)

            while not future.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.3)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

            while not queue.empty():
                event = queue.get_nowait()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            try:
                json_result, error = future.result()

                if error:
                    yield f"data: {json.dumps({'error': str(error)})}\n\n"
                    return

                azienda = json_result.get("azienda", "")
                json_filename = generate_json_filename(json_result)
                json_bytes_size = len(json.dumps(json_result, ensure_ascii=False).encode())

                try:
                    save_pratica(
                        user_id=username, tipo="checklist_json",
                        file_output_path="", file_output_name=json_filename,
                        azienda=azienda, norma=norm, file_size=json_bytes_size,
                    )
                    _log_activity(username, "json_generated", f"Norma: {norm}, Azienda: {azienda}")
                except Exception:
                    pass

                logger.info(f"[Tab2] OK → {json_filename}")
                done_event = {"done": True, "json": json_result, "filename": json_filename}
                yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"

            except Exception as e:
                tb = traceback.format_exc()
                logger.error(f"[Tab2] ERRORE: {e}\n{tb}")
                try:
                    save_error_log(
                        user_id=username, error_type="api",
                        error_message=str(e)[:500], tab_source="tab2",
                        azienda=company_name or "", stack_trace=tb[:2000],
                    )
                except Exception:
                    pass
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — RECOVERY CLAUSOLE INCOMPLETE
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/checklist/recover")
async def recover_clauses(
    file: UploadFile = File(...),
    json_data: str = Form(...),          # JSON serializzato come stringa
    incomplete_keys: str = Form(...),    # lista JSON serializzata, es. ["4.1","4.2"]
    norm: str = Form(...),
    user: Dict = Depends(_get_current_user),
):
    """
    Recupera clausole incomplete rianalizzando il report Word originale.
    Risponde come SSE stream con eventi di progresso e infine:
      data: {"done": true, "json": {...}, "still_missing": [...]}
    """
    api_key = GEMINI_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Chiave API Gemini non configurata")

    try:
        current_json = json.loads(json_data)
        keys_to_recover: List[str] = json.loads(incomplete_keys)
    except Exception:
        raise HTTPException(status_code=422, detail="Formato json_data o incomplete_keys non valido")

    if not keys_to_recover:
        async def _immediate():
            yield f"data: {json.dumps({'done': True, 'json': current_json, 'still_missing': []})}\n\n"
        return StreamingResponse(_immediate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    report_bytes = await file.read()
    username = user["username"]
    logger.info(f"[Tab2/recover] {username} → {len(keys_to_recover)} clausole, norma={norm}")

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress_cb(pct_raw, msg: str):
        pct = int(pct_raw) if pct_raw > 1 else int(pct_raw * 100)
        asyncio.run_coroutine_threadsafe(queue.put({"pct": pct, "msg": msg}), loop)

    async def event_stream():
        # Estrai testo (veloce, sincrono)
        yield f"data: {json.dumps({'pct': 5, 'msg': 'Estrazione testo dal report...'})}\n\n"
        report_text, extract_error = _extract_report_text(report_bytes, file.filename or "report.docx")
        if extract_error or not report_text:
            yield f"data: {json.dumps({'error': f'Impossibile estrarre testo: {extract_error}'})}\n\n"
            return

        yield f"data: {json.dumps({'pct': 10, 'msg': f'Avvio recupero {len(keys_to_recover)} clausole...'})}\n\n"

        def _run():
            return recover_incomplete_clauses(
                json_data=current_json,
                incomplete_keys=keys_to_recover,
                report_text=report_text,
                norma=norm,
                api_key=api_key,
                progress_callback=progress_cb,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = loop.run_in_executor(pool, _run)

            while not future.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.3)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

            while not queue.empty():
                event = queue.get_nowait()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            try:
                updated_json, still_missing = future.result()
                logger.info(
                    f"[Tab2/recover] OK — recuperate {len(keys_to_recover) - len(still_missing)}, "
                    f"ancora mancanti {len(still_missing)}"
                )
                done_event = {"done": True, "json": updated_json, "still_missing": still_missing}
                yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
            except Exception as e:
                tb = traceback.format_exc()
                logger.error(f"[Tab2/recover] ERRORE: {e}\n{tb}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — COMPILA CHECKLIST Word/Excel da JSON
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/checklist/compile")
async def compile_checklist(
    body: Dict = Body(...),
    user: Dict = Depends(_get_current_user),
):
    """
    Riceve il JSON checklist, riempie il template Word/Excel, restituisce il file.

    Request body: { "norma": ..., "azienda": ..., "clausole": { ... } }

    Response JSON:
    {
      "filename": "Checklist_ISO9001_Azienda_2025-01-01.docx",
      "file_base64": "...",      // base64 del file .docx o .xlsx
      "mime_type": "application/...",
      "norm": "ISO 9001"
    }
    """
    try:
        norma, template_path = detect_standard(body)

        if not template_path or not os.path.exists(template_path):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Template non trovato per norma '{norma}'. "
                    f"Aggiungi il file in: {TEMPLATES_DIR}"
                ),
            )

        logger.info(f"[Tab3] {user['username']} → norma={norma}  template={os.path.basename(template_path)}")

        word_bytes, error = fill_checklist(body, template_path)

        if error:
            raise HTTPException(status_code=500, detail=str(error))

        filename = generate_checklist_filename(body, template_path)
        azienda = body.get("azienda", "")

        if filename.endswith(".xlsx"):
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        save_pratica(
            user_id=user["username"],
            tipo="checklist_word",
            file_output_path="",
            file_output_name=filename,
            azienda=azienda,
            norma=norma or "",
            file_size=len(word_bytes),
        )
        _log_activity(
            user["username"], "word_compiled",
            f"Norma: {norma}, Azienda: {azienda}",
        )

        logger.info(f"[Tab3] OK → {filename}  ({len(word_bytes)//1024} KB)")

        return {
            "filename": filename,
            "file_base64": base64.b64encode(word_bytes).decode(),
            "mime_type": mime,
            "norm": norma,
        }

    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[Tab3] ERRORE: {e}\n{tb}")
        try:
            azienda = body.get("azienda", "") if isinstance(body, dict) else ""
            save_error_log(
                user_id=user["username"],
                error_type="generation",
                error_message=str(e)[:500],
                tab_source="tab3",
                azienda=azienda,
                stack_trace=tb[:2000],
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  AUDIT-OS API SERVER")
    print(f"  Gemini API Key: {'✓ configurata' if GEMINI_API_KEY else '✗ MANCANTE'}")
    print(f"  Templates dir:  {TEMPLATES_DIR}")
    print(f"  Norme:          {', '.join(SUPPORTED_NORMS)}")
    print("=" * 60)
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
