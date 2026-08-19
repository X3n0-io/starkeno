"""Rigenera l'immagine del conto per il README, da dati di nessuno.

**Perche' uno script e non uno screenshot fatto a mano.** Il conto cambia, e
un'immagine fatta a mano invecchia senza emettere un segnale: la pagina promette una
schermata che il programma non produce piu', e nessuno se ne accorge finche' non lo fa
un estraneo. E' la stessa forma di difetto che questo progetto ha gia' pagato con
l'hook che scriveva altrove e con la copia del plugin ferma a una versione.

**Perche' non il database vero.** Il conto vero contiene i nomi dei progetti
dell'autore e quanto spende. La sorgente e' `tests/fixtures/transcript_vero.jsonl`,
che e' un transcript vero gia' ripulito: forma reale, dati di nessuno, progetto
anonimizzato in `progetto-01`.

Il database canonico non viene mai toccato: si lavora in una cartella temporanea
tramite `STARKENO_DB_PATH`.

Serve Chrome o Edge installato. Non gira in CI di proposito: un test che dipende da un
browser fallisce per motivi che non riguardano StarkEno.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

RADICE = Path(__file__).resolve().parent.parent
FIXTURE = RADICE / "tests" / "fixtures" / "transcript_vero.jsonl"
DESTINAZIONE = RADICE / "docs" / "immagini" / "conto.png"

# Misurate: 1500x700 taglia subito dopo la tabella «Per progetto», senza spezzare una
# riga a meta'. Il fattore 2 serve agli schermi ad alta densita'.
LARGHEZZA, ALTEZZA, DENSITA = 1500, 700, 2

BROWSER = (
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
)


def _browser() -> Path:
    for percorso in BROWSER:
        if percorso.exists():
            return percorso
    raise SystemExit("nessun Chrome o Edge trovato: indicane uno con --browser")


def genera(destinazione: Path, *, browser: Path | None = None) -> Path:
    eseguibile = browser or _browser()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporanea:
        lavoro = Path(temporanea)
        ambiente = dict(os.environ, STARKENO_DB_PATH=str(lavoro / "starkeno.db"))
        ambiente.pop("PYTHONPATH", None)

        payload = json.dumps({
            "transcript_path": str(FIXTURE),
            "session_id": "demo-vetrina",
            "cwd": str(RADICE),
        })
        subprocess.run(
            [sys.executable, "-P", "-m", "starkeno.hook_ingestione"],
            input=payload, text=True, check=True, cwd=RADICE, env=ambiente,
            capture_output=True,
        )

        pagina = lavoro / "conto.html"
        subprocess.run(
            [sys.executable, "-m", "starkeno", "report",
             "--output", str(pagina), "--no-open"],
            check=True, cwd=RADICE, env=ambiente, capture_output=True,
        )
        if not pagina.is_file():
            raise SystemExit("il conto non e' stato generato: la fixture e' vuota?")

        destinazione.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(eseguibile), "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=%d" % DENSITA,
            "--window-size=%d,%d" % (LARGHEZZA, ALTEZZA),
            "--screenshot=%s" % destinazione,
            pagina.as_uri(),
        ], check=True, capture_output=True)

    if not destinazione.is_file():
        raise SystemExit("il browser non ha scritto l'immagine")
    return destinazione


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DESTINAZIONE)
    parser.add_argument("--browser", type=Path, default=None)
    argomenti = parser.parse_args(argv)

    scritta = genera(argomenti.output, browser=argomenti.browser)
    print("%s (%d KB)" % (scritta, scritta.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
