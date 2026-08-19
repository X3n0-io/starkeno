"""Rende `docs/immagini/anteprima-social.html` nell'immagine 1280x640 di GitHub.

E' l'immagine che compare quando il link al repository viene condiviso su X, Slack,
Hacker News o in un messaggio. Senza, esce una card grigia generica: il link viene
condiviso lo stesso, ma non dice niente.

**Va caricata a mano.** L'API di GitHub non espone questo campo — provato: un `PATCH`
con `social_preview` viene ignorato senza errore. Si carica da
Settings -> General -> Social preview.

La sorgente e' HTML accanto all'immagine, cosi' il testo si corregge senza aprire un
editor grafico e senza che nessuno debba indovinare con cosa era stata fatta.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Sequence

from genera_immagine_conto import _browser

RADICE = Path(__file__).resolve().parent.parent
SORGENTE = RADICE / "docs" / "immagini" / "anteprima-social.html"
DESTINAZIONE = RADICE / "docs" / "immagini" / "anteprima-social.png"

# Il formato che GitHub si aspetta. Un'immagine di proporzioni diverse viene ritagliata
# al centro, e il ritaglio cade sempre sulla riga che conta.
LARGHEZZA, ALTEZZA = 1280, 640


def genera(destinazione: Path = DESTINAZIONE, *, browser: Path | None = None) -> Path:
    eseguibile = browser or _browser()
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(eseguibile), "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--window-size=%d,%d" % (LARGHEZZA, ALTEZZA),
        "--screenshot=%s" % destinazione,
        SORGENTE.as_uri(),
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
    print("%s (%d KB) — caricala da Settings -> General -> Social preview"
          % (scritta, scritta.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
