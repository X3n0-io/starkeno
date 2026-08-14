"""Il processo periodico: valuta le regole e riconcilia il risultato con gli alert.

**Non importa SQLAlchemy.** L'invariante vale anche per il codice nuovo: tutto passa da
`db.py`. E non contiene nessuna soglia: le riceve da uno snapshot di `config`.

Il ciclo di vita di un alert e' il punto in cui questo sistema puo' fallire nei modi
peggiori, e sono tutti silenziosi. I due che governano tutto il resto:

**Il silenzio non e' guarigione.** Un agente fermo non produce violazioni per definizione.
Chiudere dopo N minuti senza violazioni farebbe lampeggiare per sempre un agente cron
rotto — chiuso a ogni pausa, riaperto a ogni esecuzione. La chiusura richiede una PROVA
POSITIVA: azioni pulite dopo `last_seen`, oppure inattivita' cosi' lunga da essere
archiviazione e non guarigione.

**`last_seen` e' tempo AZIONE, non tempo del giro.** E' la definizione che fa funzionare
tutto: quando il comportamento cattivo cessa, `last_seen` smette di avanzare e la
finestra pulita dopo di esso puo' crescere.
"""
import json
import logging
import socket
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from starkeno import db
from starkeno.config import DB_PATH, snapshot
from starkeno.db import make_session_factory
from starkeno.schema_version import SchemaVersionError, check_or_die
from starkeno.rules import (
    NON_VALUTABILE,
    OK,
    VIOLAZIONE,
    CandidatoSpesa,
    classifica_modelli,
    valuta_r1,
    valuta_r2,
    valuta_r3,
    valuta_r4,
)

logger = logging.getLogger("starkeno.supervisor")

AGENTE_SISTEMA = "__sistema__"
REGOLE = ("loop", "expensive_model", "spend_anomaly", "steady_waste")


@dataclass
class RoundResult:
    agenti: list = field(default_factory=list)
    rules_failed: int = 0
    aperti: int = 0
    risolti: int = 0
    ultimo_errore: str | None = None


# =============================================================================
# I quattro valutatori
# =============================================================================
#
# Ciascuno riceve un contesto e un inizio-finestra `da`, e restituisce un Esito.
#
# **`da=None` significa "la finestra PROPRIA della regola".** Ogni regola ha la sua:
# EXPENSIVE_WINDOW_HOURS per R2, HEAVY_WINDOW_HOURS per R4, SPEND_ANOMALY_WINDOW_HOURS
# per R3, e per R1 le finestre corte che i rilevatori applicano da soli rispetto a `now`.
# NON si usa SUPERVISOR_ACTIVE_AGENT_HOURS: quella decide QUALI agenti valutare, non su
# quanto passato. Confonderle rende le tre costanti di finestra morte — vive solo nel
# testo dei messaggi — e applica soglie giornaliere a due giorni di dati, rendendo R2 e
# R4 il doppio piu' sensibili del progettato. E' anche la ragione per cui esiste
# l'invariante I3: la finestra degli attivi deve COPRIRE quelle delle regole, il che
# presuppone che siano cose diverse.
#
# Il RECUPERO passa `da = last_seen`: la "finestra ristretta" di cui parla il design non
# e' un meccanismo separato, e' la stessa valutazione su un `da` diverso.


def _finestra(ctx, da, ore):
    if da is not None:
        return da
    return ctx.now - timedelta(hours=ore)


def _valuta_loop(ctx, da):
    # R1 e' l'unica a non avere una finestra propria in ore: i suoi due rilevatori
    # applicano LOOP_WINDOW_MINUTES e LOOP_CYCLE_WINDOW_MINUTES rispetto a `now`. Qui
    # serve solo abbastanza storia per LOOP_MIN_HISTORY, e la finestra degli attivi va
    # bene perche' e' lo stesso orizzonte su cui quella soglia e' definita (C9).
    da = _finestra(ctx, da, ctx.config.SUPERVISOR_ACTIVE_AGENT_HOURS)
    azioni = db.get_actions_since(ctx.session, ctx.agente, since=da, until=ctx.now,
                                  weights=ctx.config.TOKEN_COST_WEIGHTS,
                                  max_plausible=ctx.config.MAX_PLAUSIBLE_TOKENS)
    return valuta_r1(azioni, now=ctx.now, config=ctx.config)


