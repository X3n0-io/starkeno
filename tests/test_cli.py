import json
import subprocess
import sys
from pathlib import Path

import pytest

from starkeno.diagnostica import Controllo
from starkeno.cli import main


def _database_con_ultima_riga(path: Path, quando: str) -> Path:
    """Un database allo schema di produzione la cui riga piu' recente e' `quando`."""
    import sqlite3
    from contextlib import closing

    from alembic import command

    from starkeno.migrazioni import configurazione_alembic

    path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(configurazione_alembic(path), "head")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO agent_actions"
            "(project, action, model_used, tokens_used, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ("progetto", "read:file.py", "modello-finto", 100, quando),
        )
    return path


def test_il_doctor_dichiara_uno_storico_piu_recente_del_canonico(tmp_path, monkeypatch):
    """LA regressione misurata il 19/08/2026, costata quattro giorni e 465 righe.

    Un hook instradato male raccoglie per INTERO, ma in un percorso che `report` e
    `consuntivo` non guardano. Il canonico resta integro, quindi il controllo rispondeva
    `ok` e non c'era nient'altro che potesse accorgersene: l'hook e' fail-open e muto per
    l'invariante 12, e la raccolta guarda solo il canonico.

    Uno storico con righe PIU' RECENTI del canonico e' la firma di quel guasto, e i dati
    per nominarla erano gia' tutti in `CandidatoDatabase.ultimo_evento`.
    """
    from starkeno import percorsi
    from starkeno.cli import _controllo_inventario

    storica = tmp_path / "AppData" / "Local" / "StarkEno"
    monkeypatch.setattr(percorsi, "cartella_dati_windows_storica", lambda: storica)
    canonico = _database_con_ultima_riga(tmp_path / "dati" / "starkeno.db",
                                         "2026-08-17 08:32:55.000000")
    _database_con_ultima_riga(storica / "starkeno.db", "2026-08-19 07:47:01.000000")

    controllo = _controllo_inventario(canonico, tmp_path / "repo")

    assert controllo.stato == "attenzione", (
        "un canonico integro non basta: la raccolta sta scrivendo altrove"
    )
    assert str(storica) in controllo.dettaglio, "non dice DOVE stanno finendo le righe"


def test_il_doctor_non_allarma_per_uno_storico_piu_vecchio(tmp_path, monkeypatch):
    """Il rovescio, e non e' pignoleria: uno storico VECCHIO e' il caso normale di chi
    ha aggiornato, ed e' la ragione per cui l'inventario esiste. Un controllo che
    dicesse `attenzione` per ogni storico integro sarebbe rumore a ogni `doctor`, e
    l'utente imparerebbe a ignorarlo proprio prima del giorno in cui conta."""
    from starkeno import percorsi
    from starkeno.cli import _controllo_inventario

    storica = tmp_path / "AppData" / "Local" / "StarkEno"
    monkeypatch.setattr(percorsi, "cartella_dati_windows_storica", lambda: storica)
    canonico = _database_con_ultima_riga(tmp_path / "dati" / "starkeno.db",
                                         "2026-08-19 07:47:01.000000")
    _database_con_ultima_riga(storica / "starkeno.db", "2026-08-14 10:00:00.000000")

    controllo = _controllo_inventario(canonico, tmp_path / "repo")

    assert controllo.stato == "ok", "lo storico vecchio e' il caso normale, non un guasto"


def test_module_cli_delegates_report(tmp_path, monkeypatch):
    visti = {}

    def report_finto(args):
        visti["args"] = args
        return 0

    monkeypatch.setattr("starkeno.cli.report_conto.main", report_finto)

    assert main([
        "report", "--output", str(tmp_path / "conto.html"), "--no-open",
    ]) == 0
    assert visti["args"][-1] == "--no-open"


def test_module_cli_delega_preflight_prima_del_doctor(monkeypatch):
    visti = {}

    def preflight_finto(args):
        visti["args"] = args
        return 7

    monkeypatch.setattr("starkeno.preflight_cli.main", preflight_finto)
    monkeypatch.setattr(
        "starkeno.cli._diagnosi_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("doctor eseguito")),
    )

    assert main(["preflight", "draft", "--input-format", "json"]) == 7
    assert visti["args"] == ["draft", "--input-format", "json"]


def test_importare_la_cli_non_carica_il_core_preflight():
    """L'import top-level di preflight_cli trascinava pydantic e PyYAML in ogni
    invocazione di doctor e report, che non ne hanno bisogno."""
    codice = (
        "import sys, starkeno.cli;"
        "sys.exit(1 if 'starkeno.preflight_cli' in sys.modules else 0)"
    )

    esito = subprocess.run([sys.executable, "-c", codice], capture_output=True)

    assert esito.returncode == 0, esito.stderr.decode("utf-8", "replace")


