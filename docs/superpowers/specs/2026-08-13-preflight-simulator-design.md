# StarkEno Preflight v1 — progettare, revisionare e simulare workflow agentici

> Data: 2026-08-13.
>
> Questo documento aggiunge a StarkEno una superficie nuova, chiamata **Preflight**. Il
> prodotto esistente osserva localmente esecuzioni reali di coding agent; Preflight
> analizza un sistema agentico prima dell'esecuzione. I due prodotti condividono i
> concetti di costo e inefficienza, ma non condividono dati, soglie o processi runtime.

---

## 1. Obiettivo

StarkEno Preflight riceve la descrizione naturale di un goal, workflow, automazione o
team di agenti e produce un progetto strutturato che l'utente può correggere prima
dell'analisi. Può anche ricostruire e revisionare un workflow già esistente incollato
come testo, prompt, JSON o YAML.

La v1 deve rispondere a quattro domande:

1. **Che cosa verrà eseguito?** Agenti, passaggi, tool, skill, handoff, loop e criteri di
   successo in un Blueprint comprensibile e modificabile.
2. **Il progetto è eseguibile?** Errori strutturali, ambiguità, dipendenze mancanti,
   loop senza uscita e verifiche assenti.
3. **Quanto potrebbe costare?** Intervalli di token, costo e tempo per scenario, con
   ipotesi e provenienza visibili.
4. **Come può migliorare?** Correzioni reversibili, ordinate per impatto, con confronto
   originale/corretto calcolato sulle stesse ipotesi.

La promessa non è prevedere esattamente un sistema non deterministico. La promessa è
rendere esplicita e verificabile la struttura che oggi viene scoperta soltanto durante
l'esecuzione.

## 2. Principi di prodotto

### 2.1 Economico per costruzione

StarkEno deve dimostrare la disciplina che suggerisce:

- un singolo modello interpreta il testo; nessun team interno nella v1;
- lint, grafo, simulazione, confronto e applicazione delle patch sono deterministici;
- il percorso standard usa una chiamata LLM;
- è ammesso un solo retry di riparazione quando l'output non rispetta lo schema;
- una seconda chiamata è esplicita e opzionale, riservata alla revisione semantica
  profonda del Blueprint confermato;
- il sistema dichiara il proprio preventivo token prima di invocare il modello e il
  consumo osservato dopo;
- gli output voluminosi vivono in artefatti; skill e tool restituiscono per default un
  riepilogo conciso e un riferimento recuperabile;
- prompt di sistema, schema e definizioni restano un prefisso stabile e non contengono
  timestamp, ID di richiesta o metadati dinamici.

Il costo di una simulazione non dipende dal numero di percorsi virtuali: dopo la
compilazione, eseguire cento o diecimila campioni consuma CPU, non token LLM.

### 2.2 L'utente conferma l'interpretazione

Il testo naturale non viene trattato come verità strutturata. Il primo risultato è un
**Draft Blueprint** accompagnato da assunzioni e domande aperte. La simulazione definitiva
parte soltanto da un Blueprint confermato.

Se l'utente modifica il Blueprint, i rilievi semantici prodotti sulla versione precedente
diventano `stale` e non possono essere presentati come ancora validi. Il lint
deterministico viene sempre ricalcolato.

### 2.3 Correzioni non distruttive

Preflight non sostituisce silenziosamente l'input e non modifica sistemi esterni.
Produce una nuova revisione del Blueprint tramite patch atomiche che l'utente può
accettare o rifiutare. Il confronto usa le medesime assunzioni per evitare risparmi
artefatti.

### 2.4 Onestà dell'incertezza

Ogni quantità stimata porta:

- intervallo, non falsa precisione;
- provenienza: `measured`, `declared`, `inferred` o `default`;
- confidenza: `high`, `medium` o `low`;
- ragione della confidenza;
- eventuali quantità non calcolabili.

Un prezzo sconosciuto resta sconosciuto: non diventa zero. La v1 non mostra una
probabilità numerica di successo perché non dispone ancora di dati calibrati sufficienti.

## 3. Confine della v1

### Incluso

- modalità `design`: da descrizione naturale a nuovo Blueprint;
- modalità `review`: da workflow esistente a Blueprint ricostruito;
- input testuale, Markdown, prompt, JSON e YAML incollati o letti da file;
- goal, singolo agente, team di agenti, tool, skill, fonti di contesto, handoff,
  diramazioni, loop, retry, modelli, budget e verifiche;
