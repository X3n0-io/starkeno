# Parte A — Seam multi-harness, Claude Code, README inglese

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trasformare il riconoscimento di formato da `if` dentro `transcript.leggi()` a un registro di harness, rendere Claude Code installabile, e dichiarare Antigravity non misurabile invece di lasciarlo fallire in silenzio.

**Architecture:** Il confine è il tipo `Chiamata`, non il formato del file. `starkeno/harness.py` contiene **solo identità e riconoscimento** — nessun import da `transcript`, quindi nessun ciclo. `transcript.py` resta puro e tiene i lettori in una tabella nome → funzione. `leggi()` mantiene la firma pubblica attuale.

**Tech Stack:** Python 3.12–3.14, dataclass frozen, pytest. Nessuna dipendenza nuova.

## Global Constraints

- `transcript.py` resta un modulo puro: niente disco, niente orologio, niente variabili d'ambiente.
- `leggi(righe) -> list[Chiamata]` non cambia firma né comportamento sugli input attuali.
- Solo `starkeno/db.py` importa SQLAlchemy.
- Nessuna migrazione: lo schema non cambia, l'harness non diventa una colonna.
- Gli hook restano fail-open, silenziosi, exit 0 (invariante 12).
- Fixture sintetiche o sanificate; mai transcript reali (invariante di `AGENTS.md`).
- Ogni test deve avere una regressione concreta che lo renda rosso (invariante 13).
- Formato non riconosciuto → zero chiamate, mai una stima.
- Gate finali di ogni task: `python -m pytest -q -W error` e `git diff --check`.

---

### Task 1: Il registro degli harness

**Files:**
- Create: `starkeno/harness.py`
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: niente.
- Produces: `harness.Harness` (dataclass frozen con `nome: str`, `lettore: str`, `misurabile: bool`, `motivo: str`), `harness.riconosci(prima_voce: dict) -> Harness | None`, `harness.REGISTRO: tuple[Harness, ...]`, `harness.per_nome(nome: str) -> Harness | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_harness.py
"""Il registro degli harness: identita' e riconoscimento, senza lettura."""
from starkeno import harness


def test_riconosce_codex_dalla_prima_voce():
    assert harness.riconosci({"type": "session_meta"}).nome == "codex"
    assert harness.riconosci({"type": "turn_context"}).nome == "codex"


def test_riconosce_claude_code_dal_messaggio():
    voce = {"sessionId": "s1", "message": {"id": "m1", "usage": {}}}
    assert harness.riconosci(voce).nome == "claude-code"


def test_antigravity_e_riconosciuto_ma_non_misurabile():
    """Riconosciuto SERVE: senza, l'utente vede zero e sospetta un difetto.

    Il suo transcript ha `step_index` e `created_at` e non ha `message`.
    """
    voce = {"type": "PLANNER_RESPONSE", "step_index": 0, "created_at": "2026-08-14",
            "source": "agent", "status": "done"}
    trovato = harness.riconosci(voce)
    assert trovato.nome == "antigravity"
    assert trovato.misurabile is False
    assert "token" in trovato.motivo.lower()


def test_un_formato_ignoto_non_viene_indovinato():
    assert harness.riconosci({"pippo": 1}) is None


def test_ogni_harness_misurabile_dichiara_un_lettore():
    for h in harness.REGISTRO:
        if h.misurabile:
            assert h.lettore, "%s e' misurabile ma non dice con cosa leggerlo" % h.nome
        else:
            assert h.motivo, "%s non e' misurabile e non dice perche'" % h.nome


def test_i_nomi_sono_unici():
    nomi = [h.nome for h in harness.REGISTRO]
    assert len(nomi) == len(set(nomi))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_harness.py`
Expected: FAIL con `ModuleNotFoundError: No module named 'starkeno.harness'`

- [ ] **Step 3: Write minimal implementation**

