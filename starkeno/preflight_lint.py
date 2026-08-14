"""Regole pure e riproducibili per analizzare un Blueprint validato."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence, Set
import json
from types import MappingProxyType
from typing import Iterable, Literal

from pydantic import field_serializer, field_validator

from starkeno.preflight_schema import Blueprint, FrozenModel, Transition, WorkflowNode, blueprint_hash


Severity = Literal["critical", "error", "warning", "info"]

_SEVERITY_ORDER: Mapping[Severity, int] = {
    "critical": 0,
    "error": 1,
    "warning": 2,
    "info": 3,
}


class Finding(FrozenModel):
    """Un rilievo deterministico, riferito a una precisa revisione del Blueprint."""

    rule_id: str
    severity: Severity
    category: str
    message: str
    evidence: Mapping[str, object]
    locations: tuple[str, ...]
    suggestion: str
    source: Literal["deterministic"]
    blueprint_hash: str

    @field_validator("evidence", mode="after")
    @classmethod
    def evidenza_immutabile(cls, evidence: Mapping[str, object]) -> Mapping[str, object]:
        """Congela ricorsivamente l'evidenza senza cambiare i valori osservati."""
        frozen = _freeze_evidence(evidence)
        if not isinstance(frozen, Mapping):  # pragma: no cover - garantito dal tipo del campo.
            raise TypeError("evidence deve essere una mapping")
        return frozen

    @field_serializer("evidence")
    def serializza_evidenza(self, evidence: Mapping[str, object]) -> dict[str, object]:
        """Rende l'evidenza congelata nuovamente JSON-compatibile per gli export."""
        serialized = _thaw_evidence(evidence)
        if not isinstance(serialized, dict):  # pragma: no cover - garantito dal tipo del campo.
            raise TypeError("evidence serializzata deve essere una mapping")
        return serialized


def finding_sort_key(finding: Finding) -> tuple[int, str, tuple[str, ...]]:
    """Chiave pubblica che fissa l'ordine dei rilievi nel report."""
    return (_SEVERITY_ORDER[finding.severity], finding.rule_id, finding.locations)


def has_blocking_findings(findings: Iterable[Finding]) -> bool:
    """Indica se il lint contiene un errore che impedisce l'analisi affidabile."""
    return any(finding.severity in {"critical", "error"} for finding in findings)


