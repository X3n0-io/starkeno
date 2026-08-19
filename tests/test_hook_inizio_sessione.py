"""L'hook SessionStart deve aggiungere contesto senza poter rompere Codex."""
import io
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from starkeno import db
from starkeno.db import AgentAction


def _stdin(payload) -> io.StringIO:
    return io.StringIO(json.dumps(payload))


def _payload(*, evento="SessionStart", source="startup") -> dict:
    return {"hook_event_name": evento, "source": source}


def _percorso_db(session_factory) -> str:
    return session_factory.kw["bind"].url.database


def test_primo_avvio_restituisce_contesto_codex_senza_creare_database(
        monkeypatch, tmp_path, capsys):
    from starkeno import hook_inizio_sessione

    percorso = tmp_path / "cartella-ancora-assente" / "starkeno.db"
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr(sys, "stdin", _stdin(_payload()))

    assert hook_inizio_sessione.main() == 0
    uscita, errore = capsys.readouterr()
    risposta = json.loads(uscita)
    specifica = risposta["hookSpecificOutput"]
    assert specifica["hookEventName"] == "SessionStart"
    assert "StarkEno" in specifica["additionalContext"]
    assert "una sola breve riga" in specifica["additionalContext"]
    assert "prossimo messaggio utile" in specifica["additionalContext"]
    assert all(
        regola not in specifica["additionalContext"]
        for regola in ("R1", "R2", "R3", "R4")
    )
    assert errore == ""
    assert not percorso.exists()
    assert not percorso.parent.exists(), "SessionStart non deve creare nemmeno la cartella dati"


def test_database_con_schema_ma_senza_chiamate_mostra_il_benvenuto(
        monkeypatch, session_factory, capsys):
    from starkeno import hook_inizio_sessione

    monkeypatch.setenv("STARKENO_DB_PATH", _percorso_db(session_factory))
    monkeypatch.setattr(sys, "stdin", _stdin(_payload()))

    assert hook_inizio_sessione.main() == 0
    uscita, errore = capsys.readouterr()
    assert json.loads(uscita)["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert errore == ""


def test_una_sola_chiamata_non_basta_per_dire_niente(
        monkeypatch, session_factory, capsys):
    """Si chiamava «tace fino alla fase 3» e passava per quella ragione. Ora l'hook
    dopo una pausa parla, e questo test passa per un motivo diverso e piu' stretto: UNA
    chiamata sta sotto `CHIAMATE_MINIME`, quindi non c'e' niente di vero da dire.
    Il nome vecchio avrebbe continuato a passare descrivendo un comportamento che non
    esiste piu'."""
    from starkeno import hook_inizio_sessione

    with session_factory() as sessione:
        sessione.add(AgentAction(
            project="progetto", action="leggi", model_used="gpt-5",
            tokens_used=10, session_id="sessione", message_id="messaggio",
        ))
        sessione.commit()
    monkeypatch.setenv("STARKENO_DB_PATH", _percorso_db(session_factory))
    monkeypatch.setattr(sys, "stdin", _stdin(_payload()))

    assert hook_inizio_sessione.main() == 0
    uscita, errore = capsys.readouterr()
    assert uscita == ""
    assert errore == ""


@pytest.mark.parametrize("payload", [
    _payload(source="resume"),
    _payload(source="clear"),
    _payload(source="compact"),
    _payload(evento="Stop"),
    {},
])
def test_solo_session_start_startup_puo_aggiungere_contesto(
        payload, monkeypatch, tmp_path, capsys):
    from starkeno import hook_inizio_sessione

    percorso = tmp_path / "non-va-creato.db"
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr(sys, "stdin", _stdin(payload))

    assert hook_inizio_sessione.main() == 0
    assert capsys.readouterr() == ("", "")
    assert not percorso.exists()


@pytest.mark.parametrize("stdin", ["{json rotto", "[]"])
def test_input_invalido_esce_zero_senza_rumore(stdin, monkeypatch, capsys):
    from starkeno import hook_inizio_sessione

    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))

    assert hook_inizio_sessione.main() == 0
    assert capsys.readouterr() == ("", "")


