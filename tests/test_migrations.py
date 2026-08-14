"""Task 0 — Alembic e' l'unica autorita' sullo schema.

Perche' questi test esistono, in una riga: `create_all()` crea le tabelle mancanti ma
**non altera quelle esistenti e non aggiunge indici a una tabella che esiste gia'**.
Verificato eseguendo il codice sul database reale: colonna non aggiunta, indice non
aggiunto, nessun errore. Quindi con `create_all()` in giro ogni modifica di schema della
v1 sarebbe silenziosamente ignorata su `starkeno.db`, che e' gia' popolato.

Nessuno di questi fallimenti produce un errore visibile: producono silenzio.
"""
import os
import sqlite3
import subprocess
import sys

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from starkeno.db import make_session_factory

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Lo schema che la v0 ha lasciato su `starkeno.db`: e' il punto di partenza reale della
# migrazione, e va scritto a mano qui perche' e' cio' che troveremo sul disco.
SCHEMA_V0 = """
CREATE TABLE agent_actions (
    id INTEGER NOT NULL,
    agent_name VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    model_used VARCHAR NOT NULL,
    tokens_used INTEGER NOT NULL,
    timestamp DATETIME NOT NULL,
    PRIMARY KEY (id)
);
CREATE INDEX ix_agent_actions_agent_name ON agent_actions (agent_name);
"""


def alembic_config(db_path):
    """Config di Alembic puntata a un database usa e getta.

    `sqlalchemy.url` esplicito: senza, `env.py` userebbe `config.DB_PATH` e un test
    riscriverebbe il database di produzione (invariante 3 di CLAUDE.md).
    """
    cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(PROJECT_ROOT, "migrations"))
    cfg.set_main_option("sqlalchemy.url", "sqlite:///%s" % str(db_path).replace("\\", "/"))
    return cfg


def head_revision(cfg):
    return ScriptDirectory.from_config(cfg).get_current_head()


def schema_signature(db_path):
    """Firma SEMANTICA dello schema: tabelle, colonne, tipi, vincoli, indici.

    Non il testo del DDL. `sqlite_master.sql` conserva la formattazione letterale della
    CREATE, quindi confrontarlo confronta le tabulazioni: Alembic ne emette una versione,
    `create_all` un'altra, e il file scritto a mano una terza. Sarebbero tre schemi
    identici che risultano diversi.

    Cio' che deve coincidere e' quello che le query vedono: nomi e ordine delle colonne,
    tipi, `NOT NULL`, chiavi primarie, e quali indici esistono su quali colonne.

    `alembic_version` esclusa: e' l'unica tabella che i due percorsi di primo avvio
    scrivono legittimamente in modo diverso.
    """
    conn = sqlite3.connect(str(db_path))
    firma = {}
    tabelle = sorted(
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        )
    )
    for tabella in tabelle:
        colonne = [
            (r[1], r[2].upper(), r[3], r[4], r[5])  # nome, tipo, notnull, default, pk
            for r in conn.execute("PRAGMA table_info(%s)" % tabella)
        ]
        indici = []
        for riga in conn.execute("PRAGMA index_list(%s)" % tabella):
            nome, unico = riga[1], riga[2]
            if nome.startswith("sqlite_autoindex"):
                continue
            colonne_indice = [r[2] for r in conn.execute("PRAGMA index_info(%s)" % nome)]
            indici.append((nome, bool(unico), tuple(colonne_indice)))
        firma[tabella] = (colonne, sorted(indici))
    conn.close()
    return firma


# ------------------------------------------------------- create_all non comanda piu'
def test_make_session_factory_does_not_create_the_schema(tmp_path):
    """`make_session_factory` non deve piu' creare tabelle.

    Finche' lo fa, esistono DUE meccanismi che comandano lo schema, e quello che vince
    e' quello che gira per primo: l'import di `mcp_server` o di `api`. Il risultato e'
    un database senza `alembic_version` su cui la catena delle migrazioni non parte piu'.
    """
    db_path = tmp_path / "vuoto.db"
    session_factory = make_session_factory(str(db_path))

    assert not db_path.exists(), "make_session_factory ha creato il file del database"

    session = session_factory()
    try:
        with pytest.raises(OperationalError, match="no such table"):
            session.execute(text("SELECT 1 FROM agent_actions"))
    finally:
        session.close()
        session_factory.kw["bind"].dispose()


