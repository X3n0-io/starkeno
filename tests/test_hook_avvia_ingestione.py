"""Compatibilita' con i runtime Codex che non eseguono ancora hook async."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from starkeno import hook_avvia_ingestione


def _riga():
    return json.dumps({
        "sessionId": "sessione-background",
        "timestamp": "2026-08-12T17:00:00.000Z",
        "cwd": "/x/progetto",
        "message": {
            "id": "messaggio-background",
            "model": "gpt-5.6-terra",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [],
        },
    })


def test_launcher_restituisce_subito_e_ingestione_prosegue_in_background(tmp_path):
    radice = Path(hook_avvia_ingestione.__file__).resolve().parent.parent
    estranea = tmp_path / "progetto-utente"
    estranea.mkdir()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(_riga(), encoding="utf-8")
    database = tmp_path / "dati" / "starkeno.db"
    payload = json.dumps({
        "transcript_path": str(transcript),
        "session_id": "sessione-background",
        "cwd": str(estranea),
    })
    ambiente = dict(os.environ, STARKENO_DB_PATH=str(database))
    ambiente.pop("PYTHONPATH", None)

    inizio = time.monotonic()
    esito = subprocess.run(
        [sys.executable, str(radice / "starkeno" / "hook_avvia_ingestione.py")],
        input=payload,
        capture_output=True,
        text=True,
        cwd=estranea,
        env=ambiente,
        timeout=5,
    )
    durata = time.monotonic() - inizio

    assert esito.returncode == 0
    assert esito.stdout == esito.stderr == ""
    assert durata < 1.0, "il launcher ha atteso la fine dell'ingestione"

    scadenza = time.monotonic() + 20
    while time.monotonic() < scadenza:
        if database.exists():
            try:
                with sqlite3.connect(database) as conn:
                    righe = conn.execute(
                        "SELECT COUNT(*) FROM agent_actions"
                    ).fetchone()[0]
                if righe == 1:
                    break
            except sqlite3.Error:
                pass
        time.sleep(0.05)
    else:
        raise AssertionError("l'ingestione in background non ha scritto la chiamata")
