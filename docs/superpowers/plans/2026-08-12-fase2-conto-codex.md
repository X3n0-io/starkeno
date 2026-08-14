# Fase 2 — Il conto Codex Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generare un conto HTML locale su richiesta e una riga di benvenuto/informazione all'avvio di una sessione Codex, usando lo storico già raccolto.

**Architecture:** `db.py` legge snapshot immutabili ed è l'unico modulo con SQLAlchemy. `conto.py` trasforma gli snapshot in un modello puro e deterministico. `report_conto.py` scrive HTML, senza FastAPI. `hook_inizio_sessione.py` restituisce solo il JSON di contesto previsto da Codex. Il vecchio supervisore e le sue soglie restano separati.

**Tech Stack:** Python 3.12, SQLite/SQLAlchemy esistenti, HTML statico, hook Codex JSON.

## Global Constraints

- L'utente ha autorizzato il lavoro sul ramo `main`; non creare worktree o branch.
- `starkeno/db.py` resta l'unico modulo che importa SQLAlchemy.
- `starkeno/conto.py` non importa database, filesystem, browser o orologio di sistema.
- I datetime restano aware-UTC fino a `db.UTCDateTime`; il conto converte solo con `astimezone(fuso)`.
- La pagina è un file HTML scritto su richiesta: non modificare `api.py`, non aprire porte e non avviare processi persistenti.
- Progetto, modello e sessione sono partizioni. Skill, plugin, server MCP e sub-agente sono etichette sovrapposte; non devono mai essere sommate come una partizione.
- Il costo attribuito a etichette usa la base marginale: lavoro = input + output; caricamento = cache write; cache read resta rilettura separata.
- Componenti mancanti, negativi, incoerenti o implausibili sono esplicitamente non classificabili e non diventano zero.
- Non implementare soglie S2–S5, autotaratura, listino o tetto configurabile: mancano decisioni misurate.
- Ogni hook esce 0 e non scrive su stderr anche in caso di errore; `Stop` resta asincrono, `SessionStart` è sincrono.
- I test non toccano `config.DB_PATH` di produzione: usano `tmp_path`, session factory o un percorso passato esplicitamente.

---

### Task 1: Snapshot e modello puro del conto

**Files:**

- Create: `starkeno/conto.py`
- Modify: `starkeno/db.py`
- Create: `tests/test_conto.py`

**Interfaces:**

- Produce `AzioneConto`, dataclass frozen con: `project`, `session_id`, `model_used`, `timestamp`, `tokens_used`, `cache_read_tokens`, `cache_write_tokens`, `output_tokens`, `azioni_nella_chiamata`, `skill`, `plugin`, `mcp_server`, `is_sidechain`, `esito_noto`.
- Produce `Conto` e `calcola_conto(azioni, *, fuso, now, weights, max_plausible) -> Conto`.
- Produce `db.get_azioni_conto(session) -> list[AzioneConto]` e `db.conta_chiamate(session) -> int`.

- [x] **Step 1: Write the failing tests**

```python
def test_partizioni_quadrano_mentre_etichette_si_sovrappongono():
    conto = calcola_conto(
        [azione(skill="analisi", plugin="p", mcp_server="m"),
         azione(skill="analisi", is_sidechain=1)],
        fuso=timezone.utc, now=ORA, weights=PESI, max_plausible=2_000_000,
    )

    assert conto.azioni == sum(voce.azioni for voce in conto.per_progetto)
    assert conto.chiamate == sum(voce.chiamate for voce in conto.per_modello)
    assert conto.per_skill[0].chiamate == 2
    assert conto.per_plugin[0].chiamate == 1


def test_marginale_esclude_cache_read_e_separa_lavoro_da_caricamento():
    conto = calcola_conto(
        [azione(tokens_used=1700, cache_read_tokens=1000,
                cache_write_tokens=200, output_tokens=100)],
        fuso=timezone.utc, now=ORA, weights=PESI, max_plausible=2_000_000,
    )

    assert conto.riletture_pesate == 100
    assert conto.caricamento_pesato == 250
    assert conto.lavoro_pesato == 600
    assert conto.marginale_pesato == 850
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_conto.py -q`

Expected: FAIL during collection because `starkeno.conto` does not exist.

