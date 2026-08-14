"""Avvia l'ingestione senza bloccare Codex, anche senza hook async nativi."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def avvia(payload: bytes) -> None:
    script = Path(__file__).resolve().with_name("hook_ingestione.py")
    opzioni: dict[str, object] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "cwd": os.getcwd(),
        "env": os.environ.copy(),
        "close_fds": True,
    }
    if os.name == "nt":
        opzioni["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        opzioni["start_new_session"] = True

    processo = subprocess.Popen([sys.executable, str(script)], **opzioni)
    if processo.stdin is None:
        return
    processo.stdin.write(payload)
    processo.stdin.close()
    processo.stdin = None


def main() -> int:
    try:
        avvia(sys.stdin.buffer.read())
    except BaseException:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