def lint_blueprint(blueprint: Blueprint) -> tuple[Finding, ...]:
    """Esegue le regole del lint senza mutare o caricare dati esterni."""
    current_hash = blueprint_hash(blueprint)
    findings: list[Finding] = []
    node_by_id = {node.id: node for node in blueprint.nodes}
    outgoing = _outgoing_transitions(blueprint.transitions)
    reachable_ids = _reachable_node_ids(blueprint.entry_node_ids, outgoing)

    if not blueprint.goal.success_criteria:
        findings.append(
            _finding(
                current_hash,
                "PF-GOAL-001",
                "error",
                "goal",
                "Il goal non dichiara criteri di successo osservabili.",
                {"success_criteria": blueprint.goal.success_criteria},
                ("goal/success_criteria",),
                "Aggiungi almeno un criterio di successo verificabile.",
            )
        )

    unreachable_ids = tuple(sorted(set(node_by_id) - reachable_ids))
    if unreachable_ids:
        findings.append(
            _finding(
                current_hash,
                "PF-GRAPH-001",
                "error",
                "graph",
                "Alcuni nodi non sono raggiungibili dagli entry point.",
                {
                    "entry_node_ids": tuple(sorted(blueprint.entry_node_ids)),
                    "unreachable_node_ids": unreachable_ids,
                },
                tuple(f"nodes/{node_id}" for node_id in unreachable_ids),
                "Collega i nodi a un entry point oppure rimuovili dal Blueprint.",
            )
        )

    terminal_ids = tuple(sorted(node_id for node_id in node_by_id if not outgoing.get(node_id, ())))
    reachable_terminal_ids = tuple(node_id for node_id in terminal_ids if node_id in reachable_ids)
    if not reachable_terminal_ids:
        findings.append(
            _finding(
                current_hash,
                "PF-GRAPH-002",
                "critical",
                "graph",
                "Nessun nodo terminale è raggiungibile dagli entry point.",
                {
                    "entry_node_ids": tuple(sorted(blueprint.entry_node_ids)),
                    "terminal_node_ids": terminal_ids,
                    "reachable_node_ids": tuple(sorted(reachable_ids)),
                },
                tuple(f"nodes/{node_id}" for node_id in terminal_ids)
                or ("workflow",),
                "Definisci un percorso dagli entry point a un nodo senza transizioni uscenti.",
            )
        )

    unlimited_cycle_nodes = _unlimited_cycle_nodes(blueprint.nodes, blueprint.transitions)
    if unlimited_cycle_nodes:
        findings.append(
            _finding(
                current_hash,
                "PF-LOOP-001",
                "critical",
                "loop",
                "Il workflow contiene un ciclo privo di un limite di attraversamenti.",
                {"cycle_node_ids": unlimited_cycle_nodes},
                tuple(f"nodes/{node_id}" for node_id in unlimited_cycle_nodes),
                "Imposta max_traversals su almeno un arco di ogni ciclo.",
            )
        )

    retry_without_limit_ids = tuple(
        sorted(
            node.id
            for node in blueprint.nodes
            if node.budget.max_retries is None and node.budget.retry_probability.max > 0
        )
    )
    if retry_without_limit_ids:
        findings.append(
            _finding(
                current_hash,
                "PF-RETRY-001",
                "critical",
                "loop",
                "Alcuni nodi possono ritentare senza un massimo dichiarato.",
                {
                    "nodes": tuple(
                        {
                            "node_id": node_id,
                            "retry_probability": node_by_id[node_id].budget.retry_probability.model_dump(),
                            "max_retries": node_by_id[node_id].budget.max_retries,
                        }
                        for node_id in retry_without_limit_ids
                    )
                },
                tuple(f"nodes/{node_id}/budget/max_retries" for node_id in retry_without_limit_ids),
                "Dichiara max_retries per ogni nodo con probabilità di retry non nulla.",
            )
        )

    assigned_agent_ids = {node.agent_id for node in blueprint.nodes if node.agent_id is not None}
    unassigned_agent_ids = tuple(sorted(agent.id for agent in blueprint.agents if agent.id not in assigned_agent_ids))
    if unassigned_agent_ids:
        findings.append(
            _finding(
                current_hash,
                "PF-AGENT-001",
                "warning",
                "agent",
                "Alcuni agenti dichiarati non sono assegnati a nessun nodo.",
                {"unassigned_agent_ids": unassigned_agent_ids},
                tuple(f"agents/{agent_id}" for agent_id in unassigned_agent_ids),
                "Assegna gli agenti a un nodo oppure rimuovi le dichiarazioni inutilizzate.",
            )
        )

    for responsibility, agent_ids in _duplicate_responsibilities(blueprint).items():
        findings.append(
            _finding(
                current_hash,
                "PF-AGENT-002",
                "warning",
                "agent",
                "Più agenti hanno la stessa responsabilità normalizzata.",
                {"normalized_responsibility": responsibility, "agent_ids": agent_ids},
                tuple(f"agents/{agent_id}/responsibility" for agent_id in agent_ids),
                "Distingui le responsabilità o consolida gli agenti duplicati.",
            )
        )

    invalid_handoffs = _invalid_handoffs(blueprint.nodes, outgoing, node_by_id)
    if invalid_handoffs:
        findings.append(
            _finding(
                current_hash,
                "PF-HANDOFF-001",
                "error",
                "handoff",
                "Alcuni handoff non dichiarano agenti sorgente e destinazione distinti.",
                {"handoffs": invalid_handoffs},
                tuple(f"nodes/{handoff['node_id']}" for handoff in invalid_handoffs),
                "Assegna un agente al handoff e collegalo a un nodo di un agente diverso.",
            )
        )

    deterministic_with_model_ids = tuple(
        sorted(node.id for node in blueprint.nodes if node.kind == "deterministic" and node.model_id is not None)
    )
    if deterministic_with_model_ids:
        findings.append(
            _finding(
                current_hash,
                "PF-MODEL-001",
                "warning",
                "model",
                "Alcuni nodi deterministici dichiarano un modello LLM.",
                {
                    "nodes": tuple(
                        {"node_id": node_id, "model_id": node_by_id[node_id].model_id}
                        for node_id in deterministic_with_model_ids
                    )
                },
                tuple(f"nodes/{node_id}/model_id" for node_id in deterministic_with_model_ids),
                "Rimuovi il modello dal nodo oppure dichiara un tipo di nodo non deterministico.",
            )
        )

    verification_ids = tuple(
        sorted(
            node_id
            for node_id in reachable_ids
            if node_by_id[node_id].kind in {"gate", "human"}
        )
    )
    bypassed_terminal_ids = _terminals_reachable_without_verification(
        blueprint.entry_node_ids, node_by_id, outgoing, reachable_terminal_ids
    )
    if bypassed_terminal_ids:
        findings.append(
            _finding(
                current_hash,
                "PF-VERIFY-001",
                "error",
                "verification",
                "Alcuni terminali possono aggirare gate o approvazione umana.",
                {
                    "reachable_node_ids": tuple(sorted(reachable_ids)),
                    "terminal_node_ids": reachable_terminal_ids,
                    "verification_node_ids": verification_ids,
                    "bypassed_terminal_ids": bypassed_terminal_ids,
                },
                tuple(f"nodes/{node_id}" for node_id in bypassed_terminal_ids),
                "Inserisci un nodo gate o human sul percorso verso un terminale.",
            )
        )

    return tuple(sorted(findings, key=finding_sort_key))


def _finding(
    current_hash: str,
    rule_id: str,
    severity: Severity,
    category: str,
    message: str,
    evidence: Mapping[str, object],
    locations: tuple[str, ...],
    suggestion: str,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        category=category,
        message=message,
        evidence=evidence,
        locations=locations,
        suggestion=suggestion,
        source="deterministic",
        blueprint_hash=current_hash,
    )


