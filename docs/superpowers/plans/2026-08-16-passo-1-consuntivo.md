# Passo 1 — Il consuntivo: piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** legare un'esecuzione reale al Blueprint che la prevedeva e dire dove stanno gli
scarti, rifiutandosi di dirlo quando l'attribuzione sarebbe un'ipotesi.

**Architecture:** l'attribuzione è una **vista** calcolata al momento del confronto
incrociando gli intervalli dichiarati con i `timestamp` delle righe già raccolte, mai una
colonna timbrata sulla riga. Un modulo puro (`starkeno/consuntivo.py`) contiene tutta la
logica; `db.py` aggiunge due tabelle e le loro letture; tre tool MCP e un comando CLI sono
involucri sottili. `hook_ingestione.py`, `agent_actions`, `conto.py` e `report_conto.py`
non si toccano.

**Tech Stack:** Python ≥3.12 <3.15, SQLAlchemy 2 (solo dentro `db.py`), Alembic, pydantic
2, pytest.

**Specifica:** [2026-08-16-consuntivo-esecuzione-blueprint-design.md](../specs/2026-08-16-consuntivo-esecuzione-blueprint-design.md)

## Global Constraints

- **Solo `starkeno/db.py` importa SQLAlchemy** (invariante 5). `consuntivo.py` è puro:
  niente SQLAlchemy, niente `datetime.now`, niente filesystem.
- **Alembic è l'unica autorità sullo schema** (invariante 6). `create_all()` solo nella
  fixture di `tests/conftest.py`.
- **Modelli ORM e migrazioni descrivono lo stesso schema, ordine delle colonne compreso**
  (invariante 7). `tests/test_migrations.py::test_the_orm_models_and_the_migrations_describe_the_same_schema`
  lo verifica.
- **Ogni colonna temporale usa `db.UTCDateTime`** (invariante 8). Sopra `db.py` tutti i
  datetime sono aware-UTC (invariante 1).
- **Ogni connessione SQLite va chiusa da chi l'ha aperta** (invariante 14):
  `session.close()` **e** `engine.dispose()`. La fixture autouse
  `nessuna_connessione_lasciata_aperta` fa fallire chi non lo fa.
- **I test non toccano mai il database reale** (invariante 3): `tmp_path` più
  `STARKENO_DB_PATH` risolto al momento della chiamata.
- **Ogni test ha una regressione concreta che lo rende rosso** (invariante 13).
- **Nessun push, nessuna modifica remota.** Solo commit locali.
- **Niente dati personali, transcript reali, percorsi home o segreti** nei file tracciati.
  Le fixture sono sintetiche.
- Prima di dichiarare completo un task: test pertinenti, `python -m pytest -q -W error`
  (baseline attuale **601 passed, 2 skipped**) e `git diff --check`.
- **Se un task si rivela sbagliato mentre lo esegui, fermati e dillo** invece di
  aggiustare il piano da solo.

## Struttura dei file

| File | Responsabilità |
|---|---|
| `starkeno/consuntivo.py` **(nuovo)** | modulo puro: tipi di ingresso, attribuzione, totali, confronto, moneta, resa testuale |
| `starkeno/db.py` **(modifica)** | due modelli ORM nuovi e le loro letture/scritture |
| `migrations/versions/0006_esecuzioni_blueprint.py` **(nuovo)** | le due tabelle |
| `starkeno/mcp_server.py` **(modifica)** | i tre tool e il confinamento del percorso in lettura |
| `starkeno/cli.py` **(modifica)** | il comando `starkeno consuntivo` |
| `tests/test_consuntivo.py` **(nuovo)** | le regressioni del modulo puro |
| `tests/test_consuntivo_db.py` **(nuovo)** | le regressioni delle due tabelle |
| `tests/test_preflight_report.py` **(modifica)** | il round-trip dell'analisi JSON |
| `tests/test_migrations.py` **(modifica)** | l'insieme delle tabelle attese |
| `tests/test_mcp_server.py` **(modifica)** | i tre tool e la guardia «Preflight è offline» |
| `tests/test_cli.py` **(modifica)** | il comando nuovo |
| `AGENTS.md`, `CHANGELOG.md` **(modifica)** | architettura, invariante nuovo, registro |

---

### Task 0: La misura che precede il codice — il round-trip dell'analisi

Tutto il design poggia sull'idea che un'analisi JSON si rilegga identica.
`render_analysis` serializza con `model_dump(mode="json")`, che manda `Decimal` e `date`
in stringa. **Va verificato, non assunto.**

**Files:**
- Test: `tests/test_preflight_report.py`

**Interfaces:**
- Consumes: `starkeno.preflight_report.render_analysis`, `PreflightAnalysis`;
  `starkeno.preflight_schema.Blueprint`; `starkeno.preflight_simulate.SimulationReport`
- Produces: nessuna interfaccia di codice. Produce il **permesso di procedere**.

- [ ] **Step 1: Scrivi il test che fallisce**

Aggiungi in fondo a `tests/test_preflight_report.py`:

```python
def test_analisi_json_si_rilegge_identica():
    """Il consuntivo conserva l'analisi come TESTO e la rilegge al confronto.

    `model_dump(mode="json")` manda `Decimal` e `date` in stringa. Se non tornassero
    indietro identici, l'esecuzione conserverebbe un preventivo che al confronto vale
    un altro numero — e nessuno se ne accorgerebbe, perche' il testo su disco resta
    quello giusto.
    """
    import json

    from starkeno.preflight_schema import Blueprint
    from starkeno.preflight_simulate import SimulationReport, simulate_blueprint

    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "preflight" / "minimal.json").read_text(
            encoding="utf-8"
        )
    )
    payload["confirmed"] = True
    # Prezzi veri: sono i campi Decimal, cioe' esattamente quelli a rischio.
    payload["models"][0]["input_price_per_million"] = "3.00"
    payload["models"][0]["output_price_per_million"] = "15.00"
    payload["models"][0]["cache_read_price_per_million"] = "0.30"
    payload["models"][0]["cache_write_price_per_million"] = "3.75"
    payload["models"][0]["price_verified_at"] = "2026-08-16"
    blueprint = Blueprint.model_validate(payload)

    analisi = PreflightAnalysis(
        blueprint=blueprint,
        findings=(),
        simulation=simulate_blueprint(blueprint, samples=8, seed=7),
        source_path=None,
    )

    testo = render_analysis(analisi, format="json")
    riletto = json.loads(testo)

    assert Blueprint.model_validate(riletto["blueprint"]) == blueprint
    assert SimulationReport.model_validate(riletto["simulation"]) == analisi.simulation
```

Se `Path` o `PreflightAnalysis` non sono già importati in quel file, aggiungili in cima.

- [ ] **Step 2: Esegui il test**

```bash
python -m pytest tests/test_preflight_report.py::test_analisi_json_si_rilegge_identica -v
```

**Questo test può passare al primo colpo, ed è il risultato buono.** Non è TDD al
contrario: è una misura, e il suo esito decide il design.

- **PASSA** → il design procede come scritto. Vai allo Step 3.
- **FALLISCE** → **fermati e dillo all'utente.** Non aggiustare il piano da solo. Il
  design cambia lì: si conservano i totali già estratti invece del testo, e il confronto
  perde la moneta. Riporta il messaggio d'errore esatto e su quale dei due modelli.

- [ ] **Step 3: Commit**

```bash
git add tests/test_preflight_report.py
git commit -m "test: l'analisi JSON si rilegge identica, misurato prima di dipenderne"
```

---

### Task 1: I tipi di ingresso e l'attribuzione

**Files:**
- Create: `starkeno/consuntivo.py`
- Test: `tests/test_consuntivo.py`

**Interfaces:**
- Consumes: niente (modulo puro, nessuna dipendenza interna)
- Produces: `RigaOsservata`, `Marcatore`, `Esecuzione`, `Attribuzione`, `attribuisci()`.
  Ogni task successivo usa questi nomi esatti.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `tests/test_consuntivo.py`:

```python
"""Regressioni concrete dell'attribuzione: ogni test uccide un modo di sbagliare nodo."""
from datetime import datetime, timedelta, timezone

from starkeno.consuntivo import (
    Attribuzione,
    Esecuzione,
    Marcatore,
    RigaOsservata,
    attribuisci,
)

INIZIO = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


def _riga(minuti, *, sessione="s1", modello="opus", totale=1000):
    return RigaOsservata(
        session_id=sessione,
        timestamp=INIZIO + timedelta(minutes=minuti),
        model_used=modello,
        tokens_used=totale,
        cache_read_tokens=100,
        cache_write_tokens=100,
        output_tokens=200,
        azioni_nella_chiamata=1,
    )


def _esecuzione(*, fine_minuti=60):
    return Esecuzione(
        run_key="k1",
        project="progetto",
        blueprint_hash="h",
        started_at=INIZIO,
        ended_at=None if fine_minuti is None else INIZIO + timedelta(minutes=fine_minuti),
        model_map={},
    )


def _marcatore(nodo, minuti, seq):
    return Marcatore(node_id=nodo, declared_at=INIZIO + timedelta(minutes=minuti), seq=seq)


def _nodi(attribuzione):
    return {nodo: len(righe) for nodo, righe in attribuzione.per_nodo}


def test_riga_sul_confine_appartiene_al_nodo_nuovo():
    """Intervalli SEMIAPERTI. Con intervalli chiusi la riga finisce sul nodo precedente."""
    marcatori = [_marcatore("draft", 0, 1), _marcatore("review", 10, 2)]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(10)])

    assert risultato.stato == "ok"
    assert _nodi(risultato) == {"draft": 0, "review": 1}


def test_righe_prima_del_primo_marcatore_non_sono_attribuite():
    """La regressione: finiscono sul primo nodo, che non le ha mai prodotte."""
    marcatori = [_marcatore("draft", 10, 1)]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(5), _riga(15)])

    assert _nodi(risultato) == {"draft": 1}
    assert len(risultato.non_attribuite) == 1


def test_due_sessioni_fermano_il_confronto():
    """La regressione: le somma, e attribuisce a un nodo il lavoro di un altro lavoro."""
    marcatori = [_marcatore("draft", 0, 1)]

    risultato = attribuisci(
        _esecuzione(), marcatori, [_riga(5, sessione="s1"), _riga(6, sessione="s2")]
    )

    assert risultato.stato == "ambigua"
    assert risultato.per_nodo == ()
    assert risultato.sessioni == ("s1", "s2")
    assert "s1" in risultato.motivo and "s2" in risultato.motivo


def test_una_riga_senza_sessione_non_rende_ambigua_l_esecuzione():
    """`record_action` non imposta mai `session_id`: ogni riga di `log_agent_action` ha
    sessione vuota. Senza questa clausola UNA sola di esse rende ambigua ogni
    esecuzione, per sempre."""
    marcatori = [_marcatore("draft", 0, 1)]

    risultato = attribuisci(
        _esecuzione(), marcatori, [_riga(5, sessione="s1"), _riga(6, sessione="")]
    )

    assert risultato.stato == "ok"
    assert _nodi(risultato) == {"draft": 1}
    assert len(risultato.senza_sessione) == 1


def test_solo_righe_senza_sessione_e_senza_osservazioni():
    """La regressione: risulta `ok` con tutto in un secchio, come se avesse osservato."""
    marcatori = [_marcatore("draft", 0, 1)]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(5, sessione="")])

    assert risultato.stato == "senza_osservazioni"
    assert len(risultato.senza_sessione) == 1


def test_esecuzione_aperta_non_produce_attribuzione():
    """La regressione: calcola su una finestra che non e' ancora chiusa."""
    risultato = attribuisci(
        _esecuzione(fine_minuti=None), [_marcatore("draft", 0, 1)], [_riga(5)]
    )

    assert risultato.stato == "aperta"
    assert risultato.per_nodo == ()


def test_righe_fuori_dalla_finestra_sono_ignorate():
    """La finestra autorevole e' qui, non nel pre-filtro SQL."""
    marcatori = [_marcatore("draft", 0, 1)]

    risultato = attribuisci(_esecuzione(fine_minuti=30), marcatori, [_riga(10), _riga(50)])

    assert _nodi(risultato) == {"draft": 1}
    assert risultato.non_attribuite == ()


def test_stesso_nodo_dichiarato_due_volte_produce_una_riga_sola():
    """Un ritorno su `review` non deve produrre due `review` nel confronto."""
    marcatori = [
        _marcatore("draft", 0, 1),
        _marcatore("review", 10, 2),
        _marcatore("draft", 20, 3),
    ]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(5), _riga(15), _riga(25)])

    assert _nodi(risultato) == {"draft": 2, "review": 1}


def test_marcatori_con_lo_stesso_istante_si_ordinano_per_seq():
    """Senza `seq` l'ordine di due marcatori simultanei dipende dall'ordinamento."""
    marcatori = [_marcatore("review", 10, 2), _marcatore("draft", 10, 1)]

    risultato = attribuisci(_esecuzione(), marcatori, [_riga(15)])

    assert [nodo for nodo, _ in risultato.per_nodo] == ["draft", "review"]
    assert _nodi(risultato) == {"draft": 0, "review": 1}


def test_esecuzione_senza_marcatori_mette_tutto_in_non_attribuite():
    risultato = attribuisci(_esecuzione(), [], [_riga(5), _riga(6)])

    assert risultato.stato == "ok"
    assert risultato.per_nodo == ()
    assert len(risultato.non_attribuite) == 2
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
python -m pytest tests/test_consuntivo.py -v
```

