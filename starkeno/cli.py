"""Interfaccia a riga di comando supportata di StarkEno."""
from __future__ import annotations

import argparse
import json
import os
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


def _controllo_inventario(canonico: Path, plugin_root: Path) -> Controllo:
    candidati = inventaria_candidati(
        canonico=canonico, radice_progetto=plugin_root,
    )
    dati = []
    for candidato in candidati:
        voce = asdict(candidato)
        voce["percorso"] = str(candidato.percorso)
        dati.append(voce)

    canonico_integro = candidati[0].integro
    recuperabili = [c for c in candidati[1:] if c.integro]
    if canonico_integro:
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