def _outgoing_transitions(transitions: Iterable[Transition]) -> dict[str, tuple[Transition, ...]]:
    grouped: dict[str, list[Transition]] = defaultdict(list)
    for transition in transitions:
        grouped[transition.source].append(transition)
    return {
        source: tuple(sorted(items, key=lambda item: (item.target, item.activation, item.max_traversals or 0)))
        for source, items in grouped.items()
    }


def _reachable_node_ids(
    entry_node_ids: Iterable[str], outgoing: Mapping[str, tuple[Transition, ...]]
) -> set[str]:
    reached = set(entry_node_ids)
    pending = list(sorted(reached))
    while pending:
        source = pending.pop()
        for transition in outgoing.get(source, ()):
            if transition.target not in reached:
                reached.add(transition.target)
                pending.append(transition.target)
    return reached


def _unlimited_cycle_nodes(
    nodes: Iterable[WorkflowNode], transitions: Iterable[Transition]
) -> tuple[str, ...]:
    adjacency: dict[str, tuple[str, ...]] = {node.id: () for node in nodes}
    mutable_adjacency: dict[str, list[str]] = defaultdict(list)
    for transition in transitions:
        if transition.max_traversals is None:
            mutable_adjacency[transition.source].append(transition.target)
    adjacency.update(
        {
            source: tuple(sorted(targets))
            for source, targets in mutable_adjacency.items()
        }
    )
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node_id: str, trail: list[str]) -> None:
        visiting.add(node_id)
        trail.append(node_id)
        for target_id in adjacency[node_id]:
            if target_id in visiting:
                cycle_nodes.update(trail[trail.index(target_id) :])
            elif target_id not in visited:
                visit(target_id, trail)
        trail.pop()
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(adjacency):
        if node_id not in visited:
            visit(node_id, [])
    return tuple(sorted(cycle_nodes))


def _duplicate_responsibilities(blueprint: Blueprint) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for agent in blueprint.agents:
        grouped[" ".join(agent.responsibility.split()).casefold()].append(agent.id)
    return {
        responsibility: tuple(sorted(agent_ids))
        for responsibility, agent_ids in sorted(grouped.items())
        if len(agent_ids) > 1
    }


def _invalid_handoffs(
    nodes: Iterable[WorkflowNode],
    outgoing: Mapping[str, tuple[Transition, ...]],
    node_by_id: Mapping[str, WorkflowNode],
) -> tuple[dict[str, object], ...]:
    invalid: list[dict[str, object]] = []
    for node in sorted((node for node in nodes if node.kind == "handoff"), key=lambda item: item.id):
        destination_agent_ids = tuple(
            sorted(
                {
                    node_by_id[transition.target].agent_id
                    for transition in outgoing.get(node.id, ())
                    if node_by_id[transition.target].agent_id is not None
                }
            )
        )
        distinct_destination_ids = tuple(
            agent_id for agent_id in destination_agent_ids if agent_id != node.agent_id
        )
        if node.agent_id is None or not distinct_destination_ids:
            invalid.append(
                {
                    "node_id": node.id,
                    "source_agent_id": node.agent_id,
                    "destination_agent_ids": destination_agent_ids,
                }
            )
    return tuple(invalid)


def _terminals_reachable_without_verification(
    entry_node_ids: Iterable[str],
    node_by_id: Mapping[str, WorkflowNode],
    outgoing: Mapping[str, tuple[Transition, ...]],
    terminal_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Trova terminali per cui esiste almeno un percorso privo di verifica."""
    terminals = set(terminal_ids)
    pending = [(node_id, False) for node_id in sorted(entry_node_ids)]
    visited: set[tuple[str, bool]] = set()
    bypassed: set[str] = set()
    while pending:
        node_id, verified_seen = pending.pop()
        state = (node_id, verified_seen)
        if state in visited:
            continue
        visited.add(state)
        verified_now = verified_seen or node_by_id[node_id].kind in {"gate", "human"}
        if node_id in terminals:
            if not verified_now:
                bypassed.add(node_id)
            continue
        pending.extend(
            (transition.target, verified_now) for transition in outgoing.get(node_id, ())
        )
    return tuple(sorted(bypassed))


def _freeze_evidence(value: object) -> object:
    """Trasforma contenitori mutabili in equivalenti ricorsivi e immutabili."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_evidence(item) for key, item in sorted(value.items())}
        )
    if isinstance(value, Set) and not isinstance(value, (str, bytes, bytearray)):
        return frozenset(_freeze_evidence(item) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_evidence(item) for item in value)
    return value


def _thaw_evidence(value: object) -> object:
    """Ricostruisce contenitori JSON-compatibili con ordine stabile."""
    if isinstance(value, Mapping):
        return {key: _thaw_evidence(item) for key, item in sorted(value.items())}
    if isinstance(value, frozenset):
        thawed = (_thaw_evidence(item) for item in value)
        return sorted(thawed, key=_evidence_sort_key)
    if isinstance(value, tuple):
        return [_thaw_evidence(item) for item in value]
    return value


def _evidence_sort_key(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=repr)
