# StarkEno — istruzioni di progetto

## Scopo e stato

StarkEno osserva localmente i workflow degli agenti di coding per trovare sprechi ed
errori e suggerire cosa fare. I token sono una misura, non il prodotto.

La Fase 2 è operativa: gli hook Codex raccolgono le chiamate e `starkeno report` genera
il conto locale. La Fase 0 di stabilizzazione prepara packaging, diagnostica, recupero,
CI e snapshot open source. Le vecchie regole R1–R4 non sono una funzionalità da
riattivare; le segnalazioni misurate S1–S5 appartengono a una fase successiva.

## Comandi essenziali

```bash
python -m pip install -c requirements/ci.txt -e ".[dev]"
python -m pytest -q
python -m pytest -q -W error
python -m build
python -m pip check
python -m pip_audit -r requirements/ci.txt
python scripts/verifica_segreti.py --tracked
python scripts/verifica_pubblicazione.py
python scripts/stress_concorrenza.py
```

CLI supportata:

```bash
starkeno doctor
starkeno report --no-open
```

## Architettura

- `starkeno/transcript.py`: parser puro dei transcript alla grana
  `(session_id, message_id)`.
- `starkeno/hook_ingestione.py`: hook `Stop` fail-open e idempotente.
- `starkeno/hook_inizio_sessione.py`: contesto minimo per `SessionStart`.
- `starkeno/conto.py`: modello puro del conto.
- `starkeno/report_conto.py`: report HTML locale, senza server o rete.
- `starkeno/diagnostica.py`: controlli del doctor; produzione in sola lettura e
  round-trip soltanto su un database temporaneo.
- `starkeno/recupero.py`: recupero esplicito, conservativo e verificato.
- `starkeno/db.py`: unico modulo che importa SQLAlchemy.
- `migrations/`: schema di produzione; Alembic è l'unica autorità.

Il database utente vive nella directory dati della piattaforma, mai nel repository o
nel bundle del plugin. `STARKENO_DB_PATH` è l'override supportato nei test e negli
ambienti isolati.

## Invarianti tecnici

1. `db.UTCDateTime` è l'unico punto di normalizzazione dei fusi orari; sopra `db.py`
   tutti i datetime sono aware-UTC.
2. Nessun modulo crea session factory o database al momento dell'import.
3. I test non leggono né scrivono mai il database reale; usano `tmp_path` e
   `STARKENO_DB_PATH` risolto al momento della chiamata.
4. Il logging è fail-open: una funzione accessoria non deve far perdere l'azione
   osservata.
5. Solo `starkeno/db.py` importa SQLAlchemy.
6. `create_all()` è ammesso soltanto nella fixture di `tests/conftest.py`; in produzione
   lo schema si crea e migra con Alembic.
7. Modelli ORM e migrazioni descrivono lo stesso schema, compreso l'ordine delle colonne.
8. Ogni nuova colonna temporale usa `db.UTCDateTime`.
9. Il SQL manuale passa i datetime tramite `db.parametro_datetime`.
10. Le due implementazioni di `effective_tokens`, Python e SQL, restano coperte dal test
    differenziale e leggono gli stessi pesi.
11. Gli invarianti fra costanti sollevano eccezioni esplicite; non usare `assert` nel
    codice di produzione per condizioni portanti.
12. Gli hook escono sempre `0`, non scrivono su stderr e non usano il timeout del demone;
    `Stop` resta asincrono.
13. Ogni test deve avere una regressione concreta che lo renda rosso; evitare controlli
    testuali soddisfatti da commenti o assert sul posto sbagliato.

## Regole per modifiche e pubblicazione

- Preservare le modifiche non correlate già presenti nel worktree.
- Usare TDD per funzionalità e correzioni: rosso osservato, implementazione minima,
  suite pertinente, suite strict e `git diff --check`.
- Gli script in `scripts/` devono funzionare sia come `python scripts/nome.py` sia come
  `python -m scripts.nome`. Eseguito come file, `sys.path` contiene `scripts/` e non la
  radice del repository: un import fra script richiede l'innesto esplicito di `RADICE`
  già usato da `stress_concorrenza.py` e `verifica_pubblicazione.py`.
- Non introdurre richieste di rete nel percorso predefinito, nel report o nella dashboard.
- Non inserire transcript reali, database, log, credenziali, username, percorsi home o
  note personali nei file tracciati. Le fixture devono essere sintetiche o sanificate.
- Non creare remote, repository pubblici, push o branch protection senza autorizzazione
  esplicita dell'utente.
- La documentazione di design e i piani in `docs/superpowers/` spiegano le decisioni;
  quando divergono dal comportamento verificato, vincono codice, test e specifica più
  recente.
