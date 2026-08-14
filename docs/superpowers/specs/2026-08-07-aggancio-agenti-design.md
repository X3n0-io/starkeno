# StarkEno — Aggancio agli agenti e forma di distribuzione (design)

> Data: 2026-08-07. Costruisce sopra la v1 già su `main`.
>
> **Sostituisce un'ipotesi SaaS formulata e scartata lo stesso giorno.** StarkEno sarà un
> **plugin di Claude Code, open source su GitHub**: niente autenticazione, niente multi-tenancy,
> niente fatturazione. La forma scelta è quella **senza processi sempre accesi**.
>
> Le misure citate qui sono state prese il 07/08/2026 su 115 transcript reali e sono registrate
> nel `CLAUDE.md`, sezione «Prima esecuzione con dati veri». Questo documento non le ripete: le usa.
>
> ⚠️ **I quattro punti del §9 sono stati sciolti lo stesso giorno da
> `2026-08-07-il-conto-al-centro-design.md`, su una campagna di misura 4× più grande.**
> Questo documento resta valido su **come i dati entrano** — hook, grana, identità, schema,
> errori, dove vivono i dati. Il §9 va letto come storia, non come lavoro da fare, e il §9.4
> è ribaltato: la dashboard non è l'ultima questione aperta, è il centro del prodotto.

---

## 1. Il problema che questo design risolve

La v1 è completa, verde e migrata, ma **nessun agente logga**: il database di produzione contiene
una riga sola, uno smoke test del 04/08. Il compito dichiarato della v1 — raccogliere dati veri per
tarare le soglie — è fermo su un passo che nessun piano conteneva.

La causa non era una svista: mancava una risposta alla domanda «chi chiama `log_agent_action`?».
Questo documento la dà, e nel darla cambia anche la forma con cui il progetto si distribuisce.

## 2. Il principio che regge tutto: l'agente non sa quanto spende

`log_agent_action` pretende dal chiamante quattro numeri — `tokens_used`, `cache_read_tokens`,
`cache_write_tokens`, `output_tokens`. **Un agente non può conoscerli**: il proprio consumo non gli
viene mai mostrato mentre lavora. Chiederglieli significa ottenere valori inventati o assenti, e far
ragionare R2, R3 e R4 su numeri fabbricati credendoli misure.

I numeri esistono altrove: **nel transcript che Claude Code scrive già da sé**. Misurato: 3.191
righe con `model` e `usage`, e `usage` contiene esattamente i quattro campi necessari, più i blocchi
`tool_use` con nome e parametro — cioè il `categoria:dettaglio` che serve a R1.

**Conseguenza:** la fonte dei dati è il transcript, letto da un automatismo. Non l'agente.
È l'invariante 4 del progetto applicata un livello più su: *la parte che non deve fallire non si
lascia in mano a chi può dimenticarsene.*

## 3. Architettura

Nessun processo resta acceso. Due hook e una skill, dentro un plugin.

```
   fine di ogni turno              inizio di ogni sessione            su richiesta
        │                                   │                              │
        ▼                                   ▼                              ▼
  hook di ingestione              hook di valutazione               skill di lettura
  legge il transcript             chiama supervisor.run_once        Claude interroga
  scrive le chiamate nuove        riporta in una riga gli alert     e risponde
        │                                   │                              │
        └───────────────► starkeno.db (SQLite locale) ◄───────────────────┘
                                    ▲
                                    │ opzionali, non richiesti per l'uso
                          mcp_server.py · supervisor --forever · api.py + dashboard
```

**Perché la valutazione sta all'inizio sessione e non a fine turno.** Valutare tutte le regole a
ogni turno è sprecato e rischia di far aspettare l'utente; l'inizio sessione è il momento in cui il
risultato serve davvero, perché è lì che si può riportare. L'ingestione invece resta a fine turno,
dove è economica.

**Perché il server MCP e il demone diventano opzionali e non spariscono.** Restano nel repository
per chi vuole la dashboard sempre viva, e restano l'unica via per agenti che non siano Claude Code.
Ma **non sono richiesti per usare il plugin**, ed è questo che abbassa la barriera d'ingresso da
«installa e mantieni tre programmi» a «un comando».

**Perché il cuore non si tocca.** `rules.py` è fatto di funzioni pure — niente database, niente
SQLAlchemy, niente orologio. Per questo le stesse quattro regole si richiamano da un hook come da
un demone. La disciplina imposta nella v1 è ciò che rende possibile questo cambio di forma senza
riscrivere la logica.

## 4. Ingestione: la grana corretta è la chiamata API, non la riga

**Il transcript scrive una riga per blocco di contenuto e ripete `usage` a ogni riga.** Misurato:
3.191 righe per 1.525 chiamate API (2,09 righe per chiamata). Sommare per riga dà 837.392.572
token invece di 412.190.307: **2,03× di gonfiaggio**.

