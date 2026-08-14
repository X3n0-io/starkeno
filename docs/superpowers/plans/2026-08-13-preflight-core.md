# StarkEno Preflight Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Costruire il motore locale e deterministico che valida, revisiona, simula, corregge ed esporta un Blueprint agentico confermato.

**Architecture:** Il dominio è composto da modelli Pydantic immutabili e moduli puri per lint, simulazione e patch. Un service orchestra il core senza database; una CLI separa esplicitamente `draft` da `analyze --confirmed`, impedendo la simulazione prima della conferma. Questo piano non invoca ancora un LLM: accetta Blueprint JSON/YAML sintetici e costituisce la base verificabile per compilatore e sito pubblico.

**Tech Stack:** Python 3.12–3.14, Pydantic 2, PyYAML safe loader/dumper, pytest, HTML statico.

**Spec:** `docs/superpowers/specs/2026-08-13-preflight-simulator-design.md`

## Global Constraints

- Lavorare sul ramo `main` esistente e preservare modifiche non correlate.
- Usare TDD: test rosso osservato, implementazione minima, test pertinente, suite strict e `git diff --check`.
- Nessun modulo Preflight puro legge filesystem, ambiente, rete, database od orologio.
- `starkeno/db.py` resta l'unico modulo che importa SQLAlchemy; Preflight non crea tabelle.
- Non riusare `TOKEN_COST_WEIGHTS`: costo osservato e costo simulato restano tipi distinti.
- Blueprint e risultati sono immutabili; ogni correzione crea una nuova revisione.
- Un prezzo sconosciuto resta `None`, mai `0`.
- Un ciclo o retry illimitato produce `unbounded`, mai un massimo inventato.
- JSON/YAML usano parsing sicuro; HTML applica escaping a ogni valore dinamico e non carica asset remoti.
- La CLI non simula senza `--confirmed`; `draft` valida e normalizza soltanto.
- Il riepilogo stdout del coding agent resta conciso; il report completo vive in un artefatto.
- Fixture e corpus sono sintetici o sanificati; nessun transcript, vault, percorso home o dato personale entra nel repository.

---

### Task 1: Contratto Blueprint immutabile e round-trip sicuro

**Files:**
- Create: `starkeno/preflight_schema.py`
- Create: `tests/test_preflight_schema.py`
- Create: `tests/fixtures/preflight/minimal.json`
- Modify: `pyproject.toml`
- Modify: `requirements/ci.txt`

**Interfaces:**
- Produce `IntEstimate`, `RatioEstimate`, `MoneyEstimate`, `Goal`, `Agent`, `ToolSpec`, `SkillSpec`, `ContextSource`, `NodeBudget`, `WorkflowNode`, `Transition`, `ModelProfile`, `Blueprint`.
- Produce `load_blueprint(text: str, *, format_hint: str | None = None) -> Blueprint`.
- Produce `dump_blueprint(blueprint: Blueprint, *, format: Literal["json", "yaml"]) -> str`.
- Produce `blueprint_hash(blueprint: Blueprint) -> str`.

- [x] **Step 1: aggiungere i test rossi del contratto**

```python
def test_round_trip_json_yaml_preserva_il_blueprint_e_hash():
    originale = load_blueprint(Path(FIXTURE).read_text(encoding="utf-8"), format_hint="json")
    da_json = load_blueprint(dump_blueprint(originale, format="json"), format_hint="json")
    da_yaml = load_blueprint(dump_blueprint(originale, format="yaml"), format_hint="yaml")
    assert da_json == da_yaml == originale
    assert blueprint_hash(da_json) == blueprint_hash(da_yaml)


def test_riferimento_a_nodo_inesistente_viene_rifiutato():
    dati = json.loads(Path(FIXTURE).read_text(encoding="utf-8"))
    dati["transitions"][0]["target"] = "manca"
    with pytest.raises(ValueError, match="manca"):
        Blueprint.model_validate(dati)


def test_intervallo_deve_essere_ordinato():
    with pytest.raises(ValueError, match="min.*typical.*max"):
        IntEstimate(min=10, typical=4, max=8, provenance="declared",
                    confidence="high", reason="test")


def test_yaml_non_costruisce_oggetti_python():
    with pytest.raises(ValueError, match="YAML"):
        load_blueprint("!!python/object/apply:os.system ['whoami']", format_hint="yaml")
```

