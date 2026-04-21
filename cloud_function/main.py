"""
AUDIT-OS Gemini API Proxy - Cloud Function
Proxy trasparente che inoltra le richieste Gemini API da regioni bloccate (EU/Hetzner)
verso l'endpoint ufficiale Google, girando in una regione supportata (us-central1).
"""

import functions_framework
import requests
from flask import Response

TARGET_HOST = "https://generativelanguage.googleapis.com"

# Segreto condiviso per autenticazione (impostare come variabile d'ambiente)
import os
PROXY_SECRET = os.environ.get("PROXY_SECRET", "")

# Headers da NON inoltrare (hop-by-hop o specifici del proxy)
SKIP_REQUEST_HEADERS = {
    "host", "x-proxy-secret", "x-forwarded-for", "x-forwarded-proto",
    "x-cloud-trace-context", "traceparent", "x-forwarded-host",
    "forwarded", "transfer-encoding", "connection"
}

SKIP_RESPONSE_HEADERS = {
    "transfer-encoding", "connection", "content-encoding",
    "content-length"  # Flask ricalcola automaticamente
}


@functions_framework.http
def gemini_proxy(request):
    """Proxy trasparente per Gemini API."""

    # Autenticazione: verifica segreto condiviso
    if PROXY_SECRET:
        req_secret = request.headers.get("X-Proxy-Secret", "")
        if req_secret != PROXY_SECRET:
            return Response("Unauthorized", status=401)

    # Costruisci URL target
    # request.path contiene il path DOPO la base della Cloud Function
    # es: /v1beta/models/gemini-2.5-flash:generateContent
    path = request.path or ""
    target_url = TARGET_HOST + path
    if request.query_string:
        target_url += "?" + request.query_string.decode("utf-8")

    # Filtra headers della richiesta
    fwd_headers = {}
    for key, value in request.headers:
        if key.lower() not in SKIP_REQUEST_HEADERS:
            fwd_headers[key] = value

    # Inoltra la richiesta
    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=fwd_headers,
            data=request.get_data(),
            timeout=300,  # 5 minuti per richieste grandi
            stream=False
        )
    except requests.exceptions.Timeout:
        return Response("Upstream timeout", status=504)
    except requests.exceptions.RequestException as e:
        return Response(f"Proxy error: {e}", status=502)

    # Filtra headers della risposta
    resp_headers = {}
    for key, value in resp.headers.items():
        if key.lower() not in SKIP_RESPONSE_HEADERS:
            resp_headers[key] = value

    return Response(
        response=resp.content,
        status=resp.status_code,
        headers=resp_headers
    )
