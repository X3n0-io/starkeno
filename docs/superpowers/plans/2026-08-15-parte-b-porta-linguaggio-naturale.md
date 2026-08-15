# Parte B — La porta d'ingresso in linguaggio naturale

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dare a Preflight un comando che trasforma testo libero in un Draft Blueprint valido, con assunzioni e domande aperte esplicite, usando una sola chiamata al modello più un solo retry di riparazione.

**Architecture:** Tre strati separati da confini netti. `preflight_interpret.py` contiene il contratto (`ModelClient`, un `Protocol`), il modello di uscita `Interpretation` e l'orchestrazione — è puro, testabile con un client finto, senza rete e senza chiave. `preflight_anthropic.py` è **l'unico modulo che importa `anthropic`** e l'unico che nomina le variabili d'ambiente. `preflight_cli.py` aggiunge il comando `interpret`, importando il client in modo pigro come già fa con `preflight_report`.

**Tech Stack:** Python 3.12–3.14, `anthropic` (SDK ufficiale), pydantic v2, pytest. Il modello è `claude-opus-5` con structured output.

## Decisione a monte, già presa

Presa il 15/08/2026 dopo misura, **non rinegoziabile in fase di piano**:

| | Scelta | Perché |
|---|---|---|
| Fornitore | **Anthropic** | Structured output più percorso credenziali via profilo `ant` |
| Client | **SDK ufficiale**, non httpx | Lo schema del Blueprint contiene **53 occorrenze** di vincoli che gli structured output rifiutano (`minLength` ×26, `minimum` ×17, `pattern` ×7, `maximum` ×3); l'SDK li sposta nella `description` e li rivalida lato client. A mano servirebbe riscrivere quel walker ricorsivo |
| Variabile | **`ANTHROPIC_API_KEY`**, con **`STARKENO_ANTHROPIC_API_KEY`** prioritaria | La prima è «quella già presente nell'ambiente» della §3.3; la seconda separa chiave e budget per chi vuole |

Misure che non vanno ri-derivate: l'SDK aggiunge **3 pacchetti** (~1,23 MB) con wheel su **9/9** combinazioni della matrice CI; il costo per chiamata è **3–23 centesimi** e quindi **non è un criterio**; il prompt caching non farà risparmiare quasi nulla nell'uso normale (TTL 5 minuti, chiamate isolate) e paga **solo sul retry di riparazione**.

## Global Constraints

Copiati dalla specifica `docs/superpowers/specs/2026-08-14-multi-harness-e-preflight-esecuzione-design.md` §3, e da `AGENTS.md`.

- **Una sola chiamata al modello** nel percorso standard, e **un solo retry** di riparazione, soltanto quando l'uscita non valida.
- Il **preventivo** di token è dichiarato **prima** e il **consumo osservato dopo**, entrambi visibili all'utente. Il preventivo è una stima locale e va detto che lo è.
- Prompt di sistema e schema restano un **prefisso stabile**: niente timestamp, niente id di richiesta, niente metadati dinamici.
- **Nessuna chiave viene letta, scritta, registrata o stampata** da StarkEno sul percorso predefinito.
- **Va al modello soltanto il testo che l'utente passa al comando.** Niente transcript, niente database, niente percorsi assoluti, niente secondo cervello.
- Assenza di chiave o di rete **non è un errore da nascondere**: il comando lo dice e si ferma. Nessun ripiego che indovini un Blueprint senza modello.
- Il Draft **non viene simulato**: `analyze` continua a richiedere `--confirmed`.
- Hook, `report`, dashboard e `doctor` restano **offline**. `interpret` non parte mai da loro.
- Solo `starkeno/db.py` importa SQLAlchemy; nessuna migrazione, lo schema non cambia.
- I test **non fanno richieste di rete e non richiedono chiavi** (§8 della specifica).
- Ogni test deve avere una regressione concreta che lo renda rosso (invariante 13).
- Fixture sintetiche; mai transcript reali, chiavi vere o percorsi home nei file tracciati.
- Gate finali di ogni task: `python -m pytest -q -W error` e `git diff --check`.

## Struttura dei file

| File | Responsabilità |
|---|---|
| `starkeno/preflight_interpret.py` (nuovo) | `ModelClient` (Protocol), `ModelReply`, `ModelUsage`, `Interpretation`, `interpret_text()`, `estimate_tokens()`, `SYSTEM_PROMPT`. Puro: niente rete, niente ambiente, niente `anthropic`. |
| `starkeno/preflight_anthropic.py` (nuovo) | `AnthropicClient`, `build_client()`, `MissingCredentials`. **Unico** modulo che importa `anthropic` e che nomina le due variabili. |
| `starkeno/preflight_cli.py` (modifica) | Sottocomando `interpret`; import pigro del client. |
| `starkeno/diagnostica.py` (modifica) | `superficie_di_rete()`: dichiara l'unico comando che parla con la rete. |
| `tests/test_preflight_interpret.py` (nuovo) | Orchestrazione, retry, isolamento, purezza. Client finto. |
| `tests/test_preflight_anthropic.py` (nuovo) | Precedenza fra variabili e traduzione degli errori. Client SDK finto. |
| `pyproject.toml`, `requirements/ci.txt` | Dipendenza `anthropic`. |
| `README.md`, `CHANGELOG.md` | La correzione della promessa di rete, alla consegna. |

---

### Task 1: La dipendenza, e il confine che la contiene

**Files:**
- Modify: `pyproject.toml:13-23` (blocco `dependencies`)
- Modify: `requirements/ci.txt` (rigenerato, non a mano)
- Test: `tests/test_preflight_interpret.py` (nuovo)

**Interfaces:**
- Consumes: niente.
- Produces: la dipendenza `anthropic>=0.122,<1` dichiarata; il test di isolamento che ogni task successivo deve continuare a far passare.

**Perché prima:** il test di isolamento è la rete di tutto il resto. Scritto ora, fallisce solo se qualcuno importa `anthropic` fuori dal modulo previsto — cioè esattamente l'errore che rende Preflight non testabile senza rete.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_preflight_interpret.py
"""L'interprete: orchestrazione pura, e il confine che tiene fuori la rete."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


RADICE = Path(__file__).resolve().parent.parent
PACCHETTO = RADICE / "starkeno"

# L'unico modulo autorizzato a importare l'SDK e a nominare le variabili d'ambiente.
MODULO_CLIENT = "preflight_anthropic.py"


def moduli_importati(percorso: Path) -> set[str]:
    """I nomi dei moduli importati da un file, letti dall'AST.

    Non dal testo: una ricerca testuale di "anthropic" trova anche il commento che dice
    dove si puo' importare, e un test che fallisce sulla propria documentazione e'
    inservibile. Stessa tecnica di `tests/test_rules_primitives.py`.
    """
    albero = ast.parse(percorso.read_text(encoding="utf-8"))
    nomi: set[str] = set()
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Import):
            nomi.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nomi.add(nodo.module.split(".")[0])
    return nomi


def test_anthropic_e_dichiarato_come_dipendenza():
    testo = (RADICE / "pyproject.toml").read_text(encoding="utf-8")
    assert "anthropic" in testo, "l'SDK non e' dichiarato: l'installazione non lo avra'"


def test_solo_il_modulo_client_importa_lo_sdk():
    """Se l'SDK trapela altrove, il resto di Preflight smette di essere testabile
    senza rete e senza chiave — che e' il punto della \u00a73.3 della specifica."""
    colpevoli = []
    for modulo in sorted(PACCHETTO.glob("*.py")):
        if modulo.name == MODULO_CLIENT:
            continue
        if "anthropic" in moduli_importati(modulo):
            colpevoli.append(modulo.name)
    assert not colpevoli, "importano anthropic fuori dal client: %r" % colpevoli