- editor e conferma del Blueprint;
- lint deterministico e rilievi semantici con evidenza;
- simulazione ibrida senza chiamate LLM durante i campioni;
- patch accettabili individualmente e confronto prima/dopo;
- export Markdown, JSON e YAML;
- sito pubblico senza account;
- CLI locale e skill Codex nello stesso plugin esistente;
- un'unica operazione agent-facing `starkeno_preflight`, con risposta concisa di default.

### Escluso

- import diretto da n8n, Make, Codex, Claude o altri provider;
- esecuzione reale del workflow o dry-run con agenti;
- modifica automatica di automazioni o servizi esterni;
- multi-tenancy persistente, account, pagamenti e collaborazione;
- apprendimento automatico da dati degli utenti del sito;
- probabilità numerica di successo;
- scoperta di skill o plugin non installati tramite cataloghi esterni;
- autoselezione vincolante del provider o del modello;
- marketing, landing commerciale e analytics comportamentali non essenziali.

## 4. Le due superfici di ingresso

### 4.1 Progetta

L'utente descrive il risultato desiderato e i vincoli. Il compilatore propone agenti e
workflow soltanto quando servono: un goal semplice deve poter produrre un singolo agente
o persino un flusso deterministico senza agenti.

### 4.2 Revisiona

L'utente fornisce un workflow, un insieme di prompt o una configurazione strutturata.
Il compilatore conserva ciò che è dichiarato, distingue ciò che inferisce e non
"migliora" l'originale durante la ricostruzione. Originale normalizzato e proposta
corretta restano due revisioni distinte.

Entrambe le superfici convergono nello stesso schema e nello stesso motore. Non esistono
due implementazioni della simulazione.

## 5. Blueprint canonico

Il Blueprint è il contratto versionato tra LLM e codice deterministico. La sua forma
concettuale è:

```text
Blueprint
├── metadata e versione schema
├── goal e criteri di successo
├── assunzioni
├── agenti
├── tool e skill
├── fonti di contesto
├── nodi del workflow
├── transizioni e handoff
├── loop, retry e limiti
├── modelli e profili di costo
└── budget e vincoli
```

### 5.1 Identità e versionamento

Ogni oggetto possiede un ID stabile e leggibile all'interno del Blueprint. Lo schema ha
`schema_version`; ogni revisione ha `revision` e `parent_revision`. Il contenuto
normalizzato produce un hash usato come seed della simulazione e per riconoscere rilievi
semantici diventati stantii.

### 5.2 Goal

Il goal contiene descrizione, deliverable e criteri di successo osservabili. Se manca un
criterio verificabile il Blueprint resta modificabile ma riceve un errore di lint: il
simulatore può stimare il costo, non dichiarare il completamento.

### 5.3 Agenti

Ogni agente dichiara responsabilità, input necessari, output prodotto, modello o classe
di modello, tool/skill accessibili e limiti. L'agente è distinto da un passaggio: lo
stesso agente può eseguire più nodi, e un nodo deterministico può non avere agente.

### 5.4 Nodi e transizioni

I nodi supportati nella v1 sono:

- `llm`: chiamata a modello;
- `tool`: operazione esterna;
- `deterministic`: codice, regola o trasformazione senza LLM;
- `human`: approvazione o input umano;
- `gate`: controllo e diramazione;
- `handoff`: trasferimento fra agenti.

Le transizioni dichiarano condizione, probabilità o intervallo di probabilità, origine
della stima e possibilità di esecuzione parallela. Un ciclo deve indicare
`max_iterations` e una condizione di uscita; altrimenti il costo massimo è
`unbounded` e la simulazione completa viene bloccata.

La tupla `(source, target, activation, parallel_group)` è univoca nel Blueprint: due
archi con la stessa identità colliderebbero nelle basi quantitative persistite.
La chiave persistita della transizione codifica questa tupla come JSON canonico, senza
delimitatori ambigui né coercizioni: `null` resta distinto dalla stringa vuota e gli ID
possono contenere punteggiatura arbitraria.

### 5.5 Assunzioni quantitative

Ogni nodo può dichiarare intervalli per:

- token di istruzioni stabili;
- token di contesto dinamico;
- quota cacheabile;
- token di output;
- latenza;
- probabilità di retry;
- massimo numero di retry;
- costo fisso del tool;
- frequenza della diramazione.

Ogni valore porta provenienza e confidenza. I default appartengono a profili versionati,
mai sparsi come costanti anonime nel codice.

Il costo fisso usa un intervallo `Decimal` ordinato e una valuta esplicita. Soltanto un
nodo `tool` può dichiararlo: l'assenza significa costo sconosciuto, mentre zero è noto
solo quando viene dichiarato. Costi modello e tool si sommano esclusivamente nella stessa
valuta; Preflight non effettua conversioni.

## 6. Pipeline

```text
Acquire → Prepare → Compile → Validate → Confirm
                                      ↓
                   Correct ← Analyze ←┘
                                ↓
                            Simulate
                                ↓
                     Compare → Render/Export
```

### 6.1 Acquire e Prepare

Acquisiscono testo o file entro limiti espliciti, riconoscono il formato e costruiscono
il prompt. Non accedono a URL, repository o vault nella v1 pubblica. Il prompt mantiene
un prefisso byte-stabile; contenuto e metadati dinamici stanno in coda.

### 6.2 Compile

Una sola chiamata LLM produce output strutturato contenente:

- Draft Blueprint;
- assunzioni inferite;
- ambiguità;
- rilievi semantici preliminari;
- patch candidate, separate dal Blueprint originale;
- metriche d'uso restituite dal provider.

Il modello non calcola totali di costo e non percorre il grafo: sono compiti del codice.

### 6.3 Validate

La validazione controlla schema, riferimenti, unicità degli ID, tipi, intervalli e
invarianti. Se l'output non è valido, un solo tentativo di riparazione riceve gli errori
strutturati. Un secondo fallimento termina con errore recuperabile e conserva la risposta
grezza soltanto nell'artefatto locale o nell'ambiente effimero della richiesta.

### 6.4 Confirm

L'utente vede grafo, tabella degli agenti, assunzioni e ambiguità. Può modificare il
Blueprint prima di confermarlo. Nessuna percentuale di risparmio definitiva viene
mostrata prima della conferma.

### 6.5 Analyze

Esegue lint deterministico e combina, senza confonderli, i rilievi semantici ancora
validi. La revisione profonda opzionale usa al massimo una seconda chiamata LLM e produce
soltanto rilievi e patch; non modifica il Blueprint.

### 6.6 Simulate

Il simulatore percorre il grafo confermato, calcola scenari di confine e usa un generatore
pseudocasuale con seed derivato dall'hash per campionare le diramazioni. Lo stesso
Blueprint e lo stesso catalogo devono produrre lo stesso report.

I risultati minimi sono:

- scenario ottimistico, tipico e prudente;
- p50 e p90 dei campioni quando esistono probabilità utilizzabili;
- limite massimo quando il grafo è interamente limitato;
- token per componente e agente;
- costo per modello quando il prezzo è noto;
- costo di coordinamento e handoff;
- crescita del contesto e quota cacheabile;
- numero di chiamate LLM e tool;
- latenza seriale e percorso critico con parallelismo;
- retry e loop potenziali;
- confidenza e assunzioni dominanti.

Il report non somma quantità incompatibili. Token, token cache, valuta, latenza e costo
fisso dei tool restano dimensioni separate.

Il report persiste inoltre la versione dell'algoritmo e una base quantitativa immutabile
e canonicamente ordinata per nodi, transizioni e fallback effettivi dei choice group. Il
suo hash delle assunzioni copre versione, base completa e fallback, non soltanto le frasi
esplicative.

Un'aggregazione interna che incontra costi tool in valute incompatibili degrada il costo
a sconosciuto e cancella la valuta aggregata; non sceglie mai implicitamente una valuta.

### 6.7 Correct e Compare

Le patch usano un sottoinsieme versionato di JSON Patch: `test`, `add`, `remove` e
`replace`. Ogni patch include evidenza, impatto atteso, confidenza e compromesso. Prima
dell'applicazione si verifica `test`; una patch non più applicabile viene marcata
`conflict`, non forzata.

Dopo le patch accettate, il Blueprint viene rivalidato e risimulato usando gli stessi
profili e lo stesso seed. Il confronto attribuisce una variazione soltanto alla modifica
effettiva.