- [x] **Step 2: osservare il fallimento**

Run: `python -m pytest tests/test_preflight_schema.py -q`

Expected: FAIL in collection because `starkeno.preflight_schema` does not exist.

- [x] **Step 3: implementare i modelli e gli invarianti**

Usare una base condivisa:

```python
class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IntEstimate(FrozenModel):
    min: int = Field(ge=0)
    typical: int = Field(ge=0)
    max: int = Field(ge=0)
    provenance: Literal["measured", "declared", "inferred", "default"]
    confidence: Literal["high", "medium", "low"]
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordinato(self):
        if not self.min <= self.typical <= self.max:
            raise ValueError("min, typical e max devono essere ordinati")
        return self
```

`RatioEstimate` applica lo stesso invariante con valori `0 <= x <= 1`. `Blueprint`
contiene `schema_version="1.0"`, `revision >= 1`, `parent_revision`, `confirmed`, goal,
tuple di agenti/tool/skill/contesti/nodi/transizioni/modelli e `entry_node_ids`. Il
validator costruisce gli insiemi di ID, rifiuta duplicati e riferimenti inesistenti.

`NodeBudget` contiene `instructions`, `dynamic_context`, `output`, `cacheable_fraction`,
`latency_ms`, `retry_probability`, `max_retries: int | None` e
`fixed_tool_cost: MoneyEstimate | None`, ammesso soltanto per nodi `tool`; l'assenza resta
costo sconosciuto e zero deve essere esplicito. `Transition` contiene
`source`, `target`, `activation: Literal["choice", "always"]`, probabilità opzionale,
`parallel_group` e `max_traversals: int | None`; la chiave
`(source, target, activation, parallel_group)` deve essere univoca. La corrispondente
chiave quantitativa usa il prefisso `transition:` seguito dal JSON canonico della tupla,
preservando la distinzione fra `None`, stringa vuota e ID contenenti delimitatori.

`load_blueprint` usa `json.loads` o `yaml.safe_load`, rifiuta una radice non mapping e
converte ogni errore del parser in `ValueError` con formato e posizione. `dump_blueprint`
usa `model_dump(mode="json")`, `json.dumps(payload, sort_keys=True, ensure_ascii=False,
indent=2)` o `yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)`. L'hash è SHA-256
del JSON canonico con separatori compatti.

- [x] **Step 4: rendere PyYAML una dipendenza runtime e rigenerare il lock CI**

Spostare `PyYAML>=6,<7` da `[project.optional-dependencies].dev` a
`[project.dependencies]` e dichiarare direttamente `pydantic>=2.9,<3`, poi eseguire:

Run: `piptools compile --extra=dev --output-file=requirements/ci.txt --strip-extras pyproject.toml`

Expected: `pyyaml==6.0.3` resta una sola volta ed è attribuito a StarkEno.

- [x] **Step 5: verificare e committare**

Run: `python -m pytest tests/test_preflight_schema.py -q`

Expected: PASS.

```bash
git add pyproject.toml requirements/ci.txt starkeno/preflight_schema.py tests/test_preflight_schema.py tests/fixtures/preflight/minimal.json
git commit -m "feat: definisce il blueprint preflight"
```

---

### Task 2: Linter deterministico con evidenze stabili

**Files:**
- Create: `starkeno/preflight_lint.py`
- Create: `tests/test_preflight_lint.py`

