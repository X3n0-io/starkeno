# Fase 1 — I dati entrano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Far arrivare in `starkeno.db` le chiamate API vere lette dai transcript di Claude
Code, alla grana corretta, in un database che sopravvive agli aggiornamenti del plugin.

**Architecture:** Un hook di fine turno legge il file di transcript che Claude Code scrive
già da sé, lo riduce a una riga per `(sessionId, message.id)` e la scrive su SQLite. Il
lettore di transcript è un modulo **puro** — nessun database, nessun orologio — così la
regressione sul doppio conteggio si prova senza toccare il disco. Lo schema si estende in
coda; il database si sposta fuori dalla cartella del codice.

**Tech Stack:** Python 3.12, SQLAlchemy (solo in `db.py`), Alembic, pytest, hook di
Claude Code (JSON su stdin).

## Global Constraints

Copiati dagli invarianti del `CLAUDE.md` e dal design. **Valgono per ogni task.**

- **`db.py` è l'unico modulo che importa SQLAlchemy.** Vale anche per il codice nuovo.
- **Nessun modulo costruisce una session factory all'import.** Pattern `get_session_factory()` pigro.
- **I test non toccano mai `DB_PATH`.** Usare `STARKENO_DB_PATH` o `tmp_path`.
- **Le colonne nuove vanno IN CODA**, perché `ADD COLUMN` accoda: modelli ORM e migrazioni
  devono descrivere lo stesso ordine, o `test_the_orm_models_and_the_migrations_describe_the_same_schema` fallisce.
- **Ogni colonna temporale nuova usa `db.UTCDateTime`**, mai `DateTime` nudo.
- **Nel SQL scritto a mano i datetime si passano con `db.parametro_datetime`.**
- **Gli invarianti fra costanti sollevano, non usano `assert`** (`python -O` rimuove gli assert).
- **L'hook non deve mai rompere la sessione dell'utente:** uscita `0` sempre, niente rumore
  su stderr, timeout duro.
- **Mai `NULL` come «non lo so» su un booleano.** L'informazione «non lo so» ha la sua
  colonna (`esito_noto`), il booleano ha solo vero/falso.
- **`create_all()` solo in `tests/conftest.py`.**
- Migrazione corrente in produzione: **`0003`**. Le nuove sono `0004` e `0005`.

---

## Struttura dei file

| File | Responsabilità |
|---|---|
| `starkeno/percorsi.py` | **nuovo.** Dove vive il database, per piattaforma. Nessuna dipendenza |
| `starkeno/config.py` | modificato: `DB_PATH` prende il default da `percorsi.py` |
| `starkeno/trasloco.py` | **nuovo.** Trova un database vecchio accanto al codice e lo sposta |
| `migrations/versions/0004_progetto.py` | **nuovo.** `agent_name` → `project` |
| `migrations/versions/0005_ingestione.py` | **nuovo.** Le colonne che l'ingestione riempie |
| `starkeno/transcript.py` | **nuovo.** Da `.jsonl` a record. **Puro:** niente DB, niente orologio |
| `starkeno/db.py` | modificato: modelli aggiornati + `scrivi_chiamate()` idempotente |
| `starkeno/hook_ingestione.py` | **nuovo.** Il punto d'ingresso dell'hook. Esce sempre `0` |
| `plugin/hooks/hooks.json` | **nuovo.** La dichiarazione dell'hook per Claude Code |
| `tests/test_percorsi.py`, `test_trasloco.py`, `test_transcript.py`, `test_ingestione.py`, `test_hook.py` | **nuovi** |
| `tests/fixtures/transcript_vero.jsonl` | **nuovo.** Un transcript vero ridotto, con le righe attese |

`transcript.py` è separato da `hook_ingestione.py` di proposito: il primo è puro e si prova
in memoria, il secondo tocca il mondo. La regressione sul doppio conteggio — il difetto che
è costato 2,03× — vive tutta nel primo.

---

## Task 1: Il database esce dalla cartella del codice

**Files:**
- Create: `starkeno/percorsi.py`
- Modify: `starkeno/config.py:21-26`
- Test: `tests/test_percorsi.py`

**Interfaces:**
- Produces: `percorsi.cartella_dati() -> Path`, `percorsi.percorso_database() -> str`

- [x] **Step 1: Scrivere il test che fallisce**

```python
# tests/test_percorsi.py
"""Il database e' un bene dell'utente, non un file del programma.

Le cartelle dei plugin sono VERSIONATE: un aggiornamento ne crea una nuova, e con
essa lo storico dell'utente sparisce — senza errore, senza avviso, col conto che
riparte vuoto. Con il conto al centro del prodotto, perdere la storia e' perdere
il prodotto.
"""
from pathlib import Path

from starkeno import percorsi


def test_il_database_non_sta_dentro_la_cartella_del_codice():
    radice_codice = Path(percorsi.__file__).resolve().parent.parent
    db = Path(percorsi.percorso_database()).resolve()
    assert radice_codice not in db.parents, (
        "il database sta dentro il codice a %s: il primo aggiornamento del plugin "
        "cancellerebbe lo storico di chi lo usa" % db
    )


def test_la_cartella_dati_sta_sotto_la_home_dell_utente():
    assert Path.home() in percorsi.cartella_dati().parents or \
        percorsi.cartella_dati() == Path.home() / ".starkeno"


def test_la_variabile_di_ambiente_vince_sul_default(monkeypatch, tmp_path):
    """`STARKENO_DB_PATH` deve restare la giuntura: i test ci si appoggiano."""
    import importlib
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "altro.db"))
    from starkeno import config
    importlib.reload(config)
    assert config.DB_PATH == str(tmp_path / "altro.db")
    monkeypatch.delenv("STARKENO_DB_PATH")
    importlib.reload(config)
```

- [x] **Step 2: Eseguirlo per verificare che fallisca**

Run: `python -m pytest tests/test_percorsi.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'starkeno.percorsi'`

- [x] **Step 3: Scrivere `starkeno/percorsi.py`**

```python
"""Dove vivono i dati dell'utente.

Modulo senza dipendenze, di proposito: lo importa `config.py`, che tutto il resto
importa a sua volta. Una dipendenza qui si propagherebbe ovunque.
"""
import os
import sys
from pathlib import Path

NOME_DATABASE = "starkeno.db"


def cartella_dati() -> Path:
    """La cartella dati per utente, secondo la convenzione della piattaforma.

    NON accanto al codice: le cartelle dei plugin sono versionate e un aggiornamento
    ne crea una nuova. Il database deve sopravvivere agli aggiornamenti.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "StarkEno"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "StarkEno"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        if base:
            return Path(base) / "starkeno"
        return Path.home() / ".local" / "share" / "starkeno"
    # Ricaduta comune: se la variabile di piattaforma manca, la home c'e' sempre.
    return Path.home() / ".starkeno"


def percorso_database() -> str:
    """Il percorso del file, come stringa. NON crea la cartella.

    Crearla qui la creerebbe al primo `import`, cioe' anche a chi sta solo leggendo
    la documentazione con un `python -c`. La crea chi scrive davvero.
    """
    return str(cartella_dati() / NOME_DATABASE)


def assicura_cartella() -> Path:
    """Crea la cartella dati se manca, e la restituisce. La chiama chi scrive."""
    cartella = cartella_dati()
    cartella.mkdir(parents=True, exist_ok=True)
    return cartella
```

- [x] **Step 4: Modificare `starkeno/config.py`**

Sostituire il blocco `DB_PATH` esistente (righe 21-26) con:

```python
# Percorso del database. Override via STARKENO_DB_PATH: serve ai test (che non devono mai
# toccare il database di produzione) e a chi vuole spostarlo.
#
# Il DEFAULT sta fuori dalla cartella del codice, ed e' deliberato: le cartelle dei plugin
# sono versionate, un aggiornamento ne crea una nuova, e lo storico dell'utente sparirebbe
# senza errore e senza avviso. Vedi `starkeno/percorsi.py`.
DB_PATH = os.environ.get("STARKENO_DB_PATH", percorsi.percorso_database())
```

E aggiungere in cima, fra gli import: `from starkeno import percorsi`

- [x] **Step 5: Eseguire i test**

Run: `python -m pytest tests/test_percorsi.py -v`
Expected: PASS, 3 test

- [x] **Step 6: Eseguire la suite intera per vedere cosa si rompe**

Run: `python -m pytest -q`
Expected: PASS. Se qualcosa fallisce, è un test che leggeva `DB_PATH` invece di
`STARKENO_DB_PATH` — violazione dell'invariante 3, va corretto lì.

- [x] **Step 7: Commit**

```bash
git add starkeno/percorsi.py starkeno/config.py tests/test_percorsi.py
git commit -m "feat: il database esce dalla cartella del codice (fase 1, task 1)"
```

---

## Task 2: Lo storico di chi ha già un database si sposta con lui

**Files:**
- Create: `starkeno/trasloco.py`
- Test: `tests/test_trasloco.py`

**Interfaces:**
- Consumes: `percorsi.cartella_dati()`, `percorsi.percorso_database()` (Task 1)
- Produces: `trasloco.trasloca_se_serve(radice_codice: Path | None = None) -> str | None`
  — restituisce il percorso di destinazione se ha spostato qualcosa, `None` se non c'era
  niente da spostare.

- [x] **Step 1: Scrivere il test che fallisce**

