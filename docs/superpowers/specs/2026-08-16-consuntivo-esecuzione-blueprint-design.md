# Il consuntivo — legare un'esecuzione reale al Blueprint che la prevedeva

Specifica del **Passo 1** descritto in
[2026-08-16-prossimi-passi-simulazione-costi.md](../briefings/2026-08-16-prossimi-passi-simulazione-costi.md).
Lo stato del codice da cui parte è in
[2026-08-16-stato-parte-b.md](../briefings/2026-08-16-stato-parte-b.md).

## Il problema

StarkEno ha due metà che non si toccano. `db.py`, `conto.py` e `report_conto.py` non
nominano mai un Blueprint; `preflight_simulate.py` non ha mai visto una riga raccolta.
Finché manca il ponte, ogni numero stampato è un'opinione ben formattata.

Questa specifica costruisce il ponte in una direzione sola: **prendere un preventivo già
prodotto, prendere il lavoro che l'agente ha davvero fatto, e dire dove stanno gli
scarti** — compreso, e soprattutto, dove il consuntivo **si rifiuta** di dirlo.

## Perimetro

**Dentro.** Il lavoro dell'agente dentro Claude Code o Codex, cioè l'unico che gli hook
osservano già oggi. Copre sia «arrivare al goal» sia «costruire l'automazione».

**Fuori, dichiarato.** L'esecuzione di un'automazione su n8n, Make o altrove: StarkEno
non ne vede nulla e nessuna riga di codice qui dentro la fa comparire. Servirebbe un
canale che porti i dati da fuori, ed è un lavoro suo.

**Fuori, per decisione già presa.** Parte C (esecuzione vera dei workflow), dashboard,
Passo 2 (`measured` prodotto), Passo 3 (calibrazione dei default), Passo 4 (prezzi che
scadono), segnalazioni S1–S5.

**Non si tocca.** `hook_ingestione.py`, `hook_inizio_sessione.py`, la tabella
`agent_actions`, `conto.py`, `report_conto.py`. Nessuna colonna nuova sulla tabella calda,
nessuna conoscenza dei Blueprint dentro il percorso di raccolta.

## Decisione portante: l'attribuzione è una vista, mai una colonna

Le righe raccolte non vengono timbrate. L'esecuzione dichiara **quando** è iniziata,
**quando** ha cambiato nodo e **quando** è finita; l'attribuzione si calcola incrociando
quegli intervalli con i `timestamp` delle righe **al momento del confronto**.

Le conseguenze sono il motivo della scelta:

- L'hook resta intatto. È il codice che gira a casa d'altri, fail-open e silenzioso: non
  deve imparare cosa sia un Blueprint.
- Una dichiarazione sbagliata si corregge cambiando l'intervallo e ricalcolando. Niente è
  stato bruciato sulla riga.
- Le righe che l'hook scrive **dopo** la fine dell'esecuzione — il turno finisce dopo la
  chiusura — rientrano lo stesso nella finestra, perché conta il `timestamp` del
  transcript, non il momento dell'ingestione.

## La stima si conserva, non si ricalcola

`blueprint_run_start` prende il percorso di un'**analisi JSON** prodotta da
`starkeno preflight analyze --confirmed --format json`, e ne conserva il testo verbatim
nella riga dell'esecuzione.

Il motivo è un difetto reale, non un'astrazione. `_run_analyze`
([preflight_cli.py:113](../../../starkeno/preflight_cli.py)) costruisce la revisione
confermata **in memoria** e su disco scrive solo il report: il Blueprint che la
simulazione ha davvero usato non esiste in nessun file. Un'esecuzione legata al *draft*
ricalcolerebbe la stima con un `blueprint_hash` diverso da quello del preventivo — un
numero che sembra riproducibile e non è lo stesso.

Effetto voluto: **non esiste consuntivo senza preventivo.**

