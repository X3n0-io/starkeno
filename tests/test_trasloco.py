"""Cambiare il default non basta: chi ha gia' un database va portato dietro.

Se la storia e' il prodotto, perderla all'aggiornamento e' perdere il prodotto.
"""
import sqlite3

from alembic import command

from starkeno import trasloco
from starkeno.migrazioni import configurazione_alembic


def _database_finto(percorso, righe=1):
    percorso.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(configurazione_alembic(percorso), "0003")
    con = sqlite3.connect(str(percorso))
    for i in range(righe):
        con.execute(
            "INSERT INTO agent_actions"
            "(agent_name, action, model_used, tokens_used, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ("vecchio-%d" % i, "read:a.py", "gpt-5", 100,
             "2026-08-12 10:00:00"),
        )
    con.commit()
    con.close()


def test_copia_il_database_vecchio_e_conserva_le_righe(tmp_path, monkeypatch):
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


def test_lascia_intatto_l_originale_invece_di_rinominarlo(tmp_path, monkeypatch):
    """La copia esplicita non rinomina né cancella lo storico di partenza."""
    codice = tmp_path / "codice"
    codice.mkdir()
    _database_finto(codice / "starkeno.db")
    dati = tmp_path / "dati"
    monkeypatch.setattr(trasloco.percorsi, "cartella_dati", lambda: dati)
    monkeypatch.setattr(trasloco.percorsi, "percorso_database", lambda: str(dati / "starkeno.db"))

    trasloco.trasloca_se_serve(radice_codice=codice)

    assert (codice / "starkeno.db").exists()
    assert not (codice / "starkeno.db.trasferito").exists()


def test_eseguirlo_due_volte_non_fa_danni(tmp_path, monkeypatch):
    """Idempotenza: ripetere esplicitamente l'operazione non duplica la storia."""
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