def test_errore_di_lettura_esce_zero_senza_rumore(monkeypatch, tmp_path, capsys):
    from starkeno import hook_inizio_sessione

    percorso = tmp_path / "esiste.db"
    sqlite3.connect(percorso).close()
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr(sys, "stdin", _stdin(_payload()))
    monkeypatch.setattr(
        db, "make_readonly_session_factory",
        lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert hook_inizio_sessione.main() == 0
    assert capsys.readouterr() == ("", "")


def test_lanciato_per_percorso_da_cwd_estraneo_restituisce_contesto(tmp_path):
    from starkeno import hook_inizio_sessione

    radice = Path(hook_inizio_sessione.__file__).resolve().parent.parent
    percorso_db = tmp_path / "dati" / "starkeno.db"
    estranea = tmp_path / "un" / "altro" / "progetto"
    estranea.mkdir(parents=True)
    ambiente = dict(os.environ, STARKENO_DB_PATH=str(percorso_db))
    ambiente.pop("PYTHONPATH", None)

    esito = subprocess.run(
        [sys.executable, str(radice / "starkeno" / "hook_inizio_sessione.py")],
        input=json.dumps(_payload()), capture_output=True, text=True,
        cwd=str(estranea), env=ambiente, timeout=30,
    )

    assert esito.returncode == 0
    assert esito.stderr == ""
    assert json.loads(esito.stdout)["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert not percorso_db.exists()


# ================================ la riga proattiva: un fatto, non un giudizio
#
# `esegui` parlava SOLO a database vuoto e poi taceva per sempre: si zittiva esattamente
# quando cominciava ad avere qualcosa da dire. Adesso, dopo una pausa, emette una riga
# con un fatto misurato sugli ultimi 7 giorni.
#
# NON e' un allarme e non ha una soglia di allarme: `config.py` dichiara in testa che le
# sue soglie non sono tarate sui dati reali, e un avviso su una soglia non tarata insegna
# solo a ignorare gli avvisi. Una quota misurata invece e' vera comunque.


def _azione(sessione, *, quando, riletture=0, indice=0):
    """Una riga scomposta per intero: e' l'unica che entra nelle classi del conto."""
    sessione.add(AgentAction(
        project="progetto", action="leggi", model_used="gpt-5",
        tokens_used=1000, cache_read_tokens=riletture, cache_write_tokens=0,
        output_tokens=1000 - riletture, timestamp=quando,
        session_id="sessione", message_id="messaggio-%d" % indice,
    ))


def _popola(session_factory, *, quante, quando, riletture):
    with session_factory() as sessione:
        for indice in range(quante):
            _azione(sessione, quando=quando, riletture=riletture, indice=indice)
        sessione.commit()


def _esegui(monkeypatch, session_factory, capsys, *, adesso):
    from starkeno import hook_inizio_sessione

    monkeypatch.setenv("STARKENO_DB_PATH", _percorso_db(session_factory))
    monkeypatch.setattr(sys, "stdin", _stdin(_payload()))
    monkeypatch.setattr(hook_inizio_sessione, "_adesso", lambda: adesso)
    assert hook_inizio_sessione.main() == 0
    uscita, errore = capsys.readouterr()
    assert errore == "", "l'invariante 12 vieta stderr"
    return uscita


def test_dopo_una_pausa_dichiara_la_quota_di_rilettura(
        monkeypatch, session_factory, capsys):
    """LA regressione: con storico l'hook taceva, per sempre. Qui c'e' storia e una
    pausa di 10 ore, quindi deve uscire una riga con una percentuale.

    La percentuale ESATTA non si asserisce qui ed e' deliberato: le riletture nel conto
    sono PESATE — una rilettura costa una frazione di un token nuovo — quindi ricavarla
    a mano significherebbe riscrivere il modello dei pesi dentro un test, cioe' la
    seconda implementazione che questo progetto ha gia' pagato due volte. Il numero lo
    fissa il test differenziale contro `calcola_conto`."""
    from datetime import datetime, timedelta, timezone

    adesso = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    _popola(session_factory, quante=200, quando=adesso - timedelta(hours=10),
            riletture=400)

    uscita = _esegui(monkeypatch, session_factory, capsys, adesso=adesso)

    contesto = json.loads(uscita)["hookSpecificOutput"]["additionalContext"]
    assert "%" in contesto and "rilettura di contesto" in contesto, contesto
    assert "una sola breve riga" in contesto, "deve restare UNA riga, non un rapporto"


def test_senza_pausa_tace(monkeypatch, session_factory, capsys):
    """Il limite al rumore, ed e' senza stato: «prima sessione dopo una pausa» si deduce
    dall'ultima riga raccolta, cosi' l'hook resta in sola lettura come e' sempre stato.
    Riavviare l'agente dentro la stessa giornata di lavoro non fa ripetere la riga."""
    from datetime import datetime, timedelta, timezone

    adesso = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    _popola(session_factory, quante=200, quando=adesso - timedelta(minutes=10),
            riletture=400)

    assert _esegui(monkeypatch, session_factory, capsys, adesso=adesso) == ""


def test_sotto_il_minimo_di_dati_tace(monkeypatch, session_factory, capsys):
    """Con pochissime chiamate una sola sessione pesante domina la percentuale, e la
    riga direbbe qualcosa di vero sull'aritmetica e falso sul modo di lavorare."""
    from datetime import datetime, timedelta, timezone

    adesso = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    _popola(session_factory, quante=3, quando=adesso - timedelta(hours=10),
            riletture=400)

    assert _esegui(monkeypatch, session_factory, capsys, adesso=adesso) == ""


def test_la_quota_e_quella_del_conto_non_un_secondo_calcolo(
        monkeypatch, session_factory, capsys):
    """Questo progetto ha gia' pagato due volte per due implementazioni della stessa
    regola che divergono (`effective_tokens`, il parsing di `model_map`). La riga deve
    venire dalla stessa autorita' del conto, quindi il numero dell'hook e quello
    ricalcolato con `calcola_conto` sulle stesse righe devono coincidere."""
    from datetime import datetime, timedelta, timezone

    from starkeno import db
    from starkeno.config import MAX_PLAUSIBLE_TOKENS, TOKEN_COST_WEIGHTS
    from starkeno.conto import calcola_conto
    from starkeno.report_conto import FusoLocaleSistema

    adesso = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    _popola(session_factory, quante=120, quando=adesso - timedelta(hours=10),
            riletture=137)

    uscita = _esegui(monkeypatch, session_factory, capsys, adesso=adesso)

    with session_factory() as sessione:
        azioni = db.get_azioni_conto(sessione)
    conto = calcola_conto(azioni, fuso=FusoLocaleSistema(), now=adesso,
                          weights=TOKEN_COST_WEIGHTS,
                          max_plausible=MAX_PLAUSIBLE_TOKENS)
    totale = sum(giorno.totale_pesato for giorno in conto.ritmo)
    riletture = sum(giorno.riletture_pesate for giorno in conto.ritmo)
    atteso = "%d%%" % round(100 * riletture / totale)

    contesto = json.loads(uscita)["hookSpecificOutput"]["additionalContext"]
    assert atteso in contesto, "%r non contiene %r" % (contesto, atteso)


def test_la_riga_proattiva_non_crea_ne_tocca_il_database(
        monkeypatch, session_factory, capsys):
    """L'hook e' in sola lettura per progetto: qui c'e' storia, quindi percorre il ramo
    nuovo, e deve comunque non scrivere una riga."""
    from datetime import datetime, timedelta, timezone

    adesso = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    _popola(session_factory, quante=200, quando=adesso - timedelta(hours=10),
            riletture=400)
    percorso = _percorso_db(session_factory)
    prima = os.path.getmtime(percorso)

    _esegui(monkeypatch, session_factory, capsys, adesso=adesso)

    # `closing` E `conn`: il solo `with sqlite3.connect(...)` governa la transazione e
    # lascia la connessione aperta (invariante 14).
    with closing(sqlite3.connect(percorso)) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 200
    assert os.path.getmtime(percorso) == prima, "il database e' stato toccato"


def test_la_risposta_e_solo_ascii():
    """`ensure_ascii=False` metteva le virgolette basse grezze nel JSON. Se lo stdout
    dell'hook non sa rappresentarle, `print` solleva, `main` assorbe come deve, e si
    perde TUTTO il contesto senza un segnale — la forma di difetto che questo progetto
    continua a pagare. Le due rese JSON sono equivalenti per qualunque parser, quindi
    l'escape non costa niente e toglie il caso."""
    from starkeno import hook_inizio_sessione

    uscita = hook_inizio_sessione.risposta_contesto(hook_inizio_sessione.BENVENUTO)

    assert uscita.isascii(), "una console con codepage ristretta perderebbe il contesto"
    uscita.encode("ascii")
