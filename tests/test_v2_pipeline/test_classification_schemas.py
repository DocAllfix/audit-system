"""
Test V2 Fase 2 — schemi Pydantic per classificazione.

Verifica gli invarianti dichiarati nello schema:
- confidence sempre in [0, 1] anche se il modello ritorna valori fuori range
- classi sconosciute → ALTRO senza eccezione
- extra fields ignorati (tolleranza al modello che aggiunge campi)
- enrich_with_derived_fields popola macroarea e char_cap
"""
from __future__ import annotations

import pytest

from v2.schemas.classification import (
    CLASS_TO_CHAR_CAP,
    CLASS_TO_MACROAREA,
    ClassificationBatchOutput,
    ClassifiedFile,
    DocumentClass,
    LinguaDocumento,
    TipoSoggetto,
    char_cap_for,
    enrich_with_derived_fields,
    macroarea_for,
)


# ──────────────────────────────────────────────────────────────────────────────
# DocumentClass enum
# ──────────────────────────────────────────────────────────────────────────────

def test_all_classes_have_macroarea_mapping():
    """Ogni classe DEVE avere un mapping verso macroarea."""
    for cls in DocumentClass:
        assert cls in CLASS_TO_MACROAREA, f"Classe {cls.value} senza macroarea"


def test_all_classes_have_char_cap():
    """Ogni classe DEVE avere un cap caratteri definito."""
    for cls in DocumentClass:
        assert cls in CLASS_TO_CHAR_CAP, f"Classe {cls.value} senza char_cap"
        assert CLASS_TO_CHAR_CAP[cls] >= 5_000, f"Char cap troppo basso per {cls.value}"


def test_helpers_lookup():
    """macroarea_for e char_cap_for ritornano valori coerenti."""
    assert macroarea_for(DocumentClass.VISURA) == "DOCUMENTAZIONE LEGALE E SOCIETARIA"
    assert char_cap_for(DocumentClass.VISURA) == 30_000
    assert macroarea_for(DocumentClass.ATTESTATO) == "FORMAZIONE E ADDESTRAMENTO"


# ──────────────────────────────────────────────────────────────────────────────
# ClassifiedFile validators
# ──────────────────────────────────────────────────────────────────────────────

def test_confidence_clamp_above():
    """Confidence > 1 viene clampata a 1."""
    cf = ClassifiedFile(filename="x.pdf", classe=DocumentClass.VISURA, confidence=1.5)
    assert cf.confidence == 1.0


def test_confidence_clamp_below():
    """Confidence < 0 viene clampata a 0."""
    cf = ClassifiedFile(filename="x.pdf", classe=DocumentClass.VISURA, confidence=-0.3)
    assert cf.confidence == 0.0


def test_confidence_invalid_string_falls_to_zero():
    """Confidence non parsabile → 0.0, niente eccezione."""
    cf = ClassifiedFile(filename="x.pdf", classe=DocumentClass.VISURA, confidence="garbage")  # type: ignore
    assert cf.confidence == 0.0


def test_unknown_class_falls_to_altro():
    """Classe sconosciuta viene normalizzata a ALTRO."""
    cf = ClassifiedFile(filename="x.pdf", classe="QUESTA_NON_ESISTE", confidence=0.9)  # type: ignore
    # use_enum_values=True → cf.classe è la stringa "ALTRO"
    assert cf.classe == DocumentClass.ALTRO.value


def test_extra_fields_ignored():
    """extra='ignore' permette al modello di aggiungere campi senza rompere."""
    cf = ClassifiedFile(
        filename="x.pdf",
        classe=DocumentClass.DVR,
        confidence=0.9,
        campo_extra_inventato="ignored",  # type: ignore
    )
    assert cf.classe == DocumentClass.DVR.value
    # Il campo extra non è accessibile come attributo
    assert not hasattr(cf, "campo_extra_inventato")


def test_filename_max_length_enforced():
    """Filename oltre 500 chars solleva ValidationError."""
    with pytest.raises(ValueError):
        ClassifiedFile(filename="x" * 600, classe=DocumentClass.ALTRO, confidence=0.5)


def test_signal_markers_optional():
    """tipo_soggetto, lingua, data_doc_estimate sono tutti opzionali."""
    cf = ClassifiedFile(filename="x.pdf", classe=DocumentClass.ALTRO, confidence=0.5)
    assert cf.tipo_soggetto is None
    assert cf.lingua is None
    assert cf.data_doc_estimate is None
    assert cf.pre_ocr is False
    assert cf.needs_double_check is False


def test_signal_markers_set():
    """Signal markers vengono accettati se validi."""
    cf = ClassifiedFile(
        filename="x.pdf",
        classe=DocumentClass.VISURA,
        confidence=0.95,
        tipo_soggetto=TipoSoggetto.AZIENDA,
        lingua=LinguaDocumento.ITALIANO,
        data_doc_estimate="15/03/2025",
    )
    assert cf.tipo_soggetto == TipoSoggetto.AZIENDA.value
    assert cf.lingua == LinguaDocumento.ITALIANO.value
    assert cf.data_doc_estimate == "15/03/2025"


# ──────────────────────────────────────────────────────────────────────────────
# enrich_with_derived_fields
# ──────────────────────────────────────────────────────────────────────────────

def test_enrich_populates_missing_macroarea_and_cap():
    """enrich popola macroarea e char_cap_suggested se mancanti."""
    cf = ClassifiedFile(filename="x.pdf", classe=DocumentClass.VISURA, confidence=0.9)
    enriched = enrich_with_derived_fields(cf)

    assert enriched.macroarea == "DOCUMENTAZIONE LEGALE E SOCIETARIA"
    assert enriched.char_cap_suggested == 30_000
    # Il Pydantic originale non viene mutato (immutabilità funzionale)
    assert cf.macroarea is None


def test_enrich_preserves_existing_macroarea():
    """Se macroarea già presente, enrich non la sovrascrive."""
    cf = ClassifiedFile(
        filename="x.pdf",
        classe=DocumentClass.VISURA,
        confidence=0.9,
        macroarea="MACROAREA CUSTOM",
    )
    enriched = enrich_with_derived_fields(cf)
    assert enriched.macroarea == "MACROAREA CUSTOM"


# ──────────────────────────────────────────────────────────────────────────────
# ClassificationBatchOutput
# ──────────────────────────────────────────────────────────────────────────────

def test_batch_output_default_empty_list():
    """ClassificationBatchOutput senza files → lista vuota."""
    batch = ClassificationBatchOutput()
    assert batch.files == []


def test_batch_output_validates_inner_models():
    """Batch valida ogni ClassifiedFile interno."""
    batch = ClassificationBatchOutput(
        files=[
            {"filename": "a.pdf", "classe": "VISURA", "confidence": 0.9},
            {"filename": "b.pdf", "classe": "DVR", "confidence": 0.85},
            {"filename": "c.pdf", "classe": "INVALID", "confidence": 1.5},  # auto-corrected
        ]
    )
    assert len(batch.files) == 3
    assert batch.files[2].classe == DocumentClass.ALTRO.value
    assert batch.files[2].confidence == 1.0


def test_batch_output_from_json_string():
    """ClassificationBatchOutput.model_validate_json parsa output Gemini."""
    json_str = """{
        "files": [
            {"filename": "visura.pdf", "classe": "VISURA", "confidence": 0.92, "tipo_soggetto": "AZIENDA"}
        ]
    }"""
    batch = ClassificationBatchOutput.model_validate_json(json_str)
    assert len(batch.files) == 1
    assert batch.files[0].classe == DocumentClass.VISURA.value
