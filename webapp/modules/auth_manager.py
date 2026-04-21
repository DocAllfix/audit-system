"""
Modulo Auth Manager per AUDIT-OS
Gestisce autenticazione multi-utente con ruoli admin/auditor
Sicurezza: bcrypt per hashing password (resistente a rainbow tables)
"""

import streamlit as st
import hashlib
import json
import os
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from pathlib import Path

# Path del file utenti
CONFIG_DIR = Path(__file__).parent.parent / "config"
USERS_FILE = CONFIG_DIR / "users.json"
SESSIONS_FILE = CONFIG_DIR / "sessions.json"  # Nuovo: file per sessioni persistenti

# Marker per identificare hash bcrypt vs SHA-256 legacy
BCRYPT_PREFIX = "$2b$"

# Durata sessione (24 ore)
SESSION_DURATION_HOURS = 24


def hash_password(password: str) -> str:
    """Hash password con bcrypt (sicuro, include salt automatico)."""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt(rounds=10)  # 10 rounds = ~100ms, buon compromesso sicurezza/velocità
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """
    Verifica password contro hash.
    Supporta sia bcrypt (nuovo) che SHA-256 (legacy per migrazione).
    """
    if hashed.startswith(BCRYPT_PREFIX):
        # Nuovo formato bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    else:
        # Legacy SHA-256 (per migrazione password esistenti)
        salt = "AUDITOS_SECURE_SALT_2026"
        legacy_hash = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return legacy_hash == hashed


def hash_password_legacy(password: str) -> str:
    """Hash legacy SHA-256 (solo per confronto durante migrazione)."""
    salt = "AUDITOS_SECURE_SALT_2026"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def load_users() -> Dict:
    """Carica utenti dal file JSON."""
    if not USERS_FILE.exists():
        # Crea file utenti default se non esiste
        create_default_users()
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users: Dict):
    """Salva utenti nel file JSON."""
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def create_default_users():
    """Crea utenti default (admin + 5 auditor)."""
    users = {
        "admin": {
            "name": "Amministratore",
            "password": hash_password("admin2026"),  # Cambiare in produzione!
            "role": "admin",
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "active": True
        },
        "boss": {
            "name": "Boss",
            "password": hash_password("boss2026"),
            "role": "auditor",
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "active": True
        },
        "valerio": {
            "name": "Valerio",
            "password": hash_password("valerio2026"),
            "role": "auditor",
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "active": True
        },
        "egisto": {
            "name": "Egisto",
            "password": hash_password("egisto2026"),
            "role": "auditor",
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "active": True
        },
        "fabiana": {
            "name": "Fabiana",
            "password": hash_password("fabiana2026"),
            "role": "auditor",
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "active": True
        },
        "alessia": {
            "name": "Alessia",
            "password": hash_password("alessia2026"),
            "role": "auditor",
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "active": True
        }
    }
    save_users(users)
    return users


def authenticate(username: str, password: str) -> Tuple[bool, Optional[str]]:
    """
    Verifica le credenziali utente.
    Migra automaticamente password legacy SHA-256 a bcrypt al primo login.
    
    Returns:
        (success, error_message)
    """
    users = load_users()
    
    username_lower = username.lower().strip()
    
    if username_lower not in users:
        return False, "Username non trovato"
    
    user = users[username_lower]
    
    if not user.get("active", True):
        return False, "Account disabilitato"
    
    # Usa verify_password che supporta sia bcrypt che SHA-256 legacy
    if not verify_password(password, user["password"]):
        return False, "Password errata"
    
    # MIGRAZIONE AUTOMATICA: se la password è ancora SHA-256, aggiornala a bcrypt
    if not user["password"].startswith(BCRYPT_PREFIX):
        users[username_lower]["password"] = hash_password(password)
        # Salva subito la password migrata
    
    # Aggiorna last_login
    users[username_lower]["last_login"] = datetime.now().isoformat()
    save_users(users)
    
    return True, None


