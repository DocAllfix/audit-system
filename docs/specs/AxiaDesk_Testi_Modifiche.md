# AxiaDesk — Testi per Modifica del Documento PlianceDesk

> Questo file contiene i testi pronti per essere inseriti nel documento PlianceDesk esistente.
> Le modifiche sono organizzate sezione per sezione. Sostituzioni globali ed espansioni puntuali.
> Layout, colori, font: invariati dal documento originale.

---

## SOSTITUZIONE GLOBALE PRELIMINARE

Sostituisci ovunque nel documento:

- `PlianceDesk` → `AxiaDesk`

Punti specifici dove appare:
- Titolo copertina (riga "PlianceDesk")
- Header ripetuto di ogni pagina ("axialoop · PlianceDesk — Specifiche Funzionali" → "axialoop · AxiaDesk — Specifiche Funzionali")
- Sezione 1, primo paragrafo ("PlianceDesk è un gestionale web full-stack...")
- Sezione 3.8 Iris ("Iris è l'assistente conversazionale integrato in PlianceDesk...")
- Sezione 7.1 ("PlianceDesk è accessibile da qualsiasi browser...")

---

## COPERTINA

### Sottotitolo grande (sotto al titolo "AxiaDesk")

**Da:**
> Specifiche Funzionali del Sistema

**A (invariato):**
> Specifiche Funzionali del Sistema

### Riga descrittiva (sotto al sottotitolo, in corsivo grigio)

**Da:**
> Gestionale CRM su misura per Organismi di Certificazione ISO

**A:**
> Gestionale operativo su misura per la gestione di pratiche multi-fase, scadenze ricorrenti, comunicazione interna e fornitori

### Tabella metadati copertina

**Aggiungi una riga in fondo alla tabella esistente:**

| Branding finale | Personalizzato sul cliente — il sistema viene installato col nome scelto dal cliente seguito dal suffisso "Desk" (es. AcmeDesk, LogiDesk, QualityDesk) |

---

## SEZIONE 1 — PANORAMICA DEL SISTEMA

### Primo paragrafo

**Mantieni invariato:**
> AxiaDesk è un gestionale web full-stack sviluppato interamente su misura per la gestione operativa di un organismo di certificazione ISO. Il sistema copre l'intero ciclo di vita di una pratica di certificazione: dall'apertura del contratto all'emissione del certificato, passando per la pianificazione dell'audit, la gestione documentale, le firme e il monitoraggio delle sorveglianze.

### Secondo paragrafo

**Mantieni invariato:**
> L'architettura è costruita attorno a un principio fondamentale: la logica di business risiede nel database, non nel frontend. Questo significa che le regole operative — workflow, prerequisiti, transizioni di fase, generazione automatica dei dati — sono implementate come trigger e funzioni PostgreSQL che operano indipendentemente dal codice applicativo. Qualsiasi client che tenti di interagire con il database, incluse chiamate API dirette, è soggetto alle stesse regole.

### Callout esistente

**Mantieni invariato:**
> Il frontend è l'interfaccia. Il database è la legge.

### **NUOVO PARAGRAFO — da inserire DOPO il callout, PRIMA della sezione 1.1 Entità Principali:**

> **Versatilità del Motore Operativo**
>
> Sebbene la prima istanza in produzione serva un organismo di certificazione ISO (auditor di terza parte), una seconda installazione è in fase di prototipazione per un'azienda manifatturiera del settore alimentare che utilizzerà il sistema per gestione scadenze ricorrenti, comunicazione interna tra reparti e gestione fornitori. Il motore di AxiaDesk è strutturalmente agnostico al dominio applicativo: le entità ("Pratica", "Tipologia", "Cliente", "Consulente") sono concetti generici che vengono ridefiniti nel linguaggio del cliente in fase di setup. La logica di workflow, le scadenze, le notifiche, gli allegati, la messaggistica interna e l'audit trail restano universali e invariati al cambiare del dominio.

### **NUOVO CALLOUT — da inserire SUBITO DOPO il paragrafo precedente:**

> Il motore è uno. I cataloghi cambiano. Cambia il dizionario operativo, cambiano le tipologie di "pratica", cambiano i campi delle anagrafiche, cambiano le regole di scadenza ricorrente. Il software no.

---

## SEZIONE 1.1 — ENTITÀ PRINCIPALI

### Tabella Entità

