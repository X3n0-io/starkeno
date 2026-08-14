"""Smoke corpus sintetico per il core Preflight e le sue superfici CLI."""
from __future__ import annotations

from pathlib import Path

import pytest

from starkeno.preflight_cli import main as preflight_main
from starkeno.preflight_lint import finding_sort_key, lint_blueprint
from starkeno.preflight_schema import (
    Blueprint,
    blueprint_hash,
    dump_blueprint,
    load_blueprint,
)
from starkeno.preflight_simulate import simulate_blueprint


FIXTURES = Path(__file__).parent / "fixtures" / "preflight"
CORPUS = tuple(
    FIXTURES / name
    for name in (
        "simple.json",
        "medium.json",
        "complex-team.json",
        "unbounded-loop.json",
    )
)


def load_fixture(name: str) -> Blueprint:
    return load_blueprint((FIXTURES / name).read_text(encoding="utf-8"), format_hint="json")


def confirm(blueprint: Blueprint) -> Blueprint:
    return blueprint.model_copy(
        update={
            "revision": blueprint.revision + 1,
            "parent_revision": blueprint.revision,
            "confirmed": True,
        }
    )


@pytest.mark.parametrize("fixture", CORPUS, ids=lambda path: path.stem)
def test_corpus_round_trip_lint_e_simulazione_sono_deterministici(fixture: Path):
    blueprint = load_blueprint(fixture.read_text(encoding="utf-8"), format_hint="json")
    encoded = dump_blueprint(blueprint, format="json")
    round_tripped = load_blueprint(encoded, format_hint="json")

    assert round_tripped == blueprint
    assert blueprint_hash(round_tripped) == blueprint_hash(blueprint)

    findings = lint_blueprint(round_tripped)
    confirmed = confirm(round_tripped)
    first = simulate_blueprint(confirmed, samples=50)
    second = simulate_blueprint(confirmed, samples=50)

    assert (confirmed.revision, confirmed.parent_revision, confirmed.confirmed) == (
        blueprint.revision + 1,
        blueprint.revision,
        True,
    )
    assert first == second
    assert first.blueprint_hash == blueprint_hash(confirmed)
    assert tuple(findings) == tuple(sorted(findings, key=finding_sort_key))


def test_fixture_illimitata_dichiara_unbounded_ma_termina_i_sample():
    blueprint = confirm(load_fixture("unbounded-loop.json"))

    report = simulate_blueprint(blueprint, samples=20)

    assert report.maximum_status == "unbounded"
    assert report.maximum is None
    assert report.completed_samples == 20


def test_corpus_copre_sequenza_tool_retry_team_parallelismo_handoff_e_choice():
    simple = load_fixture("simple.json")
    medium = load_fixture("medium.json")
    complex_team = load_fixture("complex-team.json")

    assert len(simple.nodes) == 1
    assert any(node.kind == "tool" for node in medium.nodes)
    medium_tool = next(node for node in medium.nodes if node.kind == "tool")
    assert medium_tool.budget.fixed_tool_cost is not None
    assert medium_tool.budget.fixed_tool_cost.typical == 0
    assert any(node.kind == "gate" for node in medium.nodes)
    assert any(node.budget.max_retries for node in medium.nodes)
    assert len(complex_team.agents) >= 2
    assert any(node.kind == "handoff" for node in complex_team.nodes)
    assert any(transition.parallel_group for transition in complex_team.transitions)
    assert any(transition.activation == "choice" for transition in complex_team.transitions)


def test_medium_legge_il_record_prima_di_comporre_e_validare():
    medium = load_fixture("medium.json")

    assert medium.entry_node_ids == ("read-record",)
    assert tuple(
        (transition.source, transition.target, transition.max_traversals)
        for transition in medium.transitions
    ) == (
        ("read-record", "compose", None),
        ("compose", "validate", None),
        ("validate", "approved", None),
        ("validate", "compose", 1),
    )


def test_team_modella_output_paralleli_indipendenti_e_una_sola_raccomandazione():
    complex_team = load_fixture("complex-team.json")
    edges = {
        (transition.source, transition.target)
        for transition in complex_team.transitions
    }

    assert edges == {
        ("plan", "delegate"),
        ("delegate", "research"),
        ("delegate", "review"),
        ("research", "decision"),
        ("research", "revise"),
        ("revise", "decision"),
    }
    assert "indipendenti" in complex_team.goal.deliverable
    assert "ramo ricerca" in complex_team.goal.success_criteria[0]

    report = simulate_blueprint(confirm(complex_team), samples=50)
    for scenario_name in ("optimistic", "typical", "prudent", "maximum"):
        scenario = getattr(report, scenario_name)
        assert scenario is not None
        decision = next(node for node in scenario.nodes if node.node_id == "decision")
        assert decision.executions == 1


def test_cli_smoke_draft_json_in_json_out_e_analyze_yaml_in_html_out(
    tmp_path: Path,
):
    json_source = FIXTURES / "simple.json"
    draft_output = tmp_path / "draft.json"

    assert preflight_main(
        [
            "draft",
            "--input",
            str(json_source),
            "--format",
            "json",
            "--output",
            str(draft_output),
        ]
    ) == 0
    draft = load_blueprint(draft_output.read_text(encoding="utf-8"), format_hint="json")
    assert draft.confirmed is False

    yaml_source = tmp_path / "medium.yaml"
    yaml_source.write_text(
        dump_blueprint(load_fixture("medium.json"), format="yaml"),
        encoding="utf-8",
    )
    report_output = tmp_path / "report.html"
    assert preflight_main(
        [
            "analyze",
            "--input",
            str(yaml_source),
            "--confirmed",
            "--samples",
            "20",
            "--format",
            "html",
            "--output",
            str(report_output),
        ]
    ) == 0
    html = report_output.read_text(encoding="utf-8")
    assert "<!doctype html>" in html
    assert "Report Preflight" in html
