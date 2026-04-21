# ==============================================================================
# LOGGER - Sistema di logging per diagnostica e debug
# ==============================================================================
# Salva log dettagliati in file per analisi post-elaborazione
# ==============================================================================

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
import sys

# Aggiungi percorso config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TEMP_DIR

class AuditLogger:
    """
    Logger specializzato per il processo di audit.
    Salva log dettagliati in JSON per analisi post-elaborazione.
    """
    
    def __init__(self, session_id: str = None):
        """Inizializza il logger con un ID sessione univoco."""
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = os.path.join(TEMP_DIR, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.log_file = os.path.join(self.log_dir, f"audit_log_{self.session_id}.json")
        
        # Struttura log completa
        self.log_data = {
            "session_id": self.session_id,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "status": "in_progress",
            
            # Fase 1: Estrazione ZIP
            "extraction": {
                "total_files": 0,
                "extracted_files": [],
                "failed_files": [],
                "skipped_files": []
            },
            
            # Fase 2: Estrazione testo
            "text_extraction": {
                "total_processed": 0,
                "successful": [],
                "empty": [],
                "failed": []
            },
            
            # Fase 3: Analisi AI
            "ai_analysis": {
                "total_batches": 0,
                "batches": [],  # Dettagli per batch
                "total_paragraphs_generated": 0,
                "api_errors": [],
                "validation_errors": [],
                "regenerations": []
            },
            
            # Fase 4: Generazione Word
            "word_generation": {
                "success": False,
                "paragraphs_written": 0,
                "company_name_detected": "",
                "company_name_source": ""
            },
            
            # Riepilogo errori
            "errors": [],
            "warnings": []
        }
    
    def log_extraction_start(self, total_files: int):
        """Logga inizio estrazione ZIP."""
        self.log_data["extraction"]["total_files"] = total_files
        self._save()
    
    def log_file_extracted(self, filename: str, category: str, size: int):
        """Logga file estratto con successo."""
        self.log_data["extraction"]["extracted_files"].append({
            "filename": filename,
            "category": category,
            "size": size,
            "timestamp": datetime.now().isoformat()
        })
        self._save()
    
    def log_file_skipped(self, filename: str, reason: str):
        """Logga file saltato."""
        self.log_data["extraction"]["skipped_files"].append({
            "filename": filename,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        self._save()
    
    def log_text_extraction(self, filename: str, status: str, text_length: int = 0, error: str = None):
        """Logga risultato estrazione testo."""
        entry = {
            "filename": filename,
            "text_length": text_length,
            "timestamp": datetime.now().isoformat()
        }
        
        if status == "success":
            self.log_data["text_extraction"]["successful"].append(entry)
        elif status == "empty":
            entry["error"] = error or "Testo vuoto o insufficiente"
            self.log_data["text_extraction"]["empty"].append(entry)
        else:
            entry["error"] = error or "Errore sconosciuto"
            self.log_data["text_extraction"]["failed"].append(entry)
        
        self.log_data["text_extraction"]["total_processed"] += 1
        self._save()
    
    def log_batch_start(self, batch_index: int, documents: List[str], total_batches: int):
        """Logga inizio elaborazione batch."""
        self.log_data["ai_analysis"]["total_batches"] = total_batches
        
        batch_entry = {
            "batch_index": batch_index,
            "documents": documents,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "status": "in_progress",
            "paragraphs_generated": 0,
            "api_response_length": 0,
            "errors": [],
            "regenerations": []
        }
        
        # Cerca se esiste già questo batch
        existing = next((b for b in self.log_data["ai_analysis"]["batches"] if b["batch_index"] == batch_index), None)
        if existing:
            existing.update(batch_entry)
        else:
            self.log_data["ai_analysis"]["batches"].append(batch_entry)
        
        self._save()
    
    def log_batch_complete(self, batch_index: int, paragraphs_count: int, response_length: int = 0):
        """Logga completamento batch con successo."""
        batch = next((b for b in self.log_data["ai_analysis"]["batches"] if b["batch_index"] == batch_index), None)
        if batch:
            batch["completed_at"] = datetime.now().isoformat()
            batch["status"] = "success"
            batch["paragraphs_generated"] = paragraphs_count
            batch["api_response_length"] = response_length
        
        self.log_data["ai_analysis"]["total_paragraphs_generated"] += paragraphs_count
        self._save()
    
    def log_batch_error(self, batch_index: int, error: str):
        """Logga errore batch."""
        batch = next((b for b in self.log_data["ai_analysis"]["batches"] if b["batch_index"] == batch_index), None)
        if batch:
            batch["completed_at"] = datetime.now().isoformat()
            batch["status"] = "error"
            batch["errors"].append(error)
        
        self.log_data["ai_analysis"]["api_errors"].append({
            "batch_index": batch_index,
            "error": error,
            "timestamp": datetime.now().isoformat()
        })
        self._save()
    
    def log_validation_error(self, batch_index: int, paragraph_num: int, errors: List[str]):
        """Logga errore validazione paragrafo."""
        self.log_data["ai_analysis"]["validation_errors"].append({
            "batch_index": batch_index,
            "paragraph_num": paragraph_num,
            "errors": errors,
            "timestamp": datetime.now().isoformat()
        })
        self._save()
    
    def log_regeneration(self, batch_index: int, paragraph_num: int, attempt: int, success: bool):
        """Logga tentativo di rigenerazione."""
        self.log_data["ai_analysis"]["regenerations"].append({
            "batch_index": batch_index,
            "paragraph_num": paragraph_num,
            "attempt": attempt,
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
        self._save()
    
    def log_word_generation(self, success: bool, paragraphs: int, company_name: str, source: str):
        """Logga generazione documento Word."""
        self.log_data["word_generation"] = {
            "success": success,
            "paragraphs_written": paragraphs,
            "company_name_detected": company_name,
            "company_name_source": source,
            "timestamp": datetime.now().isoformat()
        }
        self._save()
    
    def log_error(self, error: str, context: str = ""):
        """Logga errore generico."""
        self.log_data["errors"].append({
            "error": error,
            "context": context,
            "timestamp": datetime.now().isoformat()
        })
        self._save()
    
    def log_warning(self, warning: str, context: str = ""):
        """Logga warning."""
        self.log_data["warnings"].append({
            "warning": warning,
            "context": context,
            "timestamp": datetime.now().isoformat()
        })
        self._save()
    
    def complete(self, status: str = "completed"):
        """Completa il log."""
        self.log_data["completed_at"] = datetime.now().isoformat()
        self.log_data["status"] = status
        self._save()
        return self.log_file
    
    def get_summary(self) -> Dict:
        """Restituisce un riepilogo per l'UI."""
        extraction = self.log_data["extraction"]
        text = self.log_data["text_extraction"]
        ai = self.log_data["ai_analysis"]
        
        return {
            "files_in_zip": extraction["total_files"],
            "files_extracted": len(extraction["extracted_files"]),
            "files_skipped": len(extraction["skipped_files"]),
            "text_extracted_ok": len(text["successful"]),
            "text_empty": len(text["empty"]),
            "text_failed": len(text["failed"]),
            "batches_total": ai["total_batches"],
            "batches_completed": len([b for b in ai["batches"] if b["status"] == "success"]),
            "batches_failed": len([b for b in ai["batches"] if b["status"] == "error"]),
            "paragraphs_generated": ai["total_paragraphs_generated"],
            "validation_errors": len(ai["validation_errors"]),
            "regenerations": len(ai["regenerations"]),
            "errors": len(self.log_data["errors"]),
            "warnings": len(self.log_data["warnings"]),
            "log_file": self.log_file
        }
    
    def _save(self):
        """Salva log su file."""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump(self.log_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Errore salvataggio log: {e}")