Il confronto richiede seed effettivo, campioni, profilo e versione algoritmo uguali. Per
ogni entità quantitativa presente in entrambe le revisioni richiede lo stesso fingerprint;
entità aggiunte o rimosse restano invece modifiche strutturali confrontabili. Il risultato
registra separatamente gli hash delle assunzioni prima e dopo.

## 7. Linter

### 7.1 Regole deterministiche iniziali

Le regole hanno ID stabile, severità, posizione, evidenza e azione consigliata. La v1
copre almeno:

| Famiglia | Controllo |
|---|---|
| Goal | criterio di successo assente o non osservabile |
| Grafo | nodo irraggiungibile, uscita assente, dipendenza mancante |
| Loop | ciclo non limitato, retry senza massimo, uscita non valutabile |
| Agenti | agente senza responsabilità/output, responsabilità duplicata |
| Handoff | ciclo di handoff, trasferimento senza contratto di output |
| Tool/skill | sovrapposizione dichiarata, accesso non utilizzato, tool eccessivamente potente |
| Contesto | dati inviati a nodi che non li consumano, crescita senza limite |
| Modelli | LLM usato per calcolo deterministico, classe incompatibile col budget |
| Esecuzione | passaggi indipendenti serializzati, verifica finale assente |
| Budget | limite inferiore al minimo calcolabile, prezzo o tokenizer ignoto |

Le regole semantiche non fingono di essere deterministiche. Nel report sono etichettate
come `semantic` e portano l'hash del Blueprint su cui sono state prodotte.

### 7.2 Priorità

L'ordinamento è:

1. impossibilità di completamento;
2. rischio di loop o costo illimitato;
3. correttezza e verificabilità;
4. sicurezza e permessi;
5. riduzione di token/costo/tempo;
6. manutenibilità.

Un risparmio non può nascondere un peggioramento di correttezza o sicurezza.

## 8. Superfici applicative

### 8.1 Core Python puro

Il dominio, il linter, il simulatore, il patcher e il confronto non importano FastAPI,
SQLAlchemy, browser o SDK di provider. Accettano dataclass/strutture validate e
restituiscono risultati immutabili. `starkeno/db.py` resta l'unico modulo che importa
SQLAlchemy; Preflight v1 non richiede nuove tabelle.

### 8.2 Sito pubblico

Una web app FastAPI espone due operazioni stateless:

- compilare input in Draft Blueprint;
- analizzare un Blueprint confermato e renderizzare il report.

Il browser rimanda il Blueprint confermato all'analisi; il server non necessita di un
database utente. La UI presenta in ordine:

1. input `design` o `review`;
2. preventivo token della compilazione;
3. grafo, agenti, assunzioni e ambiguità;
4. conferma/modifica;
5. audit e simulazione;
6. patch selezionabili;
7. confronto ed export.

La vecchia dashboard e l'API di osservabilità non diventano dipendenze del sito
Preflight.

### 8.3 CLI locale

La CLI mantiene un solo concetto, con due modalità:

```text
starkeno preflight design --input workflow.md
starkeno preflight review --input workflow.yaml
```

Per default stampa un riepilogo conciso. `--output` salva il report completo;
`--format json|yaml|markdown|html` controlla l'artefatto. Senza `--input` può leggere
stdin. Il provider e la chiave arrivano da configurazione locale o variabili dedicate,
mai dal Blueprint.

### 8.4 Skill e plugin Codex

Il plugin esistente aggiunge `skills/` al manifest, secondo il formato già presente nei
plugin Codex installati. La skill è un router sottile: si attiva quando l'utente vuole
progettare, revisionare, stimare o ottimizzare un workflow agentico e invoca la CLI.

La superficie agent-facing è una sola operazione concettuale:

```text
starkeno_preflight(mode, source, detail="concise")
```

Non vengono aggiunti molti tool sovrapposti. La risposta concisa contiene stato, cinque
rilievi principali, intervallo di costo, confidenza e percorso dell'artefatto. Il report
completo non entra nel contesto finché l'agente non lo richiede.

I turni normali non caricano il motore né dati di report. La descrizione della skill deve
essere corta e precisa; il suo peso e il costo di invocazione diventano test misurati.

## 9. Cataloghi e provider

