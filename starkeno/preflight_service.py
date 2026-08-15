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
