"""L'esempio deve vivere DENTRO il pacchetto, non accanto al repository.

I due comandi in cima al README — la porta d'ingresso di tutta la meta' predittiva —
puntavano a `tests/fixtures/preflight/medium.json`. Chi installa con `pip`, che e' il
percorso d'installazione documentato, quella cartella non ce l'ha: il comando di punta
falliva per chiunque non avesse clonato. Misurato installando in un virtualenv pulito.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from starkeno import preflight_cli
from starkeno.preflight_esempio import BLUEPRINT_ESEMPIO, leggi_esempio


def test_l_esempio_e_leggibile_come_risorsa_del_pacchetto():
    """Letto con importlib.resources e non da un percorso relativo: e' l'unica forma
    che sopravvive a un wheel installato, che e' esattamente il caso che falliva."""
    testo = leggi_esempio()

    blueprint = json.loads(testo)
    assert blueprint["schema_version"] == "1.0"
    assert blueprint["nodes"], "un esempio senza nodi non simula niente"


def test_il_comando_esempio_scrive_un_blueprint_valido(tmp_path):
    destinazione = tmp_path / "esempio.json"

    assert preflight_cli.main(["esempio", "--output", str(destinazione)]) == 0
    assert json.loads(destinazione.read_text(encoding="utf-8"))["schema_version"] == "1.0"


def test_l_esempio_attraversa_draft_e_analyze(tmp_path):
    """La prova che conta: la catena esatta che il README promette al lettore."""
    esempio = tmp_path / "esempio.json"
    bozza = tmp_path / "bozza.yaml"
    report = tmp_path / "report.html"

    assert preflight_cli.main(["esempio", "--output", str(esempio)]) == 0
    assert preflight_cli.main([
        "draft", "--input", str(esempio), "--format", "yaml", "--output", str(bozza),
    ]) == 0
    assert preflight_cli.main([
        "analyze", "--input", str(bozza), "--confirmed", "--samples", "20",
        "--format", "html", "--output", str(report),
    ]) == 0
    assert report.read_text(encoding="utf-8").strip(), "il report e' vuoto"


def test_il_comando_rifiuta_di_sovrascrivere_in_silenzio(tmp_path):
    """Scrivere sopra il Blueprint su cui qualcuno sta lavorando, perche' ha rilanciato
    il comando del README, e' una perdita silenziosa: quelle questo progetto le paga."""
    destinazione = tmp_path / "esempio.json"
    destinazione.write_text("{\"mio\": \"lavoro\"}", encoding="utf-8")

    assert preflight_cli.main(["esempio", "--output", str(destinazione)]) == 2
    assert json.loads(destinazione.read_text(encoding="utf-8")) == {"mio": "lavoro"}


def test_l_esempio_e_nel_wheel(tmp_path):
    """Un test sul sorgente non dice niente sul pacchetto spedito, ed e' proprio la
    differenza fra i due che ha prodotto il difetto."""
    radice = Path(preflight_cli.__file__).resolve().parent.parent
    esito = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=radice, capture_output=True, text=True,
    )
    if esito.returncode != 0:
        import pytest
        pytest.skip("build non disponibile: %s" % esito.stderr.strip()[-200:])

    import zipfile
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as z:
        nomi = z.namelist()
    assert any(n.endswith(BLUEPRINT_ESEMPIO) for n in nomi), (
        "%s non e' nel wheel: %r" % (BLUEPRINT_ESEMPIO, [n for n in nomi if "esempi" in n])
    )