def _classificazione(ctx, da):
    modelli = db.get_distinct_models(ctx.session, ctx.agente, since=da, until=ctx.now)
    return classifica_modelli(modelli, ctx.config.MODEL_TIERS)


def _stats(ctx, da, classificazione):
    return db.get_window_stats(
        ctx.session, ctx.agente, since=da, until=ctx.now,
        frontier_raw_names=classificazione.frontier,
        weights=ctx.config.TOKEN_COST_WEIGHTS,
        max_plausible=ctx.config.MAX_PLAUSIBLE_TOKENS,
        soglia_banale=ctx.config.EXPENSIVE_TRIVIAL_TOKENS,
        soglia_pesante=ctx.config.HEAVY_TOKENS,
    )


def _valuta_expensive(ctx, da):
    da = _finestra(ctx, da, ctx.config.EXPENSIVE_WINDOW_HOURS)
    cls = _classificazione(ctx, da)
    return valuta_r2(_stats(ctx, da, cls), classificazione=cls, config=ctx.config)


def _valuta_steady(ctx, da):
    da = _finestra(ctx, da, ctx.config.HEAVY_WINDOW_HOURS)
    cls = _classificazione(ctx, da)
    return valuta_r4(_stats(ctx, da, cls), classificazione=cls, config=ctx.config)


def _valuta_spend(ctx, da):
    """R3 e' l'unica regola con uno stato persistente: il watermark e le anomalie note.

    Sulla finestra ristretta (recupero) il watermark non si usa: la domanda e' "e'
    successo qualcosa di nuovo DOPO `last_seen`", e le anomalie vecchie non si portano
    dietro — una riga passata e' immutabile e non guarisce mai, quindi contarla di nuovo
    impedirebbe per sempre la chiusura.
    """
    pesi = ctx.config.TOKEN_COST_WEIGHTS
    tetto = ctx.config.MAX_PLAUSIBLE_TOKENS

    if ctx.ristretta:
        nuove = db.get_actions_since(
            ctx.session, ctx.agente,
            since=_finestra(ctx, da, ctx.config.SPEND_ANOMALY_WINDOW_HOURS),
            until=ctx.now, weights=pesi, max_plausible=tetto)
        note = ()
    else:
        watermark = db.get_watermark(ctx.session, ctx.agente)
        if watermark is None:
            # Primo avvio: si parte dall'id piu' alto, NON da zero. Con zero il primo
            # giro rivaluterebbe tutto lo storico e aprirebbe oggi alert su anomalie di
            # mesi fa.
            watermark = db.get_max_action_id(ctx.session, ctx.agente)
            db.set_watermark(ctx.session, ctx.agente, watermark)
        nuove = db.get_actions_after_id(ctx.session, ctx.agente, watermark, until=ctx.now,
                                        weights=pesi, max_plausible=tetto)
        note = ctx.anomalie_note

    candidati = [
        CandidatoSpesa(
            action_id=azione.id,
            timestamp=azione.timestamp,
            effective=azione.effective,
            baseline=db.get_spend_baseline(
                ctx.session, ctx.agente, before_id=azione.id,
                limit=ctx.config.SPEND_HISTORY_WINDOW, weights=pesi, max_plausible=tetto),
        )
        for azione in nuove
    ]
    esito = valuta_r3(candidati, anomalie_note=note, now=ctx.now, config=ctx.config)

    # Il watermark NON si scrive qui. Si annota sul contesto e lo scrive `run_once`
    # DOPO che la riconciliazione e' riuscita.
    #
    # Scriverlo qui — cioe' a valutazione finita ma prima di aver salvato l'alert — era
    # un difetto silenzioso: se la riconciliazione falliva, l'anomalia trovata non
    # veniva registrata da nessuna parte e il watermark era gia' avanzato, quindi quelle
    # azioni non sarebbero state riesaminate MAI PIU' da nessuno. Verificato: watermark
    # da 60 a 61 su un giro fallito, e l'anomalia piu' cara della giornata persa.
    if not ctx.ristretta and nuove:
        ctx.watermark_da_scrivere = max(a.id for a in nuove)
    return esito


