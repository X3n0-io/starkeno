# Changelog

Il formato segue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) e il progetto
usa il versionamento semantico.

## [Unreleased]

### Added

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

- Dashboard e report non caricano asset remoti.
- Migrazioni e risorse funzionano anche dal wheel installato.
- `starkeno doctor` e `starkeno report` non importano il core Preflight e quindi non
  pagano il caricamento di pydantic e PyYAML.
- Il job `audit` della CI esegue anche `scripts/verifica_pubblicazione.py`, finora
  soltanto locale.

### Fixed

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

## [0.2.0] - 2026-08-12

### Added

- Fase 2: conto locale per progetto, modello, sessione, skill, plugin e server MCP.
- Hook `SessionStart` e ingestione idempotente dei transcript tramite `Stop`.
