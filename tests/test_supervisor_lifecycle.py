"""Task 8 — la riconciliazione: da un esito di regola a un alert.

Il ciclo di vita di un alert e' il punto in cui questo sistema puo' fallire nei modi
peggiori, e sono tutti silenziosi:

- promuovere troppo presto -> una raffica auto-risolta diventa un alert permanente;
- chiudere per silenzio -> un agente fermo sembra guarito, e un cron rotto lampeggia
  per sempre alternando aperto e chiuso;
- trattare `NON_VALUTABILE` come non-violazione -> un alert si chiude mentre un chiamante
  rotto scrive token a zero e lo spreco continua senza che nessuno lo misuri;
- trattare `NON_VALUTABILE` come violazione -> `last_seen` avanza a ogni giro e l'alert
  non si chiude piu', nemmeno per stantio.

Tutti i test chiamano `run_once` piu' volte facendo avanzare `now` a mano, con i valori
di PRODUZIONE delle costanti. Mai avviando il loop, mai azzerando PROMOTE_MIN_MINUTES:
sarebbe cancellare la proprieta' sotto test.
"""
from datetime import datetime, timedelta, timezone

import pytest

from starkeno.config import snapshot
from starkeno.db import (
    Alert,
    AgentAction,
    RuleStatus,
    get_live_alert,
    get_open_alerts,
    write_heartbeat,
)
from starkeno.supervisor import run_once

ORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
CONF = snapshot()          # valori di produzione: le proprieta' vanno provate su quelli


def loop_azioni(session, agente, *, quante=30, fine, passo=timedelta(seconds=4), token=2000):
    """Una sequenza che fa scattare R1 e SOLO R1: `read/edit/test` sugli stessi file.

    I 2.000 token non sono arbitrari. A 1.000 (<= EXPENSIVE_TRIVIAL_TOKENS) scatterebbe
    anche R2, e a 25.000 anche R4: realistico — e' il caso "un incidente, non tre righe"
    — ma renderebbe illeggibili i test sul ciclo di vita, che parlano di UN alert.
    Il caso a piu' regole ha il suo test dedicato in fondo al file.
    """
    ciclo = ["read:app.py", "edit:app.py", "test:tests/"]
    for i in range(quante):
        session.add(AgentAction(
            project=agente, action=ciclo[i % 3], model_used="claude-opus-4-5",
            tokens_used=token, timestamp=fine - passo * (quante - 1 - i),
        ))
    session.commit()


def azioni_sane(session, agente, *, quante, fine, passo=timedelta(seconds=4), token=1000):
    for i in range(quante):
        session.add(AgentAction(
            project=agente, action="passo_%d:file_%d.py" % (i, i),
            model_used="claude-haiku-4-5", tokens_used=token,
            timestamp=fine - passo * (quante - 1 - i),
        ))
    session.commit()


# ================================================================ il senso di `now`
def test_a_round_does_not_see_actions_that_happen_after_now(session):
    """**`run_once(now=X)` valuta il mondo COM'ERA a X.**

    In produzione non esistono azioni nel futuro — `timestamp` e' l'ora di ingestione
    assegnata da `db.py` — ma il metodo di verifica prescritto per il ciclo di vita e'
    proprio chiamare `run_once` piu' volte facendo avanzare `now` a mano. Senza il limite
    superiore, ogni giro vede tutto il futuro dello scenario e i test misurano un sistema
    diverso da quello che gira.

    Misurato prima della correzione: `first_seen` finiva DOPO `now`, quindi
    `now - first_seen` era negativo e nessun alert veniva mai promosso.
    """
    # L'agente e' ATTIVO a ORA: senza queste, il limite sulla selezione degli agenti lo
    # escluderebbe del tutto e il test passerebbe senza esercitare il limite sul
    # caricamento delle azioni. Verificato mutando il codice: era vacuo.
    azioni_sane(session, "a", quante=25, fine=ORA)
    loop_azioni(session, "a", fine=ORA + timedelta(hours=2))   # il loop e' nel futuro

    risultato = run_once(session, now=ORA, config=CONF)
    assert "a" in risultato.agenti, "l'agente non e' stato nemmeno valutato: test vacuo"
    assert get_live_alert(session, "a", "loop") is None, "un giro ha valutato azioni future"

    run_once(session, now=ORA + timedelta(hours=2), config=CONF)
    alert = get_live_alert(session, "a", "loop")
    assert alert is not None
    assert alert.first_seen <= ORA + timedelta(hours=2)


