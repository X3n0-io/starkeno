"""Interfaccia a riga di comando supportata di StarkEno."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from starkeno import percorsi, report_conto, risorse
from starkeno.diagnostica import Controllo, esegui_diagnosi
from starkeno.migrazioni import upgrade_head
from starkeno.recupero import inventaria_candidati, recupera_database


def _database_runtime() -> Path:
    return Path(os.environ.get("STARKENO_DB_PATH") or percorsi.percorso_database())


def _codex_root() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _ha_righe_piu_recenti(candidato, riferimento) -> bool:
    """Se `candidato` contiene righe successive all'ultima del `riferimento`.

    E' la firma di una raccolta instradata male: un hook che scrive nel percorso
    sbagliato raccoglie per INTERO, quindi il canonico resta integro e smette
    semplicemente di crescere, mentre l'altro file continua. Misurato il 19/08/2026,
    ed era durato quattro giorni senza che nulla lo dicesse: l'hook e' fail-open e
    muto per l'invariante 12, e il controllo `raccolta` guarda solo il canonico.

    Il confronto e' fra le stringhe come stanno nel database — la rappresentazione
    scritta da `db.UTCDateTime` — ed e' lo stesso che SQLite applica gia' dentro
    `ispeziona_database` per calcolare `MAX(timestamp)`.

    Un candidato senza righe non e' mai piu' recente; un canonico senza righe e'
    superato da chiunque ne abbia.
    """
    if candidato.ultimo_evento is None:
        return False
    if riferimento.ultimo_evento is None:
        return True
    return candidato.ultimo_evento > riferimento.ultimo_evento


def _controllo_inventario(canonico: Path, plugin_root: Path) -> Controllo:
    candidati = inventaria_candidati(
        canonico=canonico, radice_progetto=plugin_root,
    )
    dati = []
    for candidato in candidati:
        voce = asdict(candidato)
        voce["percorso"] = str(candidato.percorso)
        dati.append(voce)

    canonico_candidato = candidati[0]
    recuperabili = [c for c in candidati[1:] if c.integro]
    if canonico_candidato.integro:
        piu_recenti = [c for c in recuperabili
                       if _ha_righe_piu_recenti(c, canonico_candidato)]
        if piu_recenti:
            stato = "attenzione"
            dettaglio = (
                "la raccolta sta scrivendo altrove: %s ha righe piu' recenti del "
                "canonico" % ", ".join(str(c.percorso) for c in piu_recenti)
            )
        else:
            stato, dettaglio = "ok", "database canonico inventariato"
    elif recuperabili:
        stato, dettaglio = "attenzione", "storico recuperabile trovato"
    else:
        stato, dettaglio = "attenzione", "nessuno storico recuperabile"
    return Controllo("inventario_storici", stato, dettaglio, {"candidati": dati})


def _diagnosi_runtime() -> tuple[Controllo, ...]:
    canonico = _database_runtime()
    plugin = risorse.plugin_root()
    controlli = esegui_diagnosi(
        db_path=canonico,
        codex_root=_codex_root(),
        plugin_root=plugin,
        now=datetime.now(timezone.utc),
        home=Path.home(),
    )
    return controlli + (_controllo_inventario(canonico, plugin),)


def _stampa_diagnosi(controlli: tuple[Controllo, ...], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(
            [asdict(controllo) for controllo in controlli],
            ensure_ascii=False,
            indent=2,
        ))
        return
    etichette = {
        "ok": "OK",
        "attenzione": "ATTENZIONE",
        "errore": "ERRORE",
        "manuale": "MANUALE",
    }
    for controllo in controlli:
        print("[%s] %s: %s" % (
            etichette[controllo.stato], controllo.codice, controllo.dettaglio,
        ))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="starkeno")
    comandi = parser.add_subparsers(dest="comando", required=True)
    doctor = comandi.add_parser("doctor", help="diagnostica l'installazione locale")
    doctor.add_argument("--json", action="store_true", dest="json_output")
    doctor.add_argument("--repair-from", type=Path)
    doctor.add_argument("--confirm-repair", action="store_true")
    comandi.add_parser("report", help="genera il conto HTML locale", add_help=False)
    comandi.add_parser("preflight", help="analizza Blueprint locali", add_help=False)
    consuntivo = comandi.add_parser(
        "consuntivo", help="confronta un'esecuzione con il preventivo che la prevedeva")
    consuntivo.add_argument("--run", dest="run_key")
    consuntivo.add_argument("--elenco", action="store_true")
    consuntivo.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    argomenti, residui = parser.parse_known_args(argv)
    if argomenti.comando == "report":
        return report_conto.main(residui)
    if argomenti.comando == "preflight":
        # Import differito: il core Preflight carica pydantic e PyYAML, inutili a
        # doctor e report.
        from starkeno import preflight_cli

        return preflight_cli.main(residui)
    if argomenti.comando == "consuntivo":
        return _esegui_consuntivo(argomenti)

    if residui:
        parser.error("argomenti non riconosciuti: " + " ".join(residui))
    if bool(argomenti.repair_from) != bool(argomenti.confirm_repair):
        parser.error("--repair-from e --confirm-repair devono essere usati insieme")
    if argomenti.repair_from:
        recupera_database(
            argomenti.repair_from,
            _database_runtime(),
            now=datetime.now(timezone.utc),
            migra=lambda path: upgrade_head(path, silenzioso=True),
        )

    controlli = _diagnosi_runtime()
    _stampa_diagnosi(controlli, json_output=argomenti.json_output)
    return 1 if any(c.stato == "errore" for c in controlli) else 0


def _stampa_utf8(testo: str, *, file=None) -> None:
    """Stampa `testo` su `file` (default `sys.stdout`), tollerando una codepage di
    console che non lo rappresenta.

    Il testo reso da `consuntivo.rendi_testo` contiene em-dash, freccia e middle dot
    ('—', '→', '·'), e `project`/`run_key` sono stringhe libere che possono contenere
    qualunque carattere Unicode. Su Windows, quando la codepage attiva della console e'
    una legacy come cp1252 invece di UTF-8, un `print()` diretto su uno di questi valori
    solleva `UnicodeEncodeError` — un comando diagnostico che cade proprio mentre scrive
    il proprio output e' peggio di uno che non gira affatto.

    Si tenta la stampa normale e, solo se fallisce, ci si ri-codifica sostituendo i
    caratteri non rappresentabili invece di lasciar cadere il comando. `file` si
    risolve QUI dentro e non come default dell'argomento: legato in cima al modulo
    punterebbe per sempre allo stdout letto all'avvio, e non a quello che `capsys` (o
    una console reale) sostituisce dopo.
    """
    flusso = file if file is not None else sys.stdout
    try:
        print(testo, file=flusso)
    except UnicodeEncodeError:
        codifica = getattr(flusso, "encoding", None) or "ascii"
        print(
            testo.encode(codifica, errors="replace").decode(codifica, errors="replace"),
            file=flusso,
        )


def _esegui_consuntivo(argomenti) -> int:
    """Il confronto, guardato senza passare dall'agente e senza spenderne i token.

    Import differito come per `preflight`: il confronto carica pydantic, inutile a
    `doctor` e `report`.
    """
    import json as _json

    from starkeno import consuntivo as consuntivo_modulo, db
    from starkeno.config import MAX_PLAUSIBLE_TOKENS, TOKEN_COST_WEIGHTS
    from starkeno.preflight_service import validate_stored_analysis

    if not argomenti.run_key and not argomenti.elenco:
        _stampa_utf8("Errore: serve --run <chiave> oppure --elenco", file=sys.stderr)
        return 2

    # `make_readonly_session_factory` apre SQLite con `mode=ro`: FALLISCE invece di
    # creare, e senza questa guardia un'installazione fresca — lo stato di ogni lettore
    # al giorno uno — riceveva un traceback `OperationalError` al posto di un comando
    # documentato. Stesso precedente di `report_conto.genera_report`, che guarda
    # `database.exists()` prima di costruire la stessa fabbrica. La CLI resta sola
    # lettura: non crea niente e non migra niente, dice solo cosa manca e a chi tocca.
    database = _database_runtime()
    if not database.exists():
        _stampa_utf8(
            "Errore: nessun database in %s.\n"
            "Gli hook non hanno ancora raccolto niente: installa il plugin del tuo "
            "agente, completa qualche turno, poi verifica con `starkeno doctor`. Questo "
            "comando legge soltanto: non crea il database." % database,
            file=sys.stderr,
        )
        return 2

    fabbrica = db.make_readonly_session_factory(str(database))
    sessione = fabbrica()
    try:
        if argomenti.elenco:
            esecuzioni = db.elenca_esecuzioni(sessione)
            if not esecuzioni:
                _stampa_utf8("Nessuna esecuzione registrata.")
                return 0
            for run in esecuzioni:
                _stampa_utf8("%s  %-20s %s  %s" % (
                    run.run_key, run.project, run.started_at.isoformat(),
                    run.ended_at.isoformat() if run.ended_at else "aperta",
                ))
            return 0

        run = db.leggi_esecuzione(sessione, argomenti.run_key)
        if run is None:
            _stampa_utf8(
                "Errore: run_key sconosciuta (%s)" % argomenti.run_key, file=sys.stderr,
            )
            return 2

        # Il preventivo e' conservato verbatim in `analysis_json` (mai ricalcolato: il
        # confronto vale contro cio' che l'agente ha davvero visto). Delega la STESSA
        # validazione usata dai tool MCP dell'esecuzione: un'analisi corrotta — uno
        # storico scritto prima che la validazione esistesse, o un dato manomesso — si
        # dichiara qui come errore leggibile e uscita non-zero, mai come KeyError o
        # pydantic.ValidationError non intercettati fino al terminale dell'utente.
        try:
            _testo, blueprint, simulazione = validate_stored_analysis(run.analysis_json)
        except ValueError as errore:
            _stampa_utf8(
                "Errore: analisi corrotta per l'esecuzione %s: %s"
                % (argomenti.run_key, errore),
                file=sys.stderr,
            )
            return 2

        esecuzione = db.esecuzione_snapshot(run)
        righe = (
            db.righe_nella_finestra(sessione, run.project, run.started_at, run.ended_at)
            if run.ended_at is not None else []
        )
        attribuzione = consuntivo_modulo.attribuisci(
            esecuzione, db.marcatori_di(sessione, run), righe
        )
        # Le guardie di qualita' dati arrivano da qui: `consuntivo.py` e' puro e non legge
        # `config`, come `conto.py`. La porta la legge e la passa (stesso schema di
        # `report_conto.genera_report` verso `calcola_conto`).
        risultato = consuntivo_modulo.costruisci(
            esecuzione, attribuzione, simulazione, blueprint,
            weights=TOKEN_COST_WEIGHTS, max_plausible=MAX_PLAUSIBLE_TOKENS,
        )
        if argomenti.json_output:
            _stampa_utf8(_json.dumps(asdict(risultato), ensure_ascii=False, indent=2,
                                     default=str))
        else:
            _stampa_utf8(consuntivo_modulo.rendi_testo(risultato))
        return 0
    except db.ErroreLettura as errore:
        # Il file c'e' ma non si legge: tipicamente uno schema precedente alla migrazione
        # che ha introdotto `blueprint_runs`, cioe' ogni database esistente finche' il suo
        # prossimo hook di fine turno non applica `upgrade_head`. Si dichiara come gli
        # altri errori del comando — messaggio e uscita non-zero — mai come traceback.
        _stampa_utf8(
            "Errore: il database %s non si legge (%s).\n"
            "Se manca una tabella dell'esecuzione lo schema e' piu' vecchio di questa "
            "funzione: si aggiorna da solo al prossimo turno con un agente installato. "
            "Verifica lo stato con `starkeno doctor`." % (database, errore.orig),
            file=sys.stderr,
        )
        return 2
    finally:
        sessione.close()
        fabbrica.kw["bind"].dispose()
