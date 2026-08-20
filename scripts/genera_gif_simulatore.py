"""Costruisce la GIF dei tre comandi che provano il simulatore.

Lo screenshot del report mostra il RISULTATO; questa mostra che ci si arriva in tre
comandi e in pochi secondi, che e' l'obiezione vera di chi legge un post e non sa se
valga la pena installare qualcosa.

I comandi e le righe di risposta sono quelli veri, copiati da un'esecuzione in un
virtualenv pulito: non e' una finzione grafica.

Disegnata con Pillow invece che registrando un terminale: e' deterministica, si
rigenera quando i comandi cambiano, e non porta dentro nessuna dipendenza nuova.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

RADICE = Path(__file__).resolve().parent.parent
DESTINAZIONE = RADICE / "docs" / "immagini" / "simulatore.gif"

LARGHEZZA, ALTEZZA = 1000, 300
MARGINE_X, MARGINE_Y, INTERLINEA = 26, 26, 25
FONDO, PROMPT, COMANDO, RISPOSTA, TENUE = "#101216", "#8e98a8", "#f3f4f6", "#a9b7d0", "#4a515c"

CARATTERI_PER_FOTOGRAMMA = 5
PAUSA_COMANDO_MS, PAUSA_RISPOSTA_MS, PAUSA_FINALE_MS = 40, 520, 2600

# Comandi e risposte VERI, da un'installazione pulita.
COPIONE = [
    (["python -m starkeno preflight esempio --output esempio.json"],
     ["Esempio scritto: esempio.json"]),
    (["python -m starkeno preflight draft --input esempio.json \\",
      "       --format yaml --output bozza.yaml"],
     ["Draft salvato: bozza.yaml"]),
    (["python -m starkeno preflight analyze --input bozza.yaml --confirmed \\",
      "       --samples 50 --format html --output report.html"],
     ["Analisi completata: report.html"]),
]


def _font(dimensione: int = 15) -> ImageFont.FreeTypeFont:
    for percorso in ("C:/Windows/Fonts/consola.ttf",
                     "/System/Library/Fonts/Menlo.ttc",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if Path(percorso).exists():
            return ImageFont.truetype(percorso, dimensione)
    return ImageFont.load_default()


def _disegna(righe: Sequence[tuple[str, str]], cursore: bool) -> Image.Image:
    tela = Image.new("RGB", (LARGHEZZA, ALTEZZA), FONDO)
    penna = ImageDraw.Draw(tela)
    font = _font()
    y = MARGINE_Y
    for testo, colore in righe[-13:]:
        penna.text((MARGINE_X, y), testo, font=font, fill=colore)
        y += INTERLINEA
    if cursore and righe:
        ultimo, _ = righe[-1]
        larghezza = penna.textlength(ultimo, font=font)
        penna.rectangle(
            [MARGINE_X + larghezza + 2, y - INTERLINEA + 2,
             MARGINE_X + larghezza + 10, y - INTERLINEA + 18],
            fill=TENUE,
        )
    return tela


def genera(destinazione: Path = DESTINAZIONE) -> Path:
    fotogrammi: list[Image.Image] = []
    durate: list[int] = []
    righe: list[tuple[str, str]] = []

    def aggiungi(immagine: Image.Image, durata: int) -> None:
        fotogrammi.append(immagine)
        durate.append(durata)

    for comando, risposta in COPIONE:
        for indice, riga in enumerate(comando):
            prefisso = "$ " if indice == 0 else ""
            righe.append((prefisso, PROMPT))
            for lunghezza in range(0, len(riga) + 1, CARATTERI_PER_FOTOGRAMMA):
                righe[-1] = (prefisso + riga[:lunghezza], COMANDO)
                aggiungi(_disegna(righe, cursore=True), PAUSA_COMANDO_MS)
            righe[-1] = (prefisso + riga, COMANDO)
        for riga in risposta:
            righe.append((riga, RISPOSTA))
            aggiungi(_disegna(righe, cursore=False), PAUSA_RISPOSTA_MS)
        righe.append(("", COMANDO))

    aggiungi(_disegna(righe, cursore=False), PAUSA_FINALE_MS)

    destinazione.parent.mkdir(parents=True, exist_ok=True)
    fotogrammi[0].save(
        destinazione, save_all=True, append_images=fotogrammi[1:],
        duration=durate, loop=0, optimize=True,
    )
    return destinazione


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DESTINAZIONE)
    argomenti = parser.parse_args(argv)
    scritta = genera(argomenti.output)
    print("%s (%d KB)" % (scritta, scritta.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