# --------------------------------------------------------- i due percorsi di §3.0
def test_upgrade_head_on_a_new_database_builds_the_whole_schema(tmp_path):
    """Percorso 'database nuovo': un solo `alembic upgrade head`.

    L'ordine delle colonne e' asserito, non solo l'insieme: `ADD COLUMN` accoda in fondo,
    quindi le tre colonne dei token stanno DOPO `timestamp` anche se nel modello si
    leggerebbero meglio accanto a `tokens_used`. Un `SELECT *` posizionale dipende da
    questo, e i modelli ORM devono rispettarlo.
    """
    db_path = tmp_path / "nuovo.db"
    cfg = alembic_config(db_path)

    command.upgrade(cfg, "head")

    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns = [r[1] for r in conn.execute("PRAGMA table_info(agent_actions)")]
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    conn.close()

    assert tables == {
        "agent_actions", "alerts", "rule_status", "supervisor_state",
        "agent_watermark", "alembic_version",
    }
    assert columns == [
        "id", "project", "action", "model_used", "tokens_used", "timestamp",
        "cache_read_tokens", "cache_write_tokens", "output_tokens",
        # 0005, sempre in coda: ADD COLUMN accoda e i modelli devono rispettarlo.
        "session_id", "message_id", "azione_fallita", "esito_noto",
        "azioni_nella_chiamata", "skill", "plugin", "mcp_server", "is_sidechain",
    ]
    assert {"ix_agent_actions_project", "ix_actions_project_time",
            "ix_alerts_one_live", "ix_alerts_open"} <= indexes
    # I nomi vecchi devono SPARIRE, non sopravvivere puntando alla colonna nuova.
    # `ix_agent_actions_agent_name` lo crea da solo il modello ORM con `index=True` e
    # SQLAlchemy ne deriva il nome dalla colonna: rinominare solo la colonna lo lascia
    # sul disco col nome vecchio, e i due schemi divergono senza che niente si lamenti.
    assert not {"ix_agent_actions_agent_name", "ix_actions_agent_time"} & indexes
    assert version == head_revision(cfg)


def test_stamp_then_upgrade_adopts_an_existing_database_without_losing_data(tmp_path):
    """Percorso 'starkeno.db gia' esistente': `stamp <v0>` poi `upgrade head`.

    E' la procedura che verra' eseguita una volta sola sul database di produzione, quindi
    la proprieta' che conta davvero e' che le righe sopravvivano.
    """
    db_path = tmp_path / "esistente.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_V0)
    conn.execute(
        "INSERT INTO agent_actions(agent_name, action, model_used, tokens_used, timestamp) "
        "VALUES('scraper', 'fetch:pagina', 'claude-haiku-4-5', 150, '2026-08-04 17:33:00')"
    )
    conn.commit()
    conn.close()

    cfg = alembic_config(db_path)
    command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")

    conn = sqlite3.connect(str(db_path))
    # `project`, non `agent_name`: la 0004 ha rinominato la colonna sotto i piedi della
    # riga inserita con lo schema v0, ed e' proprio quello che deve sopravvivere.
    righe = conn.execute("SELECT project, tokens_used FROM agent_actions").fetchall()
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    conn.close()

    assert righe == [("scraper", 150)], "la migrazione ha perso o alterato i dati esistenti"
    assert version == head_revision(cfg)


def test_both_startup_paths_produce_the_same_schema(tmp_path):
    """I due percorsi di §3.0 devono convergere.

    Se divergessero, lo sviluppo (database nuovo) e la produzione (database adottato)
    girerebbero su schemi diversi, e i test non vedrebbero mai la differenza.
    """
    nuovo = tmp_path / "nuovo.db"
    command.upgrade(alembic_config(nuovo), "head")

    esistente = tmp_path / "esistente.db"
    conn = sqlite3.connect(str(esistente))
    conn.executescript(SCHEMA_V0)
    conn.commit()
    conn.close()
    cfg = alembic_config(esistente)
    command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")

    assert schema_signature(nuovo) == schema_signature(esistente)


def test_upgrade_refuses_a_database_built_by_create_all(tmp_path):
    """Il fallimento che §3.0 descrive, riprodotto.

    Un database costruito da `create_all()` ha lo schema ma NON ha `alembic_version`:
    Alembic lo tratta come vuoto e prova a ricreare le tabelle. Deve fallire in modo
    rumoroso — e' esattamente il caso in cui serve lo `stamp`.
    """
    db_path = tmp_path / "avvelenato.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_V0)
    conn.commit()
    conn.close()

    with pytest.raises(Exception) as errore:
        command.upgrade(alembic_config(db_path), "head")

    assert "already exists" in str(errore.value).lower()