Atteso: `ModuleNotFoundError: No module named 'starkeno.consuntivo'`.

- [ ] **Step 3: Scrivi l'implementazione minima**

Crea `starkeno/consuntivo.py`:

```python
"""Il confronto fra il preventivo di un Blueprint e il lavoro davvero osservato.

**Modulo puro**, come `conto.py`: riceve snapshot gia' letti e restituisce dati. Niente
SQLAlchemy, niente orologio, niente filesystem. E' cosi' che l'attribuzione si prova in
memoria, e che una dichiarazione sbagliata si corregge ricalcolando invece di restare
incisa su una riga.

**I DUE OROLOGI, assunzione dichiarata.** `Marcatore.declared_at` viene dal processo che
serve MCP; `RigaOsservata.timestamp` viene dal transcript scritto dall'agente. Il server
ascolta su `127.0.0.1`, quindi e' la stessa macchina e lo stesso orologio. Si sa anche
come rompe: se il server girasse altrove, sbaglierebbero **solo le righe a cavallo di un
confine fra nodi**, e in silenzio. Se un giorno il server non fosse piu' locale, questa
regola va rivista insieme.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RigaOsservata:
    """Una riga di `agent_actions`, ridotta a cio' che il confronto usa."""

    session_id: str
    timestamp: datetime          # aware-UTC (invariante 1)
    model_used: str
    tokens_used: int
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    azioni_nella_chiamata: int


@dataclass(frozen=True)
class Marcatore:
    """«Da adesso sto lavorando su questo nodo», dichiarato dall'agente."""

    node_id: str
    declared_at: datetime
    seq: int


@dataclass(frozen=True)
class Esecuzione:
    """Il perimetro dichiarato di un'esecuzione. `ended_at` None significa aperta."""

    run_key: str
    project: str
    blueprint_hash: str
    started_at: datetime
    ended_at: datetime | None
    model_map: Mapping[str, str]


@dataclass(frozen=True)
class Attribuzione:
    """Chi ha prodotto cosa, e cosa non si sa attribuire.

    `per_nodo` segue l'ordine di prima comparsa dei marcatori. Un nodo dichiarato piu'
    volte compare UNA volta con le righe di tutti i suoi intervalli: due voci `review`
    nel confronto sarebbero due nodi che non esistono.
    """

    stato: str                   # ok | aperta | ambigua | senza_osservazioni
    motivo: str
    per_nodo: tuple[tuple[str, tuple[RigaOsservata, ...]], ...]
    non_attribuite: tuple[RigaOsservata, ...]
    senza_sessione: tuple[RigaOsservata, ...]
    sessioni: tuple[str, ...]


def _vuota(stato: str, motivo: str, senza_sessione=()) -> Attribuzione:
    return Attribuzione(
        stato=stato, motivo=motivo, per_nodo=(), non_attribuite=(),
        senza_sessione=tuple(senza_sessione), sessioni=(),
    )


def attribuisci(
    esecuzione: Esecuzione,
    marcatori: Sequence[Marcatore],
    righe: Sequence[RigaOsservata],
) -> Attribuzione:
    """Attribuisce le righe ai nodi dichiarati, o dichiara perche' non lo fa.

    La finestra AUTOREVOLE e' qui: chi legge dal database pre-filtra con un indice, ma
    l'unica regola che conta e' questa, cosi' i confini sono provabili in memoria.

    Le righe con `session_id` vuota vanno in un secchio proprio e **non contano per
    l'ambiguita'**: `record_action` non imposta mai `session_id`, quindi ogni riga
    scritta dal tool `log_agent_action` ha sessione vuota, e una sola di esse renderebbe
    ambigua ogni esecuzione per sempre.
    """
    if esecuzione.ended_at is None:
        return _vuota("aperta", "L'esecuzione non e' stata chiusa: manca ended_at.")

    dentro = [
        riga for riga in righe
        if esecuzione.started_at <= riga.timestamp <= esecuzione.ended_at
    ]
    senza_sessione = tuple(riga for riga in dentro if not riga.session_id)
    con_sessione = [riga for riga in dentro if riga.session_id]

    if not con_sessione:
        return _vuota(
            "senza_osservazioni",
            "Nessuna chiamata con una sessione nota nella finestra dell'esecuzione.",
            senza_sessione,
        )

    sessioni = tuple(sorted({riga.session_id for riga in con_sessione}))
    if len(sessioni) > 1:
        return Attribuzione(
            stato="ambigua",
            motivo=(
                "Nella finestra ci sono %d sessioni distinte (%s): attribuire una di "
                "esse al Blueprint sarebbe un'ipotesi, quindi non se ne attribuisce "
                "nessuna." % (len(sessioni), ", ".join(sessioni))
            ),
            per_nodo=(), non_attribuite=(), senza_sessione=senza_sessione,
            sessioni=sessioni,
        )

    ordinati = sorted(marcatori, key=lambda m: (m.declared_at, m.seq))
    confini = [m.declared_at for m in ordinati] + [esecuzione.ended_at]

    raccolta: dict[str, list[RigaOsservata]] = {}
    for marcatore in ordinati:
        raccolta.setdefault(marcatore.node_id, [])
    non_attribuite: list[RigaOsservata] = []

    for riga in sorted(con_sessione, key=lambda r: r.timestamp):
        indice = _intervallo(riga.timestamp, confini)
        if indice is None:
            non_attribuite.append(riga)
        else:
            raccolta[ordinati[indice].node_id].append(riga)

    return Attribuzione(
        stato="ok", motivo="",
        per_nodo=tuple((nodo, tuple(righe)) for nodo, righe in raccolta.items()),
        non_attribuite=tuple(non_attribuite),
        senza_sessione=senza_sessione,
        sessioni=sessioni,
    )


def _intervallo(quando: datetime, confini: list[datetime]) -> int | None:
    """L'indice dell'intervallo SEMIAPERTO che contiene `quando`, o None.

    Semiaperto a destra: una riga esattamente sul `declared_at` di un marcatore
    appartiene al nodo NUOVO. L'ultimo intervallo chiude su `ended_at` incluso, perche'
    la finestra e' chiusa a destra.
    """
    if len(confini) < 2 or quando < confini[0]:
        return None
    for indice in range(len(confini) - 1):
        inizio, fine = confini[indice], confini[indice + 1]
        ultimo = indice == len(confini) - 2
        if inizio <= quando < fine or (ultimo and quando == fine):
            return indice
    return None
```

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
python -m pytest tests/test_consuntivo.py -v
```

Atteso: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add starkeno/consuntivo.py tests/test_consuntivo.py
git commit -m "feat: attribuzione delle chiamate ai nodi dichiarati, o il rifiuto di farlo"
```

---

### Task 2: I totali osservati

**Files:**
- Modify: `starkeno/consuntivo.py`
- Test: `tests/test_consuntivo.py`

