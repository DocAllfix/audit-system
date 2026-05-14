"""
V2 — Legacy Event Adapter (Limitazione 2).

Traduce eventi V2 typed (12 categorie) in formato `{pct, msg}` compatibile
col frontend V1 esistente. Permette di usare V2 senza modificare il frontend
quando si attiva `?legacy_events=true`.

Mapping principale (V2 → V1):
- session.start    → {pct: 0, msg: "Avvio elaborazione..."}
- phase.start      → {pct: <stima>, msg: "Inizio fase {phase}..."}
- phase.tick       → {pct: <calcolata da progress phase>, msg: "..."}
- phase.end        → {pct: <fine fase>, msg: "Fase {phase} completata"}
- file.warn        → {warning: msg}
- file.degrade     → {warning: "..."}
- file.done        → opzionalmente conta files
- error            → {error: msg}
- heartbeat        → keepalive (nessun evento V1)
- done             → {done: true, ...} (filename + base64 fuori scope qui)

Pesi delle fasi (somma 100):
  ingestion: 5, triage: 10, classify: 5, ocr: 30,
  analyze: 35, docx_build: 10, cleanup: 5

API pubblica:
    LegacyAdapter() — stateful, traccia phase corrente per pct progressivo
    adapter.translate(event_dict) -> Optional[Dict] (None se evento da skippare)
"""
from __future__ import annotations

from typing import Any, Dict, Optional


# Pesi % per fase (totali 100)
_PHASE_WEIGHTS = {
    "ingestion": 5,
    "triage": 10,
    "classify": 5,
    "ocr": 30,
    "analyze": 35,
    "docx_build": 10,
    "cleanup": 5,
}

# Cumulativi (offset di partenza per ogni fase)
_PHASE_CUM_OFFSET: Dict[str, int] = {}
_acc = 0
for _phase in ("ingestion", "triage", "classify", "ocr", "analyze", "docx_build", "cleanup"):
    _PHASE_CUM_OFFSET[_phase] = _acc
    _acc += _PHASE_WEIGHTS[_phase]


# Messaggi human-readable per fase
_PHASE_MESSAGES = {
    "ingestion": "Estrazione ZIP",
    "triage": "Analisi file",
    "classify": "Classificazione documenti",
    "ocr": "OCR documenti scansionati",
    "analyze": "Analisi AI",
    "docx_build": "Generazione Word",
    "cleanup": "Pulizia risorse",
}


class LegacyAdapter:
    """
    Stateful adapter: traduce eventi V2 typed in formato V1 `{pct, msg}`.

    Traccia la fase corrente e il pct relativo per produrre un avanzamento
    monotono coerente. Non solleva mai eccezioni.
    """

    def __init__(self):
        self._current_phase: Optional[str] = None
        self._last_pct: int = 0
        self._files_done: int = 0
        self._total_files: int = 0
        self._final_payload: Optional[Dict[str, Any]] = None

    def translate(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Args:
            event: dict evento V2 typed (con `type`, `session_id`, ecc.)

        Returns:
            Dict V1-compatible `{pct, msg}` o `{error, ...}` o `{done, ...}`.
            None se l'evento V2 non ha equivalente V1 (es. heartbeat, llm.token).
        """
        if not isinstance(event, dict):
            return None
        event_type = event.get("type", "")

        try:
            if event_type == "session.start":
                self._total_files = int(event.get("total_files", 0) or 0)
                return {"pct": 0, "msg": f"Avvio elaborazione ({self._total_files} file)..."}

            if event_type == "phase.start":
                phase = event.get("phase", "")
                self._current_phase = phase
                base = _PHASE_CUM_OFFSET.get(phase, self._last_pct)
                self._last_pct = max(self._last_pct, base)
                msg_label = _PHASE_MESSAGES.get(phase, phase)
                return {"pct": self._last_pct, "msg": f"{msg_label}..."}

            if event_type == "phase.tick":
                phase = event.get("phase") or self._current_phase
                tick_pct = float(event.get("pct", 0.0) or 0.0)
                weight = _PHASE_WEIGHTS.get(phase, 0)
                base = _PHASE_CUM_OFFSET.get(phase, self._last_pct)
                pct = int(base + (tick_pct * weight))
                pct = max(self._last_pct, min(99, pct))  # mai discendente, max 99
                self._last_pct = pct
                detail = event.get("detail") or {}
                completed = detail.get("completed", "")
                total = detail.get("total", "")
                current_file = detail.get("current_file", "")
                waiting = detail.get("waiting", False)
                msg_label = _PHASE_MESSAGES.get(phase, phase)
                if phase == "ingestion" and current_file:
                    extracted = detail.get("extracted", "")
                    msg = f"Estrazione: {current_file}" + (f" ({extracted} file)" if extracted else "")
                elif phase == "ocr" and waiting:
                    msg = f"OCR in corso — attendere..."
                elif completed and total:
                    msg = f"{msg_label} {completed}/{total}..."
                elif current_file:
                    msg = f"{msg_label}: {current_file}"
                else:
                    msg = f"{msg_label}..."
                return {"pct": pct, "msg": msg}

            if event_type == "phase.end":
                phase = event.get("phase", "")
                base = _PHASE_CUM_OFFSET.get(phase, self._last_pct)
                weight = _PHASE_WEIGHTS.get(phase, 0)
                pct = base + weight
                pct = max(self._last_pct, min(99, pct))
                self._last_pct = pct
                msg_label = _PHASE_MESSAGES.get(phase, phase)
                return {"pct": pct, "msg": f"{msg_label} completata"}

            if event_type == "file.warn":
                msg = event.get("msg") or f"avviso su {event.get('filename', '')}"
                return {"warning": msg, "filename": event.get("filename", "")}

            if event_type == "file.degrade":
                fb = event.get("fallback", "")
                fname = event.get("filename", "")
                return {"warning": f"{fname}: degradato a {fb}"}

            if event_type == "file.done":
                self._files_done += 1
                # Eventi file.done non emettono progress in V1 per evitare
                # spam — lasciamo passare solo summary periodici
                return None

            if event_type == "error":
                kind = event.get("kind", "unknown")
                msg = event.get("msg", "")
                return {"error": f"[{kind}] {msg}"}

            if event_type == "done":
                # Cattura il payload finale per arricchire la risposta V1
                self._final_payload = event
                # Il done V1 viene emesso dall'endpoint, non qui
                return {"pct": 100, "msg": "Completato"}

            # heartbeat, llm.token: nessun corrispondente V1
            return None

        except Exception as e:
            print(f"[V2 LEGACY ADAPTER] errore traduzione {event_type}: {e}")
            return None

    @property
    def final_payload(self) -> Optional[Dict[str, Any]]:
        return self._final_payload
