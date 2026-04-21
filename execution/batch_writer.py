"""
==============================================================================
BATCH_WRITER.PY - Gestione Scrittura Incrementale JSONL
==============================================================================
Script di supporto per la scrittura incrementale di paragrafi in formato JSONL.
Usato dall'Agente per prevenire overflow del buffer di output su grandi volumi.
Parte del framework DOE - Execution Layer.

Input:  Chiamate incrementali dall'Agente
Output: /temp/agent_output.jsonl

Autore: Agente DOE
Data: 2026-01-01
==============================================================================
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Importa configurazione
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PROJECT_ROOT

# ==============================================================================
# COSTANTI E PERCORSI
# ==============================================================================

TEMP_DIR = os.path.join(PROJECT_ROOT, "temp")
JSONL_OUTPUT_PATH = os.path.join(TEMP_DIR, "agent_output.jsonl")


# ==============================================================================
# FUNZIONI DI SCRITTURA JSONL
# ==============================================================================

def init_jsonl_file(titolo, sottotitolo, data_redazione, statistiche):
    """
    Inizializza il file JSONL con l'header contenente metadata.
    ATTENZIONE: Sovrascrive qualsiasi file esistente.
    
    Args:
        titolo: Titolo del report (es. "RELAZIONE DI EVIDENZE DI AUDIT")
        sottotitolo: Sottotitolo (es. "Audit ISO 14001 - NOME AZIENDA")
        data_redazione: Data in formato GG/MM/AAAA
        statistiche: Dict con documenti_estratti, documenti_vuoti, documenti_analizzati
    
    Returns:
        str: Percorso del file JSONL creato
    """
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    header = {
        "type": "header",
        "titolo": titolo,
        "sottotitolo": sottotitolo,
        "data_redazione": data_redazione,
        "statistiche": statistiche,
        "generated_at": datetime.now().isoformat()
    }
    
    with open(JSONL_OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(json.dumps(header, ensure_ascii=False) + '\n')
    
    print(f"[JSONL] File inizializzato: {JSONL_OUTPUT_PATH}")
    return JSONL_OUTPUT_PATH


def append_categoria(nome_categoria):
    """
    Aggiunge un marcatore di categoria al file JSONL.
    
    Args:
        nome_categoria: Nome della categoria (es. "DOCUMENTAZIONE SOCIETARIA")
    """
    categoria = {
        "type": "categoria",
        "nome": nome_categoria
    }
    
    with open(JSONL_OUTPUT_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(categoria, ensure_ascii=False) + '\n')


def append_paragrafo(numero, sottotitolo, contenuto, categoria=None):
    """
    Aggiunge un paragrafo al file JSONL (append atomico).
    
    Args:
        numero: Numero progressivo del paragrafo
        sottotitolo: Sottotitolo identificativo del documento
        contenuto: Testo del paragrafo (200-800 parole)
        categoria: Nome categoria di appartenenza (opzionale, per riferimento)
    """
    paragrafo = {
        "type": "paragrafo",
        "numero": numero,
        "sottotitolo": sottotitolo,
        "contenuto": contenuto
    }
    
    if categoria:
        paragrafo["categoria"] = categoria
    
    with open(JSONL_OUTPUT_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(paragrafo, ensure_ascii=False) + '\n')


def append_batch(paragrafi_list):
    """
    Aggiunge un batch di paragrafi al file JSONL.
    Più efficiente per scritture multiple.
    
    Args:
        paragrafi_list: Lista di dict con keys: numero, sottotitolo, contenuto, [categoria]
    """
    with open(JSONL_OUTPUT_PATH, 'a', encoding='utf-8') as f:
        for p in paragrafi_list:
            paragrafo = {
                "type": "paragrafo",
                "numero": p.get("numero"),
                "sottotitolo": p.get("sottotitolo"),
                "contenuto": p.get("contenuto")
            }
            if p.get("categoria"):
                paragrafo["categoria"] = p["categoria"]
            
            f.write(json.dumps(paragrafo, ensure_ascii=False) + '\n')
    
    print(f"[JSONL] Scritti {len(paragrafi_list)} paragrafi")


def get_stats():
    """
    Restituisce statistiche sul file JSONL corrente.
    
    Returns:
        dict: Conteggio per tipo di riga
    """
    if not os.path.exists(JSONL_OUTPUT_PATH):
        return {"exists": False}
    
    stats = {"header": 0, "categoria": 0, "paragrafo": 0, "total_lines": 0}
    
    with open(JSONL_OUTPUT_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            stats["total_lines"] += 1
            try:
                obj = json.loads(line.strip())
                tipo = obj.get("type", "unknown")
                stats[tipo] = stats.get(tipo, 0) + 1
            except json.JSONDecodeError:
                stats["invalid"] = stats.get("invalid", 0) + 1
    
    stats["exists"] = True
    return stats


def validate_jsonl():
    """
    Valida il file JSONL verificando che ogni riga sia JSON valido.
    
    Returns:
        tuple: (is_valid: bool, errors: list, stats: dict)
    """
    if not os.path.exists(JSONL_OUTPUT_PATH):
        return False, ["File non esiste"], {}
    
    errors = []
    stats = {"header": 0, "categoria": 0, "paragrafo": 0}
    
    with open(JSONL_OUTPUT_PATH, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                obj = json.loads(line)
                tipo = obj.get("type", "unknown")
                stats[tipo] = stats.get(tipo, 0) + 1
                
                # Validazioni specifiche per tipo
                if tipo == "paragrafo":
                    if not obj.get("contenuto"):
                        errors.append(f"Riga {line_num}: paragrafo senza contenuto")
                    if not obj.get("numero"):
                        errors.append(f"Riga {line_num}: paragrafo senza numero")
                        
            except json.JSONDecodeError as e:
                errors.append(f"Riga {line_num}: JSON invalido - {e}")
    
    is_valid = len(errors) == 0
    return is_valid, errors, stats


# ==============================================================================
# ENTRY POINT (per test)
# ==============================================================================

def main():
    """Test delle funzioni di scrittura JSONL."""
    print("=" * 60)
    print("TEST BATCH_WRITER - Scrittura JSONL")
    print("=" * 60)
    
    # Test inizializzazione
    init_jsonl_file(
        titolo="RELAZIONE DI EVIDENZE DI AUDIT",
        sottotitolo="Audit ISO 9001 - TEST AZIENDA S.R.L.",
        data_redazione="01/01/2026",
        statistiche={
            "documenti_estratti": 50,
            "documenti_vuoti": 2,
            "documenti_analizzati": 48
        }
    )
    
    # Test categoria
    append_categoria("DOCUMENTAZIONE SOCIETARIA")
    
    # Test paragrafo singolo
    append_paragrafo(
        numero=1,
        sottotitolo="Visura Camerale CCIAA Napoli",
        contenuto="Esaminata la Visura Camerale della società TEST AZIENDA S.R.L. " * 50,
        categoria="DOCUMENTAZIONE SOCIETARIA"
    )
    
    # Test batch
    append_batch([
        {"numero": 2, "sottotitolo": "DURC Regolarità", "contenuto": "Visionato il DURC..." * 30},
        {"numero": 3, "sottotitolo": "Certificato ISO 9001", "contenuto": "Acquisito il Certificato..." * 40}
    ])
    
    # Statistiche
    stats = get_stats()
    print(f"\n[STATS] {stats}")
    
    # Validazione
    is_valid, errors, val_stats = validate_jsonl()
    print(f"[VALID] {is_valid}")
    if errors:
        for e in errors:
            print(f"  - {e}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETATO")
    print("=" * 60)


if __name__ == "__main__":
    main()
