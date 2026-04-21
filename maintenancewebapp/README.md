# 🔧 AUDIT-OS Webapp Maintenance Guide

Questa cartella contiene tutte le informazioni necessarie per accedere al server Hetzner e implementare modifiche alla webapp AUDIT-OS.

## 📁 Contenuto

- `SERVER_ACCESS.md` - Credenziali e comandi per accedere al server
- `DEPLOY_GUIDE.md` - Procedure per sincronizzare file e riavviare il servizio
- `ARCHITECTURE.md` - Struttura dell'applicazione e file chiave
- `TROUBLESHOOTING.md` - Problemi comuni e soluzioni

## ⚠️ REGOLA FONDAMENTALE

**Dopo OGNI modifica ai file Python o ai prompt, è OBBLIGATORIO riavviare il servizio:**

```bash
sudo systemctl restart auditos
```

Senza questo restart, le modifiche NON vengono applicate perché la webapp usa una cache in memoria.
