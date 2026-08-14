"""Difetti trovati dalla verifica generale dell'infrastruttura.

Nessuno dei tre produce un errore visibile. Due erano gia' descritti a parole nel codice
o nel piano come "risolti", e non lo erano: e' il modo tipico in cui questo progetto
sbaglia — la prosa suona convincente anche quando nasconde un buco.
"""
from datetime import datetime, timedelta, timezone

from starkeno.config import snapshot
from starkeno.db import Alert, get_live_alert, get_watermark, record_action
from starkeno.supervisor import AGENTE_SISTEMA, run_once
import starkeno.supervisor as sup

ORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)


def azioni(session, agente, *, quante, fine=ORA, token=5000, passo=60,
           modello="claude-opus-4-5", prefisso="task"):
    for i in range(quante):
        riga = record_action(session, project=agente, action="%s:%d" % (prefisso, i),
                             model_used=modello, tokens_used=token)
        riga.timestamp = fine - timedelta(seconds=passo * (quante - 1 - i))
        session.commit()


# =============================================================== qualita' dei dati
def test_the_data_quality_alert_closes_when_the_flood_stops(session):
    """**L'alert di qualita' dati non si chiudeva mai.**

    `data_quality` non e' fra le quattro regole valutate, quindi nessuna riconciliazione
    lo toccava: una volta aperto restava li' per sempre, anche dopo che il chiamante
    aveva corretto il proprio `project`. Un alert perpetuo su un problema risolto
    insegna a ignorare la dashboard, che e' il fallimento peggiore di tutti.
    """
    stretta = snapshot(MAX_TRACKED_AGENTS=3)
    for i in range(6):
        azioni(session, "scraper-%d" % i, quante=1)

    run_once(session, now=ORA, config=stretta)
    allarme = session.query(Alert).filter_by(rule="data_quality").one()
    assert allarme.status in ("candidate", "open")

    # il chiamante corregge: ora gli agenti distinti stanno sotto il limite
    larga = snapshot(MAX_TRACKED_AGENTS=200)
    run_once(session, now=ORA + timedelta(minutes=5), config=larga)

    allarme = session.query(Alert).filter_by(rule="data_quality").one()
    assert allarme.status == "resolved", "l'alert di qualita' dati non si chiude mai"
    assert allarme.resolution == "recovery"


def test_the_data_quality_alert_opens_immediately(session):
    """Non c'e' niente da osservare: o ci sono troppi agenti o non ci sono.

    La fase `candidate` esiste per lasciare che una raffica si risolva da sola prima di
    disturbare. Qui non c'e' nessuna raffica: il conteggio degli agenti distinti e' un
    fatto, e tenerlo in osservazione per quindici minuti ritarda soltanto l'unica
    segnalazione che spiega perche' tutte le altre sono sparite.
    """
    stretta = snapshot(MAX_TRACKED_AGENTS=3)
    for i in range(6):
        azioni(session, "scraper-%d" % i, quante=1)

    run_once(session, now=ORA, config=stretta)

    assert session.query(Alert).filter_by(rule="data_quality").one().status == "open"


def test_the_system_agent_is_never_evaluated_as_a_real_one(session):
    """`__sistema__` non e' un agente: non deve finire fra quelli su cui girano le regole.

    Il filtro c'era ma era scritto `set(a) | set(b) - {SIST}`, e in Python `-` lega piu'
    stretto di `|`: si applicava a UN SOLO operando. Verificato — con `__sistema__` fra
    gli attivi, l'espressione scritta lo lasciava passare.
    """
    stretta = snapshot(MAX_TRACKED_AGENTS=3)
    for i in range(6):
        azioni(session, "scraper-%d" % i, quante=1)
    run_once(session, now=ORA, config=stretta)

    # un chiamante malizioso o distratto usa il nome riservato
    azioni(session, AGENTE_SISTEMA, quante=30, prefisso="finto")
    larga = snapshot(MAX_TRACKED_AGENTS=200)

    risultato = run_once(session, now=ORA + timedelta(minutes=5), config=larga)

    assert AGENTE_SISTEMA not in risultato.agenti


# ==================================================================== watermark
def test_the_watermark_does_not_advance_when_the_round_fails(session, monkeypatch):
    """**Il watermark avanzava anche su un giro fallito.**

    Il commento nel codice diceva "scritto SOLO a fine giro riuscito", ma la scrittura
    avveniva alla fine della VALUTAZIONE, prima della riconciliazione. Se la
    riconciliazione falliva, l'anomalia trovata non veniva registrata da nessuna parte E
    il watermark era gia' avanzato: quelle azioni non sarebbero state riesaminate mai
    piu' da nessuno.

    Verificato prima della correzione: watermark da 60 a 61 su un giro fallito, anomalia
    persa per sempre.
    """
    config = snapshot()
    azioni(session, "spendaccione", quante=60)
    run_once(session, now=ORA, config=config)
    watermark_iniziale = get_watermark(session, "spendaccione")

    # arriva l'anomalia
    riga = record_action(session, project="spendaccione", action="task:enorme",
                         model_used="claude-opus-4-5", tokens_used=900_000)
    riga.timestamp = ORA + timedelta(minutes=1)
    session.commit()

    originale = sup._riconcilia

    def riconcilia_rotta(ctx, regola, esito, risultato):
        if regola == "spend_anomaly":
            raise RuntimeError("scrittura fallita")
        return originale(ctx, regola, esito, risultato)

    monkeypatch.setattr(sup, "_riconcilia", riconcilia_rotta)
    run_once(session, now=ORA + timedelta(minutes=2), config=config)

    assert get_watermark(session, "spendaccione") == watermark_iniziale, (
        "il watermark e' avanzato su un giro fallito: l'anomalia e' persa per sempre"
    )

    # al giro successivo, con la riconciliazione sana, l'anomalia dev'essere ritrovata
    monkeypatch.setattr(sup, "_riconcilia", originale)
    run_once(session, now=ORA + timedelta(minutes=3), config=config)

    assert get_live_alert(session, "spendaccione", "spend_anomaly") is not None, (
        "l'anomalia non e' stata riesaminata dopo il giro fallito"
    )


def test_the_watermark_advances_on_a_successful_round(session):
    """Il complemento: senza, la correzione sopra si otterrebbe non avanzandolo mai, e
    ogni giro rivaluterebbe tutto lo storico."""
    config = snapshot()
    azioni(session, "veloce", quante=40)
    run_once(session, now=ORA, config=config)
    primo = get_watermark(session, "veloce")

    azioni(session, "veloce", quante=10, fine=ORA + timedelta(minutes=5))
    run_once(session, now=ORA + timedelta(minutes=6), config=config)

    assert get_watermark(session, "veloce") > primo