**Interfaces:**
- Consumes `Blueprint`, `WorkflowNode`, `Transition`.
- Produce `Finding(rule_id, severity, category, message, evidence, locations, suggestion, source, blueprint_hash)`.
- Produce `lint_blueprint(blueprint: Blueprint) -> tuple[Finding, ...]`.
- Produce `has_blocking_findings(findings: Iterable[Finding]) -> bool`.
- Produce `finding_sort_key(finding: Finding) -> tuple[int, str, tuple[str, ...]]`.

- [x] **Step 1: scrivere test rossi per goal, grafo e limiti**

```python
def test_goal_senza_criteri_e_nodo_irraggiungibile_sono_spiegati():
    blueprint = make_blueprint(success_criteria=(), extra_unreachable=True)
    findings = {f.rule_id: f for f in lint_blueprint(blueprint)}
    assert findings["PF-GOAL-001"].severity == "error"
    assert findings["PF-GRAPH-001"].locations == ("nodes/orphan",)


def test_ciclo_senza_limite_blocca_ma_ciclo_limitato_no():
    illimitato = make_cyclic_blueprint(max_traversals=None)
    limitato = make_cyclic_blueprint(max_traversals=3)
    assert "PF-LOOP-001" in {f.rule_id for f in lint_blueprint(illimitato)}
    assert "PF-LOOP-001" not in {f.rule_id for f in lint_blueprint(limitato)}


def test_retry_senza_massimo_e_llm_per_calcolo_deterministico():
    blueprint = make_blueprint(max_retries=None, deterministic_with_model=True)
    ids = {f.rule_id for f in lint_blueprint(blueprint)}
    assert {"PF-RETRY-001", "PF-MODEL-001"} <= ids
```

- [x] **Step 2: osservare il fallimento**

Run: `python -m pytest tests/test_preflight_lint.py -q`

Expected: FAIL in collection because `starkeno.preflight_lint` does not exist.

- [x] **Step 3: implementare regole pure e ordinamento**

Implementare almeno:

- `PF-GOAL-001`: criteri di successo assenti;
- `PF-GRAPH-001`: nodo irraggiungibile dagli entry point;
- `PF-GRAPH-002`: nessun terminale raggiungibile;
- `PF-LOOP-001`: ciclo restante dopo aver rimosso gli archi con
  `max_traversals > 0`;
- `PF-RETRY-001`: `max_retries is None` con probabilità retry non nulla;
- `PF-AGENT-001`: agente mai assegnato;
- `PF-AGENT-002`: responsabilità normalizzata duplicata;
- `PF-HANDOFF-001`: handoff senza agente sorgente o destinazione distinta;
- `PF-MODEL-001`: nodo deterministico con modello;
- `PF-VERIFY-001`: nessun gate o human approval raggiungibile prima dei terminali.

La ricerca cicli usa DFS sul sottografo degli archi non limitati. Ogni finding contiene
valori osservati in `evidence`, non soltanto testo. Ordinare per severità
`critical,error,warning,info`, poi `rule_id`, poi location; a parità di input l'output è
byte-stabile.

- [x] **Step 4: verificare e committare**

Run: `python -m pytest tests/test_preflight_schema.py tests/test_preflight_lint.py -q`

Expected: PASS.

```bash
git add starkeno/preflight_lint.py tests/test_preflight_lint.py
git commit -m "feat: aggiunge il linter preflight"
```

---

### Task 3: Simulatore riproducibile e costi non inventati

**Files:**
- Create: `starkeno/preflight_simulate.py`
- Create: `tests/test_preflight_simulate.py`

**Interfaces:**
- Consumes `Blueprint`, `ModelProfile`.
- Produce `NodeTotals`, `ScenarioTotals`, `SimulationReport` come Pydantic model frozen.
- Produce `simulate_blueprint(blueprint: Blueprint, *, samples: int = 1000, seed: int | None = None) -> SimulationReport`.

- [x] **Step 1: scrivere i test rossi per somme, seed e limiti**