def test_solo_il_modulo_client_nomina_le_variabili_della_chiave():
    """Il nome della variabile e' contratto pubblico: deve vivere in un posto solo,
    altrimenti cambiarlo significa cercarlo."""
    colpevoli = []
    for modulo in sorted(PACCHETTO.glob("*.py")):
        if modulo.name == MODULO_CLIENT:
            continue
        testo = modulo.read_text(encoding="utf-8")
        if "ANTHROPIC_API_KEY" in testo:
            colpevoli.append(modulo.name)
    assert not colpevoli, "nominano la variabile fuori dal client: %r" % colpevoli
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_preflight_interpret.py`
Expected: FAIL su `test_anthropic_e_dichiarato_come_dipendenza` con `AssertionError: l'SDK non e' dichiarato`. Gli altri due passano già (nessuno importa ancora niente): è corretto, sono lì per il futuro.

- [ ] **Step 3: Write minimal implementation**

In `pyproject.toml`, dentro `dependencies`, in ordine alfabetico dopo `alembic`:

```toml
dependencies = [
  "alembic>=1.13,<2",
  "anthropic>=0.122,<1",
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "mcp[cli]>=2,<3",
  "sqlalchemy>=2,<3",
  "httpx>=0.27,<1",
  "websockets>=13,<17",
  "pydantic>=2.9,<3",
  "PyYAML>=6,<7",
]
```

Poi rigenera il file di CI — **non modificarlo a mano**, l'intestazione dice che è autogenerato:

```bash
python -m piptools compile --extra=dev --output-file=requirements/ci.txt --strip-extras pyproject.toml
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
python -m pip install -c requirements/ci.txt -e ".[dev]" && python -m pytest -q tests/test_preflight_interpret.py && python -m pip check
```
Expected: PASS, 3 test. `pip check` esce 0. In `requirements/ci.txt` devono comparire `anthropic`, `jiter` e `docstring-parser` e nient'altro di nuovo: se ne compaiono altri, fermati e dillo — la misura del 15/08 diceva 3 pacchetti.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements/ci.txt tests/test_preflight_interpret.py
git commit -m "build: dichiara l'SDK Anthropic e il confine che lo contiene"
```

---

### Task 2: La prova del contratto — misurare tre cose invece di assumerle

**Files:**
- Create: `docs/verification/2026-08-15-parte-b-contratto-sdk.md`
- Nessun file di codice, nessun test.

**⚠ Questo task spende soldi veri: circa 2–5 centesimi.** È autorizzato perché la parte B *è* la superficie che parla con la rete, ed è molto più economico di scoprire queste tre cose dentro l'implementazione.

**Perché esiste:** la parte A ha trovato tre difetti solo strumentando il codice vero, dopo che i primi giri per ipotesi non avevano prodotto nulla. Tre cose di questo task **non sono documentate in modo affidabile** e verrebbero altrimenti indovinate:

1. Che eccezione solleva `anthropic.Anthropic()` quando **non c'è nessuna credenziale** — serve per il percorso «dillo e fermati» della §3.3.
2. Se `client.messages.parse(output_format=...)` **accetta** uno schema con i 53 vincoli non supportati, e **cosa fa** quando l'uscita è sintatticamente valida ma viola un validatore semantico di pydantic (per esempio `agent_id` che punta a un agente inesistente). Da questo dipende se il retry di riparazione può leggere un messaggio d'errore utile.
3. Il **consumo reale** di una interpretazione: token in ingresso, in uscita, e latenza. È il primo dato con cui tarare il preventivo del Task 5.

- [ ] **Step 1: Misura il comportamento senza credenziali**

In una shell **senza** `ANTHROPIC_API_KEY` né `STARKENO_ANTHROPIC_API_KEY` né profilo `ant` attivo:

```bash
python -c "
import anthropic, traceback
try:
    c = anthropic.Anthropic()
    c.messages.create(model='claude-opus-5', max_tokens=16,
                      messages=[{'role':'user','content':'ok'}])
except Exception as exc:
    print('TIPO:', type(exc).__module__ + '.' + type(exc).__name__)
    print('MESSAGGIO:', exc)
"
```

Annota **tipo esatto** ed **eventuale messaggio**, e soprattutto **se l'errore arriva alla costruzione o alla prima chiamata**. Serve al Task 4.

- [ ] **Step 2: Misura structured output e fallimento semantico**

```bash
python -c "
from starkeno.preflight_interpret import Interpretation
" 2>/dev/null || echo "atteso: Interpretation non esiste ancora, usa Blueprint"
```

`Interpretation` non esiste ancora, quindi prova con lo schema che esiste:

```bash
python -c "
import time, anthropic
from starkeno.preflight_schema import Blueprint

c = anthropic.Anthropic()
t0 = time.monotonic()
r = c.messages.parse(
    model='claude-opus-5', max_tokens=16000,
    output_config={'effort': 'medium'},
    output_format=Blueprint,
    system='Produci un Blueprint minimo valido. Un solo nodo llm, un agente, un modello.',
    messages=[{'role':'user','content':'Un agente scrive una nota di rilascio.'}],
)
print('LATENZA_S:', round(time.monotonic()-t0, 1))
print('USAGE:', r.usage)
print('PARSED_OK:', r.parsed_output is not None)
"
```

Annota: **lo schema e' stato accettato?** (se no, il messaggio del 400 dice quale vincolo), `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, e la latenza.

Poi provoca un fallimento **semantico**, chiedendo esplicitamente un riferimento rotto, e annota **se `parse()` solleva o restituisce `parsed_output=None`**, e quale messaggio d'errore è disponibile:

```bash
python -c "
import anthropic, traceback
from starkeno.preflight_schema import Blueprint

c = anthropic.Anthropic()
try:
    r = c.messages.parse(
        model='claude-opus-5', max_tokens=16000,
        output_config={'effort': 'low'},
        output_format=Blueprint,
        system='Produci un Blueprint.',
        messages=[{'role':'user','content':
                   'Un nodo con agent_id \"fantasma\", e NESSUN agente nella lista agents.'}],
    )
    print('NON HA SOLLEVATO. parsed_output:', r.parsed_output)
    print('TESTO:', [b.text for b in r.content if b.type == 'text'][:1])
except Exception as exc:
    print('TIPO:', type(exc).__module__ + '.' + type(exc).__name__)
    print('MESSAGGIO:', str(exc)[:600])
"
```

- [ ] **Step 3: Scrivi il verbale**

Crea `docs/verification/2026-08-15-parte-b-contratto-sdk.md` con la stessa forma del verbale della parte A: una tabella `Evidenza | Risultato`, poi le conseguenze per il codice. Deve rispondere a tre domande e a nient'altro:

- Senza credenziali, `Anthropic()` fallisce **dove** e con **quale eccezione**?
- `parse()` su fallimento semantico **solleva** o **restituisce `None`**? Che testo d'errore posso rimandare al modello nel retry?
- Quanti token e quanti secondi costa una interpretazione a `effort: medium`?

**Il verbale non deve contenere chiavi, prompt reali dell'utente, username o percorsi assoluti** — stessa regola dell'ultima riga del verbale della parte A.

- [ ] **Step 4: Commit**

```bash
git add docs/verification/2026-08-15-parte-b-contratto-sdk.md
git commit -m "docs: verbale del contratto SDK per la parte B"
```

---

### Task 3: L'interfaccia sottile e l'orchestrazione

**Files:**
- Create: `starkeno/preflight_interpret.py`
- Test: `tests/test_preflight_interpret.py` (aggiungere in fondo)

**Interfaces:**
- Consumes: `preflight_schema.Blueprint`, `preflight_service.normalize_draft`, `preflight_service.BlueprintInputError`.
- Produces:
  - `ModelUsage` — dataclass frozen: `input_tokens: int`, `output_tokens: int`, `cache_read_tokens: int = 0`, `cache_write_tokens: int = 0`.
  - `ModelReply` — dataclass frozen: `text: str`, `usage: ModelUsage`, `model: str`.
  - `ModelClient` — `Protocol` con `complete(*, system: str, schema: dict, user_text: str, previous: tuple[str, str] | None = None) -> ModelReply`.
  - `Interpretation` — modello pydantic frozen: `blueprint: Blueprint`, `assumptions: tuple[str, ...]`, `open_questions: tuple[str, ...]`.
  - `InterpretationResult` — dataclass frozen: `interpretation: Interpretation`, `usage: ModelUsage`, `repaired: bool`, `model: str`.
  - `InterpretationError(ValueError)`.
  - `SYSTEM_PROMPT: str`, `CHARACTERS_PER_TOKEN: float`.
  - `estimate_tokens(user_text: str) -> int`.
  - `interpret_text(user_text: str, *, client: ModelClient) -> InterpretationResult`.

