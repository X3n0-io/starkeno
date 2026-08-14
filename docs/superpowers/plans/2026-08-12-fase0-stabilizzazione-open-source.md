# Fase 0 — Stabilizzazione Open Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chiudere con prove ripetibili P1–P7 della spec di stabilizzazione e consegnare StarkEno installabile, diagnosticabile, recuperabile e pronto per uno snapshot pubblico pulito.

**Architecture:** Il runtime rimane locale e fail-open negli hook. Un nuovo nucleo diagnostico in sola lettura ispeziona runtime, database e installazione Codex; un modulo separato esegue soltanto riparazioni esplicite e conservative. Packaging, CI e controlli di pubblicazione circondano il nucleo esistente senza cambiare la semantica del conto o riattivare R1–R4.

**Tech Stack:** Python 3.12–3.14, SQLite, SQLAlchemy 2, Alembic, pytest, Hatchling, GitHub Actions, pip-audit.

## Global Constraints

- La spec autoritativa è `docs/superpowers/specs/2026-08-12-stabilizzazione-open-source-design.md`.
- Non aggiungere Claude Code, Gemini CLI, protocollo multipiattaforma o segnalazioni S1–S5.
- Non modificare la semantica di `conto.py` e non riattivare R1–R4.
- Gli hook continuano a uscire 0, non scrivono su stderr e non bloccano il lavoro dell'agente.
- `doctor` è in sola lettura salvo `--repair-from PATH --confirm-repair`.
- Una riparazione non cancella l'origine, non sovrascrive senza backup e non sceglie silenziosamente fra candidati.
- Alembic resta l'unica autorità sullo schema; `create_all()` resta confinato a `tests/conftest.py`.
- `starkeno/db.py` resta l'unico modulo che importa SQLAlchemy.
- Nessun test legge o scrive il database reale: usare `STARKENO_DB_PATH`, `tmp_path` e dipendenze iniettate.
- Il percorso predefinito non effettua richieste di rete e nessun asset viene caricato da CDN.
- Supporto dichiarato soltanto per Python 3.12, 3.13 e 3.14 su Windows, macOS e Linux dopo matrice verde.
- Nessun push, repository GitHub o modifica della branch protection senza conferma esplicita dell'utente.
- Ogni task termina con test focalizzati, suite pertinente, `git diff --check` e un commit autonomo.

## File structure

- `starkeno/migrazioni.py` — costruisce configurazioni Alembic valide sia dal repository sia dal wheel.
- `starkeno/diagnostica.py` — modelli e controlli read-only del comando doctor.
- `starkeno/recupero.py` — inventario e copia conservativa dei database; nessuna UX CLI.
- `starkeno/risorse.py` — risolve manifest, hook e risorse incluse nel wheel.
- `starkeno/cli.py` — unico parser CLI, delega a doctor, recupero e report.
- `starkeno/__main__.py` — abilita `python -m starkeno`.
- `scripts/verifica_pubblicazione.py` — scansione deterministica dei file tracciati senza stampare segreti.
- `scripts/costruisci_snapshot_pubblico.py` — esporta `HEAD` in una directory nuova priva di `.git`.
- `.agents/plugins/marketplace.json` — marketplace locale ufficiale per installare il plugin in Codex.
- `.github/workflows/ci.yml` — suite strict, build, installazione wheel e audit.
- `.github/workflows/stress.yml` — stress concorrente su Windows e Linux.

---

### Task 1: Chiudere il socket nel ramo di errore del supervisore

**Files:**
- Modify: `starkeno/supervisor.py:475-499`
- Modify: `tests/test_supervisor_loop.py:152-222`

**Interfaces:**
- Consumes: `guard_istanza_singola(porta: int) -> socket.socket` esistente.
- Produces: la stessa firma; il socket locale viene chiuso su ogni eccezione di `bind` o `listen`.

- [ ] **Step 1: Aggiungere i test rossi per `bind` e `listen`**

Usare un fake esplicito, non il garbage collector:

```python
class SocketFallibile:
    def __init__(self, *, fallisce_su):
        self.fallisce_su = fallisce_su
        self.closed = False

    def bind(self, _indirizzo):
        if self.fallisce_su == "bind":
            raise OSError("porta occupata")

    def listen(self, _backlog):
        if self.fallisce_su == "listen":
            raise OSError("listen fallita")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("fase", ["bind", "listen"])
def test_guard_closes_the_socket_when_startup_fails(monkeypatch, fase):
    finto = SocketFallibile(fallisce_su=fase)
    monkeypatch.setattr("starkeno.supervisor.socket.socket", lambda *_: finto)

    with pytest.raises(OSError):
        guard_istanza_singola(47_710)

    assert finto.closed is True
```

- [ ] **Step 2: Verificare il rosso e il warning strict corrente**

Run: `python -m pytest -q tests/test_supervisor_loop.py -W error`

Expected: il nuovo test fallisce perché `closed` resta `False`; i due ResourceWarning già osservati possono comparire nello stesso run.

- [ ] **Step 3: Chiudere il socket e rilanciare l'eccezione originale**

```python
def guard_istanza_singola(porta: int = PORTA_GUARDIA):
    presa = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        presa.bind(("127.0.0.1", porta))
        presa.listen(1)
    except BaseException:
        presa.close()
        raise
    return presa
```

- [ ] **Step 4: Verificare test focalizzati e intera suite strict**

Run: `python -m pytest -q tests/test_supervisor_loop.py -W error`

Expected: PASS.

Run: `python -m pytest -q -W error`

Expected: 327 passati, 1 skip ammesso soltanto se Windows nega realmente i symlink.

- [ ] **Step 5: Commit**

```powershell
git add -- starkeno/supervisor.py tests/test_supervisor_loop.py
git commit -m "fix: chiude la guardia del supervisore in errore"
```

### Task 2: Rendere le migrazioni utilizzabili dal wheel