```python
def test_stesso_seed_produce_lo_stesso_report_e_le_somme_quadrano():
    blueprint = probabilistic_blueprint(confirmed=True)
    a = simulate_blueprint(blueprint, samples=200, seed=42)
    b = simulate_blueprint(blueprint, samples=200, seed=42)
    assert a == b
    assert a.typical.input_tokens == sum(n.input_tokens for n in a.typical.nodes)
    assert a.typical.output_tokens == sum(n.output_tokens for n in a.typical.nodes)


def test_non_simula_un_blueprint_non_confermato():
    with pytest.raises(ValueError, match="confermato"):
        simulate_blueprint(make_blueprint(confirmed=False), samples=10, seed=1)


def test_ciclo_illimitato_non_inventa_un_massimo():
    report = simulate_blueprint(make_cyclic_blueprint(confirmed=True, max_traversals=None),
                                samples=20, seed=1)
    assert report.maximum_status == "unbounded"
    assert report.maximum is None


def test_prezzo_sconosciuto_resta_sconosciuto():
    report = simulate_blueprint(blueprint_with_unknown_price(confirmed=True), samples=20, seed=1)
    assert report.typical.cost is None
    assert "model-without-price" in report.unknown_prices
```

- [x] **Step 2: osservare il fallimento**

Run: `python -m pytest tests/test_preflight_simulate.py -q`

Expected: FAIL in collection because `starkeno.preflight_simulate` does not exist.

- [x] **Step 3: implementare il motore per singola corsa**

Una corsa mantiene una coda di `ExecutionFrame(node_id, edge_counts, ready_at_ms)`.
Per ogni nodo:

1. sceglie min/typical/max dal budget richiesto;
2. campiona retry fino a `max_retries` usando `retry_probability`;
3. separa token `input`, `output`, `cache_read`, `cache_write` tramite
   `cacheable_fraction`, senza usare i pesi del conto osservato;
4. incrementa chiamate LLM o tool in base al tipo;
5. attiva tutti gli archi `always`; per gli archi `choice` ne sceglie uno usando le
   probabilità dichiarate, oppure distribuzione uniforme marcata fra le assunzioni;
6. impedisce a un arco limitato di superare `max_traversals`;
7. applica un tetto interno di passi soltanto come guardia: se scatta, il report dichiara
   `unbounded`, non restituisce dati parziali come completi.

Per `parallel_group`, i token si sommano e la latenza del gruppo è il massimo dei rami;
gli archi senza gruppo sono seriali. Gli agenti e i nodi ricevono subtotali distinti.

- [x] **Step 4: implementare scenari e prezzo**

- `optimistic`: valori minimi, nessun retry, ramo choice dal costo minimo;
- `typical`: p50 dei campioni su valori typical;
- `prudent`: p90 dei campioni;
- `maximum`: valori massimi, tutti i retry e ramo choice dal costo massimo, soltanto se
  ogni ciclo e retry è limitato.

Il seed predefinito deriva dai primi 64 bit di `blueprint_hash`. Validare
`1 <= samples <= 10_000`. Il costo usa `Decimal` e i prezzi per milione del modello;
se manca anche una sola categoria necessaria, il costo totale dello scenario è `None` e
il modello compare in `unknown_prices`.

- [x] **Step 5: verificare e committare**

Run: `python -m pytest tests/test_preflight_simulate.py -q`

Expected: PASS.

Run: `python -m pytest tests/test_preflight_schema.py tests/test_preflight_lint.py tests/test_preflight_simulate.py -q -W error`

Expected: PASS senza warning.

```bash
git add starkeno/preflight_simulate.py tests/test_preflight_simulate.py
git commit -m "feat: simula i blueprint preflight"
```

---

### Task 4: Correzioni atomiche e confronto a condizioni uguali

**Files:**
- Create: `starkeno/preflight_patch.py`
- Create: `tests/test_preflight_patch.py`

