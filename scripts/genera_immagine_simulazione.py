"""Rigenera l'immagine del report di simulazione per il README.

E' la meta' del progetto su cui si regge la presentazione, ed era l'unica senza
un'immagine: il lettore doveva credere sulla parola che il simulatore producesse
qualcosa.

La sorgente e' il Blueprint d'esempio SPEDITO COL PACCHETTO, lo stesso che il README
fa scrivere con `preflight esempio`: cosi' il lettore riproduce esattamente questa
schermata, e non una simile. Se le due sorgenti divergessero, l'immagine mentirebbe.

Serve Chrome o Edge. Non gira in CI di proposito, per lo stesso motivo dell'altra.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from genera_immagine_conto import _browser

RADICE = Path(__file__).resolve().parent.parent
BLUEPRINT = RADICE / "starkeno" / "esempi" / "catalogo.json"
DESTINAZIONE = RADICE / "docs" / "immagini" / "simulazione.png"

# Misurate: taglia dopo «Provenance delle stime», che e' la riga che distingue questo
# report da una stima qualunque. Il fattore 2 serve agli schermi ad alta densita'.
LARGHEZZA, ALTEZZA, DENSITA = 1400, 900, 2


def genera(destinazione: Path = DESTINAZIONE, *, browser: Path | None = None) -> Path:
    eseguibile = browser or _browser()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporanea:
        lavoro = Path(temporanea)
        bozza, report = lavoro / "draft.yaml", lavoro / "report.html"

        subprocess.run([
            sys.executable, "-m", "starkeno", "preflight", "draft",
            "--input", str(BLUEPRINT), "--format", "yaml", "--output", str(bozza),
        ], check=True, cwd=RADICE, capture_output=True)

        subprocess.run([
            sys.executable, "-m", "starkeno", "preflight", "analyze",
            "--input", str(bozza), "--confirmed", "--samples", "50",
            "--format", "html", "--output", str(report),
        ], check=True, cwd=RADICE, capture_output=True)

        if not report.is_file():
            raise SystemExit("l'analisi non ha prodotto il report")

        destinazione.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(eseguibile), "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=%d" % DENSITA,
            "--window-size=%d,%d" % (LARGHEZZA, ALTEZZA),
            "--screenshot=%s" % destinazione,
            report.as_uri(),
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
