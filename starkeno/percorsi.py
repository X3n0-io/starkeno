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