**Interfaces:**
- Consumes: `RigaOsservata` (Task 1)
- Produces: `TotaliOsservati`, `totali(righe) -> TotaliOsservati`,
  `totali_per_modello(righe) -> tuple[tuple[str, TotaliOsservati], ...]`

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi a `tests/test_consuntivo.py` (e aggiungi `TotaliOsservati`, `totali`,
`totali_per_modello` all'import in cima):

```python
def _riga_grezza(totale, *, lettura, scrittura, uscita, modello="opus", azioni=1):
    return RigaOsservata(
        session_id="s1", timestamp=INIZIO, model_used=modello, tokens_used=totale,
        cache_read_tokens=lettura, cache_write_tokens=scrittura, output_tokens=uscita,
        azioni_nella_chiamata=azioni,
    )


def test_totali_scompongono_le_quattro_classi_come_il_conto():
    """`ingresso = totale - lettura - scrittura - uscita`, identico a calcola_conto."""
    righe = [_riga_grezza(1000, lettura=100, scrittura=50, uscita=200, azioni=3)]

    risultato = totali(righe)

    assert risultato.chiamate == 1
    assert risultato.azioni == 3
    assert risultato.input_tokens == 650
    assert risultato.cache_read_tokens == 100
    assert risultato.cache_write_tokens == 50
    assert risultato.output_tokens == 200
    assert risultato.totale_tokens == 1000
    assert risultato.righe_non_scomposte == 0


def test_una_scomposizione_parziale_vale_come_nessuna_scomposizione():
    """NULL significa «non dichiarato». Trattarlo come 0 sottostima la spesa, ed e'
    esattamente cio' che `record_action` documenta di non voler fare."""
    righe = [_riga_grezza(1000, lettura=100, scrittura=None, uscita=200)]

    risultato = totali(righe)

    assert risultato.totale_tokens == 1000
    assert risultato.righe_non_scomposte == 1
    assert risultato.input_tokens == 0
    assert risultato.cache_read_tokens == 0


def test_totali_per_modello_separano_i_modelli_e_ordinano_per_nome():
    righe = [
        _riga_grezza(1000, lettura=0, scrittura=0, uscita=100, modello="sonnet"),
        _riga_grezza(2000, lettura=0, scrittura=0, uscita=200, modello="opus"),
    ]

    risultato = totali_per_modello(righe)

    assert [nome for nome, _ in risultato] == ["opus", "sonnet"]
    assert risultato[0][1].totale_tokens == 2000
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
python -m pytest tests/test_consuntivo.py -k "totali or scomposizione" -v
```

Atteso: `ImportError: cannot import name 'TotaliOsservati'`.

- [ ] **Step 3: Scrivi l'implementazione minima**

Aggiungi a `starkeno/consuntivo.py`, dopo `Attribuzione`:

```python
@dataclass(frozen=True)
class TotaliOsservati:
    """I totali di un insieme di righe, con la stessa scomposizione della stima.

    `totale_tokens` segue sempre `tokens_used`, anche quando la scomposizione manca:
    una riga difettosa resta visibile nel totale grezzo invece di sparire. Le quattro
    classi accolgono solo le righe scomposte per intero, e `righe_non_scomposte` dice
    quante sono rimaste fuori.
    """

    chiamate: int
    azioni: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    totale_tokens: int
    righe_non_scomposte: int


TOTALI_VUOTI = TotaliOsservati(0, 0, 0, 0, 0, 0, 0, 0)


def totali(righe: Sequence[RigaOsservata]) -> TotaliOsservati:
    """Somma le righe. Una scomposizione parziale vale come nessuna scomposizione."""
    chiamate = azioni = ingresso = uscita = lettura = scrittura = 0
    totale = non_scomposte = 0
    for riga in righe:
        chiamate += 1
        azioni += riga.azioni_nella_chiamata
        totale += riga.tokens_used
        componenti = (riga.cache_read_tokens, riga.cache_write_tokens, riga.output_tokens)
        if any(componente is None for componente in componenti):
            non_scomposte += 1
            continue
        cache_read, cache_write, output = componenti
        lettura += cache_read
        scrittura += cache_write
        uscita += output
        ingresso += riga.tokens_used - cache_read - cache_write - output
    return TotaliOsservati(
        chiamate=chiamate, azioni=azioni, input_tokens=ingresso, output_tokens=uscita,
        cache_read_tokens=lettura, cache_write_tokens=scrittura, totale_tokens=totale,
        righe_non_scomposte=non_scomposte,
    )


def totali_per_modello(
    righe: Sequence[RigaOsservata],
) -> tuple[tuple[str, TotaliOsservati], ...]:
    """I totali separati per `model_used`, che e' la grana su cui si applica un prezzo."""
    raccolta: dict[str, list[RigaOsservata]] = {}
    for riga in righe:
        raccolta.setdefault(riga.model_used, []).append(riga)
    return tuple((nome, totali(raccolta[nome])) for nome in sorted(raccolta))
```

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
python -m pytest tests/test_consuntivo.py -v
```

Atteso: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add starkeno/consuntivo.py tests/test_consuntivo.py
git commit -m "feat: totali osservati con la stessa scomposizione della stima"
```

---

### Task 3: Il confronto con la stima

**Files:**
- Modify: `starkeno/consuntivo.py`
- Test: `tests/test_consuntivo.py`

**Interfaces:**
- Consumes: `TotaliOsservati`, `totali` (Task 2); `Attribuzione` (Task 1);
  `starkeno.preflight_simulate.SimulationReport`, `ScenarioTotals`, `NodeTotals`
- Produces: `StimaScenario`, `ConfrontoNodo`, `Consuntivo`,
  `stime_per_scenario(simulazione) -> tuple[StimaScenario, ...]`,
  `posizione_nella_banda(totale, scenari) -> str`,
  `costruisci(esecuzione, attribuzione, simulazione, blueprint) -> Consuntivo`

`blueprint` è un `starkeno.preflight_schema.Blueprint`; nel Task 3 serve solo per l'elenco
dei nodi. Il Task 4 gli aggiunge la moneta.

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi a `tests/test_consuntivo.py` (import in cima: `SCENARI`, `ConfrontoNodo`,
`Consuntivo`, `StimaScenario`, `costruisci`, `posizione_nella_banda`, `stime_per_scenario`; più
`from starkeno.preflight_schema import Blueprint` e
`from starkeno.preflight_simulate import simulate_blueprint`, `import json`,
`from pathlib import Path`):

```python
FIXTURE = Path(__file__).parent / "fixtures" / "preflight" / "minimal.json"


def _blueprint(**prezzi):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = True
    payload["models"][0].update(prezzi)
    return Blueprint.model_validate(payload)


def _blueprint_senza_massimo():
    """Come `_blueprint`, ma con `max_retries` assente sul nodo `draft` (`nodes[0]`).

    Questo fa scattare `_has_unbounded_maximum` in `preflight_simulate.py`
    (`max_retries is None` e `retry_probability.max > 0`), quindi la simulazione lascia
    `maximum = None`. Il grafo NON e' pero' inevitabilmente unbounded — lo richiederebbe
    `retry_probability.typical >= 1`, e quello di `draft` e' 0.05 — quindi `optimistic`,
    `typical` e `prudent` restano tutti presenti: e' l'unico modo di ottenere un Blueprint
    con esattamente uno scenario assente e gli altri tre no."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = True
    payload["nodes"][0]["budget"]["max_retries"] = None
    return Blueprint.model_validate(payload)


def _simulazione(blueprint):
    return simulate_blueprint(blueprint, samples=8, seed=7)


def _scenario(nome, totale):
    """Scenari SINTETICI: la banda va provata su valori scelti, non su una simulazione
    i cui scenari potrebbero coincidere e rendere il test intermittente."""
    return StimaScenario(
        nome=nome, input_tokens=totale, output_tokens=0, cache_read_tokens=0,
        cache_write_tokens=0, totale_tokens=totale, executions=1, llm_calls=1,
        tool_calls=0, costo=None, valuta=None,
    )


def test_posizione_nella_banda_dice_dove_cade_l_osservato():
    scenari = (
        _scenario("optimistic", 100), _scenario("typical", 200),
        _scenario("prudent", 300), _scenario("maximum", 400),
    )

    assert posizione_nella_banda(50, scenari) == "sotto optimistic"
    assert posizione_nella_banda(250, scenari) == "fra typical e prudent"
    assert posizione_nella_banda(200, scenari) == "esattamente su typical"
    assert posizione_nella_banda(500, scenari) == "oltre maximum"


def test_uno_scenario_assente_non_entra_nella_banda_come_zero():
    """La regressione: `None` letto come 0 mette ogni osservazione «oltre il massimo»."""
    parziali = (_scenario("optimistic", 100), _scenario("typical", 200))

    testo = posizione_nella_banda(10**9, parziali)

    assert "prudent" in testo and "maximum" in testo
    assert "banda incompleta" in testo


def test_stime_per_scenario_salta_gli_scenari_assenti():
    """Un `maximum` None non deve comparire come uno scenario da zero token.

    La regressione: togliere `if scenario is not None:` in `stime_per_scenario` prova a
    costruire uno `StimaScenario` anche dal `maximum` assente di `_blueprint_senza_massimo`
    (vedi la sua docstring) invece di ometterlo."""
    scenari = stime_per_scenario(_simulazione(_blueprint_senza_massimo()))

    nomi = {s.nome for s in scenari}
    assert "maximum" not in nomi
    assert nomi == {"optimistic", "typical", "prudent"}
    assert not any(s.nome == "maximum" and s.totale_tokens == 0 for s in scenari)


def test_nodi_ordinati_per_scarto_assoluto_decrescente():
    """La prima riga deve rispondere a «dove e' finito il grosso»."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    marcatori = [_marcatore("draft", 0, 1), _marcatore("review", 30, 2)]
    righe = [_riga(5, totale=50), _riga(35, totale=500_000)]
    attribuzione = attribuisci(esecuzione, marcatori, righe)

    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)

    assert [nodo.node_id for nodo in consuntivo.nodi][0] == "review"


def test_un_nodo_senza_osservazioni_compare_a_zero_e_lo_dichiara():
    """«costato poco» e «mai eseguito» sono cose diverse: sparire le confonde."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    marcatori = [_marcatore("draft", 0, 1)]
    attribuzione = attribuisci(esecuzione, marcatori, [_riga(5)])

    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)

    review = [nodo for nodo in consuntivo.nodi if nodo.node_id == "review"]
    assert len(review) == 1
    assert review[0].osservato is None


def test_il_join_col_nodo_stimato_usa_il_node_id():
    """La regressione: se `per_nodo_typical.get(nodo.id)` in `costruisci` smettesse di
    combaciare, o le due sorgenti di `executions_stimate` / `chiamate_osservate` si
    scambiassero, la suite restava verde lo stesso — prima solo l'ordinamento e il nodo
    da 500000 token erano coperti, e quel nodo domina qualunque scarto per costruzione."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    marcatori = [_marcatore("draft", 0, 1), _marcatore("review", 30, 2)]
    righe = [_riga(5, totale=300), _riga(10, totale=400), _riga(35, totale=100)]
    attribuzione = attribuisci(esecuzione, marcatori, righe)

    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)

    per_nodo = {nodo.node_id: nodo for nodo in consuntivo.nodi}
    draft, review = per_nodo["draft"], per_nodo["review"]

    assert draft.stima_typical is not None and draft.stima_typical.nome == "typical"
    assert draft.stima_typical.totale_tokens > 0  # draft e' llm, con budget reale

    assert review.stima_typical is not None
    assert review.stima_typical.totale_tokens == 0  # review e' human, budget tutto zero
    # Il contrasto e' il punto: un join che pescasse il nodo sbagliato scambierebbe
    # questi due totali.

    assert draft.stima_typical.totale_tokens == (
        draft.stima_typical.input_tokens + draft.stima_typical.output_tokens
        + draft.stima_typical.cache_read_tokens + draft.stima_typical.cache_write_tokens
    )
    assert draft.executions_stimate >= 1
    assert draft.chiamate_osservate == 2

    assert draft.scarto_totale_tokens == (
        draft.osservato.totale_tokens - draft.stima_typical.totale_tokens
    )


def test_le_chiamate_stimate_e_osservate_non_si_sottraggono():
    """`executions` conta invocazioni di nodo, la riga conta chiamate API: unita'
    diverse. La regressione da uccidere e' un campo di scarto fra le due."""
    campi = {campo for campo in ConfrontoNodo.__dataclass_fields__}

    assert "scarto_chiamate" not in campi
    assert "scarto_executions" not in campi
    assert "executions_stimate" in campi
    assert "chiamate_osservate" in campi


def test_uno_stato_non_ok_non_produce_nodi():
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    attribuzione = attribuisci(
        esecuzione, [_marcatore("draft", 0, 1)],
        [_riga(5, sessione="s1"), _riga(6, sessione="s2")],
    )

    consuntivo = costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint)

    assert consuntivo.stato == "ambigua"
    assert consuntivo.nodi == ()
    assert consuntivo.motivo
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
python -m pytest tests/test_consuntivo.py -k "banda or nodi or chiamate or stato" -v
```

Atteso: `ImportError: cannot import name 'stime_per_scenario'`.

- [ ] **Step 3: Scrivi l'implementazione minima**

Aggiungi a `starkeno/consuntivo.py`. In cima al file, accanto agli altri import:

```python
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - solo per i tipi
    from starkeno.preflight_schema import Blueprint
    from starkeno.preflight_simulate import SimulationReport
```

L'import è differito anche a runtime: `consuntivo.py` non deve trascinare pydantic dentro
percorsi che non lo usano.

Poi, in fondo al file:

```python
SCENARI = ("optimistic", "typical", "prudent", "maximum")


@dataclass(frozen=True)
class StimaScenario:
    """Un scenario della simulazione, ridotto alle grandezze confrontabili."""

    nome: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    totale_tokens: int
    executions: int
    llm_calls: int
    tool_calls: int
    costo: Decimal | None
    valuta: str | None


@dataclass(frozen=True)
class ConfrontoNodo:
    """Un nodo del Blueprint, con l'osservato accanto allo scenario `typical`.

    NON esiste uno scarto fra chiamate: `executions_stimate` conta invocazioni di nodo
    (una piu' i retry), `chiamate_osservate` conta chiamate API, e un nodo `llm` in una
    sessione reale sono decine di chiamate. Si stampano affiancate e non si sottraggono
    mai — e' il punto in cui sarebbe piu' facile produrre un numero preciso e falso.
    """

    node_id: str
    osservato: TotaliOsservati | None
    stima_typical: StimaScenario | None
    scarto_totale_tokens: int
    executions_stimate: int
    chiamate_osservate: int


@dataclass(frozen=True)
class Consuntivo:
    """Il confronto completo, o la dichiarazione del perche' non c'e'."""

    run_key: str
    project: str
    blueprint_hash: str
    started_at: datetime
    ended_at: datetime | None
    stato: str
    motivo: str
    osservato: TotaliOsservati
    scenari: tuple[StimaScenario, ...]
    posizione: str
    nodi: tuple[ConfrontoNodo, ...]
    non_attribuite: TotaliOsservati
    senza_sessione: TotaliOsservati
    sessioni: tuple[str, ...]


def _stima_da_scenario(nome: str, scenario) -> StimaScenario:
    return StimaScenario(
        nome=nome,
        input_tokens=scenario.input_tokens,
        output_tokens=scenario.output_tokens,
        cache_read_tokens=scenario.cache_read_tokens,
        cache_write_tokens=scenario.cache_write_tokens,
        totale_tokens=(scenario.input_tokens + scenario.output_tokens
                       + scenario.cache_read_tokens + scenario.cache_write_tokens),
        executions=sum(nodo.executions for nodo in scenario.nodes),
        llm_calls=scenario.llm_calls,
        tool_calls=scenario.tool_calls,
        costo=scenario.cost,
        valuta=scenario.currency,
    )


def stime_per_scenario(simulazione: SimulationReport) -> tuple[StimaScenario, ...]:
    """Gli scenari presenti, nell'ordine canonico. Quelli `None` restano fuori."""
    presenti = []
    for nome in SCENARI:
        scenario = getattr(simulazione, nome)
        if scenario is not None:
            presenti.append(_stima_da_scenario(nome, scenario))
    return tuple(presenti)


def posizione_nella_banda(totale: int, scenari: Sequence[StimaScenario]) -> str:
    """Dove cade l'osservato rispetto agli scenari. Un solo numero non dice niente.

    Gli scenari assenti si dichiarano assenti: leggerli come zero metterebbe ogni
    osservazione «oltre il massimo», che e' un giudizio, non una misura.
    """
    if not scenari:
        return "banda incompleta: nessuno scenario disponibile"
    mancanti = [nome for nome in SCENARI if nome not in {s.nome for s in scenari}]
    coda = ""
    if mancanti:
        coda = " (banda incompleta: mancano %s)" % ", ".join(mancanti)

    ordinati = sorted(scenari, key=lambda s: s.totale_tokens)
    if totale < ordinati[0].totale_tokens:
        return "sotto %s" % ordinati[0].nome + coda
    for precedente, successivo in zip(ordinati, ordinati[1:]):
        if precedente.totale_tokens <= totale < successivo.totale_tokens:
            if totale == precedente.totale_tokens:
                return "esattamente su %s" % precedente.nome + coda
            return "fra %s e %s" % (precedente.nome, successivo.nome) + coda
    if totale == ordinati[-1].totale_tokens:
        return "esattamente su %s" % ordinati[-1].nome + coda
    return "oltre %s" % ordinati[-1].nome + coda


def costruisci(
    esecuzione: Esecuzione,
    attribuzione: Attribuzione,
    simulazione: SimulationReport,
    blueprint: Blueprint,
) -> Consuntivo:
    """Il confronto, o la dichiarazione del perche' non si puo' fare."""
    scenari = stime_per_scenario(simulazione)
    non_attribuite = totali(attribuzione.non_attribuite)
    senza_sessione = totali(attribuzione.senza_sessione)

    if attribuzione.stato != "ok":
        return Consuntivo(
            run_key=esecuzione.run_key, project=esecuzione.project,
            blueprint_hash=esecuzione.blueprint_hash,
            started_at=esecuzione.started_at, ended_at=esecuzione.ended_at,
            stato=attribuzione.stato, motivo=attribuzione.motivo,
            osservato=TOTALI_VUOTI, scenari=scenari, posizione="",
            nodi=(), non_attribuite=non_attribuite, senza_sessione=senza_sessione,
            sessioni=attribuzione.sessioni,
        )

    osservate = [riga for _, righe in attribuzione.per_nodo for riga in righe]
    osservato = totali(osservate + list(attribuzione.non_attribuite))
    per_nodo_typical = _nodi_typical(simulazione)
    osservato_per_nodo = dict(attribuzione.per_nodo)

    nodi = []
    for nodo in blueprint.nodes:
        righe = osservato_per_nodo.get(nodo.id)
        totali_nodo = totali(righe) if righe else None
        stima = per_nodo_typical.get(nodo.id)
        nodi.append(ConfrontoNodo(
            node_id=nodo.id,
            osservato=totali_nodo,
            stima_typical=stima,
            scarto_totale_tokens=(
                (totali_nodo.totale_tokens if totali_nodo else 0)
                - (stima.totale_tokens if stima else 0)
            ),
            executions_stimate=stima.executions if stima else 0,
            chiamate_osservate=totali_nodo.chiamate if totali_nodo else 0,
        ))
    nodi.sort(key=lambda n: (-abs(n.scarto_totale_tokens), n.node_id))

    return Consuntivo(
        run_key=esecuzione.run_key, project=esecuzione.project,
        blueprint_hash=esecuzione.blueprint_hash,
        started_at=esecuzione.started_at, ended_at=esecuzione.ended_at,
        stato="ok", motivo="",
        osservato=osservato, scenari=scenari,
        posizione=posizione_nella_banda(osservato.totale_tokens, scenari),
        nodi=tuple(nodi), non_attribuite=non_attribuite,
        senza_sessione=senza_sessione, sessioni=attribuzione.sessioni,
    )


def _nodi_typical(simulazione: SimulationReport) -> dict[str, StimaScenario]:
    """Il subtotale per nodo dello scenario `typical`, indicizzato per `node_id`."""
    scenario = simulazione.typical
    if scenario is None:
        return {}
    risultato = {}
    for nodo in scenario.nodes:
        risultato[nodo.node_id] = StimaScenario(
            nome="typical",
            input_tokens=nodo.input_tokens,
            output_tokens=nodo.output_tokens,
            cache_read_tokens=nodo.cache_read_tokens,
            cache_write_tokens=nodo.cache_write_tokens,
            totale_tokens=(nodo.input_tokens + nodo.output_tokens
                           + nodo.cache_read_tokens + nodo.cache_write_tokens),
            executions=nodo.executions,
            llm_calls=nodo.llm_calls,
            tool_calls=nodo.tool_calls,
            costo=nodo.cost,
            valuta=nodo.currency,
        )
    return risultato
```

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
python -m pytest tests/test_consuntivo.py -v
```

Atteso: 21 passed.

- [ ] **Step 5: Commit**

```bash
git add starkeno/consuntivo.py tests/test_consuntivo.py
git commit -m "feat: confronto fra osservato e banda degli scenari, per nodo"
```

---

### Task 4: La moneta, con i prezzi del Blueprint e la mappatura dichiarata

**Files:**
- Modify: `starkeno/consuntivo.py`
- Test: `tests/test_consuntivo.py`

**Interfaces:**
- Consumes: `TotaliOsservati`, `totali_per_modello` (Task 2); `Consuntivo` (Task 3);
  `Blueprint.models` (`ModelProfile` con `input_price_per_million`,
  `output_price_per_million`, `cache_read_price_per_million`,
  `cache_write_price_per_million`, `currency`)
- Produces: `Moneta`, `calcola_moneta(righe, model_map, blueprint) -> Moneta | None`, e il
  campo `moneta: Moneta | None` su `Consuntivo`

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi a `tests/test_consuntivo.py` (import: `Moneta`, `calcola_moneta`; più
`from decimal import Decimal`):

```python
PREZZI = {
    "input_price_per_million": "3.00",
    "output_price_per_million": "15.00",
    "cache_read_price_per_million": "0.30",
    "cache_write_price_per_million": "3.75",
}


def test_i_token_osservati_si_prezzano_col_listino_del_blueprint():
    """Gli STESSI prezzi della stima: cosi' lo scarto isola il volume, non il listino."""
    blueprint = _blueprint(**PREZZI)
    righe = [_riga_grezza(1_000_000, lettura=0, scrittura=0, uscita=0, modello="opus-4")]

    moneta = calcola_moneta(righe, {"opus-4": "economy"}, blueprint)

    assert moneta is not None
    assert moneta.valuta == "USD"
    assert moneta.osservata == Decimal("3.00")
    assert moneta.token_non_prezzati == 0


def test_un_modello_non_mappato_conta_i_token_e_dichiara_la_moneta_ignota():
    """La regressione peggiore: prezzarlo zero. Un costo mancante sembra un costo basso."""
    blueprint = _blueprint(**PREZZI)
    righe = [_riga_grezza(1_000_000, lettura=0, scrittura=0, uscita=0, modello="ignoto")]

    moneta = calcola_moneta(righe, {}, blueprint)

    assert moneta is not None
    assert moneta.osservata == Decimal("0")
    assert moneta.token_non_prezzati == 1_000_000
    assert moneta.modelli_non_mappati == (("ignoto", 1_000_000),)


def test_senza_prezzi_nel_blueprint_la_moneta_e_assente_non_zero():
    """La fixture minimal ha tutti i prezzi a null: e' il caso normale, non un errore."""
    blueprint = _blueprint()
    righe = [_riga_grezza(1000, lettura=0, scrittura=0, uscita=0, modello="opus-4")]

    assert calcola_moneta(righe, {"opus-4": "economy"}, blueprint) is None


def test_valute_diverse_fra_i_modelli_mappati_rendono_la_moneta_assente():
    """Sommare USD ed EUR produrrebbe un numero che non e' denaro."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = True
    payload["models"][0].update(PREZZI)
    secondo = json.loads(json.dumps(payload["models"][0]))
    secondo.update({"id": "premium", "currency": "EUR"})
    payload["models"].append(secondo)
    blueprint = Blueprint.model_validate(payload)
    righe = [
        _riga_grezza(1000, lettura=0, scrittura=0, uscita=0, modello="a"),
        _riga_grezza(1000, lettura=0, scrittura=0, uscita=0, modello="b"),
    ]

    assert calcola_moneta(righe, {"a": "economy", "b": "premium"}, blueprint) is None


def test_una_riga_non_scomposta_non_si_prezza():
    """Senza scomposizione non si sa quanto sia output: prezzarla a tariffa input mente."""
    blueprint = _blueprint(**PREZZI)
    righe = [_riga_grezza(1_000_000, lettura=0, scrittura=None, uscita=0, modello="opus-4")]

    moneta = calcola_moneta(righe, {"opus-4": "economy"}, blueprint)

    assert moneta is not None
    assert moneta.osservata == Decimal("0")
    assert moneta.token_non_prezzati == 1_000_000
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
python -m pytest tests/test_consuntivo.py -k "moneta or prezz" -v
```

Atteso: `ImportError: cannot import name 'Moneta'`.

- [ ] **Step 3: Scrivi l'implementazione minima**

Aggiungi a `starkeno/consuntivo.py`:

```python
MILIONE = Decimal("1000000")


@dataclass(frozen=True)
class Moneta:
    """Il costo osservato, calcolato col listino che ha usato la stima.

    `osservata` copre SOLO le righe di un modello mappato e scomposto per intero.
    Tutto il resto sta in `token_non_prezzati` e in `modelli_non_mappati`: un costo
    mancante presentato come costo basso e' peggio di un costo dichiarato ignoto.
    """

    valuta: str
    osservata: Decimal
    token_non_prezzati: int
    modelli_non_mappati: tuple[tuple[str, int], ...]


def calcola_moneta(
    righe: Sequence[RigaOsservata],
    model_map: Mapping[str, str],
    blueprint: Blueprint,
) -> Moneta | None:
    """Prezza i token osservati, o restituisce None dichiarando che non si puo'.

    None in due casi soli: il Blueprint non dichiara **nessun** listino completo, oppure
    i suoi listini usano valute diverse — sommarle produrrebbe un numero che non e'
    denaro.

    Un modello osservato ma NON mappato non annulla la moneta: finisce in
    `modelli_non_mappati` con i suoi token, che e' l'informazione utile — dice cosa
    dichiarare per ottenere il numero. Restituire None qui nasconderebbe proprio la
    riga che serve a rimediare.
    """
    profili = {modello.id: modello for modello in blueprint.models}
    listini = {
        identificativo: prezzi
        for identificativo, profilo in profili.items()
        if (prezzi := _prezzi(profilo)) is not None
    }
    if not listini:
        return None
    valute = {profili[identificativo].currency for identificativo in listini}
    if len(valute) > 1:
        return None

    costo = Decimal("0")
    non_prezzati = 0
    non_mappati: list[tuple[str, int]] = []

    for nome, totale in totali_per_modello(righe):
        prezzi = listini.get(model_map.get(nome, ""))
        if prezzi is None:
            non_prezzati += totale.totale_tokens
            if model_map.get(nome) is None:
                non_mappati.append((nome, totale.totale_tokens))
            continue
        # Le righe non scomposte non si prezzano: non si sa quanto fosse output, e
        # prezzarle a tariffa input mente proprio sul caso caro.
        non_prezzati += _token_non_scomposti(righe, nome)
        ingresso, uscita, lettura, scrittura = prezzi
        costo += (
            Decimal(totale.input_tokens) * ingresso
            + Decimal(totale.output_tokens) * uscita
            + Decimal(totale.cache_read_tokens) * lettura
            + Decimal(totale.cache_write_tokens) * scrittura
        ) / MILIONE

    return Moneta(
        valuta=valute.pop(),
        osservata=costo,
        token_non_prezzati=non_prezzati,
        modelli_non_mappati=tuple(non_mappati),
    )


def _prezzi(profilo) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    """I quattro prezzi del profilo, o None se anche uno solo manca.

    Tutti o nessuno: prezzare l'input e ignorare l'output produce un costo che sembra
    completo e non lo e'.
    """
    if profilo is None:
        return None
    valori = (
        profilo.input_price_per_million, profilo.output_price_per_million,
        profilo.cache_read_price_per_million, profilo.cache_write_price_per_million,
    )
    if any(valore is None for valore in valori):
        return None
    return tuple(Decimal(valore) for valore in valori)  # type: ignore[return-value]


def _token_non_scomposti(righe: Sequence[RigaOsservata], modello: str) -> int:
    return sum(
        riga.tokens_used for riga in righe
        if riga.model_used == modello and any(
            componente is None for componente in
            (riga.cache_read_tokens, riga.cache_write_tokens, riga.output_tokens)
        )
    )
```

Poi aggiungi il campo a `Consuntivo`, in fondo alla dataclass:

```python
    moneta: Moneta | None = None
```

e in `costruisci`, prima dei due `return`, calcola:

```python
    moneta = calcola_moneta(
        [riga for _, righe in attribuzione.per_nodo for riga in righe]
        + list(attribuzione.non_attribuite),
        esecuzione.model_map,
        blueprint,
    ) if attribuzione.stato == "ok" else None
```

passandolo come `moneta=moneta` al `return` dello stato `ok` e `moneta=None` all'altro.

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
python -m pytest tests/test_consuntivo.py -v
```

Atteso: 26 passed.

- [ ] **Step 5: Commit**

```bash
git add starkeno/consuntivo.py tests/test_consuntivo.py
git commit -m "feat: moneta col listino del Blueprint, ignota dove non e' dichiarata"
```

---

### Task 5: La resa testuale

Una sola resa, condivisa dalle due porte: la CLI e il tool MCP devono dire la stessa cosa,
altrimenti divergono e l'utente vede due verità.

**Files:**
- Modify: `starkeno/consuntivo.py`
- Test: `tests/test_consuntivo.py`

**Interfaces:**
- Consumes: `Consuntivo`, `Moneta` (Task 3 e 4)
- Produces: `rendi_testo(consuntivo) -> str`

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi a `tests/test_consuntivo.py` (import: `rendi_testo`):

```python
def test_la_resa_dichiara_lo_scarto_atteso_sulla_cache():
    """Chi lo vede la prima volta pensa di aver sbagliato una sottrazione: la simulazione
    conta cache_write una volta e cache_read solo sui retry, un agente vero rispedisce il
    contesto a ogni turno. Va scritto, non lasciato dedurre."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    attribuzione = attribuisci(esecuzione, [_marcatore("draft", 0, 1)], [_riga(5)])

    testo = rendi_testo(costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint))

    assert "cache" in testo.lower()
    assert "contesto a ogni turno" in testo