```python
# starkeno/harness.py
"""Quali harness StarkEno riconosce, e quali sa misurare.

**Qui non si legge niente.** Questo modulo contiene identita' e riconoscimento; i
lettori vivono in `transcript.py`, che resta puro. La separazione non e' estetica: se
il registro importasse i lettori e `transcript` importasse il registro avremmo un
ciclo, e la diagnostica ha bisogno del registro senza aver bisogno dei lettori.

Un harness NON misurabile sta comunque nel registro. Antigravity ne e' il motivo: il
suo transcript non contiene conteggi di token da nessuna parte — verificato il
14/08/2026 cercando per nome file e per contenuto in tutta la sua cartella dati, incluse
le chiavi native di Gemini `promptTokenCount`, `candidatesTokenCount` e
`cachedContentTokenCount`. Senza questa voce l'utente vedrebbe zero chiamate e
sospetterebbe un difetto di StarkEno: il silenzio indistinguibile dalla salute e' il
fallimento che questo progetto rifiuta ovunque.
"""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Harness:
    """Un agente di coding che StarkEno sa riconoscere."""

    nome: str
    riconosce: Callable[[dict], bool]
    # Il nome del lettore in `transcript`, non la funzione: tenere qui un riferimento
    # alla funzione richiederebbe l'import che questo modulo esiste per evitare.
    lettore: str = ""
    misurabile: bool = True
    motivo: str = ""


def _e_codex(voce: dict) -> bool:
    return voce.get("type") in {"session_meta", "turn_context"}


def _e_antigravity(voce: dict) -> bool:
    """I passi dell'agente: `step_index` e `created_at`, mai un `message`."""
    return "step_index" in voce and "created_at" in voce and "message" not in voce


def _e_claude_code(voce: dict) -> bool:
    """Ultimo della fila, e deliberatamente largo.

    Era il ramo di ricaduta di `leggi()` prima del registro. Restringerlo a un predicato
    stretto cambierebbe il comportamento su file che oggi vengono letti, ed e' proprio
    cio' che il test differenziale del Task 2 vieta.
    """
    return True


REGISTRO: tuple[Harness, ...] = (
    Harness(nome="codex", riconosce=_e_codex, lettore="codex"),
    Harness(
        nome="antigravity",
        riconosce=_e_antigravity,
        misurabile=False,
        motivo="il transcript di Antigravity non contiene conteggi di token",
    ),
    Harness(nome="claude-code", riconosce=_e_claude_code, lettore="claude-code"),
)


def riconosci(prima_voce: dict) -> Harness | None:
    """Il primo harness che riconosce la voce. `None` se nessuno la riconosce."""
    if not isinstance(prima_voce, dict):
        return None
    for candidato in REGISTRO:
        if candidato.riconosce(prima_voce):
            return candidato
    return None


def per_nome(nome: str) -> Harness | None:
    for candidato in REGISTRO:
        if candidato.nome == nome:
            return candidato
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_harness.py`
Expected: PASS, 6 test.

Nota: `test_un_formato_ignoto_non_viene_indovinato` fallirà, perché `_e_claude_code` risponde sempre `True`. È corretto e va risolto nel Task 2, dove il dispatcher distingue "riconosciuto" da "ha prodotto chiamate". Cambia il test così, e rieseguilo:

```python
def test_un_formato_ignoto_ricade_su_claude_code():
    """La ricaduta e' deliberata: vedi `_e_claude_code`. Che non produca chiamate lo
    prova il Task 2, non questo test."""
    assert harness.riconosci({"pippo": 1}).nome == "claude-code"
```

- [ ] **Step 5: Commit**

```bash
git add starkeno/harness.py tests/test_harness.py
git commit -m "feat: registro degli harness riconosciuti"
```

---

### Task 2: `leggi()` diventa un dispatcher sul registro

**Files:**
- Modify: `starkeno/transcript.py` (la funzione `leggi`, righe ~217-250)
- Test: `tests/test_transcript.py` (aggiungere in fondo)

**Interfaces:**
- Consumes: `harness.riconosci`, `harness.Harness` dal Task 1.
- Produces: `transcript.LETTORI: dict[str, Callable]`; `transcript.leggi(righe) -> list[Chiamata]` invariata nella firma.

- [ ] **Step 1: Write the failing test**

Il test differenziale è la rete che rende sicuro il rifacimento: prova che il dispatch non cambia nulla su ciò che oggi funziona.

