# ==============================================================================
# CONFIGURAZIONE AMBIENTE - Audit Automation Framework (DOE)
# ==============================================================================
# Percorsi degli strumenti esterni per OCR e manipolazione PDF
# Questo file viene importato dagli script di esecuzione
# ==============================================================================

import os

# --- TESSERACT OCR ---
# Installato tramite winget: tesseract-ocr.tesseract v5.5.0
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Verifica esistenza Tesseract
if not os.path.exists(TESSERACT_PATH):
    print(f"[WARNING] Tesseract non trovato in: {TESSERACT_PATH}")

# Configura pytesseract per usare il percorso corretto
try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
except ImportError:
    pass  # pytesseract non ancora installato

# --- POPPLER (per pdf2image) ---
# Installato tramite winget: oschwartz10612.Poppler v25.07.0
POPPLER_PATH = r"C:\Users\user\AppData\Local\Microsoft\WinGet\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe\poppler-25.07.0\Library\bin"

# Verifica esistenza Poppler
if not os.path.exists(POPPLER_PATH):
    print(f"[WARNING] Poppler non trovato in: {POPPLER_PATH}")

# --- DIRECTORY DI LAVORO ---
# Directory base del progetto
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directory per file temporanei di estrazione
TEMP_EXTRACTION_DIR = os.path.join(PROJECT_ROOT, "temp_extraction")

# Directory per output generati
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")

# --- LINGUE OCR ---
# Lingue supportate da Tesseract per il riconoscimento
# 'ita' = Italiano, 'eng' = Inglese
OCR_LANGUAGES = "ita+eng"

# ==============================================================================
# FUNZIONI DI UTILITÀ
# ==============================================================================

def ensure_directories():
    """Crea le directory di lavoro se non esistono."""
    for directory in [TEMP_EXTRACTION_DIR, OUTPUT_DIR]:
        os.makedirs(directory, exist_ok=True)
        
def get_poppler_path():
    """Restituisce il percorso di Poppler per pdf2image."""
    return POPPLER_PATH

def get_tesseract_cmd():
    """Restituisce il percorso dell'eseguibile Tesseract."""
    return TESSERACT_PATH


if __name__ == "__main__":
    # Test di verifica configurazione
    print("=" * 60)
    print("VERIFICA CONFIGURAZIONE AMBIENTE")
    print("=" * 60)
    print(f"Tesseract: {TESSERACT_PATH}")
    print(f"  Esiste: {os.path.exists(TESSERACT_PATH)}")
    print(f"Poppler:   {POPPLER_PATH}")
    print(f"  Esiste: {os.path.exists(POPPLER_PATH)}")
    print(f"Project:   {PROJECT_ROOT}")
    print("=" * 60)