L'accesso al modello passa da un adapter con contratto unico: input strutturato, schema di
output, budget, timeout e metriche d'uso. Il core non dipende da un provider specifico.

Il catalogo modelli è un file versionato che contiene capacità e prezzi per categorie di
token supportate dal provider, valuta, unità, data di verifica e fonte. La v1 può partire
con un solo adapter ospitato e uno locale configurabile, ma lo schema non assume che tutti
i provider prezzino input, output e cache nello stesso modo.

Modello, prezzo o tokenizer non riconosciuti producono una stima parziale dichiarata.
L'utente può fornire un profilo manuale senza modificare il catalogo globale.

## 10. Dati, privacy e sicurezza

### Sito pubblico

- nessun account e nessuna persistenza del contenuto nella v1;
- log applicativi senza prompt, Blueprint o output completi;
- metriche ammesse: hash non reversibile della versione schema, durata, conteggi, token,
  tipo di errore e stato HTTP;
- limiti a dimensione input/output, timeout e campioni di simulazione;
- rate limiting e budget massimo per richiesta;
- chiavi provider soltanto lato server;
- rendering con escaping e Content Security Policy;
- YAML caricato in modalità sicura, senza costruttori arbitrari;
- nessun fetch di URL e nessuna esecuzione del contenuto fornito;
- prompt e workflow sono dati non fidati e non possono cambiare istruzioni di sistema,
  strumenti disponibili o destinazioni di rete.

### Plugin locale

- file e report restano locali;
- viene inviato al provider soltanto il contenuto scelto dall'utente;
- chiavi e configurazione sono escluse da report ed export;
- gli artefatti predefiniti vivono nella directory dati di StarkEno, non nel repository;
- un diff verso un file di progetto richiede approvazione; nessuna scrittura automatica;
- il plugin non legge transcript, database o vault per una simulazione salvo richiesta
  futura esplicita e separata.

## 11. Errori e degradazione controllata

Gli errori sono strutturati e recuperabili:

- input troppo grande: limite ed esempio di riduzione;
- formato non riconosciuto: formati accettati e possibilità di trattarlo come testo;
- output LLM non valido: errori di schema e unico retry disponibile;
- provider non disponibile: nessuna simulazione inventata, ma possibilità di analizzare
  un Blueprint già strutturato senza LLM;
- prezzo sconosciuto: token stimati, costo monetario `unknown`;
- grafo illimitato: lint disponibile, massimo `unbounded`, simulazione parziale;
- patch in conflitto: Blueprint invariato e motivo del conflitto;
- rilievo stantio: escluso dal conteggio finché non viene ricalcolato;
- timeout di simulazione: risultati parziali con numero di campioni completati.

Il sito non mostra stack trace. La CLI può salvarli in diagnostica locale senza inserirli
nella risposta concisa del coding agent.

## 12. Valutazione e stabilità

La v1 non è completa perché "genera un bel grafo". Deve superare gate separati.

### 12.1 Gate deterministici

- schema valido e round-trip JSON/YAML;
- hash e simulazione riproducibili;
- nessun riferimento a ID inesistente;
- ogni ciclo limitato produce un massimo finito;
- un ciclo illimitato non produce un falso massimo;
- somma per nodo/agente coerente col totale dello scenario;
- confronti prima/dopo sulle stesse assunzioni;
- patch atomiche, reversibili e protette da `test`;
- prezzi sconosciuti mai convertiti in zero;
- nessun contenuto utente nei log pubblici;
- report HTML escapato;
- CLI concisa entro il budget di output stabilito.

### 12.2 Corpus iniziale

Il corpus usa esclusivamente dati sintetici o sanificati e copre almeno 50 casi prima del
lancio pubblico stabile, stratificati in:

- semplici: una sequenza e un singolo agente;
- medi: tool, gate e retry;
- complessi: team, handoff e parallelismo;
- molto complessi: più loop, ambiguità e budget incompatibili.

Fra i casi devono esserci: agente di ricerca, generatore di landing, revisore di codice,
automazione recensioni, pipeline contenuti e team deliberatamente inefficiente.

### 12.3 Dimensioni di qualità

Si misurano separatamente:

- fedeltà del Blueprint all'input;
- completezza di agenti, passaggi e vincoli;
- correttezza strutturale;
- qualità e azionabilità dei rilievi;
- calibrazione degli intervalli quando esiste ground truth;
- stabilità fra esecuzioni;
- token consumati da StarkEno;
- riduzione token senza perdita di qualità;
- tasso di patch accettate dagli utenti nei test umani.

Un aggregate non può compensare un fallimento sotto la soglia minima di fedeltà o
correttezza strutturale. I primi 20-30 casi guidano lo sviluppo; il gate pubblico stabile
richiede almeno 50.

### 12.4 Baseline

La baseline è una richiesta diretta allo stesso modello senza schema, lint o simulatore.
Preflight deve dimostrare almeno:

- output strutturale più valido;
- stime riproducibili;
- costo totale dichiarato e non superiore al budget configurato;
- nessun peggioramento materiale nella fedeltà al goal.

Ogni ottimizzazione del prompt viene confrontata con questa baseline e con la versione
precedente. Un meccanismo che non migliora costo, qualità o latenza viene rimosso.

## 13. Organizzazione del codice

I nomi definitivi possono seguire i pattern esistenti, ma le responsabilità restano:

```text
starkeno/
  preflight_schema.py       # dominio e validazione, puro
  preflight_compile.py      # prompt e adapter LLM
  preflight_lint.py         # regole pure
  preflight_simulate.py     # scenari e campionamento puro
  preflight_patch.py        # patch e confronto puro
  preflight_report.py       # Markdown/JSON/YAML/HTML
  preflight_service.py      # orchestrazione applicativa
  preflight_web.py          # API pubblica stateless
  cli.py                    # sottocomando, non logica di dominio
skills/
  starkeno-preflight/
    SKILL.md
tests/
  fixtures/preflight/       # soltanto dati sintetici/sanificati
```

I moduli puri non leggono orologio, filesystem, rete o variabili d'ambiente. Queste
dipendenze vengono passate dall'orchestrazione. Preflight non importa `starkeno.db` e non
introduce una seconda definizione di costo per i transcript osservati: simulato e
osservato sono grandezze diverse con tipi e nomi diversi.

## 14. Sequenza di consegna

1. schema, round-trip e fixture sintetiche;
2. compilatore manualmente validato su casi rappresentativi;
3. linter deterministico;
4. simulatore riproducibile e catalogo versionato;
5. patch, confronto e renderer;
6. CLI locale;
7. skill/plugin Codex con misure del peso contestuale;
8. API e UI pubbliche stateless;
9. corpus da almeno 50 casi, baseline e gate di stabilità;
10. preparazione alla pubblicazione, senza includere marketing o monetizzazione.

Ogni passaggio deve essere utilizzabile e verificato prima del successivo. La UI non
precede il contratto del Blueprint e il sito pubblico non precede i limiti, i log sicuri
e i gate di stabilità.

## 15. Criteri di accettazione della v1

La v1 è pronta per essere resa pubblica quando:

1. trasforma input naturale o workflow esistente in un Blueprint modificabile;
2. non simula finché l'utente non conferma l'interpretazione;
3. rileva deterministicamente i difetti strutturali definiti nel corpus;
4. produce scenari riproducibili con ipotesi, provenienza e confidenza;
5. non inventa costi o probabilità mancanti;
6. applica correzioni individuali senza modificare l'originale;
7. confronta revisioni sulle stesse condizioni;
8. funziona da sito pubblico stateless e da CLI/skill local-first;
9. consuma zero token nei turni del coding agent in cui non viene invocato;
10. dichiara preventivo e consumo della propria analisi;
11. supera suite strict, controlli di sicurezza e corpus di valutazione;
12. non invia, salva o pubblica dati del second brain o transcript personali.

## 16. Decisioni rinviate con criterio

- integrazioni native: si sceglie la prima dai formati realmente incollati dagli utenti;
- dry-run reale: soltanto se l'errore delle stime statiche resta troppo alto dopo la
  calibrazione;
- multi-agente interno: soltanto se supera il singolo agente sulla stessa suite al netto
  dei token di coordinamento;
- account e persistenza: soltanto se gli utenti chiedono di confrontare revisioni nel
  tempo;
- probabilità di successo: soltanto con ground truth sufficiente e calibrazione misurata;
- suggerimento di skill non installate: soltanto con un catalogo affidabile e una misura
  che dimostri valore superiore al costo contestuale.
