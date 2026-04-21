"""
Modulo Database Manager per AUDIT-OS
Gestisce storico pratiche, logging e persistenza dati
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# Path del database
DATA_DIR = Path(__file__).parent.parent / "data"
DB_FILE = DATA_DIR / "audit.db"

# Assicura che la directory esista
DATA_DIR.mkdir(exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """Ottiene una connessione al database."""
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Inizializza il database con le tabelle necessarie."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabella pratiche
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pratiche (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            tipo TEXT CHECK(tipo IN ('report','checklist_json','checklist_word')) NOT NULL,
            azienda TEXT,
            norma TEXT,
            data_creazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            file_output_path TEXT,
            file_input_path TEXT,
            file_output_name TEXT,
            file_size INTEGER DEFAULT 0,
            processing_time_seconds REAL DEFAULT 0,
            status TEXT DEFAULT 'completato',
            note TEXT
        )
    """)
    
    # Tabella activity log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Tabella error_log - Traccia errori per admin
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            azienda TEXT,
            error_type TEXT,
            error_message TEXT,
            stack_trace TEXT,
            tab_source TEXT,
            file_involved TEXT,
            pratica_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved INTEGER DEFAULT 0
        )
    """)
    
    # Indici per performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pratiche_user ON pratiche(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pratiche_date ON pratiche(data_creazione DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pratiche_tipo ON pratiche(tipo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pratiche_norma ON pratiche(norma)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_error_user ON error_log(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_error_date ON error_log(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_error_type ON error_log(error_type)")

    # Migrazione R-4: nuove colonne error_log (idempotente — try/except su ogni ALTER)
    migration_cols = [
        ("batch_index",      "INTEGER DEFAULT -1"),
        ("docs_involved",    "TEXT"),
        ("error_subtype",    "TEXT"),
        ("auto_recovered",   "INTEGER DEFAULT 0"),
        ("recovery_details", "TEXT"),
        ("resolved_by",      "TEXT"),
        ("resolved_at",      "TIMESTAMP"),
    ]
    for col_name, col_def in migration_cols:
        try:
            cursor.execute(f"ALTER TABLE error_log ADD COLUMN {col_name} {col_def}")
        except sqlite3.OperationalError:
            pass  # Colonna già esistente — ignorare

    # Indice su error_subtype per dashboard aggregati
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_error_subtype ON error_log(error_subtype)")

    conn.commit()
    conn.close()


# Inizializza database all'import
init_database()


# ==============================================================================
# FUNZIONI PRATICHE
# ==============================================================================

def save_pratica(
    user_id: str,
    tipo: str,
    file_output_path: str,
    file_output_name: str,
    azienda: str = "",
    norma: str = "",
    file_input_path: str = "",
    file_size: int = 0,
    processing_time: float = 0,
    note: str = ""
) -> int:
    """
    Salva una nuova pratica nel database.
    
    Returns:
        ID della pratica inserita
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO pratiche 
        (user_id, tipo, azienda, norma, file_output_path, file_input_path, 
         file_output_name, file_size, processing_time_seconds, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, tipo, azienda, norma, file_output_path, file_input_path,
          file_output_name, file_size, processing_time, note))
    
    pratica_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return pratica_id


