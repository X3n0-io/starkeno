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
    senza rete e senza chiave — che e' il punto della §3.3 della specifica."""
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