**Files:**
- Create: `starkeno/migrazioni.py`
- Create: `migrations/__init__.py`
- Create: `migrations/versions/__init__.py`
- Modify: `starkeno/hook_ingestione.py:42-76`
- Modify: `starkeno/schema_version.py:13-35`
- Create: `tests/test_migrazioni_runtime.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Produces: `configurazione_alembic(db_path: str | Path) -> alembic.config.Config`.
- Produces: `upgrade_head(db_path: str | Path, *, silenzioso: bool = False) -> None`.
- Produces: `revisione_head() -> str`.
- Consumers: recupero, hook di ingestione, schema check e packaging.

- [ ] **Step 1: Scrivere test che non dipendono da `alembic.ini`**

```python
def test_runtime_config_uses_packaged_migrations(tmp_path):
    cfg = configurazione_alembic(tmp_path / "runtime.db")
    assert Path(cfg.get_main_option("script_location")).name == "migrations"
    assert cfg.config_file_name is None


def test_runtime_upgrade_builds_head_schema(tmp_path):
    percorso = tmp_path / "runtime.db"
    upgrade_head(percorso, silenzioso=True)
    with sqlite3.connect(percorso) as conn:
        assert conn.execute("select version_num from alembic_version").fetchone()[0] == revisione_head()
        assert conn.execute("pragma quick_check").fetchone()[0] == "ok"
```

Aggiornare il test di coerenza delle migrazioni affinché confronti anche
`revisione_head()` col valore ottenuto dal vecchio helper del test.

- [ ] **Step 2: Verificare il rosso**

Run: `python -m pytest -q tests/test_migrazioni_runtime.py`

Expected: FAIL con `ModuleNotFoundError: starkeno.migrazioni`.

- [ ] **Step 3: Implementare la configurazione senza file ini**

```python
from contextlib import nullcontext, redirect_stderr
from importlib.resources import files
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def configurazione_alembic(db_path):
    cfg = Config()
    cfg.set_main_option("script_location", str(files("migrations")))
    cfg.set_main_option("sqlalchemy.url", "sqlite:///%s" % str(Path(db_path)).replace("\\", "/"))
    return cfg


def revisione_head():
    return ScriptDirectory.from_config(configurazione_alembic(":memory:")).get_current_head()


def upgrade_head(db_path, *, silenzioso=False):
    contesto = redirect_stderr(StringIO()) if silenzioso else nullcontext()
    with contesto:
        command.upgrade(configurazione_alembic(db_path), "head")
```

`hook_ingestione.prepara_database` deve delegare a `upgrade_head`; `schema_version.head_revision`
deve delegare a `revisione_head`. Nessuno dei due costruisce più percorsi relativi al repository.

- [ ] **Step 4: Verificare migrazioni, hook e schema**

Run: `python -m pytest -q tests/test_migrazioni_runtime.py tests/test_migrations.py tests/test_hook.py tests/test_schema_v1.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- migrations/__init__.py migrations/versions/__init__.py starkeno/migrazioni.py starkeno/hook_ingestione.py starkeno/schema_version.py tests/test_migrazioni_runtime.py tests/test_migrations.py
git commit -m "refactor: rende portabili le migrazioni runtime"
```

### Task 3: Costruire la diagnosi read-only

**Files:**
- Create: `starkeno/diagnostica.py`
- Create: `starkeno/risorse.py`
- Create: `tests/test_diagnostica.py`

**Interfaces:**
- Produces: `Controllo(codice: str, stato: str, dettaglio: str, dati: dict)`.
- Produces: `CandidatoDatabase(percorso: Path, integro: bool, revisione: str | None, righe: int | None, ultimo_evento: str | None, errore: str | None)`.
- Produces: `ispeziona_database(path: Path) -> CandidatoDatabase`.
- Produces: `trova_plugin_codex(codex_root: Path) -> Controllo`.
- Produces: `esegui_diagnosi(*, db_path: Path, codex_root: Path, plugin_root: Path, now: datetime) -> tuple[Controllo, ...]`.
- Produces: `plugin_root() -> Path`, che usa la radice sorgente se presente e altrimenti `starkeno/plugin_bundle` nel wheel.

- [ ] **Step 1: Scrivere test rossi per database, plugin e assenza di effetti collaterali**

```python
def test_missing_database_is_reported_without_being_created(tmp_path):
    path = tmp_path / "non-esiste" / "starkeno.db"
    esito = ispeziona_database(path)
    assert esito.integro is False
    assert esito.errore == "database_assente"
    assert not path.exists()


def test_database_inspection_reports_integrity_revision_rows_and_freshness(tmp_path):
    path = tmp_path / "starkeno.db"
    upgrade_head(path, silenzioso=True)
    inserisci_azione(path, timestamp="2026-08-12 10:00:00")
    esito = ispeziona_database(path)
    assert (esito.integro, esito.revisione, esito.righe) == (True, revisione_head(), 1)
    assert esito.ultimo_evento.startswith("2026-08-12")
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()


def test_codex_plugin_is_found_in_the_official_cache_layout(tmp_path):
    manifest = tmp_path / "plugins/cache/starkeno-local/starkeno/local/.codex-plugin/plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"starkeno","version":"0.3.0"}', encoding="utf-8")
    esito = trova_plugin_codex(tmp_path)
    assert esito.stato == "ok"
    assert esito.dati["versione"] == "0.3.0"
```

Il fixture helper `inserisci_azione` usa `sqlite3` e una INSERT esplicita sul database temporaneo.

- [ ] **Step 2: Verificare il rosso**

Run: `python -m pytest -q tests/test_diagnostica.py`

Expected: FAIL con `ModuleNotFoundError: starkeno.diagnostica`.

- [ ] **Step 3: Implementare dataclass e ispezione read-only**

```python
@dataclass(frozen=True)
class Controllo:
    codice: str
    stato: Literal["ok", "attenzione", "errore", "manuale"]
    dettaglio: str
    dati: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidatoDatabase:
    percorso: Path
    integro: bool
    revisione: str | None
    righe: int | None
    ultimo_evento: str | None
    errore: str | None
