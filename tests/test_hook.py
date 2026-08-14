"""L'hook non deve MAI rompere la sessione di chi lo usa.

E' l'invariante 4 applicata a casa d'altri: qui il costo di un fallimento non lo paga
StarkEno, lo paga il lavoro dell'utente. Uscita 0 sempre, niente rumore su stderr,
nessuna eccezione che risale.
"""
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from starkeno import hook_ingestione


@pytest.fixture(autouse=True)
def niente_traslochi_veri(monkeypatch):
    """Neutralizza anche una regressione che riattivasse il recupero automatico."""
    from starkeno import trasloco
    monkeypatch.setattr(trasloco, "trasloca_se_serve", lambda *a, **k: None)


def _payload(tmp_path, righe):
    percorso = tmp_path / "transcript.jsonl"
    percorso.write_text("\n".join(righe), encoding="utf-8")
    return {"transcript_path": str(percorso), "session_id": "s1", "cwd": str(tmp_path)}


def _riga(message_id="m1"):
    return json.dumps({
        "sessionId": "s1", "timestamp": "2026-08-07T10:00:00.000Z", "cwd": "/x/progetto",
        "message": {"id": message_id, "model": "claude-opus-5",
                    "usage": {"input_tokens": 10, "cache_read_input_tokens": 900,
                              "output_tokens": 5},
                    "content": [{"type": "tool_use", "id": "t1", "name": "Read",
                                 "input": {"file_path": "app.py"}}]}})


def test_ingerisce_e_scrive(tmp_path, monkeypatch):
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "db.sqlite"))
    hook_ingestione.prepara_database(str(tmp_path / "db.sqlite"))
    assert hook_ingestione.ingerisci(_payload(tmp_path, [_riga("m1"), _riga("m2")])) == 2


def test_rieseguirlo_non_duplica(tmp_path, monkeypatch):
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "db.sqlite"))
    hook_ingestione.prepara_database(str(tmp_path / "db.sqlite"))
    payload = _payload(tmp_path, [_riga("m1")])
    assert hook_ingestione.ingerisci(payload) == 1
    assert hook_ingestione.ingerisci(payload) == 0


def test_scrive_nel_database_dell_ambiente_non_in_quello_di_produzione(tmp_path, monkeypatch):
    """**Invariante 3, e non e' teorico.**

    `config.DB_PATH` si calcola all'IMPORT del modulo. In produzione l'hook e' un processo
    a se' e i due coincidono; ma dentro la suite `starkeno.config` e' gia' importato,
    quindi leggere quella costante farebbe scrivere l'hook nel database VERO dell'utente,
    e ogni assert su "quante righe ha scritto" passerebbe lo stesso. Qui si guarda dove
    sono finite le righe, non quante ne dice di aver scritto.
    """
    percorso = tmp_path / "db.sqlite"
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    hook_ingestione.prepara_database(str(percorso))

    hook_ingestione.ingerisci(_payload(tmp_path, [_riga("m1")]))

    con = sqlite3.connect(str(percorso))
    assert con.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 1
    con.close()


def test_il_primo_turno_su_un_installazione_pulita_crea_il_database_e_ingerisce(
        tmp_path, monkeypatch, capsys):
    """**Il difetto piu' grave trovato in questo task, e non c'era nel piano.**

    Su un'installazione pulita la cartella dati non esiste. Senza crearla, la connessione
    fallisce, `main` assorbe l'eccezione — come deve — e l'hook non ingerisce MAI niente,
    per sempre e senza un errore: cioe' il plugin appena installato non funziona e non lo
    dice. Verificato eseguendo l'hook come sottoprocesso prima della correzione: uscita 0,
    stderr vuoto, database mai creato.

    Qui il percorso ha DUE livelli di cartelle mancanti, perche' e' il caso vero: su
    Windows `%LOCALAPPDATA%\\StarkEno` non esiste finche' qualcuno non lo crea.
    """
    percorso = tmp_path / "mai" / "esistito" / "db.sqlite"
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr("sys.stdin", _finto_stdin(_payload(tmp_path, [_riga("m1")])))

    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == "", "le migrazioni non devono farsi sentire"
    assert percorso.exists(), "il database non e' stato creato al primo turno"

    con = sqlite3.connect(str(percorso))
    assert con.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 1
    con.close()


def test_esce_zero_col_database_assente(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "non" / "esiste" / "db.sqlite"))
    monkeypatch.setattr("sys.stdin", _finto_stdin(_payload(tmp_path, [_riga()])))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == "", "niente rumore su stderr"


def test_esce_zero_con_lo_stdin_vuoto(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _finto_stdin_grezzo(""))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == ""


def test_esce_zero_con_lo_stdin_non_json(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _finto_stdin_grezzo("{non e' json"))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == ""