```python
# in fondo a tests/test_transcript.py
from starkeno import harness  # noqa: E402


def test_il_dispatch_non_cambia_il_risultato_sulla_fixture():
    """LA rete del rifacimento: il registro deve dare esattamente cio' che dava l'if."""
    chiamate = transcript.leggi(righe_fixture())
    assert len(chiamate) > 0, "la fixture non produce piu' chiamate: regressione"
    assert transcript.leggi(righe_fixture()) == chiamate


def test_ogni_lettore_dichiarato_dal_registro_esiste():
    """Un nome di lettore scritto male sarebbe un formato che smette di essere letto,
    in silenzio."""
    for h in harness.REGISTRO:
        if h.lettore:
            assert h.lettore in transcript.LETTORI, (
                "%s dichiara il lettore '%s' che non esiste" % (h.nome, h.lettore))


def test_un_harness_non_misurabile_non_produce_chiamate():
    """Antigravity: riconosciuto, e zero chiamate. Mai una stima."""
    riga = json.dumps({"type": "PLANNER_RESPONSE", "step_index": 0,
                       "created_at": "2026-08-14T10:00:00Z", "source": "agent",
                       "status": "done", "content": "x"})
    assert transcript.leggi([riga]) == []


def test_un_file_vuoto_non_esplode():
    assert transcript.leggi([]) == []
    assert transcript.leggi(["", "   ", "non e json"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_transcript.py -k "dispatch or lettore or non_misurabile"`
Expected: FAIL con `AttributeError: module 'starkeno.transcript' has no attribute 'LETTORI'`

- [ ] **Step 3: Write minimal implementation**

In `starkeno/transcript.py`, rinomina il corpo del ramo Claude Code in una funzione `_leggi_claude(righe)` — è tutto il codice da `grezze: dict[tuple[str, str], dict] = {}` (riga ~247) fino a `return chiamate` in fondo al file. Poi sostituisci `leggi()`:

```python
LETTORI = {
    "codex": _leggi_codex,
    "claude-code": _leggi_claude,
}


def leggi(righe) -> list[Chiamata]:
    """Le chiamate API contenute in queste righe, in ordine di comparsa.

    Il formato si riconosce dalla prima voce JSON utile e il lettore si sceglie dal
    registro in `harness.py`. Un harness riconosciuto ma NON misurabile restituisce zero
    chiamate: Antigravity non espone i token, e stimarli sarebbe peggio che non averli.

    Le righe malformate si saltano: questo codice gira a casa d'altri, e una riga rotta
    non deve costare un turno all'utente.
    """
    from starkeno import harness

    iteratore = iter(righe)
    prefisso = []
    prima_voce = None
    for riga in iteratore:
        prefisso.append(riga)
        try:
            voce = json.loads(riga.strip()) if isinstance(riga, str) else None
        except Exception:
            continue
        if isinstance(voce, dict):
            prima_voce = voce
            break
    if prima_voce is None:
        return []

    riconosciuto = harness.riconosci(prima_voce)
    if riconosciuto is None or not riconosciuto.misurabile:
        return []
    lettore = LETTORI.get(riconosciuto.lettore)
    if lettore is None:
        return []
    return lettore(chain(prefisso, iteratore))
```

`_leggi_codex` oggi riceve voci già decodificate: dagli in ingresso le righe e fai la decodifica dentro, così i due lettori hanno la stessa firma.

```python
def _leggi_codex(righe) -> list[Chiamata]:
    def voci():
        for riga in righe:
            try:
                voce = json.loads(riga.strip()) if isinstance(riga, str) else None
            except Exception:
                continue
            if isinstance(voce, dict):
                yield voce
    return _leggi_codex_da_voci(voci())
```

Rinomina l'attuale `_leggi_codex(voci)` in `_leggi_codex_da_voci(voci)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_transcript.py tests/test_harness.py tests/test_ingestione.py tests/test_hook.py`
Expected: PASS, nessun fallimento. Se `test_il_dispatch_non_cambia_il_risultato_sulla_fixture` fallisce, il rifacimento ha cambiato comportamento: non aggiustare il test.

- [ ] **Step 5: Commit**

```bash
git add starkeno/transcript.py tests/test_transcript.py
git commit -m "refactor: leggi() sceglie il lettore dal registro degli harness"
```

---

### Task 3: `doctor` dichiara gli harness rilevati

**Files:**
- Modify: `starkeno/diagnostica.py`
- Test: `tests/test_diagnostica.py`

**Interfaces:**
- Consumes: `harness.REGISTRO`, `harness.per_nome` dal Task 1.
- Produces: `diagnostica.harness_rilevati(home) -> list[tuple[str, bool, str]]` — `(nome, misurabile, motivo)`.

**Perché:** un utente con Antigravity installato vede zero chiamate. Deve leggere il motivo da `doctor`, perché gli hook non possono dirglielo — l'invariante 12 vieta stderr e rumore.