def get_current_user() -> Optional[Dict]:
    """Ritorna l'utente corrente dalla sessione."""
    if "user" in st.session_state and st.session_state.user:
        return st.session_state.user
    return None


def is_logged_in() -> bool:
    """Verifica se l'utente è loggato."""
    return get_current_user() is not None


def is_admin() -> bool:
    """Verifica se l'utente corrente è admin."""
    user = get_current_user()
    return user is not None and user.get("role") == "admin"


def get_user_display_name() -> str:
    """Ritorna il nome visualizzato dell'utente."""
    user = get_current_user()
    if user:
        return user.get("name", user.get("username", "Utente"))
    return "Ospite"


# ==============================================================================
# SESSIONI PERSISTENTI - Mantiene login dopo refresh
# ==============================================================================

def generate_session_token() -> str:
    """Genera un token di sessione univoco."""
    import secrets
    return secrets.token_urlsafe(32)


def load_sessions() -> Dict:
    """Carica sessioni dal file JSON."""
    if not SESSIONS_FILE.exists():
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_sessions(sessions: Dict):
    """Salva sessioni nel file JSON."""
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)


def create_persistent_session(username: str) -> str:
    """
    Crea una sessione persistente per l'utente.
    Ritorna il token da salvare nei query params.
    """
    token = generate_session_token()
    sessions = load_sessions()
    
    # Pulisci sessioni scadute
    now = datetime.now()
    sessions = {
        t: s for t, s in sessions.items()
        if datetime.fromisoformat(s["expires"]) > now
    }
    
    # Aggiungi nuova sessione
    sessions[token] = {
        "username": username,
        "created": now.isoformat(),
        "expires": (now + timedelta(hours=SESSION_DURATION_HOURS)).isoformat()
    }
    
    save_sessions(sessions)
    return token


def validate_session_token(token: str) -> Optional[str]:
    """
    Verifica se un token di sessione è valido.
    Ritorna lo username se valido, None altrimenti.
    """
    if not token:
        return None
    
    sessions = load_sessions()
    
    if token not in sessions:
        return None
    
    session = sessions[token]
    expires = datetime.fromisoformat(session["expires"])
    
    if datetime.now() > expires:
        # Sessione scaduta, rimuovi
        del sessions[token]
        save_sessions(sessions)
        return None
    
    return session["username"]


def invalidate_session_token(token: str):
    """Invalida un token di sessione (per logout)."""
    sessions = load_sessions()
    if token in sessions:
        del sessions[token]
        save_sessions(sessions)


def restore_session_from_token():
    """
    Tenta di ripristinare la sessione utente dai query params.
    Chiamare all'avvio dell'app prima di mostrare la login page.
    """
    # Se già loggato, non fare nulla
    if "user" in st.session_state and st.session_state.user:
        return True
    
    # Leggi token dai query params
    try:
        query_params = st.query_params
        token = query_params.get("session", None)
    except Exception as e:
        print(f"[SESSION] Errore lettura query params: {e}")
        return False
    
    if not token:
        return False
    
    # Valida token
    username = validate_session_token(token)
    if not username:
        # Token invalido o scaduto, rimuovi dal URL
        try:
            if "session" in st.query_params:
                del st.query_params["session"]
        except:
            pass
        return False
    
    # Ripristina sessione
    users = load_users()
    if username in users:
        user_data = users[username]
        st.session_state.user = {
            "username": username,
            "name": user_data["name"],
            "role": user_data["role"]
        }
        st.session_state.authenticated = True
        st.session_state.session_token = token
        print(f"[SESSION] Sessione ripristinata per {username}")
        return True
    
    return False


def logout():
    """Esegue il logout e invalida la sessione persistente."""
    # Invalida token se presente
    if "session_token" in st.session_state:
        invalidate_session_token(st.session_state.session_token)
        del st.session_state.session_token
    
    # Rimuovi token da URL
    if "session" in st.query_params:
        del st.query_params["session"]
    
    if "user" in st.session_state:
        del st.session_state.user
    if "authenticated" in st.session_state:
        del st.session_state.authenticated


