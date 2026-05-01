# ==============================================================================
# CONFIGURAZIONE AUDIT-OS
# ==============================================================================

import os

# Percorsi base
WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(WEBAPP_DIR)

# Directory di lavoro
TEMP_DIR = os.path.join(PROJECT_ROOT, "temp")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
INPUT_DIR = os.path.join(PROJECT_ROOT, "input")
EXECUTION_DIR = os.path.join(PROJECT_ROOT, "execution")
DIRECTIVES_DIR = os.path.join(PROJECT_ROOT, "directives")
TEMPLATES_DIR = os.path.join(WEBAPP_DIR, "templates")

# File istruzioni (prompt ottimizzato per API)
API_PROMPT_PATH = os.path.join(WEBAPP_DIR, "prompts", "api_prompt.md")

# Configurazione Gemini API
GEMINI_MODEL = "gemini-2.5-flash"
BATCH_SIZE = 8  # Tuning conservativo (Middle Ground)
MAX_BATCH_CHARS = 40000       # Target ~40k chars per batch (micro-batching)
MAX_RETRIES = 1  # Fail fast per errori strutturali
PARALLEL_BATCHES = True  # Abilita esecuzione parallela batch
MAX_API_WORKERS = 7            # Allineato al semaforo gemini_structured_slot (vedi gemini_throttle.py)

# Vincoli qualità
MIN_WORDS_PER_PARAGRAPH = 50   # Ridotto per accettare cert. semplici/fatture sintetiche
MAX_WORDS_PER_PARAGRAPH = 800

