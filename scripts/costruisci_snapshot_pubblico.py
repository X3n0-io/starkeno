"""Esporta una revisione Git senza storia privata, rete o inizializzazione remota."""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Sequence


REVISIONE_SICURA = re.compile(
    r"(?:HEAD|[0-9a-fA-F]{7,64}|[A-Za-z0-9][A-Za-z0-9._/-]*)\Z"
)


def costruisci_snapshot(destinazione: Path, *, revisione: str = "HEAD") -> Path:
    destinazione = Path(destinazione)
    if not REVISIONE_SICURA.fullmatch(revisione) or ".." in revisione:
        raise ValueError("revisione non valida")
    if destinazione.exists():
        if not destinazione.is_dir() or any(destinazione.iterdir()):
            raise ValueError("la destinazione non e vuota")
    else:
        destinazione.mkdir(parents=True)

    archivio = subprocess.run(
        ["git", "archive", "--format=tar", revisione],
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archivio), mode="r:") as tar:
        tar.extractall(destinazione, filter="data")
    return destinazione


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Crea uno snapshot pubblico dalla sola revisione Git",
    )
    parser.add_argument("destinazione", type=Path)
    parser.add_argument("--revision", default="HEAD")
    argomenti = parser.parse_args(argv)
    try:
        destinazione = costruisci_snapshot(
            argomenti.destinazione, revisione=argomenti.revision,
        )
    except ValueError as errore:
        parser.error(str(errore))
    print(destinazione)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
