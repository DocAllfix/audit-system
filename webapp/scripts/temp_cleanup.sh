#!/bin/bash
# AUDIT-OS — Cleanup temp con esclusione cartella logs (audit trail).
# Retention: 1 giorno per file estratti e zip, 30 giorni per log JSON.
# Sostituisce la vecchia riga crontab diretta per motivi GDPR (residui PDF clienti).

set -u

TEMP_DIR="/opt/auditos/temp"
LOGS_DIR="$TEMP_DIR/logs"
LOG_FILE="$TEMP_DIR/cleanup.log"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

if [ ! -d "$TEMP_DIR" ]; then
    exit 0
fi

# File e directory non-logs più vecchi di 24h
BEFORE=$(du -sb "$TEMP_DIR" 2>/dev/null | awk '{print $1}')

find "$TEMP_DIR" -mindepth 1 -maxdepth 1 \
    ! -path "$LOGS_DIR" \
    \( -name 'extract_*' -o -name 'uploaded*.zip' -o -name '*.zip' -o -name '*.tmp' \) \
    -mtime +1 -exec rm -rf {} + 2>>"$LOG_FILE"

# Dentro logs/: JSON più vecchi di 30 giorni
if [ -d "$LOGS_DIR" ]; then
    find "$LOGS_DIR" -maxdepth 1 -name 'audit_log_*.json' -mtime +30 -delete 2>>"$LOG_FILE"
fi

AFTER=$(du -sb "$TEMP_DIR" 2>/dev/null | awk '{print $1}')
log "cleanup: before=${BEFORE}B after=${AFTER}B"
