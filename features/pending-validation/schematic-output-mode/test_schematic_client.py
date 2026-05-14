"""
Test schematic_client_v2 — modalita' prosa schematica telegrafica.

Test smoke: import, prompt loaded, structure functions, builder reminder.
Test deeper richiede credenziali Azure ed e' E2E nel worktree (Step D).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Bootstrap path: il client vive nella stessa cartella di questo test
_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR))

from schematic_client_v2 import (  # noqa: E402
    _build_schematic_user_prompt,
    _load_schematic_prompt,
    _SCHEMATIC_PROMPT_PATH,
    analyze_batch_schematic,
    analyze_batch_schematic_gemini,
)


# ──────────────────────────────────────────────────────────────────────────────
# Prompt loading
# ──────────────────────────────────────────────────────────────────────────────

def test_prompt_file_exists():
    """Il file prompt MD deve esistere nella stessa cartella."""
    assert _SCHEMATIC_PROMPT_PATH.exists(), (
        f"Prompt non trovato: {_SCHEMATIC_PROMPT_PATH}"
    )


def test_load_schematic_prompt_returns_content():
    prompt = _load_schematic_prompt()
    assert prompt
    assert len(prompt) > 1000  # prompt deve essere sostanzioso


def test_load_schematic_prompt_contains_r0_r4_rules():
    """Verifica che il prompt contenga le regole R0-R4 specificate dal cliente."""
    prompt = _load_schematic_prompt()
    assert "R0" in prompt or "Tipologia:" in prompt  # R0 = inizia con Tipologia
    assert "R1" in prompt or "Soggetto-Verbo-Oggetto" in prompt or "S-V-O" in prompt
    assert "R2" in prompt or "Etichetta: Valore" in prompt
    assert "R3" in prompt or "ESATTAMENTE" in prompt or "esatt" in prompt.lower()
    assert "R4" in prompt or "Elenchi piatti" in prompt or "trattino" in prompt.lower()


def test_prompt_contains_18_macroaree_or_categories():
    """Le 18 macroaree (o 9 della narrative v2) devono essere presenti."""
    prompt = _load_schematic_prompt()
    assert "MACROAREE" in prompt or "CATEGORIE" in prompt or "categoria" in prompt


def test_prompt_contains_json_format():
    """Output strutturato JSON con i 5 campi standard."""
    prompt = _load_schematic_prompt()
    for field in ["numero", "categoria", "sottotitolo", "contenuto", "ente_auditato"]:
        assert field in prompt, f"Campo JSON '{field}' mancante nel prompt"


def test_prompt_contains_examples():
    """Esempi prima/dopo per addestrare il modello."""
    prompt = _load_schematic_prompt()
    assert "Esempio" in prompt or "ESEMPI" in prompt
    # Almeno un esempio key:value visibile
    assert "Denominazione:" in prompt or "Tipologia:" in prompt


def test_prompt_privacy_rules_inherited():
    """Le regole di privacy (no CF/PIVA/IBAN) devono essere mantenute."""
    prompt = _load_schematic_prompt()
    assert "Codice Fiscale" in prompt or "codice fiscale" in prompt.lower()
    assert "Partita IVA" in prompt or "P.IVA" in prompt or "p.iva" in prompt.lower()


def test_prompt_regola_111_inherited():
    """REGOLA 1:1:1 (N documenti = N output) deve essere mantenuta."""
    prompt = _load_schematic_prompt()
    assert "1:1:1" in prompt or "VIETATO AGGREGARE" in prompt or "vietato aggregare" in prompt.lower()


# ──────────────────────────────────────────────────────────────────────────────
# User prompt builder
# ──────────────────────────────────────────────────────────────────────────────

def test_build_schematic_user_prompt_basic():
    """Prompt utente deve includere reminder schematic + documenti."""
    batch_docs = [
        {"filename": "visura.pdf", "content": "Esempio testo visura camerale"},
        {"filename": "fattura.pdf", "content": "Fattura n. 42"},
    ]
    user_prompt = _build_schematic_user_prompt(
        batch_docs=batch_docs,
        batch_idx=0,
        total_docs=2,
        para_start=1,
        verb="Verificato",
        doc_cap_multiplier=2.5,
    )
    assert "BATCH 1-2" in user_prompt
    assert "Schede da generare: 2" in user_prompt
    assert "Tipologia:" in user_prompt
    assert "Etichetta: Valore" in user_prompt
    assert "Key-Value" in user_prompt
    assert "DOCUMENTO 1" in user_prompt
    assert "DOCUMENTO 2" in user_prompt
    assert "visura.pdf" in user_prompt
    assert "fattura.pdf" in user_prompt


def test_build_schematic_user_prompt_target_length():
    """Reminder deve indicare target lunghezza schematic (<400 parole)."""
    user_prompt = _build_schematic_user_prompt(
        batch_docs=[{"filename": "x.pdf", "content": "x"}],
        batch_idx=0,
        total_docs=1,
        para_start=1,
        verb="V",
        doc_cap_multiplier=1.0,
    )
    assert "400 parole" in user_prompt or "<400" in user_prompt


def test_build_schematic_user_prompt_privacy_reminder():
    user_prompt = _build_schematic_user_prompt(
        batch_docs=[{"filename": "x.pdf", "content": "x"}],
        batch_idx=0,
        total_docs=1,
        para_start=1,
        verb="V",
        doc_cap_multiplier=1.0,
    )
    assert "codice fiscale" in user_prompt.lower()
    assert "IBAN" in user_prompt or "iban" in user_prompt.lower()


# ──────────────────────────────────────────────────────────────────────────────
# analyze_batch_schematic — smoke con SDK mockato
# ──────────────────────────────────────────────────────────────────────────────

def test_analyze_batch_schematic_empty_batch():
    """Batch vuoto ritorna lista vuota e no fallback."""
    fake_client = MagicMock()
    schede, fb = analyze_batch_schematic(
        client=fake_client,
        batch_docs=[],
        batch_idx=0,
        total_docs=0,
        para_start=1,
        verb_idx=0,
        narrative_prompt="prompt mock",
    )
    assert schede == []
    assert fb is False


def test_analyze_batch_schematic_signature_matches_narrative():
    """
    Per drop-in compat con pipeline.py, la firma di analyze_batch_schematic
    deve corrispondere esattamente a analyze_batch_narrative.
    """
    import inspect

    # Forza l'import da webapp/v2/ (path gia' settato dal client)
    from v2.narrative_client_v2 import analyze_batch_narrative

    sig_n = inspect.signature(analyze_batch_narrative)
    sig_s = inspect.signature(analyze_batch_schematic)
    assert list(sig_n.parameters.keys()) == list(sig_s.parameters.keys()), (
        f"Firma schematic deve matchare narrative. "
        f"Narrative: {list(sig_n.parameters.keys())}, "
        f"Schematic: {list(sig_s.parameters.keys())}"
    )


def test_analyze_batch_schematic_gemini_signature_matches():
    """Anche la variante Gemini deve avere firma compatibile."""
    import inspect

    from v2.narrative_client_v2 import analyze_batch_narrative_gemini

    sig_n = inspect.signature(analyze_batch_narrative_gemini)
    sig_s = inspect.signature(analyze_batch_schematic_gemini)
    assert list(sig_n.parameters.keys()) == list(sig_s.parameters.keys())