def test_each_rule_uses_its_own_window_not_the_active_agent_one(session):
    """**Ogni regola guarda la PROPRIA finestra**, non quella che decide chi valutare.

    `SUPERVISOR_ACTIVE_AGENT_HOURS` (48h) serve a scegliere QUALI agenti valutare;
    `HEAVY_WINDOW_HOURS` (24h) e' la finestra su cui R4 misura. Usando la prima per
    entrambe le cose, una soglia GIORNALIERA come `HEAVY_DAILY_TOKENS` verrebbe applicata
    a due giorni di dati — R2 e R4 il doppio piu' sensibili del progettato — e le tre
    costanti di finestra resterebbero vive solo nel testo dei messaggi.

    Misurato prima della correzione: chiamate pesanti uscite da 24 ore continuavano a
    tenere aperto l'alert di R4, perche' erano ancora dentro le 48.

    Qui la spesa e' distribuita su 36 ore: sopra la soglia se si guardano 48 ore, sotto
    se si guardano le 24 che la regola dichiara.
    """
    meta_soglia = CONF.HEAVY_DAILY_TOKENS * 0.7
    per_chiamata = int(meta_soglia / 10)
    for blocco, offset_ore in ((10, 30), (10, 6)):     # 36 ore fa e 6 ore fa
        for i in range(blocco):
            session.add(AgentAction(
                project="lungo", action="analizza:doc_%d_%d" % (offset_ore, i),
                model_used="claude-opus-4-5", tokens_used=per_chiamata,
                timestamp=ORA - timedelta(hours=offset_ore) + timedelta(seconds=i * 10),
            ))
    session.commit()

    run_once(session, now=ORA, config=CONF)

    assert get_live_alert(session, "lungo", "steady_waste") is None, (
        "R4 ha sommato 36 ore di spesa su una soglia che dichiara 24 ore"
    )


# ==================================================================== promozione
def test_a_first_violation_creates_a_candidate_not_an_open_alert(session):
    """Il percorso in linea avvisa l'agente solo sugli `open`: un candidate non deve
    ancora produrre rumore dentro il loop dell'agente."""
    loop_azioni(session, "a", fine=ORA)
    run_once(session, now=ORA, config=CONF)

    alert = get_live_alert(session, "a", "loop")
    assert alert is not None
    assert alert.status == "candidate"
    assert get_open_alerts(session, "a") == []


def test_promotion_requires_the_time_condition(session):
    """Tre giri in tre minuti NON promuovono: PROMOTE_MIN_MINUTES vale 15."""
    for minuto in range(4):
        adesso = ORA + timedelta(minutes=minuto)
        loop_azioni(session, "a", fine=adesso)
        run_once(session, now=adesso, config=CONF)

    alert = get_live_alert(session, "a", "loop")
    assert alert.observed_rounds >= CONF.PROMOTE_MIN_ROUNDS
    assert alert.status == "candidate", "promosso col solo conteggio dei giri"


def test_promotion_requires_the_round_condition(session):
    """**Il caso del portatile che si sospende.**

    Candidate creato alle 18:00, coperchio chiuso alle 18:01, primo giro alle 09:00 del
    giorno dopo: `now - first_seen` sono 15 ore, molto oltre i 15 minuti. Senza il
    conteggio dei giri l'alert verrebbe promosso avendo osservato UN SOLO giro, e la
    promozione ritardata — che e' cio' che rende il sistema prudente nei fatti — non
    avrebbe mai avuto luogo.
    """
    loop_azioni(session, "a", fine=ORA)
    run_once(session, now=ORA, config=CONF)

    domani = ORA + timedelta(hours=15)
    loop_azioni(session, "a", fine=domani)
    run_once(session, now=domani, config=CONF)

    alert = get_live_alert(session, "a", "loop")
    assert (domani - alert.first_seen) > timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)
    assert alert.observed_rounds < CONF.PROMOTE_MIN_ROUNDS
    assert alert.status == "candidate", "promosso col solo trascorrere del tempo"


