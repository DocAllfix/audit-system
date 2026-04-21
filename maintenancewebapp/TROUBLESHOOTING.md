# 🔧 Troubleshooting - Problemi Comuni e Soluzioni

## Problema: Le modifiche non vengono applicate

### Sintomi
- Hai modificato un file e caricato sul server
- Gli utenti continuano a vedere il comportamento vecchio
- Solo alcuni utenti vedono le modifiche (es. admin sì, clienti no)

### Causa
La webapp usa una **cache in memoria** che viene popolata all'avvio. Le modifiche ai file non vengono lette fino al riavvio.

### Soluzione
```powershell
plink -ssh auditos@49.13.153.117 -pw "AuditOS_Admin_2026!" -hostkey "SHA256:NfmjGcIHw9JV9OSUxYHQeSLPku0Js0aigYqn/60qGqk" "echo 'AuditOS_Admin_2026!' | sudo -S systemctl restart auditos"
```

---

## Problema: Caratteri strani (????) invece di emoji

### Sintomi
- Gli emoji come 🔄 ✅ ⚠️ appaiono come ????
- Accade dopo aver caricato file Python

### Causa
Usare `type file.py | plink ... "cat > file.py"` corrompe l'encoding UTF-8 su Windows.

### Soluzione
Usare sempre `pscp` per caricare file:
```powershell
pscp -pw "PASSWORD" -hostkey "HOSTKEY" "file_locale" user@server:/percorso/remoto
```

---

## Problema: Nome azienda troncato nel nome file

### Sintomi
- "Emmeci Appalti" diventa "Emm" o "Emmeci"
- Il nome nel contenuto delle clausole è corretto

### Causa
Le funzioni di estrazione nome usavano regex lazy o prompt non specifici.

### Soluzione
Le funzioni `extract_company_metadata()` e `extract_company_from_clauses()` sono state riscritte per richiedere esplicitamente il nome COMPLETO. Assicurarsi che il server abbia la versione aggiornata e riavviare il servizio.

---

## Problema: Citazioni di file / numeri tra parentesi nelle clausole

### Sintomi
- Le clausole contengono "(1)", "(2)" o riferimenti a file
- Violazione vincoli inderogabili dei prompt

### Causa
1. Prompt vecchi in cache (riavviare servizio)
2. Temperatura troppo alta (dovrebbe essere 0.0 o 0.1)

### Soluzione
1. Verificare temperatura nel codice:
```powershell
plink ... "grep 'temperature' /opt/auditos/webapp/modules/checklist_producer.py"
```
2. Riavviare il servizio

---

## Problema: La webapp non risponde

### Sintomi
- La pagina non carica
- Errore 502 o timeout

### Verifica stato
```powershell
plink ... "systemctl status auditos --no-pager"
```

### Se il servizio è down
```powershell
plink ... "echo 'PASSWORD' | sudo -S systemctl start auditos"
```

### Controlla i log
```powershell
plink ... "sudo journalctl -u auditos -n 50 --no-pager"
```

---

## Problema: Errore "Permission denied" con sudo

### Causa
Il comando sudo richiede password interattiva.

### Soluzione
Usare l'opzione `-S` per leggere la password da stdin:
```bash
echo 'PASSWORD' | sudo -S comando
```

---

## Comandi Utili per Debug

### Vedere ultimi log del servizio
```powershell
plink ... "sudo journalctl -u auditos -n 100 --no-pager"
```

### Verificare spazio disco
```powershell
plink ... "df -h"
```

### Verificare memoria
```powershell
plink ... "free -h"
```

### Verificare processi Python
```powershell
plink ... "ps aux | grep python"
```