- [x] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class AzioneConto:
    project: str
    session_id: str
    model_used: str
    timestamp: datetime
    tokens_used: int
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    azioni_nella_chiamata: int
    skill: str
    plugin: str
    mcp_server: str
    is_sidechain: int
    esito_noto: int


def calcola_conto(azioni, *, fuso, now, weights, max_plausible):
    # Calcola totale, lavoro, caricamento, riletture, esiti ignoti,
    # righe non classificabili, partizioni, etichette e ritmo locale a 7 giorni.
    ...
```

Non lasciare `...` nel codice: per ogni riga valida applicare la stessa semantica di
`rules.effective_tokens`. Per una scomposizione completa e valida, usare input =
`tokens_used - cache_read - cache_write - output`; pesare separatamente i tre gruppi.
Per le righe non classificabili usare il totale solo come totale osservato, mai come
attribuzione marginale. In `db.py`, convertire oggetti `AgentAction` in
`AzioneConto` mantenendo timestamp aware-UTC.

- [x] **Step 4: Run tests to verify it passes**

Run: `python -m pytest tests/test_conto.py tests/test_db_supervisor.py -q`

Expected: PASS; i test differenziali SQL/Python esistenti restano verdi.

- [x] **Step 5: Commit**

```bash
git add starkeno/conto.py starkeno/db.py tests/test_conto.py
git commit -m "feat: aggiunge il modello puro del conto"
```

### Task 2: Report HTML statico

**Files:**

- Create: `starkeno/report_conto.py`
- Create: `tests/test_report_conto.py`

**Interfaces:**

- Consume `db.get_azioni_conto`, `calcola_conto`, `TOKEN_COST_WEIGHTS`, `MAX_PLAUSIBLE_TOKENS`.
- Produce `renderizza_html(conto) -> str`, `genera_report(percorso_db, percorso_output, *, fuso, now) -> Path`, `apri_report(path) -> None`.
- Esporre `python -m starkeno.report_conto [--output PATH] [--no-open]`.

- [x] **Step 1: Write the failing tests**

```python
def test_genera_html_statico_contenuto_escapato(tmp_path, session_factory):
    scrivi_azione(session_factory(), project="<script>alert(1)</script>")
    destinazione = tmp_path / "conto.html"

    generato = genera_report(
        str(percorso_db(session_factory)), destinazione,
        fuso=timezone.utc, now=ORA,
    )
    html = generato.read_text(encoding="utf-8")

    assert generato == destinazione
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "azioni in" in html
    assert "etichette si sovrappongono" in html
    assert "StarkEno misura quello che spendi, non quello che ottieni" in html
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_conto.py -q`

Expected: FAIL during collection because `starkeno.report_conto` does not exist.

- [x] **Step 3: Write minimal implementation**

```python
def genera_report(percorso_db: str, percorso_output: Path, *, fuso, now: datetime) -> Path:
    azioni = () if not Path(percorso_db).exists() else _leggi_azioni(percorso_db)
    conto = calcola_conto(azioni, fuso=fuso, now=now,
                           weights=TOKEN_COST_WEIGHTS,
                           max_plausible=MAX_PLAUSIBLE_TOKENS)
    percorso_output.parent.mkdir(parents=True, exist_ok=True)
    percorso_output.write_text(renderizza_html(conto), encoding="utf-8")
    return percorso_output