**Interfaces:**
- Produce `PatchOperation`, `Correction`, `PatchConflict`, `PatchResult`, `Comparison`.
- Produce `apply_corrections(blueprint: Blueprint, corrections: tuple[Correction, ...]) -> PatchResult`.
- Produce `compare_reports(before: SimulationReport, after: SimulationReport) -> Comparison`.

- [x] **Step 1: scrivere test rossi per atomicità e reversibilità**

```python
def test_patch_test_replace_e_inverse_lasciano_originale_invariato():
    original = make_blueprint(confirmed=True)
    correction = replace_model_correction(expected="frontier", replacement="economy")
    applied = apply_corrections(original, (correction,))
    assert original.nodes[0].model_id == "frontier"
    assert applied.blueprint.nodes[0].model_id == "economy"
    restored = apply_corrections(applied.blueprint, applied.inverse)
    assert restored.blueprint.model_dump(exclude={"revision", "parent_revision"}) == \
        original.model_dump(exclude={"revision", "parent_revision"})
    assert restored.blueprint.revision == applied.blueprint.revision + 1
    assert restored.blueprint.parent_revision == applied.blueprint.revision


def test_precondizione_fallita_non_applica_nessuna_operazione():
    original = make_blueprint(confirmed=True)
    bad = correction_with_wrong_test_value()
    result = apply_corrections(original, (bad,))
    assert result.blueprint == original
    assert result.conflicts[0].correction_id == bad.id


def test_confronto_rifiuta_seed_o_assunzioni_diverse():
    with pytest.raises(ValueError, match="stesse condizioni"):
        compare_reports(report(seed=1), report(seed=2))
```

- [x] **Step 2: osservare il fallimento**

Run: `python -m pytest tests/test_preflight_patch.py -q`

Expected: FAIL in collection because `starkeno.preflight_patch` does not exist.

- [x] **Step 3: implementare il sottoinsieme JSON Patch**

Supportare soltanto `test`, `add`, `remove`, `replace` su JSON Pointer RFC 6901.
Applicare ogni `Correction` a una copia del `model_dump(mode="json")`; se una sua
operazione fallisce, scartare tutte le operazioni della correzione e registrare il
conflitto. Validare il risultato con `Blueprint.model_validate`, incrementare `revision`,
impostare `parent_revision` e non cambiare `confirmed`.

Una chiamata è una sola revisione di batch: le correzioni sono atomiche singolarmente e
si valutano nell'ordine ricevuto; quelle in conflitto non annullano le precedenti. Se
almeno una correzione riesce, `revision` aumenta una sola volta e `parent_revision`
punta alla revisione d'ingresso; se nessuna riesce, il Blueprint originale viene
restituito invariato. Operazioni su `schema_version`, `revision`, `parent_revision` o
`confirmed` sono conflitti, incluso un replace della radice che li aggirerebbe.

Costruire operazioni inverse durante l'applicazione: `add -> remove`, `remove -> add` col
valore rimosso, `replace -> replace` col valore precedente. Ogni inverse include una
precondizione `test` sul valore corrente. `PatchResult.inverse` è una
`tuple[Correction, ...]` delle sole correzioni riuscite, in ordine globale inverso; anche
le operazioni mutanti interne sono invertite. Per `remove -> add`, dove il path non
esiste più, la precondizione testa il contenitore genitore nello stato atteso. Le inverse
creano una nuova revisione: ripristinano il contenuto, non falsificano la lineage.

`compare_reports` richiede stesso seed, samples, profilo e versione algoritmo; produce
delta assoluto e percentuale opzionale per token, chiamate, latenza e costo. Percentuale
su baseline zero resta `None`. Le condizioni persistite da `SimulationReport` sono
`effective_seed`, `samples`, `profile_hash`, `algorithm_version`, la base quantitativa
frozen per entità e `assumptions_hash`. Quest'ultimo copre versione, base completa e
fallback. `blueprint_hash` può e deve differire. Il confronto richiede gli stessi
fingerprint per le chiavi quantitative condivise, consente entità aggiunte/rimosse e
conserva gli hash assunzioni prima/dopo. Prima di costruire gli indici rifiuta inoltre
chiavi quantitative duplicate anche nei report manuali o legacy. Il chiamante risimula
la revisione passando esplicitamente
`seed=before.effective_seed`. Il confronto copre `optimistic`, `typical`, `prudent` e il
`maximum` quando presente in entrambi; uno scenario assente resta dichiarato, non zero.

