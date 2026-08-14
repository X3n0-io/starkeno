"""L'hook SessionStart deve aggiungere contesto senza poter rompere Codex."""
import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from starkeno import db
from starkeno.db import AgentAction


def _stdin(payload) -> io.StringIO:
    return io.StringIO(json.dumps(payload))


def _payload(*, evento="SessionStart", source="startup") -> dict:
    return {"hook_event_name": evento, "source": source}


def _percorso_db(session_factory) -> str:
    return session_factory.kw["bind"].url.database


def test_primo_avvio_restituisce_contesto_codex_senza_creare_database(
        monkeypatch, tmp_path, capsys):
    from starkeno import hook_inizio_sessione

    percorso = tmp_path / "cartella-ancora-assente" / "starkeno.db"
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr(sys, "stdin", _stdin(_payload()))

    assert hook_inizio_sessione.main() == 0
    uscita, errore = capsys.readouterr()
    risposta = json.loads(uscita)
    specifica = risposta["hookSpecificOutput"]
    assert specifica["hookEventName"] == "SessionStart"
    assert "StarkEno" in specifica["additionalContext"]
    assert "una sola breve riga" in specifica["additionalContext"]
    assert "prossimo messaggio utile" in specifica["additionalContext"]
    assert all(
        regola not in specifica["additionalContext"]
        for regola in ("R1", "R2", "R3", "R4")
    )
    assert errore == ""
    assert not percorso.exists()
    assert not percorso.parent.exists(), "SessionStart non deve creare nemmeno la cartella dati"


def test_database_con_schema_ma_senza_chiamate_mostra_il_benvenuto(
        monkeypatch, session_factory, capsys):
    from starkeno import hook_inizio_sessione

    monkeypatch.setenv("STARKENO_DB_PATH", _percorso_db(session_factory))
    monkeypatch.setattr(sys, "stdin", _stdin(_payload()))

    assert hook_inizio_sessione.main() == 0
    uscita, errore = capsys.readouterr()
    assert json.loads(uscita)["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert errore == ""


def test_database_con_storico_tace_fino_alla_fase_3(
        monkeypatch, session_factory, capsys):
    from starkeno import hook_inizio_sessione

    with session_factory() as sessione:
        sessione.add(AgentAction(
            project="progetto", action="leggi", model_used="gpt-5",
            tokens_used=10, session_id="sessione", message_id="messaggio",
        ))
        sessione.commit()
    monkeypatch.setenv("STARKENO_DB_PATH", _percorso_db(session_factory))
    monkeypatch.setattr(sys, "stdin", _stdin(_payload()))

    assert hook_inizio_sessione.main() == 0
    uscita, errore = capsys.readouterr()
    assert uscita == ""
    assert errore == ""


@pytest.mark.parametrize("payload", [
    _payload(source="resume"),
    _payload(source="clear"),
    _payload(source="compact"),
    _payload(evento="Stop"),
    {},
])
def test_solo_session_start_startup_puo_aggiungere_contesto(
        payload, monkeypatch, tmp_path, capsys):
    from starkeno import hook_inizio_sessione

    percorso = tmp_path / "non-va-creato.db"
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr(sys, "stdin", _stdin(payload))

    assert hook_inizio_sessione.main() == 0
    assert capsys.readouterr() == ("", "")
    assert not percorso.exists()


@pytest.mark.parametrize("stdin", ["{json rotto", "[]"])
def test_input_invalido_esce_zero_senza_rumore(stdin, monkeypatch, capsys):
    from starkeno import hook_inizio_sessione

    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))

    assert hook_inizio_sessione.main() == 0
    assert capsys.readouterr() == ("", "")


def test_errore_di_lettura_esce_zero_senza_rumore(monkeypatch, tmp_path, capsys):
    from starkeno import hook_inizio_sessione

    percorso = tmp_path / "esiste.db"
    sqlite3.connect(percorso).close()
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr(sys, "stdin", _stdin(_payload()))
    monkeypatch.setattr(
        db, "make_readonly_session_factory",
        lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert hook_inizio_sessione.main() == 0
    assert capsys.readouterr() == ("", "")


def test_lanciato_per_percorso_da_cwd_estraneo_restituisce_contesto(tmp_path):
    from starkeno import hook_inizio_sessione

    radice = Path(hook_inizio_sessione.__file__).resolve().parent.parent
    percorso_db = tmp_path / "dati" / "starkeno.db"
    estranea = tmp_path / "un" / "altro" / "progetto"
    estranea.mkdir(parents=True)
    ambiente = dict(os.environ, STARKENO_DB_PATH=str(percorso_db))
    ambiente.pop("PYTHONPATH", None)

    esito = subprocess.run(
        [sys.executable, str(radice / "starkeno" / "hook_inizio_sessione.py")],
        input=json.dumps(_payload()), capture_output=True, text=True,
        cwd=str(estranea), env=ambiente, timeout=30,
    )

    assert esito.returncode == 0
    assert esito.stderr == ""
    assert json.loads(esito.stdout)["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert not percorso_db.exists()
