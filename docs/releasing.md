# Rilasciare StarkEno

La pubblicazione è un'azione manuale separata. Questo documento non esegue push, non
crea repository e non modifica branch protection.

1. Verifica che versione Python, `.codex-plugin/plugin.json` e changelog coincidano.
2. Installa l'ambiente vincolato ed esegui suite, stress e audit:

   ```bash
   python -m pip install -c requirements/ci.txt -e ".[dev]"
   python -m pytest -q -W error
   python scripts/stress_concorrenza.py
   python -m pip check
   python -m pip_audit -r requirements/ci.txt
   ```

3. Esegui gli scanner e costruisci uno snapshot nuovo fuori dal repository:

   ```bash
   python scripts/verifica_segreti.py --tracked
   python scripts/verifica_pubblicazione.py
   python scripts/costruisci_snapshot_pubblico.py <directory-vuota>
   ```

4. Dentro lo snapshot ripeti scanner, `python -m build` e suite strict.
5. Installa il wheel in un virtualenv vuoto e prova `starkeno doctor --json`,
   `starkeno report --no-open` e una migrazione su database temporaneo.
6. Attendi che i job `tests`, `package`, `audit` e `stress` siano verdi sulla commit.
7. Solo dopo revisione umana crea il tag SemVer e la release dal contenuto dello
   snapshot. Qualunque comando di push resta intenzionalmente fuori da questa procedura.

## Pubblicare su PyPI

Finché il pacchetto non è su PyPI, l'installazione è `pip install git+https://…`: installa
quello che `main` è in quel momento, non c'è un tag a cui appuntarsi, e per chi valuta il
progetto è il segnale che non è pronto. È la barriera d'ingresso più alta che resta.

Il nome `starkeno` risultava **libero** su PyPI al 19/08/2026 — verificato, `404` su
`https://pypi.org/pypi/starkeno/json`. Verificalo di nuovo prima di partire: i nomi si
prendono.

**Le credenziali sono tue e restano tue.** Nessun agente deve inserirle, e questa
procedura non le chiede mai: si usa un token API di PyPI, o meglio Trusted Publishing, che
non ha token da perdere.

### Preparazione, che si può fare in anticipo

```bash
python -m pip install -q build twine
python -m build --outdir dist
python -m twine check dist/*
```

`twine check` deve dire `PASSED` su entrambi gli artefatti. Controlla che il METADATA
porti `Project-URL`, `Classifier` e `Keywords`: sono ciò per cui il pacchetto viene
trovato, e passano inosservati quando mancano.

```bash
python -c "import zipfile;z=zipfile.ZipFile('dist/starkeno-0.3.3-py3-none-any.whl');print(z.read([n for n in z.namelist() if n.endswith('METADATA')][0]).decode())" | head -30
```

> **Le immagini nel README devono avere URL assoluti.** PyPI non risolve i percorsi
> relativi al repository: un `![...](docs/immagini/…)` che su GitHub si vede, sulla pagina
> del pacchetto è un'immagine rotta. Per questo il README usa `raw.githubusercontent.com`.

### La prova che conta

Prima di PyPI, **TestPyPI**. Costa dieci minuti e mostra la pagina come la vedranno gli
altri, README compreso:

```bash
python -m twine upload --repository testpypi dist/*
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps starkeno
```

Guarda la pagina su `test.pypi.org`. Se l'immagine è rotta o la descrizione non rende, lo
scopri lì invece che sulla versione definitiva — **su PyPI una versione non si sostituisce
e non si ricarica**: si può solo pubblicarne un'altra.

### La pubblicazione

```bash
python -m twine upload dist/*
```

Poi verifica da fuori, non fidandoti di quello che ha detto il comando:

```bash
python -m pip download --no-deps -d /tmp/prova starkeno
```

### Trusted Publishing, se ci si torna

Un token API in un file è un segreto che può uscire, e questo repository ha uno scanner
apposta perché è già successo altrove. GitHub Actions può pubblicare su PyPI **senza
token**, con OIDC: si configura un publisher fidato nelle impostazioni del progetto PyPI e
il workflow non porta credenziali. Se la pubblicazione diventa ricorrente, vale il tempo
di configurarlo.
