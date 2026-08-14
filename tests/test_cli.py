import json
import subprocess
import sys
from pathlib import Path

import pytest

from starkeno.diagnostica import Controllo
from starkeno.cli import main


def test_module_cli_delegates_report(tmp_path, monkeypatch):
    visti = {}

    def report_finto(args):
        visti["args"] = args
        return 0

    monkeypatch.setattr("starkeno.cli.report_conto.main", report_finto)

    assert main([
        "report", "--output", str(tmp_path / "conto.html"), "--no-open",
    ]) == 0
    assert visti["args"][-1] == "--no-open"


def test_module_cli_delega_preflight_prima_del_doctor(monkeypatch):
    visti = {}

    def preflight_finto(args):
        visti["args"] = args
        return 7

    monkeypatch.setattr("starkeno.preflight_cli.main", preflight_finto)
    monkeypatch.setattr(
        "starkeno.cli._diagnosi_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("doctor eseguito")),
    )

    assert main(["preflight", "draft", "--input-format", "json"]) == 7
    assert visti["args"] == ["draft", "--input-format", "json"]


def test_importare_la_cli_non_carica_il_core_preflight():
    """L'import top-level di preflight_cli trascinava pydantic e PyYAML in ogni
    invocazione di doctor e report, che non ne hanno bisogno."""
    codice = (
        "import sys, starkeno.cli;"
        "sys.exit(1 if 'starkeno.preflight_cli' in sys.modules else 0)"
    )

    esito = subprocess.run([sys.executable, "-c", codice], capture_output=True)

    assert esito.returncode == 0, esito.stderr.decode("utf-8", "replace")


def test_repair_requires_the_explicit_confirmation(tmp_path):
    with pytest.raises(SystemExit) as errore:
        main(["doctor", "--repair-from", str(tmp_path / "storico.db")])

    assert errore.value.code == 2


def test_doctor_json_is_machine_readable_and_fails_on_real_errors(
    monkeypatch, capsys,
):
    monkeypatch.setattr(
        "starkeno.cli._diagnosi_runtime",
        lambda: (
            Controllo("python", "ok", "Python supportato", {"versione": "3.12"}),
            Controllo("database", "errore", "database_assente"),
        ),
    )

    assert main(["doctor", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["codice"] == "python"
    assert payload[1] == {
        "codice": "database", "stato": "errore",
        "dettaglio": "database_assente", "dati": {},
    }


def test_confirmed_repair_uses_the_canonical_destination_then_reruns_doctor(
    tmp_path, monkeypatch, capsys,
):
    sorgente = tmp_path / "storico.db"
    destinazione = tmp_path / "dati" / "starkeno.db"
    chiamate = []

    def recupero_finto(source, destination, **kwargs):
        chiamate.append((Path(source), Path(destination), kwargs))

    monkeypatch.setenv("STARKENO_DB_PATH", str(destinazione))
    monkeypatch.setattr("starkeno.cli.recupera_database", recupero_finto)
    monkeypatch.setattr(
        "starkeno.cli._diagnosi_runtime",
        lambda: (Controllo("database", "ok", "database integro"),),
    )

    assert main([
        "doctor", "--repair-from", str(sorgente), "--confirm-repair", "--json",
    ]) == 0
    assert chiamate[0][:2] == (sorgente, destinazione)
    assert callable(chiamate[0][2]["migra"])
    assert json.loads(capsys.readouterr().out)[0]["stato"] == "ok"