def test_la_resa_di_uno_stato_non_ok_dice_il_motivo_e_non_stampa_numeri():
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    attribuzione = attribuisci(
        esecuzione, [_marcatore("draft", 0, 1)],
        [_riga(5, sessione="s1"), _riga(6, sessione="s2")],
    )

    testo = rendi_testo(costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint))

    assert "ambigua" in testo
    assert "s1" in testo and "s2" in testo
    assert "Per nodo" not in testo


def test_ogni_numero_dice_su_quante_chiamate_e_calcolato():
    """Il Passo 3 lo richiedera' comunque: un numero tarato su tre esecuzioni e uno
    tarato su trecento non valgono uguale."""
    blueprint = _blueprint()
    esecuzione = _esecuzione()
    attribuzione = attribuisci(esecuzione, [_marcatore("draft", 0, 1)], [_riga(5), _riga(6)])

    testo = rendi_testo(costruisci(esecuzione, attribuzione, _simulazione(blueprint), blueprint))

    assert "su 2 chiamate" in testo
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
python -m pytest tests/test_consuntivo.py -k "resa or numero" -v
```

Atteso: `ImportError: cannot import name 'rendi_testo'`.

- [ ] **Step 3: Scrivi l'implementazione minima**

Aggiungi a `starkeno/consuntivo.py`:

```python
NOTA_CACHE = (
    "Nota: la simulazione conta cache_write una volta per invocazione e cache_read solo "
    "sui retry, mentre un agente vero rispedisce il contesto a ogni turno. Un cache_read "
    "osservato molto piu' grande dello stimato e' atteso e sistematico, non un errore di "
    "calcolo."
)