```

`ispeziona_database` apre SQLite con URI `mode=ro`; se il file non esiste ritorna senza
creare la cartella. Se non esiste un sidecar `-wal` usa anche `immutable=1`, evitando di
creare `-wal` o `-shm` durante la diagnosi di una copia chiusa; se il WAL esiste usa
`mode=ro` normale per non ignorare transazioni recenti. Esegue `pragma quick_check`, verifica la presenza di
`alembic_version` e `agent_actions`, poi legge conteggio e massimo timestamp. Chiude la
connessione in `finally`.

`trova_plugin_codex` cerca soltanto sotto `codex_root/plugins/cache` e valida JSON,
`name == "starkeno"` e versione. Non legge né modifica chiavi TOML non documentate.

`risorse.plugin_root()` usa `Path(__file__).resolve().parent.parent` quando lì trova
`.codex-plugin/plugin.json`; dopo l'installazione del wheel ritorna
`Path(importlib.resources.files("starkeno")) / "plugin_bundle"`. Un test separato
monkeypatcha la radice sorgente come assente e verifica che il fallback contenga
manifest e hook inclusi dal build.

- [ ] **Step 4: Comporre il rapporto senza indovinare il trust**

`esegui_diagnosi` deve produrre controlli distinti `python`, `dipendenze`, `database`,
`schema`, `plugin_codex`, `hook_trust` e `raccolta`. Se il plugin esiste ma non ci sono
dati recenti, `hook_trust` vale `manuale` con dettaglio `Apri /hooks in una nuova sessione`.
La raccolta è `ok` soltanto se l'ultimo evento non è nel futuro e dista al massimo sette giorni.

- [ ] **Step 5: Verificare diagnosi e invarianti import**

Run: `python -m pytest -q tests/test_diagnostica.py tests/test_percorsi.py tests/test_regressions.py`

Expected: PASS.

Run: `python -c "import starkeno.diagnostica; print('import-ok')"`

Expected: `import-ok` e nessun database creato.

- [ ] **Step 6: Commit**

```powershell
git add -- starkeno/diagnostica.py starkeno/risorse.py tests/test_diagnostica.py
git commit -m "feat: aggiunge la diagnosi locale read only"
```

### Task 4: Recuperare il database in modo conservativo

**Files:**
- Create: `starkeno/recupero.py`
- Create: `tests/test_recupero.py`
- Modify: `starkeno/trasloco.py`
- Modify: `starkeno/hook_ingestione.py`
- Modify: `tests/test_trasloco.py`
- Modify: `tests/test_hook.py`

**Interfaces:**
- Produces: `inventaria_candidati(*, canonico: Path, radice_progetto: Path) -> tuple[CandidatoDatabase, ...]`.
- Produces: `recupera_database(sorgente: Path, destinazione: Path, *, now: datetime, migra: Callable[[Path], None]) -> Path | None`; ritorna il backup creato o `None`.
- Produces: `RecuperoError(RuntimeError)` per sorgente invalida, conflitto o staging incompleto.
- Consumes: `ispeziona_database` e `upgrade_head`.

- [ ] **Step 1: Scrivere i test rossi per inventario, copia, backup e rollback**

```python
def test_inventory_only_checks_known_starkeno_paths(tmp_path):
    canonico = tmp_path / "dati/starkeno.db"
    radice = tmp_path / "repo"
    trovati = inventaria_candidati(canonico=canonico, radice_progetto=radice)
    assert [x.percorso for x in trovati] == [
        canonico,
        radice / "starkeno.db",
        radice / "starkeno.db.trasferito",
    ]


def test_recovery_copies_migrates_and_preserves_the_source(tmp_path):
    sorgente = crea_database_0003(tmp_path / "storico.db", righe=3)
    destinazione = tmp_path / "dati/starkeno.db"
    backup = recupera_database(
        sorgente, destinazione, now=ORA,
        migra=lambda p: upgrade_head(p, silenzioso=True),
    )
    assert backup is None
    assert sorgente.exists()
    assert ispeziona_database(destinazione).righe == 3
    assert ispeziona_database(destinazione).revisione == revisione_head()


def test_existing_destination_is_backed_up_before_replacement(tmp_path):
    sorgente = crea_database_0003(tmp_path / "storico.db", righe=3)
    destinazione = crea_database_head(tmp_path / "dati/starkeno.db", righe=1)
    backup = recupera_database(sorgente, destinazione, now=ORA, migra=migra)
    assert backup.name == "starkeno.db.backup-20260812T120000Z"
    assert ispeziona_database(backup).righe == 1
    assert ispeziona_database(destinazione).righe == 3
```

Aggiungere un test in cui `migra` solleva: la destinazione e l'origine devono restare
inalterate e il file `.recupero` deve sparire.

- [ ] **Step 2: Verificare il rosso**

Run: `python -m pytest -q tests/test_recupero.py`

Expected: FAIL con `ModuleNotFoundError: starkeno.recupero`.

- [ ] **Step 3: Implementare copia SQLite verso staging**

Usare `sqlite3.Connection.backup`, non `shutil.copy2`, per includere transazioni WAL
consolidabili. Il flusso minimo è:

```python
def _copia_sqlite(sorgente: Path, destinazione: Path):
    with sqlite3.connect(f"file:{sorgente.as_posix()}?mode=ro", uri=True) as src:
        with sqlite3.connect(destinazione) as dst:
            src.backup(dst)


def recupera_database(sorgente, destinazione, *, now, migra):
    sorgente, destinazione = Path(sorgente), Path(destinazione)
    if sorgente.resolve() == destinazione.resolve():
        raise RecuperoError("sorgente e destinazione coincidono")
    if not ispeziona_database(sorgente).integro:
        raise RecuperoError("sorgente non integra")
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    staging = destinazione.with_name(destinazione.name + ".recupero")
    if staging.exists():
        raise RecuperoError("staging gia presente")
    backup = None
    try:
        _copia_sqlite(sorgente, staging)
        migra(staging)
        if not ispeziona_database(staging).integro:
            raise RecuperoError("copia migrata non integra")
        if destinazione.exists():
            suffisso = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = destinazione.with_name(destinazione.name + ".backup-" + suffisso)
            if backup.exists():
                raise RecuperoError("backup gia presente")
            _copia_sqlite(destinazione, backup)
        if destinazione.exists():
            _copia_sqlite(staging, destinazione)
            staging.unlink()
        else:
            os.replace(staging, destinazione)
        return backup
    finally:
        if staging.exists():
            staging.unlink()
