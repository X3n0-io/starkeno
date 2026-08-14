# StarkEno

Trova sprechi ed errori nel modo in cui lavori con Codex, e dice cosa fare.

Contare i token è il mezzo, non il fine: StarkEno legge i transcript che Codex scrive
già da sé e ricostruisce quanto costa il tuo modo di lavorare — per progetto, modello,
sessione, skill, plugin e server MCP.

> **Stato: Fase 2.** I dati entrano automaticamente e il conto locale è disponibile
> come pagina HTML generata su richiesta. Le cinque segnalazioni misurate arrivano in
> Fase 3; i vecchi alert R1–R4 non vengono mostrati all'avvio.

## Installazione

StarkEno è un plugin Codex con due hook:

- `Stop` avvia in background la rilettura del transcript a fine turno e registra le
  nuove chiamate;
- `SessionStart`, sincrono e limitato a `startup`, aggiunge il contesto per una breve
  riga di benvenuto solo finché non esiste ancora uno storico.

Serve Python 3.12, 3.13 o 3.14 sul `PATH`. Dalla radice del progetto:

```bash
pip install .
```

Per attivare il plugin in Codex:

1. riavvia ChatGPT/Codex desktop, perché il marketplace del repository viene letto
   all'avvio;
2. apri `/plugins`, scegli **StarkEno Local** e installa `starkeno`;
3. avvia una nuova sessione;
4. apri `/hooks`, revisiona e approva `SessionStart` e `Stop`;
5. completa tre turni normali;
6. esegui `starkeno doctor` e verifica schema `0005`, raccolta recente e plugin trovato.

Non modificare `~/.codex/config.toml` a mano. Se l'app non espone il marketplace, il
comando ufficiale alternativo è `codex plugin marketplace add .`, da usare soltanto
quando il binario locale `codex` è eseguibile senza l'errore `Accesso negato`.

`SessionStart` non scrive direttamente nell'interfaccia. Il suo `additionalContext`
istruisce il modello a mostrare una sola breve riga nel prossimo messaggio utile. Se il
database manca o è vuoto dà il benvenuto; con uno storico esistente tace fino alla
Fase 3. Non crea database e non applica migrazioni.

### Cosa fanno gli hook, e cosa non fanno

- `Stop` usa un avviatore che restituisce subito il controllo e lascia l'ingestione in
  background. Funziona anche sui runtime Codex che documentano `async` ma lo saltano
  ancora come non supportato. L'ingestione completa richiedeva 1,2–1,7 s sul transcript
  più grosso trovato (68,6 MB), ma non viene attesa dal turno.
- Entrambi escono `0` qualunque cosa accada e non scrivono su stderr. Un problema di
  StarkEno non deve rompere il lavoro dell'utente.
- Nessun dato lascia la macchina: le chiamate vengono salvate in SQLite locale.
- L'ingestione è idempotente. Se perde un turno, quello successivo rilegge lo stesso
  transcript senza duplicare le chiamate già registrate.

## Il conto

Genera la pagina e la apre nel browser predefinito:

```bash
starkeno report
```

Per scegliere il file o non aprire il browser:

```bash
starkeno report --output starkeno-conto.html --no-open
```

La pagina è un file HTML statico: non avvia server e non modifica il database. Mostra
azioni e chiamate, totale pesato, costo di lavoro, caricamento e rilettura, esiti ignoti,
partizioni e ritmo locale degli ultimi sette giorni. Le etichette skill/plugin/MCP si
sovrappongono e non vanno sommate.

## Preflight sperimentale

Preflight espone per ora un core locale e strutturato. `draft` valida e normalizza un
Blueprint JSON o YAML senza simularlo. `analyze` richiede il flag letterale
`--confirmed`: quella conferma esplicita crea una nuova revisione e solo allora esegue
lint e simulazione.

Smoke JSON in ingresso e JSON in uscita:

```bash
python -m starkeno preflight draft --input tests/fixtures/preflight/simple.json --format json --output preflight-draft.json
```

Smoke YAML in ingresso e report HTML in uscita:

```bash
python -m starkeno preflight draft --input tests/fixtures/preflight/medium.json --format yaml --output preflight-draft.yaml
python -m starkeno preflight analyze --input preflight-draft.yaml --confirmed --samples 50 --format html --output preflight-report.html
```