```python
# tests/test_trasloco.py
"""Cambiare il default non basta: chi ha gia' un database va portato dietro.

Se la storia e' il prodotto, perderla all'aggiornamento e' perdere il prodotto.
"""
import sqlite3

import pytest

from starkeno import trasloco


def _database_finto(percorso, righe=1):
    con = sqlite3.connect(str(percorso))
    con.execute("CREATE TABLE agent_actions (id INTEGER PRIMARY KEY, agent_name TEXT)")
    for i in range(righe):
        con.execute("INSERT INTO agent_actions (agent_name) VALUES (?)", ("vecchio-%d" % i,))
    con.commit()
    con.close()


def test_sposta_il_database_vecchio_e_conserva_le_righe(tmp_path, monkeypatch):
    codice = tmp_path / "codice"
    codice.mkdir()
    _database_finto(codice / "starkeno.db", righe=3)

    dati = tmp_path / "dati"
    monkeypatch.setattr(trasloco.percorsi, "cartella_dati", lambda: dati)
    monkeypatch.setattr(trasloco.percorsi, "percorso_database", lambda: str(dati / "starkeno.db"))

    destinazione = trasloco.trasloca_se_serve(radice_codice=codice)

    assert destinazione == str(dati / "starkeno.db")
    con = sqlite3.connect(destinazione)
    assert con.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 3
    con.close()


def test_lascia_una_copia_di_sicurezza_invece_di_cancellare(tmp_path, monkeypatch):
    """Non si cancella mai l'originale: se il trasloco va storto, la storia c'e' ancora."""
    codice = tmp_path / "codice"
    codice.mkdir()
    _database_finto(codice / "starkeno.db")
    dati = tmp_path / "dati"
    monkeypatch.setattr(trasloco.percorsi, "cartella_dati", lambda: dati)
    monkeypatch.setattr(trasloco.percorsi, "percorso_database", lambda: str(dati / "starkeno.db"))

    trasloco.trasloca_se_serve(radice_codice=codice)

    assert (codice / "starkeno.db.trasferito").exists()
    assert not (codice / "starkeno.db").exists()


def test_eseguirlo_due_volte_non_fa_danni(tmp_path, monkeypatch):
    """Idempotenza: il trasloco gira a ogni avvio, non una volta sola."""
    codice = tmp_path / "codice"
    codice.mkdir()
    _database_finto(codice / "starkeno.db", righe=2)
    dati = tmp_path / "dati"
    monkeypatch.setattr(trasloco.percorsi, "cartella_dati", lambda: dati)
    monkeypatch.setattr(trasloco.percorsi, "percorso_database", lambda: str(dati / "starkeno.db"))

    trasloco.trasloca_se_serve(radice_codice=codice)
    secondo = trasloco.trasloca_se_serve(radice_codice=codice)

    assert secondo is None
    con = sqlite3.connect(str(dati / "starkeno.db"))
    assert con.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 2
    con.close()


def test_non_sovrascrive_un_database_gia_presente_a_destinazione(tmp_path, monkeypatch):
    """Il caso peggiore: due storici, e il trasloco ne cancella uno. Non deve succedere."""
    codice = tmp_path / "codice"
    codice.mkdir()
    _database_finto(codice / "starkeno.db", righe=1)
    dati = tmp_path / "dati"
    dati.mkdir()
    _database_finto(dati / "starkeno.db", righe=9)
    monkeypatch.setattr(trasloco.percorsi, "cartella_dati", lambda: dati)
    monkeypatch.setattr(trasloco.percorsi, "percorso_database", lambda: str(dati / "starkeno.db"))

    assert trasloco.trasloca_se_serve(radice_codice=codice) is None
    con = sqlite3.connect(str(dati / "starkeno.db"))
    assert con.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 9
    con.close()
```

- [x] **Step 2: Eseguirlo per verificare che fallisca**

Run: `python -m pytest tests/test_trasloco.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'starkeno.trasloco'`

- [x] **Step 3: Scrivere `starkeno/trasloco.py`**

```python
"""Porta dietro lo storico di chi aveva il database accanto al codice.

Cambiare il default di `DB_PATH` non basta: chi ha gia' usato StarkEno ha il file
nella vecchia posizione, e senza questo modulo il conto ripartirebbe vuoto — cioe'
esattamente il danno che spostare il database doveva evitare.
"""
import shutil
from pathlib import Path

from starkeno import percorsi

SUFFISSO_COPIA = ".trasferito"


def trasloca_se_serve(radice_codice: Path | None = None) -> str | None:
    """Sposta un database che sta accanto al codice nella cartella dati.

    Restituisce il percorso di destinazione se ha spostato qualcosa, `None` altrimenti.
    Idempotente: gira a ogni avvio.

    **Non cancella e non sovrascrive.** L'originale resta come `.trasferito`, e se a
    destinazione c'e' gia' un database non si tocca niente: fondere due storici non e'
    una cosa che si fa in silenzio.
    """
    if radice_codice is None:
        radice_codice = Path(__file__).resolve().parent.parent
    vecchio = Path(radice_codice) / percorsi.NOME_DATABASE
    if not vecchio.exists():
        return None

    destinazione = Path(percorsi.percorso_database())
    if destinazione.exists():
        return None

    destinazione.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vecchio, destinazione)
    # I file di appoggio di WAL: senza, una transazione non ancora consolidata resta
    # indietro e il database copiato perde le ultime scritture.
    for suffisso in ("-wal", "-shm"):
        compagno = vecchio.with_name(vecchio.name + suffisso)
        if compagno.exists():
            shutil.copy2(compagno, destinazione.with_name(destinazione.name + suffisso))
    vecchio.rename(vecchio.with_name(vecchio.name + SUFFISSO_COPIA))
    return str(destinazione)
```

- [x] **Step 4: Eseguire i test**

Run: `python -m pytest tests/test_trasloco.py -v`
Expected: PASS, 4 test

- [x] **Step 5: Commit**

```bash
git add starkeno/trasloco.py tests/test_trasloco.py
git commit -m "feat: lo storico si sposta insieme al database (fase 1, task 2)"
```

---

## Task 3: `agent_name` diventa `project`

> **Perché adesso e non dopo.** Il database di produzione ha **una riga**: rinominare oggi
> è una migrazione senza dati da preservare. Farlo dopo la pubblicazione significa migrare
> lo storico di chi ha installato il plugin. E ogni task successivo scrive codice nuovo:
> scriverlo sul nome vecchio vorrebbe dire riscriverlo.
>
> **Blast radius misurato: 244 occorrenze in 25 file.** È mecc­anico, ma va fatto tutto
> insieme o la suite resta rossa a metà.

**Files:**
- Create: `migrations/versions/0004_progetto.py`
- Modify: `starkeno/db.py` (73 occorrenze), `starkeno/mcp_server.py` (9),
  `starkeno/supervisor.py` (5), `starkeno/api.py` (5), `starkeno/rules.py` (1),
  `starkeno/config.py` (1), `starkeno/static/index.html` (3)
- Modify (test): tutti i file in `tests/` che nominano `agent_name`
- Test: `tests/test_migrations.py` (già esistente, deve continuare a passare)

**Interfaces:**
- Produces: `db.AgentAction.project`, `db.Alert.project`, `db.RuleStatus.project`,
  `db.AgentWatermark.project`; `db.record_action(session, project=..., ...)`;
  indice `ix_actions_project_time`.

- [x] **Step 1: Scrivere la migrazione `0004`**

```python
# migrations/versions/0004_progetto.py
"""v2: l'asse non e' l'utente, e' il progetto

In locale l'utente e' una COSTANTE: una colonna che conterrebbe sempre lo stesso valore
non distingue niente. L'asse utile lo porta gia' il transcript, nel campo `cwd`.
Misurato sul traffico reale: 30 progetti distinti.

Si fa adesso perche' il database di produzione ha UNA riga: rinominare oggi e' una
migrazione senza dati da preservare, farlo dopo la pubblicazione significa migrare lo
storico di chi ha installato il plugin.

**`batch_alter_table` non e' ornamentale:** SQLite non ha `ALTER TABLE RENAME COLUMN`
in tutte le versioni supportate, e Alembic in modalita' batch ricostruisce la tabella.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABELLE = ("agent_actions", "alerts", "rule_status", "agent_watermark")


def upgrade() -> None:
    op.drop_index("ix_actions_agent_time", table_name="agent_actions")
    for tabella in TABELLE:
        with op.batch_alter_table(tabella) as batch:
            batch.alter_column("agent_name", new_column_name="project")
    op.create_index("ix_actions_project_time", "agent_actions", ["project", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_actions_project_time", table_name="agent_actions")
    for tabella in TABELLE:
        with op.batch_alter_table(tabella) as batch:
            batch.alter_column("project", new_column_name="agent_name")
    op.create_index("ix_actions_agent_time", "agent_actions", ["agent_name", "timestamp"])
```

- [x] **Step 2: Eseguire il test di parità per verificare che fallisca**

Run: `python -m pytest tests/test_migrations.py::test_the_orm_models_and_the_migrations_describe_the_same_schema -v`
Expected: FAIL — Alembic dice `project`, i modelli ORM dicono ancora `agent_name`.
È il test che fa da guida per il resto del task.

- [x] **Step 3: Rinominare nei modelli e nelle query di `db.py`**

**L'elenco completo dei nomi che cambiano** — nient'altro va toccato:

| Vecchio | Nuovo |
|---|---|
| colonna `agent_name` su `agent_actions`, `alerts`, `rule_status`, `agent_watermark` | `project` |
| parametro `agent_name=` di ogni funzione | `project=` |
| chiave `"agent_name"` nei dizionari restituiti | `"project"` |
| indice `ix_actions_agent_time` | `ix_actions_project_time` |
| `normalizza_agent_name()` | `normalizza_progetto()` |
| `get_active_agents()` | `get_active_projects()` |
| `agenti_con_alert_vivi()` | `progetti_con_alert_vivi()` |
| costante `MAX_TRACKED_AGENTS` in `config.py` | resta il nome, cambia il commento: ora conta **sessioni per progetto in 24h** |

