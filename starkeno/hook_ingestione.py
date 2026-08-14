"""L'hook di fine turno: legge il transcript e scrive le chiamate nuove.

**Esce 0 qualunque cosa accada.** E' l'invariante 4 applicata a casa d'altri: il costo
di un fallimento qui non lo paga StarkEno, lo paga il lavoro dell'utente, e questo e' un
progetto open source installato da sconosciuti. Nessuna eccezione risale, niente rumore
su stderr, nessuna dipendenza da processi accesi — si scrive dritto su SQLite.

Codex passa un JSON su stdin; per `Stop` contiene almeno `session_id`,
**`transcript_path`** (percorso assoluto del `.jsonl` della sessione), `cwd` e
`hook_event_name`. Il lettore riconosce sia il transcript a eventi di Codex sia il
formato storico di Claude Code.

Provato da capo a fondo col payload vero su un database appena creato: uscita 0, stderr
vuoto, 2,25 s, le chiamate della sessione scritte, e un secondo giro che non duplica.

Gli import pesanti stanno DENTRO le funzioni di proposito: un hook parte a ogni turno, e
il tempo di avvio lo paga l'utente.
"""
import json
import os
import sys

CHIAVE_TRANSCRIPT = "transcript_path"   # verificata dal task 7


def _percorso_database() -> str:
    """Il percorso del database, letto ADESSO e non al momento dell'import.

    `config.DB_PATH` si calcola quando il modulo viene importato. In produzione l'hook e'
    un processo a se' e le due cose coincidono; ma quando `ingerisci` viene chiamata da
    dentro un processo che ha gia' importato `starkeno.config` — la suite di test —
    leggere quella costante scriverebbe nel database VERO dell'utente, e nessun assert
    sul numero di righe scritte se ne accorgerebbe. Invariante 3.
    """
    from starkeno import config

    return os.environ.get("STARKENO_DB_PATH") or config.DB_PATH


def prepara_database(percorso: str, *, silenzioso: bool = False) -> None:
    """Porta lo schema a `head`. Usata dai test e dal primo avvio.

    L'URL si passa ESPLICITAMENTE ad Alembic invece di impostare `STARKENO_DB_PATH`:
    `migrations/env.py` ricade su `config.DB_PATH`, che e' gia' stato calcolato
    all'import, quindi la variabile d'ambiente impostata qui non lo cambierebbe e la
    migrazione finirebbe sul database di produzione.

    `silenzioso` serve al percorso dell'hook: Alembic scrive una riga INFO per ogni
    revisione applicata, e su stderr — dentro un hook e' rumore vietato.
    """
    from starkeno.migrazioni import upgrade_head

    upgrade_head(percorso, silenzioso=silenzioso)


def _assicura_database(percorso: str) -> None:
    """Crea cartella e schema se il database non c'e' ancora. **Il primo turno.**

    Senza, su un'installazione pulita non succede niente e non si vede niente: la
    cartella dati non esiste, la connessione fallisce, `main` assorbe l'eccezione — come
    deve — e l'hook non ingerisce MAI, per sempre e senza un errore. Verificato eseguendo
    l'hook con un percorso inesistente prima di questa funzione: uscita 0, stderr vuoto,
    database mai creato, zero righe. E' il fallimento silenzioso nella sua forma peggiore,
    perche' colpisce esattamente al primo avvio di chi installa il plugin.

    Solo quando il file NON c'e': far girare le migrazioni a ogni turno costerebbe circa
    un secondo di attesa all'utente, ogni volta.
    """
    from pathlib import Path

    file_database = Path(percorso)
    if file_database.exists():
        return
    file_database.parent.mkdir(parents=True, exist_ok=True)
    prepara_database(percorso, silenzioso=True)


def ingerisci(payload: dict) -> int:
    """Legge il transcript indicato dal payload e scrive le chiamate nuove.

    **Solleva** se qualcosa va storto: e' `main` che assorbe. Tenerle separate e' cio'
    che rende questa funzione testabile senza dover fingere lo stdin.
    """
    from pathlib import Path

    from starkeno import config, db, transcript

    percorso = payload.get(CHIAVE_TRANSCRIPT)
    if not percorso:
        return 0
    file_transcript = Path(percorso)
    if not file_transcript.exists():
        return 0

    with file_transcript.open(encoding="utf-8", errors="replace") as f:
        chiamate = transcript.leggi(f)
    if not chiamate:
        return 0

    percorso_db = _percorso_database()
    _assicura_database(percorso_db)
    # Il timeout CORTO, non quello del demone: qui aspettare e' il danno (invariante I7).
    fabbrica = db.make_session_factory(
        percorso_db, busy_timeout=config.HOOK_BUSY_TIMEOUT_SECONDS)
    sessione = fabbrica()
    try:
        return db.scrivi_chiamate(sessione, chiamate)
    finally:
        sessione.close()
        # `sessione.close()` restituisce la connessione al POOL, non la chiude: senza
        # `dispose()` l'hook lascia una connessione viva fino alla fine del processo, e
        # con essa il lock e i sidecar `-wal`/`-shm`. E' lo stesso pattern gia' usato da
        # `hook_inizio_sessione` e `report_conto`.
        fabbrica.kw["bind"].dispose()


def main() -> int:
    """Il punto d'ingresso. **Restituisce sempre 0.**"""
    try:
        grezzo = sys.stdin.read()
        payload = json.loads(grezzo) if grezzo.strip() else {}
        if not isinstance(payload, dict):
            return 0
        ingerisci(payload)
    except BaseException:
        # BaseException e non Exception: nemmeno un KeyboardInterrupt o un errore di
        # memoria deve trasformarsi in un turno perso per l'utente.
        pass
    return 0


if __name__ == "__main__":
    # **Lanciato per PERCORSO, non con `-m`.** L'hook gira nella cartella dell'utente, non
    # in questa: `python -m starkeno.hook_ingestione` da li' esce **1** con
    # `ModuleNotFoundError` e l'agente segnala un errore a ogni turno (misurato).
    #
    # Ma invocarlo per percorso senza questa riga e' PEGGIO, ed e' il motivo per cui la
    # riga esiste: `sys.path[0]` diventa `starkeno/`, non la radice, quindi
    # `from starkeno import config` non si risolve. Quegli import stanno dentro le
    # funzioni, cosi' l'errore non esce all'avvio — esce dentro `main`, che lo assorbe
    # come deve. Misurato l'08/08/2026 da una cartella estranea: **uscita 0, stderr vuoto,
    # database mai creato, zero righe.** Il plugin installato non raccoglie niente e non
    # lo dice: il fallimento silenzioso nella forma che questo progetto continua a pagare.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
