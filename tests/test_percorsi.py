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