Trovare tutto:
```bash
grep -rn "agent_name\|ix_actions_agent_time\|normalizza_agent_name\|get_active_agents\|agenti_con_alert_vivi" starkeno/ | wc -l
```
Expected prima: ~100 occorrenze nei soli sorgenti. Dopo: 0.

- [x] **Step 4: Rinominare nei chiamanti**

```bash
grep -rn "agent_name\|normalizza_agent_name\|get_active_agents\|agenti_con_alert_vivi" starkeno/ tests/ scripts/smoke_test_client.py
```

Aggiornare ogni occorrenza. In `starkeno/static/index.html` le tre occorrenze sono
chiavi JSON restituite da `api.py`: vanno cambiate insieme.

- [x] **Step 5: Eseguire il test di parità**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: PASS, tutti

- [x] **Step 6: Eseguire la suite intera**

Run: `python -m pytest -q`
Expected: PASS, 252 test. Un fallimento qui è un'occorrenza dimenticata.

- [x] **Step 7: Migrare il database di produzione e verificare la riga**

```bash
python -m alembic upgrade head
```

Poi verificare che la riga esistente sia ancora lì:

```bash
python -c "import sqlite3, starkeno.config as c; con=sqlite3.connect(c.DB_PATH); print(con.execute('SELECT project, action FROM agent_actions').fetchall())"
```
Expected: una riga, `('smoke-test-agent', 'manual_verification')`

- [x] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: agent_name diventa project, l'asse e' il progetto (fase 1, task 3)"
```

---

## Task 4: Le colonne che l'ingestione riempie

**Files:**
- Create: `migrations/versions/0005_ingestione.py`
- Modify: `starkeno/db.py` (modello `AgentAction`)
- Test: `tests/test_migrations.py` (parità, già esistente), `tests/test_schema_v1.py`

**Interfaces:**
- Produces: su `AgentAction` — `session_id: str`, `message_id: str`, `azione_fallita: int`,
  `esito_noto: int`, `azioni_nella_chiamata: int`, `skill: str`, `plugin: str`,
  `mcp_server: str`, `is_sidechain: int`; indice unico `ix_actions_chiamata`
  su `(session_id, message_id)`; indice `ix_actions_project_session_time`.

- [x] **Step 1: Scrivere il test che fallisce**

```python
# in tests/test_schema_v1.py, in coda
def test_le_colonne_dell_ingestione_esistono_e_stanno_in_coda(session):
    """Le colonne nuove vanno IN CODA, o i due schemi divergono.

    `ADD COLUMN` accoda in fondo. Se il modello ORM le dichiarasse prima, `create_all`
    (che i test usano) produrrebbe un ordine diverso da quello che esiste in produzione,
    e ogni SELECT * posizionale restituirebbe campi diversi nei due ambienti.
    """
    colonne = [r[1] for r in session.execute(
        db.text("PRAGMA table_info(agent_actions)")).all()]
    attese_in_coda = ["session_id", "message_id", "azione_fallita", "esito_noto",
                      "azioni_nella_chiamata", "skill", "plugin", "mcp_server",
                      "is_sidechain"]
    assert colonne[-len(attese_in_coda):] == attese_in_coda


def test_una_chiamata_non_puo_essere_scritta_due_volte(session):
    """`(session_id, message_id)` e' la chiave di idempotenza: una riesecuzione
    dell'hook sullo stesso transcript deve essere un no-op, non un raddoppio."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    for _ in range(2):
        session.add(db.AgentAction(
            project="p", action="read:a.py", model_used="claude-opus-5",
            tokens_used=100, session_id="s1", message_id="msg_1",
            azione_fallita=0, esito_noto=1, azioni_nella_chiamata=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_la_sentinella_e_la_stringa_vuota_mai_null(session):
    """In SQLite due NULL sono DISTINTI: un indice unico che contiene NULL smette di
    vincolare in silenzio. Le colonne di questa chiave usano la stringa vuota."""
    colonne = {r[1]: r for r in session.execute(
        db.text("PRAGMA table_info(agent_actions)")).all()}
    for nome in ("session_id", "message_id"):
        assert colonne[nome][3] == 1, "%s deve essere NOT NULL" % nome
```

- [x] **Step 2: Eseguirlo per verificare che fallisca**

Run: `python -m pytest tests/test_schema_v1.py -k "ingestione or due_volte or sentinella" -v`
Expected: FAIL — le colonne non esistono

- [x] **Step 3: Scrivere la migrazione `0005`**

```python
# migrations/versions/0005_ingestione.py
"""v2: le colonne che l'ingestione dal transcript riempie

La grana della spesa e' `(sessionId, message.id)` — misurato: il transcript scrive 2,04
righe per chiamata API e sommare per riga da' 2,03x di gonfiaggio. Quella coppia e'
insieme la grana corretta e la CHIAVE DI IDEMPOTENZA: l'indice unico su di essa rende
una riesecuzione dell'hook un no-op invece di un raddoppio.

`azione_fallita` ed `esito_noto` sono DUE colonne e non una a tre stati: mai NULL per
"non lo so" su un booleano. L'esito di uno strumento arriva nel messaggio successivo, e
misurato resta irrisolto nello 0,04% dei casi — piccolo, ma se lo si scrivesse "falso"
sia R1 sia il costo degli errori diventerebbero ottimisti per costruzione.

`azioni_nella_chiamata` conta le azioni di una chiamata multipla (il 10,3% ne ha piu' di
una) senza gonfiare il numero di righe: righe multiple renderebbero le soglie che contano
azioni il 10% piu' sensibili senza che nessuno l'abbia deciso.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Stringa vuota, mai NULL: in SQLite due NULL sono DISTINTI, quindi un indice unico che
# li contiene smette di vincolare senza dire niente.
VUOTA = sa.text("''")