def test_repair_requires_the_explicit_confirmation(tmp_path):
    with pytest.raises(SystemExit) as errore:
        main(["doctor", "--repair-from", str(tmp_path / "storico.db")])

    assert errore.value.code == 2


def test_doctor_json_is_machine_readable_and_fails_on_real_errors(
    monkeypatch, capsys,
):
    monkeypatch.setattr(
        "starkeno.cli._diagnosi_runtime",
        lambda: (
            Controllo("python", "ok", "Python supportato", {"versione": "3.12"}),
            Controllo("database", "errore", "database_assente"),
        ),
    )

    assert main(["doctor", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["codice"] == "python"
    assert payload[1] == {
        "codice": "database", "stato": "errore",
        "dettaglio": "database_assente", "dati": {},
    }


def test_confirmed_repair_uses_the_canonical_destination_then_reruns_doctor(
    tmp_path, monkeypatch, capsys,
):
    sorgente = tmp_path / "storico.db"
    destinazione = tmp_path / "dati" / "starkeno.db"
    chiamate = []

    def recupero_finto(source, destination, **kwargs):
        chiamate.append((Path(source), Path(destination), kwargs))

    monkeypatch.setenv("STARKENO_DB_PATH", str(destinazione))
    monkeypatch.setattr("starkeno.cli.recupera_database", recupero_finto)
    monkeypatch.setattr(
        "starkeno.cli._diagnosi_runtime",
        lambda: (Controllo("database", "ok", "database integro"),),
    )

    assert main([
        "doctor", "--repair-from", str(sorgente), "--confirm-repair", "--json",
    ]) == 0
    assert chiamate[0][:2] == (sorgente, destinazione)
    assert callable(chiamate[0][2]["migra"])
    assert json.loads(capsys.readouterr().out)[0]["stato"] == "ok"


# =================================================================== starkeno consuntivo
#
# Il comando guarda il confronto stima/osservato senza passare dall'agente: sola lettura
# (`db.make_readonly_session_factory`), mai un `_impl` MCP. Le esecuzioni si scrivono qui
# direttamente con `db.apri_esecuzione`, non tramite `starkeno.mcp_server`: quel modulo
# importa l'SDK MCP a livello di modulo e `cli.py` non deve trascinarlo dentro un comando
# da terminale — questi test restano rappresentativi solo se rispettano la stessa regola.


def _testo_analisi_valida() -> str:
    """Un'analisi Preflight valida (Blueprint + simulazione), come testo JSON pronto per
    `blueprint_runs.analysis_json`. Stessa costruzione di `_analisi_json` in
    `test_mcp_server.py`, ma restituisce testo invece di scrivere un file: la CLI legge
    `analysis_json` dal database, non da un percorso su disco."""
    from starkeno.preflight_report import PreflightAnalysis, render_analysis
    from starkeno.preflight_schema import Blueprint
    from starkeno.preflight_simulate import simulate_blueprint

    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "preflight" / "minimal.json").read_text(
            encoding="utf-8"
        )
    )
    payload["confirmed"] = True
    blueprint = Blueprint.model_validate(payload)
    analisi = PreflightAnalysis(
        blueprint=blueprint, findings=(),
        simulation=simulate_blueprint(blueprint, samples=8, seed=7), source_path=None,
    )
    return render_analysis(analisi, format="json")


def _apri_esecuzione_diretta(percorso_db, *, run_key, project="progetto",
                             analysis_json=None) -> str:
    """Scrive un'esecuzione APERTA direttamente nel database, con gli strumenti di
    scrittura normali (`db.apri_esecuzione`) e non con un `_impl` MCP, e chiude e
    dispone la propria connessione prima di restituire il controllo: la CLI la legge
    poi da una sessione sola-lettura fresca, mai da una scrittura ancora in sospeso
    (stesso ordine di `test_report_conto.py`)."""
    from datetime import datetime, timezone

    from starkeno import db

    fabbrica = db.make_session_factory(str(percorso_db))
    sessione = fabbrica()
    try:
        db.apri_esecuzione(
            sessione, run_key=run_key, project=project,
            blueprint_hash="hash-test",
            analysis_json=(
                analysis_json if analysis_json is not None else _testo_analisi_valida()
            ),
            model_map_json="{}", started_at=datetime.now(timezone.utc),
        )
    finally:
        sessione.close()
        fabbrica.kw["bind"].dispose()
    return run_key