- [x] **Step 4: verificare e committare**

Run: `python -m pytest tests/test_preflight_patch.py tests/test_preflight_simulate.py -q`

Expected: PASS.

```bash
git add starkeno/preflight_patch.py tests/test_preflight_patch.py
git commit -m "feat: applica correzioni preflight reversibili"
```

---

### Task 5: Report ed export sicuri

**Files:**
- Create: `starkeno/preflight_report.py`
- Create: `tests/test_preflight_report.py`

**Interfaces:**
- Consume `Blueprint`, `Finding`, `SimulationReport`, `Comparison`.
- Produce `PreflightAnalysis` frozen con `blueprint`, `findings`, `simulation`,
  `comparison: Comparison | None` e `source_path: Path | None`.
- Produce `render_analysis(analysis: PreflightAnalysis, *, format: Literal["json", "yaml", "markdown", "html"]) -> str`.
- Produce `write_analysis(analysis: PreflightAnalysis, destination: Path, *, format: str) -> Path`.

- [x] **Step 1: scrivere test rossi per formati e sicurezza**

```python
@pytest.mark.parametrize("format", ["json", "yaml", "markdown", "html"])
def test_ogni_formato_contiene_ipotesi_confidenza_e_scenari(format):
    output = render_analysis(make_analysis(), format=format)
    assert "typical" in output.lower()
    assert "confidence" in output.lower() or "confidenza" in output.lower()
    assert "declared" in output.lower()


def test_html_escapa_input_e_non_carica_asset_remoti():
    html = render_analysis(make_analysis(goal='<script src="https://evil.test/x"></script>'),
                           format="html")
    assert '<script src=' not in html
    assert "&lt;script" in html
    assert '<link' not in html.lower()
    assert ' src="' not in html.lower()


def test_output_non_puo_sovrascrivere_input(tmp_path):
    source = tmp_path / "blueprint.json"
    source.write_text("originale", encoding="utf-8")
    with pytest.raises(ValueError, match="input"):
        write_analysis(make_analysis(source_path=source), source, format="json")
    assert source.read_text(encoding="utf-8") == "originale"
```

- [x] **Step 2: osservare il fallimento**

Run: `python -m pytest tests/test_preflight_report.py -q`

Expected: FAIL in collection because `starkeno.preflight_report` does not exist.

- [x] **Step 3: implementare renderer puri e scrittura al confine**

JSON e YAML serializzano modelli in `mode="json"`; YAML usa `safe_dump`. Markdown mostra
goal, cinque rilievi principali, scenari, assunzioni dominanti, prezzi ignoti e limiti.
HTML contiene gli stessi dati, CSS inline, CSP tramite meta tag e ogni valore dinamico
passa da `html.escape(str(value), quote=True)`.

`source_path` è metadato locale del confine I/O, escluso da tutti e quattro gli export;
non inserire timestamp o altri valori ambientali che rompano la stabilità byte-per-byte.
Un URL presente nel testo utente può rimanere visibile dopo escaping: il vincolo è che
non diventi un tag o attributo caricabile (`script`, `link`, `img`, `src`).

`write_analysis` rifiuta una destinazione che risolve allo stesso file dell'input,
crea soltanto la directory genitore, scrive UTF-8 e restituisce il percorso risolto.

- [x] **Step 4: verificare e committare**

Run: `python -m pytest tests/test_preflight_report.py -q`

Expected: PASS.

```bash
git add starkeno/preflight_report.py tests/test_preflight_report.py
git commit -m "feat: esporta i report preflight"
```

---

