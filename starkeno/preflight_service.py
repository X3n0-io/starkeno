"""Orchestrazione locale del core Preflight, senza database o provider esterni."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from starkeno.preflight_schema import Blueprint, load_blueprint

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