def rendi_testo(consuntivo: Consuntivo) -> str:
    """La resa condivisa da CLI e tool MCP: una sola verita', non due."""
    righe = [
        "Consuntivo %s — progetto %s" % (consuntivo.run_key, consuntivo.project),
        "Blueprint %s" % consuntivo.blueprint_hash,
        "Finestra: %s → %s" % (
            consuntivo.started_at.isoformat(),
            consuntivo.ended_at.isoformat() if consuntivo.ended_at else "aperta",
        ),
        "Stato: %s" % consuntivo.stato,
    ]
    if consuntivo.stato != "ok":
        righe.append(consuntivo.motivo)
        if consuntivo.senza_sessione.chiamate:
            righe.append(
                "Righe senza sessione nella finestra: %d (mai attribuite)"
                % consuntivo.senza_sessione.chiamate
            )
        return "\n".join(righe)

    osservato = consuntivo.osservato
    righe.append("")
    righe.append("Osservato su %d chiamate (%d azioni):" % (osservato.chiamate, osservato.azioni))
    righe.append(
        "  input %d · output %d · cache read %d · cache write %d · totale %d"
        % (osservato.input_tokens, osservato.output_tokens, osservato.cache_read_tokens,
           osservato.cache_write_tokens, osservato.totale_tokens)
    )
    if osservato.righe_non_scomposte:
        righe.append(
            "  %d chiamate senza scomposizione: contate nel totale, fuori dalle classi"
            % osservato.righe_non_scomposte
        )
    righe.append("")
    righe.append("Stimato:")
    for scenario in consuntivo.scenari:
        righe.append("  %-11s totale %d" % (scenario.nome, scenario.totale_tokens))
    righe.append("L'osservato cade: %s" % consuntivo.posizione)

    righe.append("")
    righe.append("Per nodo, ordinato per scarto (stima: scenario typical):")
    for nodo in consuntivo.nodi:
        if nodo.osservato is None:
            righe.append("  %-16s nessuna osservazione" % nodo.node_id)
            continue
        righe.append(
            "  %-16s osservato %d su %d chiamate · stimato %d · scarto %+d "
            "(invocazioni stimate %d, unita' diversa dalle chiamate)"
            % (nodo.node_id, nodo.osservato.totale_tokens, nodo.chiamate_osservate,
               nodo.stima_typical.totale_tokens if nodo.stima_typical else 0,
               nodo.scarto_totale_tokens, nodo.executions_stimate)
        )

    if consuntivo.non_attribuite.chiamate:
        righe.append("")
        righe.append(
            "Non attribuite: %d chiamate, %d token (fuori da ogni intervallo dichiarato)"
            % (consuntivo.non_attribuite.chiamate, consuntivo.non_attribuite.totale_tokens)
        )
    if consuntivo.senza_sessione.chiamate:
        righe.append(
            "Senza sessione: %d chiamate, %d token (mai attribuite, non rendono ambigua)"
            % (consuntivo.senza_sessione.chiamate, consuntivo.senza_sessione.totale_tokens)
        )

    righe.append("")
    if consuntivo.moneta is None:
        righe.append("Moneta: assente — il Blueprint non dichiara un listino completo.")
    else:
        moneta = consuntivo.moneta
        righe.append("Moneta osservata: %s %s" % (moneta.osservata, moneta.valuta))
        for scenario in consuntivo.scenari:
            if scenario.costo is not None:
                righe.append("  stimato %-11s %s %s" % (
                    scenario.nome, scenario.costo, scenario.valuta))
        if moneta.token_non_prezzati:
            righe.append("  %d token non prezzati" % moneta.token_non_prezzati)
        for nome, token in moneta.modelli_non_mappati:
            righe.append(
                "  modello non mappato: %s (%d token) — dichiaralo in model_map"
                % (nome, token)
            )

    righe.append("")
    righe.append(NOTA_CACHE)
    return "\n".join(righe)
```

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
python -m pytest tests/test_consuntivo.py -v
```

Atteso: 29 passed.

- [ ] **Step 5: Commit**

```bash
git add starkeno/consuntivo.py tests/test_consuntivo.py
git commit -m "feat: resa testuale del consuntivo, condivisa dalle due porte"
```

---

### Task 6: Le due tabelle e la migrazione 0006