```

Il renderer deve applicare `html.escape` a ogni valore dal database e contenere:
`N azioni in M chiamate`, costo di lavoro/caricamento/rilettura separati, esiti ignoti,
partizioni, ritmo locale, etichette sovrapposte, tetto non configurato e nota di onestà.
Con database assente il report deve essere vuoto ma leggibile e non deve creare schema.

- [x] **Step 4: Run tests to verify it passes**

Run: `python -m pytest tests/test_conto.py tests/test_report_conto.py -q`

Run: `python -m starkeno.report_conto --output "$env:TEMP\starkeno-conto-test.html" --no-open`

Expected: PASS; il secondo comando crea un HTML locale e non apre il browser.

- [x] **Step 5: Commit**

```bash
git add starkeno/report_conto.py tests/test_report_conto.py
git commit -m "feat: genera il conto statico su richiesta"
```

### Task 3: Plugin Codex e hook SessionStart

**Files:**

- Delete: `.claude-plugin/plugin.json`
- Create: `.codex-plugin/plugin.json`
- Modify: `hooks/hooks.json`
- Create: `starkeno/hook_inizio_sessione.py`
- Create: `tests/test_hook_inizio_sessione.py`
- Create: `tests/test_plugin_codex.py`
- Modify: `README.md`

**Interfaces:**

- Consume `db.conta_chiamate` e payload Codex `SessionStart`.
- Produrre JSON stdout con `hookSpecificOutput.hookEventName == "SessionStart"` e `additionalContext`.
- Il manifest Codex deve puntare a `./hooks/hooks.json`; gli hook devono usare `PLUGIN_ROOT` e `commandWindows`.

- [x] **Step 1: Write the failing tests**

```python
def test_primo_avvio_restituisce_contesto_codex_senza_stderr(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "manca.db"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "hook_event_name": "SessionStart", "source": "startup"})))

    assert main() == 0
    uscita, errore = capsys.readouterr()
    risposta = json.loads(uscita)
    assert risposta["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "StarkEno" in risposta["hookSpecificOutput"]["additionalContext"]
    assert errore == ""


def test_manifest_codex_e_hook_puntano_a_script_esistenti():
    manifest = json.loads(Path(".codex-plugin/plugin.json").read_text())
    hooks = json.loads(Path("hooks/hooks.json").read_text())
    assert manifest["hooks"] == "./hooks/hooks.json"
    assert hooks["hooks"]["Stop"][0]["hooks"][0]["async"] is True
    assert hooks["hooks"]["SessionStart"][0]["hooks"][0]["async"] is False
    assert not Path(".claude-plugin/plugin.json").exists()
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hook_inizio_sessione.py tests/test_plugin_codex.py -q`

Expected: FAIL because the startup hook and `.codex-plugin/plugin.json` do not exist.

- [x] **Step 3: Write minimal implementation**

```python
def risposta_contesto(testo: str) -> str:
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": testo}})


def main() -> int:
    try:
        testo = esegui(json.loads(sys.stdin.read() or "{}"))
        if testo:
            print(risposta_contesto(testo))
    except BaseException:
        pass
    return 0
```

Il hook non crea database, non esegue migrazioni e non mostra i vecchi alert R1–R4.
Accetta solo `source == "startup"`: con database inesistente o senza chiamate emette un
benvenuto; con storico esistente tace fino alla Fase 3. `Stop` continua a invocare
`hook_ingestione.py` in background. Il README documenta il comando del report,
`/hooks` per il trust e il fatto che Codex può richiedere revisione dopo un cambio.

- [x] **Step 4: Run tests to verify it passes**

Run: `python -m pytest tests/test_hook.py tests/test_hook_inizio_sessione.py tests/test_plugin_codex.py -q`

Run: `python -m pytest -q`

Expected: PASS; hook e packaging Codex sono verificati senza riferimenti runtime obbligatori a Claude.

- [x] **Step 5: Commit**

```bash
git add .codex-plugin/plugin.json hooks/hooks.json starkeno/hook_inizio_sessione.py tests/test_hook_inizio_sessione.py tests/test_plugin_codex.py README.md
git rm .claude-plugin/plugin.json
git commit -m "feat: aggiunge il conto alla sessione Codex"
```

### Task 4: Verifica end-to-end

**Files:**

- Modify: `docs/superpowers/plans/2026-08-12-fase2-conto-codex.md`

- [x] **Step 1: Verify the static report with a temporary database**

```powershell
$env:STARKENO_DB_PATH = Join-Path $env:TEMP 'starkeno-fase2-verifica.db'
python -m starkeno.report_conto --output (Join-Path $env:TEMP 'starkeno-fase2-verifica.html') --no-open
Test-Path (Join-Path $env:TEMP 'starkeno-fase2-verifica.html')
```

Expected: exit `0` e `Test-Path` stampa `True` senza avviare FastAPI.

- [x] **Step 2: Run final mechanical checks**

Run: `git diff --check`

Run: `python -m pytest -q`

Run: `git status --short`

Expected: nessun errore di whitespace, suite verde e worktree pulito dopo il commit finale.

- [x] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-08-12-fase2-conto-codex.md
git commit -m "docs: registra la verifica della fase 2"
```
