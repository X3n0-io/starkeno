"""Task 9 — il loop, l'heartbeat e il guard di istanza singola.

Tre modi di morire in silenzio, tutti chiusi qui:

**Il `try` fuori dal `while`.** E' la forma piu' naturale da scrivere, e con essa la
prima eccezione fa uscire dal loop: il supervisore muore e nessuno se ne accorge, perche'
un supervisore morto e un sistema sano mostrano la stessa schermata — zero alert.

**L'heartbeat scritto dopo il giro invece che dentro.** Quando il giro fallisce
l'heartbeat non viene aggiornato, e la dashboard mostra "supervisore fermo" senza dire
perche', oppure — peggio — il giro fallisce ma l'heartbeat resta fresco e il guasto e'
invisibile.

**Il guard di istanza singola con `SO_REUSEADDR`.** Su Windows quell'opzione ha semantica
OPPOSTA a Unix: permette il rebind. Il guard non guarda niente, due supervisori girano
insieme, e con `config.py` diversi aprono e chiudono lo stesso alert a vicenda ogni
sessanta secondi.
"""
import socket
from datetime import datetime, timedelta, timezone

import pytest

from starkeno.config import snapshot
from starkeno.db import SupervisorState, get_heartbeat
from starkeno.supervisor import guard_istanza_singola, run_forever

ORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
CONF = snapshot()


class Orologio:
    """Un `now` che avanza di un intervallo a ogni lettura, senza dormire davvero."""

    def __init__(self, inizio=ORA, passo=timedelta(seconds=60)):
        self.adesso = inizio
        self.passo = passo

    def __call__(self):
        valore = self.adesso
        self.adesso += self.passo
        return valore


# ================================================================ il loop non muore
def test_the_loop_survives_a_rule_that_raises_every_single_round(session_factory,
                                                                 monkeypatch):
    """**Il `try` sta dentro il `while`.**

    Con il `try` esterno la prima eccezione esce dal loop e il processo muore in
    silenzio. Qui `run_once` solleva a ogni giro: devono comunque avvenire tre giri, e
    nessuna eccezione deve propagarsi al chiamante.
    """
    import starkeno.supervisor as sup

    chiamate = []

    def esplode(session, now, config):
        chiamate.append(now)
        raise RuntimeError("giro rotto")

    monkeypatch.setattr(sup, "run_once", esplode)
    dormite = []

    run_forever(CONF, session_factory=session_factory, sleep=dormite.append,
                max_iterations=3, now_fn=Orologio())

    assert len(chiamate) == 3, "il loop e' morto alla prima eccezione"
    assert dormite == [CONF.SUPERVISOR_INTERVAL_SECONDS] * 3


def test_the_heartbeat_is_written_even_when_the_round_fails(session_factory, monkeypatch):
    """L'heartbeat sta DENTRO il try/except, non dopo.

    Un giro che fallisce deve lasciare traccia: `consecutive_errors` che sale e
    `last_error` col messaggio. Senza, il guasto e' invisibile.
    """
    import starkeno.supervisor as sup

    def esplode(session, now, config):
        raise ZeroDivisionError("divisione per zero")

    monkeypatch.setattr(sup, "run_once", esplode)

    run_forever(CONF, session_factory=session_factory, sleep=lambda _: None,
                max_iterations=3, now_fn=Orologio())

    # La sessione va chiusa: quella di `session_factory()` tiene una connessione PRELEVATA
    # dal pool, e `dispose()` chiude solo quelle che nel pool sono rientrate.
    sessione = session_factory()
    try:
        battito = get_heartbeat(sessione)
        assert battito is not None, "nessun heartbeat dopo tre giri falliti"
        assert battito.consecutive_errors == 3
        assert "divisione per zero" in battito.last_error
    finally:
        sessione.close()


def test_a_clean_round_resets_the_error_streak(session_factory, monkeypatch):
    import starkeno.supervisor as sup

    esiti = [RuntimeError("uno"), RuntimeError("due"), None]

    def alterno(session, now, config):
        errore = esiti.pop(0)
        if errore:
            raise errore
        return sup.RoundResult(agenti=["a"])

    monkeypatch.setattr(sup, "run_once", alterno)

    run_forever(CONF, session_factory=session_factory, sleep=lambda _: None,
                max_iterations=3, now_fn=Orologio())

    sessione = session_factory()
    try:
        battito = get_heartbeat(sessione)
        assert battito.consecutive_errors == 0
        assert battito.last_error is None
        assert battito.agents_evaluated == 1
    finally:
        sessione.close()


def test_the_heartbeat_records_how_long_the_round_took(session_factory, monkeypatch):
    import starkeno.supervisor as sup

    monkeypatch.setattr(sup, "run_once",
                        lambda session, now, config: sup.RoundResult(agenti=["a", "b"]))

    run_forever(CONF, session_factory=session_factory, sleep=lambda _: None,
                max_iterations=1, now_fn=Orologio())

    sessione = session_factory()
    try:
        battito = get_heartbeat(sessione)
        assert battito.last_run_ms >= 0
        assert battito.agents_evaluated == 2
        assert battito.last_run_at.tzinfo is not None
    finally:
        sessione.close()


