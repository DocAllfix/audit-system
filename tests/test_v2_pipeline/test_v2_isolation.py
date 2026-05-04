"""
Test di isolamento V2.

Verifica che:
1. Il namespace `webapp.v2` sia importabile.
2. Il pipeline stub risponda con il payload atteso.
3. NESSUN file in `webapp/modules/` importi da `webapp.v2.*`
   (V1 deve restare totalmente cieco a V2).
4. Le costanti V2 in config.py siano presenti e con i default attesi.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Aggiungi webapp/ al sys.path come fa l'app a runtime
WEBAPP_DIR = Path(__file__).resolve().parent.parent.parent / "webapp"
if str(WEBAPP_DIR) not in sys.path:
    sys.path.insert(0, str(WEBAPP_DIR))


def test_v2_namespace_importable():
    """Il namespace webapp.v2 deve essere importabile dalla root."""
    import v2  # noqa: F401
    import v2.pipeline  # noqa: F401
    assert v2.__version__.startswith("0.")


def test_v2_stub_returns_alive():
    """Lo stub V2 risponde con il payload atteso (la fase si aggiorna nel tempo)."""
    from v2.pipeline import process_v2_stub
    payload = process_v2_stub()
    assert payload["status"] == "v2_stub_alive"
    # `phase` indica la fase attuale di sviluppo V2 (es. "0_setup", "8_orchestrator")
    assert "phase" in payload and isinstance(payload["phase"], str)
    assert "timestamp" in payload
    assert payload["timestamp"].endswith("Z")


def test_v1_does_not_import_from_v2():
    """
    REGOLA D'ORO: nessun file in webapp/modules/*.py può importare da webapp.v2.*.
    V1 deve restare totalmente isolato da V2 — il rollback deve essere triviale.
    """
    modules_dir = WEBAPP_DIR / "modules"
    violations = []

    for py_file in modules_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        # Cerca pattern d'import sospetti
        for pattern in (
            "from v2",
            "import v2",
            "from webapp.v2",
            "import webapp.v2",
        ):
            # Match riga-per-riga per evitare falsi positivi su commenti/stringhe
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                # Salta commenti e docstring banali
                if stripped.startswith("#"):
                    continue
                if stripped.startswith(pattern + " ") or stripped.startswith(pattern + "."):
                    violations.append(f"{py_file}:{lineno}: {stripped}")

    assert not violations, (
        "V1 NON deve importare da V2. Violazioni:\n  " + "\n  ".join(violations)
    )


def test_config_v2_constants_exist():
    """Le costanti V2 in config.py sono presenti con i default attesi."""
    import config

    assert hasattr(config, "USE_V2_PIPELINE")
    assert config.USE_V2_PIPELINE is False, (
        "Default USE_V2_PIPELINE deve essere False per non attivare accidentalmente V2"
    )

    assert hasattr(config, "V2_USER_WHITELIST")
    assert isinstance(config.V2_USER_WHITELIST, list)
    assert "DocAllfix" in config.V2_USER_WHITELIST, (
        "DocAllfix deve essere il primo testbed (vedi tracker §4)"
    )

    assert hasattr(config, "V2_USE_SUBPROCESS")
    assert config.V2_USE_SUBPROCESS is False, (
        "Default V2_USE_SUBPROCESS deve essere False in dev"
    )

    assert hasattr(config, "V2_MAX_RESPONSE_CHARS")
    assert config.V2_MAX_RESPONSE_CHARS == 400_000


def test_v2_does_not_import_from_v1_modules():
    """
    Simmetrico: V2 non deve importare da webapp/modules/* (V1 specifico).
    Eccezione consentita: import da `config` (condiviso, neutro).
    """
    v2_dir = WEBAPP_DIR / "v2"
    violations = []

    for py_file in v2_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Vietati gli import da modules.*
            if (
                stripped.startswith("from modules")
                or stripped.startswith("import modules")
                or stripped.startswith("from webapp.modules")
                or stripped.startswith("import webapp.modules")
            ):
                violations.append(f"{py_file}:{lineno}: {stripped}")

    assert not violations, (
        "V2 NON deve importare da webapp/modules/* (V1). Violazioni:\n  "
        + "\n  ".join(violations)
    )
