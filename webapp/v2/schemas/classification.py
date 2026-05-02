"""
V2 — Schemi Pydantic per classificazione documenti (Fase 2).

Definisce:
- DocumentClass: enum delle 13 classi note + ALTRO
- ClassifiedFile: output del classifier per singolo file
- ClassificationBatchOutput: output per batch (lista di ClassifiedFile)
- Mapping classe → macroarea SOP (per coerenza con il Word finale)
- Mapping classe → cap caratteri suggerito (sostituisce _doc_char_cap V1)

REGOLE INVIOLABILI (verificate dai test):
- `extra="ignore"` su tutti i model: tolleranza a campi extra dal modello
- `confidence` clampato in [0.0, 1.0] tramite validator
- Classi sconosciute vengono normalizzate a ALTRO con warning loggato
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ──────────────────────────────────────────────────────────────────────────────
# 1) CLASSI DOCUMENTO
# ──────────────────────────────────────────────────────────────────────────────

class DocumentClass(str, Enum):
    """Classi documento riconosciute dal classifier V2."""

    VISURA = "VISURA"
    STATUTO = "STATUTO"
    DVR = "DVR"
    POS = "POS"
    BILANCIO = "BILANCIO"
    CCNL = "CCNL"
    ATTESTATO = "ATTESTATO"
    CERTIFICATO_ISO = "CERTIFICATO_ISO"
    CONTRATTO = "CONTRATTO"
    FATTURA = "FATTURA"
    IDENTITA = "IDENTITA"
    SOA = "SOA"  # Attestazione SOA per appalti pubblici
    ALTRO = "ALTRO"


# Set per validazione veloce
_VALID_CLASS_VALUES = {c.value for c in DocumentClass}


# ──────────────────────────────────────────────────────────────────────────────
# 2) MAPPING classe → macroarea SOP (per ordinamento Word finale)
# ──────────────────────────────────────────────────────────────────────────────

CLASS_TO_MACROAREA = {
    DocumentClass.VISURA: "DOCUMENTAZIONE LEGALE E SOCIETARIA",
    DocumentClass.STATUTO: "DOCUMENTAZIONE LEGALE E SOCIETARIA",
    DocumentClass.SOA: "DOCUMENTAZIONE LEGALE E SOCIETARIA",
    DocumentClass.DVR: "SICUREZZA SUL LAVORO",
    DocumentClass.POS: "SICUREZZA SUL LAVORO",
    DocumentClass.ATTESTATO: "FORMAZIONE E ADDESTRAMENTO",
    DocumentClass.IDENTITA: "GESTIONE RISORSE UMANE",
    DocumentClass.CCNL: "GESTIONE RISORSE UMANE",
    DocumentClass.BILANCIO: "REGOLARITÀ CONTRIBUTIVA E FISCALE",
    DocumentClass.FATTURA: "REGOLARITÀ CONTRIBUTIVA E FISCALE",
    DocumentClass.CONTRATTO: "GESTIONE FORNITORI E APPALTI",
    DocumentClass.CERTIFICATO_ISO: "ALTRO",
    DocumentClass.ALTRO: "ALTRO",
}


# ──────────────────────────────────────────────────────────────────────────────
# 3) CAP CARATTERI per classe (sostituisce _doc_char_cap V1)
# ──────────────────────────────────────────────────────────────────────────────

CLASS_TO_CHAR_CAP = {
    DocumentClass.VISURA: 30_000,
    DocumentClass.STATUTO: 25_000,
    DocumentClass.DVR: 25_000,
    DocumentClass.BILANCIO: 25_000,
    DocumentClass.CCNL: 20_000,
    DocumentClass.POS: 20_000,
    DocumentClass.SOA: 18_000,
    DocumentClass.CERTIFICATO_ISO: 18_000,
    DocumentClass.CONTRATTO: 15_000,
    DocumentClass.ATTESTATO: 8_000,
    DocumentClass.FATTURA: 8_000,
    DocumentClass.IDENTITA: 5_000,
    DocumentClass.ALTRO: 12_000,
}


# ──────────────────────────────────────────────────────────────────────────────
# 4) SIGNAL MARKERS — campi facoltativi estratti durante la classificazione
# ──────────────────────────────────────────────────────────────────────────────

class TipoSoggetto(str, Enum):
    """Soggetto principale del documento (utile per privacy filtering)."""

    AZIENDA = "AZIENDA"
    PERSONA_FISICA = "PERSONA_FISICA"
    MISTO = "MISTO"
    NON_DETERMINATO = "NON_DETERMINATO"


class LinguaDocumento(str, Enum):
    """Lingua principale del documento."""

    ITALIANO = "ITALIANO"
    INGLESE = "INGLESE"
    BILINGUE = "BILINGUE"
    ALTRA = "ALTRA"


class AuditRole(str, Enum):
    """
    Ruolo del documento nella catena evidenziale audit (Leva 2 — Fase A).

    Tassonomia ortogonale a `DocumentClass`: la classe dice CHE COS'È, il role
    dice QUANTO PESA come evidenza.

    - CORE: documento la cui analisi atomica è evidenza unica di una clausola
      di norma. Visure, DVR, statuti, SOA, certificati ISO, bilanci ESG,
      mansionari, giudizi medico competente, registri infortuni/NC, contratti
      principali. Mai scartabile, sempre tier ESTESO.
    - AGGREGABLE: documento ricorrente la cui evidenza è collettiva (vale
      "tutti insieme"). Attestati formazione standard, buste paga, UniLav,
      fatture di routine. Si aggrega con tabella riepilogativa + scheda
      compatta per file.
    - SUPPORT: documento di supporto/contesto, non evidenza diretta.
      Questionari autovalutazione, schede fornitore, riepiloghi, ricevute.
      Tier MEDIO con prompt minimal possibile.
    - NOISE: provata duplicazione, file vuoto, comunicazione email banale,
      ricevuta isolata fuori contesto. Candidato allo skip ma SOLO con
      confidence ≥ 0.90 + safety net (whitelist normativa, volume cap).
    """

    CORE = "CORE"
    AGGREGABLE = "AGGREGABLE"
    SUPPORT = "SUPPORT"
    NOISE = "NOISE"


_VALID_AUDIT_ROLE_VALUES = {r.value for r in AuditRole}


# Mapping default classe → audit_role (fallback deterministico se il
# classifier non popola il campo). I valori MAI vengono usati per scartare:
# servono solo per dare un default conservativo.
CLASS_TO_DEFAULT_ROLE = {
    DocumentClass.VISURA: AuditRole.CORE,
    DocumentClass.STATUTO: AuditRole.CORE,
    DocumentClass.DVR: AuditRole.CORE,
    DocumentClass.POS: AuditRole.CORE,
    DocumentClass.BILANCIO: AuditRole.CORE,
    DocumentClass.SOA: AuditRole.CORE,
    DocumentClass.CERTIFICATO_ISO: AuditRole.CORE,
    DocumentClass.CONTRATTO: AuditRole.CORE,
    DocumentClass.CCNL: AuditRole.CORE,
    DocumentClass.ATTESTATO: AuditRole.AGGREGABLE,
    DocumentClass.FATTURA: AuditRole.AGGREGABLE,
    DocumentClass.IDENTITA: AuditRole.SUPPORT,
    DocumentClass.ALTRO: AuditRole.SUPPORT,
}


# ──────────────────────────────────────────────────────────────────────────────
# 5) OUTPUT MODEL — singolo file classificato
# ──────────────────────────────────────────────────────────────────────────────

class ClassifiedFile(BaseModel):
    """
    Output classificazione per un singolo file.

    Campi obbligatori: filename, classe, confidence.
    Tutti gli altri sono signal markers facoltativi: il classifier li popola
    quando può, altrimenti resta None (mai eccezione).
    """

    model_config = ConfigDict(
        extra="ignore",            # Tolleranza a campi extra dal modello
        use_enum_values=True,      # serializza enum come stringhe
        str_strip_whitespace=True, # trim automatico stringhe
    )

    filename: str = Field(..., max_length=500)
    classe: DocumentClass = Field(...)
    confidence: float = Field(..., ge=0.0, le=1.0)
    macroarea: Optional[str] = None
    char_cap_suggested: Optional[int] = None
    tipo_soggetto: Optional[TipoSoggetto] = None
    lingua: Optional[LinguaDocumento] = None
    data_doc_estimate: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Data documento in formato DD/MM/YYYY se rilevabile",
    )
    needs_double_check: bool = Field(
        default=False,
        description="True se confidence < threshold; il caller deve ri-classificare con flash 2.5",
    )
    classifier_model: Optional[str] = Field(
        default=None,
        description="Modello che ha prodotto questa classificazione (lite o flash)",
    )
    pre_ocr: bool = Field(
        default=False,
        description="True se classificato senza testo OCR (solo filename)",
    )
    audit_role: Optional[AuditRole] = Field(
        default=None,
        description=(
            "Ruolo del documento come evidenza audit (CORE/AGGREGABLE/"
            "SUPPORT/NOISE). Se None, viene derivato deterministicamente "
            "dalla classe via CLASS_TO_DEFAULT_ROLE."
        ),
    )
    audit_role_confidence: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description=(
            "Confidenza del classifier sull'audit_role assegnato. Solo "
            "≥ 0.90 abilita lo skip per role=NOISE (Fase B)."
        ),
    )

    @field_validator("audit_role", mode="before")
    @classmethod
    def _normalize_audit_role(cls, v):
        """Mappa role sconosciuti a None (verrà poi derivato dalla classe)."""
        if v is None:
            return None
        if isinstance(v, AuditRole):
            return v
        if isinstance(v, str):
            v_up = v.strip().upper()
            if v_up in _VALID_AUDIT_ROLE_VALUES:
                return v_up
        return None

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v):
        """Clamp confidence in [0, 1]: tolleranza a output fuori range."""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        if f < 0.0:
            return 0.0
        if f > 1.0:
            return 1.0
        return f

    @field_validator("classe", mode="before")
    @classmethod
    def _normalize_class(cls, v):
        """Mappa classi sconosciute a ALTRO senza sollevare errore."""
        if isinstance(v, DocumentClass):
            return v
        if isinstance(v, str):
            v_up = v.strip().upper()
            if v_up in _VALID_CLASS_VALUES:
                return v_up
            # Fallback silenzioso a ALTRO
            return DocumentClass.ALTRO.value
        return DocumentClass.ALTRO.value


# ──────────────────────────────────────────────────────────────────────────────
# 6) BATCH OUTPUT — risposta del modello per N file
# ──────────────────────────────────────────────────────────────────────────────

class ClassificationBatchOutput(BaseModel):
    """Wrapper per la risposta del modello su batch di file."""

    model_config = ConfigDict(extra="ignore")

    files: List[ClassifiedFile] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# 7) HELPER PUBBLICI
# ──────────────────────────────────────────────────────────────────────────────

def macroarea_for(classe: DocumentClass) -> str:
    """Ritorna la macroarea SOP per una classe documento."""
    return CLASS_TO_MACROAREA.get(classe, "ALTRO")


def char_cap_for(classe: DocumentClass) -> int:
    """Ritorna il cap caratteri suggerito per una classe."""
    return CLASS_TO_CHAR_CAP.get(classe, 12_000)


def default_audit_role_for(classe: DocumentClass) -> AuditRole:
    """Ritorna l'audit_role di default per una classe (fallback deterministico)."""
    return CLASS_TO_DEFAULT_ROLE.get(classe, AuditRole.SUPPORT)


def enrich_with_derived_fields(cf: ClassifiedFile) -> ClassifiedFile:
    """
    Popola macroarea, char_cap_suggested e audit_role se mancanti.
    Restituisce nuova istanza (non muta).
    """
    classe_enum = DocumentClass(cf.classe) if isinstance(cf.classe, str) else cf.classe
    data = cf.model_dump()
    if not data.get("macroarea"):
        data["macroarea"] = macroarea_for(classe_enum)
    if not data.get("char_cap_suggested"):
        data["char_cap_suggested"] = char_cap_for(classe_enum)
    if not data.get("audit_role"):
        data["audit_role"] = default_audit_role_for(classe_enum).value
    return ClassifiedFile(**data)
