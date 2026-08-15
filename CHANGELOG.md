# Changelog

Il formato segue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) e il progetto
usa il versionamento semantico.

## [Unreleased]

### Added

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