Il testo si conserva verbatim invece di ri-serializzare un modello: il file su disco può
essere cancellato o modificato, e l'esecuzione deve conservare la stima contro cui è
stata confrontata. Alla lettura si validano **due sotto-oggetti indipendenti**,
`blueprint` con `Blueprint.model_validate` e `simulation` con
`SimulationReport.model_validate`, invece del contenitore `PreflightAnalysis` — che porta
un `source_path: Path | None` estraneo al confronto.

### La misura che viene prima del codice

`render_analysis` serializza con `model_dump(mode="json")`, che manda `Decimal` e `date`
in stringa. Che tornino indietro identici **va verificato, non assunto**: è il primo task
del piano e non scrive niente.

- **Se il round-trip regge** su `Blueprint` e `SimulationReport`, il design procede come
  scritto.
- **Se non regge**, il design cambia lì e non altrove: si conservano nella riga i totali
  già estratti (per scenario e per nodo) invece del testo, e il confronto perde la
  capacità di rileggere il Blueprint completo — quindi perde la moneta, che dipende da
  `blueprint.models[].*_price_per_million`. Va deciso prima delle tabelle, non dopo.

## Struttura dei dati

Migrazione `0006_esecuzioni_blueprint`. Due tabelle nuove, nessuna colonna aggiunta a
`agent_actions`.

### `blueprint_runs`

| Colonna | Tipo | Nota |
|---|---|---|
| `id` | INTEGER PK | |
| `run_key` | TEXT NOT NULL UNIQUE | `uuid4().hex`, generato dalla porta. Opaco: l'agente lo rimanda indietro e non deve poter enumerare le altre esecuzioni |
| `project` | TEXT NOT NULL | normalizzato con `normalizza_progetto`, come le righe raccolte |
| `blueprint_hash` | TEXT NOT NULL | copiato da `simulation.blueprint_hash` |
| `analysis_json` | TEXT NOT NULL | il preventivo, verbatim |
| `model_map_json` | TEXT NOT NULL | `{"<model_used osservato>": "<models[].id>"}`; `{}` se nulla è dichiarato |
| `started_at` | `db.UTCDateTime` NOT NULL | |
| `ended_at` | `db.UTCDateTime` NULL | NULL significa **aperta** |

Indice su `(project, ended_at)`: serve la sola query calda, «c'è un'esecuzione aperta su
questo progetto?».

Non esiste una colonna `status`: `ended_at IS NULL` è lo stato, e due rappresentazioni
della stessa cosa divergono sempre.

### `blueprint_run_markers`

| Colonna | Tipo | Nota |
|---|---|---|
| `id` | INTEGER PK | |
| `run_id` | INTEGER NOT NULL | riferisce `blueprint_runs.id` |
| `node_id` | TEXT NOT NULL | validato contro il Blueprint **alla dichiarazione** |
| `declared_at` | `db.UTCDateTime` NOT NULL | |
| `seq` | INTEGER NOT NULL | monotono dentro l'esecuzione: ordina marcatori con lo stesso istante |

Indice su `(run_id, declared_at, seq)`. `seq` lo assegna la funzione di scrittura in
`db.py` come massimo corrente più uno dentro la stessa esecuzione, nella stessa
transazione dell'inserimento: non arriva mai dal chiamante.

Ogni nuova colonna temporale usa `db.UTCDateTime` (invariante 8). Le due tabelle vanno
dichiarate nei modelli ORM **e** nella migrazione con lo stesso ordine di colonne
(invariante 7).

## La regola di attribuzione

Vive in `starkeno/consuntivo.py`, **modulo puro** come `conto.py`: riceve snapshot già
letti, non importa SQLAlchemy, non legge l'orologio, non tocca il filesystem.

Finestra dell'esecuzione: `[started_at, ended_at]`. Righe candidate: stesso `project`,
`timestamp` dentro la finestra.

1. **Righe con `session_id` vuota: secchio a parte, mai attribuite, e non contano per
   l'ambiguità.** `record_action` ([db.py:378](../../../starkeno/db.py)) non imposta mai
   `session_id`, e la colonna ha `server_default=""`: ogni riga scritta dal tool MCP
   `log_agent_action` ha sessione vuota. Senza questa clausola **una sola** di quelle
   righe nella finestra renderebbe ambigua ogni esecuzione, per sempre. Vengono contate e
   mostrate come `senza_sessione`.