VALUTATORI = {
    "loop": _valuta_loop,
    "expensive_model": _valuta_expensive,
    "spend_anomaly": _valuta_spend,
    "steady_waste": _valuta_steady,
}


@dataclass
class _Contesto:
    session: object
    agente: str
    now: object
    config: object
    anomalie_note: tuple = ()
    ristretta: bool = False
    # Annotato da `_valuta_spend`, scritto da `run_once` solo dopo una riconciliazione
    # riuscita: un giro fallito deve far rivedere le stesse azioni al giro successivo.
    watermark_da_scrivere: int | None = None


# =============================================================================
# Riconciliazione
# =============================================================================

def _promuovibile(alert, esito, ctx):
    """Entrambe le condizioni, piu' quella specifica di R3.

    La doppia condizione esiste perche' il portatile si sospende: senza il conteggio dei
    giri, un candidate creato prima di una sospensione verrebbe promosso al primo giro
    dopo il risveglio, avendo osservato un solo giro.
    """
    abbastanza_tempo = (ctx.now - alert.first_seen) >= timedelta(
        minutes=ctx.config.PROMOTE_MIN_MINUTES)
    abbastanza_giri = alert.observed_rounds >= ctx.config.PROMOTE_MIN_ROUNDS
    if not (abbastanza_tempo and abbastanza_giri):
        return False

    if alert.rule == "spend_anomaly":
        # Un'anomalia isolata e' un fatto storico su una riga immutabile: non puo'
        # auto-risolversi, quindi la difesa anti-raffica non la coprirebbe e una singola
        # analisi one-shot diventerebbe un alert permanente.
        quante = esito.evidenza.get("anomalie_nella_finestra", 0)
        return quante >= ctx.config.SPEND_PROMOTE_MIN_ANOMALIES

    return True


def _riconcilia(ctx, regola, esito, risultato):
    session, agente = ctx.session, ctx.agente

    if esito.stato == NON_VALUTABILE:
        db.set_rule_status(session, agente, regola, state="non_valutabile",
                           reason=esito.motivo, now=ctx.now)
        # CONGELA. Non promuovere, non risolvere, non cancellare, non toccare last_seen:
        # se l'astensione fosse letta come non-violazione un alert si chiuderebbe mentre
        # il problema continua senza essere misurato; se fosse letta come violazione,
        # last_seen avanzerebbe a ogni giro e l'alert non si chiuderebbe mai.
        return

    if esito.stato == VIOLAZIONE:
        db.set_rule_status(session, agente, regola, state="violating",
                           reason=None, now=ctx.now)
        evidenza = dict(esito.evidenza)
        correlato = _alert_loop_correlato(ctx, regola)
        if correlato is not None:
            evidenza["related_rule"] = correlato
        alert = db.upsert_alert(
            session, project=agente, rule=regola, detail=esito.motivo or regola,
            evidence=evidenza, last_seen=esito.ultimo_contributo or ctx.now, now=ctx.now,
        )
        if alert.status == "candidate" and _promuovibile(alert, esito, ctx):
            db.promote_alert(session, alert, now=ctx.now)
            risultato.aperti += 1
        return

    # esito OK
    db.set_rule_status(session, agente, regola, state="ok", reason=None, now=ctx.now)
    alert = db.get_live_alert(session, agente, regola)
    if alert is None:
        return

    if alert.status == "candidate":
        db.delete_alert(session, alert)      # raffica auto-risolta: nessuna traccia
        return

    _prova_recupero(ctx, regola, alert, risultato)


