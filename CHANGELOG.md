# Changelog

Il formato segue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) e il progetto
usa il versionamento semantico.

## [Unreleased]

### Added

- **Il sito è anche in inglese**: <https://x3n0-io.github.io/starkeno/en/>. Le due pagine
  condividono un unico foglio di stile e si rimandano a vicenda con `hreflang`; il README
  inglese punta ora alla pagina inglese.
- **Anteprima del link** (Open Graph e Twitter card) su entrambe le pagine: incollato in
  una comunità, il link mostra titolo, descrizione e immagine invece di un URL nudo.
- **Il confronto previsto/osservato è disegnato**, non solo raccontato: due barre per
  misura, il freddo per la stima e il caldo per il costo vero, così lo scarto diverso fra
  le due misure si vede prima di leggerlo.
- Tema chiaro e scuro secondo le preferenze di sistema, e `prefers-reduced-motion`
  rispettato.
- `scripts/verifica_sito.py`, con diciotto test suoi, sostituisce il controllo in linea
  dentro il workflow di Pages.

### Changed

- **Il sito ha un aspetto suo**: viola e nero spazio di notte, bianco luce di giorno,
  campo stellare e aurore disegnate con gradienti, vetro smerigliato sulle schede, titolo
  in sfumatura, bottoni a pillola. Nessuna immagine di sfondo, nessun font scaricato,
  nessuno script: il peso della pagina resta quello del testo, e il cancello che vieta le
  terze parti non e' stato toccato.
- **Il bianco sul bottone viola stava a 3,3:1**, sotto lo standard AA. Il pieno del
  bottone ora non segue il tema e sta fra 5,7:1 e 6,9:1.
- **Le due barre erano finite nella stessa famiglia di colore.** Sfumavano entrambe nel
  viola del marchio, e a colpo d'occhio la stima e il costo vero si somigliavano: la
  decorazione si stava mangiando il significato. Ora il viola resta alla stima e il caldo
  al costo osservato.
- **Via i trattini lunghi dal testo del sito**, in tutte e due le lingue: erano una
  stampella ritmica. Restano solo i tre che separano il nome dal sottotitolo.
- **I due README dicevano ancora «una misura sola»**, in cinque punti ciascuno, mentre le
  misure sono due dal 19/08. Corretti insieme: titolo della sezione, riquadro di stato,
  nota sui tool MCP, richiesta di misure e elenco di quello che manca.
- **Il sito non si presenta più al negativo.** Diceva «guarda cosa si rifiuta di fare» e
  «non ti dà un numero»: chi leggeva i titoli senza il corpo capiva che StarkEno non
  prevede, cioè l'opposto di quello che fa. Stessi fatti, detti per quello che sono —
  quattro scenari invece di uno, confidenza dichiarata, provenienza di ogni stima.
- **I limiti stanno in un posto solo.** Erano ripetuti su sito, README e descrizioni; il
  README resta l'elenco completo, il sito ne tiene le due righe che servono a chi decide
  se installare.
- **Il cancello del sito distingue le sottorisorse dai collegamenti.** Prima cercava
  `https?://` in tutto il testo: vietava di linkare PyPI e non guardava dentro `url()` di
  un CSS né dentro `srcset`, che sono i posti da cui un font o un pixel di tracciamento
  entrerebbe senza farsi notare. Ora quello che il browser scarica da solo deve stare su
  un host ammesso, quello che apre una persona è permesso ed **elencato nel log**, e uno
  script in linea fa fallire il deploy.

## [0.4.1] - 2026-08-20

### Changed