**Perché `Interpretation` avvolge `Blueprint`:** la specifica chiede assunzioni e domande aperte accanto al Draft, e `Blueprint` ha `extra="forbid"` — aggiungerle lì cambierebbe un contratto immutabile. L'involucro le tiene fuori dallo schema del Blueprint e le fa comunque produrre dal modello in un colpo solo.

**Verificato il 15/08/2026 sull'involucro vero, non assunto:** produce 9.137 caratteri di schema (~2.600 token), 14 oggetti, **tutti** con `additionalProperties: false` — il requisito degli structured output arriva gratis da `FrozenModel`. Il round-trip `model_dump_json` → `Blueprint.model_validate_json` funziona. Un riferimento rotto viene respinto da pydantic con un `ValueError` leggibile, quindi il retry ha qualcosa da correggere. E — la ragione per cui `_rifiuta_measured` esiste come **codice** e non come sola istruzione nel prompt — un `provenance: "measured"` inventato **passa lo schema JSON senza obiezioni**: se non lo si controlla a mano, un numero inventato esce con l'aria di un numero osservato.

- [ ] **Step 1: Write the failing test**

```python
# in fondo a tests/test_preflight_interpret.py
import json  # noqa: E402

from starkeno import preflight_interpret as interprete  # noqa: E402
from starkeno.preflight_schema import load_blueprint  # noqa: E402


FIXTURE = RADICE / "tests" / "fixtures" / "preflight" / "minimal.json"


def _interpretazione(**modifiche) -> str:
    """Una risposta del modello ben formata, modificabile per rompere un pezzo solo."""
    blueprint = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blueprint.update(modifiche)
    return json.dumps({
        "blueprint": blueprint,
        "assumptions": ["Il revisore e' una persona."],
        "open_questions": ["Quante modifiche entrano di solito nella nota?"],
    })


class ClientFinto:
    """Un `ModelClient` che risponde da un copione. Non tocca la rete."""

    def __init__(self, *risposte: str) -> None:
        self.risposte = list(risposte)
        self.chiamate: list[dict] = []

    def complete(self, *, system, schema, user_text, previous=None):
        self.chiamate.append({"system": system, "schema": schema,
                              "user_text": user_text, "previous": previous})
        testo = self.risposte.pop(0)
        return interprete.ModelReply(
            text=testo,
            usage=interprete.ModelUsage(input_tokens=100, output_tokens=200),
            model="modello-finto",
        )


def test_una_sola_chiamata_quando_l_uscita_e_valida():
    """Il vincolo economico della \u00a73.2 e' il punto, non un dettaglio."""
    client = ClientFinto(_interpretazione())

    esito = interprete.interpret_text("un agente scrive una nota", client=client)

    assert len(client.chiamate) == 1
    assert esito.repaired is False
    assert esito.interpretation.blueprint.goal.id == "goal-release"
    assert esito.interpretation.open_questions


def test_un_solo_retry_di_riparazione_e_il_secondo_fallimento_e_dichiarato():
    """Due fallimenti non diventano tre chiamate: si dichiara e ci si ferma."""
    client = ClientFinto("{non e' json", "nemmeno questo")

    with pytest.raises(interprete.InterpretationError) as errore:
        interprete.interpret_text("testo", client=client)

    assert len(client.chiamate) == 2, "il retry deve essere UNO"
    assert "riparazione" in str(errore.value).lower()


def test_il_retry_riceve_l_uscita_precedente_e_l_errore():
    """Un retry che non dice cosa e' andato storto e' una seconda estrazione a caso."""
    client = ClientFinto("{rotto", _interpretazione())

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is True
    precedente = client.chiamate[1]["previous"]
    assert precedente is not None
    uscita, errore = precedente
    assert uscita == "{rotto"
    assert errore, "il retry non sa cosa correggere"


def test_il_draft_resta_non_confermato():
    """L'interpretazione di un modello non diventa mai verita' strutturata da sola."""
    client = ClientFinto(_interpretazione(confirmed=True, revision=3))

    esito = interprete.interpret_text("testo", client=client)

    assert esito.interpretation.blueprint.confirmed is False


def test_un_riferimento_rotto_provoca_la_riparazione_non_un_errore_interno():
    """Il validatore semantico di pydantic e' cio' che lo schema JSON non puo' imporre:
    e' il caso d'uso vero del retry."""
    rotto = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rotto["nodes"][0]["agent_id"] = "fantasma"
    client = ClientFinto(
        json.dumps({"blueprint": rotto, "assumptions": [], "open_questions": []}),
        _interpretazione(),
    )

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is True


def test_un_provenance_measured_viene_rifiutato():
    """Un modello non ha misurato niente. `measured` da' a un numero inventato l'aria
    di un numero osservato, che e' il fallimento peggiore per questo progetto."""
    bugiardo = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bugiardo["nodes"][0]["budget"]["output"]["provenance"] = "measured"
    client = ClientFinto(
        json.dumps({"blueprint": bugiardo, "assumptions": [], "open_questions": []}),
        _interpretazione(),
    )

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is True, "un `measured` inventato deve essere corretto"


def test_il_consumo_somma_le_due_chiamate():
    client = ClientFinto("{rotto", _interpretazione())

    esito = interprete.interpret_text("testo", client=client)

    assert esito.usage.input_tokens == 200
    assert esito.usage.output_tokens == 400


def test_il_prefisso_e_stabile_fra_chiamate_diverse():
    """Niente timestamp o id: un prefisso che cambia rompe la cache del fornitore,
    e la cache e' cio' che rende quasi gratis il retry di riparazione."""
    primo = ClientFinto(_interpretazione())
    secondo = ClientFinto(_interpretazione())

    interprete.interpret_text("testo A", client=primo)
    interprete.interpret_text("testo B", client=secondo)

    assert primo.chiamate[0]["system"] == secondo.chiamate[0]["system"]
    assert primo.chiamate[0]["schema"] == secondo.chiamate[0]["schema"]


def test_il_preventivo_e_una_stima_dichiarata_non_una_misura():
    assert interprete.estimate_tokens("") > 0, "lo schema e il prompt costano comunque"
    assert interprete.estimate_tokens("x" * 3500) > interprete.estimate_tokens("x")


def test_l_interprete_non_tocca_rete_ambiente_ne_orologio():
    """Purezza: e' cio' che rende questi test eseguibili senza chiave (\u00a78)."""
    vietati = {"os", "anthropic", "httpx", "requests", "socket", "time", "datetime"}
    trovati = vietati & moduli_importati(PACCHETTO / "preflight_interpret.py")
    assert not trovati, "preflight_interpret importa %r" % sorted(trovati)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_preflight_interpret.py`
Expected: FAIL con `ModuleNotFoundError: No module named 'starkeno.preflight_interpret'`

- [ ] **Step 3: Write minimal implementation**