# Percorsi OCR (opzionali - se non installati, OCR sarà disabilitato)
TESSERACT_PATH = os.environ.get("TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
POPPLER_PATH = os.environ.get("POPPLER_PATH", r"C:\Program Files\poppler\bin")
OCR_LANGUAGES = "ita+eng"  # Lingue per OCR Tesseract
MAX_OCR_WORKERS = 5  # Allineato al semaforo gemini_ocr_slot (vedi gemini_throttle.py)

# Mappatura template checklist per norma (nomi file reali in templates/)
CHECKLIST_TEMPLATES = {
    "ISO 9001": "Template9001.docx",
    "ISO 9001:2015": "Template9001.docx",
    "ISO 14001": "TEMPLATE14001.docx",
    "ISO 14001:2015": "TEMPLATE14001.docx",
    "ISO 45001": "TEMPLATE450001.docx",
    "ISO 45001:2018": "TEMPLATE450001.docx",
    "ISO 14064": "TEMPLATECHECKLIST14064_CORRETTO.docx",
    "ISO 14064-1": "TEMPLATECHECKLIST14064_CORRETTO.docx",
    "ISO 14064-1:2018": "TEMPLATECHECKLIST14064_CORRETTO.docx",
    "ESG": "TEMPLATEeasi.docx",
    "EASI": "TEMPLATEeasi.docx",
    "Modello EASI ESG": "TEMPLATEeasi.docx",
    "PAS 24000": "CHECKTEMPLATEPAS24000_CORRETTO.docx",
    "PAS24000": "CHECKTEMPLATEPAS24000_CORRETTO.docx",
    # Nuovi template aggiunti
    "ISO 27001": "TEMPLATE27001def.xlsx",
    "ISO 27001:2022": "TEMPLATE27001def.xlsx",
    "ISO/IEC 27001": "TEMPLATE27001def.xlsx",
    "ISO/IEC 27001:2022": "TEMPLATE27001def.xlsx",
    "ISO 37001": "TEMPLATE37001.docx",
    "ISO 37001:2016": "TEMPLATE37001.docx",
    "ISO 39001": "TEMPLATE39001.docx",
    "ISO 39001:2012": "TEMPLATE39001.docx",
    # ISO 50001 con varianti (ESQ come default, CERTIS selezionabile)
    "ISO 50001": "TEMPLATE50001ESQ.docx",
    "ISO 50001:2018": "TEMPLATE50001ESQ.docx",
    "ISO 50001 ESQ": "TEMPLATE50001ESQ.docx",
    "ISO 50001 CERTIS": "TEMPLATE50001CERTIS.docx",
}

# Mappatura prompt per generazione JSON checklist (Tab 2)
CHECKLIST_PROMPTS = {
    "ISO 9001": "ISO_9001_webapp.md",
    "ISO 14001": "ISO_14001_webapp.md",
    "ISO 45001": "ISO_45001_webapp.md",
    "ISO 14064": "ISO_14064_webapp.md",
    "ESG": "ESG_webapp.md",
    "PAS 24000": "PAS24000_webapp.md",
    "ISO 27001": "ISO_27001_webapp.md",
    "ISO 37001": "ISO_37001_webapp.md",
    "ISO 39001": "ISO_39001_webapp.md",
    "ISO 50001": "ISO_50001_webapp.md",
    "ISO 50001 ESQ": "ISO_50001_webapp.md",
    "ISO 50001 CERTIS": "ISO_50001_webapp.md",
}
PROMPTS_CHECKLIST_DIR = os.path.join(WEBAPP_DIR, "prompts", "checklist")

# Modello Gemini per generazione JSON checklist (Tab 2)
GEMINI_MODEL_CHECKLIST = "gemini-2.5-flash"  # Qualità + response_schema per JSON valido

# Norme supportate (ordine per dropdown)
SUPPORTED_NORMS = ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 14064", "ESG", "PAS 24000", "ISO 27001", "ISO 37001", "ISO 39001", "ISO 50001 ESQ", "ISO 50001 CERTIS"]

# ==============================================================================
# PROXY GEMINI API (per regioni bloccate - es. Hetzner EU)
# ==============================================================================
# Se configurato, tutte le chiamate Gemini API passano tramite questo proxy
# Lasciare vuoto per connessione diretta (default)
GEMINI_PROXY_URL = os.environ.get("GEMINI_PROXY_URL", "")
GEMINI_PROXY_SECRET = os.environ.get("GEMINI_PROXY_SECRET", "")

# ==============================================================================
# PIPELINE V2 (Metodo A — Triage Funnel) — additiva, non altera V1
# ==============================================================================
# Feature flag globale: se "true" e l'utente è in V2_USER_WHITELIST, l'endpoint
# storico /api/report/process viene rediretto internamente a V2.
# Default "false": V2 risponde solo su /api/v2/* per testing isolato.
USE_V2_PIPELINE = os.environ.get("USE_V2_PIPELINE", "false").lower() == "true"

# Whitelist utenti per attivazione progressiva. Solo questi user_id vedono V2
# anche con USE_V2_PIPELINE=true. Vuoto = nessuno (V1 per tutti).
V2_USER_WHITELIST = [
    u.strip()
    for u in os.environ.get("V2_USER_WHITELIST", "DocAllfix").split(",")
    if u.strip()
]

# Subprocess isolation per V2 (Fase 8.5). Default OFF in dev, ON in prod.
V2_USE_SUBPROCESS = os.environ.get("V2_USE_SUBPROCESS", "false").lower() == "true"

# TTL persistenza progress (secondi). Default 7 giorni live + 30 giorni archive.
V2_PROGRESS_TTL_LIVE_SECONDS = int(os.environ.get("V2_PROGRESS_TTL_LIVE", "604800"))
V2_PROGRESS_TTL_ARCHIVE_SECONDS = int(os.environ.get("V2_PROGRESS_TTL_ARCHIVE", "2592000"))

# Cache Gemini context (Fase 3). TTL standard 1h.
V2_CACHE_TTL_SECONDS = int(os.environ.get("V2_CACHE_TTL_SECONDS", "3600"))

# Cap di sicurezza globale sulla risposta API (Fase 5). Previene crash lxml.
V2_MAX_RESPONSE_CHARS = int(os.environ.get("V2_MAX_RESPONSE_CHARS", "400000"))