def test_esce_zero_se_il_transcript_non_esiste(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr("sys.stdin", _finto_stdin(
        {"transcript_path": str(tmp_path / "manca.jsonl")}))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == ""


def test_esce_zero_con_lo_schema_vecchio_e_non_scrive(tmp_path, monkeypatch, capsys):
    """`check_or_die` DEVE fallire rumorosamente per un processo che parte. Dentro un
    hook non puo': ucciderebbe la sessione. Silenzioso per l'utente, rumoroso in lettura."""
    percorso = tmp_path / "db.sqlite"
    con = sqlite3.connect(str(percorso))
    con.execute("CREATE TABLE agent_actions (id INTEGER PRIMARY KEY, agent_name TEXT)")
    con.commit()
    con.close()
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr("sys.stdin", _finto_stdin(_payload(tmp_path, [_riga()])))
    assert hook_ingestione.main() == 0
    assert capsys.readouterr().err == ""
    con = sqlite3.connect(str(percorso))
    assert con.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 0
    con.close()


def test_esce_zero_col_database_BLOCCATO_da_un_altro_processo(tmp_path, monkeypatch, capsys):
    """La quarta prova del design: database assente, **bloccato**, o a schema vecchio.

    Uno scrittore che tiene aperta una transazione esclusiva fa scadere il busy timeout.
    L'hook deve rinunciare in silenzio, non far aspettare l'utente e non risalire.

    La DURATA e' asserita, e non e' pedanteria: senza, questo test passerebbe identico
    anche se l'hook usasse il timeout da 30 secondi del demone — cioe' proprio il difetto
    che HOOK_BUSY_TIMEOUT_SECONDS esiste per evitare. Un test che non puo' fallire non
    protegge niente.
    """
    percorso = tmp_path / "db.sqlite"
    hook_ingestione.prepara_database(str(percorso))
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    # Svuota il buffer: `prepara_database` scrive su stderr una riga INFO per revisione,
    # e senza questo l'assert sotto guarderebbe il rumore di Alembic invece di quello
    # dell'hook — fallendo per il motivo sbagliato.
    capsys.readouterr()

    bloccante = sqlite3.connect(str(percorso), timeout=0.1)
    bloccante.execute("BEGIN EXCLUSIVE")
    try:
        monkeypatch.setattr("sys.stdin", _finto_stdin(_payload(tmp_path, [_riga()])))
        inizio = time.monotonic()
        assert hook_ingestione.main() == 0
        durata = time.monotonic() - inizio
        assert capsys.readouterr().err == ""
        assert durata < 10, (
            "l'hook ha aspettato %.1f s su un database occupato: sta usando il timeout "
            "del demone invece del suo" % durata
        )
    finally:
        bloccante.rollback()
        bloccante.close()


def test_l_hook_ha_un_busy_timeout_suo_e_molto_piu_corto():
    """**Difetto trovato scrivendo questo piano.** `SQLITE_BUSY_TIMEOUT_SECONDS` vale
    30 secondi: giusto per un demone che ha tutto il tempo, sbagliato dentro un hook di
    fine turno, dove significherebbe far aspettare l'utente mezzo minuto ogni volta che
    il database e' occupato. E' la forma piu' subdola di «un hook che si pianta blocca
    il turno»: non si pianta, aspetta educatamente, e l'utente disinstalla.

    Due costanti, e l'invariante che le tiene separate.
    """
    from starkeno import config

    assert config.HOOK_BUSY_TIMEOUT_SECONDS <= 3.0
    assert config.HOOK_BUSY_TIMEOUT_SECONDS < config.SQLITE_BUSY_TIMEOUT_SECONDS, (
        "l'hook deve rinunciare molto prima di un processo che ha tempo"
    )


def test_il_timeout_corto_arriva_davvero_alla_connessione(tmp_path, monkeypatch):
    """La costante non basta che esista: dev'essere USATA.

    Senza questo test, `HOOK_BUSY_TIMEOUT_SECONDS` potrebbe restare una costante perfetta
    che non legge nessuno — che e' esattamente com'era la prima stesura dell'hook.
    """
    from starkeno import config, db

    visti = {}
    vera = db.make_session_factory

    def spia(percorso, busy_timeout=None):
        visti["busy_timeout"] = busy_timeout
        return vera(percorso, busy_timeout=busy_timeout)

    percorso = tmp_path / "db.sqlite"
    hook_ingestione.prepara_database(str(percorso))
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    monkeypatch.setattr(db, "make_session_factory", spia)

    hook_ingestione.ingerisci(_payload(tmp_path, [_riga("m1")]))

    assert visti["busy_timeout"] == config.HOOK_BUSY_TIMEOUT_SECONDS


def test_main_non_avvia_una_riparazione_dati_automatica(tmp_path, monkeypatch):
    """Il recupero richiede conferma esplicita e non appartiene al percorso fail-open."""
    from starkeno import trasloco

    chiamate = []
    monkeypatch.setattr(trasloco, "trasloca_se_serve",
                        lambda *a, **k: chiamate.append(True))
    monkeypatch.setenv("STARKENO_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr("sys.stdin", _finto_stdin_grezzo("{}"))

    assert hook_ingestione.main() == 0
    assert chiamate == [], "l'hook ha avviato una riparazione senza consenso"


def test_lanciato_come_lo_lancia_codex_da_una_cartella_estranea(tmp_path):
    """**Il difetto del task 9, e nessun test di questo file poteva vederlo.**

    Tutti gli altri chiamano `main()` dentro la suite, dove `starkeno` e' gia' importabile
    perche' `pythonpath = ["."]` sta in `pyproject.toml`. Ma l'hook gira nel progetto
    DELL'UTENTE, con un `cwd` che non ha niente a che vedere con questa cartella, e li'
    quella comodita' non c'e'.

    Le due forme sbagliate, misurate l'08/08/2026 da una cartella estranea:

    | forma | uscita | stderr | righe |
    |---|---|---|---|
    | `python -m starkeno.hook_ingestione` | **1** `ModuleNotFoundError` | rumoroso | 0 |
    | `python <percorso>/hook_ingestione.py` senza bootstrap | **0** | vuoto | **0** |

    La seconda e' la peggiore: gli import pesanti stanno dentro le funzioni, quindi
    l'errore non esce all'avvio ma dentro `main`, che lo assorbe **come deve** — e il
    plugin appena installato non raccoglie niente, per sempre, senza dirlo.

    Per questo il test guarda le RIGHE e non l'uscita: asserire «esce 0» sarebbe passato
    identico su un hook che non ingerisce mai (invariante 13). Serve un sottoprocesso
    vero: dentro il processo di pytest il difetto non esiste.
    """
    import subprocess
    import sys as _sys

    radice = Path(hook_ingestione.__file__).resolve().parent.parent
    percorso_db = tmp_path / "dati" / "db.sqlite"
    estranea = tmp_path / "un" / "altro" / "progetto"
    estranea.mkdir(parents=True)

    ambiente = dict(os.environ, STARKENO_DB_PATH=str(percorso_db))
    # Si toglie ogni scorciatoia ereditata: con PYTHONPATH gia' puntato qui il test
    # passerebbe anche senza il bootstrap, cioe' non proverebbe niente.
    ambiente.pop("PYTHONPATH", None)

    esito = subprocess.run(
        [_sys.executable, str(radice / "starkeno" / "hook_ingestione.py")],
        input=json.dumps(_payload(tmp_path, [_riga("m1"), _riga("m2")])),
        capture_output=True, text=True, cwd=str(estranea), env=ambiente, timeout=120,
    )

    assert esito.returncode == 0, esito.stderr
    assert esito.stderr == "", "niente rumore su stderr: %r" % esito.stderr
    assert percorso_db.exists(), (
        "il database non e' stato creato: l'hook e' uscito 0 senza ingerire niente"
    )
    con = sqlite3.connect(str(percorso_db))
    try:
        assert con.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 2, (
            "l'hook non ha scritto le chiamate: da una cartella estranea `starkeno` non "
            "si importa, e l'eccezione viene assorbita in silenzio"
        )
    finally:
        con.close()


def test_la_dichiarazione_dell_hook_punta_a_un_file_che_esiste():
    """La dichiarazione e il codice possono divergere in silenzio.

    `hooks.json` contiene un percorso in una stringa: nessun import lo controlla, nessun
    test lo esercita, e rinominare il modulo lascerebbe un plugin che si installa, non
    dice niente e non raccoglie niente. `${PLUGIN_ROOT}` e' la radice del plugin,
    che qui e' la radice del repository.
    """
    radice = Path(hook_ingestione.__file__).resolve().parent.parent
    dichiarazione = json.loads(
        (radice / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    (voce,) = dichiarazione["hooks"]["Stop"]
    (comando,) = voce["hooks"]

    assert "async" not in comando, (
        "Codex 0.147 salta gli hook async prima ancora di proporli per la revisione"
    )

    riferimento = comando["command"]
    assert "${PLUGIN_ROOT}" in riferimento, (
        "un percorso assoluto vale solo sulla macchina di chi l'ha scritto"
    )
    relativo = riferimento.split("${PLUGIN_ROOT}")[1].strip('" ').lstrip("/")
    assert (radice / relativo).exists(), (
        "hooks.json lancia %s, che non esiste" % relativo)
    assert relativo == "starkeno/hook_avvia_ingestione.py"


class _Stdin:
    def __init__(self, testo):
        self._testo = testo

    def read(self):
        return self._testo


def _finto_stdin(payload):
    return _Stdin(json.dumps(payload))


def _finto_stdin_grezzo(testo):
    return _Stdin(testo)
