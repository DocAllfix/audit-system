"""
V2 — OpenTelemetry tracer (Fase 6).

Wrapper opzionale per emettere span verso un backend OTLP (Grafana/Prometheus).

Default: NO-OP. Si attiva solo se:
1. La variabile d'ambiente `V2_OTEL_ENABLED=true`
2. Le librerie `opentelemetry-api` + `opentelemetry-sdk` sono installate

Quando disattivato (caso default in sviluppo), il modulo espone API stub che
non fanno nulla, così i caller possono usarlo senza guardrail aggiuntivi:

    with otel_span("phase.ingestion"):
        ...do work...

API:
    init_tracer(service_name="audit-os-v2") -> bool
    otel_span(name, attributes=None) -> context manager
    is_enabled() -> bool
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────────────────────

_ENABLED_ENV = os.environ.get("V2_OTEL_ENABLED", "false").lower() == "true"

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.resources import Resource
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False
    trace = None  # type: ignore


_tracer = None
_initialized = False


def is_enabled() -> bool:
    """True se OTel è attivato e librerie disponibili."""
    return _ENABLED_ENV and HAS_OTEL


# ──────────────────────────────────────────────────────────────────────────────
# Init
# ──────────────────────────────────────────────────────────────────────────────

def init_tracer(service_name: str = "audit-os-v2") -> bool:
    """
    Inizializza il tracer globale. Idempotente.

    Returns:
        True se inizializzato (o già inizializzato), False se non disponibile.
    """
    global _tracer, _initialized

    if not is_enabled():
        return False

    if _initialized:
        return True

    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        # Note: nessun Span Processor di default. Il caller (es. setup
        # production) può aggiungere OTLPSpanExporter via codice esterno.
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        _initialized = True
        print(f"[V2 OTEL] Tracer inizializzato (service={service_name})")
        return True
    except Exception as e:
        print(f"[V2 OTEL] Init fallita: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Span context manager
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def otel_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Context manager che apre uno span OTel. NO-OP se OTel disabilitato.

    Args:
        name: nome dello span (es. "phase.ingestion")
        attributes: dict di attributi key=value

    Yields:
        L'oggetto span (o None se disabilitato).
    """
    if not is_enabled():
        yield None
        return

    if not _initialized:
        init_tracer()

    if _tracer is None:
        yield None
        return

    try:
        with _tracer.start_as_current_span(name) as span:
            if attributes:
                for k, v in attributes.items():
                    try:
                        span.set_attribute(k, v)
                    except Exception:
                        pass
            yield span
    except Exception:
        # Mai propagare errori del tracing al codice di business
        yield None


def add_event(span_name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
    """Aggiunge un event al current span (no-op se OTel non attivo)."""
    if not is_enabled() or trace is None:
        return
    try:
        span = trace.get_current_span()
        if span is None:
            return
        span.add_event(span_name, attributes=attributes or {})
    except Exception:
        pass