def test_promotion_happens_when_both_conditions_are_met(session):
    adesso = ORA
    for _ in range(CONF.PROMOTE_MIN_ROUNDS + 1):
        loop_azioni(session, "a", fine=adesso)
        run_once(session, now=adesso, config=CONF)
        adesso += timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)

    alert = get_live_alert(session, "a", "loop")
    assert alert.status == "open"
    assert len(get_open_alerts(session, "a")) == 1


# ============================================================ raffica auto-risolta
def test_a_candidate_whose_violation_disappears_is_deleted(session):
    """Una raffica che si risolve da sola non deve lasciare traccia.

    Se restasse, `episodes` conterebbe episodi che non sono mai stati problemi, e la
    dashboard mostrerebbe un evento dove non c'e' stato niente.
    """
    loop_azioni(session, "a", fine=ORA)
    run_once(session, now=ORA, config=CONF)
    assert get_live_alert(session, "a", "loop") is not None

    dopo = ORA + timedelta(minutes=20)
    azioni_sane(session, "a", quante=40, fine=dopo)
    run_once(session, now=dopo, config=CONF)

    assert get_live_alert(session, "a", "loop") is None
    assert session.query(Alert).count() == 0


# ============================================================== agente cron
def test_a_broken_cron_agent_produces_one_alert_and_does_not_flap(session):
    """**Il silenzio non e' guarigione.**

    Un agente cron orario e rotto: se si chiudesse dopo N minuti senza violazioni,
    chiuderebbe a ogni pausa e riaprirebbe a ogni esecuzione, lampeggiando per sempre, e
    `episodes` non accumulerebbe niente di sensato.

    Un agente fermo non produce violazioni per definizione: la chiusura richiede una
    PROVA POSITIVA, cioe' azioni pulite dopo `last_seen`, che un agente fermo non ha.

    Nota sulla costruzione: ogni esecuzione del cron blocca l'agente per una VENTINA di
    minuti, non per due. Non e' un dettaglio del test — e' l'invariante I1 che lo impone:
    `PROMOTE_MIN_MINUTES` (15) sta sopra la finestra corta piu' lunga di R1 (10) proprio
    perche' una raffica breve NON diventi mai un alert. Un blocco di due minuti resta
    candidate e viene cancellato, ed e' il comportamento voluto.
    """
    adesso = ORA
    for esecuzione in range(4):
        # 30 azioni ogni 40 secondi = poco piu' di 19 minuti di blocco
        loop_azioni(session, "cron", fine=adesso + timedelta(minutes=19),
                    passo=timedelta(seconds=40))
        for minuto in range(0, 20, 5):
            run_once(session, now=adesso + timedelta(minutes=minuto), config=CONF)
        # poi quaranta minuti di silenzio, mentre il supervisore continua a girare
        for minuto in range(20, 60, 10):
            run_once(session, now=adesso + timedelta(minutes=minuto), config=CONF)
        adesso += timedelta(hours=1)

    alerts = session.query(Alert).filter_by(project="cron", rule="loop").all()
    assert len(alerts) == 1, "l'alert ha lampeggiato: %r" % [a.status for a in alerts]
    assert alerts[0].status == "open"
    assert alerts[0].episodes == 1, "episodes conta i giri invece degli episodi"


# ============================================================== NON_VALUTABILE
def test_an_unevaluable_rule_freezes_the_alert(session):
    """`NON_VALUTABILE` congela: non promuove, non risolve, non cancella, non tocca last_seen.

    Se fosse trattato come non-violazione, un alert R2 aperto si chiuderebbe per recupero
    mentre un chiamante rotto scrive `tokens_used=0` e lo spreco continua senza che
    nessuno lo misuri.
    """
    adesso = ORA
    for _ in range(CONF.PROMOTE_MIN_ROUNDS + 1):
        loop_azioni(session, "a", fine=adesso)
        run_once(session, now=adesso, config=CONF)
        adesso += timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)

    alert = get_live_alert(session, "a", "loop")
    assert alert.status == "open"
    last_seen_prima = alert.last_seen

    # ora l'agente logga solo categorie nude: R1 si astiene
    dopo = adesso + timedelta(minutes=30)
    for i in range(40):
        session.add(AgentAction(project="a", action="read_file", model_used="claude-opus-4-5",
                                tokens_used=1000, timestamp=dopo - timedelta(seconds=40 - i)))
    session.commit()
    run_once(session, now=dopo, config=CONF)

    alert = get_live_alert(session, "a", "loop")
    assert alert is not None, "un'astensione ha chiuso l'alert"
    assert alert.status == "open"
    assert alert.last_seen == last_seen_prima, "un'astensione ha fatto avanzare last_seen"

    stato = session.query(RuleStatus).filter_by(project="a", rule="loop").one()
    assert stato.state == "non_valutabile"
    assert stato.reason


