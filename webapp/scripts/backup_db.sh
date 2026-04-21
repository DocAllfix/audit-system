#!/bin/bash
# AUDIT-OS — Backup giornaliero SQLite con retention 30 daily + 12 monthly.
# Uso previsto: cron quotidiano 03:15.
# Fallisce silenzioso verso journalctl (cron manda stderr a syslog).

set -u

DB_SRC="/opt/auditos/webapp/data/audit.db"
BACKUP_DIR="/opt/auditos/backups"
LOG_FILE="$BACKUP_DIR/backup.log"

TS=$(date +%Y%m%d_%H%M%S)
DAY=$(date +%Y%m%d)
MONTH_TAG=$(date +%Y%m)
IS_FIRST_OF_MONTH=$(date +%d)

mkdir -p "$BACKUP_DIR"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

if [ ! -f "$DB_SRC" ]; then
    log "ERROR db sorgente assente: $DB_SRC"
    exit 1
fi

# Backup online via Python stdlib (gestisce transazioni attive, sqlite3 CLI non richiesto)
DAILY_OUT="$BACKUP_DIR/daily_${DAY}.db"
/opt/auditos/webapp/venv/bin/python3 -c "
import sqlite3, sys
src = sqlite3.connect('${DB_SRC}')
dst = sqlite3.connect('${DAILY_OUT}')
with dst:
    src.backup(dst)
src.close(); dst.close()
" 2>>"$LOG_FILE"
if [ $? -ne 0 ] || [ ! -s "$DAILY_OUT" ]; then
    log "ERROR backup fallito: $DAILY_OUT"
    exit 2
fi

gzip -f "$DAILY_OUT"
log "OK daily ${DAILY_OUT}.gz ($(stat -c%s "${DAILY_OUT}.gz") bytes)"

# Snapshot mensile il giorno 1
if [ "$IS_FIRST_OF_MONTH" = "01" ]; then
    MONTHLY_OUT="$BACKUP_DIR/monthly_${MONTH_TAG}.db.gz"
    cp "${DAILY_OUT}.gz" "$MONTHLY_OUT"
    log "OK monthly $MONTHLY_OUT"
fi

# Retention: 30 daily + 12 monthly
find "$BACKUP_DIR" -maxdepth 1 -name 'daily_*.db.gz' -mtime +30 -delete 2>>"$LOG_FILE"
find "$BACKUP_DIR" -maxdepth 1 -name 'monthly_*.db.gz' -mtime +366 -delete 2>>"$LOG_FILE"

log "DONE"
