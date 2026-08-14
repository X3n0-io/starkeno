import sqlite3
from dataclasses import replace
from datetime import datetime, timezone, tzinfo
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from starkeno import db, report_conto
from starkeno.conto import calcola_conto
from starkeno.db import AgentAction
from starkeno.report_conto import apri_report, genera_report, main, renderizza_html


ORA = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)


def _percorso_db(session_factory) -> str:
    return session_factory.kw["bind"].url.database


def _scrivi_azione(session_factory, **sovrascrivi) -> None:
    valori = {
        "project": "progetto", "action": "leggi", "model_used": "modello",
        "tokens_used": 1_700, "timestamp": ORA, "cache_read_tokens": 1_000,
        "cache_write_tokens": 200, "output_tokens": 100, "session_id": "sessione",
        "message_id": "messaggio", "azioni_nella_chiamata": 3,
        "skill": "analisi", "plugin": "plugin", "mcp_server": "server",
        "is_sidechain": 1, "esito_noto": 0,
    }
    valori.update(sovrascrivi)
    with session_factory() as sessione:
        sessione.add(AgentAction(**valori))
        sessione.commit()


def test_genera_html_statico_con_conto_completo_e_valori_escapati(
        tmp_path, session_factory):
    pericoloso = '<script data-x="1">alert(1)</script>'
    _scrivi_azione(
        session_factory, project=pericoloso, model_used=pericoloso,
        session_id=pericoloso, skill=pericoloso, plugin=pericoloso,
        mcp_server=pericoloso,
    )
    destinazione = tmp_path / "cartella" / "conto.html"

    generato = genera_report(
        _percorso_db(session_factory), destinazione, fuso=timezone.utc, now=ORA,
    )
    contenuto = generato.read_text(encoding="utf-8")

    assert generato == destinazione
    assert pericoloso not in contenuto
    assert "&lt;script data-x=&quot;1&quot;&gt;alert(1)&lt;/script&gt;" in contenuto
    assert "3 azioni in 1 chiamata" in contenuto
    assert "Costo di lavoro" in contenuto
    assert "Costo di caricamento" in contenuto
    assert "Costo di rilettura" in contenuto
    assert "Esiti ignoti" in contenuto
    assert "Righe non classificabili" in contenuto
    assert "Per progetto" in contenuto
    assert "Per modello" in contenuto
    assert "Per sessione" in contenuto
    assert "Ritmo locale degli ultimi 7 giorni" in contenuto
    assert "Le etichette si sovrappongono" in contenuto
    assert "Tetto non configurato" in contenuto
    assert "StarkEno misura quello che spendi, non quello che ottieni." in contenuto


def test_database_assente_produce_conto_vuoto_senza_crearlo(tmp_path):
    database = tmp_path / "dati" / "manca.db"
    destinazione = tmp_path / "conto.html"

    genera_report(database, destinazione, fuso=timezone.utc, now=ORA)

    assert not database.exists()
    contenuto = destinazione.read_text(encoding="utf-8")
    assert "0 azioni in 0 chiamate" in contenuto
    assert "Nessun dato disponibile" in contenuto


def test_database_esistente_senza_schema_non_viene_inizializzato(tmp_path):
    database = tmp_path / "vuoto.db"
    sqlite3.connect(database).close()

    with pytest.raises(OperationalError):
        genera_report(database, tmp_path / "conto.html", fuso=timezone.utc, now=ORA)

    with sqlite3.connect(database) as connessione:
        tabelle = connessione.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    assert tabelle == []


def test_output_che_risolve_al_database_viene_rifiutato_senza_corromperlo(
        tmp_path, session_factory):
    _scrivi_azione(session_factory)
    database = Path(_percorso_db(session_factory))
    prima = database.read_bytes()
    alias_testuale = database.parent / "." / database.name

    with pytest.raises(ValueError, match="database"):
        genera_report(database, alias_testuale, fuso=timezone.utc, now=ORA)

    assert database.read_bytes() == prima
    with session_factory() as sessione:
        assert sessione.query(AgentAction).count() == 1