def get_pratiche_utente(
    user_id: str,
    tipo: str = None,
    limit: int = 50,
    offset: int = 0,
    search_azienda: str = None,
    data_inizio: str = None,
    data_fine: str = None
) -> List[Dict]:
    """
    Recupera le pratiche di un utente con filtri opzionali.
    
    Args:
        user_id: ID utente
        tipo: Filtra per tipo (report, checklist_json, checklist_word)
        limit: Numero massimo risultati
        offset: Offset per paginazione
        search_azienda: Cerca per nome azienda
        data_inizio: Data inizio (YYYY-MM-DD)
        data_fine: Data fine (YYYY-MM-DD)
    
    Returns:
        Lista di pratiche
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM pratiche WHERE user_id = ?"
    params = [user_id]
    
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    
    if search_azienda:
        query += " AND azienda LIKE ?"
        params.append(f"%{search_azienda}%")
    
    if data_inizio:
        query += " AND date(data_creazione) >= ?"
        params.append(data_inizio)
    
    if data_fine:
        query += " AND date(data_creazione) <= ?"
        params.append(data_fine)
    
    query += " ORDER BY data_creazione DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_all_pratiche_admin(
    limit: int = 100,
    offset: int = 0,
    search_azienda: str = None,
    user_filter: str = None
) -> List[Dict]:
    """
    Recupera tutte le pratiche (solo admin).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM pratiche WHERE 1=1"
    params = []
    
    if user_filter:
        query += " AND user_id = ?"
        params.append(user_filter)
    
    if search_azienda:
        query += " AND azienda LIKE ?"
        params.append(f"%{search_azienda}%")
    
    query += " ORDER BY data_creazione DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def count_pratiche_utente(user_id: str, tipo: str = None) -> int:
    """Conta le pratiche di un utente."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if tipo:
        cursor.execute(
            "SELECT COUNT(*) FROM pratiche WHERE user_id = ? AND tipo = ?",
            (user_id, tipo)
        )
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM pratiche WHERE user_id = ?",
            (user_id,)
        )
    
    count = cursor.fetchone()[0]
    conn.close()
    return count


def delete_pratica(pratica_id: int, user_id: str = None) -> bool:
    """
    Elimina una pratica.
    Se user_id è specificato, verifica che appartenga all'utente.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    if user_id:
        cursor.execute(
            "DELETE FROM pratiche WHERE id = ? AND user_id = ?",
            (pratica_id, user_id)
        )
    else:
        # Admin può eliminare qualsiasi pratica
        cursor.execute("DELETE FROM pratiche WHERE id = ?", (pratica_id,))
    
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ==============================================================================
# FUNZIONI STATISTICHE
# ==============================================================================

def get_statistiche_utente(user_id: str) -> Dict:
    """Statistiche per singolo utente."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Totale pratiche
    cursor.execute(
        "SELECT COUNT(*) FROM pratiche WHERE user_id = ?", (user_id,)
    )
    totale = cursor.fetchone()[0]
    
    # Per tipo
    cursor.execute("""
        SELECT tipo, COUNT(*) as count 
        FROM pratiche WHERE user_id = ? 
        GROUP BY tipo
    """, (user_id,))
    per_tipo = {row["tipo"]: row["count"] for row in cursor.fetchall()}
    
    # Oggi
    cursor.execute("""
        SELECT COUNT(*) FROM pratiche 
        WHERE user_id = ? AND date(data_creazione) = date('now')
    """, (user_id,))
    oggi = cursor.fetchone()[0]
    
    # Ultimi 7 giorni
    cursor.execute("""
        SELECT COUNT(*) FROM pratiche 
        WHERE user_id = ? AND data_creazione >= datetime('now', '-7 days')
    """, (user_id,))
    settimana = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "totale": totale,
        "per_tipo": per_tipo,
        "oggi": oggi,
        "settimana": settimana
    }


def get_statistiche_globali() -> Dict:
    """Statistiche globali (solo admin)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Totale pratiche
    cursor.execute("SELECT COUNT(*) FROM pratiche")
    totale = cursor.fetchone()[0]
    
    # Per utente
    cursor.execute("""
        SELECT user_id, COUNT(*) as count 
        FROM pratiche GROUP BY user_id
        ORDER BY count DESC
    """)
    per_utente = {row["user_id"]: row["count"] for row in cursor.fetchall()}
    
    # Per norma
    cursor.execute("""
        SELECT norma, COUNT(*) as count 
        FROM pratiche WHERE norma IS NOT NULL AND norma != ''
        GROUP BY norma ORDER BY count DESC
    """)
    per_norma = {row["norma"]: row["count"] for row in cursor.fetchall()}
    
    # Oggi
    cursor.execute("""
        SELECT COUNT(*) FROM pratiche 
        WHERE date(data_creazione) = date('now')
    """)
    oggi = cursor.fetchone()[0]
    
    # Tempo medio elaborazione
    cursor.execute("""
        SELECT AVG(processing_time_seconds) FROM pratiche 
        WHERE processing_time_seconds > 0
    """)
    tempo_medio = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return {
        "totale": totale,
        "per_utente": per_utente,
        "per_norma": per_norma,
        "oggi": oggi,
        "tempo_medio_secondi": round(tempo_medio, 1)
    }