Regola: **una riga di `agent_actions` per `(sessionId, message.id)`**, mai per riga di transcript.
Quella coppia è insieme la grana corretta della spesa e la chiave di idempotenza — un indice unico
su di essa rende una riesecuzione dell'hook un no-op invece di un raddoppio.

Attenzione: **`message.id` da solo non è unico** (71 righe → 34 id nel file campione), va sempre
accoppiato a `sessionId`.

**Quale riga vince sull'`usage`.** 213 chiamate su 1.525 (il 14%) hanno righe con `usage` diversi
fra loro; l'ipotesi è che il conteggio si accumuli mentre il messaggio si forma, quindi vale
l'**ultima**. È l'unica misura da rifare prima di fissarla in codice.

**Esclusione:** i messaggi con modello `<synthetic>` (1,8% del traffico) non sono chiamate API e
non vanno scritti. Si scartano all'ingresso, non nelle regole.

**Perché conta.** R3 confronta un agente con la propria storia e si sarebbe gonfiata da entrambe le
parti, quasi senza segni. Ma R2 e R4 hanno soglie assolute — `HEAVY_TOKENS`, `HEAVY_DAILY_TOKENS`,
`EXPENSIVE_TRIVIAL_TOKENS` — e sarebbero scattate a metà della spesa vera, mentre R2 avrebbe smesso
di riconoscere come «banale» una chiamata da 900 token reali. Due regole sbagliate in due direzioni
opposte, senza un errore.

## 5. Identità: il progetto, non l'utente

L'utente era l'asse giusto per il SaaS. In locale è una **costante**: una colonna che conterrebbe
sempre lo stesso valore non distingue niente.

L'asse utile lo porta già il transcript, nel campo `cwd`. Misurato sul traffico reale: tre progetti
distinti — `PROGETTI` 835 chiamate, `starkeno` 551, `xenotech` 101. «Il progetto starkeno ti è
costato X questa settimana» è un'informazione; «l'utente corrente ti è costato X» non lo è.

**Due livelli, per la stessa ragione di prima:**

| Livello | Chi lo usa | Perché |
|---|---|---|
| **progetto** (`cwd`) | R2, R3, R4 | aggregano spesa, e aggregare per progetto è ciò che l'utente vuole vedere |
| **sessione** (`sessionId`) | R1 | cerca cicli, e una sequenza interlacciata da più esecuzioni parallele non è di nessuno |

**Altri assi che il transcript offre e che NON diventano regole.** `isSidechain` distingue le
chiamate dei sub-agenti — **339 su 1.487, il 22,8%** — e i campi `attributionSkill`,
`attributionPlugin`, `attributionMcpServer` / `Tool` attribuiscono la spesa a una funzione precisa:
`superpowers:subagent-driven-development` da solo pesa 246 chiamate. **È materia per la dashboard,
non per le regole**: le regole cercano guasti, questo racconta dove vanno i soldi. Va conservato in
colonne dedicate perché la dashboard possa mostrarlo, senza che nessuna regola lo interroghi.

## 6. Schema

**Si fa adesso, e non è un dettaglio di tempismo:** il database di produzione ha **una riga sola**.
Rinominare oggi è una migrazione senza dati da preservare; farlo dopo la pubblicazione significa
migrare lo storico di chi ha installato il plugin.

| Tabella | Modifica |
|---|---|
| `agent_actions` | `agent_name` → `project`; **nuove** `session_id` e le colonne di attribuzione, **in coda** |
| `alerts`, `rule_status`, `agent_watermark` | `agent_name` → `project`, più `session_id` |
| indici | `ix_actions_agent_time` → `ix_actions_project_time`; **nuovo** `(project, session_id, timestamp)` per R1 |

Le colonne nuove vanno **in coda** per l'invariante 7: `ADD COLUMN` accoda comunque, e i modelli
ORM devono descrivere lo stesso ordine delle migrazioni o la suite gira su uno schema che in
produzione non esiste.

`alerts` va chiavata su **`(project, session_id, rule)`**. Senza `session_id` nella chiave, l'indice
`ix_alerts_one_live` — *un solo alert vivo per coppia* — consentirebbe **un solo alert R1 per
progetto**, e tre sessioni impantanate in parallelo ne produrrebbero uno.

> ⚠️ **Trappola da chiudere qui, non da scoprire dopo.** Per le regole di spesa la sessione è
> assente. Rappresentarla con `NULL` rompe l'indice unico in silenzio: **in SQLite due `NULL` sono
> distinti**, quindi il vincolo «un solo alert vivo» smetterebbe di vincolare proprio sulle tre
> regole che parlano di soldi, e la scrittura tornerebbe a duplicare invece di fare upsert. Si usa
> la **stringa vuota come sentinella**, mai `NULL`. È la stessa classe di fallimento dell'invariante
> 9 sui datetime: nessun errore, risultato sbagliato.

