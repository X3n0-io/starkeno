"""Task 12 — la dashboard.

Questo file verifica la tabella di tracciabilita' del piano riga per riga: **ogni stato,
campo ed esito nuovo deve avere un pixel.** Un terzo stato che esiste solo dentro
`rules.py` e' invisibile all'utente, ed e' esattamente l'errore 4 di §12 — "una cosa
nuova senza una casa".

Sono test su una pagina statica, quindi verificano che il codice CI SIA, non che sia
bello. Vale la pena averli lo stesso: sono l'unica cosa che impedisce a uno stato di
esistere nel database e non sullo schermo.
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import starkeno.api as api_module


def test_dashboard_uses_only_local_assets():
    html = Path("starkeno/static/index.html").read_text(encoding="utf-8")
    css = Path("starkeno/static/style.css").read_text(encoding="utf-8")
    insieme = html + css

    assert "http://" not in insieme and "https://" not in insieme
    assert "cdn.tailwindcss.com" not in insieme
    assert 'href="/style.css"' in html


def test_local_stylesheet_is_served_by_the_dashboard():
    risposta = TestClient(api_module.app).get("/style.css")

    assert risposta.status_code == 200
    assert "text/css" in risposta.headers["content-type"]
    assert "background" in risposta.text


@pytest.fixture
def pagina(session_factory):
    def override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    api_module.app.dependency_overrides[api_module.get_session] = override
    client = TestClient(api_module.app)
    risposta = client.get("/")
    api_module.app.dependency_overrides.clear()
    assert risposta.status_code == 200
    return risposta.text


# ============================================================ gli endpoint consumati
@pytest.mark.parametrize("endpoint", [
    "/api/agents", "/api/alerts", "/api/rule-status", "/api/supervisor/status",
])
def test_the_page_consumes_every_read_endpoint(pagina, endpoint):
    assert endpoint in pagina, "la dashboard non legge %s" % endpoint


def test_the_page_can_dismiss_and_mute(pagina):
    """Senza dismiss, un falso positivo su un agente sano e sempre attivo non e'
    chiudibile da nessuna via — e continua a iniettare un warning nel loop dell'agente."""
    assert "/dismiss" in pagina
    assert "/mute" in pagina


def test_the_page_polls_instead_of_loading_once(pagina):
    """La v0 caricava una volta sola al load. Un supervisore che apre un alert mentre la
    pagina e' aperta non si vedrebbe fino a un refresh manuale."""
    assert "setInterval" in pagina
    intervalli = [int(n) for n in re.findall(r"setInterval\([^,]+,\s*(\d+)\)", pagina)]
    assert intervalli, "setInterval c'e' ma senza intervallo leggibile"
    assert all(3000 <= i <= 60000 for i in intervalli), intervalli


# ======================================================== ogni stato ha un pixel (§D)
@pytest.mark.parametrize("stato", ["candidate", "open", "resolved", "dismissed"])
def test_every_alert_status_is_rendered(pagina, stato):
    assert stato in pagina


@pytest.mark.parametrize("stato", ["ok", "violating", "non_valutabile", "error"])
def test_every_rule_state_is_rendered(pagina, stato):
    """`non_valutabile` dice "sto ancora calibrando" invece di dare via libera; `error`
    dice che una regola e' rotta. Sono i due modi in cui il silenzio si traveste da
    salute, e se non arrivano allo schermo non servono a niente."""
    assert stato in pagina


def test_a_broken_rule_looks_different_from_a_healthy_one(pagina):
    """**Se `error` e `ok` avessero lo stesso colore, una regola rotta sembrerebbe sana.**

    E' il fallimento peggiore di questo sistema nella sua forma piu' diretta: il silenzio
    indistinguibile dalla salute.
    """
    stili = dict(re.findall(r'STILI_REGOLA\s*=\s*\{(.*?)\}', pagina, re.S) and
                 re.findall(r'(\w+)\s*:\s*"([^"]+)"',
                            re.search(r'STILI_REGOLA\s*=\s*\{(.*?)\}', pagina, re.S).group(1)))
    assert "error" in stili and "ok" in stili
    assert stili["error"] != stili["ok"], "una regola rotta e' indistinguibile da una sana"


