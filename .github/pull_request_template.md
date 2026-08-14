## Perché

Descrivi il problema concreto e il criterio di successo.

## Cosa cambia

Elenca le modifiche osservabili e gli eventuali trade-off.

## Verifica

- [ ] Ho osservato un test rosso prima della correzione o spiegato perché non si applica.
- [ ] Test mirati verdi.
- [ ] `python -m pytest -q -W error` verde.
- [ ] `git diff --check` pulito.
- [ ] Nessun transcript, database, log, segreto o percorso personale.
- [ ] Migrazione Alembic e test schema aggiornati, se cambia l'ORM.
- [ ] `CHANGELOG.md` aggiornato, se cambia il comportamento pubblico.