**`MAX_TRACKED_AGENTS` cambia significato.** Oggi vale «troppi agenti distinti, qualcuno sta mettendo
un id di sessione dentro `agent_name`». Con il progetto preso dal transcript quel sospetto non ha più
senso. La cardinalità può ancora esplodere un livello più in basso: la soglia si sposta su **sessioni
per progetto in 24h**, ed è quello il nuovo `data_quality`.

## 7. Errori: l'hook non deve mai rompere la sessione di chi lo usa

È l'invariante 4 applicata a casa d'altri. Qui il costo di un fallimento non lo paga StarkEno: lo
paga il lavoro dell'utente, ed è un progetto open source installato da sconosciuti.

- **Uscita `0` sempre**, qualunque cosa accada. Nessuna eccezione risale.
- **Timeout duro**: un hook che si pianta blocca il turno.
- **Niente rumore su stderr.**
- **Scrittura diretta su SQLite**, senza dipendere dal server MCP né dall'API. Non è una scommessa:
  lo stress test della v1 ha misurato 5 processi concorrenti sullo stesso file con **900 log
  riusciti su 900** e latenza peggiore 0,13 s.
- **`check_or_die` si sdoppia.** Oggi *deve* fallire rumorosamente, ed è giusto per un processo che
  parte. Dentro un hook non può: ucciderebbe la sessione. Se lo schema è disallineato l'hook **non
  scrive nulla e lascia una traccia visibile a chi legge i dati** — silenzioso per l'utente,
  rumoroso in lettura.
- **Idempotenza:** garantita dalla stessa chiave della grana, `(sessionId, message.id)`.

**L'avviso in linea si sposta.** Oggi `_warning_per` consegna gli alert dentro la risposta di
`log_agent_action`. Se l'agente non chiama più quello strumento, non li riceve più. Il rimedio è
l'hook di inizio sessione, che **inietta contesto**: meccanismo verificato, è quello che usa il
plugin superpowers.

## 8. Dove vivono i dati

`config.DB_PATH` punta **accanto al codice**. Le cartelle dei plugin sono **versionate**: un
aggiornamento crea una cartella nuova, e con essa **lo storico dell'utente sparisce** — senza
errore, senza avviso, con la dashboard che riparte vuota.

Il database dev'essere un bene dell'utente, non un file del programma: **fuori dalla cartella del
codice**, in una directory dati per utente, più export e import per cambiare macchina. La giuntura
esiste già — `STARKENO_DB_PATH` è previsto — e cambia solo il valore predefinito.

## 9. Cosa resta aperto

Elencato qui perché un design che finge di aver deciso tutto è peggio di uno che dichiara i buchi.

1. **R1 sulle sessioni corte.** La regola pretende `LOOP_MIN_HISTORY = 20` azioni e ne guarda 45.
   Legandola alla sessione le abbiamo dato una sequenza coerente, ma rischiamo di lasciarla senza
   materiale: nella simulazione la maggioranza delle sessioni ha risposto «storia insufficiente».
   Parte è artefatto del simulatore, parte no. **Da sciogliere prima di implementare R1.**
2. **Il 13,2% delle chiamate con più di un `tool_use`** (195 su 1.473). Una chiamata API, più azioni:
   va deciso se produrre una riga con l'azione principale, o più righe di cui una sola porta i token.
3. **Le due questioni su R4**, documentate nel `CLAUDE.md`: è tarata per segnalare il lavoro normale
   (4 sessioni su 5 violano) ed è cieca fuori dai modelli frontier (metà della spesa reale). Sono
   decisioni di prodotto, non correzioni.
4. **La forma della dashboard**: pagina opzionale sempre viva, o rapporto che Claude genera su
   richiesta a partire dai dati di attribuzione di §5.

## 10. Come si verifica

Le regole restano funzioni pure e i loro test non cambiano. Il pezzo nuovo e rischioso è l'hook, e
va coperto da quattro prove:

1. un **transcript vero come fixture**, con le righe attese in uscita;
2. la **regressione sul doppio conteggio**: 2,09 righe di transcript devono produrre 1 riga;
3. la **riesecuzione** dell'hook sullo stesso transcript non duplica nulla;
4. l'hook **esce `0` e non scrive** con database assente, bloccato o a schema vecchio.

Resta valido il metodo che ha trovato i difetti di oggi: **rieseguire la simulazione su transcript
veri** invece di aspettare giorni di dati.

## 11. Fuori scope

- **SaaS, autenticazione, multi-tenancy, fatturazione.** Ipotizzati e scartati il 07/08/2026.
- **Provider diversi da Claude in `MODEL_TIERS`.** Provati e annullati: il traffico è Claude. Due
  difetti dormienti della normalizzazione sono annotati nel `CLAUDE.md` se un giorno si allargasse.
- **Una quarta fascia per Fable**, che costa il doppio di Opus ma ne condivide la fascia `frontier`.
  Richiede modifiche a `rules.py`: è design, non manutenzione.