```python
# starkeno/preflight_interpret.py
"""Da testo libero a Draft Blueprint: contratto, prompt e orchestrazione.

**Qui non c'e' rete, non c'e' ambiente e non c'e' orologio.** Il client e' un
`Protocol`, quindi tutto questo modulo si prova con un oggetto finto: e' la ragione per
cui la \u00a73.3 della specifica chiede un'interfaccia sottile, e la ragione per cui i test
della parte B non spendono soldi e non richiedono una chiave.

Il vincolo economico della \u00a73.2 vive qui e in nessun altro posto: **una** chiamata nel
percorso standard, **un solo** retry, e soltanto se l'uscita non valida.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from starkeno.preflight_schema import Blueprint, FrozenModel
from starkeno.preflight_service import BlueprintInputError, normalize_draft


class InterpretationError(ValueError):
    """L'interpretazione non ha prodotto un Blueprint valido, nemmeno dopo il retry."""


@dataclass(frozen=True)
class ModelUsage:
    """Il consumo osservato. Sempre misurato dalla risposta, mai stimato."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def piu(self, altro: ModelUsage) -> ModelUsage:
        return ModelUsage(
            input_tokens=self.input_tokens + altro.input_tokens,
            output_tokens=self.output_tokens + altro.output_tokens,
            cache_read_tokens=self.cache_read_tokens + altro.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + altro.cache_write_tokens,
        )


@dataclass(frozen=True)
class ModelReply:
    text: str
    usage: ModelUsage
    model: str


class ModelClient(Protocol):
    """Il minimo che serve per interpretare un testo. Deliberatamente povero.

    `previous` porta la coppia (uscita rifiutata, errore di validazione) e vale solo
    per il retry: e' l'unica forma di conversazione che la \u00a73.2 ammette.
    """

    def complete(
        self,
        *,
        system: str,
        schema: dict,
        user_text: str,
        previous: tuple[str, str] | None = None,
    ) -> ModelReply: ...


class Interpretation(FrozenModel):
    """Il Draft piu' cio' che il modello ha dovuto assumere per produrlo.

    Assunzioni e domande stanno qui e non dentro `Blueprint`, che ha `extra="forbid"`
    ed e' un contratto immutabile: allargarlo per comodita' di questo comando
    significherebbe cambiare lo schema di tutti gli altri.

    Eredita `FrozenModel` da `preflight_schema`, quindi `frozen=True` e `extra="forbid"`
    arrivano da li': lo schema che il modello riceve avra' `additionalProperties: false`
    su ogni oggetto, che gli structured output richiedono.
    """

    blueprint: Blueprint
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()


# Stima locale, non una misura. Ricalibrala dai numeri del verbale del Task 2.
CHARACTERS_PER_TOKEN = 3.5

SYSTEM_PROMPT = """You turn a free-text description of an agent workflow into a Draft \
Blueprint that validates against the given JSON schema.

Rules you must not break:

- Never claim a number was measured. Every estimate carries a `provenance` of \
"declared" when the user stated it, "inferred" when you derived it from what they \
wrote, or "default" when you had nothing to go on. "measured" is reserved for numbers \
StarkEno observed itself and is never correct in your output.
- Set `confidence` honestly. "low" is the right answer more often than not.
- Every assumption you had to make goes in `assumptions`, in the user's own terms.
- Everything you could not determine goes in `open_questions`, phrased so a person can \
answer it in one line.
- Prefer a small honest Blueprint over a large invented one. Do not add nodes, agents, \
tools or models the text does not support.
- `confirmed` is always false. `revision` is always 1 and `parent_revision` is null.
- Prices you do not know stay null. Do not guess them.
"""


def estimate_tokens(user_text: str) -> int:
    """Preventivo **stimato** dei token in ingresso, calcolato in locale.

    Non chiama `count_tokens`: sarebbe una seconda richiesta di rete prima della sola
    chiamata che la \u00a73.2 concede. Chi la mostra deve dire che e' una stima — un numero
    stimato presentato come misurato e' esattamente cio' che questo progetto rifiuta.
    """
    caratteri = len(SYSTEM_PROMPT) + len(_schema_text()) + len(user_text)
    return int(caratteri / CHARACTERS_PER_TOKEN) + 1


def _schema_text() -> str:
    import json

    return json.dumps(interpretation_schema(), sort_keys=True, separators=(",", ":"))


def interpretation_schema() -> dict:
    """Lo schema che il modello deve rispettare. Stabile: nessun dato dinamico."""
    return Interpretation.model_json_schema()


def _rifiuta_measured(interpretazione: Interpretation) -> None:
    """Un modello non misura niente. `measured` renderebbe un numero inventato
    indistinguibile da uno osservato, e su questo il progetto non transige."""
    for nodo in interpretazione.blueprint.nodes:
        budget = nodo.budget
        for nome in ("instructions", "dynamic_context", "output", "cacheable_fraction",
                     "latency_ms", "retry_probability"):
            stima = getattr(budget, nome)
            if stima.provenance == "measured":
                raise ValueError(
                    f"node {nodo.id}: {nome} dichiara provenance 'measured', ma nulla "
                    "e' stato misurato. Usa 'declared', 'inferred' o 'default'."
                )


def _leggi(testo: str) -> Interpretation:
    import json

    dati = json.loads(testo)
    interpretazione = Interpretation.model_validate(dati)
    normalizzato = normalize_draft(
        interpretazione.blueprint.model_dump_json(), format_hint="json"
    )
    interpretazione = interpretazione.model_copy(update={"blueprint": normalizzato})
    _rifiuta_measured(interpretazione)
    return interpretazione


@dataclass(frozen=True)
class InterpretationResult:
    interpretation: Interpretation
    usage: ModelUsage
    repaired: bool
    model: str


def interpret_text(user_text: str, *, client: ModelClient) -> InterpretationResult:
    """Una chiamata; se l'uscita non valida, **una** riparazione; poi si dichiara.

    Non esiste un terzo tentativo e non esiste un ripiego che indovini un Blueprint
    senza modello: la \u00a73.3 lo vieta, perche' un Draft inventato in silenzio e' peggio
    di un comando che si ferma.
    """
    schema = interpretation_schema()
    prima = client.complete(system=SYSTEM_PROMPT, schema=schema, user_text=user_text)
    try:
        return InterpretationResult(
            interpretation=_leggi(prima.text),
            usage=prima.usage,
            repaired=False,
            model=prima.model,
        )
    except (ValueError, BlueprintInputError) as primo_errore:
        motivo = " ".join(str(primo_errore).splitlines())[:2000]

    seconda = client.complete(
        system=SYSTEM_PROMPT,
        schema=schema,
        user_text=user_text,
        previous=(prima.text, motivo),
    )
    consumo = prima.usage.piu(seconda.usage)
    try:
        return InterpretationResult(
            interpretation=_leggi(seconda.text),
            usage=consumo,
            repaired=True,
            model=seconda.model,
        )
    except (ValueError, BlueprintInputError) as secondo_errore:
        raise InterpretationError(
            "L'interpretazione non ha prodotto un Blueprint valido nemmeno dopo la "
            f"riparazione. Primo errore: {motivo}. Secondo errore: {secondo_errore}"
        ) from secondo_errore
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_preflight_interpret.py -W error`
Expected: PASS, 13 test. Se `test_l_interprete_non_tocca_rete_ambiente_ne_orologio` fallisce su `json`, sposta l'import di `json` in cima al modulo e togli `json` dai vietati: non è nella lista.

- [ ] **Step 5: Commit**

```bash
git add starkeno/preflight_interpret.py tests/test_preflight_interpret.py
git commit -m "feat: interfaccia sottile e orchestrazione dell'interprete Preflight"
```

---

### Task 4: Il client Anthropic — l'unico modulo che vede l'SDK e le variabili

**Files:**
- Create: `starkeno/preflight_anthropic.py`
- Test: `tests/test_preflight_anthropic.py`

**Interfaces:**
- Consumes: `preflight_interpret.ModelClient`, `ModelReply`, `ModelUsage`.
- Produces:
  - `VARIABILI: tuple[str, str]` — `("STARKENO_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")`, **in ordine di precedenza**.
  - `MODELLO: str` — `"claude-opus-5"`.
  - `MissingCredentials(RuntimeError)`.
  - `NetworkUnavailable(RuntimeError)`.
  - `variabile_trovata(ambiente: dict) -> str | None`.
  - `build_client(*, sdk=None) -> AnthropicClient`.
  - `AnthropicClient` — implementa `ModelClient`.

**⚠ Prima di scrivere:** apri `docs/verification/2026-08-15-parte-b-contratto-sdk.md` del Task 2 e usa **il tipo di eccezione che hai misurato**, non quello che sembra plausibile.

**La proprietà da preservare, e il suo limite onesto:** sul percorso predefinito StarkEno **non legge il valore della chiave** — costruisce `Anthropic()` a zero argomenti e lascia che sia l'SDK a risolvere `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, un profilo di `ant auth login` o il default su disco. Sul percorso `STARKENO_ANTHROPIC_API_KEY` StarkEno **deve** leggere il valore, perché l'SDK non conosce quel nome: è il prezzo di avere una via d'uscita, e va detto invece che nascosto.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_preflight_anthropic.py
"""Il client: precedenza fra le variabili, e errori tradotti invece che nascosti."""
from __future__ import annotations

