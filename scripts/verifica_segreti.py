"""Scansione locale redatta: segnala il tipo di segreto, mai il suo valore."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class RilievoSegreto:
    percorso: Path
    tipo: str


PATTERN = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("private_key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    )),
    ("bearer_token", re.compile(
        r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}", re.IGNORECASE
    )),
)


def scansiona(paths: Iterable[Path]) -> tuple[RilievoSegreto, ...]:
    rilievi = []
    for path in paths:
        percorso = Path(path)
        contenuto = percorso.read_text(encoding="utf-8", errors="ignore")
        for tipo, pattern in PATTERN:
            if pattern.search(contenuto):
                rilievi.append(RilievoSegreto(percorso, tipo))
    return tuple(rilievi)


def _file_tracciati() -> tuple[Path, ...]:
    risultato = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True,
    )
    return tuple(
        Path(os.fsdecode(voce))
        for voce in risultato.stdout.split(b"\0")
        if voce
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cerca pattern di segreti senza stamparne il valore",
    )
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--tracked", action="store_true")
    argomenti = parser.parse_args(argv)
    paths = list(argomenti.paths)
    if argomenti.tracked:
        paths.extend(_file_tracciati())
    if not paths:
        parser.error("indica almeno un file o usa --tracked")

    rilievi = scansiona(paths)
    for rilievo in rilievi:
        print(f"{rilievo.percorso}:{rilievo.tipo}")
    return 1 if rilievi else 0


if __name__ == "__main__":
    raise SystemExit(main())