def _prova_recupero(ctx, regola, alert, risultato):
    """Chiusura con prova positiva: azioni pulite dopo `last_seen`, e la regola
    rivalutata su quella sola finestra che dice OK.

    **Cosa fa davvero la finestra ristretta, che non e' quello che sembra.**

    `last_seen` e' per definizione l'azione piu' recente che ha CONTRIBUITO alla
    violazione. Quindi, per costruzione, nella finestra dopo `last_seen` non c'e' nessuna
    azione che abbia contribuito: la rivalutazione ristretta non puo' quasi mai
    restituire VIOLAZIONE. Per R4 e' addirittura impossibile — conteggi e somme sono
    monotoni, e un suffisso non puo' superare una soglia che il tutto non superava.

    Il suo lavoro vero e' l'ASTENSIONE. Se le azioni dopo `last_seen` non bastano a
    giudicare — troppa poca storia per R1, nessun dettaglio, baseline corta per R3 —
    l'esito e' NON_VALUTABILE e l'alert NON si chiude. E' cio' che impedisce di
    dichiarare guarito un agente sulla base di prove che non ci sono, ed e' la ragione
    per cui l'invariante I4 ha margine zero: sotto RESOLVE_MIN_HEALTHY_ACTIONS la
    finestra sarebbe troppo corta perche' una regola possa dire qualcosa.

    Conseguenza da conoscere: un alert R2 o R4 resta aperto finche' le azioni che l'hanno
    causato non escono dalla loro finestra di 24 ore, anche se l'agente si e' corretto
    subito. Non e' un difetto — quella spesa e' davvero avvenuta nelle ultime 24 ore — ma
    e' una latenza di chiusura di un giorno.
    """
    pulite = db.conta_azioni_dopo(ctx.session, ctx.agente, alert.last_seen, until=ctx.now)
    if pulite < ctx.config.RESOLVE_MIN_HEALTHY_ACTIONS:
        return

    ristretto = _Contesto(ctx.session, ctx.agente, ctx.now, ctx.config, ristretta=True)
    esito = VALUTATORI[regola](ristretto, alert.last_seen)
    if esito.stato == OK:
        db.resolve_alert(ctx.session, alert, resolution="recovery", now=ctx.now)
        risultato.risolti += 1


def _alert_loop_correlato(ctx, regola):
    """Un incidente, non tre righe.

    Un agente bloccato su modello frontier fa scattare piu' regole insieme: una causa
    sola e una correzione sola. La soppressione vera e' rimandata; qui si registra solo
    la parentela, e la dashboard raggruppa per agente.
    """
    if regola == "loop":
        return None
    loop = db.get_live_alert(ctx.session, ctx.agente, "loop")
    return "loop" if loop is not None else None


def _archivia_se_stantio(ctx, risultato):
    """Non e' guarigione, e' archiviazione: `resolution='stale'`, marcato diversamente.

    Saltato per un giro dopo un'interruzione del processo piu' lunga di
    3 x SUPERVISOR_INTERVAL_SECONDS, altrimenti dieci giorni di vacanza archiviano in
    blocco ogni alert aperto.
    """
    ultima = db.ultima_azione(ctx.session, ctx.agente, until=ctx.now)
    if ultima is None:
        return
    if (ctx.now - ultima) < timedelta(days=ctx.config.RESOLVE_STALE_DAYS):
        return
    for alert in db.get_live_alerts_for_agent(ctx.session, ctx.agente):
        db.resolve_alert(ctx.session, alert, resolution="stale", now=ctx.now)
        risultato.risolti += 1