import pytest

from starkeno import preflight_anthropic as client_modulo
from starkeno import preflight_interpret as interprete


class SdkFinto:
    """Sta al posto di `anthropic.Anthropic`, e registra come e' stato costruito."""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.chiamate: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.chiamate.append(kwargs)

        class Uso:
            input_tokens = 1200
            output_tokens = 800
            cache_read_input_tokens = 0
            cache_creation_input_tokens = 0

        class Blocco:
            type = "text"
            text = '{"blueprint": {}, "assumptions": [], "open_questions": []}'

        class Risposta:
            content = [Blocco()]
            usage = Uso()
            model = "claude-opus-5"

        return Risposta()


def test_starkeno_ha_la_precedenza_sulla_variabile_condivisa():
    ambiente = {"ANTHROPIC_API_KEY": "a", "STARKENO_ANTHROPIC_API_KEY": "b"}

    assert client_modulo.variabile_trovata(ambiente) == "STARKENO_ANTHROPIC_API_KEY"


def test_la_variabile_condivisa_basta_da_sola():
    assert client_modulo.variabile_trovata({"ANTHROPIC_API_KEY": "a"}) == "ANTHROPIC_API_KEY"


def test_nessuna_variabile_non_significa_nessuna_credenziale():
    """L'SDK risolve anche i profili di `ant auth login`: rispondere 'manca la chiave'
    a chi ne ha una sarebbe un falso negativo sicuro di se', cioe' la forma esatta dei
    tre difetti trovati nella parte A."""
    assert client_modulo.variabile_trovata({}) is None


def test_sul_percorso_predefinito_non_passiamo_la_chiave_all_sdk():
    """Se non gliela passiamo, non l'abbiamo letta: la \u00a73.3 chiede esattamente questo."""
    costruiti = []

    def fabbrica(**kwargs):
        costruiti.append(kwargs)
        return SdkFinto(**kwargs)

    client_modulo.build_client(sdk=fabbrica, ambiente={"ANTHROPIC_API_KEY": "segreto"})

    assert costruiti == [{}], "abbiamo letto e ripassato la chiave senza bisogno"


def test_con_la_variabile_starkeno_la_chiave_viene_passata_esplicitamente():
    costruiti = []

    def fabbrica(**kwargs):
        costruiti.append(kwargs)
        return SdkFinto(**kwargs)

    client_modulo.build_client(
        sdk=fabbrica, ambiente={"STARKENO_ANTHROPIC_API_KEY": "mia"}
    )

    assert costruiti == [{"api_key": "mia"}]


def test_il_client_traduce_la_risposta_in_ModelReply():
    client = client_modulo.AnthropicClient(SdkFinto())

    risposta = client.complete(system="s", schema={"type": "object"}, user_text="t")

    assert isinstance(risposta, interprete.ModelReply)
    assert risposta.usage.input_tokens == 1200
    assert risposta.usage.output_tokens == 800


def test_il_retry_manda_l_uscita_rifiutata_e_l_errore():
    sdk = SdkFinto()
    client = client_modulo.AnthropicClient(sdk)

    client.complete(system="s", schema={"type": "object"}, user_text="t",
                    previous=("{rotto", "manca una parentesi"))

    messaggi = sdk.chiamate[0]["messages"]
    assert len(messaggi) == 3, "servono utente, assistente rifiutato e correzione"
    assert "{rotto" in str(messaggi[1])
    assert "manca una parentesi" in str(messaggi[2])


def test_il_prompt_non_contiene_dati_locali():
    """Va al modello soltanto il testo del comando: mai percorsi, mai transcript."""
    sdk = SdkFinto()
    client = client_modulo.AnthropicClient(sdk)

    client.complete(system="s", schema={"type": "object"}, user_text="ciao")

    inviato = str(sdk.chiamate[0])
    assert "ciao" in inviato
    for vietato in ("C:\\\\Users", "/home/", ".starkeno", "transcript"):
        assert vietato not in inviato


def test_una_chiave_assente_diventa_un_errore_che_si_puo_spiegare():
    def fabbrica(**kwargs):
        raise RuntimeError("could not resolve authentication")

    with pytest.raises(client_modulo.MissingCredentials) as errore:
        client_modulo.build_client(sdk=fabbrica, ambiente={})

    assert "ANTHROPIC_API_KEY" in str(errore.value), "non dice come rimediare"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_preflight_anthropic.py`
Expected: FAIL con `ModuleNotFoundError: No module named 'starkeno.preflight_anthropic'`

- [ ] **Step 3: Write minimal implementation**

Il `except Exception` in `build_client` qui sotto è **deliberatamente largo solo finché non hai il verbale**: restringilo al tipo che il Task 2 ha **misurato**, altrimenti un errore di rete o un bug di programmazione verrebbero riportati all'utente come «manca la chiave», che è una diagnosi sbagliata detta con sicurezza.

```python
# starkeno/preflight_anthropic.py
"""L'unico modulo di StarkEno che importa l'SDK Anthropic e nomina la chiave.

Il confine e' verificato da `tests/test_preflight_interpret.py`: se l'import o il nome
della variabile compaiono altrove, quei test diventano rossi. Non e' pedanteria — e'
cio' che tiene il resto di Preflight provabile senza rete e senza chiave (\u00a73.3).

**Sul percorso predefinito StarkEno non legge il valore della chiave.** Costruisce
`Anthropic()` a zero argomenti e lascia risolvere all'SDK: variabile d'ambiente, token,
profilo di `ant auth login`, default su disco. Solo quando l'utente sceglie
`STARKENO_ANTHROPIC_API_KEY` — un nome che l'SDK non conosce — StarkEno deve leggerne il
valore per ripassarlo. E' il prezzo della via d'uscita, ed e' scritto qui perche' si
veda.
"""
from __future__ import annotations

import os

import anthropic

from starkeno.preflight_interpret import ModelClient, ModelReply, ModelUsage

# In ordine di precedenza: la prima che c'e' vince.
VARIABILI = ("STARKENO_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")

MODELLO = "claude-opus-5"
MAX_TOKENS = 16000
EFFORT = "medium"


class MissingCredentials(RuntimeError):
    """Nessuna credenziale utilizzabile. Si dichiara e ci si ferma (\u00a73.3)."""


class NetworkUnavailable(RuntimeError):
    """La rete non risponde. Nessun ripiego: un Draft indovinato sarebbe peggio."""


def variabile_trovata(ambiente: dict[str, str] | None = None) -> str | None:
    """Il nome della variabile impostata, mai il valore.

    `None` **non** significa "nessuna credenziale": l'SDK risolve anche i profili di
    `ant auth login`. Chi mostra questo risultato deve dirlo, altrimenti produce un
    falso negativo che ha l'aria di una diagnosi.
    """
    ambiente = os.environ if ambiente is None else ambiente
    for nome in VARIABILI:
        if ambiente.get(nome):
            return nome
    return None


def build_client(*, sdk=None, ambiente: dict[str, str] | None = None) -> AnthropicClient:
    """Costruisce il client. `sdk` esiste per i test e non ha altri usi."""
    fabbrica = anthropic.Anthropic if sdk is None else sdk
    ambiente = os.environ if ambiente is None else ambiente

    argomenti: dict[str, str] = {}
    proprio = ambiente.get("STARKENO_ANTHROPIC_API_KEY")
    if proprio:
        argomenti["api_key"] = proprio

    try:
        return AnthropicClient(fabbrica(**argomenti))
    except Exception as exc:  # tipo confermato dal verbale del Task 2
        raise MissingCredentials(
            "Nessuna credenziale Anthropic utilizzabile. Imposta ANTHROPIC_API_KEY, "
            "oppure STARKENO_ANTHROPIC_API_KEY per usarne una separata, oppure esegui "
            "`ant auth login`. StarkEno non legge, non salva e non stampa la chiave."
        ) from exc