def test_stale_is_rendered_differently_from_recovery(pagina):
    """Archiviazione per inattivita' e rientro sono due cose diverse: "risolto" da solo
    mentirebbe su meta' dei casi."""
    assert "stale" in pagina
    assert "recovery" in pagina
    etichette = re.findall(r'ETICHETTE_CHIUSURA\s*=\s*\{(.*?)\}', pagina, re.S)
    assert etichette, "manca la mappa delle etichette di chiusura"
    assert "inattivit" in etichette[0].lower(), "lo stantio non e' spiegato in parole"


def test_the_data_quality_rule_is_rendered(pagina):
    """Il guard MAX_TRACKED_AGENTS apre un alert che non appartiene a nessuna regola.
    Se la dashboard non lo conoscesse, il caso "4.000 agenti finti, zero alert"
    resterebbe invisibile proprio mentre il supervisore e' cieco."""
    assert "data_quality" in pagina


# ============================================================= stato del supervisore
def test_the_supervisor_heartbeat_is_shown(pagina):
    """Un supervisore morto e un sistema sano mostrano la stessa schermata: zero alert.
    Questa riga e' l'unica cosa che li distingue.

    Si cerca l'ID dell'elemento e non la parola "Supervisore": quella compare anche nel
    `<title>` e nei commenti, quindi il test passava anche togliendo la riga. Verificato
    mutando il codice.
    """
    assert 'id="riga-supervisore"' in pagina, "manca l'elemento della riga di stato"
    assert "last_run_at" in pagina


@pytest.mark.parametrize("funzione", [
    "caricaSupervisore", "caricaAlert", "caricaStatiRegola", "loadAgents",
])
def test_every_loader_is_both_defined_and_called(pagina, funzione):
    """Definita E chiamata: contare le occorrenze prende la definizione rinominata.

    E' il limite dei test su una pagina statica — vedono che il codice c'e', non che
    giri. Rinominare la sola definizione lascia il nome al sito di chiamata, e una
    ricerca testuale semplice non se ne accorge; contando le occorrenze si'.

    Il fatto che la pagina funzioni davvero e' stato verificato aprendola su un database
    di demo e leggendo il DOM renderizzato, non da qui.
    """
    assert pagina.count(funzione) >= 2, (
        "%s compare una volta sola: o e' definita e mai chiamata, o chiamata e mai "
        "definita" % funzione
    )


def test_a_stale_heartbeat_is_flagged_visually(pagina):
    """Oltre 3 x l'intervallo il supervisore e' da considerarsi fermo."""
    assert re.search(r"3\s*\*", pagina) or "180" in pagina, (
        "manca la soglia di 3 x SUPERVISOR_INTERVAL_SECONDS sull'heartbeat"
    )


# ============================================================== altri campi di §D
def test_weighted_tokens_are_shown_next_to_raw_ones(pagina):
    """Oggi il numero piu' grande della pagina e' in un'unita' DIVERSA da quella con cui
    ragionano gli alert: R3 e R4 misurano su `effective_tokens`."""
    assert "total_effective_tokens" in pagina
    assert "pesati" in pagina.lower()


def test_alerts_are_grouped_by_agent(pagina):
    """Un agente bloccato su modello frontier fa scattare piu' regole insieme: una causa
    sola e una correzione sola. Tre righe sparse si leggono come tre problemi."""
    assert "project" in pagina
    # l'ACCESSO al campo, non la parola: `related_rule` compare anche nel commento che
    # spiega il raggruppamento, e cercarla li' rendeva il test vacuo
    assert "evidence.related_rule" in pagina, (
        "il legame fra alert correlati non viene letto: tre righe di uno stesso incidente "
        "si leggeranno come tre problemi"
    )


def test_the_rename_caveat_is_written_on_the_page(pagina):
    """Un rename orfana i suoi alert: `agent-v1` -> `agent-v2` lascia il vecchio senza
    possibilita' di recupero, e chiudera' per stantio dopo 7 giorni marcato "non
    risolto". E' accettato in v1 e va scritto dov'e' visibile."""
    assert "rinomin" in pagina.lower() or "rename" in pagina.lower()


def test_the_page_still_shows_the_agents_table(pagina):
    """La v0 non deve sparire sotto la sezione nuova."""
    assert "agents-table-body" in pagina
    assert "StarkEno" in pagina
