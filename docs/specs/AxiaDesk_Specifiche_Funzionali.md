# AxiaDesk

**Specifiche Funzionali del Sistema**

*Gestionale operativo su misura per la gestione di pratiche multi-fase, scadenze ricorrenti, comunicazione interna e fornitori*

---

| | |
|---|---|
| **Versione** | 1.0 |
| **Data** | Aprile 2026 |
| **Sviluppato da** | axialoop |
| **Stack** | React 18 · TypeScript 5 · Supabase · PostgreSQL 15 |
| **Utenti** | 5 utenti simultanei — 3 ruoli (Admin, Responsabile, Operatore) |
| **Accesso** | Browser web, nessuna installazione richiesta |
| **Branding finale** | Personalizzato sul cliente — il sistema viene installato col nome scelto dal cliente seguito dal suffisso "Desk" (es. AcmeDesk, LogiDesk, QualityDesk) |

*Documento riservato — Proprietà axialoop*

---

# 1. Panoramica del Sistema

AxiaDesk è un gestionale web full-stack sviluppato interamente su misura per la gestione operativa di un organismo di certificazione ISO. Il sistema copre l'intero ciclo di vita di una pratica di certificazione: dall'apertura del contratto all'emissione del certificato, passando per la pianificazione dell'audit, la gestione documentale, le firme e il monitoraggio delle sorveglianze.

L'architettura è costruita attorno a un principio fondamentale: la logica di business risiede nel database, non nel frontend. Questo significa che le regole operative — workflow, prerequisiti, transizioni di fase, generazione automatica dei dati — sono implementate come trigger e funzioni PostgreSQL che operano indipendentemente dal codice applicativo. Qualsiasi client che tenti di interagire con il database, incluse chiamate API dirette, è soggetto alle stesse regole.

> **Il frontend è l'interfaccia. Il database è la legge.**

## Versatilità del Motore Operativo

Sebbene la prima istanza in produzione serva un organismo di certificazione ISO (auditor di terza parte), una seconda installazione è in fase di prototipazione per un'azienda manifatturiera del settore alimentare che utilizzerà il sistema per gestione scadenze ricorrenti, comunicazione interna tra reparti e gestione fornitori. Il motore di AxiaDesk è strutturalmente agnostico al dominio applicativo: le entità ("Pratica", "Tipologia", "Cliente", "Consulente") sono concetti generici che vengono ridefiniti nel linguaggio del cliente in fase di setup. La logica di workflow, le scadenze, le notifiche, gli allegati, la messaggistica interna e l'audit trail restano universali e invariati al cambiare del dominio.

> **Il motore è uno. I cataloghi cambiano.** Cambia il dizionario operativo, cambiano le tipologie di "pratica", cambiano i campi delle anagrafiche, cambiano le regole di scadenza ricorrente. Il software no.

## 1.1 Entità Principali

Il sistema gestisce quattro entità operative primarie e un insieme di entità di supporto:

| Entità | Descrizione | Relazioni chiave |
|---|---|---|
| Pratica | Unità di lavoro centrale. Rappresenta un progetto, una commessa, un contratto, un dossier o un intervento. Configurabile sul dominio del cliente; nella prima istanza è un contratto di certificazione su una norma specifica. | Appartiene a Cliente, ha Tipologie (M:N), è assegnata a un Utente, ha Allegati, Messaggi, Promemoria, Storico |
| Cliente | Anagrafica aziendale completa, con campi specifici aggiunti per dominio. Nella prima istanza include codice EA, NACE/ATECO, numero dipendenti (parametri ISO). In contesti industriali può includere certificazioni di prodotto, schede tecniche, dati fornitore. | Ha molte Pratiche, può essere gestito da un Consulente |
| Consulente | Intermediario o partner esterno. Può essere associato a una Pratica come canale di acquisizione o come fornitore di competenze specialistiche. | Collegato a Pratiche e a Tipologie di sua competenza |
| Utente | Operatore interno del sistema con ruolo (Admin / Responsabile / Operatore). | Assegnato a Pratiche, destinatario di Notifiche, autore di Messaggi |
| Tipologia | Catalogo configurabile sul dominio del cliente. Nella prima istanza contiene 17 norme ISO/EN; in altre installazioni può contenere tipologie di pratica legale, categorie di intervento, classi di prodotto, schemi di certificazione settoriali. Integrità referenziale con ON UPDATE CASCADE. | Collegata a Pratiche, Utenti responsabili, Consulenti |

---

# 2. Workflow Pratiche — Pipeline a 6 Stadi

Il workflow è la colonna vertebrale del sistema. Ogni pratica attraversa obbligatoriamente una sequenza di fasi definita. Non è possibile saltare fasi, invertire l'ordine di più di un passo, né far avanzare una pratica senza che i prerequisiti della fase siano soddisfatti.