def login(username: str, password: str) -> Tuple[bool, str]:
    """
    Esegue il login e salva l'utente in sessione.
    Crea anche una sessione persistente per sopravvivere ai refresh.
    
    Returns:
        (success, message)
    """
    success, error = authenticate(username, password)
    
    if success:
        users = load_users()
        username_lower = username.lower().strip()
        user_data = users[username_lower]
        
        st.session_state.user = {
            "username": username_lower,
            "name": user_data["name"],
            "role": user_data["role"]
        }
        st.session_state.authenticated = True
        
        # NUOVO: Crea sessione persistente
        token = create_persistent_session(username_lower)
        st.session_state.session_token = token
        
        # Salva token nei query params per persistenza al refresh
        st.query_params["session"] = token
        
        return True, f"Benvenuto, {user_data['name']}!"
    else:
        return False, error


def change_password(username: str, old_password: str, new_password: str) -> Tuple[bool, str]:
    """Cambia la password di un utente."""
    users = load_users()
    username_lower = username.lower().strip()
    
    if username_lower not in users:
        return False, "Utente non trovato"
    
    if users[username_lower]["password"] != hash_password(old_password):
        return False, "Password attuale errata"
    
    if len(new_password) < 6:
        return False, "La nuova password deve avere almeno 6 caratteri"
    
    users[username_lower]["password"] = hash_password(new_password)
    save_users(users)
    
    return True, "Password cambiata con successo"


def admin_reset_password(username: str, new_password: str) -> Tuple[bool, str]:
    """Admin resetta la password di un utente."""
    if not is_admin():
        return False, "Solo l'admin può resettare le password"
    
    users = load_users()
    username_lower = username.lower().strip()
    
    if username_lower not in users:
        return False, "Utente non trovato"
    
    if len(new_password) < 6:
        return False, "La password deve avere almeno 6 caratteri"
    
    users[username_lower]["password"] = hash_password(new_password)
    save_users(users)
    
    return True, f"Password di {username} resettata"


def get_all_users() -> Dict:
    """Ritorna tutti gli utenti (solo per admin)."""
    return load_users()


def render_login_page():
    """
    Renderizza la pagina di login.
    Ritorna True se l'utente è autenticato.
    """
    # Se già loggato, mostra info utente
    if is_logged_in():
        return True
    
    # Styling login
    st.markdown("""
    <style>
    .login-container {
        max-width: 400px;
        margin: 0 auto;
        padding: 2rem;
    }
    .login-header {
        text-align: center;
        margin-bottom: 2rem;
    }
    .login-header h1 {
        color: #14b8a6;
        font-size: 2.5rem;
    }
    </style>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        <div class="login-header">
            <h1>🔐 AUDIT-OS</h1>
            <p style="color: #94a3b8;">Sistema di Audit Documentale</p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.form("login_form"):
            username = st.text_input("👤 Username", placeholder="Inserisci username")
            password = st.text_input("🔑 Password", type="password", placeholder="Inserisci password")
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                submit = st.form_submit_button("🚀 Accedi", use_container_width=True, type="primary")
            
            if submit:
                if username and password:
                    success, message = login(username, password)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")
                else:
                    st.warning("⚠️ Inserisci username e password")
        
        st.markdown("---")
        st.caption("💡 Contatta l'amministratore per credenziali")
    
    return False


def render_user_menu():
    """Renderizza il menu utente nella sidebar."""
    user = get_current_user()
    
    if user:
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"### 👤 {user['name']}")
        st.sidebar.caption(f"Ruolo: {'🔧 Admin' if user['role'] == 'admin' else '📋 Auditor'}")
        
        if st.sidebar.button("🚪 Logout", use_container_width=True):
            logout()
            st.rerun()


# Inizializza file utenti se necessario
if not USERS_FILE.exists():
    create_default_users()
