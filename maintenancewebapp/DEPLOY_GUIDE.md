# 🚀 Deploy Guide - Procedure di Deployment

## Workflow Standard per Implementare Modifiche

### Step 1: Modifica i File Localmente

Tutti i file sorgente sono in:
```
c:\Users\user\AUDITORSEMI\webapp\
```

Modifica i file necessari usando gli strumenti di editing disponibili.

### Step 2: Sincronizza i File sul Server

Usa `pscp` per caricare i file modificati:

```powershell
# Esempio: caricare checklist_producer.py
pscp -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "c:\Users\user\AUDITORSEMI\webapp\modules\checklist_producer.py" auditos@49.13.153.117:/opt/auditos/webapp/modules/checklist_producer.py

# Esempio: caricare app.py
pscp -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "c:\Users\user\AUDITORSEMI\webapp\app.py" auditos@49.13.153.117:/opt/auditos/webapp/app.py

# Esempio: caricare un prompt
pscp -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "c:\Users\user\AUDITORSEMI\webapp\prompts\checklist\ISO_9001_webapp.md" auditos@49.13.153.117:/opt/auditos/webapp/prompts/checklist/ISO_9001_webapp.md
```

### Step 3: Verifica il Caricamento

Controlla che il file sia stato caricato correttamente:

```powershell
# Verifica numero righe
plink -ssh auditos@49.13.153.117 -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "wc -l /opt/auditos/webapp/modules/checklist_producer.py"

# Verifica presenza di una stringa specifica
plink -ssh auditos@49.13.153.117 -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "grep 'STRINGA_DA_CERCARE' /opt/auditos/webapp/modules/checklist_producer.py"
```

### Step 4: ⚠️ RIAVVIA IL SERVIZIO (OBBLIGATORIO!)

**QUESTO STEP È FONDAMENTALE!**

La webapp usa una **cache in memoria** per i prompt e il codice Python. Senza riavvio, le modifiche NON vengono applicate.

```powershell
plink -ssh auditos@49.13.153.117 -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "echo 'AuditOS_Admin_2026!' | sudo -S systemctl restart auditos"
```

### Step 5: Verifica che il Servizio sia Attivo

```powershell
plink -ssh auditos@49.13.153.117 -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "systemctl status auditos --no-pager | head -10"
```

Output atteso:
```
● auditos.service - AUDIT-OS Streamlit Application
     Loaded: loaded (/etc/systemd/system/auditos.service; enabled)
     Active: active (running) since [TIMESTAMP RECENTE]
```

---

## Errori Comuni e Soluzioni

### "Le modifiche non funzionano"
**Causa**: Servizio non riavviato
**Soluzione**: Esegui `sudo systemctl restart auditos`

### "Caratteri strani (????) al posto degli emoji"
**Causa**: File caricato con `type | plink` che corrompe UTF-8
**Soluzione**: Usa sempre `pscp` per caricare file

### "Permission denied"
**Causa**: Comando sudo senza password
**Soluzione**: Usa `echo 'PASSWORD' | sudo -S comando`