def test_output_symlink_al_database_viene_rifiutato_quando_supportato(
        tmp_path, session_factory):
    _scrivi_azione(session_factory)
    database = Path(_percorso_db(session_factory))
    collegamento = tmp_path / "conto.html"
    try:
        collegamento.symlink_to(database)
    except OSError as errore:
        pytest.skip(f"symlink non disponibili: {errore}")
    prima = database.read_bytes()

    with pytest.raises(ValueError, match="database"):
        genera_report(database, collegamento, fuso=timezone.utc, now=ORA)

    assert database.read_bytes() == prima


def test_percorso_database_esistente_ma_directory_viene_rifiutato(tmp_path):
    database = tmp_path / "directory.db"
    database.mkdir()

    with pytest.raises(ValueError, match="file"):
        genera_report(database, tmp_path / "conto.html", fuso=timezone.utc, now=ORA)


def test_factory_di_lettura_rifiuta_le_scritture(session_factory):
    _scrivi_azione(session_factory)
    database = _percorso_db(session_factory)
    session_factory.kw["bind"].dispose()

    fabbrica = db.make_readonly_session_factory(database)
    try:
        with fabbrica() as sessione:
            assert sessione.query(AgentAction).count() == 1
            with pytest.raises(OperationalError, match="readonly"):
                sessione.execute(text("DELETE FROM agent_actions"))
                sessione.commit()
    finally:
        fabbrica.kw["bind"].dispose()


def test_report_legge_senza_modificare_il_database(session_factory, tmp_path):
    _scrivi_azione(session_factory)
    database = Path(_percorso_db(session_factory))
    session_factory.kw["bind"].dispose()
    prima = database.read_bytes()

    genera_report(database, tmp_path / "conto.html", fuso=timezone.utc, now=ORA)

    assert database.read_bytes() == prima


def test_apri_report_usa_un_uri_file_assoluto(tmp_path, monkeypatch):
    percorso = tmp_path / "conto con spazi.html"
    percorso.write_text("ok", encoding="utf-8")
    aperti = []
    monkeypatch.setattr("webbrowser.open", aperti.append)

    apri_report(percorso)

    assert aperti == [percorso.resolve().as_uri()]


def test_cli_no_open_scrive_il_report_senza_aprire_browser(tmp_path, monkeypatch):
    database = tmp_path / "manca.db"
    destinazione = tmp_path / "conto.html"
    monkeypatch.setenv("STARKENO_DB_PATH", str(database))

    def apertura_vietata(_percorso):
        raise AssertionError("--no-open non deve aprire il browser")

    monkeypatch.setattr("starkeno.report_conto.apri_report", apertura_vietata)
    fusi = []
    calcola_vero = report_conto.calcola_conto

    def registra_fuso(azioni, **argomenti):
        fusi.append(argomenti["fuso"])
        return calcola_vero(azioni, **argomenti)

    monkeypatch.setattr(report_conto, "calcola_conto", registra_fuso)

    assert main(["--output", str(destinazione), "--no-open"]) == 0
    assert destinazione.exists()
    assert not database.exists()
    assert len(fusi) == 1
    assert isinstance(fusi[0], tzinfo)


def test_renderer_non_perde_precisione_sugli_interi_grandi():
    vuoto = calcola_conto(
        (), fuso=timezone.utc, now=ORA,
        weights={"input": 1, "cache_read": 0.1, "cache_write": 1.25, "output": 5},
        max_plausible=2_000_000,
    )
    intero = 2 ** 53 + 1

    contenuto = renderizza_html(replace(vuoto, azioni=intero))

    assert "9.007.199.254.740.993 azioni" in contenuto


def test_report_has_no_remote_assets(tmp_path):
    output = tmp_path / "conto.html"

    genera_report(
        tmp_path / "assente.db", output, fuso=timezone.utc, now=ORA,
    )
    html = output.read_text(encoding="utf-8")

    assert "http://" not in html and "https://" not in html
