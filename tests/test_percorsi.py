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


def test_su_windows_i_dati_non_stanno_sotto_appdata(monkeypatch):
    """`%LOCALAPPDATA%` sembra un percorso normale e non lo e'.

    Un processo lanciato da un host impacchettato MSIX — Claude Code lo e' — scrive li'
    dentro un overlay privato del pacchetto. Misurato il 15/08/2026: lo stesso identico
    script contava **12 righe dentro l'hook e 699 da una shell**, allo stesso percorso.
    L'hook raccoglieva, ingeriva e scriveva senza un errore, in un database che `report`
    e `doctor` non guardavano: raccolta perduta e invisibile, che e' la forma di
    fallimento che questo progetto rifiuta ovunque.

    La home non e' virtualizzata: verificato scrivendo un file da dentro l'hook e
    rileggendolo da una shell normale.
    """
    import sys as modulo_sys

    monkeypatch.setattr(modulo_sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))

    cartella = percorsi.cartella_dati()

    assert "AppData" not in cartella.parts, (
        "sotto AppData un host impacchettato scrive in un database invisibile all'utente"
    )
    assert cartella == Path.home() / ".starkeno"


def test_la_vecchia_cartella_windows_resta_conoscibile(monkeypatch):
    """Chi aggiorna ha lo storico nella vecchia posizione: se StarkEno smettesse di
    saperlo, `doctor` non potrebbe piu' proporne il recupero."""
    import sys as modulo_sys

    monkeypatch.setattr(modulo_sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))

    assert percorsi.cartella_dati_windows_storica() == (
        Path.home() / "AppData" / "Local" / "StarkEno")


def test_fuori_da_windows_non_esiste_una_cartella_storica(monkeypatch):
    import sys as modulo_sys

    monkeypatch.setattr(modulo_sys, "platform", "linux")

    assert percorsi.cartella_dati_windows_storica() is None


def test_la_variabile_di_ambiente_vince_sul_default(monkeypatch, tmp_path):
    """`STARKENO_DB_PATH` deve restare la giuntura: i test ci si appoggiano."""
    import importlib
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "altro.db"))
    from starkeno import config
    importlib.reload(config)
    assert config.DB_PATH == str(tmp_path / "altro.db")
    monkeypatch.delenv("STARKENO_DB_PATH")
    importlib.reload(config)
