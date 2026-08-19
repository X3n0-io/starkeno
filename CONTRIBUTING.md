# Contribuire a StarkEno

## Il contributo che serve di più non è codice

È una **misura**. La previsione di StarkEno ha sbagliato di 9x su una sola esecuzione, e
con un punto non si distingue una costante moltiplicativa da un errore che dipende dalla
forma del lavoro. Servono esecuzioni vere di forme diverse.

Non serve il tuo database e non lo vogliamo: servono otto numeri. Come produrli e cosa
cancellare prima di incollarli sta in [lo scarto 9x](docs/lo-scarto-9x.md)
([English](docs/the-9x-gap.en.md)); si manda con il template di issue **«Una misura»**.

Se invece vuoi scrivere codice, il resto di questa pagina è per te.

## Setup

Richiede Python 3.12–3.14.

```bash
python -m venv .venv
python -m pip install -c requirements/ci.txt -e ".[dev]"
python -m pytest -q
```

## Flusso di lavoro

1. Scrivi un test che riproduca il difetto o definisca il nuovo comportamento.
2. Osserva il test rosso per la ragione attesa.
3. Implementa la modifica minima e mantieni separati modello puro, persistenza e CLI.
4. Esegui test mirati, `python -m pytest -q -W error` e `git diff --check`.
5. Se tocchi dipendenze, rigenera `requirements/ci.txt` con `piptools compile` e lancia
   `pip check` e `pip-audit`.
6. Usa commit piccoli, autonomi e descrittivi; aggiorna `CHANGELOG.md` per cambiamenti
   visibili agli utenti.

## Schema e dati

Alembic è l'unica autorità sullo schema di produzione. Ogni modifica ORM richiede una
migrazione e i test di coerenza schema/ordine colonne. `create_all()` resta confinato
alle fixture.

Non contribuire transcript reali, database, log, prompt o percorsi personali. Le fixture
devono essere sintetiche o sanificate preservando soltanto la struttura necessaria al
test. Prima della PR esegui:

```bash
python scripts/verifica_segreti.py --tracked
python scripts/verifica_pubblicazione.py
```

Leggi [AGENTS.md](AGENTS.md) per gli invarianti tecnici completi.