# ==============================================================================
# FUNZIONI ACTIVITY LOG
# ==============================================================================

def log_activity(user_id: str, action: str, details: str = "", ip: str = ""):
    """Registra un'attività nel log."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO activity_log (user_id, action, details, ip_address)
        VALUES (?, ?, ?, ?)
    """, (user_id, action, details, ip))
    
    conn.commit()
    conn.close()


def get_recent_activity(limit: int = 50, user_id: str = None) -> List[Dict]:
    """Recupera attività recenti."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if user_id:
        cursor.execute("""
            SELECT * FROM activity_log 
            WHERE user_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (user_id, limit))
    else:
        cursor.execute("""
            SELECT * FROM activity_log 
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ==============================================================================
# FUNZIONI ERROR LOG - Tracciamento errori per Admin
# ==============================================================================

def save_error_log(
    user_id: str,
    error_type: str,
    error_message: str,
    tab_source: str,
    azienda: str = "",
    stack_trace: str = "",
    file_involved: str = "",
    pratica_id: int = None
) -> int:
    """
    Salva un errore nel log per revisione admin.
    
    Args:
        user_id: Username dell'utente
        error_type: Tipo errore ('extraction', 'api', 'generation', 'fatal', 'validation')
        error_message: Messaggio di errore principale
        tab_source: Tab in cui è avvenuto l'errore ('tab1', 'tab2', 'tab3')
        azienda: Nome azienda della pratica (se disponibile)
        stack_trace: Stack trace completo (opzionale)
        file_involved: File coinvolto nell'errore (opzionale)
        pratica_id: ID pratica correlata (opzionale)
    
    Returns:
        ID del log inserito
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO error_log 
            (user_id, azienda, error_type, error_message, stack_trace, tab_source, file_involved, pratica_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, azienda, error_type, error_message, stack_trace, tab_source, file_involved, pratica_id))
        
        error_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return error_id
    except Exception as e:
        # Non bloccare il flusso principale se il log fallisce
        print(f"[WARNING] Errore salvataggio error_log: {e}")
        return -1


def get_errors_for_admin(
    limit: int = 50,
    user_id: str = None,
    error_type: str = None,
    include_resolved: bool = False,
    days_back: int = 30
) -> List[Dict]:
    """
    Recupera errori per la pagina admin.
    
    Args:
        limit: Numero massimo di errori da restituire
        user_id: Filtra per utente specifico (opzionale)
        error_type: Filtra per tipo errore (opzionale)
        include_resolved: Se True, include anche errori risolti
        days_back: Ultimi N giorni da considerare
    
    Returns:
        Lista di errori come dizionari
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT * FROM error_log 
        WHERE created_at >= datetime('now', ?)
    """
    params = [f'-{days_back} days']
    
    if not include_resolved:
        query += " AND resolved = 0"
    
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    
    if error_type:
        query += " AND error_type = ?"
        params.append(error_type)
    
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def mark_error_resolved(error_id: int, resolved_by: str = "") -> bool:
    """Segna un errore come risolto, tracciando chi e quando."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE error_log "
            "SET resolved = 1, resolved_by = ?, resolved_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (resolved_by or "", error_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def save_partial_error(
    user_id: str,
    azienda: str,
    error_subtype: str,
    error_message: str,
    batch_index: int = -1,
    docs_involved: list = None,
    auto_recovered: bool = False,
    recovery_details: str = "",
    tab_source: str = "tab1"
) -> int:
    """
    Salva un errore parziale (non bloccante) nel log errori.

    error_subtype valori attesi:
        "json_parse"    — batch perso per parsing JSON fallito
        "ocr_none"      — response.text None su pagina vuota
        "name_conflict" — conflitto nome azienda ZIP vs visura
        "mupdf_warn"    — warning MuPDF (non bloccante)
        "batch_loss"    — batch perso completamente

    Sempre wrapped in try/except — non deve mai bloccare la pipeline.
    """
    try:
        import json as _json
        conn = get_connection()
        cursor = conn.cursor()

        docs_str = _json.dumps(docs_involved) if docs_involved else None

        cursor.execute("""
            INSERT INTO error_log
            (user_id, azienda, error_type, error_message, tab_source,
             error_subtype, batch_index, docs_involved, auto_recovered, recovery_details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, azienda, "partial_error", error_message, tab_source,
            error_subtype, batch_index, docs_str,
            1 if auto_recovered else 0, recovery_details
        ))

        error_id = cursor.lastrowid
        conn.commit()
        conn.close()
        print(f"[ERROR_LOG] {error_subtype} salvato (batch={batch_index}, recovered={auto_recovered})")
        return error_id
    except Exception as e:
        print(f"[WARNING] save_partial_error fallito (non bloccante): {e}")
        return -1


