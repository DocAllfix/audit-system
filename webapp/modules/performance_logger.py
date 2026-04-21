# ==============================================================================
# PERFORMANCE LOGGER - Sistema di benchmark per analisi tempi di elaborazione
# ==============================================================================
# Registra tempi, dimensioni, complessità per report prestazionali cliente
# ==============================================================================

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
import sys

# Aggiungi percorso config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TEMP_DIR

class PerformanceLogger:
    """
    Logger specializzato per il benchmarking delle prestazioni.
    Registra tempi di elaborazione, dimensioni file, complessità per analisi cliente.
    """
    
    # File centralizzato per tutti i test
    PERFORMANCE_FILE = os.path.join(TEMP_DIR, "performance_benchmark.json")
    
    def __init__(self):
        """Inizializza il logger e carica dati esistenti."""
        os.makedirs(TEMP_DIR, exist_ok=True)
        self.data = self._load_existing()
    
    def _load_existing(self) -> Dict:
        """Carica dati benchmark esistenti o crea struttura vuota."""
        if os.path.exists(self.PERFORMANCE_FILE):
            try:
                with open(self.PERFORMANCE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        
        return {
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "total_tests": 0,
            "tests": []
        }
    
    def start_test(self, test_name: str, norma_iso: str, zip_size_mb: float, 
                   total_files: int, files_requiring_ocr: int = 0,
                   notes: str = "") -> str:
        """
        Avvia un nuovo test di benchmark.
        
        Args:
            test_name: Nome identificativo del test
            norma_iso: Norma ISO utilizzata (es. "ISO 45001", "ISO 14001")
            zip_size_mb: Dimensione totale ZIP in MB
            total_files: Numero totale file nel ZIP
            files_requiring_ocr: Numero file che richiedono OCR
            notes: Note aggiuntive
            
        Returns:
            test_id univoco
        """
        test_id = f"TEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        test_entry = {
            "test_id": test_id,
            "test_name": test_name,
            "norma_iso": norma_iso,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "status": "in_progress",
            
            # Metriche file
            "zip_size_mb": zip_size_mb,
            "total_files": total_files,
            "files_requiring_ocr": files_requiring_ocr,
            
            # Fasi temporali
            "phases": {
                "tab1_estrazione": {
                    "started_at": None,
                    "completed_at": None,
                    "duration_seconds": None,
                    "files_processed": 0,
                    "files_with_text": 0,
                    "files_empty": 0,
                    "ocr_files_processed": 0
                },
                "tab2_checklist": {
                    "started_at": None,
                    "completed_at": None,
                    "duration_seconds": None,
                    "clauses_generated": 0,
                    "api_calls": 0
                },
                "tab3_word": {
                    "started_at": None,
                    "completed_at": None,
                    "duration_seconds": None,
                    "document_generated": False
                }
            },
            
            # Tempi totali
            "total_duration_seconds": None,
            
            # Note e osservazioni
            "notes": notes,
            "errors": []
        }
        
        self.data["tests"].append(test_entry)
        self.data["total_tests"] += 1
        self._save()
        
        return test_id
    
    def start_phase(self, test_id: str, phase: str):
        """Avvia cronometro per una fase specifica."""
        test = self._find_test(test_id)
        if test and phase in test["phases"]:
            test["phases"][phase]["started_at"] = datetime.now().isoformat()
            self._save()
    
    def complete_phase(self, test_id: str, phase: str, 
                       files_processed: int = 0,
                       files_with_text: int = 0,
                       files_empty: int = 0,
                       ocr_files_processed: int = 0,
                       clauses_generated: int = 0,
                       api_calls: int = 0,
                       document_generated: bool = False):
        """
        Completa una fase e calcola durata.
        
        Args variano in base alla fase:
        - tab1: files_processed, files_with_text, files_empty, ocr_files_processed
        - tab2: clauses_generated, api_calls
        - tab3: document_generated
        """
        test = self._find_test(test_id)
        if not test or phase not in test["phases"]:
            return
        
        phase_data = test["phases"][phase]
        phase_data["completed_at"] = datetime.now().isoformat()
        
        # Calcola durata
        if phase_data["started_at"]:
            start = datetime.fromisoformat(phase_data["started_at"])
            end = datetime.fromisoformat(phase_data["completed_at"])
            phase_data["duration_seconds"] = (end - start).total_seconds()
        
        # Popola metriche specifiche per fase
        if phase == "tab1_estrazione":
            phase_data["files_processed"] = files_processed
            phase_data["files_with_text"] = files_with_text
            phase_data["files_empty"] = files_empty
            phase_data["ocr_files_processed"] = ocr_files_processed
        elif phase == "tab2_checklist":
            phase_data["clauses_generated"] = clauses_generated
            phase_data["api_calls"] = api_calls
        elif phase == "tab3_word":
            phase_data["document_generated"] = document_generated
        
        self._save()
    
    def complete_test(self, test_id: str, notes: str = ""):
        """Completa un test e calcola tempo totale."""
        test = self._find_test(test_id)
        if not test:
            return
        
        test["completed_at"] = datetime.now().isoformat()
        test["status"] = "completed"
        
        # Calcola durata totale
        start = datetime.fromisoformat(test["started_at"])
        end = datetime.fromisoformat(test["completed_at"])
        test["total_duration_seconds"] = (end - start).total_seconds()
        
        if notes:
            test["notes"] = notes
        
        self.data["last_updated"] = datetime.now().isoformat()
        self._save()
    
    def log_error(self, test_id: str, error: str, phase: str = ""):
        """Registra errore durante un test."""
        test = self._find_test(test_id)
        if test:
            test["errors"].append({
                "error": error,
                "phase": phase,
                "timestamp": datetime.now().isoformat()
            })
            self._save()
    
    def update_from_json(self, test_id: str, phase: str, json_data: Dict):
        """
        Aggiorna metriche di una fase partendo dal JSON di output della webapp.
        Estrae automaticamente le metriche rilevanti.
        """
        test = self._find_test(test_id)
        if not test:
            return
        
        phase_data = test["phases"].get(phase, {})
        
        # Estrai metriche in base alla struttura JSON
        if phase == "tab1_estrazione":
            # Cerca campi comuni nei JSON di Tab 1
            phase_data["files_processed"] = json_data.get("total_files", 
                                             json_data.get("files_processed", 0))
            phase_data["files_with_text"] = json_data.get("files_with_text",
                                             json_data.get("successful", 0))
            phase_data["files_empty"] = json_data.get("files_empty",
                                         json_data.get("empty", 0))
            phase_data["ocr_files_processed"] = json_data.get("ocr_processed",
                                                 json_data.get("ocr_files", 0))
            
        elif phase == "tab2_checklist":
            phase_data["clauses_generated"] = json_data.get("clauses_count",
                                               json_data.get("total_clauses", 0))
            phase_data["api_calls"] = json_data.get("api_calls", 0)
            
        elif phase == "tab3_word":
            phase_data["document_generated"] = json_data.get("success", 
                                                json_data.get("generated", False))
        
        self._save()
    
    def add_manual_entry(self, test_name: str, norma_iso: str,
                         zip_size_mb: float, total_files: int,
                         files_requiring_ocr: int,
                         tab1_duration_sec: float,
                         tab2_duration_sec: float,
                         tab3_duration_sec: float,
                         files_with_text: int = 0,
                         files_empty: int = 0,
                         clauses_generated: int = 0,
                         notes: str = ""):
        """
        Aggiunge un entry manuale completo (per retrocompatibilità o inserimenti manuali).
        """
        test_id = f"MANUAL_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        now = datetime.now().isoformat()
        
        total_duration = tab1_duration_sec + tab2_duration_sec + tab3_duration_sec
        
        test_entry = {
            "test_id": test_id,
            "test_name": test_name,
            "norma_iso": norma_iso,
            "started_at": now,
            "completed_at": now,
            "status": "completed",
            "zip_size_mb": zip_size_mb,
            "total_files": total_files,
            "files_requiring_ocr": files_requiring_ocr,
            "phases": {
                "tab1_estrazione": {
                    "started_at": now,
                    "completed_at": now,
                    "duration_seconds": tab1_duration_sec,
                    "files_processed": total_files,
                    "files_with_text": files_with_text,
                    "files_empty": files_empty,
                    "ocr_files_processed": files_requiring_ocr
                },
                "tab2_checklist": {
                    "started_at": now,
                    "completed_at": now,
                    "duration_seconds": tab2_duration_sec,
                    "clauses_generated": clauses_generated,
                    "api_calls": 0
                },
                "tab3_word": {
                    "started_at": now,
                    "completed_at": now,
                    "duration_seconds": tab3_duration_sec,
                    "document_generated": True
                }
            },
            "total_duration_seconds": total_duration,
            "notes": notes,
            "errors": []
        }
        
        self.data["tests"].append(test_entry)
        self.data["total_tests"] += 1
        self.data["last_updated"] = now
        self._save()
        
        return test_id
    
    def get_all_tests(self) -> List[Dict]:
        """Restituisce tutti i test registrati."""
        return self.data["tests"]
    
    def get_statistics(self) -> Dict:
        """
        Calcola statistiche aggregate sui test completati.
        """
        completed = [t for t in self.data["tests"] if t["status"] == "completed"]
        
        if not completed:
            return {"message": "Nessun test completato disponibile"}
        
        # Statistiche per fase
        tab1_times = [t["phases"]["tab1_estrazione"]["duration_seconds"] 
                      for t in completed if t["phases"]["tab1_estrazione"]["duration_seconds"]]
        tab2_times = [t["phases"]["tab2_checklist"]["duration_seconds"] 
                      for t in completed if t["phases"]["tab2_checklist"]["duration_seconds"]]
        tab3_times = [t["phases"]["tab3_word"]["duration_seconds"] 
                      for t in completed if t["phases"]["tab3_word"]["duration_seconds"]]
        total_times = [t["total_duration_seconds"] for t in completed if t["total_duration_seconds"]]
        
        def calc_stats(values):
            if not values:
                return {"min": 0, "max": 0, "avg": 0, "count": 0}
            return {
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "avg": round(sum(values) / len(values), 2),
                "count": len(values)
            }
        
        return {
            "total_tests": len(completed),
            "tab1_estrazione": calc_stats(tab1_times),
            "tab2_checklist": calc_stats(tab2_times),
            "tab3_word": calc_stats(tab3_times),
            "totale": calc_stats(total_times),
            "per_norma": self._stats_by_norma(completed),
            "correlazioni": self._calc_correlations(completed)
        }
    
    def _stats_by_norma(self, tests: List[Dict]) -> Dict:
        """Calcola statistiche raggruppate per norma ISO."""
        by_norma = {}
        for t in tests:
            norma = t["norma_iso"]
            if norma not in by_norma:
                by_norma[norma] = []
            by_norma[norma].append(t["total_duration_seconds"] or 0)
        
        return {
            norma: {
                "count": len(times),
                "avg_seconds": round(sum(times) / len(times), 2) if times else 0
            }
            for norma, times in by_norma.items()
        }
    
    def _calc_correlations(self, tests: List[Dict]) -> Dict:
        """Calcola correlazioni utili (tempo vs dimensione, tempo vs OCR)."""
        if len(tests) < 2:
            return {"message": "Servono almeno 2 test per calcolare correlazioni"}
        
        # Tempo per MB
        tempo_per_mb = []
        for t in tests:
            if t["zip_size_mb"] and t["total_duration_seconds"]:
                tempo_per_mb.append(t["total_duration_seconds"] / t["zip_size_mb"])
        
        # Tempo per file
        tempo_per_file = []
        for t in tests:
            if t["total_files"] and t["total_duration_seconds"]:
                tempo_per_file.append(t["total_duration_seconds"] / t["total_files"])
        
        return {
            "avg_seconds_per_mb": round(sum(tempo_per_mb) / len(tempo_per_mb), 2) if tempo_per_mb else 0,
            "avg_seconds_per_file": round(sum(tempo_per_file) / len(tempo_per_file), 2) if tempo_per_file else 0
        }
    
    def generate_report_data(self) -> Dict:
        """
        Genera dati strutturati per il report finale cliente.
        """
        stats = self.get_statistics()
        
        return {
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_tests_completed": stats.get("total_tests", 0),
                "average_total_time_seconds": stats.get("totale", {}).get("avg", 0),
                "average_per_phase": {
                    "estrazione_evidenze": stats.get("tab1_estrazione", {}).get("avg", 0),
                    "generazione_checklist": stats.get("tab2_checklist", {}).get("avg", 0),
                    "compilazione_word": stats.get("tab3_word", {}).get("avg", 0)
                }
            },
            "performance_by_norma": stats.get("per_norma", {}),
            "correlations": stats.get("correlazioni", {}),
            "detailed_tests": self.data["tests"],
            "recommendations": self._generate_recommendations(stats)
        }
    
    def _generate_recommendations(self, stats: Dict) -> List[str]:
        """Genera raccomandazioni basate sui dati."""
        recs = []
        
        correlazioni = stats.get("correlazioni", {})
        if correlazioni.get("avg_seconds_per_mb", 0) > 0:
            recs.append(f"Tempo medio per MB: {correlazioni['avg_seconds_per_mb']} secondi")
        if correlazioni.get("avg_seconds_per_file", 0) > 0:
            recs.append(f"Tempo medio per file: {correlazioni['avg_seconds_per_file']} secondi")
        
        return recs
    
    def _find_test(self, test_id: str) -> Optional[Dict]:
        """Trova un test per ID."""
        return next((t for t in self.data["tests"] if t["test_id"] == test_id), None)
    
    def _save(self):
        """Salva dati su file."""
        try:
            with open(self.PERFORMANCE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Errore salvataggio performance log: {e}")


# Singleton per accesso globale
_performance_logger = None

def get_performance_logger() -> PerformanceLogger:
    """Restituisce istanza singleton del performance logger."""
    global _performance_logger
    if _performance_logger is None:
        _performance_logger = PerformanceLogger()
    return _performance_logger