- **`pip install starkeno`**: l'installazione documentata non passa più da
  `git+https://…`. La 0.4.0 è su [PyPI](https://pypi.org/project/starkeno/) con wheel e
  sdist, pubblicata da un workflow che non custodisce nessuna credenziale.
- Corrette due affermazioni diventate false: il README diceva «non c'è ancora un rilascio
  su PyPI» e «nessun rilascio appuntabile».

### Added

- **Il sito**, su GitHub Pages: <https://x3n0-io.github.io/starkeno/>. Una pagina sola,
  senza build e senza richieste a terze parti — font di sistema, zero CDN, zero analytics.
  Un cancello nel workflow fallisce il deploy se la pagina contatta un host estraneo.
- **La GIF dei tre comandi** (`docs/immagini/simulatore.gif`), con comandi e risposte veri
  da un'installazione pulita, in entrambi i README e nel sito.
- `scripts/genera_gif_simulatore.py` la rigenera quando i comandi cambiano.

## [0.4.0] - 2026-08-19

### Added

- **La seconda misura dello scarto**, e con due punti l'ipotesi della costante
  moltiplicativa cade: 9,15x contro 3,1x. Registrata in `docs/lo-scarto-9x.md` con i
  propri limiti dichiarati — non è un consuntivo attribuito ai nodi, e il Blueprint è
  stato scritto dopo.
- `tests/fixtures/preflight/sessione-lunga.json`, il Blueprint che descrive una sessione
  lunga di lavoro con un agente.
- **`starkeno preflight esempio`**: scrive su disco il Blueprint d'esempio spedito col
  pacchetto. I tre comandi in cima al README puntavano a `tests/fixtures/`, che chi
  installa con `pip` non ha: la porta d'ingresso della metà predittiva falliva per
  chiunque non avesse clonato il repository. Rifiuta di sovrascrivere un file esistente.
- **Il simulatore si prova in due comandi**, in cima a entrambi i README, con l'immagine
  del report che produce. Non serve plugin, hook o server MCP: la fixture è già nel
  repository e il lettore riproduce esattamente quella schermata.
- `scripts/genera_immagine_simulazione.py` rigenera quell'immagine dalla fixture.
- `docs/lo-scarto-9x.md` e la sua versione inglese: perché la previsione ha sbagliato di
  9x, perché è un errore strutturale e non aritmetico, e la domanda che ne resta aperta —
  costante moltiplicativa o dipendente dalla forma del lavoro. Con un invito a mandare
  misure: otto numeri, niente database e niente transcript.
- Template di issue **«Una misura»**, che chiede esattamente quei numeri e pretende che
  `project`, `session_id`, `run_key` e `blueprint_hash` siano stati tolti.
- `scripts/genera_immagine_conto.py`: rigenera l'immagine del conto per il README da dati
  di nessuno, così non invecchia in silenzio.
- Metadati per farsi trovare: `keywords`, `classifiers` e `project.urls` nel pacchetto.
- `docs/releasing.md` documenta la pubblicazione su PyPI, TestPyPI compreso.
- `README.en.md`, con quattro guardie che impediscono alle due lingue di divergere.

### Changed

- Dipendenze allineate: `actions/checkout` 4 -> 7, `actions/setup-python` 5 -> 7,
  `websockets` 16.1.1 -> 17.0.1 con il vincolo in `pyproject.toml` alzato a `<18`.
- Il README apre con la previsione invece che con il 60% di rilettura: quel numero è noto
  a chiunque segua il tema, mentre la previsione è l'unica cosa che il progetto tenta da
  solo. Il 60% resta, come spiegazione dello scarto.
- Il progetto parla italiano: README, skill, manifest e metadati. Il `description` della
  skill resta bilingue perché è la superficie con cui l'agente decide se invocarla.
- Le immagini nel README usano URL assoluti: PyPI non risolve i percorsi relativi al
  repository e mostrerebbe un'immagine rotta.

### Removed

- **La dipendenza `anthropic`**, mai importata da nessun file del repository. Era stata
  aggiunta il 15/08/2026 per un client che il cambio di architettura dello stesso giorno
  ha reso inutile — l'agente genera, StarkEno valida — e il briefing del 16/08 la dava
  già per rimuovibile con un commit dedicato. Il modulo `preflight_anthropic.py` che
  avrebbe dovuto usarla non è mai esistito. L'installazione perde cinque pacchetti:
  `anthropic`, `jiter`, `docstring-parser`, `distro`, `sniffio`.

### Fixed

- **Un ciclo lungo non produce più «Errore interno».** Oltre circa 150 passaggi il
  lookahead ricorsivo del simulatore sfonda lo stack; ora il limite si dichiara, con il
  rimedio, ed esce 2 invece di 1. Il limite resta: è la ricorsione a doverlo perdere.

### Security

- Lo scanner dei segreti riconosce le credenziali AWS: l'identificativo `AKIA…`/`ASIA…`,
  che si riconosce da solo, e la chiave segreta quando compare accanto al proprio nome.
  Prima passavano entrambe, e lo scanner è il cancello che precede ogni pubblicazione.
  La chiave segreta lontana dal proprio nome resta invisibile — è dichiarato in un test,
  perché quaranta caratteri base64 da soli sono indistinguibili da uno sha1.

## [0.3.3] - 2026-08-19

### Added

- Consuntivo di un'esecuzione: tre tool MCP (`blueprint_run_start`, `blueprint_run_node`,
  `blueprint_run_end`) e il comando `starkeno consuntivo` confrontano il preventivo di un
  Blueprint con le chiamate davvero raccolte, dichiarando cosa non sanno attribuire.