2. **Più di una `session_id` non vuota fra le candidate → esecuzione `ambigua`.** Nessuna
   attribuzione, né per nodo né totale; il confronto elenca le sessioni trovate e si
   ferma. Costo accettato e dichiarato: una sessione che riparte a metà lavoro
   (compattazione, riavvio, crash) cambia `session_id` e perde tutto. StarkEno non sa
   distinguerla da una sessione parallela di un altro lavoro, e indovinare è vietato.
3. I marcatori ordinati per `(declared_at, seq)` definiscono intervalli **semiaperti**
   `[m(i), m(i+1))`; l'ultimo chiude su `ended_at` incluso. Una riga esattamente sul
   confine appartiene al nodo **nuovo**.
4. Righe prima del primo marcatore, o in un'esecuzione senza marcatori → secchio
   **`non_attribuite`**, con chiamate e token, mostrato accanto agli altri e **mai fuso**
   nei totali per nodo.
5. Un nodo del Blueprint senza righe attribuite compare con osservato a zero e la nota
   «nessuna osservazione». Distinguere «costato poco» da «mai eseguito» è metà del valore
   del confronto.

### I due orologi

`declared_at` viene dall'orologio del processo che serve MCP; `timestamp` viene dal
transcript scritto dall'agente. Il server ascolta su `127.0.0.1`
([mcp_server.py:284](../../../starkeno/mcp_server.py)), quindi è la stessa macchina e lo
stesso orologio.

È un'assunzione, ed è dichiarata perché si sa come rompe: se il server girasse altrove,
sbaglierebbero **solo le righe a cavallo di un confine fra nodi**, e in silenzio. Se un
giorno il server non fosse più locale, questa regola va rivista insieme.

## Cosa dice il confronto, e cosa si rifiuta di dire

`Consuntivo`, dataclass congelata prodotta da `consuntivo.py`.

**Quattro stati.** Tre non producono numeri di risultato: `aperta` (manca `ended_at`),
`ambigua` (più sessioni), `senza_osservazioni` (nessuna riga candidata con `session_id` non
vuota). Fa eccezione un solo numero, diagnostico e non di risultato: quante righe senza
sessione cadono nella finestra, mostrato accanto al motivo quando ce ne sono — spiega
perché non c'è un confronto, non lo sostituisce. Il quarto stato è `ok`.

`senza_osservazioni` si misura sulle sole righe con sessione, perché sono le uniche
attribuibili: un'esecuzione che nella finestra trova solo righe senza sessione non è `ok`
con tutto in un secchio, è un'esecuzione di cui non si è osservato nulla di utilizzabile —
e le righe senza sessione vengono comunque contate e mostrate accanto alla dichiarazione.
Lo stesso stato copre il caso in cui il `project` dichiarato all'apertura non corrisponda a
quello delle righe raccolte: zero candidate, e il confronto lo dice invece di cercare
altrove.

**Totali.** Le quattro classi di token — input al netto della cache, output, cache read,
cache write — più il totale, osservate contro i quattro scenari. Le due semantiche
coincidono, verificato: `_node_invocation` calcola `input_tokens = gross_input - cacheable`
([preflight_simulate.py:445](../../../starkeno/preflight_simulate.py)) e `calcola_conto`
calcola `ingresso = tokens_used - cache_read - cache_write - output`
([conto.py:139](../../../starkeno/conto.py)).

La riga che conta non è lo scarto: è **dove cade l'osservato rispetto alla banda** —
sotto l'ottimistico, fra typical e prudente, oltre il massimo. Uno scenario può essere
`None` (`maximum_status` lo prevede): quelli assenti si dichiarano assenti e non entrano
nella banda.

