# Fase 0 — Stabilizzazione prima dell'open source

**Data:** 2026-08-12  
**Stato:** design approvato a voce; in attesa di revisione della spec scritta

## 1. Obiettivo

StarkEno non aggiunge Claude Code, Gemini CLI o le segnalazioni S1–S5 finché i sette
problemi emersi dall'audit del 12 agosto non sono chiusi con prove ripetibili.

La Fase 0 consegna un prodotto Codex installabile, diagnosticabile, recuperabile e
pubblicabile senza esporre dati personali. "Chiuso" non significa che il codice sembra
corretto: significa che il criterio di accettazione indicato sotto è verde.

## 2. Stato di partenza misurato

- Suite normale: 327 test passati e 1 saltato per indisponibilità dei symlink.
- Round-trip isolato: schema `0005`, 86 chiamate ingerite, 86 dopo la riesecuzione,
  report HTML generato.
- Stress SQLite: 900/900 scritture, 0 giri del supervisore falliti, 0 risposte HTTP
  non-200 su 160, `integrity_check` riuscito.
- Suite con warning trattati come errori: 2 fallimenti per un socket non chiuso nel
  ramo di errore della guardia del supervisore.
- Nessun plugin o hook StarkEno registrato nel profilo Codex corrente.
- Il database canonico non esiste. L'unico candidato trovato nei percorsi noti è
  `starkeno.db.trasferito`, integro, schema `0003`, una riga del 4 agosto.
- `pyproject.toml` non descrive un pacchetto; non esiste CI multipiattaforma.
- I documenti tracciati contengono percorsi personali. La dashboard storica carica
  Tailwind da una CDN.

## 3. I sette problemi e la loro chiusura

### P1 — Il plugin Codex non è installato né attivo

Il repository contiene il manifest, ma averlo nel worktree non installa il plugin.
StarkEno deve distinguere chiaramente fra "codice presente", "plugin installato",
"hook approvato" e "raccolta riuscita".

Si aggiunge un comando `starkeno doctor` in sola lettura che controlla almeno:

- versione Python e dipendenze;
- presenza e revisione dello schema;
- manifest e comandi degli hook;
- presenza dell'integrazione nei file o registri ufficiali che Codex espone. Se lo stato
  di fiducia non è leggibile da un processo esterno, il doctor restituisce
  `verifica_manuale_richiesta` e indica `/hooks`, senza indovinare;
- ultimo dato raccolto e freschezza;
- round-trip isolato su un database temporaneo, senza toccare la produzione.

L'installazione non approva hook al posto dell'utente. La fiducia resta nel flusso
ufficiale `/hooks`; la documentazione deve indicare il passaggio e il doctor deve
spiegare quando manca.

**Criterio di accettazione:** da un ambiente pulito si installa StarkEno, si approvano
gli hook, si apre una nuova sessione Codex e il database canonico cresce dopo almeno
tre turni senza invocare manualmente il tool MCP. `starkeno doctor` termina con successo
e mostra evidenza dell'ultimo evento.

### P2 — Lo storico non si trova nel percorso canonico

La riparazione deve essere conservativa. Nessun file viene cancellato, spostato o
sovrascritto automaticamente. Il doctor cerca soltanto nei percorsi StarkEno noti:
percorso canonico della piattaforma, vecchia radice del progetto e copie
`.trasferito`. Non esegue una scansione indiscriminata della home.

Una modalità esplicita di riparazione:

1. inventaria i candidati in sola lettura;
2. verifica `quick_check`, revisione Alembic, numero di righe e ultimo timestamp;
3. rifiuta candidati corrotti o una scelta ambigua;
4. copia il candidato scelto nella destinazione, senza rimuovere l'origine;
5. conserva un backup della destinazione se già presente;
6. applica le migrazioni alla copia;
7. ricontrolla schema, conteggi e idempotenza.

Se non esiste una copia dello storico atteso, StarkEno lo dichiara esplicitamente:
creare un database nuovo rende di nuovo operativo il prodotto, ma non viene descritto
come "recupero".

**Criterio di accettazione:** ogni copia nota è inventariata; il miglior candidato
recuperabile è copiato e migrato senza perdita dell'originale, oppure viene prodotto un
esito verificabile "nessuno storico recuperabile". Il database canonico finale passa
`quick_check`, è a `head` e riceve nuove chiamate.

### P3 — Perdita di socket sul secondo supervisore

`guard_istanza_singola` deve chiudere il socket se `bind` o `listen` sollevano, quindi
rilanciare la stessa eccezione. Il socket viene restituito e mantenuto vivo solo nel
ramo riuscito. Non si aggiunge `SO_REUSEADDR`.

**Criterio di accettazione:** i test della guardia provano sia `bind` sia `listen`
falliti e osservano la chiusura; l'intera suite passa con `-W error`.

### P4 — Il progetto non è un pacchetto installabile

`pyproject.toml` diventa l'autorità per build e metadata. Deve dichiarare:

- nome, versione, licenza MIT, autori e descrizione;
- intervallo Python realmente testato;
- dipendenze runtime;
- package data per dashboard, migrazioni e manifest necessari;
- un solo comando principale `starkeno`, con almeno `doctor` e `report`.

La versione del pacchetto è la fonte di verità e i manifest degli agenti devono essere
controllati contro di essa. Gli URL di progetto non ricevono placeholder: vengono
aggiunti solo quando l'utente avrà scelto e creato il repository pubblico.

La build produce wheel e sdist. L'installazione non crea database, non avvia processi e
non modifica la configurazione degli agenti all'import.

**Criterio di accettazione:** wheel e sdist si costruiscono; il wheel si installa in un
virtualenv pulito; da una directory estranea funzionano import, `starkeno doctor`,
`starkeno report --no-open` e le migrazioni su un database temporaneo.