### Task 6: Service locale e protocollo di conferma CLI

**Files:**
- Create: `starkeno/preflight_service.py`
- Create: `starkeno/preflight_cli.py`
- Create: `tests/test_preflight_cli.py`
- Modify: `starkeno/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produce `normalize_draft(text: str, *, format_hint: str | None) -> Blueprint` senza simulare.
- Produce `analyze_confirmed(blueprint: Blueprint, *, samples: int, seed: int | None,
  source_path: Path | None = None) -> PreflightAnalysis`.
- Produce `preflight_cli.main(argv: Sequence[str] | None = None) -> int`.
- Extend `starkeno.cli.main` with delegated `preflight` command.

- [x] **Step 1: scrivere test rossi per il confine umano**

```python
def test_draft_normalizza_ma_non_chiama_il_simulatore(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    output = tmp_path / "draft.json"
    source.write_text(MINIMAL_BLUEPRINT, encoding="utf-8")
    monkeypatch.setattr("starkeno.preflight_service.simulate_blueprint",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("simulato")))
    assert main(["draft", "--input", str(source), "--format", "json",
                 "--output", str(output)]) == 0


def test_analyze_rifiuta_senza_confirmed(tmp_path, capsys):
    source = write_blueprint(tmp_path, confirmed=False)
    output = tmp_path / "report.json"
    assert main(["analyze", "--input", str(source),
                 "--output", str(output), "--format", "json"]) == 2
    assert "--confirmed" in capsys.readouterr().err


def test_analyze_confirmed_scrive_artefatto_e_stdout_conciso(tmp_path, capsys):
    source = write_blueprint(tmp_path, confirmed=False)
    output = tmp_path / "report.json"
    assert main(["analyze", "--input", str(source), "--confirmed",
                 "--output", str(output), "--format", "json", "--samples", "20"]) == 0
    assert output.exists()
    stdout = capsys.readouterr().out
    assert len(stdout.encode("utf-8")) <= 2_000
    assert str(output.resolve()) in stdout
```

- [x] **Step 2: osservare il fallimento**

Run: `python -m pytest tests/test_preflight_cli.py -q`

Expected: FAIL in collection because `starkeno.preflight_cli` does not exist.

- [x] **Step 3: implementare service e CLI**

La CLI ha due sottocomandi:

```text
starkeno preflight draft --input blueprint.yaml --format json --output draft.json
starkeno preflight analyze --input draft.json --confirmed --format html --output report.html
```

`--format` indica sempre il formato di output. Il formato di input si inferisce da
`.json`, `.yaml` o `.yml`; `--input-format {json,yaml}` lo può sovrascrivere ed è
obbligatorio quando si legge stdin o un suffisso ignoto. `--output` è obbligatorio per
entrambi i sottocomandi, non può coincidere con l'input e stdout contiene soltanto esito
e percorso dell'artefatto.

`draft` forza `confirmed=False` senza chiamare il simulatore. Se disconferma un Blueprint
già confermato crea una nuova revisione; altrimenti la sola normalizzazione non inventa
una revisione. `analyze --confirmed` crea sempre una nuova revisione con
`revision + 1`, `parent_revision` uguale alla revisione letta e `confirmed=True`, quindi
esegue lint e simulazione e scrive il report col suo `source_path` locale. Errori di input
o conferma restituiscono `2`; errori interni restituiscono `1` senza stack trace su stdout.

Il confine è difeso due volte: `normalize_draft` applica la regola di disconferma e non
importa/chiamata il simulatore; `analyze_confirmed` accetta soltanto un Blueprint già
`confirmed=True` e non può confermarlo implicitamente. È la CLI, esclusivamente in
presenza del flag letterale `--confirmed`, a costruire la nuova revisione confermata.
Parsing/validazione/uso scorretto scrivono un messaggio conciso su stderr e ritornano 2,
senza lasciare artefatti; i parser diretti non propagano `SystemExit` al chiamante.

`draft` e `analyze` sono nomi provvisori del core strutturato. I comandi pubblici
`design` e `review` arriveranno col compilatore in linguaggio naturale e riuseranno
questo stesso protocollo di conferma; non aggiungere parsing naturale in questo task.

In `starkeno/cli.py` seguire la delega di `report`: parser `preflight` con
`add_help=False`, poi `return preflight_cli.main(residui)` prima della logica doctor.

- [x] **Step 4: verificare e committare**

Run: `python -m pytest tests/test_preflight_cli.py tests/test_cli.py -q`

Expected: PASS.

```bash
git add starkeno/preflight_service.py starkeno/preflight_cli.py starkeno/cli.py tests/test_preflight_cli.py tests/test_cli.py
git commit -m "feat: espone il preflight locale"
```

---

### Task 7: Corpus sintetico e gate del core

**Files:**
- Create: `tests/fixtures/preflight/simple.json`
- Create: `tests/fixtures/preflight/medium.json`
- Create: `tests/fixtures/preflight/complex-team.json`
- Create: `tests/fixtures/preflight/unbounded-loop.json`
- Create: `tests/test_preflight_corpus.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/plans/2026-08-13-preflight-core.md`

**Interfaces:**
- Consume all public core and CLI interfaces.
- Produce a reproducible four-case smoke corpus and documented local workflow.

- [x] **Step 1: aggiungere il corpus e i gate rossi**

```python
CORPUS = tuple(FIXTURES / name for name in (
    "simple.json", "medium.json", "complex-team.json", "unbounded-loop.json"
))


