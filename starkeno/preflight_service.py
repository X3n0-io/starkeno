"""Orchestrazione locale del core Preflight, senza database o provider esterni."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from starkeno.preflight_schema import Blueprint, dump_blueprint, load_blueprint

if TYPE_CHECKING:
    from starkeno.preflight_report import PreflightAnalysis
    from starkeno.preflight_simulate import SimulationReport


class BlueprintInputError(ValueError):
    """Un testo utente non puo essere caricato come Blueprint strutturato."""


def simulate_blueprint(
    blueprint: Blueprint, *, samples: int = 1000, seed: int | None = None
) -> SimulationReport:
    """Wrapper lazy mantenuto come seam stabile per test e integrazioni locali."""
    from starkeno.preflight_simulate import simulate_blueprint as simulate

    return simulate(blueprint, samples=samples, seed=seed)


def normalize_draft(text: str, *, format_hint: str | None) -> Blueprint:
    """Valida un Blueprint e garantisce che resti una revisione non confermata."""
    try:
        blueprint = load_blueprint(text, format_hint=format_hint)
    except ValueError as exc:
        raise BlueprintInputError(str(exc)) from exc
    if not blueprint.confirmed:
        return blueprint
    return blueprint.model_copy(
        update={
            "revision": blueprint.revision + 1,
            "parent_revision": blueprint.revision,
            "confirmed": False,
        }
    )


def analyze_confirmed(
    blueprint: Blueprint,
    *,
    samples: int,
    seed: int | None,
    source_path: Path | None = None,
) -> PreflightAnalysis:
    """Esegue lint e simulazione soltanto su una revisione gia confermata."""
    if not blueprint.confirmed:
        raise ValueError("Il Blueprint deve essere confermato prima dell'analisi")
    from starkeno.preflight_lint import lint_blueprint
    from starkeno.preflight_report import PreflightAnalysis

    return PreflightAnalysis(
        blueprint=blueprint,
        findings=lint_blueprint(blueprint),
        simulation=simulate_blueprint(blueprint, samples=samples, seed=seed),
        source_path=source_path,
    )


def write_blueprint_atomic(
    blueprint: Blueprint,
    destination: Path,
    *,
    format: str,
    source_path: Path | None = None,
) -> Path:
    """Scrive un Blueprint validato su `destination` senza mai lasciare un file a meta.

    Condivisa fra la CLI (`draft`) e i tool MCP di Preflight (`preflight_save_draft`):
    entrambi i chiamanti devono garantire che una scrittura interrotta non lasci un
    artefatto parziale, quindi la garanzia vive qui una volta sola invece che duplicata
    per ogni chiamante. Prima viveva come `_write_blueprint_atomic`, privata di
    `preflight_cli`; qui e' pubblica perche' un secondo chiamante ne ha bisogno.

    Scrive su un file temporaneo nella stessa directory di `destination`, forza
    `fsync` e poi rinomina atomicamente con `os.replace`: un errore a meta' scrittura
    lascia al piu' il temporaneo, mai `destination` a meta'. Il blocco `finally` rimuove
    il temporaneo se non si arriva alla rinomina.

    `source_path`, quando presente, e' il file da cui il Blueprint e' stato letto:
    scriverci sopra distruggerebbe l'unica copia buona, quindi e' un errore rifiutato
    qui anche se il chiamante lo ha gia' controllato prima (tipicamente la CLI, in
    `_read_input`) — chi chiama senza un `source_path`, come il tool MCP che riceve il
    Draft come testo e non da un file, non puo' avere questo problema.
    """
    resolved = destination.resolve()
    if source_path is not None and resolved == source_path.resolve():
        raise BlueprintInputError("La destinazione di output non puo coincidere con l'input")
    content = dump_blueprint(blueprint, format=format)  # type: ignore[arg-type]
    resolved.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{resolved.name}.", suffix=".tmp", dir=resolved.parent
    )
    temporary: Path | None = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return resolved


# ============================================== il preventivo di un'esecuzione registrata
#
# Non e' Preflight (lint + simulazione di un Blueprint nuovo): e' la lettura di un'analisi
# GIA' prodotta e conservata verbatim in `blueprint_runs.analysis_json`. Vive qui perche' ha
# DUE chiamanti sola-lettura che non possono importarsi a vicenda: i tool MCP
# dell'esecuzione in `mcp_server.py` (che importa l'SDK MCP a livello di modulo) e il
# comando `starkeno consuntivo` in `cli.py` (che non deve trascinare quell'SDK dentro un
# comando da terminale). Questo modulo non ha ne' l'uno ne' l'altro problema.


def validate_stored_analysis(text: str) -> tuple[str, Blueprint, SimulationReport]:
    """Valida il testo JSON di un'analisi Preflight (Blueprint + simulazione) salvata.

    Condivisa da `mcp_server.py` (`_carica_analisi` da file, `_carica_analisi_da_testo` dal
    campo `analysis_json` gia' in database) e da `cli.py` (`_esegui_consuntivo`, che legge
    lo stesso campo in sola lettura): STESSA validazione, non copie che potrebbero
    divergere di nuovo. Divergevano prima che questa funzione esistesse: una versione
    controllava solo la chiave 'simulation' e poi indicizzava `payload["blueprint"]` alla
    cieca, cosi' un payload — un dict, con 'simulation' ma senza 'blueprint' — sollevava
    `KeyError`, un `LookupError` e non un `ValueError`, che un `except (OSError, ValueError,
    UnicodeError)` a monte non intercetta: l'eccezione attraversava il chiamante come errore
    di protocollo invece che come testo dichiarato.

    Solleva SEMPRE `ValueError` — mai `KeyError` ne' altri `LookupError` — per ogni
    problema strutturale, in quest'ordine: il testo non e' JSON valido
    (`json.JSONDecodeError` e' gia' una sottoclasse di `ValueError`, passa cosi' com'e');
    il risultato non e' un dict; manca la chiave 'blueprint' o 'simulation' (o entrambe);
    il contenuto non valida contro il proprio modello (`pydantic.ValidationError` e'
    anch'essa una sottoclasse di `ValueError`).

    Ritorna `(text, blueprint, simulation)` — il testo originale incluso, cosi' un
    chiamante che deve conservarlo verbatim (`blueprint_run_start_impl`) non deve
    ri-leggerlo da un'altra fonte.

    Importa `SimulationReport` qui dentro, non in cima al modulo: stesso schema lazy di
    `simulate_blueprint` qui sopra, cosi' un comando CLI che non confronta nulla (`doctor`,
    `report`) non si carica pydantic in tasca.
    """
    import json as _json

    from starkeno.preflight_simulate import SimulationReport

    payload = _json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(
            "il file non e' un'analisi Preflight: il contenuto non e' un oggetto JSON"
        )
    missing = [key for key in ("blueprint", "simulation") if key not in payload]
    if missing:
        verb = "manca la chiave" if len(missing) == 1 else "mancano le chiavi"
        elenco = " e ".join("'%s'" % key for key in missing)
        raise ValueError(
            "il file non e' un'analisi Preflight: %s %s" % (verb, elenco)
        )
    blueprint = Blueprint.model_validate(payload["blueprint"])
    simulation = SimulationReport.model_validate(payload["simulation"])
    return text, blueprint, simulation