```

- [ ] **Step 4: Rendere `trasloco` non distruttivo**

Il vecchio `trasloca_se_serve` non deve più rinominare l'origine. Quando viene invocato
esplicitamente, delega alla copia conservativa e lascia intatti `starkeno.db` e gli
eventuali sidecar. `hook_ingestione.main` smette di chiamarlo automaticamente: il test
`test_main_fa_il_trasloco_prima_di_ingerire` viene sostituito da un test che installa
una spia sollevante e dimostra che `main()` non la chiama. Il recupero di copie
`.trasferito` passa soltanto da `doctor --repair-from ... --confirm-repair`.

- [ ] **Step 5: Verificare recupero e migrazioni**

Run: `python -m pytest -q tests/test_recupero.py tests/test_trasloco.py tests/test_hook.py tests/test_migrations.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add -- starkeno/recupero.py starkeno/trasloco.py starkeno/hook_ingestione.py tests/test_recupero.py tests/test_trasloco.py tests/test_hook.py
git commit -m "feat: recupera lo storico senza sovrascrivere"
```

### Task 5: Creare CLI e pacchetto wheel/sdist

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Modify: `starkeno/__init__.py`
- Create: `starkeno/cli.py`
- Create: `starkeno/__main__.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_packaging.py`
- Modify: `.codex-plugin/plugin.json`
- Modify: `tests/test_plugin_codex.py`

**Interfaces:**
- Produces: `starkeno.cli.main(argv: Sequence[str] | None = None) -> int`.
- CLI: `starkeno doctor [--json] [--repair-from PATH --confirm-repair]`.
- CLI: `starkeno report [--output PATH] [--no-open]`.
- Versione unica: `starkeno.__version__ == 0.3.0`, letta dinamicamente da Hatchling.

- [ ] **Step 1: Scrivere test rossi per CLI, versione e build metadata**

```python
def test_module_cli_delegates_report(tmp_path, monkeypatch):
    visti = {}
    def report_finto(args):
        visti["args"] = args
        return 0
    monkeypatch.setattr("starkeno.cli.report_conto.main", report_finto)
    assert main(["report", "--output", str(tmp_path / "conto.html"), "--no-open"]) == 0
    assert visti["args"][-1] == "--no-open"


def test_repair_requires_the_explicit_confirmation(tmp_path):
    with pytest.raises(SystemExit) as errore:
        main(["doctor", "--repair-from", str(tmp_path / "storico.db")])
    assert errore.value.code == 2