class _StdoutSoloAscii:
    """Sostituto di `sys.stdout` che solleva `UnicodeEncodeError` su un carattere
    non-ASCII, come farebbe una console Windows con una codepage legacy (es. cp1252)
    invece di UTF-8.

    Il fallimento e' atomico per costruzione: `.write()` o accoda l'intera stringa o non
    accoda nulla, cosi' il test non dipende dal buffering interno di
    `io.TextIOWrapper`, che non garantisce la stessa atomicita'."""

    def __init__(self):
        self.encoding = "ascii"
        self._righe = []

    def write(self, testo):
        testo.encode("ascii")  # solleva UnicodeEncodeError sui caratteri non-ASCII
        self._righe.append(testo)
        return len(testo)

    def flush(self):
        pass

    def testo_scritto(self) -> str:
        return "".join(self._righe)


def test_consuntivo_elenco_su_database_vuoto(tmp_path, monkeypatch, capsys):
    """Nessuna esecuzione non e' un errore: e' un'informazione."""
    from starkeno import cli
    from starkeno.hook_ingestione import prepara_database

    percorso = tmp_path / "vuoto.db"
    prepara_database(str(percorso), silenzioso=True)
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))

    codice = cli.main(["consuntivo", "--elenco"])

    assert codice == 0
    assert "Nessuna esecuzione" in capsys.readouterr().out


def test_consuntivo_su_chiave_sconosciuta_esce_2(tmp_path, monkeypatch, capsys):
    from starkeno import cli
    from starkeno.hook_ingestione import prepara_database

    percorso = tmp_path / "vuoto.db"
    prepara_database(str(percorso), silenzioso=True)
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))

    codice = cli.main(["consuntivo", "--run", "mai-vista"])

    assert codice == 2
    assert "mai-vista" in capsys.readouterr().err


def test_consuntivo_senza_run_ne_elenco_esce_2(capsys):
    """Ne' l'uno ne' l'altro modo d'uso: un errore d'uso dichiarato, non un crash e non
    un no-op silenzioso. Non tocca il database: non serve nemmeno prepararne uno."""
    from starkeno import cli

    codice = cli.main(["consuntivo"])

    assert codice == 2
    assert "--run" in capsys.readouterr().err


def test_consuntivo_su_analisi_corrotta_esce_2_senza_sollevare(
    tmp_path, monkeypatch, capsys,
):
    """La regressione che questo task esiste per non reintrodurre: il brief originale
    indicizzava `payload["blueprint"]` alla cieca, e un `analysis_json` con 'simulation'
    ma senza 'blueprint' (dato vero: puo' capitare da uno storico scritto prima che la
    validazione esistesse) sollevava `KeyError` invece di tornare un errore dichiarato.
    Qui l'esecuzione e' scritta direttamente nel database, scavalcando ogni validazione
    a monte, cosi' il test riproduce un'analisi davvero corrotta e non una che i tool
    MCP avrebbero gia' rifiutato. Deve uscire non-zero, mai sollevare."""
    from starkeno import cli
    from starkeno.hook_ingestione import prepara_database

    percorso = tmp_path / "corrotta.db"
    prepara_database(str(percorso), silenzioso=True)
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    _apri_esecuzione_diretta(
        percorso, run_key="run-corrotta",
        analysis_json=json.dumps({"simulation": {}}),
    )

    codice = cli.main(["consuntivo", "--run", "run-corrotta"])

    catturato = capsys.readouterr()
    assert codice == 2
    assert "run-corrotta" in catturato.err
    assert "blueprint" in catturato.err.lower()


def test_consuntivo_elenco_con_esecuzioni_le_elenca(tmp_path, monkeypatch, capsys):
    from starkeno import cli
    from starkeno.hook_ingestione import prepara_database

    percorso = tmp_path / "con_dati.db"
    prepara_database(str(percorso), silenzioso=True)
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    _apri_esecuzione_diretta(percorso, run_key="run-elenco", project="progetto-x")

    codice = cli.main(["consuntivo", "--elenco"])

    catturato = capsys.readouterr()
    assert codice == 0
    assert "run-elenco" in catturato.out
    assert "progetto-x" in catturato.out


