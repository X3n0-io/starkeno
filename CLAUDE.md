# StarkEno — contratto per agenti

La documentazione autoritativa per lavorare in questo repository è [AGENTS.md](AGENTS.md).
Leggila integralmente e rispettane architettura, comandi, invarianti e regole di
pubblicazione.

In breve:

- StarkEno è osservabilità locale per workflow di coding-agent; i token sono il mezzo,
  non il fine.
- La Fase 2 raccoglie tramite hook Codex e genera il conto; la Fase 0 sta rendendo il
  progetto installabile, diagnosticabile, recuperabile e pubblicabile in sicurezza.
- Non assumere che payload, hook o manifest di un agente siano compatibili con un altro.
- `starkeno/db.py` è l'unico modulo che importa SQLAlchemy; Alembic è l'unica autorità
  sullo schema.
- Gli hook sono fail-open, silenziosi e non devono rallentare il lavoro dell'utente.
- Test e diagnosi non devono toccare il database reale.
- Non tracciare dati personali, transcript reali, database, log o segreti.
- Nessuna pubblicazione o modifica remota senza consenso esplicito.

Prima di dichiarare un lavoro completo esegui almeno i test pertinenti,
`python -m pytest -q -W error` e `git diff --check`.