**Files:**
- Modify: `starkeno/db.py` (dopo la classe `AgentWatermark`)
- Create: `migrations/versions/0006_esecuzioni_blueprint.py`
- Modify: `tests/test_migrations.py:142-145` (l'insieme atteso delle tabelle)

**Interfaces:**
- Consumes: `db.Base`, `db.UTCDateTime`
- Produces: i modelli ORM `BlueprintRun` e `BlueprintRunMarker`

**Attenzione:** `test_upgrade_head_on_a_new_database_builds_the_whole_schema` asserisce
l'insieme **esatto** delle tabelle e si romperà. È previsto: va aggiornato in questo task,
non aggirato.

- [ ] **Step 1: Aggiorna il test dell'insieme delle tabelle e verifica che fallisca**

In `tests/test_migrations.py`, sostituisci l'assert delle tabelle:

```python
    assert tables == {
        "agent_actions", "alerts", "rule_status", "supervisor_state",
        "agent_watermark", "blueprint_runs", "blueprint_run_markers",
        "alembic_version",
    }
```

```bash
python -m pytest tests/test_migrations.py::test_upgrade_head_on_a_new_database_builds_the_whole_schema -v
```

Atteso: FAIL — le due tabelle nuove non esistono.

- [ ] **Step 2: Scrivi i modelli ORM**

In `starkeno/db.py`, dopo la classe `AgentWatermark`:

```python
class BlueprintRun(Base):
    """Un'esecuzione dichiarata: il perimetro entro cui confrontare stima e realta'.

    `analysis_json` conserva il PREVENTIVO verbatim invece di un riferimento al file:
    il file su disco puo' essere cancellato o modificato, e un'esecuzione deve
    conservare la stima contro cui e' stata confrontata. `_run_analyze` costruisce la
    revisione confermata in memoria e non la scrive da nessuna parte, quindi non esiste
    nemmeno un file a cui riferirsi.

    Nessuna colonna `status`: `ended_at IS NULL` E' lo stato, e due rappresentazioni
    della stessa cosa divergono sempre.
    """

    __tablename__ = "blueprint_runs"

    id = Column(Integer, primary_key=True)
    run_key = Column(String, nullable=False, unique=True)
    project = Column(String, nullable=False)
    blueprint_hash = Column(String, nullable=False)
    analysis_json = Column(String, nullable=False)
    model_map_json = Column(String, nullable=False, server_default=text("'{}'"))
    started_at = Column(UTCDateTime, nullable=False)
    ended_at = Column(UTCDateTime, nullable=True)

    __table_args__ = (
        # L'unica query calda: «c'e' un'esecuzione aperta su questo progetto?».
        Index("ix_blueprint_runs_project_ended", "project", "ended_at"),
    )


class BlueprintRunMarker(Base):
    """«Da adesso sto lavorando su questo nodo».

    `seq` lo assegna `aggiungi_marcatore` come massimo corrente piu' uno, nella stessa
    transazione dell'inserimento: due marcatori con lo stesso `declared_at` altrimenti
    si ordinerebbero a caso, e l'intervallo fra i due finirebbe sul nodo sbagliato.
    """

    __tablename__ = "blueprint_run_markers"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, nullable=False)
    node_id = Column(String, nullable=False)
    declared_at = Column(UTCDateTime, nullable=False)
    seq = Column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_blueprint_run_markers_run", "run_id", "declared_at", "seq"),
    )
```

- [ ] **Step 3: Scrivi la migrazione**

Crea `migrations/versions/0006_esecuzioni_blueprint.py`:

```python
"""v3: le esecuzioni dichiarate e i loro marcatori di nodo

Il ponte fra la meta' osservativa e quella predittiva. **Non tocca `agent_actions`**:
l'attribuzione e' una vista calcolata al momento del confronto incrociando questi
intervalli con i `timestamp` gia' raccolti, mai una colonna timbrata sulla riga. Cosi'
l'hook non deve imparare cosa sia un Blueprint, e una dichiarazione sbagliata si
corregge ricalcolando.

Le colonne temporali sono `sa.DateTime` come nella 0003: `db.UTCDateTime` ha
`impl = DateTime`, quindi il DDL emesso e' identico, ma i MODELLI devono usare
`UTCDateTime` perche' la normalizzazione del fuso e' un comportamento Python.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blueprint_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_key", sa.String(), nullable=False),
        sa.Column("project", sa.String(), nullable=False),
        sa.Column("blueprint_hash", sa.String(), nullable=False),
        sa.Column("analysis_json", sa.String(), nullable=False),
        sa.Column("model_map_json", sa.String(), nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key"),
    )
    op.create_index("ix_blueprint_runs_project_ended", "blueprint_runs",
                    ["project", "ended_at"])

    op.create_table(
        "blueprint_run_markers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("declared_at", sa.DateTime(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blueprint_run_markers_run", "blueprint_run_markers",
                    ["run_id", "declared_at", "seq"])


def downgrade() -> None:
    op.drop_index("ix_blueprint_run_markers_run", table_name="blueprint_run_markers")
    op.drop_table("blueprint_run_markers")
    op.drop_index("ix_blueprint_runs_project_ended", table_name="blueprint_runs")
    op.drop_table("blueprint_runs")
```

- [ ] **Step 4: Esegui i test delle migrazioni**

```bash
python -m pytest tests/test_migrations.py -v
```

Atteso: tutti verdi, incluso
`test_the_orm_models_and_the_migrations_describe_the_same_schema`. Se quest'ultimo
fallisce, i due schemi divergono davvero (tipicamente il `server_default` o l'ordine
delle colonne): allinea il modello ORM alla migrazione, non il contrario.

- [ ] **Step 5: Commit**

```bash
git add starkeno/db.py migrations/versions/0006_esecuzioni_blueprint.py tests/test_migrations.py
git commit -m "feat: tabelle delle esecuzioni dichiarate, senza toccare agent_actions"
```

---

### Task 7: Le letture e le scritture in `db.py`

**Files:**
- Modify: `starkeno/db.py`
- Test: `tests/test_consuntivo_db.py` (nuovo)

**Interfaces:**
- Consumes: `BlueprintRun`, `BlueprintRunMarker` (Task 6);
  `starkeno.consuntivo.RigaOsservata`, `Marcatore`, `Esecuzione` (Task 1)
- Produces:
  - `apri_esecuzione(session, *, run_key, project, blueprint_hash, analysis_json, model_map_json, started_at) -> BlueprintRun`
  - `esecuzione_aperta(session, project) -> BlueprintRun | None`
  - `leggi_esecuzione(session, run_key) -> BlueprintRun | None`
  - `aggiungi_marcatore(session, run, *, node_id, declared_at) -> BlueprintRunMarker`
  - `chiudi_esecuzione(session, run, *, ended_at, model_map_json=None) -> None`
  - `aggiorna_mappatura(session, run, *, model_map_json) -> None`
  - `marcatori_di(session, run) -> list[Marcatore]`
  - `righe_nella_finestra(session, project, inizio, fine) -> list[RigaOsservata]`
  - `elenca_esecuzioni(session, limite=20) -> list[BlueprintRun]`
  - `esecuzione_snapshot(run) -> Esecuzione`

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `tests/test_consuntivo_db.py`:

```python
"""Le due tabelle nuove, su database usa e getta. Nessun test tocca il database reale."""
from datetime import datetime, timedelta, timezone

import pytest

from starkeno import db

INIZIO = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


def _apri(session, *, progetto="progetto", chiave="k1"):
    return db.apri_esecuzione(
        session, run_key=chiave, project=progetto, blueprint_hash="h",
        analysis_json="{}", model_map_json="{}", started_at=INIZIO,
    )


def test_una_esecuzione_aperta_si_ritrova_per_progetto(session):
    _apri(session)

    assert db.esecuzione_aperta(session, "progetto") is not None
    assert db.esecuzione_aperta(session, "altro") is None


def test_una_esecuzione_chiusa_non_risulta_piu_aperta(session):
    run = _apri(session)

    db.chiudi_esecuzione(session, run, ended_at=INIZIO + timedelta(hours=1))

    assert db.esecuzione_aperta(session, "progetto") is None


def test_il_progetto_si_normalizza_come_le_righe_raccolte(session):
    """Senza, un `project` con maiuscole o spazi non incrocia mai le righe raccolte."""
    _apri(session, progetto="  Progetto  ")

    assert db.esecuzione_aperta(session, db.normalizza_progetto("Progetto")) is not None


def test_seq_dei_marcatori_e_progressivo_e_non_arriva_dal_chiamante(session):
    """La regressione: due marcatori con lo stesso `declared_at` e lo stesso `seq`,
    ordinati a caso, con l'intervallo fra i due sul nodo sbagliato."""
    run = _apri(session)

    primo = db.aggiungi_marcatore(session, run, node_id="draft", declared_at=INIZIO)
    secondo = db.aggiungi_marcatore(session, run, node_id="review", declared_at=INIZIO)

    assert (primo.seq, secondo.seq) == (1, 2)


def test_i_marcatori_tornano_come_snapshot_puri_ordinati(session):
    run = _apri(session)
    db.aggiungi_marcatore(session, run, node_id="review", declared_at=INIZIO + timedelta(minutes=10))
    db.aggiungi_marcatore(session, run, node_id="draft", declared_at=INIZIO)

    letti = db.marcatori_di(session, run)

    assert [m.node_id for m in letti] == ["draft", "review"]
    assert letti[0].declared_at.tzinfo is not None


def test_righe_nella_finestra_filtra_progetto_e_intervallo(session):
    for minuti, progetto in ((5, "progetto"), (5, "altro"), (500, "progetto")):
        db.scrivi_chiamate(session, [_chiamata(minuti, progetto)])

    righe = db.righe_nella_finestra(
        session, "progetto", INIZIO, INIZIO + timedelta(hours=1)
    )

    assert len(righe) == 1
    assert righe[0].timestamp.tzinfo is not None


def _chiamata(minuti, progetto):
    from starkeno.transcript import Chiamata

    quando = INIZIO + timedelta(minutes=minuti)
    return Chiamata(
        session_id="s1", message_id="m%d%s" % (minuti, progetto),
        timestamp=quando.isoformat(), project=progetto, action="read",
        model_used="opus", input_tokens=600, cache_read_tokens=100,
        cache_write_tokens=100, output_tokens=200, azione_fallita=0, esito_noto=1,
        azioni_nella_chiamata=1, skill="", plugin="", mcp_server="", is_sidechain=0,
    )


def test_la_mappatura_si_aggiorna_anche_su_un_esecuzione_chiusa(session):
    """E' il ciclo utile: il confronto elenca i modelli non mappati, li dichiari, e
    ricalcoli. La regressione: la mappatura tardiva viene ignorata in silenzio e il
    confronto continua a dire «moneta ignota» per sempre."""
    run = _apri(session)
    db.chiudi_esecuzione(session, run, ended_at=INIZIO + timedelta(hours=1))

    db.aggiorna_mappatura(session, run, model_map_json='{"opus-4": "economy"}')

    assert db.esecuzione_snapshot(run).model_map == {"opus-4": "economy"}


def test_chiudere_prima_di_aprire_e_rifiutato(session):
    """Un orologio che torna indietro non deve produrre una finestra negativa."""
    run = _apri(session)

    with pytest.raises(ValueError):
        db.chiudi_esecuzione(session, run, ended_at=INIZIO - timedelta(minutes=1))

    assert db.esecuzione_aperta(session, "progetto") is not None
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
python -m pytest tests/test_consuntivo_db.py -v
```

Atteso: `AttributeError: module 'starkeno.db' has no attribute 'apri_esecuzione'`.

- [ ] **Step 3: Scrivi l'implementazione minima**

In `starkeno/db.py`, aggiungi all'import dei tipi puri in cima:

```python
from starkeno.consuntivo import Esecuzione, Marcatore, RigaOsservata
```

e in fondo al file:

```python
# ============================================= le esecuzioni dichiarate di un Blueprint


def apri_esecuzione(session: Session, *, run_key: str, project: str,
                    blueprint_hash: str, analysis_json: str, model_map_json: str,
                    started_at: datetime) -> BlueprintRun:
    """Apre un'esecuzione. Il chiamante ha gia' verificato che non ce ne sia una aperta."""
    run = BlueprintRun(
        run_key=run_key, project=normalizza_progetto(project),
        blueprint_hash=blueprint_hash, analysis_json=analysis_json,
        model_map_json=model_map_json, started_at=started_at, ended_at=None,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def esecuzione_aperta(session: Session, project: str) -> BlueprintRun | None:
    """L'esecuzione aperta su questo progetto, se c'e'.

    Un'esecuzione aperta e dimenticata e' un aspirapolvere: si prenderebbe ogni chiamata
    successiva del progetto. Aprirne una seconda va rifiutato, e questa e' la lookup.
    """
    return (session.query(BlueprintRun)
            .filter(BlueprintRun.project == normalizza_progetto(project),
                    BlueprintRun.ended_at.is_(None))
            .order_by(BlueprintRun.id.desc())
            .first())


def leggi_esecuzione(session: Session, run_key: str) -> BlueprintRun | None:
    return session.query(BlueprintRun).filter(BlueprintRun.run_key == run_key).first()


def aggiungi_marcatore(session: Session, run: BlueprintRun, *, node_id: str,
                       declared_at: datetime) -> BlueprintRunMarker:
    """Aggiunge un marcatore assegnando `seq` come massimo corrente piu' uno.

    `seq` non arriva mai dal chiamante: due marcatori con lo stesso `declared_at`
    andrebbero altrimenti in ordine arbitrario, e l'intervallo fra i due finirebbe sul
    nodo sbagliato.
    """
    massimo = (session.query(func.max(BlueprintRunMarker.seq))
               .filter(BlueprintRunMarker.run_id == run.id).scalar()) or 0
    marcatore = BlueprintRunMarker(
        run_id=run.id, node_id=node_id, declared_at=declared_at, seq=massimo + 1,
    )
    session.add(marcatore)
    session.commit()
    session.refresh(marcatore)
    return marcatore


def chiudi_esecuzione(session: Session, run: BlueprintRun, *, ended_at: datetime,
                      model_map_json: str | None = None) -> None:
    """Chiude l'esecuzione. `model_map_json` omessa lascia invariata quella esistente."""
    if ended_at < run.started_at:
        raise ValueError(
            "ended_at (%s) e' anteriore a started_at (%s): la finestra sarebbe negativa"
            % (ended_at.isoformat(), run.started_at.isoformat())
        )
    run.ended_at = ended_at
    if model_map_json is not None:
        run.model_map_json = model_map_json
    session.commit()


def aggiorna_mappatura(session: Session, run: BlueprintRun, *,
                       model_map_json: str) -> None:
    """Sostituisce la mappatura modello→profilo, anche su un'esecuzione gia' chiusa.

    Il confronto elenca i modelli osservati che nessuna mappatura copre; dichiararli e
    ricalcolare e' il ciclo previsto. Nessuna riga raccolta viene toccata: l'attribuzione
    e' una vista, non un timbro.
    """
    run.model_map_json = model_map_json
    session.commit()


def marcatori_di(session: Session, run: BlueprintRun) -> list[Marcatore]:
    righe = (session.query(BlueprintRunMarker)
             .filter(BlueprintRunMarker.run_id == run.id)
             .order_by(BlueprintRunMarker.declared_at.asc(),
                       BlueprintRunMarker.seq.asc())
             .all())
    return [Marcatore(node_id=r.node_id, declared_at=r.declared_at, seq=r.seq)
            for r in righe]


def righe_nella_finestra(session: Session, project: str, inizio: datetime,
                         fine: datetime) -> list[RigaOsservata]:
    """Pre-filtro indicizzato. La finestra AUTOREVOLE resta `consuntivo.attribuisci`."""
    righe = (session.query(AgentAction)
             .filter(AgentAction.project == normalizza_progetto(project),
                     AgentAction.timestamp >= inizio,
                     AgentAction.timestamp <= fine)
             .order_by(AgentAction.timestamp.asc(), AgentAction.id.asc())
             .all())
    return [RigaOsservata(
        session_id=r.session_id, timestamp=r.timestamp, model_used=r.model_used,
        tokens_used=r.tokens_used, cache_read_tokens=r.cache_read_tokens,
        cache_write_tokens=r.cache_write_tokens, output_tokens=r.output_tokens,
        azioni_nella_chiamata=r.azioni_nella_chiamata,
    ) for r in righe]


def elenca_esecuzioni(session: Session, limite: int = 20) -> list[BlueprintRun]:
    return (session.query(BlueprintRun)
            .order_by(BlueprintRun.id.desc()).limit(limite).all())


def esecuzione_snapshot(run: BlueprintRun) -> Esecuzione:
    """Il perimetro come dato puro, pronto per `consuntivo.attribuisci`."""
    return Esecuzione(
        run_key=run.run_key, project=run.project, blueprint_hash=run.blueprint_hash,
        started_at=run.started_at, ended_at=run.ended_at,
        model_map=json.loads(run.model_map_json or "{}"),
    )
```

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
python -m pytest tests/test_consuntivo_db.py tests/test_db.py -v
```

Atteso: tutti verdi. Se la fixture `nessuna_connessione_lasciata_aperta` fa fallire un
test, una sessione o un engine non sono stati chiusi: `session.close()` **e**
`engine.dispose()`.

- [ ] **Step 5: Commit**

```bash
git add starkeno/db.py tests/test_consuntivo_db.py
git commit -m "feat: letture e scritture delle esecuzioni dichiarate"
```

---

### Task 8: I tre tool MCP e la guardia «Preflight è offline»

**Files:**
- Modify: `starkeno/mcp_server.py`
- Modify: `tests/test_mcp_server.py:154` (estendere la guardia)

**Interfaces:**
- Consumes: tutto `starkeno.consuntivo`; le funzioni `db.*` del Task 7;
  `starkeno.preflight_schema.Blueprint`; `starkeno.preflight_simulate.SimulationReport`
- Produces: `blueprint_run_start_impl(analysis_path, project, model_map=None) -> str`,
  `blueprint_run_node_impl(run_key, node_id) -> str`,
  `blueprint_run_end_impl(run_key, model_map=None) -> str`, più i tre tool `@mcp.tool()`
  omonimi senza `_impl`

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi a `tests/test_mcp_server.py`:

```python
def _analisi_json(tmp_path):
    """Scrive un'analisi vera con `starkeno preflight analyze`, non un JSON finto."""
    import json as _json

    from starkeno.preflight_report import PreflightAnalysis, render_analysis
    from starkeno.preflight_schema import Blueprint
    from starkeno.preflight_simulate import simulate_blueprint

    payload = _json.loads(
        (Path(__file__).parent / "fixtures" / "preflight" / "minimal.json").read_text(
            encoding="utf-8"
        )
    )
    payload["confirmed"] = True
    blueprint = Blueprint.model_validate(payload)
    analisi = PreflightAnalysis(
        blueprint=blueprint, findings=(),
        simulation=simulate_blueprint(blueprint, samples=8, seed=7), source_path=None,
    )
    percorso = tmp_path / "analisi.json"
    percorso.write_text(render_analysis(analisi, format="json"), encoding="utf-8")
    return percorso


def test_blueprint_run_start_rifiuta_una_seconda_esecuzione_aperta(
    session_factory, tmp_path, monkeypatch
):
    """Un'esecuzione dimenticata aperta si prenderebbe ogni chiamata successiva."""
    monkeypatch.setattr(mcp_server_module, "get_session_factory", lambda: session_factory)
    monkeypatch.chdir(tmp_path)
    analisi = _analisi_json(tmp_path)

    prima = mcp_server_module.blueprint_run_start_impl(str(analisi), "progetto")
    seconda = mcp_server_module.blueprint_run_start_impl(str(analisi), "progetto")

    assert "run_key" in prima
    assert "un'esecuzione aperta" in seconda
    assert "blueprint_run_end" in seconda


def test_blueprint_run_node_rifiuta_un_nodo_fuori_dal_blueprint(
    session_factory, tmp_path, monkeypatch
):
    """Il messaggio deve elencare gli id validi: l'agente li usa per correggersi da solo."""
    monkeypatch.setattr(mcp_server_module, "get_session_factory", lambda: session_factory)
    monkeypatch.chdir(tmp_path)
    analisi = _analisi_json(tmp_path)
    avvio = mcp_server_module.blueprint_run_start_impl(str(analisi), "progetto")
    chiave = avvio.split("run_key: ")[1].split()[0]

    risposta = mcp_server_module.blueprint_run_node_impl(chiave, "inesistente")

    assert "draft" in risposta and "review" in risposta


def test_blueprint_run_start_confina_il_percorso_alla_working_directory(
    session_factory, tmp_path, monkeypatch
):
    """`analysis_path` lo sceglie l'agente: fuori dalla radice non si legge."""
    monkeypatch.setattr(mcp_server_module, "get_session_factory", lambda: session_factory)
    fuori = tmp_path / "fuori"
    fuori.mkdir()
    analisi = _analisi_json(fuori)
    dentro = tmp_path / "dentro"
    dentro.mkdir()
    monkeypatch.chdir(dentro)

    risposta = mcp_server_module.blueprint_run_start_impl(str(analisi), "progetto")

    assert "outside" in risposta or "fuori" in risposta


def test_blueprint_run_end_restituisce_il_consuntivo(
    session_factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(mcp_server_module, "get_session_factory", lambda: session_factory)
    monkeypatch.chdir(tmp_path)
    analisi = _analisi_json(tmp_path)
    avvio = mcp_server_module.blueprint_run_start_impl(str(analisi), "progetto")
    chiave = avvio.split("run_key: ")[1].split()[0]
    mcp_server_module.blueprint_run_node_impl(chiave, "draft")

    risposta = mcp_server_module.blueprint_run_end_impl(chiave)

    assert "Consuntivo" in risposta
    assert "senza_osservazioni" in risposta


def test_una_chiave_sconosciuta_non_solleva(session_factory, monkeypatch):
    """Nessuno di questi tool solleva: l'errore torna come testo, come save_draft."""
    monkeypatch.setattr(mcp_server_module, "get_session_factory", lambda: session_factory)

    risposta = mcp_server_module.blueprint_run_node_impl("mai-vista", "draft")

    assert isinstance(risposta, str) and "mai-vista" in risposta
```

E **estendi la guardia esistente**, sostituendo il corpo di
`test_preflight_save_draft_impl_non_tocca_il_database` con:

```python
def test_i_tool_preflight_non_toccano_il_database(tmp_path, monkeypatch):
    """Preflight e' offline: NESSUNO dei due tool deve chiamare `get_session_factory`.

    Prima questo test dichiarava di coprirli entrambi e ne esercitava uno. Da quando
    `blueprint_run_*` tocca il database accanto a loro, e' la guardia che tiene separate
    osservazione e predizione: va esercitata su entrambi davvero.
    """
    def esplode():
        raise AssertionError("i tool Preflight non devono toccare il database")

    monkeypatch.setattr(mcp_server_module, "get_session_factory", esplode)
    monkeypatch.chdir(tmp_path)

    compito = mcp_server_module.preflight_interpretation_task_impl("Scrivi una nota.")
    assert isinstance(compito, str) and compito

    output = tmp_path / "draft.json"
    risposta = mcp_server_module.preflight_save_draft_impl(
        _interpretazione_valida(), str(output)
    )

    assert output.exists()
    assert "Draft salvato" in risposta
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
python -m pytest tests/test_mcp_server.py -v
```

Atteso: `AttributeError: module 'starkeno.mcp_server' has no attribute 'blueprint_run_start_impl'`.

- [ ] **Step 3: Scrivi l'implementazione minima**

In `starkeno/mcp_server.py`, sostituisci `_confina_output_path` con la coppia che
condivide il nucleo (il messaggio cambia, la regola no):

```python
def _dentro_la_radice(percorso: str) -> tuple[Path | None, Path, Path]:
    """Risolve `percorso` e dice se sta dentro la working directory del server.

    `Path.resolve()` normalizza sia i `..` sia i symlink, quindi il confronto va fatto
    DOPO la risoluzione — mai sulla stringa grezza, che i `..` la aggirerebbero.
    """
    radice = Path.cwd().resolve()
    risolto = Path(percorso).resolve()
    if not risolto.is_relative_to(radice):
        return None, risolto, radice
    return risolto, risolto, radice


def _confina_output_path(output_path: str) -> tuple[Path | None, str]:
    """Come sopra, per una SCRITTURA. Il messaggio dice che non e' stato scritto nulla."""
    dentro, risolto, radice = _dentro_la_radice(output_path)
    if dentro is None:
        return None, (
            f"Path error, nothing was written: `output_path` ({output_path}) resolves to "
            f"{risolto}, which is outside the server's working directory ({radice}).\n"
            "Pass an `output_path` that resolves inside the working directory — a relative "
            "path, or an absolute path already under it — and call preflight_save_draft "
            "again."
        )
    return dentro, ""


def _confina_input_path(input_path: str) -> tuple[Path | None, str]:
    """Come sopra, per una LETTURA. Il percorso lo sceglie l'agente anche qui."""
    dentro, risolto, radice = _dentro_la_radice(input_path)
    if dentro is None:
        return None, (
            f"Path error, nothing was read: ({input_path}) resolves to {risolto}, which "
            f"is outside the server's working directory ({radice}).\n"
            "Pass a path that resolves inside the working directory and call again."
        )
    return dentro, ""
```

Poi, in fondo al file prima del blocco `if __name__ == "__main__":`:

```python
# ========================================================== il consuntivo di un'esecuzione
#
# Questi tre tool TOCCANO il database, e non e' un'incoerenza con i due Preflight qui
# sopra: sono OSSERVAZIONE, non predizione, e stanno accanto a `log_agent_action`.
#
# Non sono fail-open come gli hook, ed e' deliberato. Un hook silenzioso protegge il
# turno dell'utente; un marcatore perso in silenzio produce un'attribuzione SBAGLIATA,
# che e' il danno peggiore di tutti. Qui un errore si dichiara — come testo, mai come
# eccezione.


def _carica_analisi(percorso: Path):
    """Legge il preventivo e ne valida i due sotto-oggetti che servono al confronto."""
    import json as _json

    from starkeno.preflight_schema import Blueprint
    from starkeno.preflight_simulate import SimulationReport

    testo = percorso.read_text(encoding="utf-8")
    payload = _json.loads(testo)
    if not isinstance(payload, dict) or "simulation" not in payload:
        raise ValueError(
            "il file non e' un'analisi Preflight: manca la chiave 'simulation'"
        )
    blueprint = Blueprint.model_validate(payload["blueprint"])
    simulazione = SimulationReport.model_validate(payload["simulation"])
    return testo, blueprint, simulazione


def blueprint_run_start_impl(analysis_path: str, project: str,
                             model_map: str | None = None) -> str:
    import json as _json
    import uuid
    from datetime import datetime, timezone

    percorso, errore = _confina_input_path(analysis_path)
    if percorso is None:
        return errore
    try:
        testo, _blueprint, simulazione = _carica_analisi(percorso)
    except (OSError, ValueError, UnicodeError) as errore_analisi:
        motivo = " ".join(str(errore_analisi).splitlines())
        return (
            "Analysis error, nothing was recorded: " + motivo + "\n"
            "Produce the analysis with `starkeno preflight analyze --confirmed "
            "--format json` and call blueprint_run_start again with its path."
        )
    try:
        mappa = _json.loads(model_map) if model_map else {}
        if not isinstance(mappa, dict):
            raise ValueError("model_map deve essere un oggetto JSON")
    except ValueError as errore_mappa:
        return "model_map error, nothing was recorded: %s" % errore_mappa

    session = get_session_factory()()
    try:
        aperta = db.esecuzione_aperta(session, project)
        if aperta is not None:
            return (
                "Run error, nothing was recorded: c'e' gia' un'esecuzione aperta su "
                "questo progetto (run_key: %s, aperta il %s).\n"
                "Chiudila con blueprint_run_end prima di aprirne un'altra: "
                "un'esecuzione dimenticata aperta si prende ogni chiamata successiva "
                "del progetto." % (aperta.run_key, aperta.started_at.isoformat())
            )
        run = db.apri_esecuzione(
            session, run_key=uuid.uuid4().hex, project=project,
            blueprint_hash=simulazione.blueprint_hash, analysis_json=testo,
            model_map_json=_json.dumps(mappa), started_at=datetime.now(timezone.utc),
        )
        return (
            "Esecuzione aperta — run_key: %s\n"
            "Dichiara ogni cambio di nodo con blueprint_run_node, e chiudi con "
            "blueprint_run_end. Le chiamate fuori da un intervallo dichiarato "
            "risulteranno non attribuite invece di essere indovinate." % run.run_key
        )
    finally:
        session.close()


def blueprint_run_node_impl(run_key: str, node_id: str) -> str:
    from datetime import datetime, timezone

    session = get_session_factory()()
    try:
        run = db.leggi_esecuzione(session, run_key)
        if run is None:
            return "Run error, nothing was recorded: run_key sconosciuta (%s)." % run_key
        if run.ended_at is not None:
            return (
                "Run error, nothing was recorded: l'esecuzione %s e' gia' chiusa (%s)."
                % (run_key, run.ended_at.isoformat())
            )
        try:
            _testo, blueprint, _simulazione = _carica_analisi_da_testo(run.analysis_json)
        except ValueError as errore:
            return "Run error, nothing was recorded: %s" % errore
        validi = tuple(nodo.id for nodo in blueprint.nodes)
        if node_id not in validi:
            return (
                "Node error, nothing was recorded: '%s' non e' un nodo di questo "
                "Blueprint. Nodi validi: %s." % (node_id, ", ".join(validi))
            )
        db.aggiungi_marcatore(
            session, run, node_id=node_id, declared_at=datetime.now(timezone.utc)
        )
        return "Nodo corrente: %s (esecuzione %s)." % (node_id, run_key)
    finally:
        session.close()


def _carica_analisi_da_testo(testo: str):
    """Come `_carica_analisi`, ma su un testo gia' conservato nel database."""
    import json as _json

    from starkeno.preflight_schema import Blueprint
    from starkeno.preflight_simulate import SimulationReport

    payload = _json.loads(testo)
    return (
        testo,
        Blueprint.model_validate(payload["blueprint"]),
        SimulationReport.model_validate(payload["simulation"]),
    )


def blueprint_run_end_impl(run_key: str, model_map: str | None = None) -> str:
    import json as _json
    from datetime import datetime, timezone

    from starkeno import consuntivo as consuntivo_modulo

    session = get_session_factory()()
    try:
        run = db.leggi_esecuzione(session, run_key)
        if run is None:
            return "Run error, nothing was recorded: run_key sconosciuta (%s)." % run_key
        # La mappatura si aggiorna ANCHE su un'esecuzione gia' chiusa: e' il ciclo
        # utile. Il primo confronto elenca i modelli non mappati, tu li dichiari, e
        # richiami questo tool per ricalcolare. L'attribuzione e' una vista: ricalcolarla
        # non tocca nessuna riga raccolta.
        mappa_json = None
        if model_map:
            try:
                mappa = _json.loads(model_map)
                if not isinstance(mappa, dict):
                    raise ValueError("model_map deve essere un oggetto JSON")
                mappa_json = _json.dumps(mappa)
            except ValueError as errore_mappa:
                return "model_map error, nothing was recorded: %s" % errore_mappa

        if run.ended_at is None:
            try:
                db.chiudi_esecuzione(
                    session, run, ended_at=datetime.now(timezone.utc),
                    model_map_json=mappa_json,
                )
            except ValueError as errore:
                return "Run error, nothing was recorded: %s" % errore
        elif mappa_json is not None:
            db.aggiorna_mappatura(session, run, model_map_json=mappa_json)

        _testo, blueprint, simulazione = _carica_analisi_da_testo(run.analysis_json)
        esecuzione = db.esecuzione_snapshot(run)
        righe = db.righe_nella_finestra(
            session, run.project, run.started_at, run.ended_at
        )
        attribuzione = consuntivo_modulo.attribuisci(
            esecuzione, db.marcatori_di(session, run), righe
        )
        return consuntivo_modulo.rendi_testo(consuntivo_modulo.costruisci(
            esecuzione, attribuzione, simulazione, blueprint
        ))
    finally:
        session.close()


@mcp.tool()
def blueprint_run_start(analysis_path: str, project: str,
                        model_map: str | None = None) -> str:
    """Open a Blueprint run and return its `run_key`.

    `analysis_path` is the JSON analysis produced by `starkeno preflight analyze
    --confirmed --format json`. It is stored verbatim: the run is compared against the
    estimate you were actually shown, not one recomputed later.

    READS ARE CONFINED to the server's current working directory, `..` and symlinks
    resolved first. `project` must be the last path segment of the working directory
    the agent is running in — it is how collected calls are matched.

    `model_map` is an optional JSON object mapping the OBSERVED model name to a
    `models[].id` of the Blueprint, e.g. `{"claude-opus-4": "opus"}`. Without it the
    comparison still counts tokens and declares the money unknown; it never guesses.

    THIS TOOL DOES NOT RAISE. Errors — an analysis that will not load, a path outside
    the working directory, a run already open on this project — come back as plain
    text and nothing is recorded. Read the message, fix the argument yourself and call
    again.
    """
    return blueprint_run_start_impl(analysis_path, project, model_map)


@mcp.tool()
def blueprint_run_node(run_key: str, node_id: str) -> str:
    """Declare that work is moving to node `node_id` of the running Blueprint.

    Call this EVERY time you start working on a different node. Calls that fall
    outside any declared interval are reported as unattributed rather than assigned to
    a neighbouring node: a number attributed to the wrong node is worse than one left
    unattributed, because it sends the calibration in the wrong direction.

    `node_id` is validated against the Blueprint stored with the run. An unknown id is
    rejected and the message lists the valid ones.

    THIS TOOL DOES NOT RAISE. Errors come back as plain text and nothing is recorded.
    """
    return blueprint_run_node_impl(run_key, node_id)


@mcp.tool()
def blueprint_run_end(run_key: str, model_map: str | None = None) -> str:
    """Close the run and return the comparison between the estimate and what was spent.

    `model_map` REPLACES the one given at `blueprint_run_start` when provided; omit it
    to leave the existing one unchanged.

    The returned text states where the observed total falls inside the estimated band,
    the per-node deltas ordered by size, and what it refuses to attribute and why.
    Estimated node invocations and observed API calls are printed side by side and
    never subtracted: they are different units.

    Calling it again on an already closed run recomputes the comparison without
    changing anything — attribution is a view, not a stamp on the collected rows.

    THIS TOOL DOES NOT RAISE. Errors come back as plain text.
    """
    return blueprint_run_end_impl(run_key, model_map)
```

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
python -m pytest tests/test_mcp_server.py tests/test_mcp_warning.py -v
```

Atteso: tutti verdi.

- [ ] **Step 5: Commit**

```bash
git add starkeno/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: i tre tool dell'esecuzione, e la guardia che tiene Preflight offline"
```

---

### Task 9: Il comando `starkeno consuntivo`

**Files:**
- Modify: `starkeno/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `db.elenca_esecuzioni`, `db.leggi_esecuzione`, `db.marcatori_di`,
  `db.righe_nella_finestra`, `db.esecuzione_snapshot` (Task 7); `consuntivo.*` (Task 1-5)
- Produces: il sottocomando `consuntivo` di `starkeno`

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi a `tests/test_cli.py`:

```python
def test_consuntivo_elenco_su_database_vuoto(tmp_path, monkeypatch, capsys):
    """Nessuna esecuzione non e' un errore: e' un'informazione."""
    from starkeno import cli
    from starkeno.hook_ingestione import prepara_database

    percorso = tmp_path / "vuoto.db"
    prepara_database(str(percorso), silenzioso=True)
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))

    codice = cli.main(["consuntivo", "--elenco"])

    assert codice == 0
    assert "Nessuna esecuzione" in capsys.readouterr().out