def get_error_dashboard(days: int = 30) -> Dict:
    """
    Dashboard errori parziali per admin.
    Restituisce aggregati per subtype e trend giornaliero.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Aggregati per subtype
    cursor.execute("""
        SELECT error_subtype,
               COUNT(*) as count,
               SUM(auto_recovered) as recovered
        FROM error_log
        WHERE error_type = 'partial_error'
          AND created_at >= datetime('now', ?)
          AND error_subtype IS NOT NULL
        GROUP BY error_subtype
        ORDER BY count DESC
    """, (f'-{days} days',))
    by_subtype = [
        {"subtype": row[0], "count": row[1], "recovered": row[2] or 0}
        for row in cursor.fetchall()
    ]

    # Trend giornaliero
    cursor.execute("""
        SELECT date(created_at) as day,
               error_subtype,
               COUNT(*) as count
        FROM error_log
        WHERE error_type = 'partial_error'
          AND created_at >= datetime('now', ?)
          AND error_subtype IS NOT NULL
        GROUP BY date(created_at), error_subtype
        ORDER BY day DESC
    """, (f'-{days} days',))
    daily_trend = [
        {"day": row[0], "subtype": row[1], "count": row[2]}
        for row in cursor.fetchall()
    ]

    # Totali overall
    cursor.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN auto_recovered = 1 THEN 1 ELSE 0 END)
        FROM error_log
        WHERE error_type = 'partial_error'
          AND created_at >= datetime('now', ?)
    """, (f'-{days} days',))
    row = cursor.fetchone()
    total = row[0] or 0
    recovered_total = row[1] or 0

    conn.close()

    return {
        "days": days,
        "total_partial_errors": total,
        "recovered": recovered_total,
        "recovery_rate": round(recovered_total / total * 100, 1) if total > 0 else 0,
        "by_subtype": by_subtype,
        "daily_trend": daily_trend,
    }


def get_error_stats() -> Dict:
    """Statistiche errori per dashboard admin."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Errori ultime 24 ore
    cursor.execute("""
        SELECT COUNT(*) FROM error_log 
        WHERE created_at >= datetime('now', '-1 day')
    """)
    last_24h = cursor.fetchone()[0]
    
    # Errori ultimi 7 giorni
    cursor.execute("""
        SELECT COUNT(*) FROM error_log 
        WHERE created_at >= datetime('now', '-7 days')
    """)
    last_7d = cursor.fetchone()[0]
    
    # Errori non risolti
    cursor.execute("SELECT COUNT(*) FROM error_log WHERE resolved = 0")
    unresolved = cursor.fetchone()[0]
    
    # Errori per tipo (ultimi 7 giorni)
    cursor.execute("""
        SELECT error_type, COUNT(*) as count 
        FROM error_log 
        WHERE created_at >= datetime('now', '-7 days')
        GROUP BY error_type
        ORDER BY count DESC
    """)
    by_type = {row[0]: row[1] for row in cursor.fetchall()}
    
    conn.close()
    
    return {
        "last_24h": last_24h,
        "last_7d": last_7d,
        "unresolved": unresolved,
        "by_type": by_type
    }
