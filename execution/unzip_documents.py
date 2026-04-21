"""
==============================================================================
UNZIP_DOCUMENTS.PY - Ingestion e Indicizzazione (FASE 1)
==============================================================================
Script per l'estrazione e catalogazione di file ZIP contenenti documentazione
di audit. Parte del framework DOE - Execution Layer.

Input:  /input/*.zip
Output: /temp/extracted/, /temp/manifest.json

Autore: Agente DOE
Data: 2025-12-29
==============================================================================
"""

import os
import sys
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

# Importa configurazione
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PROJECT_ROOT


# ==============================================================================
# COSTANTI E PERCORSI
# ==============================================================================

INPUT_DIR = os.path.join(PROJECT_ROOT, "input")
TEMP_DIR = os.path.join(PROJECT_ROOT, "temp")
EXTRACTED_DIR = os.path.join(TEMP_DIR, "extracted")
MANIFEST_PATH = os.path.join(TEMP_DIR, "manifest.json")

# Estensioni supportate per categoria
FILE_CATEGORIES = {
    "pdf": [".pdf"],
    "word": [".doc", ".docx"],
    "excel": [".xls", ".xlsx"],
    "images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif"],
    "text": [".txt", ".csv"],
    "other": []
}


# ==============================================================================
# FUNZIONI PRINCIPALI
# ==============================================================================

def clean_temp_directory():
    """
    Svuota completamente la directory /temp per garantire igiene dei dati.
    Chiamata all'inizio di ogni nuova esecuzione.
    """
    if os.path.exists(TEMP_DIR):
        print(f"[INFO] Pulizia Staging Area: {TEMP_DIR}")
        shutil.rmtree(TEMP_DIR)
    
    # Ricrea la struttura
    os.makedirs(EXTRACTED_DIR, exist_ok=True)
    os.makedirs(os.path.join(TEMP_DIR, "text_chunks"), exist_ok=True)
    os.makedirs(os.path.join(TEMP_DIR, "images"), exist_ok=True)
    print("[INFO] Staging Area ricreata con struttura pulita.")


def find_zip_files():
    """
    Cerca tutti i file ZIP nella Landing Zone (/input).
    
    Returns:
        list: Lista dei percorsi completi dei file ZIP trovati.
    """
    if not os.path.exists(INPUT_DIR):
        os.makedirs(INPUT_DIR, exist_ok=True)
        print(f"[WARNING] Landing Zone creata: {INPUT_DIR}")
        return []
    
    zip_files = [
        os.path.join(INPUT_DIR, f) 
        for f in os.listdir(INPUT_DIR) 
        if f.lower().endswith(".zip")
    ]
    
    print(f"[INFO] Trovati {len(zip_files)} file ZIP nella Landing Zone.")
    return zip_files


def categorize_file(filename):
    """
    Determina la categoria di un file basandosi sull'estensione.
    
    Args:
        filename: Nome del file.
    
    Returns:
        str: Nome della categoria (pdf, word, images, etc.)
    """
    ext = os.path.splitext(filename)[1].lower()
    
    for category, extensions in FILE_CATEGORIES.items():
        if ext in extensions:
            return category
    
    return "other"