def test_consuntivo_su_chiave_sconosciuta_esce_2(tmp_path, monkeypatch, capsys):
    from starkeno import cli
    from starkeno.hook_ingestione import prepara_database

    percorso = tmp_path / "vuoto.db"
    prepara_database(str(percorso), silenzioso=True)
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))

    codice = cli.main(["consuntivo", "--run", "mai-vista"])

    assert codice == 2
    assert "mai-vista" in capsys.readouterr().err
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
python -m pytest tests/test_cli.py -k consuntivo -v
```

Atteso: FAIL — `argument comando: invalid choice: 'consuntivo'`.

- [ ] **Step 3: Scrivi l'implementazione minima**

In `starkeno/cli.py`, dentro `_parser()` prima del `return parser`:

```python
    consuntivo = comandi.add_parser(
        "consuntivo", help="confronta un'esecuzione con il preventivo che la prevedeva")
    consuntivo.add_argument("--run", dest="run_key")
    consuntivo.add_argument("--elenco", action="store_true")
    consuntivo.add_argument("--json", action="store_true", dest="json_output")
```

In `main()`, subito dopo il ramo `preflight`:

```python
    if argomenti.comando == "consuntivo":
        return _esegui_consuntivo(argomenti)
```

E in fondo al file:

```python
def _esegui_consuntivo(argomenti) -> int:
    """Il confronto, guardato senza passare dall'agente e senza spenderne i token.

    Import differito come per `preflight`: il confronto carica pydantic, inutile a
    `doctor` e `report`.
    """
    import json as _json

    from starkeno import consuntivo as consuntivo_modulo, db

    if not argomenti.run_key and not argomenti.elenco:
        print("Errore: serve --run <chiave> oppure --elenco", file=sys.stderr)
        return 2

    fabbrica = db.make_readonly_session_factory(str(_database_runtime()))
    sessione = fabbrica()
    try:
        if argomenti.elenco:
            esecuzioni = db.elenca_esecuzioni(sessione)
            if not esecuzioni:
                print("Nessuna esecuzione registrata.")
                return 0
            for run in esecuzioni:
                print("%s  %-20s %s  %s" % (
                    run.run_key, run.project, run.started_at.isoformat(),
                    run.ended_at.isoformat() if run.ended_at else "aperta",
                ))
            return 0

        run = db.leggi_esecuzione(sessione, argomenti.run_key)
        if run is None:
            print("Errore: run_key sconosciuta (%s)" % argomenti.run_key,
                  file=sys.stderr)
            return 2

        payload = _json.loads(run.analysis_json)
        from starkeno.preflight_schema import Blueprint
        from starkeno.preflight_simulate import SimulationReport

        blueprint = Blueprint.model_validate(payload["blueprint"])
        simulazione = SimulationReport.model_validate(payload["simulation"])
        esecuzione = db.esecuzione_snapshot(run)
        righe = (
            db.righe_nella_finestra(sessione, run.project, run.started_at, run.ended_at)
            if run.ended_at is not None else []
        )
        attribuzione = consuntivo_modulo.attribuisci(
            esecuzione, db.marcatori_di(sessione, run), righe
        )
        risultato = consuntivo_modulo.costruisci(
            esecuzione, attribuzione, simulazione, blueprint
        )
        if argomenti.json_output:
            print(_json.dumps(asdict(risultato), ensure_ascii=False, indent=2,
                              default=str))
        else:
            print(consuntivo_modulo.rendi_testo(risultato))
        return 0
    finally:
        sessione.close()
        fabbrica.kw["bind"].dispose()