**Sostituisci le descrizioni con queste versioni neutralizzate** (mantieni le colonne e l'impaginazione attuale):

| Entità | Descrizione | Relazioni chiave |
|---|---|---|
| Pratica | Unità di lavoro centrale. Rappresenta un progetto, una commessa, un contratto, un dossier o un intervento. Configurabile sul dominio del cliente; nella prima istanza è un contratto di certificazione su una norma specifica. | Appartiene a Cliente, ha Tipologie (M:N), è assegnata a un Utente, ha Allegati, Messaggi, Promemoria, Storico |
| Cliente | Anagrafica aziendale completa, con campi specifici aggiunti per dominio. Nella prima istanza include codice EA, NACE/ATECO, numero dipendenti (parametri ISO). In contesti industriali può includere certificazioni di prodotto, schede tecniche, dati fornitore. | Ha molte Pratiche, può essere gestito da un Consulente |
| Consulente | Intermediario o partner esterno. Può essere associato a una Pratica come canale di acquisizione o come fornitore di competenze specialistiche. | Collegato a Pratiche e a Tipologie di sua competenza |
| Utente | Operatore interno del sistema con ruolo (Admin / Responsabile / Operatore). | Assegnato a Pratiche, destinatario di Notifiche, autore di Messaggi |
| Tipologia | Catalogo configurabile sul dominio del cliente. Nella prima istanza contiene 17 norme ISO/EN; in altre installazioni può contenere tipologie di pratica legale, categorie di intervento, classi di prodotto, schemi di certificazione settoriali. Integrità referenziale con ON UPDATE CASCADE. | Collegata a Pratiche, Utenti responsabili, Consulenti |

**Nota di traduzione:** la voce "Norma" del documento attuale viene rinominata "Tipologia" per riflettere la natura generica dell'entità. Il termine "Norma" resta valido come configurazione specifica nel dominio di certificazione ISO.

---

## SEZIONE 2 — WORKFLOW PRATICHE — PIPELINE A 6 STADI

### Primo paragrafo

**Mantieni invariato:**
> Il workflow è la colonna vertebrale del sistema. Ogni pratica attraversa obbligatoriamente una sequenza di fasi definita. Non è possibile saltare fasi, invertire l'ordine di più di un passo, né far avanzare una pratica senza che i prerequisiti della fase siano soddisfatti.

### **NUOVO PARAGRAFO — da inserire SUBITO DOPO il primo paragrafo:**

> Il workflow a 6 stadi è parametrico: la sequenza descritta sotto è la configurazione attuale per il dominio della certificazione ISO. La logica del motore è invariante: in altre installazioni le 6 fasi assumono nomi diversi (ad esempio "Apertura → Istruttoria → Verifica → Approvazione → Esecuzione → Chiusura" per uno studio professionale; oppure "Contatto → Sopralluogo → Preventivo → Lavori → Collaudo → Fatturazione" per un'azienda di servizi tecnici) senza modifiche al codice.

### Riga sequenza fasi

**Mantieni invariato:**
> La sequenza è: Contratto Firmato → Programmazione Verifica → Richiesta Proforma → Elaborazione Pratica → Firme → Completata.

### Tabella 6 fasi

**Mantieni invariata.**

---

## SEZIONE 2.1 — CICLI CERTIFICATIVI SUPPORTATI

### Tabella cicli ISO

**Mantieni invariata.**

### **NUOVO PARAGRAFO — da inserire DOPO la tabella esistente:**

> Il concetto di "ciclo" è anch'esso configurabile sul dominio del cliente. Nella prima istanza i cicli sono quelli triennali ISO (Certificazione, Sorveglianza I, Sorveglianza II, Ricertificazione). In altre installazioni i cicli possono rappresentare: "Ciclo qualità annuale", "Ciclo audit fornitore biennale", "Ciclo manutenzione programmata" per un'azienda manifatturiera; oppure "Pratica ordinaria", "Pratica complessa", "Consulenza ricorrente" per uno studio professionale. La struttura del ciclo (sequenza, durata, transizioni) resta la stessa; cambiano le etichette e i valori temporali.

---

## SEZIONE 2.2 — TRIGGER DI VALIDAZIONE DATABASE

**Mantieni invariata.**

---

## SEZIONE 2.3 — QUALITY ASSURANCE E VERIFICA DEI TRIGGER

**Mantieni invariata.**

---

## SEZIONE 3 — MODULI FUNZIONALI

### Sezione 3.1 Dashboard KPI

**Mantieni invariata.**

### Sezione 3.2 Sistema di Notifiche Real-Time

**Mantieni invariata.**

### Sezione 3.3 Gestione Allegati

**Mantieni invariata.**

### Sezione 3.4 Feed Messaggi Interno

**Mantieni invariata.**

### Sezione 3.5 Gestione Scadenze

**Mantieni invariato fino alla fine della sezione.**

### **NUOVO PARAGRAFO — da inserire IN FONDO alla sezione 3.5, DOPO l'ultimo testo esistente:**

> **Soglie configurabili per tipologia.** Le tre fasce (Critica / Attenzione / Nella norma) e le rispettive soglie temporali sono configurabili per tipologia di pratica. La configurazione 15/45 giorni descritta sopra è quella adottata per le pratiche di certificazione ISO. In altri domini le soglie cambiano: una taratura strumento può essere critica a 7 giorni, una manutenzione semestrale critica a 30 giorni, un rinnovo contratto fornitore critico a 60 giorni. Il sistema applica la regola corretta in base alla tipologia della singola pratica, senza modifiche al codice.

### Sezione 3.6 Promemoria e Sorveglianza Automatica

**Mantieni invariato fino alla fine della sottosezione "Job notturno".**

### **NUOVO PARAGRAFO — da inserire IN FONDO alla sezione 3.6, DOPO il blocco "Job notturno":**

> **Intervalli ricorrenti configurabili.** L'intervallo di +365 giorni descritto sopra è la configurazione standard per la sorveglianza annuale ISO. È un parametro per tipologia: in altre installazioni può diventare +365 per rinnovo certificazione BRC, +180 per audit interno semestrale, +90 per controllo qualità trimestrale, +30 per ispezione mensile. La logica del trigger automatico e del job notturno di safety-net è universale; cambiano solo i valori temporali configurati per ciascuna tipologia di pratica.

### Sezione 3.7 Anagrafica Clienti e Consulenti

**Mantieni invariato il testo esistente.**

### **NUOVO PARAGRAFO — da inserire IN FONDO alla sezione 3.7, DOPO il testo esistente:**

> **Campi custom per dominio.** La scheda Cliente accoglie campi personalizzati in base al dominio dell'installazione. Per la certificazione ISO i campi specifici sono Codice EA, NACE/ATECO, numero dipendenti. Per un'azienda manifatturiera con fornitori da qualificare, i campi possono includere certificazioni di prodotto, schede tecniche aggiornate, dichiarazioni di conformità, audit fornitore più recente. L'anagrafica è estensibile via configurazione senza interventi sul codice.

### Sezione 3.8 Iris — Assistente Operativo Conversazionale

**Mantieni TUTTA la sezione INVARIATA**, incluso tutto il contenuto su:
- Casi d'uso operativi
- Architettura (4 passaggi)
- Tabella "Strumenti operativi disponibili a Iris"
- Storia conversazionale persistente
- Disponibilità per ruolo

(Sostituire solo `PlianceDesk` → `AxiaDesk` ove compare nel testo.)

---

## SEZIONE 4 — ARCHITETTURA DI SICUREZZA

### Sezioni 4.1, 4.2, 4.3, 4.4

**Mantieni invariate.**

### Sezione 4.5 Sicurezza Conversazionale di Iris

**Mantieni TUTTA la sezione INVARIATA**, inclusi:
- Accesso ai dati conforme a RLS
- Provider del modello e localizzazione
- Audit log conversazionale
- Confini operativi

---

## ⚠️ NUOVA SEZIONE — DA INSERIRE TRA L'ATTUALE § 4 E L'ATTUALE § 5

### § 5 — Modello di Deploy: Istanza Privata Dedicata

(Le sezioni successive del documento attuale scalano: vecchia 5 → nuova 6, vecchia 6 → nuova 7, vecchia 7 → nuova 8, vecchia 8 → nuova 9.)

### Testo introduttivo della sezione

> AxiaDesk non è un servizio SaaS condiviso. Ogni cliente riceve un'istanza completamente isolata, installata su server privato dedicato in territorio europeo, con il proprio database, le proprie credenziali, le proprie chiavi crittografiche, i propri log, il proprio dominio. Non esiste account multi-tenant: ogni installazione è un ambiente a sé stante.

### Sottosezione 5.1 — Single-Tenant per Design

> La scelta di un modello single-tenant non è un dettaglio tecnico ma una decisione architetturale di fondo. Tre i motivi:
>
> - **Isolamento totale dei dati** — nessun rischio di contaminazione cross-tenant, anche in caso di errore software o compromissione di una singola istanza. Le organizzazioni che utilizzano AxiaDesk non condividono mai memoria, processo, database o filesystem con dati di altre organizzazioni.
> - **Personalizzazione senza vincoli** — il prodotto può essere adattato sul dominio specifico del cliente (prompt di Iris, catalogo tipologie, regole di scadenza, anagrafiche custom) senza che le modifiche impattino altre installazioni.
> - **Sovranità del cliente sui propri dati** — al collaudo del sistema, il codice sorgente e le credenziali infrastrutturali vengono trasferiti al cliente (vedi § 8.4). Il cliente è effettivamente proprietario di ciò che usa.

### Sottosezione 5.2 — Componenti dell'istanza dedicata

| Componente | Dettaglio |
|---|---|
| Server VPS dedicato | Hetzner Cloud, datacenter EU-Central (Germania), accesso amministrativo riservato |
| Database | PostgreSQL 15 via Supabase — istanza dedicata, nessuna condivisione di schema o tabelle |
| Storage allegati | Bucket Supabase Storage dedicato, policy di accesso esclusive al cliente |
| Dominio | Sottodominio personalizzato (es. `clientedesk.app`) o dominio cliente custom |
| Branding | Nome visualizzato, logo, colore primario, denominazione organizzazione — tutto configurabile via variabili d'ambiente |
| Backup | Snapshot VPS giornalieri + Point-in-Time Recovery PostgreSQL a 7 giorni, indipendenti per istanza |
| Iris (opzionale) | Risorsa Azure OpenAI dedicata al tenant, region West Europe |
| Notifiche email | Account Resend dedicato, dominio mittente personalizzato |

### Sottosezione 5.3 — Conseguenze pratiche

> - **Audit indipendenti** — il cliente può commissionare penetration test, valutazioni di conformità, valutazioni di impatto privacy (DPIA) sulla propria istanza, in totale autonomia, senza autorizzazioni di terzi.
> - **Continuità operativa autonoma** — eventuali aggiornamenti o manutenzioni programmate sono concordati con il singolo cliente e non sono mai imposti da finestre di servizio condivise.
> - **Tracciabilità GDPR semplificata** — il registro dei trattamenti del cliente (art. 30 GDPR) può fare riferimento a un sub-responsabile unico (Axialoop) e a un'infrastruttura geograficamente identificabile, senza la complessità di mappare flussi di dati cross-tenant.
> - **Conformità ISO 27001 / SOC 2 facilitata** — l'isolamento single-tenant elimina alla radice una classe di controlli richiesti per piattaforme multi-tenant.

### Callout di chiusura per la nuova sezione 5

> Multi-tenant condiviso: compromesso sui costi, rischio sui dati. Single-tenant dedicato: controllo totale, conformità totale. AxiaDesk sceglie il secondo per default.

---

## ⚠️ RINUMERAZIONE — DA QUI IN POI

Le sezioni che seguono nel documento originale erano numerate 5, 6, 7, 8. Con l'inserimento della nuova § 5, diventano:

- Vecchia **§ 5 Stack Tecnologico** → nuova **§ 6 Stack Tecnologico**
- Vecchia **§ 6 Catalogo Norme — 17 Standard Supportati** → nuova **§ 7 Catalogo Configurabile**
- Vecchia **§ 7 Accesso e Utilizzo** → nuova **§ 8 Accesso e Utilizzo**
- Vecchia **§ 8 Conformità e Protezione dei Dati** → nuova **§ 9 Conformità e Protezione dei Dati**

---

## SEZIONE 6 (era 5) — STACK TECNOLOGICO

### Tabella stack tecnologico

**Mantieni invariata.**

### Sottosezione 6.1 Database — Schema

**Mantieni invariata.**

### ⚠️ Sottosezione 6.2 — Infrastruttura

**Modifica importante: RIMUOVI la colonna "Costo mensile" dalla tabella infrastruttura.**

Tabella aggiornata (senza colonna costi):

| Componente | Specifiche |
|---|---|
| VPS Hetzner CX22 | Ubuntu 24.04, 2 vCPU, 4 GB RAM, 40 GB SSD — data center EU-Central (Germania) |
| Backup automatici | Snapshot giornalieri del VPS (politica Hetzner) |
| Supabase Cloud Pro | Database PostgreSQL, Auth, Storage, Realtime, Edge Functions |
| Azure OpenAI Service | GPT-4o + text-embedding-3-small, region West Europe. Modello pay-per-use a consumo per il backend conversazionale di Iris. |
| DNS + HTTPS | DuckDNS o Cloudflare Tunnel — accesso HTTPS senza dominio dedicato |
| Email notifiche | Resend — tier gratuito fino a 3.000 email/mese |

**Rimuovi inoltre l'ultima riga "Totale infrastruttura ~48-60 €/mese".**

### Sottosezione 6.3 Strategia di Backup e Recovery

**Mantieni invariata, con una piccola correzione:**

Nel blocco "Livello 1 — Snapshot VPS (Hetzner)", **rimuovi l'inciso tra parentesi** che cita il costo:
- **Da:** "Costo incluso nella voce backup automatici (0,91 €/mese)."
- **A:** rimuovi la frase intera. Il paragrafo diventa: "Hetzner esegue snapshot giornalieri dell'intero VPS (configurazione, codice applicativo, Nginx). Consente il ripristino completo del server in caso di guasto hardware o errore di configurazione, con granularità giornaliera."

---

## SEZIONE 7 (era 6) — CATALOGO CONFIGURABILE

### **Riscrittura del titolo della sezione**

**Da:**
> 6. Catalogo Norme — 17 Standard Supportati

**A:**
> 7. Catalogo Configurabile

### Nuovo paragrafo introduttivo (sostituisce quello esistente)

**Da rimuovere:**
> Il catalogo norme è preconfigurato nel database con i 17 standard più richiesti dagli organismi di certificazione italiani. Le norme sono entità referenziate con vincoli di integrità referenziale: non è possibile eliminare una norma in uso, e qualsiasi modifica al codice si propaga automaticamente a tutte le entità collegate tramite ON UPDATE CASCADE.

**Sostituire con:**

> Il catalogo delle tipologie di pratica gestite dal sistema è configurabile per istanza. Nella prima installazione in produzione (organismo di certificazione ISO) il catalogo contiene i 17 standard più richiesti dagli organismi italiani.
>
> Le tipologie sono entità referenziate con vincoli di integrità referenziale: non è possibile eliminare una tipologia in uso, e qualsiasi modifica al codice si propaga automaticamente a tutte le entità collegate tramite ON UPDATE CASCADE. Ogni tipologia è collegabile a pratiche, a utenti responsabili e a consulenti tramite tabelle di giunzione dedicate. Questo consente query come: "tutte le pratiche ISO 9001 assegnate a questo auditor", "tutti i consulenti certificati su ISO 27001", oppure — in altri domini — "tutti gli audit fornitori scaduti da rinnovare", "tutti gli interventi di manutenzione completati nell'ultimo trimestre".

### Tabella delle 17 norme ISO

**Mantieni invariata.**

### **NUOVO BLOCCO — da inserire DOPO la tabella delle 17 norme:**

> **Esempi di catalogo per altri domini applicativi**
>
> Lo stesso sistema, in altre installazioni, ospita cataloghi diversi configurati sul dominio del cliente:
>
> **Industria manifatturiera (es. settore alimentare):** Certificazione BRC, IFS Food, ISO 22000, IFS Logistic, BIO, Kosher, Halal, Audit Fornitore Materie Prime, Audit Fornitore Packaging, Verifica HACCP, Taratura Strumenti di Misura, Manutenzione Impianto Programmata.
>
> **Studio professionale:** Pratica ordinaria, Pratica complessa, Consulenza ricorrente, Contenzioso, Pareristica.
>
> **Azienda di servizi tecnici:** Sopralluogo, Progettazione, Esecuzione, Collaudo, Manutenzione programmata, Intervento straordinario.
>
> **Studio di ingegneria:** Progetto strutturale, Pratica edilizia, Direzione lavori, Collaudo, Pratica ambientale, Pratica antincendio.
>
> In tutti i casi, le tipologie del catalogo determinano il workflow applicabile, le regole di scadenza ricorrente, i campi delle anagrafiche correlate e gli strumenti di Iris disponibili.

---

## SEZIONE 8 (era 7) — ACCESSO E UTILIZZO

### Sottosezioni 8.1, 8.2

**Mantieni invariate.**

### Sottosezione 8.3 — Configurabilità per Istanza

**Mantieni il testo esistente** che descrive le variabili d'ambiente.

### **NUOVO PARAGRAFO — da inserire IN FONDO alla sezione 8.3, DOPO il testo esistente:**

> **Nome del prodotto installato.** Il nome finale del sistema installato presso il cliente è scelto dal cliente stesso. La convenzione standard adottata è: **nome dell'organizzazione del cliente + suffisso "Desk"** (esempi: AcmeDesk, LogiDesk, QualityDesk, FoodOpsDesk). Questo consente al cliente di presentare il sistema come uno strumento proprio, integrato nel proprio brand, mantenendo coerenza visiva con la propria identità aziendale. La denominazione "AxiaDesk" utilizzata in questo documento è la denominazione interna del prodotto da parte dello sviluppatore.

### Sottosezione 8.4 Proprietà del Codice Sorgente

**Mantieni invariata.**

---

## SEZIONE 9 (era 8) — CONFORMITÀ E PROTEZIONE DEI DATI

### Testo introduttivo

**Mantieni invariato** il paragrafo introduttivo della sezione.

### Tabella GDPR esistente

**Mantieni invariata.**

### **NUOVA SOTTOSEZIONE — da inserire DOPO la tabella GDPR esistente:**

> **9.1 Modello di Responsabilità a Tre Livelli**
>
> AxiaDesk opera in una catena di responsabilità chiaramente definita ai sensi degli articoli 4 e 28 GDPR.

| Ruolo | Soggetto | Obblighi principali |
|---|---|---|
| Interessato | Persona fisica i cui dati possono comparire nei contenuti del sistema (operatori interni del cliente) | Nessun obbligo; titolare di diritti ai sensi degli artt. 15–22 GDPR |
| Titolare del trattamento | Cliente che installa AxiaDesk per le proprie attività operative | Base giuridica, informativa, DPA con il responsabile, gestione richieste interessati |
| Responsabile del trattamento | Axialoop di Di Lonardo Alessandro (sviluppatore e gestore tecnico) | Misure tecniche e organizzative, audit trail, notifica violazioni, riservatezza, istruzioni documentate dal titolare |
| Sub-responsabili | Microsoft Azure (Iris — solo se attivato), Hetzner (hosting), Supabase (database), Resend (email) | Coperti da DPA standard EU; nessun trasferimento extra-UE |

### **NUOVA SOTTOSEZIONE — da inserire SUBITO DOPO la 9.1:**

> **9.2 Diritti degli Interessati**
>
> Il sistema supporta tecnicamente l'esercizio dei diritti previsti dagli articoli 15–22 GDPR. Le richieste degli interessati sono indirizzate primariamente al titolare (cliente), il quale può richiedere ad Axialoop l'assistenza tecnica necessaria.

| Diritto | Supporto tecnico fornito |
|---|---|
| Art. 15 — Accesso | Export su richiesta dei dati relativi all'interessato dalle tabelle pertinenti (utenti, storico fasi, messaggi) |
| Art. 16 — Rettifica | Modifica diretta tramite interfaccia o, per dati storici, intervento amministrativo tracciato |
| Art. 17 — Cancellazione | Procedura di hard-delete su richiesta del titolare entro 72 ore, con conservazione del solo record di audit anonimizzato |
| Art. 18 — Limitazione | Sospensione operativa di utenti specifici via flag amministrativo |
| Art. 20 — Portabilità | Export in formato standard (JSON, CSV) di tutti i dati riferibili a un interessato |

### **NUOVA SOTTOSEZIONE — da inserire SUBITO DOPO la 9.2:**

> **9.3 Posizione su Training di Modelli AI**
>
> I contenuti gestiti dal sistema e — quando Iris è attivo — i prompt e le risposte conversazionali **non vengono utilizzati per addestrare modelli di intelligenza artificiale**, né da Axialoop né da Microsoft. Questo è garantito contrattualmente da Microsoft per Azure OpenAI Service tramite il Microsoft Products and Services Data Protection Addendum. Inoltre, sull'istanza di Iris è attivata la clausola di opt-out dall'Abuse Monitoring di Microsoft: nessun prompt o risposta è ispezionato manualmente da personale del provider.

### **NUOVA SOTTOSEZIONE FINALE — da inserire IN FONDO alla sezione 9:**

> **9.4 Procedura di Notifica Violazioni (Art. 33 GDPR)**
>
> In caso di violazione dei dati personali rilevata dal responsabile (Axialoop) o segnalata dal titolare (cliente), la procedura formalizzata prevede:
>
> 1. **Detection** — identificazione della violazione tramite monitoraggio degli audit log, segnalazione operativa o evidenza tecnica
> 2. **Containment** — isolamento dell'incidente, sospensione delle componenti compromesse, mitigazione immediata
> 3. **Notifica al titolare** — comunicazione al cliente entro 24 ore dalla conoscenza dell'evento, con descrizione della natura della violazione, categorie e numero approssimativo di interessati coinvolti, conseguenze probabili, misure adottate
> 4. **Supporto al titolare** — assistenza tecnica per la valutazione del rischio e per l'eventuale notifica al Garante e agli interessati (artt. 33 e 34 GDPR), oneri a carico del titolare
> 5. **Post-mortem documentato** — analisi delle cause, azioni correttive, aggiornamento delle misure tecniche e organizzative

---

## FOOTER E HEADER FINALI

### Header ogni pagina

**Da:**
> axialoop · PlianceDesk — Specifiche Funzionali

**A:**
> axialoop · AxiaDesk — Specifiche Funzionali

### Footer ogni pagina

**Mantieni invariato:**
> Documento riservato — Proprietà axialoop

### Linea finale dopo la tabella GDPR (era già presente nel documento)

**Mantieni invariata:**
> axialoop · Documento riservato · Versione 1.0 · Aprile 2026

---

## RIEPILOGO CHANGELOG

Modifiche al documento PlianceDesk per ottenere AxiaDesk:

1. **Sostituzione globale** `PlianceDesk` → `AxiaDesk` (tutti i contesti)
2. **Sottotitolo copertina** aggiornato per riflettere uso multi-dominio
3. **Riga "Branding finale"** aggiunta ai metadati copertina
4. **Sezione 1**: nuovo paragrafo "Versatilità del Motore Operativo" + nuovo callout
5. **Sezione 1.1**: tabella entità neutralizzata, "Norma" rinominata "Tipologia"
6. **Sezione 2**: nuovo paragrafo sulla parametricità del workflow
7. **Sezione 2.1**: nuovo paragrafo sulla configurabilità dei cicli
8. **Sezione 3.5**: nuovo paragrafo sulle soglie scadenza configurabili
9. **Sezione 3.6**: nuovo paragrafo sugli intervalli ricorrenti configurabili
10. **Sezione 3.7**: nuovo paragrafo sui campi anagrafica custom per dominio
11. **NUOVA SEZIONE 5**: "Modello di Deploy: Istanza Privata Dedicata" (3 sottosezioni + callout)
12. **Rinumerazione** sezioni successive (5→6, 6→7, 7→8, 8→9)
13. **Sezione 6.2** (era 5.2): rimossa colonna "Costo mensile" + ultima riga totale
14. **Sezione 6.3** (era 5.3): rimosso inciso costo nello "Snapshot VPS"
15. **Sezione 7** (era 6): titolo cambiato in "Catalogo Configurabile", nuovo paragrafo introduttivo, nuovo blocco "Esempi di catalogo per altri domini"
16. **Sezione 8.3** (era 7.3): nuovo paragrafo sulla nomenclatura `<NomeCliente>Desk`
17. **Sezione 9** (era 8): nuove sottosezioni 9.1 (Modello di Responsabilità), 9.2 (Diritti Interessati), 9.3 (Posizione AI Training), 9.4 (Notifica Violazioni)

**Cosa è rimasto invariato:**
- Architettura logica, principi di sistema, callout originali
- Sezioni 2.2 (Trigger), 2.3 (QA Trigger)
- Tutta la sezione 3.8 (Iris)
- Tutta la sezione 4.5 (Sicurezza Iris)
- Tabelle 6 fasi, Cicli, Trigger, KPI, Allegati, Scadenze, Stack
- Sezione 4 (Sicurezza completa)
- Layout, colori, font, callout, footer