### P5 — Portabilità non dimostrata

GitHub Actions esegue la suite sugli ambienti supportati. La prima promessa pubblica è
Python 3.12–3.14 su Windows, macOS e Linux; una versione entra nella promessa solo quando
la matrice è verde. I test dipendenti dai symlink possono saltare soltanto quando la
piattaforma nega realmente la capacità, non per un controllo generico del sistema.

La CI comprende:

- suite normale e warning strict;
- build e installazione del wheel;
- test di migrazione e coerenza ORM/schema;
- hook eseguiti da una directory estranea;
- report su database assente e popolato;
- stress concorrente almeno su Windows e Linux, separato dalla suite veloce.

**Criterio di accettazione:** tutti i job obbligatori sono verdi su una commit pulita;
i loro nomi stabili sono elencati nella checklist di rilascio come status check da
rendere obbligatori quando verrà creato il repository GitHub. L'attivazione della branch
protection resta nell'azione separata di pubblicazione.

### P6 — Dipendenze e sicurezza della supply chain non governate

Le dipendenze runtime vivono in `pyproject.toml`, con limiti inferiori provati e limiti
superiori sulle versioni maggiori incompatibili. I tool di sviluppo stanno in un extra
separato. La CI usa un constraints file o lock riproducibile senza trasformare la
libreria in un'applicazione rigidamente pinnata.

Ogni build esegue almeno:

- `pip check`;
- audit delle vulnerabilità note;
- controllo che il lock/constraints sia aggiornato;
- scansione dei segreti senza stampare il valore trovato.

Gli aggiornamenti delle dipendenze arrivano tramite PR automatiche e devono attraversare
la stessa matrice. Nessun audit viene dichiarato riuscito solo perché il relativo tool
non è installato.

Un'eventuale eccezione a una vulnerabilità deve indicare dipendenza, advisory, impatto,
mitigazione, responsabile e data di scadenza; in assenza di questi campi l'audit fallisce.

**Criterio di accettazione:** installazione riproducibile, `pip check` pulito, audit senza
vulnerabilità note non accettate e scansione segreti pulita.

### P7 — Repository non pronto alla pubblicazione

Prima di GitHub vengono rimossi o generalizzati dai file tracciati:

- username, percorsi di archivi personali e percorsi assoluti privati;
- stato della macchina dell'autore presentato come documentazione del prodotto;
- istruzioni obsolete o specifiche di Claude dentro i file destinati a Codex;
- riferimenti a dati reali non necessari per riprodurre le misure.

Si aggiungono almeno `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, changelog,
template per issue/PR, `.gitattributes` e istruzioni di rilascio. Fixture e documenti
vengono controllati automaticamente contro dati personali e segreti.

La dashboard non effettua richieste a CDN: gli asset necessari vengono inclusi nel
pacchetto o sostituiti con CSS locale. La frase "nessun dato lascia la macchina" deve
essere vera per il percorso predefinito.

La storia Git privata contiene già percorsi personali. Per evitare una riscrittura
distruttiva, la pubblicazione userà una nuova storia pubblica a partire da uno snapshot
sanitizzato. Il repository attuale e la sua storia restano intatti come archivio privato.
Creare o pubblicare il repository GitHub è un'azione separata e richiederà conferma
esplicita.

**Criterio di accettazione:** scansioni privacy/segreti pulite sullo snapshot pubblico,
documentazione comunitaria presente, nessuna rete nel report o nella dashboard locale,
artefatti utente ignorati e non tracciati, e prova di installazione eseguita sullo
snapshot con storia pulita.

## 4. Confini del sistema

La Fase 0 può modificare infrastruttura, packaging, CLI diagnostica, documentazione,
test e i difetti necessari a soddisfare i criteri sopra. Non modifica la semantica del
conto e non riattiva le regole R1–R4.

Sono fuori scope fino alla chiusura della Fase 0:

- adattatori Claude Code e Gemini CLI;
- protocollo canonico multipiattaforma;
- segnalazioni S1–S5;
- dashboard nuova;
- pubblicazione o push su GitHub;
- ricerca semantica di skill alternative.

## 5. Comportamento degli errori

- Gli hook restano fail-open: escono 0 e non interrompono l'agente.
- `doctor`, build, migrazioni manuali e CI falliscono rumorosamente con una causa utile.
- La diagnosi predefinita è in sola lettura.
- Ogni riparazione dati richiede un'opzione esplicita, non sovrascrive e lascia una copia
  recuperabile.
- Un dato incompleto o una raccolta non attiva non vengono mostrati come stato sano.

## 6. Ordine di esecuzione

1. Riprodurre e correggere il leak del socket.
2. Costruire packaging e CLI `doctor` senza attivare hook.
3. Inventariare e recuperare in modo conservativo il database.
4. Installare e approvare l'integrazione Codex, poi provarla dal vivo.
5. Rendere suite e build multipiattaforma in CI.
6. Governare dipendenze e controlli di sicurezza.
7. Sanificare lo snapshot pubblico e completare la documentazione open source.
8. Rieseguire suite normale, warning strict, build isolata, round-trip, stress e prova
   live prima di dichiarare la Fase 0 completa.

## 7. Definizione di completamento

La Fase 0 è completa soltanto quando:

- tutti i criteri P1–P7 hanno evidenza allegabile;
- la raccolta Codex reale è attiva e il doctor la riconosce;
- il database canonico è integro e a `head`;
- suite, warning strict, build, installazione isolata e CI sono verdi;
- il worktree privato è pulito;
- esiste uno snapshot pubblico sanitizzato, ma nulla è stato pubblicato senza consenso;
- README e changelog distinguono chiaramente capacità supportate, beta e non ancora
  implementate.