@pytest.mark.parametrize("fixture", CORPUS)
def test_corpus_round_trip_lint_e_simulazione_non_crashano(fixture):
    blueprint = load_blueprint(fixture.read_text(encoding="utf-8"), format_hint="json")
    encoded = dump_blueprint(blueprint, format="json")
    assert load_blueprint(encoded, format_hint="json") == blueprint
    findings = lint_blueprint(blueprint)
    confirmed = blueprint.model_copy(update={
        "revision": blueprint.revision + 1,
        "parent_revision": blueprint.revision,
        "confirmed": True,
    })
    report = simulate_blueprint(confirmed, samples=50)
    assert report.blueprint_hash == blueprint_hash(confirmed)
    assert tuple(findings) == tuple(sorted(findings, key=finding_sort_key))


def test_fixture_illimitata_dichiara_unbounded():
    blueprint = load_fixture("unbounded-loop.json").model_copy(update={"confirmed": True})
    assert simulate_blueprint(blueprint, samples=20).maximum_status == "unbounded"
```

`minimal.json` resta la fixture contrattuale dello schema e non fa parte dei quattro casi
smoke. Il test del corpus deve esercitare davvero dump/load prima di lint e simulazione.

- [x] **Step 2: eseguire gate completi**

Run: `python -m pytest -q -W error`

Expected: PASS.

Run: `python -m build`

Expected: wheel e sdist creati.

Run: `python -m pip check`

Expected: nessuna dipendenza rotta.

Run: `python scripts/verifica_segreti.py --tracked`

Expected: exit 0.

Run: `python scripts/verifica_pubblicazione.py`

Expected: exit 0.

Run: `git diff --check`

Expected: nessun errore.

- [x] **Step 3: documentare il confine e la verifica**

Nel README aggiungere una sezione “Preflight sperimentale” con i due comandi
`draft`/`analyze --confirmed`, dichiarando che il core non interpreta ancora linguaggio
naturale e non esegue workflow. Nel changelog registrare schema v1, lint, simulatore,
patch ed export. Spuntare le task completate in questo piano.

- [x] **Step 4: commit finale del core**

```bash
git add README.md CHANGELOG.md docs/superpowers/plans/2026-08-13-preflight-core.md tests/fixtures/preflight tests/test_preflight_corpus.py
git commit -m "test: verifica il core preflight"
```

Run: `git status --short`

Expected: worktree pulito.
