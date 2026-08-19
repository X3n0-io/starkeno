"""Il simulatore non regge i cicli lunghi, e deve dirlo invece di tacere.

Trovato provando a produrre la SECONDA misura per lo scarto 9x: un Blueprint che
descrive una sessione vera di 586 turni fa esplodere il lookahead ricorsivo di
`preflight_simulate`. La sessione da cui nasce questo test aveva 586 chiamate raccolte.

Misurato: regge fino a 150 passaggi, si rompe fra 150 e 200.

Il difetto peggiore non e' il limite — un limite si dichiara e si aggira. E' che
l'utente vedeva `Errore interno durante preflight.` e un codice 1, cioe' la forma di
guasto che questo progetto dichiara di combattere: qualcosa si perde senza emettere un
segnale utile.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from starkeno import preflight_cli

FIXTURE = Path(__file__).parent / "fixtures" / "preflight" / "sessione-lunga.json"


def _bozza(tmp_path: Path, traversate: int) -> Path:
    blueprint = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for transizione in blueprint["transitions"]:
        if transizione.get("max_traversals") is not None:
            transizione["max_traversals"] = traversate
    sorgente = tmp_path / "sessione.json"
    sorgente.write_text(json.dumps(blueprint), encoding="utf-8")

    bozza = tmp_path / "bozza.json"
    assert preflight_cli.main([
        "draft", "--input", str(sorgente), "--format", "json", "--output", str(bozza),
    ]) == 0
    return bozza


def _analizza(tmp_path: Path, bozza: Path) -> int:
    return preflight_cli.main([
        "analyze", "--input", str(bozza), "--confirmed", "--samples", "20",
        "--format", "json", "--output", str(tmp_path / "analisi.json"),
    ])


def test_un_ciclo_corto_si_analizza(tmp_path):
    """Il limite e' nel numero di passaggi, non nella forma: senza questo il test
    successivo proverebbe soltanto che il Blueprint e' sbagliato."""
    assert _analizza(tmp_path, _bozza(tmp_path, 100)) == 0


def test_un_ciclo_lungo_fallisce_dicendo_perche(tmp_path, capsys):
    """Il limite resta, ma smette di presentarsi come un errore interno."""
    esito = _analizza(tmp_path, _bozza(tmp_path, 585))

    assert esito == 2, "un limite noto non e' un errore interno: deve uscire 2, non 1"
    uscita = capsys.readouterr()
    messaggio = uscita.err + uscita.out
    assert "cicl" in messaggio.lower(), (
        "il messaggio non nomina la causa: %r" % messaggio
    )