- Claude Code è un harness supportato e installabile, accanto a Codex, con un bundle e
  un marketplace propri.
- `starkeno doctor` elenca gli harness rilevati sulla macchina e, per quelli che non
  sa misurare, dice perché.
- Pacchetto wheel/sdist e CLI `starkeno doctor` / `starkeno report`.
- Diagnostica locale, round-trip isolato e inventario degli storici noti.
- Recupero esplicito con copia consistente, migrazione, verifica e backup.
- Marketplace locale Codex, matrice CI, stress concorrente, audit e scanner pubblici.
- Core sperimentale Preflight con schema Blueprint v1 immutabile, round-trip JSON/YAML
  e hash canonico.
- Linter deterministico con findings ordinati ed evidenze stabili; simulatore
  riproducibile con scenari, retry, loop, parallelismo e prezzi sconosciuti conservati
  come tali.
- Correzioni JSON Patch atomiche e reversibili, confronto fra revisioni alle stesse
  condizioni ed export JSON, YAML, Markdown e HTML locale.
- Basi quantitative frozen e versionate nei report/confronti; costi fissi tool Decimal
  distinti fra sconosciuti e zero esplicito, senza conversioni implicite di valuta.
- CLI strutturata `starkeno preflight draft` / `analyze --confirmed` e corpus smoke
  sintetico per sequenze, tool, team, handoff, choice, parallelismo e loop illimitato.

### Changed

- Il riconoscimento del formato di transcript passa da un ramo condizionale a un
  registro di harness. Un harness riconosciuto ma non misurabile produce zero chiamate
  invece di una stima: Antigravity non espone conteggi di token in nessun punto della
  sua cartella dati.