**Per nodo.** Solo dove un marcatore esiste, contro lo scenario `typical` con la banda
accanto, **ordinato per scarto assoluto decrescente**. È la prima riga a rispondere alla
domanda vera: *quasi tutto sul nodo `review`*.

**Chiamate e azioni.** Si stampano affiancate e **non si sottraggono mai**. `executions` e
`llm_calls` stimati contano invocazioni di nodo (una più i retry); la riga osservata è una
chiamata API, e un nodo `llm` in una sessione reale sono decine di chiamate. Etichette
diverse, nessun delta calcolato. È il punto in cui sarebbe più facile produrre un numero
preciso e falso.

**Moneta.** I prezzi di `blueprint.models[]` applicati ai token osservati — **gli stessi**
che ha usato la stima, così lo scarto isola il volume e non il listino. Solo per le righe
il cui `model_used` è mappato in `model_map_json`. Le altre contano i token e dichiarano
la moneta **ignota**, e il confronto elenca i `model_used` privi di mappatura con quanti
token pesano, così si sa cosa dichiarare. Blueprint senza prezzi, o con `unknown_prices`
non vuoto: moneta assente su entrambi i lati — assente, non zero.

**Ogni numero porta su quante chiamate è calcolato.** Il Passo 3 lo richiederà comunque, e
aggiungerlo dopo a un formato già letto costa di più.

### Uno scarto atteso, che non è un difetto

La simulazione conta `cache_write` una volta per invocazione e `cache_read` solo sui retry
([preflight_simulate.py:462](../../../starkeno/preflight_simulate.py)); un agente vero
rispedisce il contesto a ogni turno. I `cache_read` osservati saranno molto più grandi
degli stimati, in modo sistematico e su tutti i nodi.

È il segnale che serve al Passo 3, non un bug da tappare. Va scritto nell'output, perché
il primo che lo vedrà penserà di aver sbagliato una sottrazione.

## Superficie

Tre tool MCP in `mcp_server.py`, accanto a `log_agent_action`. Sono **osservazione, non
predizione**: i due tool Preflight restano offline e continuano a non toccare il database.

| Tool | Argomenti | Restituisce |
|---|---|---|
| `blueprint_run_start` | `analysis_path`, `project`, `model_map` opzionale | la `run_key`, o l'errore come testo |
| `blueprint_run_node` | `run_key`, `node_id` | conferma, o l'errore con gli id validi |
| `blueprint_run_end` | `run_key`, `model_map` opzionale | il confronto già pronto, o l'errore |

`model_map` passata a `blueprint_run_end` **sostituisce** quella di `blueprint_run_start`;
omessa, lascia invariata quella esistente.

CLI: `starkeno consuntivo --elenco` e `starkeno consuntivo --run <chiave>`, con `--json`.
Import differito in `cli.py` come già fa `preflight`, perché il confronto carica pydantic.
La logica sta una volta sola nel modulo puro; le due porte sono involucri sottili — lo
stesso rapporto che c'è già fra `preflight_service.py`, `preflight_cli.py` e
`mcp_server.py`.

## Errori

I tre tool e la CLI **restituiscono testo e non sollevano**, come `preflight_save_draft`.

Ma **non sono fail-open come gli hook**, e la distinzione va scritta nei docstring — per
un tool MCP il docstring è l'interfaccia. Un hook silenzioso protegge il turno
dell'utente; un marcatore perso in silenzio produce un'attribuzione sbagliata, che è il
danno peggiore di tutti. Un errore qui si dichiara.

- **Esecuzione già aperta sullo stesso progetto** → `blueprint_run_start` rifiuta,
  nominando la `run_key` aperta e come chiuderla. Un'esecuzione dimenticata aperta è un
  aspirapolvere: si prenderebbe ogni chiamata successiva del progetto.
- **`run_key` sconosciuta, esecuzione già chiusa, `node_id` fuori dal Blueprint** → testo,
  niente scritto. Il messaggio del `node_id` elenca gli id validi.
- **`ended_at` anteriore a `started_at`** (orologio che torna indietro) → rifiutato,
  l'esecuzione resta aperta.