def upgrade() -> None:
    op.add_column("agent_actions", sa.Column("session_id", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("message_id", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("azione_fallita", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("agent_actions", sa.Column("esito_noto", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("agent_actions", sa.Column("azioni_nella_chiamata", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.add_column("agent_actions", sa.Column("skill", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("plugin", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("mcp_server", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("is_sidechain", sa.Integer(), nullable=False, server_default=sa.text("0")))

    # L'unico indice UNICO della tabella: e' cio' che rende l'hook rieseguibile.
    # Parziale, perche' la riga preesistente (e chiunque scriva senza passare
    # dall'ingestione) ha le sentinelle vuote e non deve collidere con se stessa.
    op.execute(
        "CREATE UNIQUE INDEX ix_actions_chiamata ON agent_actions (session_id, message_id) "
        "WHERE session_id != '' AND message_id != ''"
    )
    # R1 legge la sequenza di UNA sessione: senza questo indice ordina in memoria.
    op.create_index("ix_actions_project_session_time", "agent_actions",
                    ["project", "session_id", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_actions_project_session_time", table_name="agent_actions")
    op.drop_index("ix_actions_chiamata", table_name="agent_actions")
    for colonna in ("is_sidechain", "mcp_server", "plugin", "skill",
                    "azioni_nella_chiamata", "esito_noto", "azione_fallita",
                    "message_id", "session_id"):
        op.drop_column("agent_actions", colonna)
```

- [x] **Step 4: Aggiornare il modello `AgentAction` in `db.py`**

In coda alle colonne esistenti — **dopo `output_tokens`**, mai prima:

```python
    # ---- Colonne dell'ingestione dal transcript (migrazione 0005) ----
    # IN CODA per l'invariante 7: ADD COLUMN accoda, e i due schemi devono coincidere.
    #
    # Sentinella STRINGA VUOTA, mai NULL: in SQLite due NULL sono distinti, quindi
    # l'indice unico su (session_id, message_id) smetterebbe di vincolare in silenzio.
    session_id = Column(String, nullable=False, server_default="")
    message_id = Column(String, nullable=False, server_default="")

    # DUE colonne, non un booleano a tre stati. L'esito di uno strumento arriva nel
    # messaggio successivo: quando non c'e' ancora, `esito_noto` vale 0 e `azione_fallita`
    # NON va letta. Scriverla "falso" per "non lo so" renderebbe ottimisti per costruzione
    # sia R1 sia il costo degli errori.
    azione_fallita = Column(Integer, nullable=False, server_default="0")
    esito_noto = Column(Integer, nullable=False, server_default="0")

    # Il 10,3% delle chiamate contiene piu' di un'azione. Una riga per chiamata (la grana
    # della spesa) piu' questo contatore: righe multiple gonfierebbero del 10% ogni soglia
    # che conta azioni, senza che nessuno l'abbia deciso.
    azioni_nella_chiamata = Column(Integer, nullable=False, server_default="1")

    # Attribuzione. Nessuna regola le interroga: sono il materiale del conto.
    skill = Column(String, nullable=False, server_default="")
    plugin = Column(String, nullable=False, server_default="")
    mcp_server = Column(String, nullable=False, server_default="")
    is_sidechain = Column(Integer, nullable=False, server_default="0")
```

E in `__table_args__`, sostituire l'indice e aggiungere gli altri due:

```python
    __table_args__ = (
        Index("ix_actions_project_time", "project", "timestamp"),
        # R1 legge la sequenza di UNA sessione, non del progetto: una sequenza
        # interlacciata da piu' esecuzioni parallele non e' di nessuno.
        Index("ix_actions_project_session_time", "project", "session_id", "timestamp"),
        # L'unico UNICO: e' cio' che rende l'hook rieseguibile senza duplicare.
        Index("ix_actions_chiamata", "session_id", "message_id", unique=True,
              sqlite_where=text("session_id != '' AND message_id != ''")),
    )
```

- [x] **Step 5: Eseguire i test nuovi e quello di parità**

Run: `python -m pytest tests/test_schema_v1.py tests/test_migrations.py -v`
Expected: PASS

- [x] **Step 6: Eseguire la suite intera**

Run: `python -m pytest -q`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: le colonne dell'ingestione, in coda e con la chiave di idempotenza (fase 1, task 4)"
```

---

## Task 5: Il lettore di transcript — puro, e con la regressione sul 2,03×

> **Il pezzo più importante del piano.** Qui vive il difetto che è costato 2,03× di
> gonfiaggio, e qui si prova che non torna. Modulo **puro**: nessun database, nessun
> orologio, nessuna variabile d'ambiente. Si prova in memoria.

**Files:**
- Create: `starkeno/transcript.py`
- Create: `tests/fixtures/transcript_vero.jsonl`
- Test: `tests/test_transcript.py`

**Interfaces:**
- Produces: `transcript.Chiamata` (dataclass congelata con i campi:
  `session_id, message_id, timestamp, project, action, model_used, input_tokens,
  cache_read_tokens, cache_write_tokens, output_tokens, azione_fallita, esito_noto,
  azioni_nella_chiamata, skill, plugin, mcp_server, is_sidechain`),
  `transcript.leggi(righe: Iterable[str]) -> list[Chiamata]`

- [x] **Step 1: Costruire la fixture da un transcript vero**

```bash
python - <<'PY'
import json, glob, os, itertools
sorgente = sorted(glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True))
# Si sceglie un file che contenga sia chiamate multi-strumento sia almeno un fallimento.
scelto = None
for p in sorgente:
    testo = open(p, encoding="utf-8").read()
    if '"is_error":true' in testo.replace(" ", "") and testo.count('"tool_use"') > 20:
        scelto = p
        break
righe = open(scelto, encoding="utf-8").read().splitlines()[:400]
os.makedirs("tests/fixtures", exist_ok=True)
with open("tests/fixtures/transcript_vero.jsonl", "w", encoding="utf-8") as f:
    f.write("\n".join(righe))
print("preso da", scelto, "->", len(righe), "righe")
PY
```

Poi calcolare i valori attesi **con lo stesso metodo della campagna di misura**, così il
test verifica il codice nuovo contro una misura indipendente:

```bash
python - <<'PY'
import json
righe = open("tests/fixtures/transcript_vero.jsonl", encoding="utf-8").read().splitlines()
con_usage = 0
chiamate = set()
for r in righe:
    if not r.strip():
        continue
    d = json.loads(r)
    m = d.get("message")
    if not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
        continue
    con_usage += 1
    if (m.get("model") or "") == "<synthetic>":
        continue
    chiamate.add((d.get("sessionId"), m.get("id")))
print("righe con usage:", con_usage, "| chiamate uniche:", len(chiamate),
      "| righe per chiamata: %.2f" % (con_usage / len(chiamate)))
PY
```

Annotare i due numeri: servono al passo 2.

- [x] **Step 2: Scrivere il test che fallisce**

```python
# tests/test_transcript.py
"""Il lettore di transcript, e la regressione sul difetto piu' caro del progetto.

Il transcript scrive UNA RIGA PER BLOCCO DI CONTENUTO e ripete l'involucro del
messaggio, `usage` incluso. Misurato su 475 file: 2,04 righe per chiamata API.
Sommare per riga da' 2,03x di gonfiaggio.

R3 confronta un agente con la propria storia e si sarebbe gonfiata da entrambe le parti,
quasi senza segni. Ma le soglie ASSOLUTE sarebbero scattate a meta' della spesa vera.
Due regole sbagliate in due direzioni opposte, senza un errore.
"""
import json
from pathlib import Path

from starkeno import transcript

FIXTURE = Path(__file__).parent / "fixtures" / "transcript_vero.jsonl"


def righe_fixture():
    return FIXTURE.read_text(encoding="utf-8").splitlines()


def test_una_riga_per_chiamata_api_non_per_riga_di_transcript():
    """LA regressione. I due numeri si ricavano dalla fixture stessa, non si scrivono
    a mano: cosi' il test resta valido se un giorno la fixture viene rifatta."""
    righe = righe_fixture()
    con_usage = sum(
        1 for r in righe if r.strip()
        and isinstance(json.loads(r).get("message"), dict)
        and isinstance(json.loads(r)["message"].get("usage"), dict)
    )
    chiamate = transcript.leggi(righe)

    assert len(chiamate) < con_usage, (
        "il lettore ha prodotto una riga per riga di transcript: e' il gonfiaggio 2,03x"
    )
    assert con_usage / len(chiamate) > 1.5, "il rapporto misurato era ~2,04"


def test_le_chiamate_sono_uniche_per_sessione_e_messaggio():
    chiamate = transcript.leggi(righe_fixture())
    chiavi = [(c.session_id, c.message_id) for c in chiamate]
    assert len(chiavi) == len(set(chiavi))


def test_message_id_da_solo_non_basta():
    """Misurato: 71 righe -> 34 id nel file campione. Va sempre accoppiato a sessionId."""
    righe = [
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                    "message": {"id": "msg_1", "model": "claude-opus-5",
                                "usage": {"input_tokens": 10, "output_tokens": 1},
                                "content": []}}),
        json.dumps({"sessionId": "B", "timestamp": "2026-08-07T10:00:01Z", "cwd": "/x",
                    "message": {"id": "msg_1", "model": "claude-opus-5",
                                "usage": {"input_tokens": 20, "output_tokens": 2},
                                "content": []}}),
    ]
    assert len(transcript.leggi(righe)) == 2


def test_l_ultima_riga_vince_sull_usage():
    """Misurato: il 4,6% delle chiamate ha righe con `usage` diversi, e nel 100% di quei
    casi l'ULTIMA e' anche la piu' alta — il conteggio si accumula mentre il messaggio
    si forma."""
    comune = {"sessionId": "A", "cwd": "/x"}
    righe = [
        json.dumps({**comune, "timestamp": "2026-08-07T10:00:00Z",
                    "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                "usage": {"input_tokens": 10, "output_tokens": 1}}}),
        json.dumps({**comune, "timestamp": "2026-08-07T10:00:02Z",
                    "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                "usage": {"input_tokens": 10, "output_tokens": 7}}}),
    ]
    (chiamata,) = transcript.leggi(righe)
    assert chiamata.output_tokens == 7


def test_i_messaggi_sintetici_si_scartano_all_ingresso():
    """L'1,8% del traffico. Non sono chiamate API: si scartano all'ingresso, non nelle
    regole."""
    righe = [
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                    "message": {"id": "m1", "model": "<synthetic>", "content": [],
                                "usage": {"input_tokens": 5, "output_tokens": 1}}}),
    ]
    assert transcript.leggi(righe) == []


def test_una_chiamata_con_piu_azioni_da_UNA_riga_col_contatore():
    """Il 10,3% delle chiamate. Righe multiple gonfierebbero del 10% ogni soglia che
    conta azioni; l'attribuzione sta gia' sulla chiamata, quindi spezzare la
    duplicherebbe invece di affinarla."""
    riga = json.dumps({
        "sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x/progetto",
        "message": {"id": "m", "model": "claude-opus-5",
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "Read",
                         "input": {"file_path": "a.py"}},
                        {"type": "tool_use", "id": "t2", "name": "Read",
                         "input": {"file_path": "b.py"}},
                        {"type": "tool_use", "id": "t3", "name": "Bash",
                         "input": {"command": "ls"}},
                    ]}})
    (c,) = transcript.leggi([riga])
    assert c.azioni_nella_chiamata == 3
    assert c.action == "read:a.py", "l'etichetta e' la PRIMA azione"


def test_il_progetto_viene_dal_cwd():
    riga = json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z",
                       "cwd": "C:\\\\workspace\\\\starkeno",
                       "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                   "usage": {"input_tokens": 1, "output_tokens": 1}}})
    (c,) = transcript.leggi([riga])
    assert c.project == "starkeno"


def test_l_esito_si_prende_dal_messaggio_successivo():
    """Il risultato di uno strumento arriva DOPO. Misurato: resta irrisolto nello 0,04%."""
    righe = [
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                    "message": {"id": "m", "model": "claude-opus-5",
                                "usage": {"input_tokens": 1, "output_tokens": 1},
                                "content": [{"type": "tool_use", "id": "t1",
                                             "name": "Bash", "input": {"command": "ls"}}]}}),
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:01Z", "cwd": "/x",
                    "message": {"role": "user",
                                "content": [{"type": "tool_result", "tool_use_id": "t1",
                                             "is_error": True, "content": "Exit code 1"}]}}),
    ]
    (c,) = transcript.leggi(righe)
    assert c.esito_noto == 1
    assert c.azione_fallita == 1


def test_esito_mancante_non_diventa_successo():
    """Mai «falso» per «non lo so»: renderebbe ottimisti per costruzione sia R1 sia il
    costo degli errori."""
    riga = json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                       "message": {"id": "m", "model": "claude-opus-5",
                                   "usage": {"input_tokens": 1, "output_tokens": 1},
                                   "content": [{"type": "tool_use", "id": "t9",
                                                "name": "Bash", "input": {"command": "ls"}}]}})
    (c,) = transcript.leggi([riga])
    assert c.esito_noto == 0
    assert c.azione_fallita == 0


def test_una_riga_rotta_non_ferma_la_lettura():
    """L'hook gira a casa d'altri: una riga malformata non deve costare un turno."""
    righe = [
        "{non e' json",
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                    "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                "usage": {"input_tokens": 1, "output_tokens": 1}}}),
    ]
    assert len(transcript.leggi(righe)) == 1


def test_l_attribuzione_si_prende_dalla_riga_della_chiamata():
    riga = json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                       "isSidechain": True, "attributionSkill": "superpowers:brainstorming",
                       "attributionPlugin": "superpowers",
                       "attributionMcpServer": "Claude Browser",
                       "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                   "usage": {"input_tokens": 1, "output_tokens": 1}}})
    (c,) = transcript.leggi([riga])
    assert c.skill == "superpowers:brainstorming"
    assert c.plugin == "superpowers"
    assert c.mcp_server == "Claude Browser"
    assert c.is_sidechain == 1
```

- [x] **Step 3: Eseguirlo per verificare che fallisca**

Run: `python -m pytest tests/test_transcript.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'starkeno.transcript'`

- [x] **Step 4: Scrivere `starkeno/transcript.py`**

```python
"""Da un transcript di Claude Code alle chiamate API che contiene.

**Modulo puro:** niente database, niente orologio, niente variabili d'ambiente. Prende
righe di testo e restituisce dati. E' cosi' che la regressione sul doppio conteggio si
prova in memoria, senza toccare il disco.

**La grana e' `(sessionId, message.id)`, mai la riga.** Il transcript scrive una riga per
blocco di contenuto e ripete `usage` a ogni riga: misurato, 2,04 righe per chiamata API, e
sommare per riga da' 2,03x di gonfiaggio. Quella coppia e' insieme la grana corretta della
spesa e la chiave di idempotenza.
"""
import json
from dataclasses import dataclass

# Il parametro che identifica un'azione, in ordine di preferenza. Il primo che c'e' vince.
CHIAVI_DETTAGLIO = (
    "file_path", "path", "notebook_path", "pattern", "command", "url",
    "query", "prompt", "skill", "subagent_type", "file", "filePath",
)

MODELLO_SINTETICO = "<synthetic>"
LUNGHEZZA_MASSIMA_DETTAGLIO = 300


@dataclass(frozen=True)
class Chiamata:
    """Una chiamata API, cioe' UNA riga di `agent_actions`."""

    session_id: str
    message_id: str
    timestamp: str          # ISO 8601 come lo scrive il transcript. Chi scrive converte.
    project: str
    action: str
    model_used: str
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    azione_fallita: int
    esito_noto: int
    azioni_nella_chiamata: int
    skill: str
    plugin: str
    mcp_server: str
    is_sidechain: int

    @property
    def tokens_used(self) -> int:
        """Il totale, cache read inclusi: e' la misura di «quanto e' grosso il task»."""
        return (self.input_tokens + self.cache_read_tokens
                + self.cache_write_tokens + self.output_tokens)


def _dettaglio(parametri) -> str | None:
    if not isinstance(parametri, dict):
        return None
    for chiave in CHIAVI_DETTAGLIO:
        valore = parametri.get(chiave)
        if isinstance(valore, str) and valore.strip():
            return valore.strip()[:LUNGHEZZA_MASSIMA_DETTAGLIO]
    return None


def _progetto(cwd: str) -> str:
    """L'ultimo segmento del percorso di lavoro.

    L'utente in locale e' una costante e non distingue niente; il progetto si'.
    Misurato: 30 progetti distinti sul traffico reale.
    """
    ripulito = (cwd or "").rstrip("\\/").replace("/", "\\")
    return ripulito.split("\\")[-1] or "?"


def leggi(righe) -> list[Chiamata]:
    """Le chiamate API contenute in queste righe di transcript, in ordine di comparsa.

    Le righe malformate si saltano: questo codice gira a casa d'altri, e una riga rotta
    non deve costare un turno all'utente.
    """
    grezze: dict[tuple[str, str], dict] = {}
    esiti: dict[str, bool] = {}
    ordine: list[tuple[str, str]] = []

    for riga in righe:
        riga = riga.strip() if isinstance(riga, str) else ""
        if not riga:
            continue
        try:
            voce = json.loads(riga)
        except Exception:
            continue
        if not isinstance(voce, dict):
            continue
        messaggio = voce.get("message")
        if not isinstance(messaggio, dict):
            continue
        contenuto = messaggio.get("content")

        # Gli esiti stanno nei messaggi dell'utente, e arrivano DOPO la chiamata che li
        # ha prodotti: si raccolgono in una passata sola e si riconciliano alla fine.
        if isinstance(contenuto, list):
            for blocco in contenuto:
                if (isinstance(blocco, dict) and blocco.get("type") == "tool_result"
                        and blocco.get("tool_use_id")):
                    esiti[blocco["tool_use_id"]] = bool(blocco.get("is_error"))

        uso = messaggio.get("usage")
        if not isinstance(uso, dict):
            continue
        modello = messaggio.get("model") or ""
        if modello == MODELLO_SINTETICO:
            # Non e' una chiamata API. Si scarta all'ingresso, non nelle regole.
            continue
        sessione, identificativo = voce.get("sessionId"), messaggio.get("id")
        if not sessione or not identificativo:
            continue

        strumenti = []
        if isinstance(contenuto, list):
            for blocco in contenuto:
                if isinstance(blocco, dict) and blocco.get("type") == "tool_use":
                    nome = (blocco.get("name") or "?").lower()
                    dettaglio = _dettaglio(blocco.get("input"))
                    strumenti.append((
                        "%s:%s" % (nome, dettaglio) if dettaglio else nome,
                        blocco.get("id"),
                    ))

        chiave = (sessione, identificativo)
        if chiave not in grezze:
            ordine.append(chiave)
            grezze[chiave] = {
                "timestamp": voce.get("timestamp") or "",
                "project": _progetto(voce.get("cwd")),
                "model_used": modello,
                "strumenti": [],
                "skill": voce.get("attributionSkill") or "",
                "plugin": voce.get("attributionPlugin") or "",
                "mcp_server": voce.get("attributionMcpServer") or "",
                "is_sidechain": 1 if voce.get("isSidechain") else 0,
            }
        record = grezze[chiave]
        record["strumenti"].extend(strumenti)
        # L'ULTIMA riga vince sull'usage: misurato, il conteggio si accumula mentre il
        # messaggio si forma, e nel 100% dei casi discordi l'ultima e' anche la piu' alta.
        record["usage"] = (
            int(uso.get("input_tokens") or 0),
            int(uso.get("cache_read_input_tokens") or 0),
            int(uso.get("cache_creation_input_tokens") or 0),
            int(uso.get("output_tokens") or 0),
        )
        # Il primo timestamp non nullo: le righe successive sono la stessa chiamata.
        if not record["timestamp"]:
            record["timestamp"] = voce.get("timestamp") or ""

    chiamate = []
    for sessione, identificativo in ordine:
        record = grezze[(sessione, identificativo)]
        strumenti = record["strumenti"]
        # UNA riga per chiamata, etichettata con la PRIMA azione. L'attribuzione sta gia'
        # sulla chiamata: spezzare la duplicherebbe invece di affinarla.
        if strumenti:
            azione, identificativo_strumento = strumenti[0]
        else:
            azione, identificativo_strumento = "risposta", None

        if identificativo_strumento in esiti:
            noto, fallita = 1, 1 if esiti[identificativo_strumento] else 0
        elif identificativo_strumento is None:
            # Una risposta senza strumenti non ha un esito da conoscere: e' riuscita.
            noto, fallita = 1, 0
        else:
            # Mai «falso» per «non lo so».
            noto, fallita = 0, 0

        ingresso, lettura, scrittura, uscita = record["usage"]
        chiamate.append(Chiamata(
            session_id=sessione,
            message_id=identificativo,
            timestamp=record["timestamp"],
            project=record["project"],
            action=azione,
            model_used=record["model_used"],
            input_tokens=ingresso,
            cache_read_tokens=lettura,
            cache_write_tokens=scrittura,
            output_tokens=uscita,
            azione_fallita=fallita,
            esito_noto=noto,
            azioni_nella_chiamata=max(1, len(strumenti)),
            skill=record["skill"],
            plugin=record["plugin"],
            mcp_server=record["mcp_server"],
            is_sidechain=record["is_sidechain"],
        ))
    return chiamate
```

- [x] **Step 5: Eseguire i test**

Run: `python -m pytest tests/test_transcript.py -v`
Expected: PASS, 11 test

- [x] **Step 6: Commit**

```bash
git add starkeno/transcript.py tests/test_transcript.py tests/fixtures/transcript_vero.jsonl
git commit -m "feat: il lettore di transcript, con la regressione sul 2,03x (fase 1, task 5)"
```

---

## Task 6: La scrittura idempotente

**Files:**
- Modify: `starkeno/db.py` (nuova funzione `scrivi_chiamate`)
- Test: `tests/test_ingestione.py`

**Interfaces:**
- Consumes: `transcript.Chiamata` (Task 5), colonne di Task 4
- Produces: `db.scrivi_chiamate(session, chiamate: list) -> int` — restituisce **quante
  righe nuove** ha scritto. Rieseguirla sulle stesse chiamate restituisce `0`.

- [x] **Step 1: Scrivere il test che fallisce**

```python
# tests/test_ingestione.py
"""La scrittura delle chiamate lette dal transcript.

Idempotente per costruzione, non per accortezza del chiamante: la chiave e'
`(session_id, message_id)` e l'indice unico la fa rispettare dal database.
"""
from starkeno import db
from starkeno.transcript import Chiamata


def _chiamata(message_id="m1", session_id="s1", **extra):
    campi = dict(
        session_id=session_id, message_id=message_id,
        timestamp="2026-08-07T10:00:00.000Z", project="starkeno",
        action="read:app.py", model_used="claude-opus-5",
        input_tokens=100, cache_read_tokens=900, cache_write_tokens=10,
        output_tokens=50, azione_fallita=0, esito_noto=1,
        azioni_nella_chiamata=1, skill="", plugin="", mcp_server="", is_sidechain=0)
    campi.update(extra)
    return Chiamata(**campi)


def test_scrive_le_chiamate(session):
    scritte = db.scrivi_chiamate(session, [_chiamata("m1"), _chiamata("m2")])
    assert scritte == 2
    assert session.query(db.AgentAction).count() == 2


def test_rieseguirla_sullo_stesso_transcript_non_duplica_niente(session):
    """LA prova che rende l'hook sicuro: gira a ogni turno sullo stesso file, che
    cresce. Senza questa, ogni turno riscriverebbe tutta la storia."""
    chiamate = [_chiamata("m1"), _chiamata("m2")]
    assert db.scrivi_chiamate(session, chiamate) == 2
    assert db.scrivi_chiamate(session, chiamate) == 0
    assert session.query(db.AgentAction).count() == 2


def test_scrive_solo_le_nuove_quando_il_transcript_cresce(session):
    db.scrivi_chiamate(session, [_chiamata("m1")])
    scritte = db.scrivi_chiamate(session, [_chiamata("m1"), _chiamata("m2")])
    assert scritte == 1
    assert session.query(db.AgentAction).count() == 2


def test_lo_stesso_message_id_in_sessioni_diverse_sono_due_righe(session):
    """`message.id` da solo NON e' unico: misurato, 71 righe -> 34 id."""
    db.scrivi_chiamate(session, [_chiamata("m1", session_id="A"),
                                 _chiamata("m1", session_id="B")])
    assert session.query(db.AgentAction).count() == 2


def test_il_timestamp_scritto_e_quello_del_transcript_non_l_ora_di_ingestione(session):
    """Il default della colonna e' l'ora dell'insert: qui va sovrascritto, o l'hook
    comprimerebbe ore di lavoro nell'istante in cui gira, e le regole a finestra corta
    lo vedrebbero come una raffica."""
    db.scrivi_chiamate(session, [_chiamata("m1", timestamp="2026-07-01T08:30:00.000Z")])
    riga = session.query(db.AgentAction).one()
    assert riga.timestamp.year == 2026 and riga.timestamp.month == 7
    assert riga.timestamp.tzinfo is not None, "invariante 1: sopra db.py tutto e' aware-UTC"


def test_una_chiamata_con_timestamp_illeggibile_si_salta_senza_fermare_le_altre(session):
    scritte = db.scrivi_chiamate(session, [
        _chiamata("m1", timestamp="non e' una data"),
        _chiamata("m2"),
    ])
    assert scritte == 1
```

- [x] **Step 2: Eseguirlo per verificare che fallisca**

Run: `python -m pytest tests/test_ingestione.py -v`
Expected: FAIL con `AttributeError: module 'starkeno.db' has no attribute 'scrivi_chiamate'`

- [x] **Step 3: Scrivere `scrivi_chiamate` in `db.py`**

Aggiungere dopo `record_action`:

```python
def _quando(iso: str) -> datetime | None:
    """Il timestamp del transcript, come datetime aware-UTC. `None` se illeggibile.

    Sopra `db.py` tutto e' aware-UTC (invariante 1): la conversione avviene qui, al
    confine, e non si ripete da nessun'altra parte.
    """
    try:
        quando = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if quando.tzinfo is None:
        return quando.replace(tzinfo=timezone.utc)
    return quando.astimezone(timezone.utc)


def scrivi_chiamate(session: Session, chiamate) -> int:
    """Scrive le chiamate nuove. Restituisce quante ne ha scritte.

    **Idempotente per costruzione**, non per accortezza del chiamante: l'indice unico
    `ix_actions_chiamata` su `(session_id, message_id)` fa rispettare la regola al
    database. E' cio' che rende l'hook rieseguibile a ogni turno sullo stesso file, che
    nel frattempo cresce.

    Il `timestamp` scritto e' quello del TRANSCRIPT, non l'ora di ingestione: l'hook
    processa in un istante ore di lavoro, e col default della colonna le regole a
    finestra corta vedrebbero una raffica che non e' mai esistita.

    Le chiamate gia' presenti si scartano PRIMA dell'insert invece di lasciar sollevare
    l'indice: un `IntegrityError` invaliderebbe l'intera transazione, e le chiamate nuove
    che seguono andrebbero perse insieme a quella duplicata.
    """
    if not chiamate:
        return 0

    chiavi = {(c.session_id, c.message_id) for c in chiamate}
    gia_presenti = set()
    # A blocchi: SQLite ha un tetto sul numero di parametri di una query.
    elenco = list(chiavi)
    for inizio in range(0, len(elenco), 400):
        blocco = elenco[inizio:inizio + 400]
        condizione = " OR ".join(
            "(session_id = :s%d AND message_id = :m%d)" % (i, i) for i in range(len(blocco))
        )
        parametri = {}
        for i, (sessione, messaggio) in enumerate(blocco):
            parametri["s%d" % i] = sessione
            parametri["m%d" % i] = messaggio
        righe = session.execute(
            text("SELECT session_id, message_id FROM agent_actions WHERE " + condizione),
            parametri,
        ).all()
        gia_presenti.update((r[0], r[1]) for r in righe)

    nuove = []
    viste = set()
    for chiamata in chiamate:
        chiave = (chiamata.session_id, chiamata.message_id)
        if chiave in gia_presenti or chiave in viste:
            continue
        quando = _quando(chiamata.timestamp)
        if quando is None:
            # Senza un momento credibile la riga e' inutile a ogni regola a finestra:
            # meglio perderne una che avvelenare la finestra di tutte.
            continue
        viste.add(chiave)
        nuove.append(AgentAction(
            project=normalizza_progetto(chiamata.project),
            action=chiamata.action,
            model_used=chiamata.model_used,
            tokens_used=chiamata.tokens_used,
            timestamp=quando,
            cache_read_tokens=chiamata.cache_read_tokens,
            cache_write_tokens=chiamata.cache_write_tokens,
            output_tokens=chiamata.output_tokens,
            session_id=chiamata.session_id,
            message_id=chiamata.message_id,
            azione_fallita=chiamata.azione_fallita,
            esito_noto=chiamata.esito_noto,
            azioni_nella_chiamata=chiamata.azioni_nella_chiamata,
            skill=chiamata.skill,
            plugin=chiamata.plugin,
            mcp_server=chiamata.mcp_server,
            is_sidechain=chiamata.is_sidechain,
        ))

    if not nuove:
        return 0
    session.add_all(nuove)
    session.commit()
    return len(nuove)
```

- [x] **Step 4: Eseguire i test**

Run: `python -m pytest tests/test_ingestione.py -v`
Expected: PASS, 6 test

- [x] **Step 5: Eseguire la suite intera**

Run: `python -m pytest -q`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add starkeno/db.py tests/test_ingestione.py
git commit -m "feat: scrittura idempotente delle chiamate (fase 1, task 6)"
```

---

## Task 7: Scoprire cosa riceve davvero un hook

> **Questo task non scrive codice di produzione: misura.** Nessun documento del progetto
> dice quale evento di Claude Code corrisponde a «fine turno», né quale JSON arriva sullo
> stdin dell'hook. **Assumerlo è esattamente l'errore che il progetto ha già pagato tre
> volte.** Si scopre eseguendo, e il risultato guida il task 8.

**Files:**
- Create: `scripts/misure/11_cosa_riceve_un_hook.py`
- Create: `.claude/settings.local.json` (temporaneo, si rimuove alla fine del task)

**Interfaces:**
- Produces: un file `hook_osservato.json` nella cartella scratch con il payload reale,
  e l'evento giusto annotato nel piano.

- [x] **Step 1: Scrivere la sonda**

```python
# scripts/misure/11_cosa_riceve_un_hook.py
"""Che cosa riceve un hook di Claude Code, davvero.

Non lo dice nessun documento del progetto, e assumerlo e' l'errore che questo progetto
ha gia' pagato tre volte. Questa sonda non fa niente: scrive quello che ha ricevuto e
esce 0, come dovra' fare l'hook vero.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

USCITA = Path.home() / ".starkeno_sonda_hook.jsonl"


def main() -> int:
    try:
        grezzo = sys.stdin.read()
    except Exception:
        grezzo = "<stdin illeggibile>"
    try:
        voce = {
            "quando": datetime.now(timezone.utc).isoformat(),
            "argv": sys.argv[1:],
            "stdin": grezzo[:4000],
            "variabili_claude": {k: v for k, v in os.environ.items()
                                 if "CLAUDE" in k.upper()},
        }
        with open(USCITA, "a", encoding="utf-8") as f:
            f.write(json.dumps(voce, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # SEMPRE zero: l'hook non deve mai rompere la sessione di chi lo usa.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 2: Registrare la sonda su più eventi contemporaneamente**

Creare `.claude/settings.local.json` nella radice del repository:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"<radice-progetto>/scripts/misure/11_cosa_riceve_un_hook.py\"",
            "timeout": 10
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"<radice-progetto>/scripts/misure/11_cosa_riceve_un_hook.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

- [x] **Step 3: Riavviare Claude Code in questa cartella e fare due o tre scambi**

Serve una sessione vera: la sonda scrive una riga per ogni volta che l'hook parte.

- [x] **Step 4: Leggere cosa è arrivato**

```bash
python -c "
import json, pathlib
p = pathlib.Path.home() / '.starkeno_sonda_hook.jsonl'
righe = p.read_text(encoding='utf-8').splitlines()
print('scatti registrati:', len(righe))
for r in righe[:3]:
    v = json.loads(r)
    print('---', v['quando'])
    try:
        s = json.loads(v['stdin'])
        print('  chiavi dello stdin:', sorted(s.keys()))
        for k in ('hook_event_name', 'session_id', 'transcript_path', 'cwd'):
            print('   ', k, '=', s.get(k))
    except Exception:
        print('  stdin grezzo:', v['stdin'][:300])
    print('  variabili CLAUDE:', list(v['variabili_claude'])[:8])
"
```

**Da annotare prima di procedere al task 8:**
- il nome esatto dell'evento che scatta a fine turno;
- la chiave che contiene il percorso del transcript;
- se il payload porta anche `cwd` e `session_id` (se sì, l'hook non deve dedurli).

- [x] **Step 5: Togliere la sonda**

```bash
rm .claude/settings.local.json
rm ~/.starkeno_sonda_hook.jsonl
```

- [x] **Step 6: Commit**

```bash
git add scripts/misure/11_cosa_riceve_un_hook.py
git commit -m "misura: cosa riceve davvero un hook di Claude Code (fase 1, task 7)"
```

---

## Task 8: L'hook di ingestione

> **L'invariante 4 applicata a casa d'altri.** Qui il costo di un fallimento non lo paga
> StarkEno: lo paga il lavoro dell'utente, ed è un progetto open source installato da
> sconosciuti.

**Files:**
- Create: `starkeno/hook_ingestione.py`
- Test: `tests/test_hook.py`

**Interfaces:**
- Consumes: `transcript.leggi` (Task 5), `db.scrivi_chiamate` (Task 6),
  `trasloco.trasloca_se_serve` (Task 2), il nome dell'evento e la chiave del percorso
  scoperti nel Task 7.
- Produces: `hook_ingestione.main() -> int` (sempre `0`),
  `hook_ingestione.ingerisci(payload: dict) -> int` (quante righe scritte; solleva).

- [x] **Step 1: Scrivere il test che fallisce**

```python
# tests/test_hook.py
"""L'hook non deve MAI rompere la sessione di chi lo usa.

E' l'invariante 4 applicata a casa d'altri: qui il costo di un fallimento non lo paga
StarkEno, lo paga il lavoro dell'utente. Uscita 0 sempre, niente rumore su stderr,
nessuna eccezione che risale.
"""
import json

import pytest

from starkeno import hook_ingestione


def _payload(tmp_path, righe):
    percorso = tmp_path / "transcript.jsonl"
    percorso.write_text("\n".join(righe), encoding="utf-8")
    return {"transcript_path": str(percorso), "session_id": "s1", "cwd": str(tmp_path)}


def _riga(message_id="m1"):
    return json.dumps({
        "sessionId": "s1", "timestamp": "2026-08-07T10:00:00.000Z", "cwd": "/x/progetto",
        "message": {"id": message_id, "model": "claude-opus-5",
                    "usage": {"input_tokens": 10, "cache_read_input_tokens": 900,
                              "output_tokens": 5},
                    "content": [{"type": "tool_use", "id": "t1", "name": "Read",
                                 "input": {"file_path": "app.py"}}]}})


def test_ingerisce_e_scrive(tmp_path, monkeypatch):
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "db.sqlite"))
    hook_ingestione.prepara_database(str(tmp_path / "db.sqlite"))
    assert hook_ingestione.ingerisci(_payload(tmp_path, [_riga("m1"), _riga("m2")])) == 2


def test_rieseguirlo_non_duplica(tmp_path, monkeypatch):
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "db.sqlite"))
    hook_ingestione.prepara_database(str(tmp_path / "db.sqlite"))
    payload = _payload(tmp_path, [_riga("m1")])
    assert hook_ingestione.ingerisci(payload) == 1
    assert hook_ingestione.ingerisci(payload) == 0


def test_esce_zero_col_database_assente(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "non" / "esiste" / "db.sqlite"))
    monkeypatch.setattr("sys.stdin", _finto_stdin(_payload(tmp_path, [_riga()])))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == "", "niente rumore su stderr"


def test_esce_zero_con_lo_stdin_vuoto(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _finto_stdin_grezzo(""))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == ""


def test_esce_zero_con_lo_stdin_non_json(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _finto_stdin_grezzo("{non e' json"))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == ""


def test_esce_zero_se_il_transcript_non_esiste(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr("sys.stdin", _finto_stdin(
        {"transcript_path": str(tmp_path / "manca.jsonl")}))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == ""


def test_esce_zero_con_lo_schema_vecchio_e_non_scrive(tmp_path, monkeypatch, capsys):
    """`check_or_die` DEVE fallire rumorosamente per un processo che parte. Dentro un
    hook non puo': ucciderebbe la sessione. Silenzioso per l'utente, rumoroso in lettura."""
    import sqlite3
    percorso = tmp_path / "db.sqlite"
    con = sqlite3.connect(str(percorso))
    con.execute("CREATE TABLE agent_actions (id INTEGER PRIMARY KEY, agent_name TEXT)")
    con.commit()
    con.close()
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr("sys.stdin", _finto_stdin(_payload(tmp_path, [_riga()])))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == ""
    con = sqlite3.connect(str(percorso))
    assert con.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 0
    con.close()


def test_esce_zero_col_database_BLOCCATO_da_un_altro_processo(tmp_path, monkeypatch, capsys):
    """La quarta prova del design: database assente, **bloccato**, o a schema vecchio.

    Uno scrittore che tiene aperta una transazione esclusiva fa scadere il busy timeout.
    L'hook deve rinunciare in silenzio, non far aspettare l'utente e non risalire.
    """
    import sqlite3

    percorso = tmp_path / "db.sqlite"
    hook_ingestione.prepara_database(str(percorso))
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))

    bloccante = sqlite3.connect(str(percorso), timeout=0.1)
    bloccante.execute("BEGIN EXCLUSIVE")
    try:
        monkeypatch.setattr("sys.stdin", _finto_stdin(_payload(tmp_path, [_riga()])))
        assert hook_ingestione.main() == 0
        assert capsys.readouterr().err == ""
    finally:
        bloccante.rollback()
        bloccante.close()


def test_l_hook_ha_un_busy_timeout_suo_e_molto_piu_corto():
    """**Difetto trovato scrivendo questo piano.** `SQLITE_BUSY_TIMEOUT_SECONDS` vale
    30 secondi: giusto per un demone che ha tutto il tempo, sbagliato dentro un hook di
    fine turno, dove significherebbe far aspettare l'utente mezzo minuto ogni volta che
    il database e' occupato. E' la forma piu' subdola di «un hook che si pianta blocca
    il turno»: non si pianta, aspetta educatamente, e l'utente disinstalla.

    Due costanti, e l'invariante che le tiene separate.
    """
    from starkeno import config

    assert config.HOOK_BUSY_TIMEOUT_SECONDS <= 3.0
    assert config.HOOK_BUSY_TIMEOUT_SECONDS < config.SQLITE_BUSY_TIMEOUT_SECONDS, (
        "l'hook deve rinunciare molto prima di un processo che ha tempo"
    )


class _Stdin:
    def __init__(self, testo):
        self._testo = testo

    def read(self):
        return self._testo


def _finto_stdin(payload):
    return _Stdin(json.dumps(payload))


def _finto_stdin_grezzo(testo):
    return _Stdin(testo)
```

- [x] **Step 2: Eseguirlo per verificare che fallisca**

Run: `python -m pytest tests/test_hook.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'starkeno.hook_ingestione'`

- [x] **Step 3: Aggiungere la costante del timeout a `config.py`**

In coda a `SQLITE_BUSY_TIMEOUT_SECONDS`:

```python
# Lo stesso, ma per l'hook — ed e' molto piu' corto di proposito.
#
# 30 secondi vanno bene per un processo che ha tempo. Dentro un hook di fine turno
# significherebbe far aspettare l'utente mezzo minuto ogni volta che il database e'
# occupato: e' la forma piu' subdola di "un hook che si pianta blocca il turno", perche'
# non si pianta — aspetta educatamente, e l'utente disinstalla. Meglio perdere
# un'ingestione: il turno dopo la rifa', l'hook e' idempotente.
HOOK_BUSY_TIMEOUT_SECONDS = 2.0
```

E aggiungere il controllo dentro `check_invariants()`, accanto agli altri — **solleva, non
usa `assert`** (`python -O` rimuove gli assert):

```python
    # I7 — margine atteso: 28 secondi
    if not c["HOOK_BUSY_TIMEOUT_SECONDS"] < c["SQLITE_BUSY_TIMEOUT_SECONDS"]:
        errore(
            "I7",
            "L'hook deve rinunciare molto prima di un processo che ha tempo: con un "
            "timeout lungo un database occupato fa aspettare l'utente a OGNI turno",
            "HOOK_BUSY_TIMEOUT_SECONDS=%s" % c["HOOK_BUSY_TIMEOUT_SECONDS"],
            "SQLITE_BUSY_TIMEOUT_SECONDS=%s" % c["SQLITE_BUSY_TIMEOUT_SECONDS"],
        )
```

E in `db.make_session_factory`, aggiungere il parametro opzionale:

```python
def make_session_factory(db_path: str, busy_timeout: float | None = None) -> sessionmaker:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": busy_timeout
                      if busy_timeout is not None else SQLITE_BUSY_TIMEOUT_SECONDS},
    )
```

- [x] **Step 4: Scrivere `starkeno/hook_ingestione.py`**

> **Sostituire `transcript_path` con la chiave scoperta nel Task 7** se è diversa.

```python
"""L'hook di fine turno: legge il transcript e scrive le chiamate nuove.

**Esce 0 qualunque cosa accada.** E' l'invariante 4 applicata a casa d'altri: il costo
di un fallimento qui non lo paga StarkEno, lo paga il lavoro dell'utente, e questo e' un
progetto open source installato da sconosciuti. Nessuna eccezione risale, niente rumore
su stderr, nessuna dipendenza da processi accesi — si scrive dritto su SQLite.
"""
import json
import sys

CHIAVE_TRANSCRIPT = "transcript_path"   # verificata dal task 7


def prepara_database(percorso: str) -> None:
    """Porta lo schema a `head`. Usata dai test e dal primo avvio."""
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    radice = Path(__file__).resolve().parent.parent
    configurazione = Config(str(radice / "alembic.ini"))
    configurazione.set_main_option("script_location", str(radice / "migrations"))
    import os
    os.environ["STARKENO_DB_PATH"] = percorso
    command.upgrade(configurazione, "head")


def ingerisci(payload: dict) -> int:
    """Legge il transcript indicato dal payload e scrive le chiamate nuove.

    **Solleva** se qualcosa va storto: e' `main` che assorbe. Tenerle separate e' cio'
    che rende questa funzione testabile senza dover fingere lo stdin.
    """
    from pathlib import Path

    from starkeno import config, db, transcript

    percorso = payload.get(CHIAVE_TRANSCRIPT)
    if not percorso:
        return 0
    file_transcript = Path(percorso)
    if not file_transcript.exists():
        return 0

    with file_transcript.open(encoding="utf-8", errors="replace") as f:
        chiamate = transcript.leggi(f)
    if not chiamate:
        return 0

    fabbrica = db.make_session_factory(config.DB_PATH)
    sessione = fabbrica()
    try:
        return db.scrivi_chiamate(sessione, chiamate)
    finally:
        sessione.close()


def main() -> int:
    """Il punto d'ingresso. **Restituisce sempre 0.**"""
    try:
        grezzo = sys.stdin.read()
        payload = json.loads(grezzo) if grezzo.strip() else {}
        if not isinstance(payload, dict):
            return 0
        from starkeno import trasloco
        trasloco.trasloca_se_serve()
        ingerisci(payload)
    except BaseException:
        # BaseException e non Exception: nemmeno un KeyboardInterrupt o un errore di
        # memoria deve trasformarsi in un turno perso per l'utente.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 5: Eseguire i test**

Run: `python -m pytest tests/test_hook.py -v`
Expected: PASS, 7 test

- [x] **Step 6: Verificare il timeout duro — l'hook non deve mai far aspettare**

```bash
python - <<'PY'
import json, subprocess, sys, time, glob, os
sorgente = sorted(glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"),
                            recursive=True), key=os.path.getsize)[-1]
payload = json.dumps({"transcript_path": sorgente})
inizio = time.time()
r = subprocess.run([sys.executable, "-m", "starkeno.hook_ingestione"],
                   input=payload, capture_output=True, text=True,
                   env={**os.environ, "STARKENO_DB_PATH": os.path.join(
                       os.environ.get("TEMP", "/tmp"), "prova_hook.db")})
print("file piu' grande: %.1f MB" % (os.path.getsize(sorgente) / 1e6))
print("uscita:", r.returncode, "| durata: %.2f s" % (time.time() - inizio))
print("stderr:", repr(r.stderr[:200]))
PY
```
Expected: `uscita: 0`, durata **sotto i 5 secondi**, `stderr: ''`.
Se supera i 5 secondi, l'hook va reso incrementale prima di andare avanti — un hook che
fa aspettare a ogni turno viene disinstallato.

- [x] **Step 7: Eseguire la suite intera**

Run: `python -m pytest -q`
Expected: PASS

- [x] **Step 8: Commit**

```bash
git add starkeno/hook_ingestione.py tests/test_hook.py
git commit -m "feat: l'hook di ingestione, che non rompe mai la sessione (fase 1, task 8)"
```

---

## Task 9: Il plugin che impacchetta l'hook, e la prova con dati veri

> ✅ **ESEGUITO E VERIFICATO l'08/08/2026.** Tre scostamenti dal piano, tutti misurati:
>
> 1. **Il plugin sta alla radice del repository**, non in `plugin/`: cosi'
>    `${CLAUDE_PLUGIN_ROOT}` e' gia' la radice del codice e il comando non deve risalire
>    con `..` per trovare il modulo che lancia.
> 2. **`python -m starkeno.hook_ingestione` (Step 2) non funziona:** da una cartella
>    estranea esce 1 con `ModuleNotFoundError`. Ma invocarlo per percorso senza bootstrap
>    e' PEGGIO — uscita 0, stderr vuoto, zero righe, per sempre. Il modulo si mette la
>    radice su `sys.path` da solo. **Nessun lanciatore `.cmd`, contro l'ipotesi iniziale.**
> 3. **`"async": true`** aggiunto, e `timeout` portato a 60.
>
> **Step 3 — la registrazione, che e' costata un giro a vuoto.** Un hook scritto in un file
> di impostazioni **creato da zero a sessione avviata NON scatta mai**; scritto in un file
> **gia' esistente** scatta subito, senza riavvio. La documentazione parla di un *file
> watcher*, e un watcher sorveglia file che esistono.
>
> **Step 4/5 — misurato in produzione:** `agent_actions` da **1 riga a 69** senza che
> nessuno chiamasse niente. 68 chiamate distinte su 68 righe con sessione, **nessun
> duplicato**; 15 chiamate con piu' di un'azione; 3 azioni fallite; 47 con skill; e i
> timestamp sono quelli del transcript (13:32→14:06), non l'istante dell'ingestione.
>
> **Step 6/7:** `README.md` e `LICENSE` (MIT) scritti; commit `c755039`, `db2f3b0`,
> `a56b9e9`, `6bcc3c7`.


**Files:**
- Create: `plugin/.claude-plugin/plugin.json`
- Create: `plugin/hooks/hooks.json`
- Modify: `README.md`
- Test: verifica manuale su una sessione vera

- [x] **Step 1: Scrivere `plugin/.claude-plugin/plugin.json`**

```json
{
  "name": "starkeno",
  "description": "Trova sprechi ed errori nel modo in cui lavori con Claude Code",
  "version": "0.1.0"
}
```

- [x] **Step 2: Scrivere `plugin/hooks/hooks.json`**

> Sostituire il nome dell'evento con quello **verificato nel Task 7**.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python -m starkeno.hook_ingestione",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

- [x] **Step 3: Registrare l'hook per davvero e fare una sessione**

Aggiungere l'hook a `.claude/settings.local.json` puntando al modulo installato, poi
riavviare Claude Code in questa cartella e lavorare qualche scambio.

- [x] **Step 4: Verificare che i dati siano arrivati — la prova che tutto il piano esiste per dare**

```bash
python -c "
import sqlite3, starkeno.config as c
con = sqlite3.connect(c.DB_PATH)
print('database:', c.DB_PATH)
print('righe:', con.execute('SELECT COUNT(*) FROM agent_actions').fetchone()[0])
print()
print('per progetto:')
for r in con.execute('SELECT project, COUNT(*), SUM(tokens_used) FROM agent_actions GROUP BY project ORDER BY 2 DESC'):
    print('  %-28s %5d azioni  %12d token' % r)
print()
print('ultime 5 azioni:')
for r in con.execute('SELECT timestamp, project, action, model_used, azioni_nella_chiamata, esito_noto, azione_fallita FROM agent_actions ORDER BY id DESC LIMIT 5'):
    print(' ', r)
"
```
Expected: **più di una riga**, `project` valorizzato col nome della cartella, `session_id`
non vuoto, `azioni_nella_chiamata` a volte maggiore di 1.

- [x] **Step 5: Verificare che rieseguire non duplichi**

Fare altri due scambi nella stessa sessione, poi:

```bash
python -c "
import sqlite3, starkeno.config as c
con = sqlite3.connect(c.DB_PATH)
tot = con.execute('SELECT COUNT(*) FROM agent_actions').fetchone()[0]
distinte = con.execute('SELECT COUNT(*) FROM (SELECT DISTINCT session_id, message_id FROM agent_actions WHERE session_id != \"\")').fetchone()[0]
vuote = con.execute('SELECT COUNT(*) FROM agent_actions WHERE session_id = \"\"').fetchone()[0]
print('righe:', tot, '| chiamate distinte:', distinte, '| righe senza sessione (preesistenti):', vuote)
assert tot - vuote == distinte, 'DUPLICATI: l indice unico non sta funzionando'
print('nessun duplicato')
"
```
Expected: `nessun duplicato`

- [x] **Step 6: Aggiornare il `README.md`**

Aggiungere una sezione «Installazione» che dica: il plugin registra un hook di fine turno,
il database vive in `%LOCALAPPDATA%\StarkEno` (Windows) / `~/.local/share/starkeno`
(Linux) / `~/Library/Application Support/StarkEno` (macOS), e chi aveva già un database
accanto al codice se lo ritrova spostato con una copia `.trasferito` lasciata indietro.

- [x] **Step 7: Commit**

```bash
git add plugin README.md
git commit -m "feat: il plugin che impacchetta l'hook, e la prima ingestione vera (fase 1, task 9)"
```

---

## Fine della Fase 1

**Cosa esiste adesso che non esisteva:** un database fuori dalla cartella del codice, con
dentro le chiamate API vere di Claude Code, alla grana giusta, che non si duplicano.

**Cosa è stato chiuso:** il buco per cui il progetto era fermo da agosto — *nessun agente
logga* — e il passo che il `CLAUDE.md` chiamava «il passo che manca davvero».

**Cosa NON esiste ancora:** niente da guardare. Il conto è la Fase 2.

**Prima della Fase 3** vanno chiusi i punti aperti 5 e 6 del design: il filtro sulle
compattazioni per S3, e la stabilità dell'autotaratura rimisurata col quantile.
