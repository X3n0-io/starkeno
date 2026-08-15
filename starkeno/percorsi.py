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

    **E su Windows NON sotto `%LOCALAPPDATA%.`** Sembra il posto giusto, ed e' quello che
    la convenzione indica, ma un processo lanciato da un host impacchettato MSIX scrive
    li' dentro un overlay privato del pacchetto. Claude Code e' impacchettato cosi':
    misurato il 15/08/2026, lo stesso identico script contava 12 righe eseguito
    dall'hook e 699 eseguito da una shell, allo stesso percorso. L'hook ingeriva e
    scriveva senza un errore, in un database che `report` e `doctor` non guardavano.
    La home invece non e' virtualizzata, verificato scrivendoci da dentro l'hook e
    rileggendo da fuori.
    """
    if sys.platform == "win32":
        return Path.home() / ".starkeno"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "StarkEno"
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "starkeno"
    return Path.home() / ".local" / "share" / "starkeno"


def cartella_dati_windows_storica() -> Path | None:
    """Dove stava il database su Windows prima del 15/08/2026, se esisteva.

    Serve a `doctor`: chi aggiorna ha lo storico li' e deve poterselo riprendere. Non
    la usa nessun percorso automatico — adottare uno storico resta una decisione
    esplicita dell'utente, con backup e verifica.
    """
    if sys.platform != "win32":
        return None
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "StarkEno" if base else None


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
