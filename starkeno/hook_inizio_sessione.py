"""Hook Codex ``SessionStart``: aggiunge il solo benvenuto utile della Fase 2.

L'hook e' deliberatamente in sola lettura: non crea il database, non applica migrazioni
e non porta nella conversazione i vecchi alert R1-R4. Qualunque errore viene assorbito,
perche' un problema di StarkEno non deve impedire l'avvio della sessione dell'utente.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


BENVENUTO = (
    "Nel prossimo messaggio utile mostra una sola breve riga di benvenuto: "
    "«StarkEno e' attivo e iniziera' a costruire il conto locale da questa sessione.» "
    "Non presentarla come un alert e non aggiungere altre spiegazioni."
)


FATTO = (
    "Nel prossimo messaggio utile mostra una sola breve riga: "
    "«StarkEno: negli ultimi 7 giorni il %d%% della spesa e' stata rilettura di "
    "contesto.» Non presentarla come un alert, non aggiungere spiegazioni e non "
    "ripeterla nei messaggi successivi."
)

# Quanto silenzio serve perche' una sessione conti come «nuova». Ragionata, non misurata,
# come tutte le soglie di questo progetto: e' una pausa di lavoro, non una regola.
# Serve a non ripetere la riga a ogni riavvio dentro la stessa giornata, e si valuta
# SENZA stato — l'ultima riga raccolta e' abbastanza vecchia — cosi' l'hook resta in sola
# lettura. Il limite noto: riavviare senza aver completato un turno non scrive righe, e
# la riga puo' uscire due volte. Costa poco, e la cura sarebbe scrivere stato.
PAUSA_MINIMA = timedelta(hours=8)

# Sotto questa soglia una singola sessione pesante domina la percentuale: sarebbe vera
# in aritmetica e falsa su come lavori.
CHIAMATE_MINIME = 50


def _adesso() -> datetime:
    """L'orologio in un posto solo, cosi' i test lo sostituiscono senza fingere il fuso."""
    return datetime.now(timezone.utc)


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

    percorso = _percorso_database()
    chiamate = _numero_chiamate(percorso)
    if chiamate in (None, 0):
        return BENVENUTO
    return _fatto_misurato(percorso, _adesso())


def _fatto_misurato(percorso: str, adesso: datetime) -> str | None:
    """Una riga vera sugli ultimi 7 giorni, oppure `None` se non c'e' niente di vero.

    **Il numero viene da `conto.calcola_conto`**, la stessa autorita' che produce il
    conto, mai da una seconda query scritta qui. Questo progetto ha gia' pagato due volte
    per due implementazioni della stessa regola che divergono, e una riga all'avvio che
    contraddice il report sarebbe peggio del silenzio.

    Tace in tre casi, tutti deliberati: se non e' passata abbastanza pausa dall'ultima
    chiamata raccolta, se la finestra ha troppi pochi dati per dire qualcosa di vero, e
    se il totale pesato e' nullo. Non tace su un errore perche' non li intercetta: li
    assorbe `main`, come per ogni altro ramo di questo hook.
    """
    from starkeno import db
    from starkeno.config import MAX_PLAUSIBLE_TOKENS, TOKEN_COST_WEIGHTS
    from starkeno.conto import calcola_conto
    # Importato qui e non in testa: un hook parte a ogni sessione e il tempo di avvio
    # lo paga l'utente. `FusoLocaleSistema` e' lo stesso fuso con cui il report divide
    # i giorni, e usarne un altro farebbe divergere i due numeri sul confine.
    from starkeno.report_conto import FusoLocaleSistema

    fabbrica = db.make_readonly_session_factory(percorso)
    sessione = fabbrica()
    try:
        azioni = db.get_azioni_conto(sessione)
    finally:
        sessione.close()
        fabbrica.kw["bind"].dispose()

    if not azioni:
        return None
    if adesso - max(azione.timestamp for azione in azioni) < PAUSA_MINIMA:
        return None

    conto = calcola_conto(
        azioni, fuso=FusoLocaleSistema(), now=adesso,
        weights=TOKEN_COST_WEIGHTS, max_plausible=MAX_PLAUSIBLE_TOKENS,
    )
    chiamate = sum(giorno.chiamate for giorno in conto.ritmo)
    totale = sum(giorno.totale_pesato for giorno in conto.ritmo)
    riletture = sum(giorno.riletture_pesate for giorno in conto.ritmo)
    if chiamate < CHIAMATE_MINIME or totale <= 0:
        return None
    return FATTO % round(100 * riletture / totale)


def risposta_contesto(testo: str) -> str:
    """Il contesto come JSON, in solo ASCII.

    `ensure_ascii` resta il DEFAULT. Con `False` le virgolette basse finivano grezze nel
    JSON: se lo stdout dell'hook non sa rappresentarle, `print` solleva, `main` assorbe
    come deve, e si perde TUTTO il contesto senza un segnale. Le due rese sono
    equivalenti per qualunque parser JSON, quindi l'escape non costa niente.
    """
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": testo,
        }
    })


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
