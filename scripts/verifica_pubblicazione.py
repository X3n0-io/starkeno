"""Controlla privacy e segreti dello snapshot senza esporre i valori trovati."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# Eseguito come file, sys.path contiene scripts/ e non la radice del repository, quindi
# l'import fra script risolverebbe soltanto con `python -m scripts.verifica_pubblicazione`.
RADICE = str(Path(__file__).resolve().parent.parent)
if RADICE not in sys.path:
    sys.path.insert(0, RADICE)

from scripts.verifica_segreti import scansiona  # noqa: E402


DIRECTORY_IGNORATE = {
    ".git", ".pytest_cache", ".venv", "__pycache__", "build", "dist",
}


@dataclass(frozen=True)
class RilievoPubblico:
    percorso: Path
    tipo: str


def _sembra_testo(path: Path) -> bool:
    try:
        contenuto = path.read_bytes()
    except OSError:
        return False
    if b"\0" in contenuto:
        return False
    try:
        contenuto.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def tracked_text_files(root: Path) -> tuple[Path, ...]:
    """Elenca testo versionato; senza Git usa l'albero esportato dello snapshot."""
    root = Path(root).resolve()
    if (root / ".git").exists():
        risultato = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        candidati = (
            root / Path(os.fsdecode(nome))
            for nome in risultato.stdout.split(b"\0")
            if nome
        )
    else:
        candidati = (
            path for path in root.rglob("*")
            if path.is_file()
            and not any(parte in DIRECTORY_IGNORATE for parte in path.relative_to(root).parts)
        )
    return tuple(sorted(
        (path for path in candidati if _sembra_testo(path)),
        key=lambda path: path.as_posix(),
    ))


_WINDOWS_HOME = re.compile(
    r"(?:[A-Za-z]:[\\/]+|/[A-Za-z]/)Users[\\/]+(?!<)[^\\/\s\"'`]+",
    re.IGNORECASE,
)
_MAC_HOME = re.compile(
    "/" + "Users" + r"/(?!<)[^/\s\"'`]+",
    re.IGNORECASE,
)
_LINUX_HOME = re.compile(
    "/" + "home" + r"/(?!<)[^/\s\"'`]+",
    re.IGNORECASE,
)
_CONTESTO_PERSONALE = re.compile(
    r"(?:vault\s+(?:Obsidian|personale)|"
    r"Contesto\s+(?:di\s+business|di\s+prodotto)\s+nel\s+vault)",
    re.IGNORECASE,
)
_NOME_AUTORE = "Simo" + "ne"
_DATI_AUTORE = re.compile(
    r"(?:transcript(?:\s+di)?\s+|l'utente\s+)" + re.escape(_NOME_AUTORE),
    re.IGNORECASE,
)


def scansiona_pubblico(paths: Iterable[Path]) -> tuple[RilievoPubblico, ...]:
    percorsi = tuple(Path(path) for path in paths)
    rilievi = [
        RilievoPubblico(rilievo.percorso, "segreto_" + rilievo.tipo)
        for rilievo in scansiona(percorsi)
    ]
    pattern = (
        ("windows_home_letterale", _WINDOWS_HOME),
        ("macos_home_letterale", _MAC_HOME),
        ("linux_home_letterale", _LINUX_HOME),
        ("contesto_personale", _CONTESTO_PERSONALE),
        ("dati_autore", _DATI_AUTORE),
    )
    for path in percorsi:
        contenuto = path.read_text(encoding="utf-8")
        for tipo, espressione in pattern:
            if espressione.search(contenuto):
                rilievi.append(RilievoPubblico(path, tipo))
    return tuple(rilievi)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verifica che i file pubblici non contengano dati privati",
    )
    parser.add_argument("paths", nargs="*", type=Path)
    argomenti = parser.parse_args(argv)
    paths = tuple(argomenti.paths) or tracked_text_files(Path.cwd())
    rilievi = scansiona_pubblico(paths)
    for rilievo in rilievi:
        print(f"{rilievo.percorso}:{rilievo.tipo}")
    return 1 if rilievi else 0


if __name__ == "__main__":
    raise SystemExit(main())