Il core non interpreta ancora descrizioni in linguaggio naturale e non esegue il
workflow: analizza esclusivamente Blueprint già strutturati. Le superfici naturali
`design` e `review`, la skill/plugin Codex e il sito pubblico sono incrementi successivi,
non capacità incluse in questa versione sperimentale.

I costi tool assenti restano sconosciuti: un tool gratuito deve dichiarare esplicitamente
un costo fisso zero. Costi in valute diverse non vengono convertiti o sommati.

## Dove vivono i dati

Il database non sta nella cartella del plugin: gli aggiornamenti non possono cancellare
lo storico.

| Sistema | Percorso |
|---|---|
| Windows | `%LOCALAPPDATA%\StarkEno\starkeno.db` |
| macOS | `~/Library/Application Support/StarkEno/starkeno.db` |
| Linux | `$XDG_DATA_HOME/starkeno/starkeno.db`, altrimenti `~/.local/share/starkeno/starkeno.db` |

`STARKENO_DB_PATH` ha la precedenza su questi percorsi.

`starkeno doctor` inventaria in sola lettura il percorso canonico, `starkeno.db` accanto
al codice e l'eventuale `starkeno.db.trasferito`. Nessun hook sposta o rinomina lo
storico. Un recupero richiede sempre il percorso e una conferma esplicita:

```bash
starkeno doctor --repair-from ./starkeno.db.trasferito --confirm-repair
```

La sorgente resta intatta; se la destinazione esiste viene prima salvata in un backup
timestampato. Il recupero migra e verifica la copia prima di adottarla.

## Installazione manuale degli hook

Il plugin include `.codex-plugin/plugin.json` e `hooks/hooks.json`; i comandi usano
`PLUGIN_ROOT` e le varianti Windows dedicate. Per una prova manuale usa percorsi assoluti
ai due file Python. `SessionStart` resta sincrono; `Stop` punta a
`hook_avvia_ingestione.py`, che avvia il lavoro in background. Poi verifica la
configurazione con `/hooks` nella Codex CLI.

> Gli script vanno invocati per percorso. `python -m starkeno.hook_ingestione` da una
> cartella estranea non trova il pacchetto; gli entry point includono il bootstrap per
> funzionare dalla cartella del progetto aperto in Codex.

## Verificare che stia raccogliendo

```bash
python -c "
import sqlite3, starkeno.config as c
con = sqlite3.connect(c.DB_PATH)
print('database:', c.DB_PATH)
print('chiamate:', con.execute('SELECT COUNT(*) FROM agent_actions').fetchone()[0])
for r in con.execute('SELECT project, COUNT(*), SUM(tokens_used) FROM agent_actions GROUP BY project ORDER BY 2 DESC'):
    print('  %-28s %5d chiamate  %12d token' % r)
"
```

## Cosa c'è dentro

| | |
|---|---|
| `starkeno/transcript.py` | Da `.jsonl` a chiamate API; modulo puro |
| `starkeno/hook_avvia_ingestione.py` | Avviatore non bloccante compatibile con Codex |
| `starkeno/hook_ingestione.py` | Ingestione idempotente di fine turno |
| `starkeno/hook_inizio_sessione.py` | Hook sincrono di inizio sessione |
| `starkeno/conto.py` | Modello puro del conto |
| `starkeno/report_conto.py` | Generatore della pagina HTML statica |
| `starkeno/percorsi.py` | Percorsi dati per piattaforma |
| `starkeno/db.py` | Modelli e query; unico modulo che parla con SQLAlchemy |
| `migrations/` | Catena Alembic, unica autorità sullo schema |

```bash
python -m pytest -q
```

## Licenza

MIT — vedi [LICENSE](LICENSE).

## Progetto open source

- [Come contribuire](CONTRIBUTING.md)
- [Policy di sicurezza](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Codice di condotta](CODE_OF_CONDUCT.md)

## Una nota sulle soglie

Le soglie storiche in `config.py` non sono valori da distribuire: derivano dai dati di
una sola persona. La Fase 3 userà soglie ricavate dallo storico di chi installa StarkEno.