def _riconcilia_qualita_dati(session, attivi, now, config, risultato):
    """Il ciclo di vita dell'alert `data_quality`, che non appartiene a nessuna regola.

    Serve una riconciliazione sua perche' `data_quality` non e' fra le REGOLE valutate:
    senza, l'alert veniva aperto e non lo toccava piu' nessuno: restava li' per sempre,
    anche dopo che il chiamante aveva corretto il proprio `project`. Un alert perpetuo
    su un problema risolto insegna a ignorare la dashboard, che e' il fallimento peggiore
    di tutti.

    Si apre come `open` e non come `candidate`: la fase di osservazione esiste per
    lasciare che una raffica si risolva da sola prima di disturbare, e qui non c'e'
    nessuna raffica — il conteggio degli agenti distinti e' un fatto. Tenerlo in
    osservazione per quindici minuti ritarderebbe soltanto l'unica segnalazione che
    spiega perche' tutte le altre sono sparite.
    """
    esistente = db.get_live_alert(session, AGENTE_SISTEMA, "data_quality")

    if len(attivi) <= config.MAX_TRACKED_AGENTS:
        if esistente is not None:
            db.resolve_alert(session, esistente, resolution="recovery", now=now)
            risultato.risolti += 1
        return

    # Quasi certamente un chiamante mette un id di sessione dentro `project`:
    # migliaia di nomi con poche azioni ciascuno, tutti sotto ogni soglia di storia. Il
    # supervisore sarebbe massimamente occupato e completamente cieco.
    alert = db.upsert_alert(
        session, project=AGENTE_SISTEMA, rule="data_quality",
        detail="%d agenti distinti nelle ultime %d ore, oltre il limite di %d: "
               "probabile id di sessione dentro project. La valutazione delle regole "
               "e' sospesa finche' non rientra."
               % (len(attivi), config.SUPERVISOR_ACTIVE_AGENT_HOURS,
                  config.MAX_TRACKED_AGENTS),
        evidence={"agenti_distinti": len(attivi), "limite": config.MAX_TRACKED_AGENTS},
        last_seen=now, now=now,
    )
    if alert.status == "candidate":
        db.promote_alert(session, alert, now=now)
        risultato.aperti += 1


def _buco_di_heartbeat(session, now, config) -> bool:
    battito = db.get_heartbeat(session)
    if battito is None:
        return True     # primo avvio in assoluto: non si archivia niente
    limite = timedelta(seconds=3 * config.SUPERVISOR_INTERVAL_SECONDS)
    return (now - battito.last_run_at) > limite


# =============================================================================
# Un giro
# =============================================================================