def test_manifest_version_matches_python_package():
    manifest = json.loads(Path(".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    assert manifest["version"] == starkeno.__version__
```

`tests/test_packaging.py` deve eseguire `python -m build --wheel --sdist --outdir <tmp>`,
aprire gli archivi e asserire la presenza di `starkeno/static/index.html`,
`migrations/env.py`, `migrations/versions/0005_ingestione.py`,
`starkeno/plugin_bundle/.codex-plugin/plugin.json` e
`starkeno/plugin_bundle/hooks/hooks.json`.

- [ ] **Step 2: Verificare il rosso**

Run: `python -m pytest -q tests/test_cli.py tests/test_packaging.py tests/test_plugin_codex.py`

Expected: FAIL perché CLI e metadata di build non esistono.

- [ ] **Step 3: Dichiarare il pacchetto in `pyproject.toml`**

Usare questa struttura, mantenendo `[tool.pytest.ini_options]`:

```toml
[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[project]
name = "starkeno"
dynamic = ["version"]
description = "Local observability for coding-agent workflows"
readme = "README.md"
requires-python = ">=3.12,<3.15"
license = { file = "LICENSE" }
authors = [{ name = "Simone Mansella" }]
dependencies = [
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "mcp[cli]>=2,<3",
  "sqlalchemy>=2,<3",
  "alembic>=1.13,<2",
  "httpx>=0.27,<1",
]

[project.optional-dependencies]
dev = ["pytest>=8,<10", "build>=1.2,<2", "pip-audit>=2.9,<3"]

[project.scripts]
starkeno = "starkeno.cli:main"

[tool.hatch.version]
path = "starkeno/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["starkeno", "migrations"]

[tool.hatch.build.targets.wheel.force-include]
".codex-plugin" = "starkeno/plugin_bundle/.codex-plugin"
"hooks" = "starkeno/plugin_bundle/hooks"
```

`starkeno/__init__.py` contiene soltanto `__version__ = "0.3.0"`.
`requirements.txt` contiene `-e .[dev]`, così il pyproject resta l'autorità.

- [ ] **Step 4: Implementare parser e output doctor**

`doctor --json` serializza ogni `Controllo` con `asdict`; senza `--json` stampa una riga
`[OK|ATTENZIONE|ERRORE|MANUALE] codice: dettaglio`. Il codice di uscita è 1 se esiste
un controllo `errore`, altrimenti 0. La riparazione chiama `recupera_database`, poi
riesegue la diagnosi. `report` passa gli argomenti residui a `report_conto.main`.

- [ ] **Step 5: Verificare build, CLI e installazione da directory estranea**

Run: `python -m pytest -q tests/test_cli.py tests/test_packaging.py tests/test_plugin_codex.py`

Expected: PASS.

Run: `python -m build`

Expected: wheel e sdist in `dist/`.

Creare un virtualenv temporaneo fuori dal repository, installare il wheel e lanciare:

```powershell
starkeno doctor --json
starkeno report --output conto.html --no-open
python -m starkeno doctor --json
```

Expected: i comandi partono; doctor può uscire 1 perché il database isolato manca, ma
produce JSON valido; report crea `conto.html` senza creare il database.

- [ ] **Step 6: Commit**

```powershell
git add -- pyproject.toml requirements.txt starkeno/__init__.py starkeno/cli.py starkeno/__main__.py .codex-plugin/plugin.json tests/test_cli.py tests/test_packaging.py tests/test_plugin_codex.py
git commit -m "feat: distribuisce StarkEno come pacchetto Python"
```

### Task 6: Aggiungere il marketplace locale e provare Codex dal vivo

**Files:**
- Create: `.agents/plugins/marketplace.json`
- Modify: `tests/test_plugin_codex.py`
- Modify: `README.md`
- Create: `docs/verification/2026-08-12-codex-live.md`

**Interfaces:**
- Consumes: layout marketplace ufficiale Codex e plugin root corrente.
- Produces: plugin `starkeno` disponibile nel browser `/plugins` come sorgente locale.

- [ ] **Step 1: Scrivere il test rosso del marketplace**

```python
def test_repo_marketplace_exposes_the_root_plugin():
    catalogo = json.loads((RADICE / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    voce = catalogo["plugins"][0]
    assert catalogo["name"] == "starkeno-local"
    assert voce["name"] == "starkeno"
    assert voce["source"] == {"source": "local", "path": "./"}
    assert voce["policy"] == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}
    assert voce["category"] == "Productivity"
    assert (RADICE / voce["source"]["path"] / ".codex-plugin/plugin.json").is_file()
```

- [ ] **Step 2: Verificare il rosso**

Run: `python -m pytest -q tests/test_plugin_codex.py`

Expected: FAIL perché il marketplace non esiste.

- [ ] **Step 3: Creare il catalogo locale**

```json
{
  "name": "starkeno-local",
  "interface": { "displayName": "StarkEno Local" },
  "plugins": [
    {
      "name": "starkeno",
      "source": { "source": "local", "path": "./" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Productivity"
    }
  ]
}
```

- [ ] **Step 4: Documentare e svolgere l'attivazione manuale**

README deve dire esattamente:

1. riavvia ChatGPT/Codex desktop perché il marketplace repo viene letto all'avvio;
2. apri `/plugins`, scegli `StarkEno Local` e installa `starkeno`;
3. avvia una nuova sessione;
4. apri `/hooks`, revisiona e approva `SessionStart` e `Stop`;
5. completa tre turni normali;
6. esegui `starkeno doctor` e verifica database a `0005`, raccolta recente e plugin trovato.

Non modificare `~/.codex/config.toml` a mano. Se l'app non espone il marketplace, usare
il comando ufficiale `codex plugin marketplace add .` soltanto dopo aver risolto
l'`Accesso negato` del binario locale.

- [ ] **Step 5: Registrare evidenza senza percorsi personali**

`docs/verification/2026-08-12-codex-live.md` deve contenere versione plugin, revisione
schema, conteggio prima/dopo tre turni, numero duplicati, exit code doctor e risultato
`quick_check`; non deve contenere transcript, prompt, username o path assoluti.

- [ ] **Step 6: Verificare e commit**

Run: `python -m pytest -q tests/test_plugin_codex.py tests/test_hook.py tests/test_hook_inizio_sessione.py tests/test_diagnostica.py`

Expected: PASS.

```powershell
git add -- .agents/plugins/marketplace.json README.md docs/verification/2026-08-12-codex-live.md tests/test_plugin_codex.py
git commit -m "feat: rende installabile il plugin Codex locale"
```

### Task 7: Governare dipendenze, audit e scansione segreti

**Files:**
- Create: `requirements/ci.txt`
- Modify: `pyproject.toml`
- Create: `scripts/verifica_segreti.py`
- Create: `tests/test_verifica_segreti.py`
- Create: `.github/dependabot.yml`

**Interfaces:**
- Produces: `scansiona(paths: Iterable[Path]) -> tuple[RilievoSegreto, ...]`.
- Produce output soltanto `percorso:tipo`, mai il valore corrispondente.
- Constraints generati direttamente da `pyproject.toml` e installabili con
  `pip install -c requirements/ci.txt -e .[dev]`.

- [ ] **Step 1: Scrivere test rossi della scansione redatta**

```python
def test_secret_scanner_reports_type_without_leaking_value(tmp_path, capsys):
    segreto = "sk-" + "A" * 40
    file = tmp_path / "leak.txt"
    file.write_text(segreto, encoding="utf-8")
    rilievi = scansiona([file])
    assert [(r.percorso, r.tipo) for r in rilievi] == [(file, "openai_key")]
    assert segreto not in repr(rilievi)


def test_sanitized_fixture_is_clean():
    assert scansiona([Path("tests/fixtures/transcript_vero.jsonl")]) == ()
```

- [ ] **Step 2: Verificare il rosso**

Run: `python -m pytest -q tests/test_verifica_segreti.py`

Expected: FAIL perché lo script non esiste.

- [ ] **Step 3: Implementare pattern e CLI della scansione**

Usare pattern compilati per chiavi OpenAI `sk-`, token GitHub `gh[pousr]_`, blocchi
`PRIVATE KEY` e bearer token lunghi. `main` riceve file da argv, stampa solo tipo e path,
e ritorna 1 se trova rilievi.

- [ ] **Step 4: Bloccare e verificare le dipendenze CI**

Il `pyproject.toml` resta l'unica sorgente. Aggiungere `pip-tools>=7.4,<8` all'extra
`dev` e generare `requirements/ci.txt` direttamente da esso:

```powershell
python -m pip install "pip-tools>=7.4,<8"
python -m piptools compile pyproject.toml --extra dev --output-file requirements/ci.txt --strip-extras
```

Aggiungere `pip-tools>=7.4,<8` all'extra `dev`. Verificare:

```powershell
python -m pip install -c requirements/ci.txt -e .[dev]
python -m pip check
python -m pip_audit -r requirements/ci.txt
```

Expected: nessun requirement rotto e nessuna vulnerabilità non documentata secondo P6.

- [ ] **Step 5: Configurare aggiornamenti automatici**

`.github/dependabot.yml` abilita `pip` e `github-actions` settimanalmente, limite 5 PR
aperte e target branch `main`.

- [ ] **Step 6: Verificare e commit**

Run: `python -m pytest -q tests/test_verifica_segreti.py`

Run: `python scripts/verifica_segreti.py --tracked`

Expected: PASS e uscita 0.

```powershell
git add -- pyproject.toml requirements/ci.txt scripts/verifica_segreti.py tests/test_verifica_segreti.py .github/dependabot.yml
git commit -m "build: governa dipendenze e segreti"
```

### Task 8: Creare la matrice CI multipiattaforma

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/stress.yml`
- Create: `tests/test_workflows.py`

**Interfaces:**
- Produces job stabili: `tests`, `package`, `audit`, `stress`.
- Consumes: extra dev, constraints, scanner, wheel smoke e stress script.

- [ ] **Step 1: Scrivere test rossi sui job obbligatori**

```python
def test_ci_covers_supported_os_and_python_versions():
    ci = yaml.safe_load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
    matrice = ci["jobs"]["tests"]["strategy"]["matrix"]
    assert set(matrice["os"]) == {"ubuntu-latest", "windows-latest", "macos-latest"}
    assert set(map(str, matrice["python"])) == {"3.12", "3.13", "3.14"}
    comando = "\n".join(step.get("run", "") for step in ci["jobs"]["tests"]["steps"])
    assert "pytest -q -W error" in comando


def test_stress_runs_on_windows_and_linux():
    workflow = yaml.safe_load(Path(".github/workflows/stress.yml").read_text(encoding="utf-8"))
    assert set(workflow["jobs"]["stress"]["strategy"]["matrix"]["os"]) == {
        "ubuntu-latest", "windows-latest"
    }
```

Aggiungere `PyYAML>=6,<7` all'extra dev e rigenerare constraints.

- [ ] **Step 2: Verificare il rosso**

Run: `python -m pytest -q tests/test_workflows.py`

Expected: FAIL perché i workflow non esistono.

- [ ] **Step 3: Creare `ci.yml`**

Il job `tests` usa `actions/checkout`, `actions/setup-python`, cache pip, installazione
con constraints e `python -m pytest -q -W error`. Il job `package` costruisce wheel e
sdist, installa il wheel in un venv temporaneo e lancia da una directory estranea
`starkeno doctor --json` e `starkeno report --no-open`. Il job `audit` esegue `pip check`,
`pip-audit`, scanner segreti e controllo che `pip-compile` non modifichi constraints.

- [ ] **Step 4: Creare `stress.yml`**

Eseguire su `workflow_dispatch`, push a `main` e settimanalmente:

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest]
steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-python@v5
    with: { python-version: "3.12", cache: "pip" }
  - run: python -m pip install -c requirements/ci.txt -e ".[dev]"
  - run: python scripts/stress_concorrenza.py
```

- [ ] **Step 5: Verificare sintassi e test locali**

Run: `python -m pytest -q tests/test_workflows.py`

Run: `python -m pytest -q -W error`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add -- pyproject.toml requirements/ci.txt .github/workflows/ci.yml .github/workflows/stress.yml tests/test_workflows.py
git commit -m "ci: verifica tre sistemi e tre versioni Python"
```

### Task 9: Rendere dashboard e report completamente offline

**Files:**
- Create: `starkeno/static/style.css`
- Modify: `starkeno/static/index.html`
- Modify: `tests/test_dashboard_smoke.py`
- Modify: `tests/test_report_conto.py`

**Interfaces:**
- Produce: dashboard servita da FastAPI senza URL remoti.
- Preserva: endpoint, polling, dismiss, mute, badge e stato supervisore esistenti.

- [ ] **Step 1: Scrivere test rossi contro dipendenze remote**

```python
def test_dashboard_and_report_have_no_remote_assets(session_factory, tmp_path):
    dashboard = (Path("starkeno/static/index.html").read_text(encoding="utf-8") +
                 Path("starkeno/static/style.css").read_text(encoding="utf-8"))
    assert "http://" not in dashboard and "https://" not in dashboard
    assert "cdn.tailwindcss.com" not in dashboard

    output = tmp_path / "conto.html"
    genera_report(tmp_path / "assente.db", output, fuso=timezone.utc, now=ORA)
    html = output.read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
```

- [ ] **Step 2: Verificare il rosso**

Run: `python -m pytest -q tests/test_dashboard_smoke.py tests/test_report_conto.py`

Expected: FAIL per la CDN Tailwind e per `style.css` assente.

- [ ] **Step 3: Sostituire Tailwind con CSS locale**

Rimuovere `<script src="https://cdn.tailwindcss.com"></script>`, aggiungere
`<link rel="stylesheet" href="/style.css">` e definire in `style.css` almeno body,
heading, table, border, button, badge, colori di stato, spaziature e font monospace.
Lasciare invariati id DOM e funzioni JavaScript.

- [ ] **Step 4: Verificare pagina, API e report**

Run: `python -m pytest -q tests/test_dashboard_smoke.py tests/test_api.py tests/test_api_alerts.py tests/test_report_conto.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- starkeno/static/index.html starkeno/static/style.css tests/test_dashboard_smoke.py tests/test_report_conto.py
git commit -m "fix: rende l'interfaccia completamente locale"
```

### Task 10: Sanificare istruzioni, documenti e fixture pubbliche

**Files:**
- Replace: `AGENTS.md`
- Replace: `CLAUDE.md`
- Modify: `docs/superpowers/plans/2026-08-04-agent-tracker-v0.md`
- Modify: `docs/superpowers/plans/2026-08-06-supervisor-v1.md`
- Modify: `docs/superpowers/plans/2026-08-07-fase1-i-dati-entrano.md`
- Modify: `docs/superpowers/specs/2026-08-05-supervisor-agent-design.md`
- Create: `scripts/verifica_pubblicazione.py`
- Create: `tests/test_pubblicazione.py`

**Interfaces:**
- Produces: `scansiona_pubblico(paths: Iterable[Path]) -> tuple[RilievoPubblico, ...]`.
- Vietati: path home letterali, riferimenti ad archivi personali e firme segrete.
- Ammessi: `%USERPROFILE%`, `$HOME`, `<utente>` e percorsi relativi.

- [ ] **Step 1: Scrivere il test rosso della privacy**

```python
def test_every_tracked_text_file_is_public_safe():
    paths = tracked_text_files(Path.cwd())
    rilievi = scansiona_pubblico(paths)
    assert rilievi == (), "\n".join(f"{r.percorso}:{r.tipo}" for r in rilievi)


def test_scanner_flags_a_literal_home_without_printing_the_username(tmp_path):
    file = tmp_path / "doc.md"
    file.write_text("C:" + "\\\\" + "Users" + "\\\\" + "nome-reale", encoding="utf-8")
    rilievi = scansiona_pubblico([file])
    assert [r.tipo for r in rilievi] == ["windows_home_letterale"]
    assert "nome-reale" not in repr(rilievi)
```

- [ ] **Step 2: Verificare il rosso sul repository corrente**

Run: `python -m pytest -q tests/test_pubblicazione.py`

Expected: FAIL elencando soltanto file e tipi, inclusi AGENTS, CLAUDE e piani storici.

- [ ] **Step 3: Sostituire le istruzioni private con istruzioni pubbliche**

Il nuovo `AGENTS.md` contiene: scopo del prodotto, stato Fase 2/Fase 0, comandi di test,
invarianti tecnici 1–13 in forma concisa, regola database fuori dal repo, autorità
Alembic e divieto di dati personali. Non contiene note private, database dell'autore, conteggi
privati o path assoluti.

Il nuovo `CLAUDE.md` contiene lo stesso contratto essenziale e indica che la
documentazione autoritativa di progetto è `AGENTS.md`; non descrive payload Codex come
se fossero Claude Code.

- [ ] **Step 4: Generalizzare i documenti storici**

Applicare sostituzioni esplicite:

- un percorso home Windows letterale → `%USERPROFILE%`;
- un percorso MSYS letterale → `$HOME`;
- un percorso Windows con slash letterali → `%USERPROFILE%`;
- vecchie radici assolute del progetto → `<radice-progetto>`;
- path di note personali → rimuovere la frase, non sostituirla con un altro path.

Conservare misure tecniche e razionali che non identificano l'autore.

- [ ] **Step 5: Implementare scanner pubblico redatto**

`scripts/verifica_pubblicazione.py` usa `git ls-files -z`, ignora binari, riusa
`verifica_segreti.scansiona` e aggiunge pattern privacy. Se la radice non contiene una
directory `.git`, come nello snapshot pubblico, `tracked_text_files` usa `rglob` ed
esclude soltanto directory di build/cache (`dist`, `build`, `.venv`, `__pycache__`).
`RilievoPubblico.__repr__` contiene soltanto `percorso` e `tipo`.

- [ ] **Step 6: Verificare e commit**

Run: `python -m pytest -q tests/test_pubblicazione.py tests/test_verifica_segreti.py`

Run: `python scripts/verifica_pubblicazione.py`

Expected: PASS e nessun valore sensibile stampato.

```powershell
git add -- AGENTS.md CLAUDE.md docs/superpowers/plans/2026-08-04-agent-tracker-v0.md docs/superpowers/plans/2026-08-06-supervisor-v1.md docs/superpowers/plans/2026-08-07-fase1-i-dati-entrano.md docs/superpowers/specs/2026-08-05-supervisor-agent-design.md scripts/verifica_pubblicazione.py tests/test_pubblicazione.py
git commit -m "docs: rimuove contesto personale dallo snapshot pubblico"
```

### Task 11: Aggiungere documenti comunitari e snapshot senza storia privata

**Files:**
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `CHANGELOG.md`
- Create: `.gitattributes`
- Create: `.github/ISSUE_TEMPLATE/bug.yml`
- Create: `.github/ISSUE_TEMPLATE/feature.yml`
- Create: `.github/pull_request_template.md`
- Create: `docs/releasing.md`
- Create: `scripts/costruisci_snapshot_pubblico.py`
- Create: `tests/test_open_source_files.py`
- Create: `tests/test_snapshot_pubblico.py`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Produces: `costruisci_snapshot(destinazione: Path, *, revisione: str = "HEAD") -> Path`.
- La destinazione deve non esistere o essere vuota; non contiene `.git` né file ignorati.
- Il comando non inizializza repository e non effettua rete o push.

- [ ] **Step 1: Scrivere test rossi per documenti e snapshot**

```python
@pytest.mark.parametrize("path", [
    "SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md",
    ".gitattributes", ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml", ".github/pull_request_template.md",
    "docs/releasing.md",
])
def test_required_open_source_file_exists(path):
    assert Path(path).is_file()


def test_public_snapshot_contains_head_without_private_history(tmp_path):
    destinazione = costruisci_snapshot(tmp_path / "pubblico")
    assert (destinazione / "pyproject.toml").is_file()
    assert not (destinazione / ".git").exists()
    assert not (destinazione / "starkeno.db").exists()
    assert scansiona_pubblico(tracked_text_files(destinazione)) == ()
```

Aggiungere test che una destinazione non vuota viene rifiutata senza cancellare file.

- [ ] **Step 2: Verificare il rosso**

Run: `python -m pytest -q tests/test_open_source_files.py tests/test_snapshot_pubblico.py`

Expected: FAIL per file e modulo snapshot assenti.

- [ ] **Step 3: Scrivere documentazione comunitaria concreta**

- `SECURITY.md`: versioni supportate 0.3.x, segnalazione tramite GitHub
  **Security → Report a vulnerability**, dati da non allegare mai e SLA best-effort
  esplicitamente non garantito. Prima che quel canale esista non viene distribuita una
  release pubblica.
- `CONTRIBUTING.md`: setup `pip install -e .[dev]`, TDD, suite strict, migrazioni,
  fixture sanificate, commit piccoli.
- `CODE_OF_CONDUCT.md`: Contributor Covenant 2.1 con contatto rinviato al canale Security.
- `CHANGELOG.md`: Keep a Changelog, sezione Unreleased e 0.2.0/Fase 2.
- `docs/releasing.md`: build, audit, snapshot, installazione wheel, CI, tag; nessun comando push automatico.
- Issue form bug: OS, Python, versione StarkEno, output redatto di doctor, divieto transcript.
- PR template: test red/green, privacy, migrazioni, changelog.

- [ ] **Step 4: Implementare snapshot tramite `git archive`**

```python
def costruisci_snapshot(destinazione: Path, *, revisione="HEAD"):
    destinazione = Path(destinazione)
    if destinazione.exists() and any(destinazione.iterdir()):
        raise ValueError("la destinazione non e vuota")
    destinazione.mkdir(parents=True, exist_ok=True)
    archivio = subprocess.run(
        ["git", "archive", "--format=tar", revisione],
        check=True, capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archivio), mode="r:") as tar:
        tar.extractall(destinazione, filter="data")
    return destinazione
```

La CLI dello script accetta un solo path di output e termina nonzero sui conflitti.

- [ ] **Step 5: Verificare snapshot, build e installazione**

Run: `python -m pytest -q tests/test_open_source_files.py tests/test_snapshot_pubblico.py`

Creare uno snapshot temporaneo, poi dalla sua radice:

```powershell
python scripts/verifica_pubblicazione.py
python -m build
python -m pytest -q -W error
```

Expected: PASS; nessuna `.git`, database, log o configurazione locale nell'export.

- [ ] **Step 6: Commit**

```powershell
git add -- SECURITY.md CONTRIBUTING.md CODE_OF_CONDUCT.md CHANGELOG.md .gitattributes .gitignore .github/ISSUE_TEMPLATE/bug.yml .github/ISSUE_TEMPLATE/feature.yml .github/pull_request_template.md docs/releasing.md README.md scripts/costruisci_snapshot_pubblico.py tests/test_open_source_files.py tests/test_snapshot_pubblico.py
git commit -m "docs: prepara lo snapshot open source"
```

### Task 12: Recupero reale, verifica finale e gate GitHub

**Files:**
- Modify: `docs/verification/2026-08-12-codex-live.md`
- Create: `docs/verification/2026-08-12-fase0.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: CLI installata, doctor, recupero, marketplace, CI, scanner e snapshot.
- Produces: evidenza P1–P7 priva di dati personali e un worktree pulito.

- [ ] **Step 1: Rieseguire la baseline prima di toccare dati reali**

Run:

```powershell
python -m pytest -q
python -m pytest -q -W error
python scripts/stress_concorrenza.py
python -m build
python -m pip check
python -m pip_audit -r requirements/ci.txt
python scripts/verifica_pubblicazione.py
git diff --check
```

Expected: tutti verdi; stress 900/900 e integrità `ok`.

- [ ] **Step 2: Inventariare lo storico reale senza modificarlo**

Run: `starkeno doctor --json`

Expected: il rapporto elenca canonico assente e `starkeno.db.trasferito` come candidato
integro schema `0003`, oppure dati più aggiornati se nel frattempo sono comparsi. Non
procedere se esistono due candidati validi con storie divergenti: mostrare conteggi e
chiedere all'utente quale recuperare.

- [ ] **Step 3: Eseguire il recupero esplicito autorizzato dalla spec**

Solo se il candidato non è ambiguo:

```powershell
starkeno doctor --repair-from .\starkeno.db.trasferito --confirm-repair
```

Expected: origine intatta, canonico a `0005`, `quick_check=ok`, righe preservate. Se
nessuno storico recuperabile esiste, creare il database canonico con `upgrade_head` e
registrare esplicitamente `nessuno storico recuperabile`, non `recuperato`.

- [ ] **Step 4: Completare la prova Codex live**

Seguire Task 6, quindi verificare:

```powershell
starkeno doctor
```

Expected: plugin trovato, schema a head, raccolta recente, conteggio cresciuto, zero
duplicati su `(session_id, message_id)`.

- [ ] **Step 5: Creare e provare lo snapshot pubblico senza pubblicarlo**

Run:

```powershell
$snapshotRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('starkeno-public-' + [guid]::NewGuid().ToString('N'))
python scripts/costruisci_snapshot_pubblico.py $snapshotRoot
```

Dentro lo snapshot eseguire scanner, build, suite strict e wheel smoke. Eliminare lo
snapshot temporaneo soltanto dopo aver verificato che il path risolto è sotto la temp di
sistema e non è una radice ampia.

- [ ] **Step 6: Registrare evidenza P1–P7**

`docs/verification/2026-08-12-fase0.md` contiene una tabella P1–P7 con comando, exit
code, risultato, commit che ha chiuso il problema ed eventuale azione manuale. Nessun
path assoluto, username, transcript o segreto.

- [ ] **Step 7: Richiedere conferma per il repository GitHub**

Fermarsi prima di creare remote, repository, branch protection o push. Presentare:

- path dello snapshot pulito;
- hash della commit privata verificata;
- risultati locali;
- nomi dei job obbligatori `tests`, `package`, `audit`, `stress`;
- scelta richiesta di owner/nome/visibilità del nuovo repository.

Dopo conferma esplicita, creare una nuova storia dal solo snapshot, collegare il remote,
eseguire la matrice e configurare gli status check. Se la matrice remota non è verde,
P5 e la Fase 0 restano aperti.

- [ ] **Step 8: Commit di verifica**

```powershell
git add -- CHANGELOG.md docs/verification/2026-08-12-codex-live.md docs/verification/2026-08-12-fase0.md
git commit -m "docs: verifica la stabilizzazione open source"
```

- [ ] **Step 9: Controllo finale del ramo privato**

Run: `git status --short`

Expected: output vuoto.

Run: `git log --oneline d05c267..HEAD`

Expected: un commit autonomo per ogni task completato, più plan e verifica.