def test_each_round_gets_a_fresh_session(session_factory, monkeypatch):
    """Una sessione per giro, chiusa a fine giro.

    Tenendone una sola aperta per sempre, la cache di identita' di SQLAlchemy servirebbe
    righe stantie: il supervisore leggerebbe alert che nel frattempo l'utente ha
    marcato come falsi positivi dalla dashboard.
    """
    import starkeno.supervisor as sup

    # Si conservano le SESSIONI, non i loro `id()`. Un `id()` e' unico solo fra oggetti
    # vivi CONTEMPORANEAMENTE: la sessione del giro precedente viene chiusa e liberata
    # prima che nasca la successiva, e CPython riusa volentieri quell'indirizzo. Il test
    # leggeva quel riuso come "sessione riusata fra i giri" e falliva senza che nulla
    # fosse rotto — misurato: 2 fallimenti su 40 esecuzioni, identici prima e dopo la
    # correzione delle connessioni. Tenendo un riferimento, gli indirizzi non si
    # riciclano e l'identita' torna a significare quello che il test vuole dire.
    viste = []
    monkeypatch.setattr(sup, "run_once",
                        lambda session, now, config: (viste.append(session),
                                                      sup.RoundResult())[1])

    run_forever(CONF, session_factory=session_factory, sleep=lambda _: None,
                max_iterations=3, now_fn=Orologio())

    assert len({id(s) for s in viste}) == 3, "la stessa sessione e' stata riusata fra i giri"


# ======================================================== guard di istanza singola
class SocketFallibile:
    """Socket minimale che rende osservabile la chiusura nel ramo fallito."""

    def __init__(self, *, fallisce_su):
        self.fallisce_su = fallisce_su
        self.closed = False

    def bind(self, _indirizzo):
        if self.fallisce_su == "bind":
            raise OSError("porta occupata")

    def listen(self, _backlog):
        if self.fallisce_su == "listen":
            raise OSError("listen fallita")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("fase", ["bind", "listen"])
def test_guard_closes_the_socket_when_startup_fails(monkeypatch, fase):
    """La risorsa locale non deve sopravvivere a un avvio non riuscito."""
    finto = SocketFallibile(fallisce_su=fase)
    monkeypatch.setattr("starkeno.supervisor.socket.socket", lambda *_: finto)

    with pytest.raises(OSError):
        guard_istanza_singola(47_710)

    assert finto.closed is True


def test_a_second_instance_cannot_start(monkeypatch):
    """Due supervisori insieme raddoppierebbero `episodes` e, con configurazioni
    diverse, aprirebbero e chiuderebbero lo stesso alert a vicenda ogni minuto."""
    porta = 47_701
    primo = guard_istanza_singola(porta)
    try:
        with pytest.raises(OSError):
            guard_istanza_singola(porta)
    finally:
        primo.close()


def test_the_guard_releases_the_port_when_the_process_ends(monkeypatch):
    """Un lock file non si pulisce dopo un kill; un socket si'.

    E' la ragione per cui il guard e' un socket e non un file con dentro un pid.
    """
    porta = 47_702
    primo = guard_istanza_singola(porta)
    primo.close()

    secondo = guard_istanza_singola(porta)     # non deve sollevare
    secondo.close()


def test_the_guard_does_not_set_so_reuseaddr():
    """**Su Windows `SO_REUSEADDR` ha semantica opposta a Unix: permette il rebind.**

    Misurato eseguendo: `bind` semplice -> OSError(10048); `bind` con SO_REUSEADDR ->
    riesce, e due supervisori girano insieme in silenzio. L'opzione e' l'idioma riflesso
    di chiunque scriva un server, quindi il divieto va reso esplicito e verificabile.

    Il controllo passa dall'AST e non dal testo: il docstring del guard SPIEGA perche'
    SO_REUSEADDR non va usato, quindi una ricerca testuale trova la propria
    documentazione e fallisce sempre. E' lo stesso errore gia' fatto nel test di purezza
    di `rules.py`.
    """
    import ast

    import starkeno.supervisor as sup

    with open(sup.__file__, encoding="utf-8") as f:
        albero = ast.parse(f.read())

    opzioni = [
        ast.unparse(nodo)
        for nodo in ast.walk(albero)
        if isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Attribute)
        and nodo.func.attr == "setsockopt"
    ]

    assert not opzioni, "il guard imposta opzioni sul socket: %r" % opzioni


def test_the_guard_actually_holds_the_socket_open():
    """Se il socket venisse raccolto dal garbage collector, la porta si libererebbe e il
    guard proteggerebbe solo per la durata della chiamata."""
    import gc

    porta = 47_703
    guardia = guard_istanza_singola(porta)
    gc.collect()
    try:
        with pytest.raises(OSError):
            guard_istanza_singola(porta)
    finally:
        guardia.close()


# ================================================================ avvio del processo
def test_the_module_can_be_started_as_a_module(monkeypatch):
    """`python -m starkeno.supervisor`, mai per percorso: rompe gli import assoluti."""
    import subprocess
    import sys
    import os
    import tempfile

    radice = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db = os.path.join(tempfile.mkdtemp(), "vuoto.db")
    ambiente = {**os.environ, "STARKENO_DB_PATH": db, "PYTHONPATH": radice}

    risultato = subprocess.run(
        [sys.executable, "-m", "starkeno.supervisor", "--una-volta"],
        cwd=radice, env=ambiente, capture_output=True, text=True, timeout=60,
    )

    # deve rifiutarsi di partire su uno schema non migrato, non esplodere in altri modi
    assert risultato.returncode != 0
    assert "alembic upgrade head" in (risultato.stdout + risultato.stderr)