def run_once(session, now, config) -> RoundResult:
    """Un giro completo. `now` e' un parametro: nessun modulo qui legge l'orologio.

    Ogni regola e' isolata nel proprio try/except, e l'eccezione scrive `state='error'`
    in `rule_status`. Senza, una regola rotta e' indistinguibile da una che dice OK — il
    fallimento peggiore di questo sistema.
    """
    risultato = RoundResult()
    salta_stantio = _buco_di_heartbeat(session, now, config)

    # `until=now` non e' pignoleria: senza, un giro vede anche le azioni con timestamp
    # SUCCESSIVO a `now`. In produzione non esistono — `timestamp` e' l'ora di ingestione
    # assegnata da db.py — ma il metodo di verifica prescritto e' proprio chiamare
    # `run_once` piu' volte facendo avanzare `now` a mano, e senza il limite superiore
    # ogni giro vedrebbe tutto il futuro dello scenario. Misurato: `first_seen` finiva
    # DOPO `now`, quindi `now - first_seen` era negativo e nessun alert veniva mai
    # promosso.
    attivi = db.get_active_projects(
        session, since=now - timedelta(hours=config.SUPERVISOR_ACTIVE_AGENT_HOURS),
        until=now)

    _riconcilia_qualita_dati(session, attivi, now, config, risultato)
    if len(attivi) > config.MAX_TRACKED_AGENTS:
        return risultato

    # Unione con gli agenti che hanno un alert non risolto: RESOLVE_STALE_DAYS e' molto
    # oltre SUPERVISOR_ACTIVE_AGENT_HOURS, quindi un agente fermo esce dagli attivi PRIMA
    # di poter essere archiviato. Senza questa clausola i suoi alert resterebbero aperti
    # per sempre. E' l'invariante I5 di config.py.
    # Le parentesi non sono ornamentali: in Python `-` lega piu' stretto di `|`, quindi
    # `set(a) | set(b) - {X}` sottrae X da UN SOLO operando. Oggi sarebbe innocuo perche'
    # `__sistema__` non ha azioni proprie, ma basta un chiamante che usi quel nome per
    # far girare quattro regole su un agente che non esiste.
    da_valutare = sorted((set(attivi) | set(db.progetti_con_alert_vivi(session)))
                         - {AGENTE_SISTEMA})
    risultato.agenti = da_valutare

    for agente in da_valutare:
        note = _anomalie_note(session, agente)
        ctx = _Contesto(session, agente, now, config, anomalie_note=note)
        for regola in REGOLE:
            try:
                ctx.watermark_da_scrivere = None
                esito = VALUTATORI[regola](ctx, None)   # None = finestra propria della regola
                _riconcilia(ctx, regola, esito, risultato)
                # Solo ora: l'esito e' stato salvato, quindi le azioni esaminate possono
                # essere dichiarate tali. Se qualcosa sopra solleva, il watermark resta
                # dov'era e al giro dopo si riparte da li'.
                if ctx.watermark_da_scrivere is not None:
                    db.set_watermark(session, agente, ctx.watermark_da_scrivere)
            except Exception as errore:            # noqa: BLE001 — deliberato
                session.rollback()
                risultato.rules_failed += 1
                risultato.ultimo_errore = "%s/%s: %s" % (agente, regola, errore)
                logger.exception("regola %s fallita per %s", regola, agente)
                db.set_rule_status(session, agente, regola, state="error",
                                   reason="%s: %s" % (type(errore).__name__, errore),
                                   now=now)
        if not salta_stantio:
            _archivia_se_stantio(ctx, risultato)

    return risultato


def _anomalie_note(session, agente) -> tuple:
    """Le anomalie gia' registrate nell'alert di R3.

    Servono perche' la promozione richiede piu' anomalie in una finestra di ore, mentre
    il watermark fa si' che ogni giro veda solo le azioni nuove: senza memoria, la prima
    anomalia sparirebbe prima che arrivi la seconda.
    """
    alert = db.get_live_alert(session, agente, "spend_anomaly")
    if alert is None or not alert.evidence:
        return ()
    try:
        return tuple(json.loads(alert.evidence).get("anomalie", ()))
    except (ValueError, TypeError):
        return ()


# =============================================================================
# Il processo
# =============================================================================

PORTA_GUARDIA = 47_699


def guard_istanza_singola(porta: int = PORTA_GUARDIA):
    """Impedisce a un secondo supervisore di partire. Restituisce il socket da TENERE VIVO.

    **Niente `SO_REUSEADDR`, ed e' il punto piu' importante di questa funzione.** Su
    Windows quell'opzione ha semantica OPPOSTA a Unix: permette il rebind di un indirizzo
    gia' occupato. Misurato eseguendo:

        bind semplice            -> OSError(10048)   il guard funziona
        bind con SO_REUSEADDR    -> riesce           il guard non guarda niente

    E' l'idioma riflesso di chiunque scriva un server, quindi qualcuno lo riaggiungera'
    "per sicurezza". Non farlo: due supervisori insieme raddoppiano `episodes` e, con
    `config.py` diversi, aprono e chiudono lo stesso alert a vicenda ogni sessanta
    secondi — il lampeggio che il ciclo di vita esiste per impedire, reso silenzioso
    dalla difesa upsert.

    Un socket e non un lock file con dentro un pid: il sistema operativo rilascia la
    porta alla morte del processo, mentre un file resta li' dopo un kill e blocca ogni
    riavvio successivo.
    """
    presa = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        presa.bind(("127.0.0.1", porta))
        presa.listen(1)
    except BaseException:
        presa.close()
        raise
    return presa


