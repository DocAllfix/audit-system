#!/bin/bash
# ==============================================================================
# Deploy script per Gemini API Proxy Cloud Function
# Prerequisiti: gcloud CLI installato e autenticato
# ==============================================================================

# CONFIGURAZIONE - Modifica questi valori
PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="us-central1"
FUNCTION_NAME="gemini-proxy"
PROXY_SECRET="${PROXY_SECRET:-auditos-proxy-2026}"

if [ -z "$PROJECT_ID" ]; then
    echo "ERRORE: Imposta GCP_PROJECT_ID"
    echo "Uso: GCP_PROJECT_ID=my-project ./deploy.sh"
    exit 1
fi

echo "Deploy Cloud Function: $FUNCTION_NAME"
echo "Progetto: $PROJECT_ID"
echo "Regione: $REGION"
echo ""

gcloud functions deploy "$FUNCTION_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --runtime=python312 \
    --trigger-http \
    --allow-unauthenticated \
    --entry-point=gemini_proxy \
    --memory=256MB \
    --timeout=300s \
    --max-instances=20 \
    --set-env-vars="PROXY_SECRET=$PROXY_SECRET" \
    --source=.

if [ $? -eq 0 ]; then
    URL=$(gcloud functions describe "$FUNCTION_NAME" --project="$PROJECT_ID" --region="$REGION" --format='value(url)')
    echo ""
    echo "=========================================="
    echo "DEPLOY COMPLETATO!"
    echo "URL Proxy: $URL"
    echo "Secret: $PROXY_SECRET"
    echo "=========================================="
    echo ""
    echo "Configura sul server:"
    echo "  GEMINI_PROXY_URL=$URL"
    echo "  GEMINI_PROXY_SECRET=$PROXY_SECRET"
else
    echo "ERRORE nel deploy!"
    exit 1
fi