```

Aggiungi `import sys` in cima a `cli.py` se non c'è già.

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
python -m pytest tests/test_cli.py -v
```

Atteso: tutti verdi.

- [ ] **Step 5: Commit**

```bash
git add starkeno/cli.py tests/test_cli.py
git commit -m "feat: starkeno consuntivo, per guardare il confronto senza spendere token"
```

---

### Task 10: La documentazione e la verifica finale

**Files:**
- Modify: `AGENTS.md` (sezioni «Architettura» e «Invarianti tecnici»)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: tutto quanto sopra
- Produces: nessuna interfaccia di codice

- [ ] **Step 1: Aggiorna `AGENTS.md`**

In «Architettura», dopo la riga di `starkeno/conto.py`:

```markdown
- `starkeno/consuntivo.py`: modello puro del confronto fra un preventivo e l'esecuzione
  osservata; nessuna dipendenza da SQLAlchemy, orologio o filesystem.
```

In «Invarianti tecnici», in fondo:

```markdown
15. L'attribuzione di una chiamata a un nodo di un Blueprint e' una VISTA calcolata al
    momento del confronto, mai una colonna su `agent_actions`. L'hook non conosce i
    Blueprint, e una dichiarazione sbagliata si corregge ricalcolando.
16. Quando l'attribuzione e' incerta si dichiara: piu' di una sessione nella finestra
    ferma il confronto invece di sommare, e i conteggi di chiamate stimati e osservati
    si stampano affiancati senza mai sottrarsi, perche' contano unita' diverse.
```

- [ ] **Step 2: Aggiorna `CHANGELOG.md`**

Aggiungi in cima alla sezione non rilasciata:

```markdown
- Consuntivo di un'esecuzione: tre tool MCP (`blueprint_run_start`, `blueprint_run_node`,
  `blueprint_run_end`) e il comando `starkeno consuntivo` confrontano il preventivo di un
  Blueprint con le chiamate davvero raccolte, dichiarando cosa non sanno attribuire.
```

- [ ] **Step 3: Esegui la suite completa in modalità stretta**

```bash
python -m pytest -q -W error
```

Atteso: **almeno 601 passed più i nuovi test, 2 skipped**. Un fallimento sotto `-W error`
che non compare senza è quasi sempre una connessione SQLite lasciata aperta: vedi
l'invariante 14.

- [ ] **Step 4: Verifica gli altri controlli**

```bash
git diff --check
```

```bash
python scripts/verifica_segreti.py --tracked
```

```bash
python scripts/verifica_pubblicazione.py
```

Atteso: nessun output d'errore da tutti e tre.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md CHANGELOG.md
git commit -m "docs: registra il consuntivo e l'invariante dell'attribuzione come vista"
```

---

## Cosa NON fa questo piano

- **Non inizia la parte C.** Nessun tool esegue niente: i tre nuovi registrano
  dichiarazioni e leggono righe già raccolte.
- **Non fa la dashboard.** Viene dopo i primi feedback, per decisione dell'utente.
- **Non produce `measured`** (Passo 2), **non calibra i default** (Passo 3), **non
  controlla l'età dei prezzi** (Passo 4).
- **Non importa esecuzioni da n8n o Make.** StarkEno non le osserva, e nessuna riga di
  questo piano le fa comparire.
- **Non rimuove la dipendenza `anthropic`**, che resta una decisione separata.