def _configura_logging(percorso_db: str):
    """File con rotazione accanto al database, mai `print`.

    Un processo periodico su Windows non ha uno stderr che qualcuno legga mai: senza un
    file, ogni diagnostica di questo modulo e' scritta e persa.
    """
    percorso = Path(percorso_db).resolve().parent / "supervisor.log"
    gestore = RotatingFileHandler(percorso, maxBytes=2_000_000, backupCount=3,
                                  encoding="utf-8")
    gestore.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(gestore)
    logger.setLevel(logging.INFO)
    return percorso


def run_forever(config, *, session_factory, sleep=time.sleep, max_iterations=None,
                now_fn=None):
    """Il loop periodico.

    **Il `try` sta DENTRO il `while`**, non fuori. Con il `try` esterno — che e' la forma
    piu' naturale da scrivere — la prima eccezione fa uscire dal loop e il supervisore
    muore in silenzio: e un supervisore morto mostra la stessa identica schermata di una
    flotta sana, cioe' zero alert.

    L'heartbeat si scrive a fine di OGNI giro, **dentro** il try/except, cosi' che si
    aggiorni anche quando il giro fallisce. `sleep` e `max_iterations` sono iniettabili
    perche' altrimenti il loop non e' verificabile.

    Una sessione NUOVA per giro: tenendone una sola aperta per sempre, la cache di
    identita' di SQLAlchemy servirebbe righe stantie e il supervisore leggerebbe alert
    che nel frattempo l'utente ha marcato come falsi positivi dalla dashboard.
    """
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    giri = 0

    while max_iterations is None or giri < max_iterations:
        giri += 1
        session = session_factory()
        inizio = time.monotonic()
        risultato = RoundResult()
        errore = None
        try:
            adesso = now_fn()
            risultato = run_once(session, now=adesso, config=config)
        except Exception as eccezione:            # noqa: BLE001 — deliberato
            session.rollback()
            errore = "%s: %s" % (type(eccezione).__name__, eccezione)
            logger.exception("giro fallito")
            adesso = now_fn()
        finally:
            try:
                db.write_heartbeat(
                    session, now=adesso,
                    duration_ms=int((time.monotonic() - inizio) * 1000),
                    agents_evaluated=len(risultato.agenti),
                    rules_failed=risultato.rules_failed,
                    last_error=errore or risultato.ultimo_errore,
                )
            except Exception:                     # noqa: BLE001
                # Se nemmeno l'heartbeat si scrive, il database e' irraggiungibile: si
                # logga e si riprova al giro dopo. Uscire dal loop qui rifarebbe
                # esattamente il danno che tutta questa struttura evita.
                logger.exception("heartbeat non scritto")
            session.close()

        sleep(config.SUPERVISOR_INTERVAL_SECONDS)


def main(argv=None) -> int:
    """Avvio: `python -m starkeno.supervisor`, mai per percorso.

    L'ordine conta. Il controllo di versione dello schema viene PRIMA di tutto ed e'
    l'unico punto del sistema dove e' giusto fallire rumorosamente: partire con uno
    schema disallineato produce `no such column` inghiottiti dai try/except e zero alert.
    """
    argomenti = list(argv if argv is not None else sys.argv[1:])
    una_volta = "--una-volta" in argomenti

    factory = make_session_factory(DB_PATH)
    try:
        check_or_die(factory.kw["bind"])
    except SchemaVersionError as errore:
        print(errore, file=sys.stderr)
        return 2

    percorso_log = _configura_logging(DB_PATH)
    try:
        guardia = guard_istanza_singola()
    except OSError:
        print("Un altro supervisore e' gia' in esecuzione (porta %d occupata). "
              "Non ne parte un secondo: due istanze aprirebbero e chiuderebbero gli "
              "stessi alert a vicenda." % PORTA_GUARDIA, file=sys.stderr)
        return 3

    logger.info("supervisore avviato, log in %s", percorso_log)
    try:
        run_forever(snapshot(), session_factory=factory,
                    max_iterations=1 if una_volta else None)
    finally:
        guardia.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