- **`analysis_path`** lo sceglie l'agente: **confinato alla working directory del
  server**, riusando il controllo già scritto per `preflight_save_draft`
  ([mcp_server.py:171](../../../starkeno/mcp_server.py)) generalizzato alla lettura.
- **`analysis_path` che non è un'analisi valida** → testo con il motivo, niente scritto.

## Test

Ogni test ha una regressione concreta che lo rende rosso (invariante 13).

Puri, in `tests/test_consuntivo.py`, su snapshot sintetici:

| Test | Regressione che deve uccidere |
|---|---|
| riga esattamente sul `declared_at` di un marcatore | intervallo chiuso invece che semiaperto: la riga finisce sul nodo precedente |
| righe prima del primo marcatore | finiscono attribuite al primo nodo |
| due `session_id` non vuote nella finestra | vengono sommate invece di fermare il confronto |
| una riga con `session_id` vuota più una sessione vera | la riga vuota rende ambigua l'esecuzione |
| nella finestra solo righe senza sessione | risulta `ok` con tutto in un secchio invece che `senza_osservazioni` |
| esecuzione senza `ended_at` | produce numeri su una finestra che non è chiusa |
| `model_used` non mappato | viene prezzato zero invece che dichiarato ignoto |
| nodo del Blueprint senza righe | scompare dal confronto invece di comparire a zero |
| ordinamento per nodo | non ordinato per scarto assoluto |
| scenario `None` | entra nella banda come zero |

Con database, su `tmp_path` più `STARKENO_DB_PATH` risolto alla chiamata (invariante 3):
apertura, rifiuto della seconda esecuzione aperta, marcatore su esecuzione chiusa,
chiusura. Ogni connessione chiusa da chi l'ha aperta, `engine.dispose()` incluso
(invariante 14).

Migrazione: il confronto fra modelli ORM e schema migrato, colonna per colonna e ordine
compreso (invariante 7).

Round-trip: `Blueprint` e `SimulationReport` riletti da `render_analysis(..., "json")`
devono tornare uguali agli originali. È il primo task e precede le tabelle.

## Un difetto già noto che questo lavoro rende urgente

`test_preflight_save_draft_impl_non_tocca_il_database`
([tests/test_mcp_server.py:154](../../../tests/test_mcp_server.py)) dichiara nel docstring
di coprire «nessuno dei due tool» ma ne esercita uno solo — è fra i rilievi minori aperti
nello stato della parte B.

Finora era un test che prometteva più di quanto mantenesse. Da qui in avanti è **la guardia
che tiene Preflight offline** mentre tre tool nuovi che toccano il database si siedono
accanto: va esteso a `preflight_interpretation_task_impl` insieme a questo lavoro.

Gli altri rilievi minori aperti (`test_anthropic_e_dichiarato_come_dipendenza` che asserisce
su testo grezzo, `test_preflight_save_draft_impl_supporta_yaml` che resta verde senza
`format`, l'import inutilizzato del Task 3, la dipendenza `anthropic` da rimuovere) non
toccano questo lavoro e restano dove sono.

## Cosa questo passo abilita, e cosa no

Abilita il Passo 2: con osservazioni legate ai nodi, StarkEno diventa l'unico soggetto che
può scrivere `provenance: "measured"` avendo davvero misurato. E abilita il Passo 3: gli
scarti osservati sono ciò che trasforma `CHARACTERS_PER_TOKEN = 3.5` da stima dichiarata a
numero ricavato — con accanto da quante osservazioni viene.

Non abilita la dashboard, che resta dopo i primi feedback per decisione dell'utente, e non
avvicina la parte C di un passo.

## Vincoli sempre in vigore

- Nessun push e nessuna modifica remota senza consenso esplicito.
- Niente dati personali, transcript reali, database, log, segreti o percorsi home nei file
  tracciati. Le fixture sono sintetiche.
- Prima di dichiarare completo un lavoro: test pertinenti, `python -m pytest -q -W error`
  e `git diff --check`.
