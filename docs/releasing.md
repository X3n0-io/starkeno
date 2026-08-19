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

### La pubblicazione avviene senza credenziali

`.github/workflows/release.yml` pubblica via **Trusted Publishing**: PyPI si fida di
questo workflow, in questo repository, in questo environment, e GitHub firma la richiesta
al momento con un token OIDC che dura pochi minuti. **Non esiste un segreto da conservare,
da ruotare o da perdere** — ed è il motivo per cui questa è la strada scelta invece di un
token API in un secret.

**Configurazione, una volta sola**, su <https://pypi.org/manage/account/publishing/> →
*Add a new pending publisher*:

| Campo | Valore |
|---|---|
| PyPI Project Name | `starkeno` |
| Owner | `X3n0-io` |
| Repository name | `starkeno` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

Ripeti su <https://test.pypi.org/manage/account/publishing/> con environment `testpypi`.

> **Metti un revisore sull'environment `pypi`**, in Settings → Environments. Il job resta
> in attesa finché un umano non approva: è la regola del progetto — nessuna pubblicazione
> senza consenso esplicito — resa esecutiva invece che scritta in un documento.

### Il workflow è stato provato, non solo scritto

Eseguito il 19/08/2026 con `workflow_dispatch` verso TestPyPI, **prima** che esistesse un
publisher configurato. Esito:

| Job | Esito |
|---|---|
| `cancelli` | ✅ suite, scanner, coerenza fra versione e tag |
| `costruisci` | ✅ build, `twine check --strict`, artefatto caricato |
| `TestPyPI` | ❌ `invalid-publisher` — **l'unico motivo atteso** |

Il messaggio esatto è `valid token, but no corresponding publisher`. Le due parole che
contano sono **valid token**: lo scambio OIDC ha funzionato, GitHub ha emesso il token,
e manca soltanto la registrazione dal lato PyPI. Tutto il resto del workflow è verificato
in esecuzione, non per lettura.

I claim che GitHub dichiara — da confrontare col form, così non si configura a memoria:

```
repository        X3n0-io/starkeno
repository_owner  X3n0-io
workflow_ref      X3n0-io/starkeno/.github/workflows/release.yml@refs/heads/main
environment       testpypi        (per la pubblicazione vera: pypi)
```

> In Actions resta una corsa `Release` rossa: è questa prova. Si cancella con
> `gh run delete <id>` se dà fastidio a chi guarda, ma la sua evidenza è qui sopra.

### La prova, prima di quella vera

Da Actions → Release → *Run workflow*, destinazione **testpypi**. Costa dieci minuti e
mostra la pagina come la vedranno gli altri, README compreso:

```bash
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps starkeno
```

Guarda la pagina su `test.pypi.org`. Se l'immagine è rotta o la descrizione non rende, lo
scopri lì — **su PyPI una versione non si sostituisce e non si ricarica**: si può solo
pubblicarne un'altra.

> **Le immagini nel README devono avere URL assoluti.** PyPI non risolve i percorsi
> relativi al repository: un `![...](docs/immagini/…)` che su GitHub si vede, sulla pagina
> del pacchetto è un'immagine rotta. Per questo il README usa `raw.githubusercontent.com`.

### Il rilascio

Il workflow parte da solo sul tag, e **i cancelli girano prima del caricamento** — suite
sotto `-W error`, i due scanner, la coerenza fra la versione dichiarata nei tre punti e il
tag stesso. Non è un controllo che si spera sia stato fatto: è un job che deve passare.

```bash
git tag -a v0.4.0 -m "v0.4.0"
git push origin v0.4.0
```

Poi verifica da fuori, senza fidarti di quello che ha detto il workflow:

```bash
python -m pip download --no-deps -d /tmp/prova starkeno
```

### A mano, se il workflow non è disponibile

```bash
python -m pip install -q build twine
python -m build --outdir dist
python -m twine check --strict dist/*
python -m twine upload dist/*
```

Questa strada richiede un token API ed è la ragione per cui non è quella predefinita.
**Nessun agente deve inserirlo**: è una credenziale, e va digitata da una persona.