def test_consuntivo_run_json_produce_json_valido(tmp_path, monkeypatch, capsys):
    """`--json` deve restare macchina-leggibile anche su un'esecuzione ancora aperta,
    dove il confronto non arriva a calcolare nodi o moneta."""
    from starkeno import cli
    from starkeno.hook_ingestione import prepara_database

    percorso = tmp_path / "json.db"
    prepara_database(str(percorso), silenzioso=True)
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    _apri_esecuzione_diretta(percorso, run_key="run-json")

    codice = cli.main(["consuntivo", "--run", "run-json", "--json"])

    catturato = capsys.readouterr()
    assert codice == 0
    payload = json.loads(catturato.out)
    assert payload["run_key"] == "run-json"
    assert payload["stato"] == "aperta"


def test_consuntivo_su_codepage_console_limitata_non_solleva(tmp_path, monkeypatch):
    """`consuntivo.rendi_testo` contiene em-dash e freccia: su una console con una
    codepage che non li rappresenta (qui simulata con ascii puro) il comando non deve
    sollevare `UnicodeEncodeError` mentre stampa il proprio output."""
    from starkeno import cli
    from starkeno.hook_ingestione import prepara_database

    percorso = tmp_path / "utf8.db"
    prepara_database(str(percorso), silenzioso=True)
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))
    _apri_esecuzione_diretta(percorso, run_key="run-utf8")
    finto_stdout = _StdoutSoloAscii()
    monkeypatch.setattr(sys, "stdout", finto_stdout)

    codice = cli.main(["consuntivo", "--run", "run-utf8"])

    assert codice == 0
    assert "Consuntivo" in finto_stdout.testo_scritto()


def test_consuntivo_non_trascina_mcp_server(tmp_path):
    """`cli.py` non deve importare `mcp_server`: quel modulo carica l'SDK MCP a livello
    di modulo, e un comando da terminale non deve trascinarlo dentro (stesso spirito di
    `test_importare_la_cli_non_carica_il_core_preflight`, ma end-to-end su un'esecuzione
    vera del comando, non solo sull'import di `cli.py`)."""
    from starkeno.hook_ingestione import prepara_database

    percorso = tmp_path / "vuoto.db"
    prepara_database(str(percorso), silenzioso=True)

    codice = (
        "import sys, os;"
        "os.environ['STARKENO_DB_PATH'] = sys.argv[1];"
        "from starkeno import cli;"
        "cli.main(['consuntivo', '--elenco']);"
        "sys.exit(1 if 'starkeno.mcp_server' in sys.modules else 0)"
    )
    esito = subprocess.run(
        [sys.executable, "-c", codice, str(percorso)], capture_output=True
    )

    assert esito.returncode == 0, esito.stderr.decode("utf-8", "replace")


def test_consuntivo_su_database_assente_dichiara_e_esce_2(tmp_path, monkeypatch, capsys):
    """La regressione trovata dalla revisione finale: `make_readonly_session_factory`
    apre SQLite con `mode=ro`, che FALLISCE invece di creare. Su un'installazione fresca
    — lo stato di ogni lettore al giorno uno — il comando cadeva con
    `sqlalchemy.exc.OperationalError: unable to open database file` fino al terminale.
    Il precedente sta gia' in `report_conto.genera_report`, che guarda `database.exists()`
    prima di costruire la stessa fabbrica."""
    from starkeno import cli

    percorso = tmp_path / "mai-esistito.db"
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))

    codice = cli.main(["consuntivo", "--elenco"])

    catturato = capsys.readouterr()
    assert codice == 2
    assert "mai-esistito.db" in catturato.err
    assert "hook" in catturato.err.lower()
    assert "Traceback" not in catturato.err


def test_consuntivo_su_schema_precedente_alla_migrazione_dichiara_e_esce_2(
    tmp_path, monkeypatch, capsys,
):
    """Il secondo modo di cadere: un database creato prima della migrazione `0006` non
    ha `blueprint_runs`, e la lettura sollevava `no such table: blueprint_runs`. E' lo
    stato di ogni utente esistente finche' il suo prossimo hook di fine turno non applica
    `upgrade_head`. Il file qui e' un database SQLite vero e vuoto: nessuna tabella di
    StarkEno, quindi la stessa condizione dello schema vecchio."""
    import sqlite3

    from starkeno import cli

    percorso = tmp_path / "vecchio.db"
    connessione = sqlite3.connect(str(percorso))
    try:
        connessione.execute("CREATE TABLE segnaposto (id INTEGER PRIMARY KEY)")
        connessione.commit()
    finally:
        connessione.close()
    monkeypatch.setenv("STARKENO_DB_PATH", str(percorso))

    codice = cli.main(["consuntivo", "--elenco"])

    catturato = capsys.readouterr()
    assert codice == 2
    assert "blueprint_runs" in catturato.err
    assert "schema" in catturato.err.lower()
    assert "Traceback" not in catturato.err