Il workflow a 6 stadi è parametrico: la sequenza descritta sotto è la configurazione attuale per il dominio della certificazione ISO. La logica del motore è invariante: in altre installazioni le 6 fasi assumono nomi diversi (ad esempio "Apertura → Istruttoria → Verifica → Approvazione → Esecuzione → Chiusura" per uno studio professionale; oppure "Contatto → Sopralluogo → Preventivo → Lavori → Collaudo → Fatturazione" per un'azienda di servizi tecnici) senza modifiche al codice.

La sequenza è: Contratto Firmato → Programmazione Verifica → Richiesta Proforma → Elaborazione Pratica → Firme → Completata.

| # | Fase | Comportamento del sistema |
|---|---|---|
| 1 | Contratto Firmato | Apertura della pratica. Vengono registrati i dati anagrafici del cliente, la norma di certificazione, il tipo di ciclo (certificazione iniziale, sorveglianza o ricertificazione), il referente e l'eventuale consulente associato. Il sistema genera automaticamente un numero pratica univoco nel formato CERT-AAAA-XXXX, protetto da lock concorrenza per garantire unicità anche con più utenti simultanei. |
| 2 | Programmazione Verifica | Fase di pianificazione operativa. Vengono registrati la data dell'audit, la sede di verifica e l'auditor assegnato. Nessun avanzamento alla fase successiva è possibile senza che la data di verifica sia presente — vincolo imposto direttamente dal database, non aggirabile. |
| 3 | Richiesta Proforma | Il sistema traccia la richiesta e l'emissione della proforma fattura. I timestamp di richiesta e di emissione vengono registrati automaticamente. L'avanzamento alla fase successiva è bloccato finché la proforma non risulta emessa — validazione server-side, non client-side. |
| 4 | Elaborazione Pratica | Fase di raccolta documentale. Il sistema traccia il flag di ricezione documenti con timestamp. Finché i documenti non risultano ricevuti, il workflow blocca qualsiasi avanzamento verso la fase Firme — anche se l'operatore tenta di forzare l'aggiornamento via API diretta. |
| 5 | Firme | Fase conclusiva di firma della documentazione di certificazione. Da questa fase è possibile completare la pratica. Tutti i flag di fasi precedenti sono a questo punto protetti da un secondo trigger che impedisce di resettarli a false — l'integrità del percorso è permanente. |
| ✓ | Completata | Al completamento, il sistema esegue automaticamente nella stessa transazione di database: (1) imposta i campi data_completamento e flag completata, (2) genera un promemoria di sorveglianza a +365 giorni, (3) registra l'evento nello storico fasi. Tutto avviene atomicamente — o tutto o niente. |

## 2.1 Cicli Certificativi Supportati

Ogni pratica è classificata con uno dei quattro cicli certificativi del dominio ISO:

| Ciclo | Descrizione operativa |
|---|---|
| Certificazione | Prima certificazione del cliente su una norma. Ciclo completo dalla raccolta documenti all'emissione del certificato triennale. |
| Prima Sorveglianza | Prima verifica annuale post-certificazione. Verifica il mantenimento dei requisiti. Non emette nuovo certificato. |
| Seconda Sorveglianza | Seconda verifica annuale. Chiude il ciclo triennale prima della ricertificazione. |
| Ricertificazione | Rinnovo completo del certificato alla scadenza triennale. Equivale operativamente a una nuova certificazione. |

Il concetto di "ciclo" è anch'esso configurabile sul dominio del cliente. Nella prima istanza i cicli sono quelli triennali ISO. In altre installazioni i cicli possono rappresentare: "Ciclo qualità annuale", "Ciclo audit fornitore biennale", "Ciclo manutenzione programmata" per un'azienda manifatturiera; oppure "Pratica ordinaria", "Pratica complessa", "Consulenza ricorrente" per uno studio professionale. La struttura del ciclo (sequenza, durata, transizioni) resta la stessa; cambiano le etichette e i valori temporali.

## 2.2 Trigger di Validazione Database

Il comportamento del workflow è interamente governato da sei trigger PostgreSQL attivi sul database. Nessuno di questi è replicato o sostituibile dal frontend — operano come strato di enforcement definitivo:

| Trigger | Evento | Comportamento |
|---|---|---|
| `genera_numero_pratica` | BEFORE INSERT su pratiche | Genera il numero CERT-AAAA-XXXX con advisory lock PostgreSQL che serializza gli inserimenti concorrenti. Nessun numero duplicato è possibile, nemmeno con più utenti che aprono pratiche in simultanea. |
| `validate_fase_transition` | BEFORE UPDATE OF fase su pratiche | Valida ogni transizione di fase. Rifiuta salti di più di una fase, retrocessioni di più di un passo e qualsiasi modifica su pratiche non attive. Controlla i prerequisiti specifici per ogni fase (data verifica, proforma emessa, documenti ricevuti). Opera lato database: impossibile aggirare anche con chiamate API dirette. |
| `protect_fase_flags` | BEFORE UPDATE su pratiche | Impedisce il reset dei flag di fasi già superate. Una volta che proforma_emessa è true in fase 4+, non può tornare false. Idem per documenti_ricevuti in fase 5+. Garantisce l'integrità retroattiva del percorso. |
| `on_pratica_completata` | BEFORE UPDATE OF fase su pratiche | Al passaggio in fase 'completata': crea automaticamente nella stessa transazione il promemoria di sorveglianza a +365 giorni, con testo che include le norme della pratica. Imposta il flag sorveglianza_reminder_creato per evitare duplicati. |
| `log_cambio_fase` | AFTER UPDATE OF fase su pratiche | Registra ogni cambio di fase nello storico_fasi con fase precedente, fase nuova, utente e timestamp. Trigger AFTER: scrive solo se la transizione ha superato validate_fase_transition. Lo storico è append-only — nessun ruolo ha permessi UPDATE/DELETE su storico_fasi. |
| `update_updated_at` | BEFORE UPDATE su pratiche, clienti | Aggiorna automaticamente il campo updated_at ad ogni modifica. Garantisce tracciabilità temporale senza dipendere dal codice applicativo. |

> Ogni tentativo di bypassare il workflow — incluse chiamate API dirette con chiave anonima valida — viene rifiutato dal database con un errore esplicito. Il frontend può pre-validare per migliorare l'esperienza utente, ma non è mai la fonte di verità.

## 2.3 Quality Assurance e Verifica dei Trigger

Ogni trigger PostgreSQL descritto nella sezione 2.2 è coperto da una suite di test automatici eseguiti su un database di staging dedicato, isolato dall'ambiente di produzione. I test verificano sia il comportamento atteso (transizioni valide) sia il comportamento di rifiuto (tentativi di salto di fase, reset di flag protetti, inserimenti concorrenti). La suite viene eseguita automaticamente a ogni rilascio, garantendo che nessuna modifica al codice o allo schema possa alterare silenziosamente la logica di workflow.

La copertura minima garantita per i trigger critici è la seguente:

| Trigger | Scenari testati | Copertura |
|---|---|---|
| `genera_numero_pratica` | Unicità seriale, inserimenti concorrenti simulati | Positivo + concorrenza |
| `validate_fase_transition` | Ogni transizione valida, salti di fase, retrocessioni, prerequisiti mancanti, API diretta | Positivo + 5 scenari di rifiuto |
| `protect_fase_flags` | Reset di flag già impostati, tentativo via API diretta | Rifiuto garantito |
| `on_pratica_completata` | Creazione promemoria sorveglianza, atomicità della transazione, assenza di duplicati | Atomico + idempotente |

---

# 3. Moduli Funzionali

## 3.1 Dashboard KPI

La dashboard è la schermata principale del sistema. Si aggiorna automaticamente ogni 5 minuti senza ricaricare la pagina. I dati sono differenziati per ruolo: Admin e Responsabile vedono il quadro globale, l'Operatore vede esclusivamente i propri dati.

| Sezione | Contenuto | Comportamento |
|---|---|---|
| KPI Cards (4) | Pratiche Attive, Scadenze Critiche <15gg, Completate nel mese, Pratiche Bloccate. | Ogni card è cliccabile e porta alla lista pratiche filtrata per quella metrica. Mostra delta rispetto al mese precedente. |
| Scadenze Immediate | Lista compatta delle 5 pratiche con scadenza più vicina. | Colonne: cliente, norma, giorni rimanenti (badge colorato), fase attuale, accesso diretto. |
| Distribuzione per Fase | Conteggio pratiche per ciascuna delle 6 fasi. | Visione istantanea della distribuzione del carico operativo. |
| Pratiche Assegnate | Lista pratiche attive assegnate all'utente corrente. | Visibile solo agli Operatori. Admin e Responsabile vedono la distribuzione globale. |
| Ultime Attività | Feed cronologico degli ultimi 10 eventi di sistema: chi ha fatto cosa su quale pratica e quando. | Aggiornato in tempo reale. Fonte: tabella storico_fasi + eventi notifiche. |

## 3.2 Sistema di Notifiche Real-Time

Il sistema di notifiche è costruito su WebSocket tramite Supabase Realtime. Le notifiche sono recapitate istantaneamente a ogni utente connesso interessato all'evento. La subscription è filtrata per destinatario a livello database: nessun utente riceve notifiche destinate ad altri.

### Eventi che generano notifiche automatiche

- Avanzamento o retrocessione di fase di una pratica
- Assegnazione o riassegnazione di una pratica a un operatore
- Richiesta o emissione della proforma
- Ricezione documenti confermata
- Promemoria scaduto (generato dal job notturno)
- Completamento pratica

### Architettura di resilienza

La connessione WebSocket è monitorata continuamente con un heartbeat ogni 30 secondi. In caso di interruzione, il sistema implementa tre livelli di recupero:

- Tentativo di riconnessione automatica immediata
- Attivazione di un polling fallback ogni 60 secondi se la riconnessione non avviene
- Indicatore visivo in tempo reale dello stato della connessione (verde / arancione lampeggiante / rosso)

Le notifiche con tipo critico o richiesta generano automaticamente un toast visivo in alto a destra con auto-dismiss a 5 secondi, indipendentemente dalla schermata aperta.

## 3.3 Gestione Allegati

Ogni pratica dispone di un'area allegati con upload drag-and-drop. I file sono archiviati su Supabase Storage con path strutturato per pratica: `allegati-pratiche/{praticaId}/{uuid}-{nome_originale}`.

| Funzione | Dettaglio tecnico |
|---|---|
| Upload | Drag-and-drop o selezione file. Barra di avanzamento in tempo reale. Validazione client: max 50 MB, tipi MIME ammessi. Metadati salvati in tabella allegati con fase di riferimento, dimensione, tipo e utente che ha caricato. |
| Download | Genera un URL firmato con scadenza 5 minuti. Dopo la scadenza il link non è più valido. Non esiste accesso diretto al file senza autenticazione. |
| Sicurezza | Policy Supabase Storage che consentono la lettura solo agli utenti che hanno accesso alla pratica corrispondente. Nessun accesso anonimo. |
| Eliminazione | Disponibile per chi ha caricato il file o per l'Admin. Rimuove sia il record in tabella che il file fisico dallo storage nella stessa operazione. |
| Associazione | Ogni allegato è associabile a una fase specifica della pratica, consentendo di contestualizzare la documentazione nel percorso certificativo. |

## 3.4 Feed Messaggi Interno

Ogni pratica ha un feed di messaggi interni strutturato per tipo: commento, richiesta, risposta, sistema. I messaggi del tipo sistema sono generati automaticamente dagli eventi di workflow. Gli altri tipi sono scritti dagli operatori.

Il feed supporta messaggi con destinatario specifico (comunicazione privata tra due utenti nel contesto della pratica) o messaggi broadcast visibili a tutti i membri del team. I messaggi si aggiornano in tempo reale tramite Supabase Realtime. Gli allegati possono essere collegati direttamente a un messaggio.

## 3.5 Gestione Scadenze

La pagina Scadenze aggrega tutte le pratiche attive con data di scadenza e le ordina per urgenza crescente. Le pratiche sono classificate in tre fasce:

| Fascia | Criterio | Presentazione visiva |
|---|---|---|
| Critica | Scadenza entro 15 giorni | Badge rosso. Appare nella KPI card 'Scadenze Critiche' della dashboard. |
| Attenzione | Scadenza tra 16 e 45 giorni | Badge giallo. |
| Nella norma | Scadenza oltre 45 giorni | Badge verde. |

La tabella scadenze include una checklist operativa aggiornabile inline: i flag `data_verifica` impostata, `documenti_ricevuti`, `proforma_emessa` e `completata` sono modificabili con un singolo click direttamente nella riga, con salvataggio immediato su database senza aprire la scheda della pratica.

**Soglie configurabili per tipologia.** Le tre fasce (Critica / Attenzione / Nella norma) e le rispettive soglie temporali sono configurabili per tipologia di pratica. La configurazione 15/45 giorni descritta sopra è quella adottata per le pratiche di certificazione ISO. In altri domini le soglie cambiano: una taratura strumento può essere critica a 7 giorni, una manutenzione semestrale critica a 30 giorni, un rinnovo contratto fornitore critico a 60 giorni. Il sistema applica la regola corretta in base alla tipologia della singola pratica, senza modifiche al codice.

## 3.6 Promemoria e Sorveglianza Automatica

Il modulo promemoria funziona su due livelli: manuale e automatico.

### Promemoria manuali

Gli operatori possono creare promemoria su qualsiasi pratica, assegnarli a sé stessi o ad altri utenti, con data di scadenza. La pagina Promemoria globale mostra tutti i promemoria attivi dell'utente corrente ordinati per scadenza.

### Sorveglianza automatica

Al completamento di ogni pratica, il trigger `on_pratica_completata` crea nella stessa transazione atomica un promemoria di sorveglianza con scadenza a +365 giorni. Il testo del promemoria è generato dinamicamente e include le norme certificate e il numero della pratica.

### Job notturno (Edge Function schedulata)

Un job automatico eseguito ogni giorno alle 08:00 (ora italiana) svolge due funzioni: (1) individua pratiche completate senza promemoria sorveglianza e li crea retroattivamente come safety-net, (2) identifica i promemoria in scadenza o scaduti e genera le notifiche corrispondenti verso i destinatari. Il job opera server-side indipendentemente dagli utenti connessi.

**Intervalli ricorrenti configurabili.** L'intervallo di +365 giorni descritto sopra è la configurazione standard per la sorveglianza annuale ISO. È un parametro per tipologia: in altre installazioni può diventare +365 per rinnovo certificazione BRC, +180 per audit interno semestrale, +90 per controllo qualità trimestrale, +30 per ispezione mensile. La logica del trigger automatico e del job notturno di safety-net è universale; cambiano solo i valori temporali configurati per ciascuna tipologia di pratica.

## 3.7 Anagrafica Clienti e Consulenti

L'anagrafica clienti include oltre ai dati aziendali standard i campi specifici del dominio certificativo ISO:

- **Codice EA** (codice dell'attività economica per la certificazione)
- **Codice NACE/ATECO** (classificazione attività, rilevante per la durata degli audit)
- **Numero di dipendenti** (parametro che incide sul calcolo della durata minima dell'audit secondo gli schemi ISO)

L'anagrafica consulenti tiene traccia degli intermediari esterni con le norme di loro competenza, consentendo di filtrare e associare il consulente corretto a ogni pratica.

**Campi custom per dominio.** La scheda Cliente accoglie campi personalizzati in base al dominio dell'installazione. Per la certificazione ISO i campi specifici sono Codice EA, NACE/ATECO, numero dipendenti. Per un'azienda manifatturiera con fornitori da qualificare, i campi possono includere certificazioni di prodotto, schede tecniche aggiornate, dichiarazioni di conformità, audit fornitore più recente. L'anagrafica è estensibile via configurazione senza interventi sul codice.

## 3.8 Iris — Assistente Operativo Conversazionale

Iris è l'assistente conversazionale integrato in AxiaDesk. Accessibile da qualsiasi schermata tramite un pulsante flottante o lo shortcut da tastiera ⌘K (Ctrl+K su Windows), Iris permette agli operatori di interrogare il sistema in linguaggio naturale italiano per ottenere risposte, riepiloghi, aggregati operativi e ricerche puntuali senza dover navigare manualmente tra pratiche, filtri e schermate.

> Iris non è un chatbot generico calato dall'esterno. È un assistente operativo che lavora dentro i confini di sicurezza del sistema: vede esattamente i dati a cui l'utente che lo interroga ha accesso, e niente di più.

### Casi d'uso operativi

Iris è progettata per rispondere a domande che oggi richiederebbero più click e l'attraversamento di più schermate. Esempi di richieste reali supportate:

- "Quante pratiche ISO 9001 sono in scadenza nei prossimi 30 giorni?"
- "Mostrami tutte le pratiche assegnate a Mario Rossi negli ultimi tre mesi."
- "Riassumimi lo stato della pratica CERT-2026-0042: fase, flag, allegati, ultima attività."
- "Tempo medio di completamento delle pratiche di ricertificazione nel 2026."
- "Quale norma genera più scadenze critiche negli ultimi sei mesi?"
- "Quali clienti hanno più di due pratiche attive contemporaneamente?"
- "Promemoria in scadenza questa settimana raggruppati per responsabile."

Per le richieste analitiche Iris genera la risposta in testo, con tabelle inline quando appropriato. Per i risultati di ricerca strutturati, ogni pratica citata è cliccabile e porta direttamente al dettaglio.

### Architettura

Iris opera come strato conversazionale sopra il sistema esistente, senza duplicare logica di business o dati. La pipeline di una richiesta segue quattro passaggi:

1. La domanda dell'utente raggiunge una Edge Function dedicata (`iris-bridge`) insieme al token JWT della sessione corrente.
2. La Edge Function inoltra la richiesta al modello linguistico ospitato su Azure OpenAI Service insieme al registro degli strumenti operativi disponibili.
3. Il modello individua quali strumenti operativi attivare (ad esempio `query_pratiche`, `get_kpi_dashboard`, `search_clienti`, `summarize_pratica`) e con quali parametri.
4. La Edge Function esegue gli strumenti operativi richiesti contro il database Supabase usando il JWT dell'utente — la Row Level Security applica le stesse restrizioni che si applicherebbero a una navigazione manuale. Il risultato viene restituito al modello, che produce la risposta finale in linguaggio naturale.

### Strumenti operativi disponibili a Iris

| Strumento | Funzione |
|---|---|
| `query_pratiche` | Filtra pratiche per stato, fase, scadenza, cliente, norma, assegnatario |
| `get_kpi_dashboard` | Aggregati KPI con stesso filtro per ruolo della Dashboard |
| `search_clienti` | Ricerca anagrafica clienti con match su nome, P.IVA, codice EA |
| `get_scadenze` | Lista scadenze ordinate per urgenza con classificazione critica/attenzione |
| `summarize_pratica` | Riepilogo strutturato di una pratica: fasi, flag, allegati, storico |
| `cerca_negli_allegati` | Ricerca semantica sui contenuti dei documenti allegati |
| `analizza_trend` | Aggregati temporali su pratiche completate, durate medie, distribuzioni |

Ogni strumento è eseguito server-side con il contesto di sicurezza dell'utente richiedente. Un operatore che chiede a Iris "tutte le pratiche attive" riceve esclusivamente le proprie, esattamente come accade nella schermata Pratiche.

### Storia conversazionale persistente

Le conversazioni di ciascun utente sono persistenti nel database (tabella `iris_conversations`, soggetta a RLS per utente). Questo consente di riprendere una conversazione dal punto in cui era stata interrotta e di mantenere il contesto tra una domanda e la successiva ("e di quelle, quante sono già state firmate?" funziona perché Iris ricorda di cosa stava parlando).

Ogni conversazione è soggetta al medesimo audit log dello storico_fasi: ogni interazione registra utente, timestamp, domanda, strumenti operativi invocati e parametri. Questo costituisce parte della tracciabilità del trattamento dei dati ai sensi dell'art. 30 GDPR.

### Disponibilità per ruolo

Iris è disponibile per tutti e tre i ruoli del sistema (Admin, Responsabile, Operatore) con visibilità dei dati identica a quella del ruolo:

- l'Admin può chiedere aggregati su tutte le pratiche e tutti gli utenti
- il Responsabile vede aggregati globali ma non la gestione utenti
- l'Operatore riceve risposte limitate alle pratiche a lui assegnate

L'Admin può, dalla schermata di configurazione, disattivare Iris per specifici ruoli se richiesto dal cliente.

---

# 4. Architettura di Sicurezza

## 4.1 Row Level Security (RLS)

Ogni tabella del database ha la Row Level Security abilitata. Le policy definiscono con precisione quali righe ciascun ruolo può leggere, inserire, modificare o eliminare. La funzione helper `get_user_role()` è dichiarata SECURITY DEFINER con REVOKE su PUBLIC e GRANT solo agli utenti autenticati — impedisce che gli utenti leggano direttamente la propria riga di profilo per determinare il ruolo.

| Ruolo | Descrizione accessi e permessi |
|---|---|
| Admin | Accesso completo senza restrizioni. Vede e modifica tutte le pratiche, tutti gli utenti, tutte le configurazioni. Può annullare e sospendere pratiche con registrazione del motivo e del timestamp. Unico ruolo con accesso alla configurazione del sistema. |
| Responsabile | Visibilità completa su tutte le pratiche del sistema. Può modificare pratiche non assegnate ad altri operatori. Non accede alla gestione utenti e configurazioni di sistema. |
| Operatore | Accesso esclusivamente alle pratiche con il proprio UUID nel campo assegnato_a. Questa restrizione è applicata da una Row Level Security policy sul database: anche accedendo direttamente all'API Supabase con credenziali valide, un operatore non può leggere né scrivere dati di pratiche altrui. |

> La separazione dei dati tra operatori non è una scelta di interfaccia — è un vincolo fisico del database. Un operatore con credenziali valide che chiama direttamente l'API Supabase riceve solo e soltanto le righe che la RLS gli permette di vedere.

## 4.2 Sicurezza degli Allegati

I file allegati non sono accessibili via URL statico. L'unico modo per accedere a un file è generare un URL firmato tramite la funzione Supabase Storage, che: (1) verifica l'autenticazione dell'utente richiedente, (2) verifica che l'utente abbia accesso alla pratica corrispondente, (3) genera un URL con firma crittografica valida 5 minuti. Dopo la scadenza, il link non funziona.

## 4.3 Sicurezza del Frontend

Il frontend non contiene mai la chiave service_role di Supabase — solo la chiave anonima pubblica `VITE_SUPABASE_ANON_KEY`. Tutte le operazioni privilegiate avvengono tramite funzioni SECURITY DEFINER nel database. Il Content Security Policy è configurato sull'Nginx del VPS per prevenire injection di script esterni.

## 4.4 Storico Immutabile

La tabella `storico_fasi` è append-only per design: nessun ruolo, incluso Admin, ha permessi UPDATE o DELETE su questa tabella. Ogni cambio di fase è permanentemente registrato con utente, timestamp, fase precedente e fase nuova. Questo crea un audit trail inviolabile dell'intero percorso di ogni pratica.

## 4.5 Sicurezza Conversazionale di Iris

Iris è soggetta agli stessi controlli di sicurezza del resto del sistema, con misure specifiche per la natura conversazionale del servizio.

### Accesso ai dati conforme a RLS

Ogni strumento operativo invocato da Iris è eseguito con il JWT della sessione utente corrente. Le query risultanti attraversano Row Level Security esattamente come una qualsiasi interazione manuale dell'utente. Questo significa che è impossibile per Iris esporre dati a cui l'utente non ha accesso — la barriera è applicata a livello di database, non di prompt engineering.

> Nessuna istruzione, contesto o "prompt injection" può aggirare la Row Level Security. Anche se un utente tentasse di chiedere a Iris di "ignorare le restrizioni di ruolo", le query generate riceverebbero comunque solo le righe che l'RLS gli permette di vedere.

### Provider del modello e localizzazione

Iris utilizza il modello linguistico ospitato su Azure OpenAI Service, region West Europe (data center Amsterdam). I dati delle conversazioni non lasciano mai lo Spazio Economico Europeo. Il rapporto contrattuale prevede il Data Processing Addendum standard di Microsoft Corporation con clausole specifiche per il settore certificativo.

Il contratto include la disattivazione dell'Abuse Monitoring di Microsoft (opt-out richiedibile via modulo standard a Microsoft) — nessun prompt o risposta è ispezionato manualmente da personale del provider.

### Audit log conversazionale

Ogni interazione con Iris registra in modo permanente:

- identità dell'utente che ha posto la domanda
- timestamp della richiesta
- testo integrale della domanda
- strumenti operativi invocati e relativi parametri
- righe del database lette per la risposta (riferimento agli ID, non al contenuto integrale)
- testo della risposta generata

Questo registro è append-only, accessibile esclusivamente all'Admin e costituisce prova della tracciabilità dei trattamenti automatizzati ai sensi dell'art. 30 GDPR.

### Confini operativi

Iris è progettata per la lettura analitica e operativa. Non esegue azioni distruttive (eliminazione di pratiche, modifica di fasi, archiviazione) in modo autonomo. Eventuali richieste di operazioni di scrittura vengono trasformate in suggerimenti operativi che l'utente deve confermare esplicitamente nell'interfaccia. Questa scelta è coerente con il principio generale del sistema: il workflow critico passa per validazione esplicita, non per agenti autonomi.

---

# 5. Modello di Deploy: Istanza Privata Dedicata

AxiaDesk non è un servizio SaaS condiviso. Ogni cliente riceve un'istanza completamente isolata, installata su server privato dedicato in territorio europeo, con il proprio database, le proprie credenziali, le proprie chiavi crittografiche, i propri log, il proprio dominio. Non esiste account multi-tenant: ogni installazione è un ambiente a sé stante.

## 5.1 Single-Tenant per Design

La scelta di un modello single-tenant non è un dettaglio tecnico ma una decisione architetturale di fondo. Tre i motivi:

- **Isolamento totale dei dati** — nessun rischio di contaminazione cross-tenant, anche in caso di errore software o compromissione di una singola istanza. Le organizzazioni che utilizzano AxiaDesk non condividono mai memoria, processo, database o filesystem con dati di altre organizzazioni.
- **Personalizzazione senza vincoli** — il prodotto può essere adattato sul dominio specifico del cliente (prompt di Iris, catalogo tipologie, regole di scadenza, anagrafiche custom) senza che le modifiche impattino altre installazioni.
- **Sovranità del cliente sui propri dati** — al collaudo del sistema, il codice sorgente e le credenziali infrastrutturali vengono trasferiti al cliente (vedi § 8.4). Il cliente è effettivamente proprietario di ciò che usa.

## 5.2 Componenti dell'istanza dedicata

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

## 5.3 Conseguenze pratiche

- **Audit indipendenti** — il cliente può commissionare penetration test, valutazioni di conformità, valutazioni di impatto privacy (DPIA) sulla propria istanza, in totale autonomia, senza autorizzazioni di terzi.
- **Continuità operativa autonoma** — eventuali aggiornamenti o manutenzioni programmate sono concordati con il singolo cliente e non sono mai imposti da finestre di servizio condivise.
- **Tracciabilità GDPR semplificata** — il registro dei trattamenti del cliente (art. 30 GDPR) può fare riferimento a un sub-responsabile unico (Axialoop) e a un'infrastruttura geograficamente identificabile, senza la complessità di mappare flussi di dati cross-tenant.
- **Conformità ISO 27001 / SOC 2 facilitata** — l'isolamento single-tenant elimina alla radice una classe di controlli richiesti per piattaforme multi-tenant.

> Multi-tenant condiviso: compromesso sui costi, rischio sui dati. Single-tenant dedicato: controllo totale, conformità totale. AxiaDesk sceglie il secondo per default.

---

# 6. Stack Tecnologico

Il sistema è costruito interamente con tecnologie open-source o con licenze permissive (MIT, Apache 2.0). Nessuna dipendenza proprietaria che possa generare lock-in tecnologico o costi di licenza aggiuntivi.

| Layer | Tecnologia | Ruolo nel sistema |
|---|---|---|
| Frontend | React 18 + TypeScript 5 | Interfaccia web moderna, tipizzazione stretta (zero any), compilazione statica senza runtime server. |
| UI Components | Shadcn UI + Tailwind CSS | Componenti accessibili e stilizzati, coerenti su tutti i browser e dispositivi. |
| State & Data | TanStack Query v5 | Cache intelligente, refetch automatico, optimistic updates. I dati rimangono sincronizzati senza ricaricare la pagina. |
| Validazione | React Hook Form + Zod | Validazione schema-based sia client-side che server-side. Nessun dato malformato raggiunge il database. |
| Database | PostgreSQL 15 via Supabase | Database relazionale con trigger, funzioni, advisory lock, Row Level Security e indici ottimizzati. |
| Auth | Supabase Auth | Gestione sessioni, token JWT, refresh automatico. Nessuna credenziale nel codice. |
| Storage | Supabase Storage | File archiviati su object storage con policy di accesso granulari per pratica. |
| Realtime | Supabase Realtime (WebSocket) | Notifiche e aggiornamenti istantanei tra tutti gli utenti connessi, con heartbeat e fallback polling. |
| Edge Functions | Deno (Supabase Edge Functions) | Job schedulato notturno per promemoria scaduti e safety-net sorveglianza. Eseguito server-side, indipendente dai client connessi. |
| AI Layer | Azure OpenAI Service (GPT-4o) | Modello linguistico di Iris. Region West Europe (Amsterdam). Embeddings (text-embedding-3-small) per ricerca semantica su norme e allegati, persistiti via pgvector su Supabase. |
| Hosting | Hetzner VPS + Nginx | Server dedicato in Europa, build statica servita via Nginx con Content Security Policy headers. |
| Routing | Cloudflare Tunnel / DuckDNS | Accesso HTTPS senza esporre porte, senza costo di dominio dedicato. |

## 6.1 Database — Schema

Il database PostgreSQL 15 comprende 11 tabelle principali, con le seguenti caratteristiche di design:

- UUID come chiavi primarie su tutte le tabelle (`gen_random_uuid()`)
- Soft delete tramite flag attivo = false dove applicabile
- Campi `created_at` / `updated_at` su ogni tabella, aggiornati da trigger
- Tabelle di giunzione con FK ON UPDATE CASCADE per le relazioni norme (`pratiche_norme`, `responsabili_norme`, `consulenti_norme`)
- Indici composti su (fase, assegnato_a), (stato, fase) e (destinatario_id, letta) per le query più frequenti
- Advisory lock `pg_advisory_xact_lock` per la generazione serializzata dei numeri pratica

## 6.2 Infrastruttura

Il sistema è ospitato su infrastruttura dedicata e isolata:

| Componente | Specifiche |
|---|---|
| VPS Hetzner CX22 | Ubuntu 24.04, 2 vCPU, 4 GB RAM, 40 GB SSD — data center EU-Central (Germania) |
| Backup automatici | Snapshot giornalieri del VPS (politica Hetzner) |
| Supabase Cloud Pro | Database PostgreSQL, Auth, Storage, Realtime, Edge Functions |
| Azure OpenAI Service | GPT-4o + text-embedding-3-small, region West Europe. Modello pay-per-use a consumo per il backend conversazionale di Iris. |
| DNS + HTTPS | DuckDNS o Cloudflare Tunnel — accesso HTTPS senza dominio dedicato |
| Email notifiche | Resend — tier gratuito fino a 3.000 email/mese |

## 6.3 Strategia di Backup e Recovery

Il sistema implementa una strategia di backup su due livelli indipendenti, garantendo la recuperabilità dei dati sia in caso di guasto infrastrutturale che in caso di corruzione logica del database.

### Livello 1 — Snapshot VPS (Hetzner)

Hetzner esegue snapshot giornalieri dell'intero VPS (configurazione, codice applicativo, Nginx). Consente il ripristino completo del server in caso di guasto hardware o errore di configurazione, con granularità giornaliera.

### Livello 2 — Point-in-Time Recovery (Supabase Pro)

Supabase Cloud Pro include il Point-in-Time Recovery (PITR) del database PostgreSQL con finestra di 7 giorni e granularità al secondo. In caso di eliminazione accidentale di dati, corruzione logica o errore operativo, è possibile ripristinare il database a qualsiasi istante nei 7 giorni precedenti senza perdita di dati intermedi. Il PITR opera indipendentemente dagli snapshot VPS e copre esclusivamente il layer database, incluse tutte le tabelle, i trigger e lo storico fasi. Il ripristino avviene su un'istanza separata per consentire la verifica dei dati prima del rientro in produzione.

---

# 7. Catalogo Configurabile

Il catalogo delle tipologie di pratica gestite dal sistema è configurabile per istanza. Nella prima installazione in produzione (organismo di certificazione ISO) il catalogo contiene i 17 standard più richiesti dagli organismi italiani.

Le tipologie sono entità referenziate con vincoli di integrità referenziale: non è possibile eliminare una tipologia in uso, e qualsiasi modifica al codice si propaga automaticamente a tutte le entità collegate tramite ON UPDATE CASCADE. Ogni tipologia è collegabile a pratiche, a utenti responsabili e a consulenti tramite tabelle di giunzione dedicate. Questo consente query come: "tutte le pratiche ISO 9001 assegnate a questo auditor", "tutti i consulenti certificati su ISO 27001", oppure — in altri domini — "tutti gli audit fornitori scaduti da rinnovare", "tutti gli interventi di manutenzione completati nell'ultimo trimestre".

### Catalogo della prima installazione (17 norme ISO/EN)

| | |
|---|---|
| · ISO 9001 — Sistemi di gestione della qualità | · ISO 13009 — Operatori balneari |
| · ISO 14001 — Gestione ambientale | · ISO 30415 — Diversità e inclusione HR |
| · ISO 45001 — Salute e sicurezza sul lavoro | · ISO 3834 — Qualità saldatura metalli |
| · ISO 27001 — Sicurezza delle informazioni | · EN 1090 — Strutture in acciaio e alluminio |
| · ISO 50001 — Gestione dell'energia | · SA 8000 — Responsabilità sociale d'impresa |
| · ISO 37001 — Sistemi anti-corruzione | · PDR 125/2022 — Parità di genere |
| · ISO 39001 — Sicurezza stradale | · PAS 24000 — Gestione sociale (SMS) |
| · ISO 14064-1 — Emissioni di gas serra | · ESG-EASI — Sostenibilità e responsabilità |
| · ISO 20121 — Sostenibilità degli eventi | |

### Esempi di catalogo per altri domini applicativi

Lo stesso sistema, in altre installazioni, ospita cataloghi diversi configurati sul dominio del cliente:

**Industria manifatturiera (es. settore alimentare):** Certificazione BRC, IFS Food, ISO 22000, IFS Logistic, BIO, Kosher, Halal, Audit Fornitore Materie Prime, Audit Fornitore Packaging, Verifica HACCP, Taratura Strumenti di Misura, Manutenzione Impianto Programmata.

**Studio professionale:** Pratica ordinaria, Pratica complessa, Consulenza ricorrente, Contenzioso, Pareristica.

**Azienda di servizi tecnici:** Sopralluogo, Progettazione, Esecuzione, Collaudo, Manutenzione programmata, Intervento straordinario.

**Studio di ingegneria:** Progetto strutturale, Pratica edilizia, Direzione lavori, Collaudo, Pratica ambientale, Pratica antincendio.

In tutti i casi, le tipologie del catalogo determinano il workflow applicabile, le regole di scadenza ricorrente, i campi delle anagrafiche correlate e gli strumenti di Iris disponibili.

---

# 8. Accesso e Utilizzo

## 8.1 Modalità di Accesso

AxiaDesk è accessibile da qualsiasi browser moderno (Chrome, Firefox, Edge, Safari) senza installazioni. L'accesso avviene tramite URL HTTPS con autenticazione tramite email e password. Le sessioni sono gestite con token JWT con refresh automatico — l'utente rimane autenticato senza dover effettuare nuovamente il login a ogni visita.

## 8.2 Compatibilità

L'interfaccia è costruita con Tailwind CSS e componenti responsive. È utilizzabile su desktop, laptop e smartphone. Su dispositivi mobili l'interfaccia si adatta automaticamente al viewport, mantenendo la piena operatività di tutte le funzioni.

## 8.3 Configurabilità per Istanza

Il sistema è personalizzabile tramite variabili d'ambiente senza modificare il codice: nome dell'organismo (`VITE_APP_NAME`), denominazione visualizzata (`VITE_CLIENTE_NAME`), colore primario (`VITE_PRIMARY_COLOR`), URL del logo (`VITE_LOGO_URL`).

**Nome del prodotto installato.** Il nome finale del sistema installato presso il cliente è scelto dal cliente stesso. La convenzione standard adottata è: **nome dell'organizzazione del cliente + suffisso "Desk"** (esempi: AcmeDesk, LogiDesk, QualityDesk, FoodOpsDesk). Questo consente al cliente di presentare il sistema come uno strumento proprio, integrato nel proprio brand, mantenendo coerenza visiva con la propria identità aziendale. La denominazione "AxiaDesk" utilizzata in questo documento è la denominazione interna del prodotto da parte dello sviluppatore.

## 8.4 Proprietà del Codice Sorgente

Al completamento e al collaudo del sistema, l'integrità del codice sorgente viene trasferita integralmente al cliente. La consegna include il repository completo (frontend React/TypeScript, funzioni Edge, script di migrazione database e configurazioni infrastrutturali), le credenziali di accesso all'istanza Supabase e al VPS Hetzner intestate al cliente, e la documentazione tecnica necessaria per la gestione autonoma del sistema.

Il cliente può liberamente modificare, estendere, affidare a terzi la manutenzione o integrare il sistema con altri strumenti. axialoop non trattiene alcun diritto sul codice specifico sviluppato per questa commessa.

---

# 9. Conformità e Protezione dei Dati

Il sistema tratta dati aziendali di clienti e operatori nell'ambito di processi di certificazione ISO. Le scelte architetturali descritte in questo documento sono coerenti con i principi del Regolamento (UE) 2016/679 (GDPR) e con le prassi di sicurezza applicabili agli organismi di certificazione. Di seguito le misure implementate per ciascuna area di conformità.

| Principio GDPR | Implementazione nel sistema |
|---|---|
| Minimizzazione dei dati | Il sistema raccoglie esclusivamente i dati necessari alla gestione del ciclo certificativo (art. 5.1.c GDPR). Nessun dato personale dei clienti finali dell'organismo viene trattato: le anagrafiche riguardano esclusivamente persone giuridiche. |
| Integrità e riservatezza | Tutti i dati sono cifrati in transito (HTTPS/TLS) e a riposo (cifratura Supabase a livello storage). La Row Level Security garantisce che ciascun operatore acceda esclusivamente ai dati di propria competenza (art. 25 GDPR — privacy by design). |
| Tracciabilità dei trattamenti | Lo storico fasi append-only costituisce un registro immutabile di ogni operazione sulle pratiche, con autore e timestamp. I campi updated_at aggiornati da trigger garantiscono la tracciabilità temporale di ogni modifica su clienti e pratiche (art. 5.1.f GDPR). |
| Localizzazione dei dati | Il VPS Hetzner è situato nel data center EU-Central (Germania). Supabase Cloud Pro può essere configurato sulla region eu-central-1 (Francoforte). Tutti i dati rimangono all'interno dello Spazio Economico Europeo, in conformità con l'art. 44 GDPR. |
| Controllo degli accessi | Il sistema di ruoli (Admin, Responsabile, Operatore) con separazione fisica via RLS implementa il principio del minimo privilegio. Le credenziali sono gestite tramite Supabase Auth con token JWT a scadenza: nessuna password è conservata in chiaro nel database. |
| Trattamenti automatizzati (art. 22 GDPR) | Iris opera esclusivamente come strumento di lettura analitica e non assume decisioni vincolanti per gli interessati. Il modello linguistico è ospitato su Azure OpenAI Service in region West Europe (EU) sotto Data Processing Addendum Microsoft EU. È attivata la clausola di opt-out dall'Abuse Monitoring: nessun prompt o risposta è ispezionato dal provider. Le conversazioni sono persistite nel database soggetto a Row Level Security per utente. |

## 9.1 Modello di Responsabilità a Tre Livelli

AxiaDesk opera in una catena di responsabilità chiaramente definita ai sensi degli articoli 4 e 28 GDPR.

| Ruolo | Soggetto | Obblighi principali |
|---|---|---|
| Interessato | Persona fisica i cui dati possono comparire nei contenuti del sistema (operatori interni del cliente) | Nessun obbligo; titolare di diritti ai sensi degli artt. 15–22 GDPR |
| Titolare del trattamento | Cliente che installa AxiaDesk per le proprie attività operative | Base giuridica, informativa, DPA con il responsabile, gestione richieste interessati |
| Responsabile del trattamento | Axialoop di Di Lonardo Alessandro (sviluppatore e gestore tecnico) | Misure tecniche e organizzative, audit trail, notifica violazioni, riservatezza, istruzioni documentate dal titolare |
| Sub-responsabili | Microsoft Azure (Iris — solo se attivato), Hetzner (hosting), Supabase (database), Resend (email) | Coperti da DPA standard EU; nessun trasferimento extra-UE |

## 9.2 Diritti degli Interessati

Il sistema supporta tecnicamente l'esercizio dei diritti previsti dagli articoli 15–22 GDPR. Le richieste degli interessati sono indirizzate primariamente al titolare (cliente), il quale può richiedere ad Axialoop l'assistenza tecnica necessaria.

| Diritto | Supporto tecnico fornito |
|---|---|
| Art. 15 — Accesso | Export su richiesta dei dati relativi all'interessato dalle tabelle pertinenti (utenti, storico fasi, messaggi) |
| Art. 16 — Rettifica | Modifica diretta tramite interfaccia o, per dati storici, intervento amministrativo tracciato |
| Art. 17 — Cancellazione | Procedura di hard-delete su richiesta del titolare entro 72 ore, con conservazione del solo record di audit anonimizzato |
| Art. 18 — Limitazione | Sospensione operativa di utenti specifici via flag amministrativo |
| Art. 20 — Portabilità | Export in formato standard (JSON, CSV) di tutti i dati riferibili a un interessato |

## 9.3 Posizione su Training di Modelli AI

I contenuti gestiti dal sistema e — quando Iris è attivo — i prompt e le risposte conversazionali **non vengono utilizzati per addestrare modelli di intelligenza artificiale**, né da Axialoop né da Microsoft. Questo è garantito contrattualmente da Microsoft per Azure OpenAI Service tramite il Microsoft Products and Services Data Protection Addendum. Inoltre, sull'istanza di Iris è attivata la clausola di opt-out dall'Abuse Monitoring di Microsoft: nessun prompt o risposta è ispezionato manualmente da personale del provider.

## 9.4 Procedura di Notifica Violazioni (Art. 33 GDPR)

In caso di violazione dei dati personali rilevata dal responsabile (Axialoop) o segnalata dal titolare (cliente), la procedura formalizzata prevede:

1. **Detection** — identificazione della violazione tramite monitoraggio degli audit log, segnalazione operativa o evidenza tecnica
2. **Containment** — isolamento dell'incidente, sospensione delle componenti compromesse, mitigazione immediata
3. **Notifica al titolare** — comunicazione al cliente entro 24 ore dalla conoscenza dell'evento, con descrizione della natura della violazione, categorie e numero approssimativo di interessati coinvolti, conseguenze probabili, misure adottate
4. **Supporto al titolare** — assistenza tecnica per la valutazione del rischio e per l'eventuale notifica al Garante e agli interessati (artt. 33 e 34 GDPR), oneri a carico del titolare
5. **Post-mortem documentato** — analisi delle cause, azioni correttive, aggiornamento delle misure tecniche e organizzative

---

*axialoop · Documento riservato · Versione 1.0 · Aprile 2026*

*Header ricorrente: axialoop · AxiaDesk — Specifiche Funzionali*

*Footer ricorrente: Documento riservato — Proprietà axialoop*
