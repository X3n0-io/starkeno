"""Il Blueprint d'esempio, spedito DENTRO il pacchetto.

I due comandi in cima al README puntavano a `tests/fixtures/preflight/medium.json`, che
esiste solo in un clone del repository. Il percorso d'installazione documentato e'
`pip install`, e li' quella cartella non c'e': la porta d'ingresso della meta'
predittiva falliva per chiunque non avesse clonato. Trovato installando in un
virtualenv pulito, non rileggendo il README.

L'esempio e' lo STESSO Blueprint che genera l'immagine nel README, cosi' chi lancia i
comandi vede la schermata che gli e' stata promessa e non una simile.

Letto con `importlib.resources`: un percorso relativo al file sorgente funziona nel
repository e si rompe nel wheel — cioe' proprio dove serve.
"""
from __future__ import annotations

from importlib import resources

PACCHETTO_ESEMPI = "starkeno.esempi"
BLUEPRINT_ESEMPIO = "catalogo.json"


def leggi_esempio() -> str:
    """Il Blueprint d'esempio come testo, dal pacchetto installato."""
    return (
        resources.files(PACCHETTO_ESEMPI)
        .joinpath(BLUEPRINT_ESEMPIO)
        .read_text(encoding="utf-8")
    )
