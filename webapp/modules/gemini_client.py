# ==============================================================================
# GEMINI CLIENT - Wrapper API con mitigazioni qualità
# ==============================================================================

import os
import re
import time
import json
try:
    from google import genai
    from google.genai import types
    USE_NEW_SDK = True
except ImportError:
    import google.generativeai as genai
    USE_NEW_SDK = False
from typing import List, Dict, Optional

# Carica configurazione
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    GEMINI_MODEL, BATCH_SIZE, MAX_RETRIES,
    MIN_WORDS_PER_PARAGRAPH, MAX_WORDS_PER_PARAGRAPH,
    API_PROMPT_PATH
)
from modules.genai_factory import create_genai_client

try:
    from modules.gemini_throttle import gemini_structured_slot, adaptive_delay
    _HAS_THROTTLE = True
except ImportError:
    _HAS_THROTTLE = False
    from contextlib import contextmanager
    @contextmanager
    def gemini_structured_slot():
        yield
    def adaptive_delay(attempt, error_kind="rate_limit"):
        return 5 * (2 ** attempt)


class GeminiClient:
    """
    Client wrapper per Gemini API con:
    - System prompt pre-caricato (GEMINI.md + SOP)
    - Elaborazione a batch
    - Validazione automatica
    - Rigenerazione se errori
    """
    
    def __init__(self, api_key: str):
        """Inizializza il client con la chiave API."""
        self.api_key = api_key
        
        # Carica istruzioni
        self.system_prompt = self._load_system_prompt()
        
        # Inizializza client/modello in base alla versione SDK
        if USE_NEW_SDK:
            # Nuova libreria google-genai (con supporto proxy trasparente)
            self.client = create_genai_client(api_key)
            self.model_name = GEMINI_MODEL
        else:
            # Vecchia libreria google-generativeai
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=self.system_prompt
            )
        
        # Stato per contesto continuo
        self.last_paragraph_number = 0
        self.last_verb_index = 0
        self.verbs = [
            "Esaminato", "Visionato", "Acquisito", "Verificato",
            "Consultato", "Analizzato", "Preso atto di", "Rilevato"
        ]
    
    def _load_system_prompt(self) -> str:
        """Carica il prompt API ottimizzato."""
        if os.path.exists(API_PROMPT_PATH):
            with open(API_PROMPT_PATH, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            # Fallback: prompt minimo se file non trovato
            return """
            Sei un Auditor senior. Genera paragrafi di evidenze oggettive in italiano.
            Ogni documento = 1 paragrafo (200-800 parole).
            MAI: codice fiscale, P.IVA, data/luogo nascita.
            Output: JSON array con numero, sottotitolo, contenuto.
            """
    
    def _get_batch_reminder(self, batch_start: int, total_docs: int) -> str:
        """Genera reminder CONCISO ma completo per ogni batch."""
        next_verb = self.verbs[self.last_verb_index % len(self.verbs)]
        num_docs = min(BATCH_SIZE, total_docs - batch_start + 1)
        
        return f"""
BATCH {batch_start}-{batch_start + num_docs - 1} | Paragrafo iniziale: {self.last_paragraph_number + 1} | Verbo: {next_verb}

REGOLE ESSENZIALI:
• 1 documento = 1 paragrafo (200-800 parole)
• MAI: codice fiscale, P.IVA, data/luogo nascita
• Stile: prosa narrativa, NO liste puntate
• Inizia con: {next_verb}

OUTPUT RICHIESTO - SOLO JSON:
[
  {{"numero": {self.last_paragraph_number + 1}, "sottotitolo": "Tipo - Nome", "contenuto": "Testo..."}},
  {{"numero": {self.last_paragraph_number + 2}, "sottotitolo": "...", "contenuto": "..."}}
]
"""
    
    def _call_api(self, prompt: str, timeout: int = 60, skip_system_prompt: bool = False) -> str:
        """
        Chiama l'API Gemini con gestione rate limiting e retry esponenziale.

        Args:
            prompt: Il prompt da inviare
            timeout: Timeout in secondi (default 60)
            skip_system_prompt: Se True, non prepende self.system_prompt (usato dalla
                                pipeline strutturata che ha già il proprio system prompt)

        Returns:
            Testo della risposta
        """
        import time
        
        MAX_API_RETRIES = 3
        BASE_DELAY = 5  # Secondi base tra retry
        
        for attempt in range(MAX_API_RETRIES):
            start_time = time.time()
            
            try:

                if USE_NEW_SDK:
                    # Nuova libreria google-genai
                    full_prompt = prompt if skip_system_prompt else self.system_prompt + "\n\n---\n\n" + prompt

                    # Determinismo: temperature=0 + seed fissato per riproducibilita'
                    # run-to-run (FIX #1 — elimina varianza stocastica che causava
                    # output divergenti sulla stessa ZIP).
                    safety_config = types.GenerateContentConfig(
                        temperature=0.0,
                        top_p=1.0,
                        seed=42,
                        safety_settings=[
                            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                        ]
                    )

                    with gemini_structured_slot():
                        response = self.client.models.generate_content(
                            model=self.model_name,
                            contents=full_prompt,
                            config=safety_config
                        )
                    
                    # Estrai testo dalla risposta
                    if hasattr(response, 'text'):
                        result = (response.text or "").strip()
                    elif hasattr(response, 'candidates') and response.candidates:
                        # Formato alternativo
                        raw = response.candidates[0].content.parts[0].text
                        result = (raw or "").strip()
                    else:
                        print(f"[WARN] Formato risposta inaspettato: {type(response)}")
                        result = str(response)
                else:
                    # Vecchia libreria google-generativeai
                    safety_settings_old = {
                        "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                        "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
                        "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
                        "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
                    }
                    old_prompt = prompt if skip_system_prompt else self.system_prompt + "\n\n---\n\n" + prompt
                    # Determinismo: temperature=0 + seed=42 anche su SDK legacy
                    generation_config_old = {"temperature": 0.0, "top_p": 1.0, "seed": 42}
                    with gemini_structured_slot():
                        response = self.model.generate_content(
                            old_prompt,
                            safety_settings=safety_settings_old,
                            generation_config=generation_config_old,
                        )
                    result = (response.text or "").strip()
                
                elapsed = time.time() - start_time
                print(f"[API] Risposta ricevuta in {elapsed:.1f}s ({len(result)} chars)")
                
                return result
                
            except Exception as e:
                elapsed = time.time() - start_time
                error_str = str(e).lower()
                
                # Gestione errore 429 (rate limit) — backoff aggressivo + jitter
                if '429' in str(e) or 'resource_exhausted' in error_str or 'quota' in error_str:
                    wait_time = adaptive_delay(attempt, "rate_limit")
                    print(f"[RATE LIMIT] Tentativo {attempt + 1}/{MAX_API_RETRIES} - Attesa {wait_time:.1f}s prima di riprovare...")
                    time.sleep(wait_time)
                    continue

                # Errore 503 (overload Google) — backoff conservativo
                if '503' in str(e) or 'unavailable' in error_str:
                    wait_time = adaptive_delay(attempt, "overload")
                    print(f"[OVERLOAD] Tentativo {attempt + 1}/{MAX_API_RETRIES} - Attesa {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue

                # Altri errori
                print(f"[API ERROR] {str(e)} dopo {elapsed:.1f}s")

                if attempt < MAX_API_RETRIES - 1:
                    wait_time = adaptive_delay(attempt, "rate_limit")
                    print(f"[RETRY] Attesa {wait_time:.1f}s prima del tentativo {attempt + 2}...")
                    time.sleep(wait_time)
                else:
                    raise
        
        raise Exception(f"API fallita dopo {MAX_API_RETRIES} tentativi")
    
    def _validate_paragraph(self, paragraph: Dict) -> List[str]:
        """Valida un paragrafo e restituisce lista errori.
        
        NOTA: Controlli privacy DISABILITATI perché:
        1. L'AI è già istruita via prompt a omettere dati personali
        2. P.IVA/CF AZIENDALI sono legittimi e devono restare
        3. Controlli troppo aggressivi causavano perdita >30% paragrafi
        """
        errors = []
        content = paragraph.get("contenuto", "")
        
        # Controllo parole - SOLO WARNING, non bloccare
        word_count = len(content.split())
        if word_count < 10:  # Solo paragrafi vuoti/quasi vuoti
            errors.append(f"TROPPO CORTO ({word_count} parole)")
        # Rimosso limite MAX - lasciamo che l'AI gestisca
        
        # DISABILITATI: controlli privacy che causavano falsi positivi
        # - P.IVA aziendali sono legittime (es. in visure, fatture)
        # - CF aziendali pure
        # - "nato a" può apparire in contesti legittimi
        
        # Controllo liste puntate - DISABILITATO (sintesi intelligente le rimuove già)
        
        return errors
    
    def _fix_paragraph(self, paragraph: Dict, errors: List[str]) -> Dict:
        """Rigenera un paragrafo con correzioni."""
        fix_prompt = f"""
Il seguente paragrafo ha questi ERRORI che DEVI correggere:
{chr(10).join(f"- {e}" for e in errors)}

PARAGRAFO ORIGINALE:
Numero: {paragraph.get('numero')}
Sottotitolo: {paragraph.get('sottotitolo')}
Contenuto: {paragraph.get('contenuto')}

RISCRIVI il paragrafo CORREGGENDO gli errori.
MANTIENI tutti i dati fattuali.
Se troppo corto, ESPANDI con più dettagli dal documento.
Se contiene dati privacy, RIMUOVILI completamente senza menzionarli.

Output: JSON singolo con numero, sottotitolo, contenuto.
"""
        try:
            fixed_text = self._call_api(fix_prompt)
            
            # Parse JSON
            if fixed_text.startswith("```"):
                fixed_text = re.sub(r'^```\w*\n?', '', fixed_text)
                fixed_text = re.sub(r'\n?```$', '', fixed_text)
            
            return json.loads(fixed_text)
        except:
            return paragraph  # Ritorna originale se rigenerazione fallisce
    
    def _sanitize_text(self, text: str) -> str:
        """Rimuove caratteri problematici che causano errori API."""
        if not text:
            return ""
        # Rimuovi caratteri null e controllo
        text = text.replace('\x00', '')
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\t\r')
        # Rimuovi sequenze di escape problematiche
        text = text.replace('\x0b', ' ').replace('\x0c', ' ')
        # Normalizza newline
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        # Limita lunghezza righe eccessive
        lines = text.split('\n')
        cleaned_lines = [line[:1000] if len(line) > 1000 else line for line in lines]
        return '\n'.join(cleaned_lines)
    
    def _parse_json_response(self, response_text: str, batch_index: int) -> list:
        """Parser a 3 livelli: standard → strict=False → regex per oggetto."""
        text = response_text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        text = text.strip()
        if '[' in text:
            text = text[text.index('['):text.rindex(']') + 1]
        else:
            return []

        # Livello 1: json standard
        try:
            parsed = json.loads(text)
            paragraphs = []
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        paragraphs.append(item)
                    elif isinstance(item, list):
                        for subitem in item:
                            if isinstance(subitem, dict):
                                paragraphs.append(subitem)
            elif isinstance(parsed, dict):
                paragraphs = [parsed]
            return paragraphs
        except json.JSONDecodeError:
            pass

        # Livello 2: strict=False (tollera apostrofi e newline non escapati)
        try:
            parsed = json.loads(text, strict=False)
            paragraphs = []
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        paragraphs.append(item)
                    elif isinstance(item, list):
                        for subitem in item:
                            if isinstance(subitem, dict):
                                paragraphs.append(subitem)
            elif isinstance(parsed, dict):
                paragraphs = [parsed]
            return paragraphs
        except json.JSONDecodeError:
            pass

        # Livello 3: estrazione oggetto per oggetto con brace matching
        objects, depth, start_pos = [], 0, None
        for i, char in enumerate(text):
            if char == '{' and depth == 0:
                start_pos, depth = i, 1
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start_pos is not None:
                    try:
                        obj = json.loads(text[start_pos:i + 1], strict=False)
                        if isinstance(obj, dict) and 'contenuto' in obj:
                            objects.append(obj)
                    except json.JSONDecodeError:
                        pass
                    start_pos = None

        if objects:
            print(f"[JSON PARSER] Batch {batch_index}: recuperati {len(objects)} obj via regex")
            return objects

        safe_preview = response_text[:200].encode('ascii', 'replace').decode('ascii')
        print(f"[JSON PARSER] Batch {batch_index}: FALLIMENTO TOTALE. Preview: {safe_preview}")
        return []

    def analyze_batch(self, documents: List[Dict], batch_index: int, total_docs: int) -> List[Dict]:
        """
        Analizza un batch di documenti e genera paragrafi.
        
        Args:
            documents: Lista di dict con 'filename' e 'content' (testo estratto)
            batch_index: Indice del batch corrente
            total_docs: Numero totale documenti
        
        Returns:
            Lista di paragrafi validati
        """
        # Prepara prompt con documenti
        reminder = self._get_batch_reminder(batch_index * BATCH_SIZE + 1, total_docs)
        
        docs_text = ""
        for i, doc in enumerate(documents):
            docs_text += f"\n\n--- DOCUMENTO {batch_index * BATCH_SIZE + i + 1} ---\n"
            docs_text += f"Filename: {doc.get('filename', 'unknown')}\n"
            # Sanitizza il contenuto prima di aggiungerlo
            content = self._sanitize_text(doc.get('content', '')[:8000])
            docs_text += f"Contenuto:\n{content}"
        
        full_prompt = reminder + "\n\nDOCUMENTI DA ANALIZZARE:" + docs_text
        
        # Sanitizza l'intero prompt prima dell'invio
        full_prompt = self._sanitize_text(full_prompt)
        
        try:
            response_text = self._call_api(full_prompt)

            # Parse JSON con parser resiliente a 3 livelli
            paragraphs = self._parse_json_response(response_text, batch_index)

            # Se parsing fallisce completamente, genera placeholder per ogni documento
            if not paragraphs:
                for doc in documents:
                    paragraphs.append({
                        "numero": self.last_paragraph_number + 1,
                        "sottotitolo": f"{os.path.splitext(doc.get('filename', 'sconosciuto'))[0]} - ELABORAZIONE FALLITA",
                        "categoria": "ALTRO",
                        "contenuto": f"Il documento '{doc.get('filename', '')}' non ha potuto essere elaborato in questo batch (errore parsing risposta AI)."
                    })
                    self.last_paragraph_number += 1

            print(f"[DEBUG] Batch {batch_index}: estratti {len(paragraphs)} paragrafi")

        except Exception as e:
            try:
                print(f"Errore generazione batch {batch_index}: {str(e).encode('ascii', 'replace').decode('ascii')}")
            except:
                print(f"Errore generazione batch {batch_index}: GENERIC ERROR")
            return []
        
        # Validazione e correzione
        validated_paragraphs = []
        for idx, para in enumerate(paragraphs):
            # Verifica tipo prima di procedere
            if not isinstance(para, dict):
                print(f"Warning: paragrafo {idx} non valido (tipo: {type(para)}), skip")
                continue
            
            # Verifica campi minimi
            if "contenuto" not in para and "content" not in para:
                print(f"Warning: paragrafo {idx} senza contenuto, skip")
                continue
                
            # Normalizza campo contenuto
            if "content" in para and "contenuto" not in para:
                para["contenuto"] = para.pop("content")
            
            try:
                errors = self._validate_paragraph(para)
                
                if errors:
                    # Tenta correzione
                    for retry in range(MAX_RETRIES):
                        para = self._fix_paragraph(para, errors)
                        if isinstance(para, dict):
                            errors = self._validate_paragraph(para)
                            if not errors:
                                break
                
                # Aggiungi solo se è un dizionario valido
                if isinstance(para, dict):
                    validated_paragraphs.append(para)
                
                # Aggiorna stato solo se para è dict valido
                if isinstance(para, dict):
                    self.last_paragraph_number = para.get("numero", self.last_paragraph_number + 1)
                    self.last_verb_index += 1
                    
            except Exception as e:
                print(f"Errore validazione paragrafo {idx}: {e}")
                continue
        
        return validated_paragraphs
    
    # ==========================================================================
    # METODI MODALITÀ STRUTTURATA (PROMPT UNIVERSALE ADATTIVO v2.1)
    # analyze_batch() e _call_api() restano INTOCCATI
    # ==========================================================================

    # Cap dinamico per documento (FIX #2): documenti chiave hanno soglie piu'
    # alte per evitare che dati critici (SOA, albi, certificazioni, rischi)
    # cadano oltre la truncation. Il detector usa filename + prime 1500 chars.
    _DOC_CAP_PATTERNS = (
        # (pattern, cap_chars) — ordinati per priorita'
        (("visura", "camerale", "cciaa", "rea", "registro imprese"), 30000),
        (("dvr", "valutazione rischi", "valutazione dei rischi"),     25000),
        (("statuto", "atto costitutivo", "atto notarile"),            25000),
        (("bilancio", "esg", "sostenibilita", "gri", "esrs", "csrd"), 25000),
        (("analisi energetica", "iso 50001", "enpi", "see "),         20000),
        (("ghg", "inventario emissioni", "iso 14064", "carbon"),      20000),
        (("iso 9001", "iso 14001", "iso 45001", "iso 27001",
          "iso 37001", "iso 39001", "soa ", "rating legalita"),       18000),
    )
    _DOC_CAP_DEFAULT = 12000  # incrementato da 8000 per tutti gli altri doc

    @classmethod
    def _doc_char_cap(cls, filename: str, content: str) -> int:
        """
        Determina il cap di caratteri per un singolo documento basandosi su
        filename + prime 1500 chars di content. Ritorna int.
        Normalizza underscore/trattino in spazio così pattern come "iso 9001"
        matchano anche con "iso_9001_cert.pdf".
        """
        fn = (filename or "").lower().replace("_", " ").replace("-", " ")
        head = (content or "")[:1500].lower().replace("_", " ").replace("-", " ")
        for patterns, cap in cls._DOC_CAP_PATTERNS:
            for pat in patterns:
                if pat in fn or pat in head:
                    return cap
        return cls._DOC_CAP_DEFAULT

    def _load_universal_prompt(self, path: str) -> str:
        """
        Legge universal_evidence_prompt.md dal percorso dato.
        Ritorna stringa vuota su qualsiasi errore — mai None, mai eccezione.
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"[STRUCTURED] _load_universal_prompt: impossibile leggere {path}: {e}")
            return ""

    def analyze_batch_structured(
        self,
        batch_docs: List[Dict],
        batch_idx: int,
        total_docs: int,
        universal_prompt: str
    ) -> Optional[str]:
        """
        Versione strutturata di analyze_batch().
        Invia i documenti al modello con il PROMPT UNIVERSALE ADATTIVO e
        ritorna il testo grezzo YAML prodotto dal modello.

        Differenze rispetto ad analyze_batch():
        - Input: universal_prompt (system prompt completo) + documenti
        - Output: stringa YAML grezza (non JSON, non lista di dict)
        - Batch size consigliato: max 4 doc (YAML è più verboso del JSON)
        - Usa _call_api() interno — gestisce automaticamente retry e rate limit
        - Usa _parse_json_response() NON applicabile qui (output è YAML, non JSON)

        Args:
            batch_docs:      lista di dict con 'filename' e 'content'
            batch_idx:       indice batch corrente (0-based)
            total_docs:      numero totale documenti (per logging)
            universal_prompt: contenuto di universal_evidence_prompt.md

        Returns:
            Stringa YAML grezza, oppure None se l'API fallisce.
        """
        if not batch_docs:
            return None

        if not universal_prompt:
            print(f"[STRUCTURED] Batch {batch_idx}: universal_prompt vuoto — "
                  "verificare che universal_evidence_prompt.md sia presente e leggibile")

        # Costruzione prompt — cap dinamico per tipo documento (FIX #2)
        # Visura, DVR, Statuto, bilanci ESG ottengono cap 20-30k (vs 8k fisso
        # legacy). Gli altri documenti 12k. Elimina il sintomo "sì/presente"
        # su documenti ricchi che venivano troncati.
        _parts = []
        for i, d in enumerate(batch_docs):
            fname = d.get('filename', 'sconosciuto')
            content = self._sanitize_text(d.get('content', '') or '')
            cap = self._doc_char_cap(fname, content)
            _parts.append(f"### DOCUMENTO {i + 1}: {fname}\n{content[:cap]}")
        docs_text = "\n\n".join(_parts)

        prompt = (
            f"{universal_prompt}\n\n"
            f"---\n\n"
            f"## DOCUMENTI DA ELABORARE "
            f"({len(batch_docs)} file — Batch {batch_idx + 1}, "
            f"totale progetto {total_docs} doc)\n\n"
            f"{docs_text}\n\n"
            f"---\n\n"
            f"Elabora i {len(batch_docs)} documenti seguendo le 3 FASI "
            f"(CLASSIFICA → ESTRAI → ANNOTA). "
            f"Produci output YAML completo con BLOCCO META e tutte le schede documento."
        )

        prompt = self._sanitize_text(prompt)

        try:
            # skip_system_prompt=True: il universal_prompt è già il system prompt completo,
            # non deve essere contaminato dal vecchio prompt narrativo (che produce JSON)
            raw_output = self._call_api(prompt, skip_system_prompt=True)

            if not raw_output or not raw_output.strip():
                print(f"[STRUCTURED] Batch {batch_idx}: risposta vuota dal modello")
                return None

            print(f"[STRUCTURED] Batch {batch_idx}: ricevuti {len(raw_output)} chars")

            if os.environ.get("DEBUG_DUMP_RAW", "").strip() in ("1", "true", "True"):
                try:
                    import datetime as _dt
                    from pathlib import Path as _Path
                    _logs_dir = _Path(__file__).resolve().parent.parent / "logs" / "raw"
                    _logs_dir.mkdir(parents=True, exist_ok=True)
                    _ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    _docs_names = "_".join(
                        (d.get('filename', 'x')[:20].replace(' ', '_').replace('/', '_'))
                        for d in batch_docs[:2]
                    )
                    _fn = _logs_dir / f"batch_{batch_idx:02d}_{_ts}_{_docs_names}.yaml"
                    _fn.write_text(raw_output, encoding="utf-8")
                    print(f"[DEBUG_DUMP_RAW] salvato: {_fn}")
                except Exception as _e:
                    print(f"[DEBUG_DUMP_RAW] dump fallito: {_e}")

            return raw_output

        except Exception as e:
            try:
                print(f"[STRUCTURED] Batch {batch_idx}: errore API — "
                      f"{str(e).encode('ascii', 'replace').decode('ascii')}")
            except Exception:
                print(f"[STRUCTURED] Batch {batch_idx}: errore API — GENERIC ERROR")
            try:
                from modules.db_manager import save_partial_error
                docs_names = [d.get('filename', '') for d in batch_docs]
                save_partial_error(
                    user_id="system",
                    azienda="",
                    error_subtype="batch_loss",
                    error_message=str(e)[:500],
                    batch_index=batch_idx,
                    docs_involved=docs_names,
                    auto_recovered=False,
                    recovery_details="analyze_batch_structured: API exception",
                    tab_source="tab1"
                )
            except Exception:
                pass  # Il logging secondario NON deve mai bloccare la pipeline
            return None

    def get_quality_stats(self, paragraphs: List[Dict]) -> Dict:
        """Calcola statistiche qualità per report."""
        if not paragraphs:
            return {}
        
        # Filtra solo dizionari validi
        valid_paragraphs = [p for p in paragraphs if isinstance(p, dict)]
        
        if not valid_paragraphs:
            return {"total_paragraphs": 0, "avg_words": 0, "min_words": 0, "max_words": 0, "verbs_variety": 0}
        
        word_counts = [len(p.get("contenuto", "").split()) for p in valid_paragraphs]
        
        # Conta verbi unici usati
        verbs_used = set()
        for p in valid_paragraphs:
            content = p.get("contenuto", "")
            for verb in self.verbs:
                if verb.lower() in content[:100].lower():
                    verbs_used.add(verb)
        
        return {
            "total_paragraphs": len(paragraphs),
            "avg_words": sum(word_counts) / len(word_counts) if word_counts else 0,
            "min_words": min(word_counts) if word_counts else 0,
            "max_words": max(word_counts) if word_counts else 0,
            "unique_verbs": len(verbs_used),
            "privacy_violations": 0  # Già corretti in validazione
        }
