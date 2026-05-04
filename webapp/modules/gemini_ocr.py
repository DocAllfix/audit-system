# ==============================================================================
# GEMINI OCR - Estrazione testo da immagini usando Gemini Vision
# ==============================================================================
# Alternativa a Tesseract per PDF scansionati
# Usa le capacità multimodali di Gemini per leggere testo dalle immagini
# ==============================================================================

import os
import sys
import base64
import time
from typing import Optional, List, Tuple
import io

# Aggiungi percorsi
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import fitz  # PyMuPDF - più veloce di pdf2image e non richiede Poppler
    HAS_PYMUPDF = True
    try:
        fitz.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass
except ImportError:
    HAS_PYMUPDF = False

try:
    import google.genai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

try:
    from modules.genai_factory import create_genai_client
    HAS_FACTORY = True
except ImportError:
    HAS_FACTORY = False

try:
    from modules.gemini_throttle import gemini_ocr_slot, adaptive_delay
    HAS_THROTTLE = True
except ImportError:
    HAS_THROTTLE = False
    from contextlib import contextmanager
    @contextmanager
    def gemini_ocr_slot():
        yield
    def adaptive_delay(attempt, error_kind="rate_limit"):
        return [5, 15, 30][min(attempt, 2)]


class GeminiOCR:
    """
    Usa Gemini Vision per estrarre testo da immagini/PDF scansionati.
    Non richiede Tesseract o Poppler.
    """
    
    def __init__(self, api_key: str = None):
        """Inizializza con API key opzionale (può essere passata dopo)."""
        self.api_key = api_key
        self.client = None
        self.model_name = "gemini-2.5-flash"  # Primario: più preciso
        self.fallback_model = "gemini-2.5-flash-lite"  # Fallback: leggero e supportato
        self.max_retries = 3  # Retry sul modello primario prima del fallback
        self.retry_delays = [5, 15, 30]  # Backoff esponenziale in secondi
        
        if api_key and HAS_GENAI:
            self.client = create_genai_client(api_key) if HAS_FACTORY else genai.Client(api_key=api_key)

    def set_api_key(self, api_key: str):
        """Imposta API key se non fornita al costruttore."""
        self.api_key = api_key
        if HAS_GENAI:
            self.client = create_genai_client(api_key) if HAS_FACTORY else genai.Client(api_key=api_key)
    
    def pdf_to_images(self, pdf_path: str, max_pages: int = 12, dpi: int = 100, fast_mode: bool = False) -> List[bytes]:
        """
        Converte PDF in immagini PNG usando PyMuPDF (no Poppler needed).
        Con gestione errori robusta per PDF corrotti.
        
        Args:
            pdf_path: Percorso al file PDF
            max_pages: Massimo numero pagine da convertire (ridotto per velocità)
            dpi: Risoluzione (100 è sufficiente per OCR ed è più veloce)
            fast_mode: Se True, riduce drasticamente qualità e pagine per velocità (fallback)
        
        Returns:
            Lista di immagini come bytes PNG
        """
        if not HAS_PYMUPDF:
            return []
        
        images = []
        doc = None
        page_errors = 0
        MAX_PAGE_ERRORS = 3  # Se troppe pagine falliscono, considera il PDF corrotto
        
        # In fast_mode, limitiamo le pagine a 3 max, a prescindere dall'input
        if fast_mode:
            max_pages = min(max_pages, 3)
        
        try:
            # Apri il documento con gestione errori
            try:
                doc = fitz.open(pdf_path)
            except Exception as open_err:
                print(f"[OCR] Impossibile aprire PDF {os.path.basename(pdf_path)}: {open_err}")
                return []
            
            num_pages = min(len(doc), max_pages)
            
            for page_num in range(num_pages):
                # Se troppi errori consecutivi, salta il resto del PDF
                if page_errors >= MAX_PAGE_ERRORS:
                    print(f"[OCR] Troppi errori ({page_errors}) su {os.path.basename(pdf_path)}, skip pagine restanti")
                    break
                
                try:
                    page = doc[page_num]
                    
                    # CALCOLO ZOOM OTTIMALE
                    # Target max dimension: 1024 px (velocizza upload e inferenza Vision)
                    rect = page.rect
                    max_dimension = max(rect.width, rect.height)
                    
                    # Default 800px target (sufficiente per OCR, più veloce)
                    # FAST MODE: scende a 600px
                    target_px = 600 if fast_mode else 800
                    
                    zoom = target_px / max_dimension if max_dimension > 0 else 1.0
                    
                    # Clamp zoom: non ingrandire troppo (max 2.0 = 144 DPI) ne ridurre troppo (min 0.5)
                    # FAST MODE: accetta anche 0.4
                    min_zoom = 0.4 if fast_mode else 0.5
                    zoom = max(min_zoom, min(zoom, 2.0))
                    
                    mat = fitz.Matrix(zoom, zoom)
                    
                    # Renderizza con gestione errori
                    try:
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        img_bytes = pix.tobytes("png")
                        images.append(img_bytes)
                        page_errors = 0  # Reset contatore se pagina OK
                    except Exception as render_err:
                        page_errors += 1
                        print(f"[OCR] Errore rendering pagina {page_num + 1}/{num_pages}: {render_err}")
                        continue  # Salta alla prossima pagina
                        
                except Exception as page_err:
                    page_errors += 1
                    print(f"[OCR] Errore accesso pagina {page_num + 1}: {page_err}")
                    continue  # Salta alla prossima pagina
            
        except Exception as e:
            print(f"[OCR] Errore generale conversione PDF {os.path.basename(pdf_path)}: {e}")
        finally:
            # Chiudi sempre il documento
            if doc:
                try:
                    doc.close()
                except:
                    pass
        
        return images
    
    def extract_text_from_image(self, image_bytes: bytes, page_num: int = 1) -> str:
        """
        Estrae testo da un'immagine usando Gemini Vision.
        
        Args:
            image_bytes: Immagine come bytes
            page_num: Numero pagina per logging
        
        Returns:
            Testo estratto
        """
        if not self.client:
            return ""
        
        try:
            # Encode image as base64
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            
            # Prompt per OCR
            prompt = """Estrai TUTTO il testo presente in questa immagine.
Riporta il testo esattamente come appare, mantenendo la struttura del documento.
Se ci sono tabelle, riportale in formato testuale.
NON aggiungere commenti o interpretazioni, solo il testo estratto.
Se non riesci a leggere parti del testo, indica [illeggibile].
"""
            
            # Chiamata API con immagine — throttled
            with gemini_ocr_slot():
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        {
                            "parts": [
                                {"text": prompt},
                                {
                                    "inline_data": {
                                        "mime_type": "image/png",
                                        "data": image_b64
                                    }
                                }
                            ]
                        }
                    ]
                )

            return (getattr(response, 'text', None) or "").strip()

        except Exception as e:
            print(f"Errore OCR Gemini pagina {page_num}: {e}")
            return ""
    
    def extract_text_from_pdf_batch(self, pdf_path: str, max_pages: int = 12, fast_mode: bool = False) -> Tuple[str, str]:
        """
        Estrae testo da PDF inviando TUTTE le pagine in UNA SOLA chiamata API.
        Molto più veloce del metodo pagina per pagina.
        
        Args:
            pdf_path: Percorso al file PDF
            max_pages: Massimo numero pagine da processare
            fast_mode: Se True, usa modalità veloce per fallback
        
        Returns:
            Tuple (testo_estratto, metodo_usato)
        """
        if not self.client:
            return "", "no_api_key"
        
        if not HAS_PYMUPDF:
            return "", "no_pymupdf"
        
        # Converti PDF in immagini
        images = self.pdf_to_images(pdf_path, max_pages, fast_mode=fast_mode)
        
        if not images:
            return "", "conversion_failed"
        
        try:
            # Prepara tutte le immagini per una singola chiamata
            parts = [{"text": f"Estrai il testo da queste {len(images)} pagine di documento. Per ogni pagina, indica '--- PAGINA N ---' seguito dal testo estratto. Mantieni la struttura originale."}]
            
            for i, img_bytes in enumerate(images):
                image_b64 = base64.b64encode(img_bytes).decode('utf-8')
                parts.append({
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": image_b64
                    }
                })
            
            # TENTATIVO 1: Modello primario con retry + backoff (Gemini 2.5 Flash)
            last_primary_err = None
            for attempt in range(self.max_retries):
                try:
                    with gemini_ocr_slot():
                        response = self.client.models.generate_content(
                            model=self.model_name,
                            contents=[{"parts": parts}]
                        )
                    text = response.text.strip() if response.text else ""
                    
                    # Sanity check lunghezza output (evita loop infiniti > 40k chars per batch)
                    if len(text) > 40000 and fast_mode:
                         text = text[:40000] + "\n[OCR TRONCATO PER ECCESSO LUNGHEZZA]"
                    
                    if text and len(text) > 20:
                        mode_suffix = "_fast" if fast_mode else ""
                        if attempt > 0:
                            print(f"[OCR] Gemini 2.5 riuscito al tentativo {attempt + 1}")
                        return text, f"gemini_ocr_batch_2.5{mode_suffix}"
                except Exception as primary_err:
                    last_primary_err = primary_err
                    err_str = str(primary_err)
                    is_overloaded = "503" in err_str or "UNAVAILABLE" in err_str
                    is_rate_limit = "429" in err_str or "Rate" in err_str or "quota" in err_str.lower()

                    if (is_overloaded or is_rate_limit) and attempt < self.max_retries - 1:
                        kind = "overload" if is_overloaded else "rate_limit"
                        delay = adaptive_delay(attempt, kind)
                        print(f"[OCR] Gemini 2.5 tentativo {attempt + 1}/{self.max_retries} fallito ({kind}), retry tra {delay:.1f}s...")
                        time.sleep(delay)
                    elif attempt < self.max_retries - 1:
                        # Errore non-retryable (es. FAILED_PRECONDITION, INVALID_ARGUMENT)
                        print(f"[OCR] Gemini 2.5 fallito (non-retry): {primary_err}, passo a fallback...")
                        break
                    else:
                        print(f"[OCR] Gemini 2.5 fallito dopo {self.max_retries} tentativi: {last_primary_err}, passo a fallback...")
            
            # TENTATIVO 2: Modello fallback (Gemini 2.5 Flash Lite - leggero e supportato)
            try:
                with gemini_ocr_slot():
                    response = self.client.models.generate_content(
                        model=self.fallback_model,
                        contents=[{"parts": parts}]
                    )
                text = response.text.strip() if response.text else ""
                if text and len(text) > 20:
                    print(f"[OCR] Fallback {self.fallback_model} riuscito!")
                    return text, "gemini_ocr_batch_lite_fallback"
            except Exception as fallback_err:
                print(f"[OCR] Anche fallback {self.fallback_model} fallito: {fallback_err}")
            
            # Se entrambi falliscono, prova estrazione sequenziale
            return self._extract_sequential(images)
            
        except Exception as e:
            print(f"Errore OCR batch generale: {e}")
            # Fallback al metodo pagina per pagina
            return self._extract_sequential(images)
    
    def _extract_sequential(self, images: List[bytes]) -> Tuple[str, str]:
        """Fallback: estrazione sequenziale se batch fallisce."""
        text_parts = []
        for i, img_bytes in enumerate(images):
            page_text = self.extract_text_from_image(img_bytes, i + 1)
            if page_text:
                text_parts.append(f"--- PAGINA {i + 1} (GEMINI OCR) ---\n{page_text}")
        
        if not text_parts:
            try:
                from modules.db_manager import save_partial_error
                save_partial_error(
                    user_id="system",
                    azienda="",
                    error_subtype="ocr_none",
                    error_message="OCR sequenziale fallito: nessuna pagina estratta",
                    batch_index=-1,
                    auto_recovered=False,
                    recovery_details="_extract_sequential: tutte le pagine hanno restituito testo vuoto",
                    tab_source="tab1"
                )
            except Exception:
                pass  # Il logging secondario NON deve mai bloccare la pipeline
            return "", "ocr_failed"
        
        return "\n\n".join(text_parts), "gemini_ocr"
    
    def extract_text_from_image_raw(self, image_bytes: bytes, mime_type: str = "image/png") -> Tuple[str, str]:
        """
        Estrae testo da bytes immagine con MIME type arbitrario.
        Usato per formati non-PNG che Gemini supporta come inline data
        (es. image/heic, image/webp, image/jpeg).
        Non richiede conversione — invia i bytes originali direttamente all'API.
        """
        if not self.client:
            return "", "no_api_key"
        try:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            prompt = (
                "Estrai TUTTO il testo presente in questa immagine.\n"
                "Riporta il testo esattamente come appare, mantenendo la struttura del documento.\n"
                "Se ci sono tabelle, riportale in formato testuale.\n"
                "NON aggiungere commenti o interpretazioni, solo il testo estratto.\n"
                "Se non riesci a leggere parti del testo, indica [illeggibile]."
            )
            with gemini_ocr_slot():
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[{
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": mime_type, "data": image_b64}}
                        ]
                    }]
                )
            text = (getattr(response, "text", None) or "").strip()
            fmt = mime_type.split("/")[-1]
            return text, f"gemini_ocr_{fmt}"
        except Exception as e:
            print(f"[OCR] extract_text_from_image_raw ({mime_type}): {e}")
            return "", "error"

    def extract_text_from_pdf(self, pdf_path: str, max_pages: int = 12, fast_mode: bool = False) -> Tuple[str, str]:
        """
        Metodo principale - usa batch OCR per velocità.
        """
        return self.extract_text_from_pdf_batch(pdf_path, max_pages, fast_mode=fast_mode)
    
    def extract_text_from_image_file(self, image_path: str) -> Tuple[str, str]:
        """
        Estrae testo da un file immagine.
        
        Args:
            image_path: Percorso al file immagine
        
        Returns:
            Tuple (testo_estratto, metodo_usato)
        """
        if not self.client:
            return "", "no_api_key"
        
        try:
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            
            text = self.extract_text_from_image(image_bytes)
            
            if text:
                return text, "gemini_ocr"
            else:
                return "", "ocr_failed"
                
        except Exception as e:
            print(f"Errore lettura immagine: {e}")
            return "", "error"


# Funzione helper per uso standalone
def ocr_pdf_with_gemini(pdf_path: str, api_key: str, max_pages: int = 12) -> str:
    """
    Helper function per OCR di un PDF con Gemini.
    
    Args:
        pdf_path: Percorso al PDF
        api_key: Chiave API Gemini
        max_pages: Massimo pagine da processare
    
    Returns:
        Testo estratto
    """
    ocr = GeminiOCR(api_key)
    text, method = ocr.extract_text_from_pdf(pdf_path, max_pages)
    return text


if __name__ == "__main__":
    # Test
    print("=== Test GeminiOCR ===")
    print(f"PIL: {'OK' if HAS_PIL else 'MANCANTE'}")
    print(f"PyMuPDF: {'OK' if HAS_PYMUPDF else 'MANCANTE'}")
    print(f"google-genai: {'OK' if HAS_GENAI else 'MANCANTE'}")
