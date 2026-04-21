# 🔐 Server Access - Credenziali e Accesso

## Informazioni Server

| Campo | Valore |
|-------|--------|
| **Provider** | Hetzner |
| **IP Address** | `49.13.153.117` |
| **SSH User** | `auditos` |
| **SSH Password** | `AuditOS_Admin_2026!` |
| **SSH Port** | 22 (default) |
| **Hostkey Fingerprint** | `SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk` |

## Percorsi Chiave sul Server

| Percorso | Descrizione |
|----------|-------------|
| `/opt/auditos/webapp/` | Directory principale webapp |
| `/opt/auditos/webapp/app.py` | File principale Streamlit |
| `/opt/auditos/webapp/modules/` | Moduli Python (checklist_producer, etc.) |
| `/opt/auditos/webapp/prompts/` | Prompt per le varie norme ISO |
| `/opt/auditos/webapp/venv/` | Virtual environment Python |

## Comandi SSH Pronti all'Uso (Windows con PuTTY)

### Connessione Interattiva
```powershell
plink -ssh auditos@49.13.153.117 -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk"
```

### Eseguire Comando Singolo
```powershell
plink -ssh auditos@49.13.153.117 -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "COMANDO_DA_ESEGUIRE"
```

### Caricare File sul Server (PSCP)
```powershell
pscp -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "C:\percorso\locale\file.py" auditos@49.13.153.117:/opt/auditos/webapp/modules/file.py
```

### Verificare Stato Servizio
```powershell
plink -ssh auditos@49.13.153.117 -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "systemctl status auditos --no-pager"
```

### Riavviare Servizio (OBBLIGATORIO dopo modifiche)
```powershell
plink -ssh auditos@49.13.153.117 -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "echo 'AuditOS_Admin_2026!' | sudo -S systemctl restart auditos"
```

## Note Importanti

- Il parametro `-hostkey` è OBBLIGATORIO per evitare prompt interattivi di conferma
- Usare sempre `pscp` (non `type | plink`) per preservare encoding UTF-8
- La password contiene caratteri speciali, racchiuderla sempre tra virgolette