# ==================================================================== recupero
def test_an_open_alert_closes_after_enough_clean_actions(session):
    adesso = ORA
    for _ in range(CONF.PROMOTE_MIN_ROUNDS + 1):
        loop_azioni(session, "a", fine=adesso)
        run_once(session, now=adesso, config=CONF)
        adesso += timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)
    assert get_live_alert(session, "a", "loop").status == "open"

    dopo = adesso + timedelta(minutes=30)
    azioni_sane(session, "a", quante=CONF.RESOLVE_MIN_HEALTHY_ACTIONS + 5, fine=dopo)
    run_once(session, now=dopo, config=CONF)

    assert get_live_alert(session, "a", "loop") is None
    chiuso = session.query(Alert).filter_by(project="a", rule="loop").one()
    assert chiuso.status == "resolved"
    assert chiuso.resolution == "recovery"
    assert chiuso.resolved_at is not None


def test_too_few_clean_actions_do_not_close_the_alert(session):
    adesso = ORA
    for _ in range(CONF.PROMOTE_MIN_ROUNDS + 1):
        loop_azioni(session, "a", fine=adesso)
        run_once(session, now=adesso, config=CONF)
        adesso += timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)

    dopo = adesso + timedelta(minutes=30)
    azioni_sane(session, "a", quante=CONF.RESOLVE_MIN_HEALTHY_ACTIONS - 1, fine=dopo)
    run_once(session, now=dopo, config=CONF)

    assert get_live_alert(session, "a", "loop").status == "open"