class AnthropicClient:
    """Traduce il contratto povero di `ModelClient` nella forma dell'SDK."""

    def __init__(self, sdk) -> None:
        self._sdk = sdk

    def complete(
        self,
        *,
        system: str,
        schema: dict,
        user_text: str,
        previous: tuple[str, str] | None = None,
    ) -> ModelReply:
        messaggi: list[dict] = [{"role": "user", "content": user_text}]
        if previous is not None:
            rifiutata, errore = previous
            messaggi.append({"role": "assistant", "content": rifiutata})
            messaggi.append({
                "role": "user",
                "content": (
                    "Your previous output did not validate. Fix exactly this and "
                    f"return the whole object again:\n{errore}"
                ),
            })

        try:
            risposta = self._sdk.messages.create(
                model=MODELLO,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=messaggi,
                output_config={
                    "effort": EFFORT,
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.APIConnectionError as exc:
            raise NetworkUnavailable(
                "La rete non ha risposto. Il comando si ferma: StarkEno non indovina "
                "un Blueprint senza modello."
            ) from exc
        except anthropic.AuthenticationError as exc:
            raise MissingCredentials(
                "La credenziale e' stata rifiutata dal fornitore."
            ) from exc

        testo = next(
            (b.text for b in risposta.content if getattr(b, "type", None) == "text"), ""
        )
        uso = risposta.usage
        return ModelReply(
            text=testo,
            usage=ModelUsage(
                input_tokens=getattr(uso, "input_tokens", 0),
                output_tokens=getattr(uso, "output_tokens", 0),
                cache_read_tokens=getattr(uso, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(uso, "cache_creation_input_tokens", 0) or 0,
            ),
            model=getattr(risposta, "model", MODELLO),
        )


_: ModelClient = AnthropicClient(None)  # type: ignore[arg-type]
```

**Nota sullo schema:** `output_config.format` richiede uno schema senza i 53 vincoli che il Task 2 ha verificato. Se la prova ha mostrato che l'API li rifiuta, passa lo schema attraverso il trasformatore dell'SDK **prima** di costruire la richiesta, e scrivi nel modulo da dove viene:

```python
from anthropic.lib._parse._transform import transform_schema  # percorso privato: vedi verbale
```

Se il verbale dice invece che `messages.parse(output_format=Interpretation)` funziona e solleva un errore leggibile, usa quello: è API pubblica e non dipende da un modulo privato.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_preflight_anthropic.py tests/test_preflight_interpret.py -W error`
Expected: PASS. I test di isolamento del Task 1 devono restare verdi: `preflight_anthropic.py` è l'unico escluso.

- [ ] **Step 5: Commit**

```bash
git add starkeno/preflight_anthropic.py tests/test_preflight_anthropic.py
git commit -m "feat: client Anthropic isolato per l'interprete Preflight"
```

---

### Task 5: Il comando `preflight interpret`

**Files:**
- Modify: `starkeno/preflight_cli.py` (`_parser()` righe 38-56; `main()` righe 77-89; nuove funzioni in fondo)
- Test: `tests/test_preflight_cli.py` (aggiungere in fondo)

**Interfaces:**
- Consumes: `preflight_interpret.interpret_text`, `estimate_tokens`, `InterpretationError`; `preflight_anthropic.build_client`, `MissingCredentials`, `NetworkUnavailable`.
- Produces: `starkeno preflight interpret --input <file> --output <file> --format {json,yaml}`; opzionale `--dry-run` che stampa solo il preventivo e **non chiama il modello**.

**L'import dell'SDK deve restare pigro**, dentro `_run_interpret`, come già fa `_run_analyze` con `preflight_report` alla riga 124. Un import in cima farebbe pagare l'SDK anche a `draft`, che è offline.

- [ ] **Step 1: Write the failing test**

```python
# in fondo a tests/test_preflight_cli.py
from starkeno import preflight_cli  # noqa: E402
from starkeno import preflight_interpret as interprete  # noqa: E402


def _risposta_valida() -> str:
    payload = json.loads(MINIMAL_BLUEPRINT)
    return json.dumps({"blueprint": payload,
                       "assumptions": ["Il revisore e' una persona."],
                       "open_questions": ["Quante modifiche per nota?"]})


class _ClientDiProva:
    def __init__(self, testo: str) -> None:
        self._testo = testo

    def complete(self, *, system, schema, user_text, previous=None):
        return interprete.ModelReply(
            text=self._testo,
            usage=interprete.ModelUsage(input_tokens=1234, output_tokens=567),
            model="claude-opus-5",
        )


def test_interpret_scrive_un_draft_e_mostra_preventivo_e_consuntivo(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        preflight_cli, "_costruisci_client", lambda: _ClientDiProva(_risposta_valida())
    )
    sorgente = tmp_path / "note.md"
    sorgente.write_text("Un agente scrive la nota di rilascio.", encoding="utf-8")
    destinazione = tmp_path / "draft.json"

    codice = main(["interpret", "--input", str(sorgente),
                   "--output", str(destinazione), "--format", "json"])

    assert codice == 0
    uscita = capsys.readouterr().out
    assert "stima" in uscita.lower(), "il preventivo deve dichiararsi stima"
    assert "1234" in uscita and "567" in uscita, "il consumo osservato non e' mostrato"
    scritto = load_blueprint(destinazione.read_text(encoding="utf-8"), format_hint="json")
    assert scritto.confirmed is False


def test_interpret_stampa_assunzioni_e_domande_aperte(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        preflight_cli, "_costruisci_client", lambda: _ClientDiProva(_risposta_valida())
    )
    sorgente = tmp_path / "note.md"
    sorgente.write_text("testo", encoding="utf-8")

    main(["interpret", "--input", str(sorgente),
          "--output", str(tmp_path / "d.json"), "--format", "json"])

    uscita = capsys.readouterr().out
    assert "Il revisore e' una persona." in uscita
    assert "Quante modifiche per nota?" in uscita


def test_dry_run_non_chiama_il_modello(tmp_path, monkeypatch, capsys):
    """Chi vuole sapere quanto costa deve poterlo sapere senza spendere."""
    def esplodi():
        raise AssertionError("--dry-run non deve costruire il client")

    monkeypatch.setattr(preflight_cli, "_costruisci_client", esplodi)
    sorgente = tmp_path / "note.md"
    sorgente.write_text("testo", encoding="utf-8")

    codice = main(["interpret", "--input", str(sorgente),
                   "--output", str(tmp_path / "d.json"), "--format", "json",
                   "--dry-run"])

    assert codice == 0
    assert "stima" in capsys.readouterr().out.lower()
    assert not (tmp_path / "d.json").exists()


def test_senza_credenziali_il_comando_lo_dice_e_si_ferma(tmp_path, monkeypatch, capsys):
    """Nessun ripiego: un Draft indovinato in silenzio e' peggio di un errore."""
    from starkeno.preflight_anthropic import MissingCredentials

    def senza():
        raise MissingCredentials("Nessuna credenziale Anthropic utilizzabile.")

    monkeypatch.setattr(preflight_cli, "_costruisci_client", senza)
    sorgente = tmp_path / "note.md"
    sorgente.write_text("testo", encoding="utf-8")

    codice = main(["interpret", "--input", str(sorgente),
                   "--output", str(tmp_path / "d.json"), "--format", "json"])

    assert codice == 2
    assert "credenziale" in capsys.readouterr().err.lower()
    assert not (tmp_path / "d.json").exists(), "non deve restare un file a meta'"


def test_una_interpretazione_irreparabile_e_dichiarata(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        preflight_cli, "_costruisci_client", lambda: _ClientDiProva("{rotto")
    )
    sorgente = tmp_path / "note.md"
    sorgente.write_text("testo", encoding="utf-8")

    codice = main(["interpret", "--input", str(sorgente),
                   "--output", str(tmp_path / "d.json"), "--format", "json"])

    assert codice == 2
    assert "riparazione" in capsys.readouterr().err.lower()


def test_interpret_non_importa_l_sdk_finche_non_serve():
    """`draft` e `analyze` restano offline e non pagano l'import dell'SDK."""
    import ast

    albero = ast.parse(
        (Path(preflight_cli.__file__)).read_text(encoding="utf-8")
    )
    for nodo in albero.body:  # solo il livello superiore
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            testo = ast.unparse(nodo)
            assert "anthropic" not in testo, "import dell'SDK in cima: %s" % testo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_preflight_cli.py -k interpret`
Expected: FAIL con `AttributeError: module 'starkeno.preflight_cli' has no attribute '_costruisci_client'`

- [ ] **Step 3: Write minimal implementation**

In `_parser()`, dopo il blocco `analyze` e prima di `return parser`:

```python
    interpret = commands.add_parser(
        "interpret", help="interpreta testo libero in un Draft Blueprint"
    )
    interpret.add_argument("--input", type=Path)
    interpret.add_argument("--format", choices=("json", "yaml"), required=True)
    interpret.add_argument("--output", type=Path, required=True)
    interpret.add_argument(
        "--dry-run",
        action="store_true",
        help="mostra solo il preventivo, senza chiamare il modello",
    )
```

In `main()`, sostituisci il blocco di dispatch delle righe 77-89:

```python
    try:
        if arguments.command == "draft":
            return _run_draft(arguments)
        if arguments.command == "interpret":
            return _run_interpret(arguments)
        return _run_analyze(arguments)
    except _UsageError as exc:
        _print_user_error(exc)
        return 2
    except (OSError, UnicodeError):
        _print_user_error(_UsageError("operazione I/O locale non riuscita"))
        return 2
    except Exception:
        print("Errore interno durante preflight.", file=sys.stderr)
        return 1
```

In fondo al file:

```python
def _costruisci_client():
    """Seam sostituibile nei test, e unico punto in cui l'SDK viene importato.

    L'import e' pigro di proposito: `draft` e `analyze` sono offline e non devono
    pagare il caricamento di un SDK che non useranno.
    """
    from starkeno.preflight_anthropic import build_client

    return build_client()


def _run_interpret(arguments: argparse.Namespace) -> int:
    from starkeno.preflight_interpret import (
        InterpretationError,
        estimate_tokens,
        interpret_text,
    )

    destinazione = arguments.output.resolve()
    sorgente = arguments.input.resolve() if arguments.input is not None else None
    if sorgente is not None and sorgente == destinazione:
        raise _UsageError("La destinazione di output non puo coincidere con l'input")
    testo = sys.stdin.read() if sorgente is None else sorgente.read_text(encoding="utf-8")
    if not testo.strip():
        raise _UsageError("il testo da interpretare e vuoto")

    preventivo = estimate_tokens(testo)
    print(f"Preventivo (stima locale, non una misura): ~{preventivo} token in ingresso.")
    print("Al modello va solo il testo che hai passato a questo comando.")
    if arguments.dry_run:
        print("--dry-run: nessuna chiamata effettuata.")
        return 0

    from starkeno.preflight_anthropic import MissingCredentials, NetworkUnavailable

    try:
        client = _costruisci_client()
        esito = interpret_text(testo, client=client)
    except (MissingCredentials, NetworkUnavailable) as exc:
        raise _UsageError(str(exc)) from exc
    except InterpretationError as exc:
        raise _UsageError(str(exc)) from exc

    scritto = _write_blueprint_atomic(
        esito.interpretation.blueprint,
        destinazione,
        format=arguments.format,
        source_path=sorgente,
    )
    consumo = esito.usage
    print(
        f"Consumo osservato: {consumo.input_tokens} token in ingresso, "
        f"{consumo.output_tokens} in uscita ({esito.model})."
    )
    scarto = consumo.input_tokens - preventivo
    print(f"Scarto fra stima e misura in ingresso: {scarto:+d} token.")
    if esito.repaired:
        print("La prima uscita non validava: e' servita una riparazione.")
    for assunzione in esito.interpretation.assumptions:
        print(f"Assunzione: {assunzione}")
    for domanda in esito.interpretation.open_questions:
        print(f"Domanda aperta: {domanda}")
    print(f"Draft salvato: {scritto}")
    print("Non e' stato simulato: `analyze --confirmed` resta un passo separato.")
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_preflight_cli.py -W error`
Expected: PASS, i test esistenti più 6 nuovi.

- [ ] **Step 5: Commit**

```bash
git add starkeno/preflight_cli.py tests/test_preflight_cli.py
git commit -m "feat: comando preflight interpret con preventivo e consuntivo"
```

---

### Task 6: `doctor` dichiara l'unica superficie di rete

**Files:**
- Modify: `starkeno/diagnostica.py`
- Test: `tests/test_diagnostica.py` (aggiungere in fondo)

**Interfaces:**
- Consumes: `preflight_anthropic.VARIABILI` — **solo i nomi**, mai i valori. `diagnostica` non deve importare `anthropic`: importa la costante da un modulo che sì, quindi l'import va fatto **dentro la funzione**, altrimenti `doctor` carica l'SDK e smette di essere offline.
- Produces: `diagnostica.superficie_di_rete(ambiente: dict | None = None) -> tuple[str, str | None, str]` — `(comando, variabile_trovata, nota)`.

**La trappola, esplicita:** «nessuna variabile impostata» **non** significa «nessuna credenziale», perché l'SDK risolve anche i profili di `ant auth login`. Un `doctor` che dicesse «manca la chiave» a chi ce l'ha produrrebbe un falso negativo sicuro di sé — la stessa forma dei tre difetti trovati nella parte A.

- [ ] **Step 1: Write the failing test**

```python
# in fondo a tests/test_diagnostica.py
def test_doctor_nomina_l_unico_comando_che_parla_con_la_rete():
    from starkeno import diagnostica

    comando, variabile, nota = diagnostica.superficie_di_rete({})

    assert "interpret" in comando
    assert variabile is None
    assert "profilo" in nota.lower(), (
        "senza questa nota, 'nessuna variabile' si legge come 'nessuna credenziale'")


def test_doctor_nomina_la_variabile_trovata_e_mai_il_valore():
    from starkeno import diagnostica

    # Deliberatamente non somigliante a una chiave vera: questo file e' pubblico, e una
    # finta chiave in un repo pubblico costa a qualcuno il tempo di verificare che sia finta.
    ambiente = {"ANTHROPIC_API_KEY": "VALORE-FINTO-NON-DEVE-USCIRE"}
    risultato = diagnostica.superficie_di_rete(ambiente)
    _, variabile, _ = risultato

    assert variabile == "ANTHROPIC_API_KEY"
    assert "NON-DEVE-USCIRE" not in " ".join(str(pezzo) for pezzo in risultato), (
        "il valore della chiave e' finito nell'uscita di doctor")


def test_doctor_rispetta_la_precedenza_di_starkeno():
    from starkeno import diagnostica

    _, variabile, _ = diagnostica.superficie_di_rete(
        {"ANTHROPIC_API_KEY": "a", "STARKENO_ANTHROPIC_API_KEY": "b"})

    assert variabile == "STARKENO_ANTHROPIC_API_KEY"


def test_diagnostica_resta_offline():
    """`doctor` non deve caricare l'SDK: e' un comando che non parla con la rete."""
    import ast
    from pathlib import Path

    import starkeno.diagnostica as modulo

    albero = ast.parse(Path(modulo.__file__).read_text(encoding="utf-8"))
    for nodo in albero.body:
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            assert "anthropic" not in ast.unparse(nodo)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_diagnostica.py -k "rete or offline or precedenza"`
Expected: FAIL con `AttributeError: module 'starkeno.diagnostica' has no attribute 'superficie_di_rete'`

- [ ] **Step 3: Write minimal implementation**

```python
# in starkeno/diagnostica.py
COMANDO_DI_RETE = "starkeno preflight interpret"


def superficie_di_rete(
    ambiente: dict[str, str] | None = None,
) -> tuple[str, str | None, str]:
    """L'unico comando che manda dati fuori, e se una credenziale e' configurata.

    Restituisce il **nome** della variabile trovata, mai il suo valore.

    `None` non vuol dire "nessuna credenziale": l'SDK risolve anche i profili di
    `ant auth login`. Dire "manca la chiave" a chi ne ha una sarebbe un falso negativo
    sicuro di se', ed e' esattamente la forma dei difetti che la prova live della parte A
    ha trovato. La nota esiste per impedire quella lettura.
    """
    import os

    from starkeno.preflight_anthropic import VARIABILI

    ambiente = os.environ if ambiente is None else ambiente
    trovata = next((nome for nome in VARIABILI if ambiente.get(nome)), None)
    if trovata is not None:
        nota = (
            f"{trovata} e' impostata. StarkEno non ne legge, salva ne' stampa il valore."
        )
    else:
        nota = (
            "Nessuna delle due variabili e' impostata. Questo non significa che manchi "
            "una credenziale: l'SDK usa anche un profilo di `ant auth login`. Se il "
            "comando serve e non parte, lo dira' lui."
        )
    return COMANDO_DI_RETE, trovata, nota
```

Poi mostralo nell'uscita testuale di `doctor` accanto agli altri controlli e nel suo `--json`, con la stessa forma usata da `harness_rilevati`. Aggiungi una riga fissa che resta vera anche quando non c'è nessuna credenziale:

```
Rete: hook, report, dashboard e doctor sono offline. L'unico comando che manda dati
fuori e' `starkeno preflight interpret`, e manda solo il testo che gli passi tu.
```

**Attenzione all'import:** `from starkeno.preflight_anthropic import VARIABILI` importa il modulo che importa `anthropic`. Se questo rendesse `doctor` sensibilmente più lento, sposta `VARIABILI` in `preflight_interpret.py` (che non importa l'SDK) e falla ri-esportare da `preflight_anthropic`. Misura prima di spostare: `python -c "import time; t=time.monotonic(); import starkeno.diagnostica; print(time.monotonic()-t)"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_diagnostica.py -W error && python -m starkeno doctor`
Expected: PASS e `doctor` esce 0 mostrando la riga sulla rete.

- [ ] **Step 5: Commit**

```bash
git add starkeno/diagnostica.py tests/test_diagnostica.py
git commit -m "feat: doctor dichiara l'unica superficie di rete di StarkEno"
```

---

### Task 7: La promessa del README, corretta senza attenuarla

**Files:**
- Modify: `README.md:100` e nuova sezione dopo «What the hooks do, and what they do not»
- Modify: `CHANGELOG.md` (sotto `## [Unreleased]`)
- Test: `tests/test_open_source_files.py` (aggiungere in fondo)

**Questo è il task che rende la consegna onesta**, e va fatto **solo qui**: anticiparlo avrebbe promesso una superficie di rete che non esisteva ancora. La riga 100 di oggi — «**No data leaves your machine.** Calls are stored in local SQLite.» — vive in un elenco sugli hook e resta letteralmente vera per loro, ma un lettore la prende come una promessa sul prodotto. Si corregge rendendo esplicito l'ambito **e** aggiungendo la sezione che dice l'eccezione.

- [ ] **Step 1: Write the failing test**

```python
# in fondo a tests/test_open_source_files.py
def test_il_readme_dichiara_l_unica_superficie_di_rete():
    """Un README che promette piu' di quanto il codice mantiene e' una bugia lenta."""
    from pathlib import Path

    testo = (Path(__file__).resolve().parent.parent / "README.md").read_text(
        encoding="utf-8")

    assert "preflight interpret" in testo, "l'eccezione non e' nominata"
    assert "Anthropic" in testo, "non si dice a chi vanno i dati"
    assert "ANTHROPIC_API_KEY" in testo, "non si dice come si configura"


def test_il_readme_non_promette_piu_che_nulla_esca_dalla_macchina():
    """La promessa vecchia era vera prima della parte B e ora non lo e' piu'."""
    from pathlib import Path

    testo = (Path(__file__).resolve().parent.parent / "README.md").read_text(
        encoding="utf-8")

    for bugia in ("No data leaves your machine.",
                  "No data ever leaves your machine"):
        assert bugia not in testo, "promessa non piu' vera: %r" % bugia
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_open_source_files.py -k readme`
Expected: FAIL su entrambi — il README non nomina `preflight interpret` e contiene ancora la riga vecchia.

- [ ] **Step 3: Correggi il README**

Sostituisci la riga 100:

```markdown
- **The hooks send nothing anywhere.** Calls are stored in local SQLite. For the one
  command that does use the network, see *What leaves your machine* below.
```

Aggiungi questa sezione subito dopo il paragrafo su `SessionStart` (dopo la riga 107):

```markdown
## What leaves your machine

Nothing, with one exception you have to ask for by name.

Hooks, `report`, the dashboard and `doctor` are offline. They read transcripts your agent
already wrote and a database on your own disk, and they make no network requests.

`starkeno preflight interpret` is the exception. It sends **the text you pass to that
command, and nothing else**, to the Anthropic API, which turns it into a Draft Blueprint.
Your transcripts, your database, your notes and your file paths are never part of that
request. The command is never started by a hook, by `report`, by `doctor` or by the
dashboard — you run it, or it does not run. It prints an estimate of what it will send
before it sends anything, and what it actually used afterwards, and `--dry-run` shows the
estimate without calling the model at all.

It uses the API key already in your environment (`ANTHROPIC_API_KEY`, or
`STARKENO_ANTHROPIC_API_KEY` if you would rather give StarkEno a separate one, which takes
precedence). StarkEno never writes, logs or prints that key.

The Draft it produces is not simulated and not trusted. `analyze` still requires the
literal `--confirmed` flag, so a model's interpretation never becomes structured truth
without a person having looked at it.
```

**Non attenuare.** Niente «i tuoi dati restano al sicuro»: dire esattamente cosa esce, a chi, e cosa no.

- [ ] **Step 4: Aggiungi le voci di changelog**

Sotto `## [Unreleased]`, in `### Added`:

```markdown
- `starkeno preflight interpret`: da testo libero a Draft Blueprint, con assunzioni e
  domande aperte esplicite. Una sola chiamata al modello e un solo retry di riparazione;
  preventivo stimato prima, consumo osservato dopo, e lo scarto fra i due. `--dry-run`
  mostra il preventivo senza chiamare nulla.
- `starkeno doctor` dichiara l'unica superficie di rete di StarkEno e se una credenziale
  e' configurata, senza mai leggerne il valore.
```

In `### Changed`:

```markdown
- Il README non promette piu' che nessun dato lasci la macchina. Resta vero per hook,
  conto, dashboard e `doctor`; diventa falso per il solo comando che interpreta il testo,
  che invia il testo passato dall'utente e nient'altro.
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
python -m pytest -q -W error && git diff --check && python scripts/verifica_segreti.py --tracked && python scripts/verifica_pubblicazione.py
```
Expected: PASS su tutta la suite, exit 0 su tutti gli script.

- [ ] **Step 6: Commit**

```bash
git add README.md CHANGELOG.md tests/test_open_source_files.py
git commit -m "docs: la promessa di rete corretta alla consegna della parte B"
```

---

## Cosa questo piano NON copre

- **La parte C.** Dipende dalla B per l'ingresso naturale e ha vincoli duri che non si rinegoziano in fase di piano: flag letterale separato, tetto di spesa **obbligatorio senza default**, mai avviata da hook, report, doctor o dashboard. Merita il suo piano, dopo che la B esiste.
- **Un `--model` sulla CLI.** Il modello è una costante di modulo (`claude-opus-5`). Renderlo scegliibile è una decisione di prodotto — quanto rischio di qualità si scambia per quanto risparmio — e finché nessuno l'ha presa un flag sarebbe un segnaposto travestito da funzionalità.
- **La taratura del preventivo.** `CHARACTERS_PER_TOKEN = 3.5` è una stima dichiarata. Diventerà un numero ricavato quando ci saranno abbastanza scarti osservati dal Task 5 — che è lo stesso meccanismo che la parte C promette per le soglie di `config.py`.
- **Il prompt caching esplicito.** Il prefisso è stabile, che è la condizione perché la cache funzioni, ma non ci sono `cache_control` in questo piano: con chiamate isolate e TTL di 5 minuti pagherebbe solo il retry, e vale la pena aggiungerlo quando ci sarà una misura che lo giustifica invece di un'ipotesi.
- **Altri harness.** Cursor, OpenCode e OpenClaw restano fuori finché non esiste un transcript vero da cui leggerne lo schema.