- Su Windows il database esce da `%LOCALAPPDATA%` e va in `%USERPROFILE%\.starkeno\`.
  Un processo lanciato da un host impacchettato MSIX scrive sotto `AppData\Local`
  nell'overlay privato del pacchetto: misurato, lo stesso script contava 12 righe
  eseguito dall'hook e 699 da una shell, allo stesso percorso. `starkeno doctor`
  segnala come recuperabile lo storico rimasto nella vecchia posizione.
- Il README è in inglese e dichiara lo stato verificato di ogni harness.
- Dashboard e report non caricano asset remoti.
- Migrazioni e risorse funzionano anche dal wheel installato.
- `starkeno doctor` e `starkeno report` non importano il core Preflight e quindi non
  pagano il caricamento di pydantic e PyYAML.
- Il job `audit` della CI esegue anche `scripts/verifica_pubblicazione.py`, finora
  soltanto locale.

### Fixed

- La skill arriva anche a Codex. I due harness montano radici di plugin diverse dallo
  stesso repository — Claude Code `plugin-claude-code/`, Codex la radice — quindi una
  copia sola era invisibile a uno dei due. Ora esistono entrambe e un test fallisce se
  divergono.
- `starkeno doctor` dichiara quando la copia installata del plugin esegue codice diverso
  dal pacchetto. Correggere il bundle nel repository non aggiorna cio' che gira: l'harness
  copia il plugin nella propria cache, e quella copia e' ciò che esegue. Il confronto e'
  strutturale sul JSON, non testuale, perche' indentazione e fine riga divergono fra la
  copia scritta dall'harness e il sorgente uscito da git.
- `starkeno doctor` dichiara quando uno storico ha righe più recenti del canonico. È la
  firma di una raccolta instradata male — l'hook raccoglie per intero, ma in un file che
  `report` e `consuntivo` non guardano — e il controllo rispondeva `ok` perché il
  canonico restava integro. I dati per accorgersene c'erano già tutti; nessuno li
  confrontava.
- Gli hook Claude Code si invocano con `python -P -m`, non `python -m`. Senza `-P` il
  primo elemento di `sys.path` è la working directory della sessione, che ha la
  precedenza sul pacchetto installato: chi lavora dentro un qualunque checkout di
  StarkEno faceva eseguire all'hook il codice di quel checkout. Misurato il 19/08/2026
  su un archivio anteriore allo spostamento della cartella dati: la raccolta funzionava
  per intero ma scriveva nel percorso storico, quindi `report`, `doctor` e `consuntivo`
  non ne vedevano una riga. Nessun errore e nessuna riga su stderr, perché l'invariante
  12 li vieta entrambi.
- `starkeno consuntivo` dichiara invece di cadere quando non c'è niente da leggere. La
  sessione è aperta in sola lettura (`mode=ro`, che fallisce invece di creare): su
  un'installazione fresca il comando usciva con un traceback `OperationalError`, e su uno
  schema precedente alla tabella `blueprint_runs` con `no such table`. Adesso entrambi
  sono un messaggio con il rimedio e un'uscita non-zero.
- I totali osservati passano dalle stesse guardie di qualità dati del conto
  (`rules.effective_tokens`), non da una copia parziale. Misurato: una riga i cui
  componenti superavano il totale dava `input_tokens = -1100` senza alcun segnale, ed era
  pure prezzata. Ora una riga incoerente è contata a parte, dichiarata nella resa e mai
  prezzata.
- La riga «Moneta: assente» distingue le sue due cause — nessun listino completo, oppure
  listini in valute diverse — perché i rimedi sono opposti. Prima ne dichiarava una sola
  per entrambe.
- Il confronto stampa i modelli che la **stima** non ha saputo prezzare
  (`unknown_prices`), come già faceva per quelli osservati: due numeri adiacenti non
  possono avere onestà diversa senza dirlo. Il costo stimato non viene soppresso, perché
  uno scenario con costo valorizzato non ha usato le categorie mancanti.
- Il `README.md` dichiara il confronto, i tre tool MCP e il comando `starkeno consuntivo`:
  erano documentati solo in `AGENTS.md`, che un visitatore del repository non legge.
- Gli hook di Claude Code sono sincroni: le varianti non bloccanti non raccoglievano
  niente e non lo dicevano. L'avviatore restituisce il controllo in 354 ms e `async`
  rientra subito, mentre l'ingestione ne richiede circa 1600, e il processo non
  sopravvive. Su Codex l'avviatore resta, perché lì serve.
- Un hook `SessionEnd` recupera l'ultimo turno di ogni sessione Claude Code: lo `Stop`
  scatta prima che il turno sia sul disco, e per l'ultimo non esiste un giro successivo
  che lo recuperi.
- L'ingestione riconosce il transcript a eventi di Codex e separa correttamente token
  nuovi, cache letta, cache scritta e token di ragionamento.
- Chiusura del socket del supervisore quando `bind` o `listen` falliscono.
- L'hook non avvia più riparazioni o spostamenti dati automatici.
- La lettura di uno storico WAL senza sidecar non crea file `-wal` o `-shm` accanto
  alla sorgente.
- La simulazione Preflight di un ciclo opzionale dichiarato come `choice` termina: la
  valutazione dei rami non è più esponenziale nella profondità del percorso e
  un'esplorazione oltre il tetto dichiara lo scenario mancante invece di non rispondere.
- Un `remove` Preflight su un campo di primo livello è un conflitto che indirizza a
  `replace`: la sua inversa non era applicabile e il contenuto rimosso andava perso in
  silenzio.
- I prezzi ignoti Preflight dichiarano di riguardare il caso peggiore, così un costo
  valorizzato accanto a un prezzo mancante non resta ambiguo.
- Una precondizione `test` torna ammessa anche sui campi protetti perché non scrive, e
  soltanto i `ValueError` diventano conflitti di patch.
- `scripts/verifica_pubblicazione.py` funziona anche eseguito come file: l'import fra
  script risolveva soltanto con `python -m`.
- L'hook di fine turno chiude la connessione al database invece di lasciarla viva fino
  alla fine del processo: `session.close()` la restituisce al pool, solo
  `engine.dispose()` la chiude. Costo misurato sul percorso caldo: 0,9 ms mediani.
- Una connessione non entra più in stato orfano quando i PRAGMA di apertura falliscono
  su un database occupato da un altro processo: era il percorso dell'hook su database
  bloccato, che perdeva una connessione e il suo lock a ogni turno.
- Il recupero non fallisce più su Windows con `PermissionError` per una connessione
  lasciata aperta sulla destinazione.

### Changed

- La suite fallisce il test che lascia aperta una connessione SQLite, con l'attribuzione
  al test colpevole. Da Python 3.13 una connessione raccolta dal GC senza `close()`
  emette `ResourceWarning`, che sotto `-W error` uccideva un test a caso: la CI era rossa
  su 3.13 e 3.14 su tutti e tre i sistemi.

## [0.2.0] - 2026-08-12

### Added

- Fase 2: conto locale per progetto, modello, sessione, skill, plugin e server MCP.
- Hook `SessionStart` e ingestione idempotente dei transcript tramite `Stop`.