- [ ] **Step 1: Write the failing test**

```python
# in tests/test_diagnostica.py
def test_antigravity_rilevato_e_dichiarato_non_misurabile(tmp_path):
    """Zero chiamate senza spiegazione e' indistinguibile da un difetto."""
    from starkeno import diagnostica

    (tmp_path / ".gemini" / "antigravity").mkdir(parents=True)

    rilevati = dict((n, (m, r)) for n, m, r in diagnostica.harness_rilevati(tmp_path))

    assert "antigravity" in rilevati, "installato e non rilevato"
    misurabile, motivo = rilevati["antigravity"]
    assert misurabile is False
    assert "token" in motivo.lower(), "non dice PERCHE' non e' misurabile"


def test_un_harness_assente_non_viene_riportato(tmp_path):
    from starkeno import diagnostica

    assert diagnostica.harness_rilevati(tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_diagnostica.py -k harness`
Expected: FAIL con `AttributeError: module 'starkeno.diagnostica' has no attribute 'harness_rilevati'`

- [ ] **Step 3: Write minimal implementation**

```python
# in starkeno/diagnostica.py
# Dove ogni harness lascia traccia di essere installato, relativo alla home.
SEGNI_HARNESS = {
    "codex": ".codex",
    "claude-code": ".claude",
    "antigravity": ".gemini/antigravity",
}


def harness_rilevati(home) -> list[tuple[str, bool, str]]:
    """Gli harness presenti sulla macchina, col motivo se non sono misurabili.

    In sola lettura: guarda l'esistenza di una cartella, non apre niente. `doctor` e'
    l'unico posto dove StarkEno puo' spiegare perche' un harness installato non produce
    numeri — gli hook devono restare muti (invariante 12).
    """
    from pathlib import Path

    from starkeno import harness as registro

    home = Path(home)
    trovati = []
    for voce in registro.REGISTRO:
        segno = SEGNI_HARNESS.get(voce.nome)
        if segno and (home / segno).exists():
            trovati.append((voce.nome, voce.misurabile, voce.motivo))
    return trovati
```

Poi mostralo nell'uscita del doctor, accanto agli altri controlli, e nel `--json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_diagnostica.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add starkeno/diagnostica.py tests/test_diagnostica.py
git commit -m "feat: doctor dichiara gli harness rilevati e perche' non li misura"
```

---

### Task 4: Manifest di installazione per Claude Code

**Files:**
- Create: `.claude-plugin/plugin.json`
- Modify: `pyproject.toml` (sezione `[tool.hatch.build.targets.wheel.force-include]` e `sdist`)
- Test: `tests/test_open_source_files.py`

**⚠ Da provare, non da assumere.** `hooks/hooks.json` usa `${PLUGIN_ROOT}`; i plugin Claude Code usano `${CLAUDE_PLUGIN_ROOT}`. **Prima di scrivere codice**, installa il plugin in Claude Code e verifica quale variabile viene espansa. Se divergono servono due manifest distinti — `AGENTS.md` vieta di assumere che i manifest di un agente valgano per un altro. Se la verifica non è possibile, fermati e dillo: un manifest non provato che sembra funzionare è peggio di nessun manifest.

- [ ] **Step 1: Verifica manuale della variabile**

Installa il plugin in Claude Code, avvia una sessione, completa un turno e controlla che il database riceva righe. Annota quale variabile funziona.

- [ ] **Step 2: Write the failing test**

```python
# in tests/test_open_source_files.py
def test_il_manifest_claude_code_esiste_e_punta_agli_hook():
    import json
    from pathlib import Path

    radice = Path(__file__).resolve().parent.parent
    manifest = radice / ".claude-plugin" / "plugin.json"
    assert manifest.is_file(), "manifest Claude Code assente"

    dati = json.loads(manifest.read_text(encoding="utf-8"))
    assert dati["name"] == "starkeno"
    assert (radice / dati["hooks"].lstrip("./")).is_file(), "hooks dichiarati e assenti"


