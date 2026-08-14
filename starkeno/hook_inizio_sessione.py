"""Hook Codex ``SessionStart``: aggiunge il solo benvenuto utile della Fase 2.

L'hook e' deliberatamente in sola lettura: non crea il database, non applica migrazioni
e non porta nella conversazione i vecchi alert R1-R4. Qualunque errore viene assorbito,
perche' un problema di StarkEno non deve impedire l'avvio della sessione dell'utente.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


BENVENUTO = (
    "Nel prossimo messaggio utile mostra una sola breve riga di benvenuto: "
    "«StarkEno e' attivo e iniziera' a costruire il conto locale da questa sessione.» "
    "Non presentarla come un alert e non aggiungere altre spiegazioni."
)


def _percorso_database() -> str:
    """Risolve il percorso adesso: ``config.DB_PATH`` e' fissato all'import."""
    from starkeno.percorsi import percorso_database

    return os.environ.get("STARKENO_DB_PATH") or percorso_database()


def _numero_chiamate(percorso: str) -> int | None:
    """Restituisce ``None`` se non esiste ancora niente da leggere."""
    from starkeno import db

    database = Path(percorso)
    if not database.is_file():
        return None
    fabbrica = db.make_readonly_session_factory(str(database))
    sessione = fabbrica()
    try:
        return db.conta_chiamate(sessione)
    finally:
        sessione.close()
        fabbrica.kw["bind"].dispose()


def esegui(payload: dict) -> str | None:
    """Decide il contesto da aggiungere; non intercetta eventi diversi dallo startup."""
    if payload.get("hook_event_name") != "SessionStart":
        return None
    if payload.get("source") != "startup":
        return None

    chiamate = _numero_chiamate(_percorso_database())
    return BENVENUTO if chiamate in (None, 0) else None


def risposta_contesto(testo: str) -> str:
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": testo,
        }
    }, ensure_ascii=False)


def main() -> int:
    """Punto d'ingresso: sempre 0, sempre silenzioso in caso d'errore."""
    try:
        grezzo = sys.stdin.read()
        payload = json.loads(grezzo) if grezzo.strip() else {}
        if not isinstance(payload, dict):
            return 0
        testo = esegui(payload)
        if testo:
            print(risposta_contesto(testo))
    except BaseException:
        pass
    return 0


if __name__ == "__main__":
    # Codex lancia questo file dalla cartella del progetto dell'utente.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