def test_an_r4_alert_lingers_until_the_heavy_calls_leave_the_window(session):
    """**Una conseguenza del design che vale la pena vedere scritta.**

    Il recupero si tenta solo quando la regola dice OK sulla finestra PIENA. Per R2 e R4,
    la cui finestra e' di 24 ore, questo significa che un alert resta aperto fino a
    quando le azioni che l'hanno causato non escono dalla finestra — anche se l'agente si
    e' corretto subito.

    Non e' un difetto: finche' quelle chiamate sono dentro la finestra, la spesa che
    misurano e' realmente avvenuta nelle ultime 24 ore. Ma e' una latenza di chiusura di
    un giorno, e chi guarda la dashboard deve sapere che la vedra'.

    L'alternativa — tentare il recupero anche mentre la finestra piena viola — chiuderebbe
    l'alert per poi riaprirlo al giro dopo sulle stesse identiche prove: il lampeggio che
    tutto il ciclo di vita esiste per impedire.
    """
    for i in range(20):
        session.add(AgentAction(
            project="p", action="analizza:doc_%d" % i, model_used="claude-opus-4-5",
            tokens_used=60_000, timestamp=ORA - timedelta(seconds=10 * (20 - i)),
        ))
    session.commit()

    adesso = ORA
    for _ in range(CONF.PROMOTE_MIN_ROUNDS + 1):
        run_once(session, now=adesso, config=CONF)
        adesso += timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)
    assert get_live_alert(session, "p", "steady_waste").status == "open", "R4 non si e' aperto"

    # l'agente si corregge subito
    dopo = adesso + timedelta(minutes=30)
    for i in range(CONF.RESOLVE_MIN_HEALTHY_ACTIONS + 5):
        session.add(AgentAction(
            project="p", action="analizza:nuovo_%d" % i, model_used="claude-opus-4-5",
            tokens_used=3_000, timestamp=dopo - timedelta(seconds=5 * (25 - i)),
        ))
    session.commit()

    # a meta' finestra l'alert e' ancora aperto: la spesa e' davvero dentro le 24 ore
    meta = ORA + timedelta(hours=CONF.HEAVY_WINDOW_HOURS // 2)
    run_once(session, now=meta, config=CONF)
    assert get_live_alert(session, "p", "steady_waste").status == "open"

    # uscite dalla finestra, la regola dice OK e il recupero si compie
    fuori = ORA + timedelta(hours=CONF.HEAVY_WINDOW_HOURS + 1)
    run_once(session, now=fuori, config=CONF)

    chiuso = session.query(Alert).filter_by(project="p", rule="steady_waste").one()
    assert chiuso.status == "resolved"
    assert chiuso.resolution == "recovery", "chiuso per inattivita' invece che per recupero"


def test_a_still_violating_agent_does_not_recover_on_the_restricted_window(session):
    """**Il test che protegge l'invariante I4, quello a margine zero.**

    `RESOLVE_MIN_HEALTHY_ACTIONS` (20) deve stare sopra il numero di occorrenze che ogni
    regola richiede per violare. Se fosse piu' piccolo, la rivalutazione sulla finestra
    ristretta direbbe OK PER COSTRUZIONE — la finestra sarebbe troppo corta perche' una
    violazione ci stia dentro — e l'alert si chiuderebbe da solo mentre il comportamento
    continua, riaprendo al giro dopo.

    Qui l'agente continua a fare esattamente la stessa cosa: l'alert deve restare aperto.
    """
    adesso = ORA
    for _ in range(CONF.PROMOTE_MIN_ROUNDS + 1):
        loop_azioni(session, "a", fine=adesso)
        run_once(session, now=adesso, config=CONF)
        adesso += timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)
    assert get_live_alert(session, "a", "loop").status == "open"

    dopo = adesso + timedelta(minutes=30)
    loop_azioni(session, "a", quante=CONF.RESOLVE_MIN_HEALTHY_ACTIONS + 10, fine=dopo)
    run_once(session, now=dopo, config=CONF)

    alert = get_live_alert(session, "a", "loop")
    assert alert is not None, "l'alert si e' chiuso mentre l'agente violava ancora"
    assert alert.status == "open"


# ====================================================================== stantio
def test_an_agent_gone_quiet_for_long_enough_is_archived_not_healed(session):
    adesso = ORA
    for _ in range(CONF.PROMOTE_MIN_ROUNDS + 1):
        loop_azioni(session, "a", fine=adesso)
        run_once(session, now=adesso, config=CONF)
        adesso += timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)

    molto_dopo = adesso + timedelta(days=CONF.RESOLVE_STALE_DAYS + 1)
    write_heartbeat(session, now=molto_dopo - timedelta(seconds=CONF.SUPERVISOR_INTERVAL_SECONDS),
                    duration_ms=1, agents_evaluated=1, rules_failed=0, last_error=None)
    run_once(session, now=molto_dopo, config=CONF)

    chiuso = session.query(Alert).filter_by(project="a", rule="loop").one()
    assert chiuso.status == "resolved"
    assert chiuso.resolution == "stale", "archiviato come guarigione invece che come inattivita'"


def test_stale_archiving_is_skipped_after_a_long_supervisor_outage(session):
    """Dieci giorni di vacanza non devono archiviare in blocco ogni alert aperto.

    Il buco si rileva dall'heartbeat: se l'ultimo giro e' piu' vecchio di
    3 x SUPERVISOR_INTERVAL_SECONDS, la valutazione dello stantio si salta per un giro.
    """
    adesso = ORA
    for _ in range(CONF.PROMOTE_MIN_ROUNDS + 1):
        loop_azioni(session, "a", fine=adesso)
        run_once(session, now=adesso, config=CONF)
        adesso += timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)

    molto_dopo = adesso + timedelta(days=CONF.RESOLVE_STALE_DAYS + 3)
    run_once(session, now=molto_dopo, config=CONF)   # l'heartbeat e' vecchissimo

    alert = get_live_alert(session, "a", "loop")
    assert alert is not None, "lo stantio ha archiviato dopo un'interruzione del processo"
    assert alert.status == "open"


