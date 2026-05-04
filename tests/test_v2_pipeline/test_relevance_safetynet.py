"""
Test V2 Leva 2 — Fase B — relevance_safetynet.

Coperture:
- Whitelist normativa forza CORE su filename DVR/Visura/ISO/etc.
- Confidence < 0.90 fa fallback NOISE → SUPPORT
- Volume cap 15%: se >15% file marcati noise, eccedenza torna SUPPORT
- Dedup hash: stesso contenuto estratto → primo wins, altri NOISE
- Ordine layers: whitelist > dedup > confidence > volume_cap
- Mai un CORE classificato finisce noise dopo safety net
- Documento con role=NOISE e arc=None: fallback a SUPPORT (conservativo)
- Stats restituite coerenti con i 4 layer
"""
from __future__ import annotations

from v2.relevance_safetynet import (
    NOISE_MIN_CONFIDENCE,
    MAX_NOISE_FRACTION,
    apply_safety_net,
    apply_whitelist_override,
    dedup_by_content_hash,
    enforce_confidence_threshold,
    enforce_volume_cap,
    _filename_matches_whitelist,
)
from v2.schemas.classification import (
    AuditRole,
    ClassifiedFile,
    DocumentClass,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make(filename: str, classe: DocumentClass, *,
          audit_role: str = None, audit_role_confidence: float = None,
          confidence: float = 0.9) -> ClassifiedFile:
    return ClassifiedFile(
        filename=filename,
        classe=classe,
        confidence=confidence,
        audit_role=audit_role,
        audit_role_confidence=audit_role_confidence,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Whitelist
# ──────────────────────────────────────────────────────────────────────────────

def test_whitelist_matches_dvr_filename():
    assert _filename_matches_whitelist("DVR_2024_Rev07.pdf") is not None
    assert _filename_matches_whitelist("dvr-aggiornato.pdf") is not None


def test_whitelist_matches_visura_and_iso():
    assert _filename_matches_whitelist("Visura_Camerale_MEDIL.pdf") is not None
    assert _filename_matches_whitelist("Certificato_ISO_45001.pdf") is not None
    assert _filename_matches_whitelist("ISO9001_2025.pdf") is not None


def test_whitelist_matches_pos_psc_pimus():
    assert _filename_matches_whitelist("POS_cantiere_X.pdf") is not None
    assert _filename_matches_whitelist("PSC_appalto.pdf") is not None
    assert _filename_matches_whitelist("PiMUS_ponteggi.pdf") is not None


def test_whitelist_matches_governance_and_compliance():
    assert _filename_matches_whitelist("Nomina_RSPP.pdf") is not None
    assert _filename_matches_whitelist("registro_infortuni_2024.pdf") is not None
    assert _filename_matches_whitelist("Mansionario_Aziendale.pdf") is not None
    assert _filename_matches_whitelist("Non-Conformita_2024.pdf") is not None


def test_whitelist_does_not_match_random_files():
    assert _filename_matches_whitelist("Mail_trasmissione.pdf") is None
    assert _filename_matches_whitelist("ricevuta_bonifico.pdf") is None
    assert _filename_matches_whitelist("foto_evento.jpg") is None


def test_whitelist_override_forces_core_for_dvr_misclassified_as_noise():
    """Un DVR classificato per errore come NOISE deve tornare CORE."""
    files = [
        _make("DVR_2024.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.95),
    ]
    out, overrides = apply_whitelist_override(files)
    assert out[0].audit_role == AuditRole.CORE.value
    assert len(overrides) == 1
    assert overrides[0]["filename"] == "DVR_2024.pdf"


def test_whitelist_no_change_when_already_core():
    """File già CORE non viene loggato come override."""
    files = [
        _make("DVR_2024.pdf", DocumentClass.DVR,
              audit_role="CORE", audit_role_confidence=0.95),
    ]
    out, overrides = apply_whitelist_override(files)
    assert overrides == []
    assert out[0].audit_role == "CORE"


# ──────────────────────────────────────────────────────────────────────────────
# Confidence threshold
# ──────────────────────────────────────────────────────────────────────────────

def test_confidence_threshold_demotes_low_arc_noise():
    """NOISE con arc=0.7 deve diventare SUPPORT (sotto soglia 0.90)."""
    files = [
        _make("x.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.7),
    ]
    out, downs = enforce_confidence_threshold(files)
    assert out[0].audit_role == AuditRole.SUPPORT.value
    assert len(downs) == 1


def test_confidence_threshold_keeps_high_arc_noise():
    """NOISE con arc=0.95 resta NOISE."""
    files = [
        _make("x.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.95),
    ]
    out, downs = enforce_confidence_threshold(files)
    assert out[0].audit_role == AuditRole.NOISE.value
    assert downs == []


def test_confidence_threshold_demotes_when_arc_is_none():
    """NOISE con arc=None (modello non l'ha popolato) → SUPPORT (conservativo)."""
    files = [
        _make("x.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=None),
    ]
    out, downs = enforce_confidence_threshold(files)
    assert out[0].audit_role == AuditRole.SUPPORT.value
    assert len(downs) == 1


def test_confidence_threshold_does_not_touch_non_noise():
    """SUPPORT/AGGREGABLE/CORE non vengono modificati."""
    files = [
        _make("a.pdf", DocumentClass.DVR, audit_role="CORE"),
        _make("b.pdf", DocumentClass.ATTESTATO, audit_role="AGGREGABLE"),
        _make("c.pdf", DocumentClass.ALTRO, audit_role="SUPPORT"),
    ]
    out, downs = enforce_confidence_threshold(files)
    assert downs == []
    assert [cf.audit_role for cf in out] == ["CORE", "AGGREGABLE", "SUPPORT"]


# ──────────────────────────────────────────────────────────────────────────────
# Volume cap
# ──────────────────────────────────────────────────────────────────────────────

def test_volume_cap_under_threshold_keeps_all_noise():
    """Se ≤15% noise, tutti restano NOISE."""
    files = [
        _make(f"noise_{i}.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.95)
        for i in range(2)
    ] + [
        _make(f"core_{i}.pdf", DocumentClass.DVR, audit_role="CORE")
        for i in range(20)
    ]
    out, downs = enforce_volume_cap(files)
    # 2 NOISE su 22 = 9%, sotto cap 15%
    assert downs == []
    noise_count = sum(1 for cf in out if cf.audit_role == "NOISE")
    assert noise_count == 2


def test_volume_cap_demotes_low_confidence_noise_when_over_cap():
    """Su 10 file 5 noise: cap 15% = 1 max → 4 declassati a SUPPORT."""
    files = [
        _make(f"noise_high_{i}.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.99)
        for i in range(1)
    ] + [
        _make(f"noise_low_{i}.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.91)
        for i in range(4)
    ] + [
        _make(f"core_{i}.pdf", DocumentClass.DVR, audit_role="CORE")
        for i in range(5)
    ]
    out, downs = enforce_volume_cap(files)
    noise_after = [cf for cf in out if cf.audit_role == "NOISE"]
    # Cap 15% di 10 = 1 → max 1 NOISE
    assert len(noise_after) == 1
    # Il NOISE sopravvissuto deve essere quello con arc più alta
    assert noise_after[0].audit_role_confidence == 0.99
    assert len(downs) == 4
    for d in downs:
        assert d["reason"] == "volume_cap_exceeded"


def test_volume_cap_empty_input_safe():
    out, downs = enforce_volume_cap([])
    assert out == []
    assert downs == []


# ──────────────────────────────────────────────────────────────────────────────
# Dedup
# ──────────────────────────────────────────────────────────────────────────────

def test_dedup_marks_duplicates_as_noise():
    """File con stesso extracted_text: secondo (per filename alfa) → NOISE."""
    same_text = "Contenuto identico " * 30  # ≥ 200 char
    files = [
        _make("z_doc.pdf", DocumentClass.ATTESTATO, audit_role="AGGREGABLE"),
        _make("a_doc.pdf", DocumentClass.ATTESTATO, audit_role="AGGREGABLE"),
    ]
    files_index = {
        "z_doc.pdf": {"extracted_text": same_text},
        "a_doc.pdf": {"extracted_text": same_text},
    }
    out, dups = dedup_by_content_hash(files, files_index)
    # Il primo per ordine alfabetico (a_doc) wins
    out_by_name = {cf.filename: cf for cf in out}
    assert out_by_name["a_doc.pdf"].audit_role == "AGGREGABLE"
    assert out_by_name["z_doc.pdf"].audit_role == "NOISE"
    assert len(dups) == 1
    assert dups[0]["duplicate_of"] == "a_doc.pdf"


def test_dedup_does_not_affect_short_text():
    """Testi < 200 char NON sono mai considerati duplicati."""
    short = "Breve."
    files = [
        _make("a.pdf", DocumentClass.ATTESTATO, audit_role="AGGREGABLE"),
        _make("b.pdf", DocumentClass.ATTESTATO, audit_role="AGGREGABLE"),
    ]
    files_index = {
        "a.pdf": {"extracted_text": short},
        "b.pdf": {"extracted_text": short},
    }
    out, dups = dedup_by_content_hash(files, files_index)
    assert dups == []
    assert all(cf.audit_role == "AGGREGABLE" for cf in out)


def test_dedup_no_files_index_safe():
    """Senza files_index nessun file può essere dedotto."""
    files = [_make("a.pdf", DocumentClass.ATTESTATO, audit_role="AGGREGABLE")]
    out, dups = dedup_by_content_hash(files, {})
    assert dups == []


# ──────────────────────────────────────────────────────────────────────────────
# apply_safety_net (orchestratore)
# ──────────────────────────────────────────────────────────────────────────────

def test_safety_net_dvr_misclassified_noise_is_rescued_to_core():
    """
    INVARIANTE PRINCIPALE: un DVR classificato come NOISE con high
    confidence dal modello deve sopravvivere come CORE grazie alla
    whitelist (Layer 1).
    """
    files = [
        _make("DVR_aggiornato_2024.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.99),
        _make("Mail_trasmissione.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.95),
    ]
    res = apply_safety_net(files)
    kept_names = {cf.filename for cf in res["kept"]}
    skipped_names = {cf.filename for cf in res["skipped"]}
    assert "DVR_aggiornato_2024.pdf" in kept_names
    assert "Mail_trasmissione.pdf" in skipped_names
    # DVR tornato a CORE (override whitelist)
    dvr = next(cf for cf in res["kept"] if cf.filename == "DVR_aggiornato_2024.pdf")
    assert dvr.audit_role == "CORE"


def test_safety_net_low_confidence_noise_kept_as_support():
    """Mail con role=NOISE ma arc=0.7 → diventa SUPPORT, finisce in kept."""
    files = [
        _make("Mail.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.7),
    ]
    res = apply_safety_net(files)
    assert res["skipped"] == []
    assert res["kept"][0].audit_role == "SUPPORT"


def test_safety_net_volume_cap_protects_pipeline():
    """
    Se un classifier impazzito marcasse il 50% dei file come NOISE high-conf,
    il volume cap blocca il danno. Su 20 file con 10 NOISE arc=0.99,
    massimo 3 (15%) restano NOISE.
    """
    files = [
        _make(f"noise_{i}.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.99)
        for i in range(10)
    ] + [
        _make(f"keep_{i}.pdf", DocumentClass.DVR, audit_role="CORE")
        for i in range(10)
    ]
    res = apply_safety_net(files)
    assert len(res["skipped"]) <= 3  # 15% di 20
    assert res["stats"]["volume_cap_downgrades_to_support"] >= 7


def test_safety_net_empty_input():
    res = apply_safety_net([])
    assert res["kept"] == []
    assert res["skipped"] == []
    assert res["ledger"] == []


def test_safety_net_ledger_contains_skipped_only():
    """Il ledger deve avere una entry per ogni file skippato (non per kept)."""
    files = [
        _make("Mail_x.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.95),
        _make("DVR.pdf", DocumentClass.DVR, audit_role="CORE"),
    ]
    res = apply_safety_net(files)
    assert len(res["ledger"]) == 1
    assert res["ledger"][0]["filename"] == "Mail_x.pdf"
    assert res["ledger"][0]["reason"] == "model_marked_noise_high_confidence"


def test_safety_net_dedup_marks_duplicate_in_ledger():
    """Il ledger include sub-reason 'duplicate' per i dup."""
    same_text = "Stesso contenuto " * 50
    files = [
        _make("a.pdf", DocumentClass.ATTESTATO, audit_role="AGGREGABLE"),
        _make("b.pdf", DocumentClass.ATTESTATO, audit_role="AGGREGABLE"),
    ]
    files_index = {
        "a.pdf": {"extracted_text": same_text},
        "b.pdf": {"extracted_text": same_text},
    }
    res = apply_safety_net(files, files_index)
    assert len(res["skipped"]) == 1
    ledger_entry = res["ledger"][0]
    assert ledger_entry["reason"] == "duplicate"
    assert ledger_entry["duplicate_of"] in {"a.pdf", "b.pdf"}


def test_safety_net_invariant_no_core_in_skipped():
    """
    INVARIANTE FORTE: dopo apply_safety_net, nessun file con audit_role=CORE
    può essere nella lista skipped. La whitelist deve sempre prevalere.
    """
    files = [
        _make("DVR.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.99),
        _make("Visura_x.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.95),
        _make("Statuto.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.99),
        _make("Mail.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.99),
    ]
    res = apply_safety_net(files)
    skipped_classes = [cf.audit_role for cf in res["skipped"]]
    assert all(role == "NOISE" for role in skipped_classes)
    # Verifico che DVR/Visura/Statuto siano kept
    kept_names = {cf.filename for cf in res["kept"]}
    assert "DVR.pdf" in kept_names
    assert "Visura_x.pdf" in kept_names
    assert "Statuto.pdf" in kept_names


def test_safety_net_stats_consistency():
    """Le stats devono sommare al totale input."""
    files = [
        _make("Mail.pdf", DocumentClass.ALTRO,
              audit_role="NOISE", audit_role_confidence=0.95),
        _make("DVR.pdf", DocumentClass.DVR, audit_role="CORE"),
        _make("Quest.pdf", DocumentClass.ALTRO,
              audit_role="SUPPORT", audit_role_confidence=0.7),
    ]
    res = apply_safety_net(files)
    s = res["stats"]
    assert s["total_input"] == 3
    assert s["kept_count"] + s["skipped_count"] == 3
    assert 0.0 <= s["skipped_pct"] <= 100.0