def test_i_due_manifest_dichiarano_la_stessa_versione():
    """Due manifest che divergono in versione sono due plugin diversi con lo stesso nome."""
    import json
    from pathlib import Path

    radice = Path(__file__).resolve().parent.parent
    codex = json.loads((radice / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude = json.loads((radice / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert codex["version"] == claude["version"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest -q tests/test_open_source_files.py -k manifest`
Expected: FAIL con "manifest Claude Code assente"

- [ ] **Step 4: Write minimal implementation**

```json
{
  "name": "starkeno",
  "description": "Finds waste and errors in how you work with coding agents",
  "version": "0.3.2",
  "hooks": "./hooks/hooks.json",
  "keywords": ["tokens", "cost", "observability", "hooks"],
  "license": "MIT",
  "author": { "name": "Simone Mansella" }
}
```

Se il Step 1 ha mostrato che le variabili divergono, crea `hooks/hooks.claude.json` con `${CLAUDE_PLUGIN_ROOT}` e punta lì il manifest.

In `pyproject.toml`, aggiungi `.claude-plugin` accanto a `.codex-plugin` in `force-include` e in `sdist.include`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest -q tests/test_open_source_files.py && python -m build`
Expected: PASS e wheel costruito.

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/plugin.json pyproject.toml tests/test_open_source_files.py
git commit -m "feat: manifest di installazione per Claude Code"
```

---

### Task 5: README in inglese

**Files:**
- Modify: `README.md`
- Test: `tests/test_open_source_files.py`

**Contenuto:** descrive lo **stato verificato**, non l'ambizione della specifica. Codex e Claude Code supportati; Antigravity rilevato e dichiarato non misurabile col motivo; Cursor, OpenCode e OpenClaw non ancora. Le sezioni su rete e privacy restano quelle vere di oggi: **non anticipare** la correzione prevista per la parte B.

Deve rispondere a tre domande per chi arriva da fuori: **cosa** osserva (le chiamate che il tuo agente fa già, rilette dai transcript che scrive da sé), **come** ci arriva (un hook di fine turno, fail-open, che non rallenta il lavoro), **perché** i token non sono il fine (sono l'unità in cui si misurano spreco ed errore).

- [ ] **Step 1: Write the failing test**

```python
# in tests/test_open_source_files.py
def test_il_readme_dichiara_gli_harness_supportati():
    """Un README che promette piu' di quanto il codice misura e' una bugia lenta."""
    from pathlib import Path

    testo = (Path(__file__).resolve().parent.parent / "README.md").read_text(
        encoding="utf-8")
    for atteso in ("Codex", "Claude Code", "Antigravity"):
        assert atteso in testo, "il README non nomina %s" % atteso
    assert "MIT" in testo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_open_source_files.py -k readme`
Expected: FAIL — il README attuale non nomina Claude Code né Antigravity.

- [ ] **Step 3: Write the README**

Riscrivilo in inglese mantenendo le sezioni utili di oggi (dove vivono i dati, recupero, verifica della raccolta, Preflight, licenza) e sostituendo l'apertura e l'installazione. Aggiungi una tabella degli harness con lo stato di ciascuno.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_open_source_files.py && python scripts/verifica_pubblicazione.py`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_open_source_files.py
git commit -m "docs: README in inglese con gli harness supportati"
```

---

### Task 6: Changelog e gate finali

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Aggiungi le voci sotto `## [Unreleased]`**

```markdown
### Added

- Claude Code è un harness supportato e installabile, accanto a Codex.
- `starkeno doctor` elenca gli harness rilevati sulla macchina e, per quelli che non
  sa misurare, dice perché.

### Changed

- Il riconoscimento del formato di transcript passa da un ramo condizionale a un
  registro di harness. Un harness riconosciuto ma non misurabile produce zero chiamate
  invece di una stima: Antigravity non espone conteggi di token in nessun punto della
  sua cartella dati.
```

- [ ] **Step 2: Esegui i gate completi**

Run:
```bash
python -m pytest -q -W error && git diff --check && python scripts/verifica_segreti.py --tracked && python scripts/verifica_pubblicazione.py
```
Expected: `534+ passed`, exit 0 su tutti.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: registra il seam multi-harness nel changelog"
```

---

## Cosa questo piano NON copre

- **Parte B** (porta d'ingresso in linguaggio naturale) e **parte C** (esecuzione reale misurata): un piano ciascuno, e la B richiede prima una decisione che la specifica non fissa — quale fornitore e quale client, e come si configura la chiave. Senza quella decisione un piano conterrebbe segnaposto, che qui sono un difetto del piano.
- Cursor, OpenCode e OpenClaw: fuori ambito finché non esiste un transcript vero da cui leggerne lo schema.