# ============================================================== regola che solleva
def test_a_raising_rule_is_visible_and_does_not_stop_the_others(session):
    """Senza `state='error'`, una regola rotta e' indistinguibile da una che dice OK.

    E' il fallimento peggiore di questo sistema nella sua forma piu' diretta.
    """
    import starkeno.supervisor as sup

    loop_azioni(session, "a", fine=ORA)

    def esplode(*args, **kwargs):
        raise ZeroDivisionError("regola rotta")

    originale = sup.VALUTATORI["expensive_model"]
    sup.VALUTATORI["expensive_model"] = esplode
    try:
        risultato = run_once(session, now=ORA, config=CONF)
    finally:
        sup.VALUTATORI["expensive_model"] = originale

    rotta = session.query(RuleStatus).filter_by(project="a", rule="expensive_model").one()
    assert rotta.state == "error"
    assert "regola rotta" in rotta.reason
    assert risultato.rules_failed == 1

    # le altre regole sono state valutate lo stesso
    assert get_live_alert(session, "a", "loop") is not None
    assert session.query(RuleStatus).filter_by(project="a", rule="loop").one().state == "violating"


# ============================================================== insieme valutato
def test_agents_with_an_unresolved_alert_stay_in_the_evaluated_set(session):
    """La clausola di unione non e' ornamentale: e' cio' che permette la chiusura.

    `RESOLVE_STALE_DAYS` (7 giorni) e' molto oltre `SUPERVISOR_ACTIVE_AGENT_HOURS` (48h),
    quindi un agente fermo esce dall'insieme degli attivi PRIMA di poter essere
    archiviato. Senza l'unione, i suoi alert non si chiuderebbero mai.
    """
    adesso = ORA
    for _ in range(CONF.PROMOTE_MIN_ROUNDS + 1):
        loop_azioni(session, "fermo", fine=adesso)
        run_once(session, now=adesso, config=CONF)
        adesso += timedelta(minutes=CONF.PROMOTE_MIN_MINUTES)

    # oltre la finestra degli attivi, ma dentro quella dello stantio
    dopo = adesso + timedelta(hours=CONF.SUPERVISOR_ACTIVE_AGENT_HOURS + 5)
    write_heartbeat(session, now=dopo - timedelta(seconds=CONF.SUPERVISOR_INTERVAL_SECONDS),
                    duration_ms=1, agents_evaluated=1, rules_failed=0, last_error=None)
    risultato = run_once(session, now=dopo, config=CONF)

    assert "fermo" in risultato.agenti


def test_too_many_agents_opens_a_data_quality_alert_and_stops_evaluating(session):
    """`f"scraper-{run_id}"` produce migliaia di nomi con poche azioni ciascuno: tutti
    sotto ogni soglia di storia, quindi zero alert, mentre il supervisore fa migliaia di
    query al minuto. Massimamente occupato e completamente cieco."""
    stretta = snapshot(MAX_TRACKED_AGENTS=5)
    for i in range(8):
        azioni_sane(session, "scraper-%d" % i, quante=3, fine=ORA)

    risultato = run_once(session, now=ORA, config=stretta)

    allarme = session.query(Alert).filter_by(rule="data_quality").one()
    assert "8" in allarme.detail
    assert risultato.agenti == []


# ================================================================ correlazione
def test_a_concurrent_violation_records_the_related_loop(session):
    """Un incidente, non tre righe.

    Un agente bloccato su modello frontier fa scattare R1 e R4 insieme: una causa sola e
    una correzione sola. La dashboard raggruppa per agente, e `related_rule` dice quale
    alert e' il capostipite.
    """
    import json

    for i in range(30):
        session.add(AgentAction(
            project="grosso", action=["read:app.py", "edit:app.py", "test:t/"][i % 3],
            model_used="claude-opus-4-5", tokens_used=60_000,
            timestamp=ORA - timedelta(seconds=4 * (30 - i)),
        ))
    session.commit()
    run_once(session, now=ORA, config=CONF)

    spreco = get_live_alert(session, "grosso", "steady_waste")
    assert spreco is not None
    assert json.loads(spreco.evidence).get("related_rule") == "loop"
