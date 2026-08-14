"""Regressioni concrete per le regole pure del linter preflight."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from starkeno.preflight_lint import (
    Finding,
    finding_sort_key,
    has_blocking_findings,
    lint_blueprint,
)
from starkeno.preflight_schema import Blueprint


FIXTURE = Path(__file__).parent / "fixtures" / "preflight" / "minimal.json"


def make_blueprint(
    *,
    success_criteria: tuple[str, ...] = ("Approvazione registrata.",),
    extra_unreachable: bool = False,
    max_retries: int | None = 1,
    deterministic_with_model: bool = False,
) -> Blueprint:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["goal"]["success_criteria"] = list(success_criteria)
    payload["nodes"][0]["budget"]["max_retries"] = max_retries
    if deterministic_with_model:
        payload["nodes"][0]["kind"] = "deterministic"
    if extra_unreachable:
        orphan = payload["nodes"][0].copy()
        orphan["id"] = "orphan"
        orphan["description"] = "Non è raggiungibile."
        payload["nodes"].append(orphan)
    return Blueprint.model_validate(payload)


def make_cyclic_blueprint(*, max_traversals: int | None) -> Blueprint:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["transitions"].append(
        {
            "source": "review",
            "target": "draft",
            "activation": "always",
            "probability": None,
            "parallel_group": None,
            "max_traversals": max_traversals,
        }
    )
    return Blueprint.model_validate(payload)


def test_goal_senza_criteri_e_nodo_irraggiungibile_sono_spiegati():
    blueprint = make_blueprint(success_criteria=(), extra_unreachable=True)

    findings = {finding.rule_id: finding for finding in lint_blueprint(blueprint)}

    assert findings["PF-GOAL-001"].severity == "error"
    assert findings["PF-GOAL-001"].evidence["success_criteria"] == ()
    assert findings["PF-GRAPH-001"].locations == ("nodes/orphan",)


def test_ciclo_senza_limite_blocca_ma_ciclo_limitato_no():
    illimitato = make_cyclic_blueprint(max_traversals=None)
    limitato = make_cyclic_blueprint(max_traversals=3)

    assert "PF-LOOP-001" in {finding.rule_id for finding in lint_blueprint(illimitato)}
    assert "PF-LOOP-001" not in {finding.rule_id for finding in lint_blueprint(limitato)}


def test_retry_senza_massimo_e_llm_per_calcolo_deterministico():
    blueprint = make_blueprint(max_retries=None, deterministic_with_model=True)

    ids = {finding.rule_id for finding in lint_blueprint(blueprint)}

    assert {"PF-RETRY-001", "PF-MODEL-001"} <= ids


def test_regole_agenti_handoff_e_verifica_espongono_le_evidenze():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["agents"].append(
        {
            "id": "unused",
            "responsibility": "  SCRIVE   la  NOTA. ",
            "inputs": [],
            "output": "Nota.",
            "model_id": None,
            "tool_ids": [],
            "skill_ids": [],
        }
    )
    payload["nodes"][1]["kind"] = "handoff"
    payload["nodes"][1]["agent_id"] = "writer"

    findings = {finding.rule_id: finding for finding in lint_blueprint(Blueprint.model_validate(payload))}

    assert findings["PF-AGENT-001"].evidence["unassigned_agent_ids"] == ("unused",)
    assert findings["PF-AGENT-002"].evidence["agent_ids"] == ("unused", "writer")
    assert findings["PF-HANDOFF-001"].evidence["handoffs"] == (
        {
            "node_id": "review",
            "source_agent_id": "writer",
            "destination_agent_ids": (),
        },
    )
    assert findings["PF-VERIFY-001"].evidence["terminal_node_ids"] == ("review",)


def test_terminali_irraggiungibili_e_ordinamento_sono_stabili():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["transitions"].append(
        {
            "source": "review",
            "target": "review",
            "activation": "always",
            "probability": None,
            "parallel_group": None,
            "max_traversals": None,
        }
    )
    blueprint = Blueprint.model_validate(payload)

    findings = lint_blueprint(blueprint)

    assert "PF-GRAPH-002" in {finding.rule_id for finding in findings}
    assert findings == tuple(sorted(findings, key=finding_sort_key))
    assert has_blocking_findings(findings)
    assert not has_blocking_findings(())


def test_verifica_non_puo_essere_aggirata_da_un_percorso_parallelo():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    unchecked = payload["nodes"][0].copy()
    unchecked.update(
        {
            "id": "unchecked",
            "kind": "deterministic",
            "description": "Completa senza approvazione.",
            "model_id": None,
        }
    )
    payload["nodes"].append(unchecked)
    payload["transitions"].append(
        {
            "source": "draft",
            "target": "unchecked",
            "activation": "choice",
            "probability": None,
            "parallel_group": None,
            "max_traversals": None,
        }
    )

    findings = {finding.rule_id: finding for finding in lint_blueprint(Blueprint.model_validate(payload))}

    assert findings["PF-VERIFY-001"].evidence["bypassed_terminal_ids"] == ("unchecked",)
    assert findings["PF-VERIFY-001"].locations == ("nodes/unchecked",)


def test_evidence_e_ricorsivamente_immutabile_e_serializzabile():
    finding = Finding(
        rule_id="PF-TEST-001",
        severity="info",
        category="test",
        message="Test.",
        evidence={"nested": {"items": [{"id": "one"}], "ids": {"b", "a"}}},
        locations=("test",),
        suggestion="Nessuna.",
        source="deterministic",
        blueprint_hash="hash",
    )

    with pytest.raises(TypeError):
        finding.evidence["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        finding.evidence["nested"]["items"][0]["id"] = "changed"  # type: ignore[index]

    assert finding.model_dump(mode="json")["evidence"] == {
        "nested": {"ids": ["a", "b"], "items": [{"id": "one"}]}
    }