def extract_zip(zip_path):
    """
    Estrae il contenuto di un file ZIP nella Staging Area.
    OTTIMIZZATO: rimosso logging per ogni singolo file.
    
    Args:
        zip_path: Percorso completo del file ZIP.
    
    Returns:
        list: Lista dei file estratti con metadati.
    """
    extracted_files = []
    zip_name = os.path.splitext(os.path.basename(zip_path))[0]
    extract_subdir = os.path.join(EXTRACTED_DIR, zip_name)
    
    print(f"[INFO] Estrazione: {os.path.basename(zip_path)}")
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Estrai tutti i file
            zf.extractall(extract_subdir)
            
            # Cataloga ogni file estratto (senza print per velocita)
            for root, dirs, files in os.walk(extract_subdir):
                for filename in files:
                    # Ignora file nascosti, di sistema e metadata macOS (._*)
                    if filename.startswith('.') or filename.startswith('__') or filename.startswith('._'):
                        continue
                    
                    filepath = os.path.join(root, filename)
                    rel_path = os.path.relpath(filepath, EXTRACTED_DIR)
                    category = categorize_file(filename)
                    
                    file_info = {
                        "filename": filename,
                        "relative_path": rel_path,
                        "absolute_path": filepath,
                        "category": category,
                        "size_bytes": os.path.getsize(filepath),
                        "source_zip": os.path.basename(zip_path)
                    }
                    
                    extracted_files.append(file_info)
        
        print(f"[INFO] Estratti {len(extracted_files)} file da {os.path.basename(zip_path)}")
        
    except zipfile.BadZipFile:
        print(f"[ERROR] File ZIP corrotto: {zip_path}")
    except Exception as e:
        print(f"[ERROR] Errore durante l'estrazione: {str(e)}")
    
    return extracted_files


def create_reading_order(files):
    """
    Stabilisce un ordine logico di lettura dei documenti.
    Priorità: PDF > Word > Excel > Immagini > Altro
    All'interno di ogni categoria, ordine alfabetico.
    
    Args:
        files: Lista dei file estratti.
    
    Returns:
        list: File ordinati per lettura ottimale.
    """
    priority = {"pdf": 1, "word": 2, "excel": 3, "images": 4, "text": 5, "other": 6}
    
    return sorted(
        files,
        key=lambda x: (priority.get(x["category"], 99), x["filename"].lower())
    )


def generate_manifest(all_files):
    """
    Genera il manifest JSON con tutti i file catalogati e l'ordine di lettura.
    
    Args:
        all_files: Lista completa dei file estratti.
    
    Returns:
        dict: Manifest strutturato.
    """
    # Ordina per lettura ottimale
    ordered_files = create_reading_order(all_files)
    
    # Conta per categoria
    category_counts = {}
    for f in all_files:
        cat = f["category"]
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    manifest = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "total_files": len(all_files),
            "categories": category_counts
        },
        "files": ordered_files
    }
    
    # Salva il manifest (senza indent per velocita)
    with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
    
    print(f"\n[INFO] Manifest generato: {MANIFEST_PATH}")
    print(f"[INFO] Totale file indicizzati: {len(all_files)}")
    for cat, count in category_counts.items():
        print(f"  > {cat.upper()}: {count}")
    
    return manifest


# ==============================================================================
# ENTRY POINT
# ==============================================================================

def main(zip_path=None):
    """
    Funzione principale di ingestion.
    
    Args:
        zip_path: Percorso opzionale di un singolo ZIP. 
                  Se None, processa tutti gli ZIP in /input.
    
    Returns:
        dict: Manifest dei file estratti.
    """
    print("=" * 60)
    print("FASE 1: INGESTION E INDICIZZAZIONE")
    print("=" * 60)
    
    # Step 1: Pulisci la Staging Area
    clean_temp_directory()
    
    # Step 2: Trova i file ZIP
    if zip_path:
        zip_files = [zip_path] if os.path.exists(zip_path) else []
    else:
        zip_files = find_zip_files()
    
    if not zip_files:
        print("[WARNING] Nessun file ZIP trovato nella Landing Zone.")
        print(f"[INFO] Deposita i file ZIP in: {INPUT_DIR}")
        return None
    
    # Step 3: Estrai tutti gli ZIP
    all_extracted_files = []
    for zf in zip_files:
        extracted = extract_zip(zf)
        all_extracted_files.extend(extracted)
    
    # Step 4: Genera il manifest
    manifest = generate_manifest(all_extracted_files)
    
    print("\n" + "=" * 60)
    print("FASE 1 COMPLETATA")
    print("=" * 60)
    
    return manifest


if __name__ == "__main__":
    # Supporto per argomento da linea di comando
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main()