def test_the_orm_models_and_the_migrations_describe_the_same_schema(tmp_path):
    """**I due schemi che il progetto costruisce devono coincidere.**

    La produzione crea lo schema con Alembic. I test lo creano con `create_all` dai
    modelli ORM (fixture `session_factory` in conftest.py). Sono due sorgenti diverse
    per la stessa cosa, ed e' esattamente la configurazione in cui una divergenza non
    produce nessun errore: la suite resta verde mentre gira su uno schema che in
    produzione non esiste.

    E' l'errore 2 di §12 — "due meccanismi che vogliono comandare la stessa cosa" —
    nella sua forma residua e inevitabile: `create_all` nei test serve, quindi va
    tenuto allineato invece che eliminato.
    """
    from starkeno.db import Base

    da_alembic = tmp_path / "alembic.db"
    command.upgrade(alembic_config(da_alembic), "head")

    da_orm = tmp_path / "orm.db"
    engine = create_engine("sqlite:///%s" % str(da_orm).replace("\\", "/"))
    Base.metadata.create_all(engine)
    engine.dispose()

    atteso = schema_signature(da_alembic)
    ottenuto = schema_signature(da_orm)

    assert set(atteso) == set(ottenuto), "le tabelle non coincidono"
    for tabella in sorted(atteso):
        assert ottenuto[tabella] == atteso[tabella], (
            "la tabella '%s' e' diversa fra Alembic e i modelli ORM:\n"
            "  alembic: %r\n  orm    : %r" % (tabella, atteso[tabella], ottenuto[tabella])
        )


def test_the_documented_cli_command_actually_works(tmp_path):
    """`alembic upgrade head` dalla riga di comando, che e' la procedura di §3.0.

    Questo test gira in un sottoprocesso perche' e' l'UNICO modo di esercitare il ramo
    di fallback di `env.py` (quello che ricade su `config.DB_PATH`): tutti gli altri
    test passano un `sqlalchemy.url` esplicito e quel ramo non lo tocca nessuno.

    Verificato che serviva: col placeholder `driver://user:pass@localhost/dbname` che
    `alembic init` lascia in `alembic.ini`, il comando moriva su
    `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:driver`. Tutti i test
    passavano lo stesso, e il comando documentato non funzionava.
    """
    db_path = tmp_path / "da_cli.db"
    env = {**os.environ, "STARKENO_DB_PATH": str(db_path), "PYTHONPATH": PROJECT_ROOT}

    risultato = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
    )

    assert risultato.returncode == 0, "alembic upgrade head e' fallito:\n%s" % risultato.stderr
    assert db_path.exists(), "il comando non ha migrato il database indicato da STARKENO_DB_PATH"

    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "agent_actions" in tables


# ------------------------------------------------- il controllo di versione all'avvio
def test_check_or_die_passes_when_the_database_is_at_head(tmp_path):
    from starkeno.schema_version import check_or_die

    db_path = tmp_path / "ok.db"
    command.upgrade(alembic_config(db_path), "head")

    engine = create_engine("sqlite:///%s" % str(db_path).replace("\\", "/"))
    check_or_die(engine)  # non deve sollevare
    engine.dispose()


def test_check_or_die_refuses_to_start_on_an_unmigrated_database(tmp_path):
    """L'unica eccezione ammessa a "il log non deve mai fallire" (§7).

    Fallire rumorosamente all'avvio e' infinitamente meglio di un `no such column`
    inghiottito da un try/except un'ora dopo.
    """
    from starkeno.schema_version import SchemaVersionError, check_or_die

    db_path = tmp_path / "vecchio.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_V0)
    conn.commit()
    conn.close()

    engine = create_engine("sqlite:///%s" % str(db_path).replace("\\", "/"))
    with pytest.raises(SchemaVersionError) as errore:
        check_or_die(engine)
    engine.dispose()

    messaggio = str(errore.value)
    assert "alembic upgrade head" in messaggio, "il messaggio non dice come rimediare"
    assert "stamp" in messaggio, "il messaggio non copre il caso del database gia' esistente"


def test_the_api_refuses_to_start_on_an_unmigrated_database(tmp_path, monkeypatch):
    """Il controllo non basta che esista: dev'essere CABLATO all'avvio del processo.

    Senza questo test, `check_or_die` puo' essere perfetta e non venire chiamata da
    nessuno — e l'API partirebbe volentieri su uno schema vecchio.
    """
    from fastapi.testclient import TestClient

    import starkeno.api as api_module
    from starkeno.db import make_session_factory
    from starkeno.schema_version import SchemaVersionError

    db_path = tmp_path / "vecchio.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_V0)
    conn.commit()
    conn.close()

    factory = make_session_factory(str(db_path))
    monkeypatch.setattr(api_module, "get_session_factory", lambda: factory)

    try:
        # la forma `with` e' quella che esegue il lifespan; quella semplice no
        with pytest.raises(SchemaVersionError):
            with TestClient(api_module.app):
                pass
    finally:
        factory.kw["bind"].dispose()


def test_the_api_starts_when_the_schema_is_at_head(tmp_path, monkeypatch):
    """Il complemento del test precedente: senza, basterebbe sollevare sempre."""
    import starkeno.api as api_module
    from fastapi.testclient import TestClient
    from starkeno.db import make_session_factory

    db_path = tmp_path / "aggiornato.db"
    command.upgrade(alembic_config(db_path), "head")

    factory = make_session_factory(str(db_path))
    monkeypatch.setattr(api_module, "get_session_factory", lambda: factory)

    try:
        with TestClient(api_module.app) as client:
            assert client.get("/api/agents").status_code == 200
    finally:
        factory.kw["bind"].dispose()
