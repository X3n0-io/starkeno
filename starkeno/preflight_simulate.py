"""Simulazione pura, riproducibile e senza prezzi impliciti dei Blueprint Preflight."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
import math
import random
from typing import Literal, Mapping

from pydantic import Field

from starkeno.preflight_schema import (
    Blueprint,
    FrozenModel,
    IntEstimate,
    MoneyEstimate,
    ModelProfile,
    RatioEstimate,
    Transition,
    WorkflowNode,
    blueprint_hash,
)


MaximumStatus = Literal["finite", "unbounded"]
RunMode = Literal["min", "sample", "max"]
SIMULATION_ALGORITHM_VERSION = "preflight-simulate-v5"
UNBOUNDED_CYCLE_TRAVERSAL_LIMIT = 128
UNBOUNDED_RETRY_LIMIT = 64
LOOKAHEAD_EVALUATION_LIMIT = 200_000


class NodeTotals(FrozenModel):
    """Subtotale di tutte le esecuzioni di un nodo in uno scenario."""

    node_id: str
    agent_id: str | None
    model_id: str | None
    executions: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cost: Decimal | None
    currency: str | None


class AgentTotals(FrozenModel):
    """Subtotale dei nodi attribuiti a un agente."""

    agent_id: str
    executions: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cost: Decimal | None
    currency: str | None


class ScenarioTotals(FrozenModel):
    """Totali coerenti di una singola corsa completa del grafo."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cost: Decimal | None
    currency: str | None
    nodes: tuple[NodeTotals, ...]
    agents: tuple[AgentTotals, ...]


class NodeQuantitativeBasis(FrozenModel):
    """Budget quantitativo persistito di un nodo raggiungibile."""

    key: str
    instructions: IntEstimate
    dynamic_context: IntEstimate
    output: IntEstimate
    cacheable_fraction: RatioEstimate
    latency_ms: IntEstimate
    retry_probability: RatioEstimate
    max_retries: int | None
    fixed_tool_cost: MoneyEstimate | None


class TransitionQuantitativeBasis(FrozenModel):
    """Probabilita e limite persistiti di un arco raggiungibile."""

    key: str
    source: str
    target: str
    activation: Literal["choice", "always"]
    parallel_group: str | None
    probability: RatioEstimate | None
    max_traversals: int | None


class ChoiceBranchWeight(FrozenModel):
    """Peso typical effettivo usato dal fallback di un choice group."""

    transition_key: str
    weight: float = Field(ge=0)


class ChoiceGroupQuantitativeBasis(FrozenModel):
    """Fallback materializzato per un insieme stabile di rami choice."""

    key: str
    source: str
    fallback: Literal["uniform", "residual"]
    branches: tuple[ChoiceBranchWeight, ...]


QuantitativeBasis = (
    NodeQuantitativeBasis | TransitionQuantitativeBasis | ChoiceGroupQuantitativeBasis
)


class SimulationReport(FrozenModel):
    """Scenari e metadati sufficienti a ripetere e confrontare una simulazione."""

    blueprint_hash: str
    effective_seed: int = Field(ge=0)
    samples: int = Field(ge=1, le=10_000)
    completed_samples: int = Field(ge=0)
    profile_hash: str
    algorithm_version: str
    quantitative_basis: tuple[QuantitativeBasis, ...]
    assumptions_hash: str
    optimistic: ScenarioTotals | None
    typical: ScenarioTotals | None
    prudent: ScenarioTotals | None
    maximum_status: MaximumStatus
    maximum: ScenarioTotals | None
    unknown_prices: tuple[str, ...]
    assumptions: tuple[str, ...]
    confidence: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class ExecutionFrame:
    """Stato locale del prossimo nodo da attraversare."""

    node_id: str
    edge_counts: dict[tuple[str, str], int]
    ready_at_ms: int


@dataclass(frozen=True)
class GraphGuard:
    """Bound strutturale delle visite e budget dei soli archi ciclici illimitati."""

    step_limit: int
    cyclic_edge_keys: frozenset[tuple[str, str]]
    cyclic_edge_limit: int


@dataclass
class _MutableTotals:
    executions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    latency_ms: int = 0
    fixed_tool_cost: Decimal = Decimal("0")
    fixed_tool_currency: str | None = None
    unknown_tool_cost: bool = False

    def add(self, other: _MutableTotals) -> None:
        self.executions += other.executions
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.llm_calls += other.llm_calls
        self.tool_calls += other.tool_calls
        self.latency_ms += other.latency_ms
        self.fixed_tool_cost += other.fixed_tool_cost
        currency_conflict = (
            self.fixed_tool_currency is not None
            and other.fixed_tool_currency is not None
            and self.fixed_tool_currency != other.fixed_tool_currency
        )
        self.unknown_tool_cost = (
            self.unknown_tool_cost or other.unknown_tool_cost or currency_conflict
        )
        if self.unknown_tool_cost:
            self.fixed_tool_currency = None
        else:
            self.fixed_tool_currency = (
                other.fixed_tool_currency or self.fixed_tool_currency
            )


@dataclass
class _LookaheadBudget:
    """Tetto dell'esplorazione min/max: esaurirlo dichiara, non stima di nascosto."""

    remaining: int = LOOKAHEAD_EVALUATION_LIMIT

    def spend(self) -> None:
        if self.remaining <= 0:
            raise _StepLimitReached
        self.remaining -= 1


@dataclass
class _RunState:
    node_totals: dict[str, _MutableTotals] = field(default_factory=lambda: defaultdict(_MutableTotals))
    steps: int = 0
    maximum_finish_ms: int = 0


class _StepLimitReached(RuntimeError):
    """Guardia interna: non rappresenta uno scenario completo."""


def simulate_blueprint(
    blueprint: Blueprint,
    *,
    samples: int = 1000,
    seed: int | None = None,
) -> SimulationReport:
    """Simula un Blueprint confermato senza leggere stato esterno o invocare modelli."""
    if not blueprint.confirmed:
        raise ValueError("Il Blueprint deve essere confermato prima della simulazione")
    if not 1 <= samples <= 10_000:
        raise ValueError("samples deve essere compreso tra 1 e 10_000")

    current_hash = blueprint_hash(blueprint)
    effective_seed = int(current_hash[:16], 16) if seed is None else seed
    if effective_seed < 0:
        raise ValueError("seed deve essere maggiore o uguale a zero")

    assumptions = list(_declared_assumptions(blueprint))
    maximum_status: MaximumStatus = "unbounded" if _has_unbounded_maximum(blueprint) else "finite"
    if maximum_status == "unbounded":
        assumptions.append("Il massimo è unbounded perché almeno un ciclo o retry non è limitato.")

    inevitably_unbounded = _is_inevitably_unbounded(blueprint)
    optimistic = None if inevitably_unbounded else _run_safely(blueprint, mode="min", rng=None)
    if optimistic is None and not inevitably_unbounded:
        assumptions.append(
            "Lo scenario ottimistico non è determinabile entro la guardia di grafo o di esplorazione."
        )
    maximum = None
    if maximum_status == "finite":
        maximum = _run_safely(blueprint, mode="max", rng=None)
        if maximum is None:
            maximum_status = "unbounded"
            assumptions.append("La guardia di passi ha rilevato un percorso massimo non limitato.")

    completed: list[ScenarioTotals] = []
    if not inevitably_unbounded:
        rng = random.Random(effective_seed)
        for _ in range(samples):
            result = _run_safely(blueprint, mode="sample", rng=rng)
            if result is not None:
                completed.append(result)
    if len(completed) < samples:
        assumptions.append(
            f"{samples - len(completed)} campioni non sono completi per la guardia di grafo o retry e sono esclusi dai percentili."
        )

    typical = _percentile_run(completed, 0.50)
    prudent = _percentile_run(completed, 0.90)
    reachable_node_ids = _reachable_node_ids(blueprint)
    quantitative_basis = _quantitative_basis(blueprint, reachable_node_ids)
    unknown_prices = _unknown_price_ids(blueprint, reachable_node_ids)
    if unknown_prices:
        assumptions.append(
            "Prezzi mancanti nel caso peggiore per: "
            + ", ".join(unknown_prices)
            + ". Uno scenario con costo valorizzato non ha usato le categorie mancanti."
        )
    currencies = _used_currencies(blueprint, reachable_node_ids)
    if len(currencies) > 1:
        assumptions.append("Costi in valute diverse non vengono sommati in un totale monetario.")

    stable_assumptions = tuple(sorted(set(assumptions)))
    return SimulationReport(
        blueprint_hash=current_hash,
        effective_seed=effective_seed,
        samples=samples,
        completed_samples=len(completed),
        profile_hash=_profile_hash(blueprint.models),
        algorithm_version=SIMULATION_ALGORITHM_VERSION,
        quantitative_basis=quantitative_basis,
        assumptions_hash=_assumptions_hash(
            quantitative_basis, _declared_assumptions(blueprint)
        ),
        optimistic=optimistic,
        typical=typical,
        prudent=prudent,
        maximum_status=maximum_status,
        maximum=maximum,
        unknown_prices=unknown_prices,
        assumptions=stable_assumptions,
        confidence=_overall_confidence(blueprint, reachable_node_ids),
    )


def _run_safely(
    blueprint: Blueprint,
    *,
    mode: RunMode,
    rng: random.Random | None,
) -> ScenarioTotals | None:
    try:
        return _run_once(blueprint, mode=mode, rng=rng)
    except _StepLimitReached:
        return None


def _run_once(
    blueprint: Blueprint,
    *,
    mode: RunMode,
    rng: random.Random | None,
) -> ScenarioTotals:
    node_by_id = {node.id: node for node in blueprint.nodes}
    outgoing = _outgoing(blueprint.transitions)
    state = _RunState()
    edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    graph_guard = _graph_guard(blueprint)
    lookahead = _LookaheadBudget()
    serial_cursor = 0
    for entry_id in sorted(blueprint.entry_node_ids):
        serial_cursor = _visit(
            ExecutionFrame(entry_id, edge_counts, serial_cursor),
            blueprint=blueprint,
            node_by_id=node_by_id,
            outgoing=outgoing,
            state=state,
            mode=mode,
            rng=rng,
            graph_guard=graph_guard,
            lookahead=lookahead,
        )
    state.maximum_finish_ms = max(state.maximum_finish_ms, serial_cursor)
    return _freeze_scenario(blueprint, state)


def _visit(
    frame: ExecutionFrame,
    *,
    blueprint: Blueprint,
    node_by_id: Mapping[str, WorkflowNode],
    outgoing: Mapping[str, tuple[Transition, ...]],
    state: _RunState,
    mode: RunMode,
    rng: random.Random | None,
    graph_guard: GraphGuard,
    lookahead: _LookaheadBudget,
) -> int:
    state.steps += 1
    if state.steps > graph_guard.step_limit:
        raise _StepLimitReached

    node = node_by_id[frame.node_id]
    current = _node_invocation(node, mode=mode, rng=rng)
    state.node_totals[node.id].add(current)
    finish_ms = frame.ready_at_ms + current.latency_ms
    state.maximum_finish_ms = max(state.maximum_finish_ms, finish_ms)

    activated = _activated_transitions(
        node,
        tuple(
            transition
            for transition in outgoing.get(node.id, ())
            if transition.max_traversals is None
            or frame.edge_counts[(transition.source, transition.target)] < transition.max_traversals
        ),
        node_by_id=node_by_id,
        outgoing=outgoing,
        edge_counts=frame.edge_counts,
        graph_guard=graph_guard,
        mode=mode,
        rng=rng,
        lookahead=lookahead,
    )
    available: list[Transition] = []
    for transition in activated:
        key = (transition.source, transition.target)
        if (
            key in graph_guard.cyclic_edge_keys
            and frame.edge_counts[key] >= graph_guard.cyclic_edge_limit
        ):
            raise _StepLimitReached
        frame.edge_counts[key] += 1
        available.append(transition)

    cursor = finish_ms
    for group in _execution_groups(available):
        group_finish = cursor
        for transition in group:
            branch_finish = _visit(
                ExecutionFrame(transition.target, frame.edge_counts, cursor),
                blueprint=blueprint,
                node_by_id=node_by_id,
                outgoing=outgoing,
                state=state,
                mode=mode,
                rng=rng,
                graph_guard=graph_guard,
                lookahead=lookahead,
            )
            group_finish = max(group_finish, branch_finish)
        cursor = group_finish
    return cursor


def _node_invocation(
    node: WorkflowNode,
    *,
    mode: RunMode,
    rng: random.Random | None,
) -> _MutableTotals:
    budget = node.budget
    value_name = "typical" if mode == "sample" else mode
    instructions = getattr(budget.instructions, value_name)
    dynamic_context = getattr(budget.dynamic_context, value_name)
    output = getattr(budget.output, value_name)
    cache_fraction = Decimal(str(getattr(budget.cacheable_fraction, value_name)))
    latency = getattr(budget.latency_ms, value_name)
    retries = _retry_count(node, mode=mode, rng=rng)
    attempts = 1 + retries
    gross_input = instructions + dynamic_context
    cacheable = int(Decimal(gross_input) * cache_fraction)
    uncached = gross_input - cacheable
    fixed_tool_cost = Decimal("0")
    fixed_tool_currency = None
    unknown_tool_cost = False
    if node.kind == "tool":
        if budget.fixed_tool_cost is None:
            unknown_tool_cost = True
        else:
            fixed_tool_cost = getattr(budget.fixed_tool_cost, value_name) * attempts
            fixed_tool_currency = budget.fixed_tool_cost.currency

    return _MutableTotals(
        executions=attempts,
        input_tokens=uncached * attempts,
        output_tokens=output * attempts,
        cache_read_tokens=cacheable * retries,
        cache_write_tokens=cacheable,
        llm_calls=attempts if node.kind == "llm" else 0,
        tool_calls=attempts if node.kind == "tool" else 0,
        latency_ms=latency * attempts,
        fixed_tool_cost=fixed_tool_cost,
        fixed_tool_currency=fixed_tool_currency,
        unknown_tool_cost=unknown_tool_cost,
    )


def _retry_count(
    node: WorkflowNode,
    *,
    mode: RunMode,
    rng: random.Random | None,
) -> int:
    if mode == "min":
        return 0
    maximum = node.budget.max_retries
    if mode == "max":
        if maximum is None and node.budget.retry_probability.max > 0:
            raise _StepLimitReached
        return (maximum or 0) if node.budget.retry_probability.max > 0 else 0
    if rng is None:  # pragma: no cover - protetto dai chiamanti interni.
        raise TypeError("Il campionamento richiede un generatore pseudocasuale")
    probability = node.budget.retry_probability.typical
    retries = 0
    while maximum is None or retries < maximum:
        if rng.random() >= probability:
            break
        retries += 1
        if maximum is None and retries >= UNBOUNDED_RETRY_LIMIT:
            raise _StepLimitReached
    return retries


def _activated_transitions(
    node: WorkflowNode,
    transitions: tuple[Transition, ...],
    *,
    node_by_id: Mapping[str, WorkflowNode],
    outgoing: Mapping[str, tuple[Transition, ...]],
    edge_counts: Mapping[tuple[str, str], int],
    graph_guard: GraphGuard,
    mode: RunMode,
    rng: random.Random | None,
    lookahead: _LookaheadBudget,
) -> tuple[Transition, ...]:
    always = [transition for transition in transitions if transition.activation == "always"]
    choices = [
        transition
        for transition in transitions
        if transition.activation == "choice" and _transition_is_possible(transition)
    ]
    if choices:
        if mode == "sample":
            if rng is None:  # pragma: no cover - protetto dai chiamanti interni.
                raise TypeError("Il campionamento richiede un generatore pseudocasuale")
            chosen = _sample_choice(choices, rng)
        else:
            chosen, _score = _select_choice(
                choices,
                mode=mode,
                node_by_id=node_by_id,
                outgoing=outgoing,
                edge_counts=edge_counts,
                graph_guard=graph_guard,
                remaining_steps=graph_guard.step_limit,
                lookahead=lookahead,
            )
        always.append(chosen)
    return tuple(sorted(always, key=lambda item: (item.parallel_group or "", item.target)))


def _transition_identity(transition: Transition) -> tuple[str, str, str, str | None]:
    """Chiave univoca di un arco, coerente con l'invariante dello schema."""
    return (
        transition.source,
        transition.target,
        transition.activation,
        transition.parallel_group,
    )


def _select_choice(
    choices: list[Transition],
    *,
    mode: RunMode,
    node_by_id: Mapping[str, WorkflowNode],
    outgoing: Mapping[str, tuple[Transition, ...]],
    edge_counts: Mapping[tuple[str, str], int],
    graph_guard: GraphGuard,
    remaining_steps: int,
    lookahead: _LookaheadBudget,
) -> tuple[Transition, tuple[int, int]]:
    """Valuta ogni ramo una volta sola e restituisce anche il punteggio del vincitore.

    Ripetere la valutazione nel giro dei gruppi rendeva la lookahead esponenziale
    nella profondità del percorso.
    """
    scored = [
        (
            _transition_score(
                transition,
                mode=mode,
                node_by_id=node_by_id,
                outgoing=outgoing,
                edge_counts=dict(edge_counts),
                graph_guard=graph_guard,
                remaining_steps=remaining_steps,
                lookahead=lookahead,
            ),
            transition.target,
            transition,
        )
        for transition in choices
    ]
    scored.sort(key=lambda item: (item[0], item[1]), reverse=mode == "max")
    score, _target, chosen = scored[0]
    return chosen, score


def _sample_choice(choices: list[Transition], rng: random.Random) -> Transition:
    weights, _fallback = _effective_choice_weights(choices)
    return rng.choices(choices, weights=weights, k=1)[0]


def _effective_choice_weights(
    choices: list[Transition],
) -> tuple[list[float], Literal["uniform", "residual"] | None]:
    declared = [
        choice.probability.typical if choice.probability is not None else None
        for choice in choices
    ]
    if all(weight is None for weight in declared):
        weights = [1.0] * len(choices)
        fallback: Literal["uniform", "residual"] | None = "uniform"
    elif any(weight is None for weight in declared):
        known_total = sum(weight or 0.0 for weight in declared)
        missing = sum(weight is None for weight in declared)
        remainder = max(0.0, 1.0 - known_total)
        missing_weight = remainder / missing if remainder > 0 else 0.0
        weights = [missing_weight if weight is None else weight for weight in declared]
        fallback = "residual"
        if not any(weights):
            weights = [1.0] * len(choices)
            fallback = "uniform"
    else:
        weights = [float(weight) for weight in declared if weight is not None]
        fallback = None
        if not any(weights):
            weights = [1.0] * len(choices)
            fallback = "uniform"
    return [float(weight) for weight in weights], fallback


def _node_score(node: WorkflowNode, *, mode: RunMode) -> tuple[int, int]:
    value_name = "min" if mode == "min" else "max"
    attempts = 1
    if mode == "max" and node.budget.retry_probability.max > 0:
        attempts += node.budget.max_retries or 0
    tokens = (
        getattr(node.budget.instructions, value_name)
        + getattr(node.budget.dynamic_context, value_name)
        + getattr(node.budget.output, value_name)
    ) * attempts
    latency = getattr(node.budget.latency_ms, value_name) * attempts
    return (tokens, latency)


def _transition_score(
    transition: Transition,
    *,
    mode: RunMode,
    node_by_id: Mapping[str, WorkflowNode],
    outgoing: Mapping[str, tuple[Transition, ...]],
    edge_counts: dict[tuple[str, str], int],
    graph_guard: GraphGuard,
    remaining_steps: int,
    lookahead: _LookaheadBudget,
) -> tuple[int, int]:
    key = (transition.source, transition.target)
    if (
        key in graph_guard.cyclic_edge_keys
        and edge_counts.get(key, 0) >= graph_guard.cyclic_edge_limit
    ):
        return (10**30, 10**30)
    edge_counts[key] = edge_counts.get(key, 0) + 1
    return _path_score(
        transition.target,
        mode=mode,
        node_by_id=node_by_id,
        outgoing=outgoing,
        edge_counts=edge_counts,
        graph_guard=graph_guard,
        remaining_steps=remaining_steps,
        lookahead=lookahead,
    )


def _path_score(
    node_id: str,
    *,
    mode: RunMode,
    node_by_id: Mapping[str, WorkflowNode],
    outgoing: Mapping[str, tuple[Transition, ...]],
    edge_counts: dict[tuple[str, str], int],
    graph_guard: GraphGuard,
    remaining_steps: int,
    lookahead: _LookaheadBudget,
) -> tuple[int, int]:
    if remaining_steps <= 0:
        return (10**30, 10**30)
    lookahead.spend()
    own_tokens, own_latency = _node_score(node_by_id[node_id], mode=mode)
    eligible = tuple(
        transition
        for transition in outgoing.get(node_id, ())
        if _transition_is_possible(transition)
        and (
            transition.max_traversals is None
            or edge_counts.get((transition.source, transition.target), 0)
            < transition.max_traversals
        )
    )
    activated = [transition for transition in eligible if transition.activation == "always"]
    choices = [transition for transition in eligible if transition.activation == "choice"]
    already_scored: dict[tuple[str, str, str, str | None], tuple[int, int]] = {}
    if choices:
        chosen, chosen_score = _select_choice(
            choices,
            mode=mode,
            node_by_id=node_by_id,
            outgoing=outgoing,
            edge_counts=edge_counts,
            graph_guard=graph_guard,
            remaining_steps=remaining_steps - 1,
            lookahead=lookahead,
        )
        activated.append(chosen)
        already_scored[_transition_identity(chosen)] = chosen_score

    downstream_tokens = 0
    downstream_latency = 0
    for group in _execution_groups(activated):
        group_tokens = 0
        group_latency = 0
        for transition in group:
            branch = already_scored.get(_transition_identity(transition))
            if branch is None:
                branch = _transition_score(
                    transition,
                    mode=mode,
                    node_by_id=node_by_id,
                    outgoing=outgoing,
                    edge_counts=dict(edge_counts),
                    graph_guard=graph_guard,
                    remaining_steps=remaining_steps - 1,
                    lookahead=lookahead,
                )
            branch_tokens, branch_latency = branch
            group_tokens += branch_tokens
            group_latency = max(group_latency, branch_latency)
        downstream_tokens += group_tokens
        downstream_latency += group_latency
    return (own_tokens + downstream_tokens, own_latency + downstream_latency)


def _execution_groups(transitions: list[Transition]) -> tuple[tuple[Transition, ...], ...]:
    """Raggruppa soltanto archi con lo stesso parallel_group; gli altri restano seriali."""
    groups: list[tuple[Transition, ...]] = []
    parallel: dict[str, list[Transition]] = {}
    order: list[str] = []
    for transition in transitions:
        if transition.parallel_group is None:
            groups.append((transition,))
            continue
        if transition.parallel_group not in parallel:
            parallel[transition.parallel_group] = []
            order.append(transition.parallel_group)
        parallel[transition.parallel_group].append(transition)
    groups.extend(tuple(parallel[group_id]) for group_id in order)
    return tuple(groups)


def _freeze_scenario(blueprint: Blueprint, state: _RunState) -> ScenarioTotals:
    models = {model.id: model for model in blueprint.models}
    executed_node_ids = set(state.node_totals)
    currencies = _used_currencies(blueprint, executed_node_ids)
    scenario_currency = next(iter(currencies)) if len(currencies) == 1 else None
    nodes: list[NodeTotals] = []
    for node in sorted(blueprint.nodes, key=lambda item: item.id):
        if node.id not in state.node_totals:
            continue
        totals = state.node_totals[node.id]
        cost, currency = _price_totals(totals, node.model_id, models)
        nodes.append(
            NodeTotals(
                node_id=node.id,
                agent_id=node.agent_id,
                model_id=node.model_id,
                executions=totals.executions,
                input_tokens=totals.input_tokens,
                output_tokens=totals.output_tokens,
                cache_read_tokens=totals.cache_read_tokens,
                cache_write_tokens=totals.cache_write_tokens,
                llm_calls=totals.llm_calls,
                tool_calls=totals.tool_calls,
                latency_ms=totals.latency_ms,
                cost=cost,
                currency=currency,
            )
        )

    agents: list[AgentTotals] = []
    for agent in sorted(blueprint.agents, key=lambda item: item.id):
        assigned = [node for node in nodes if node.agent_id == agent.id]
        agent_cost = _sum_costs(assigned, scenario_currency)
        agents.append(
            AgentTotals(
                agent_id=agent.id,
                executions=sum(node.executions for node in assigned),
                input_tokens=sum(node.input_tokens for node in assigned),
                output_tokens=sum(node.output_tokens for node in assigned),
                cache_read_tokens=sum(node.cache_read_tokens for node in assigned),
                cache_write_tokens=sum(node.cache_write_tokens for node in assigned),
                llm_calls=sum(node.llm_calls for node in assigned),
                tool_calls=sum(node.tool_calls for node in assigned),
                latency_ms=sum(node.latency_ms for node in assigned),
                cost=agent_cost,
                currency=scenario_currency if agent_cost is not None else None,
            )
        )

    scenario_cost = _sum_costs(nodes, scenario_currency)
    return ScenarioTotals(
        input_tokens=sum(node.input_tokens for node in nodes),
        output_tokens=sum(node.output_tokens for node in nodes),
        cache_read_tokens=sum(node.cache_read_tokens for node in nodes),
        cache_write_tokens=sum(node.cache_write_tokens for node in nodes),
        llm_calls=sum(node.llm_calls for node in nodes),
        tool_calls=sum(node.tool_calls for node in nodes),
        latency_ms=state.maximum_finish_ms,
        cost=scenario_cost,
        currency=scenario_currency if scenario_cost is not None else None,
        nodes=tuple(nodes),
        agents=tuple(agents),
    )


def _price_totals(
    totals: _MutableTotals,
    model_id: str | None,
    models: Mapping[str, ModelProfile],
) -> tuple[Decimal | None, str | None]:
    priced = (
        (totals.input_tokens, "input_price_per_million"),
        (totals.output_tokens, "output_price_per_million"),
        (totals.cache_read_tokens, "cache_read_price_per_million"),
        (totals.cache_write_tokens, "cache_write_price_per_million"),
    )
    if totals.unknown_tool_cost:
        return None, None

    model_cost = Decimal("0")
    model_currency = None
    if model_id is not None:
        profile = models[model_id]
        model_currency = profile.currency
        for amount, price_name in priced:
            if amount == 0:
                continue
            price = getattr(profile, price_name)
            if price is None:
                return None, None
            model_cost += Decimal(amount) * price / Decimal(1_000_000)

    currencies = {
        currency
        for currency in (model_currency, totals.fixed_tool_currency)
        if currency is not None
    }
    if len(currencies) > 1:
        return None, None
    currency = next(iter(currencies)) if currencies else None
    return model_cost + totals.fixed_tool_cost, currency


def _sum_costs(items: list[NodeTotals], currency: str | None) -> Decimal | None:
    if any(item.cost is None for item in items):
        return None
    nonempty_currencies = {item.currency for item in items if item.currency is not None}
    if len(nonempty_currencies) > 1 or (nonempty_currencies and currency is None):
        return None
    return sum((item.cost for item in items if item.cost is not None), Decimal("0"))


def _percentile_run(runs: list[ScenarioTotals], quantile: float) -> ScenarioTotals | None:
    if not runs:
        return None
    ordered = sorted(runs, key=_scenario_rank)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _scenario_rank(scenario: ScenarioTotals) -> tuple[int, int, int, int, int, int, str]:
    return (
        scenario.input_tokens + scenario.output_tokens,
        scenario.cache_read_tokens + scenario.cache_write_tokens,
        scenario.llm_calls,
        scenario.tool_calls,
        scenario.latency_ms,
        len(scenario.nodes),
        json.dumps(scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
    )


def _outgoing(transitions: tuple[Transition, ...]) -> dict[str, tuple[Transition, ...]]:
    grouped: dict[str, list[Transition]] = defaultdict(list)
    for transition in transitions:
        grouped[transition.source].append(transition)
    return {
        source: tuple(sorted(items, key=lambda item: (item.target, item.activation, item.parallel_group or "")))
        for source, items in grouped.items()
    }


def _transition_is_possible(transition: Transition) -> bool:
    return not (
        transition.activation == "choice"
        and transition.probability is not None
        and transition.probability.max == 0
    )


def _possible_transitions(blueprint: Blueprint) -> tuple[Transition, ...]:
    return tuple(
        transition
        for transition in blueprint.transitions
        if _transition_is_possible(transition)
    )


def _reachable_node_ids(blueprint: Blueprint) -> set[str]:
    return _reachable_with_transitions(
        blueprint.entry_node_ids, _possible_transitions(blueprint)
    )


def _reachable_with_transitions(
    entry_node_ids: tuple[str, ...], transitions: tuple[Transition, ...]
) -> set[str]:
    outgoing = _outgoing(transitions)
    reached = set(entry_node_ids)
    pending = list(sorted(reached))
    while pending:
        source = pending.pop()
        for transition in outgoing.get(source, ()):
            if transition.target not in reached:
                reached.add(transition.target)
                pending.append(transition.target)
    return reached


def _has_unbounded_maximum(blueprint: Blueprint) -> bool:
    reachable_node_ids = _reachable_node_ids(blueprint)
    if any(
        node.budget.max_retries is None and node.budget.retry_probability.max > 0
        for node in blueprint.nodes
        if node.id in reachable_node_ids
    ):
        return True
    return bool(_unlimited_cycle_nodes(blueprint))


def _is_inevitably_unbounded(blueprint: Blueprint) -> bool:
    always_edges = tuple(
        transition
        for transition in _possible_transitions(blueprint)
        if transition.activation == "always"
    )
    reachable_node_ids = _reachable_with_transitions(
        blueprint.entry_node_ids, always_edges
    )
    if any(
        node.budget.max_retries is None and node.budget.retry_probability.typical >= 1
        for node in blueprint.nodes
        if node.id in reachable_node_ids
    ):
        return True
    unlimited_always_edges = tuple(
        transition
        for transition in always_edges
        if transition.source in reachable_node_ids
        and transition.target in reachable_node_ids
        and transition.max_traversals is None
    )
    return bool(
        _cycle_nodes(tuple(sorted(reachable_node_ids)), unlimited_always_edges)
    )


def _unlimited_cycle_nodes(blueprint: Blueprint) -> tuple[str, ...]:
    reachable_node_ids = _reachable_node_ids(blueprint)
    unlimited = tuple(
        transition
        for transition in _possible_transitions(blueprint)
        if transition.source in reachable_node_ids
        and transition.target in reachable_node_ids
        and transition.max_traversals is None
    )
    return _cycle_nodes(tuple(sorted(reachable_node_ids)), unlimited)


def _cycle_nodes(node_ids: tuple[str, ...], transitions: tuple[Transition, ...]) -> tuple[str, ...]:
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for transition in transitions:
        adjacency[transition.source].append(transition.target)
    visiting: list[str] = []
    visited: set[str] = set()
    cycles: set[str] = set()

    def visit(node_id: str) -> None:
        visiting.append(node_id)
        for target in sorted(adjacency[node_id]):
            if target in visiting:
                cycles.update(visiting[visiting.index(target) :])
            elif target not in visited:
                visit(target)
        visiting.pop()
        visited.add(node_id)

    for node_id in sorted(node_ids):
        if node_id not in visited:
            visit(node_id)
    return tuple(sorted(cycles))


def _graph_guard(blueprint: Blueprint) -> GraphGuard:
    """Deriva il bound aciclico e limita separatamente gli archi di ciclo."""
    reachable_node_ids = _reachable_node_ids(blueprint)
    possible = tuple(
        transition
        for transition in _possible_transitions(blueprint)
        if transition.source in reachable_node_ids and transition.target in reachable_node_ids
    )
    unlimited = tuple(transition for transition in possible if transition.max_traversals is None)
    cyclic_edge_keys = _cyclic_edge_keys(unlimited)
    acyclic = tuple(
        transition
        for transition in possible
        if transition.max_traversals is None
        and (transition.source, transition.target) not in cyclic_edge_keys
    )

    acyclic_outgoing = _outgoing(acyclic)
    memo: dict[str, int] = {}

    def visits_from(node_id: str) -> int:
        if node_id not in memo:
            memo[node_id] = 1 + sum(
                visits_from(transition.target)
                for transition in acyclic_outgoing.get(node_id, ())
            )
        return memo[node_id]

    entry_visits = sum(visits_from(node_id) for node_id in blueprint.entry_node_ids)
    guarded_seed_visits = sum(
        (
            transition.max_traversals
            if transition.max_traversals is not None
            else UNBOUNDED_CYCLE_TRAVERSAL_LIMIT
        )
        * visits_from(transition.target)
        for transition in possible
        if transition not in acyclic
    )
    return GraphGuard(
        step_limit=max(1, entry_visits + guarded_seed_visits),
        cyclic_edge_keys=cyclic_edge_keys,
        cyclic_edge_limit=UNBOUNDED_CYCLE_TRAVERSAL_LIMIT,
    )


def _cyclic_edge_keys(
    transitions: tuple[Transition, ...],
) -> frozenset[tuple[str, str]]:
    """Trova gli archi illimitati per cui il target può tornare alla sorgente."""
    outgoing = _outgoing(transitions)

    def can_reach(start: str, target: str) -> bool:
        pending = [start]
        visited: set[str] = set()
        while pending:
            node_id = pending.pop()
            if node_id == target:
                return True
            if node_id in visited:
                continue
            visited.add(node_id)
            pending.extend(
                transition.target for transition in outgoing.get(node_id, ())
            )
        return False

    return frozenset(
        (transition.source, transition.target)
        for transition in transitions
        if can_reach(transition.target, transition.source)
    )


def _unknown_price_ids(
    blueprint: Blueprint, reachable_node_ids: set[str]
) -> tuple[str, ...]:
    models = {model.id: model for model in blueprint.models}
    unknown: set[str] = set()
    for node in blueprint.nodes:
        if node.id not in reachable_node_ids:
            continue
        if node.kind == "tool" and node.budget.fixed_tool_cost is None:
            unknown.add(
                f"tool:{node.tool_id}" if node.tool_id is not None else f"tool-node:{node.id}"
            )
        if node.model_id is None:
            continue
        profile = models[node.model_id]
        gross = node.budget.instructions.max + node.budget.dynamic_context.max
        needed = (
            (gross > 0 and node.budget.cacheable_fraction.min < 1, profile.input_price_per_million),
            (node.budget.output.max > 0, profile.output_price_per_million),
            (gross > 0 and node.budget.cacheable_fraction.max > 0, profile.cache_write_price_per_million),
            (
                gross > 0
                and node.budget.cacheable_fraction.max > 0
                and node.budget.retry_probability.max > 0
                and (node.budget.max_retries is None or node.budget.max_retries > 0),
                profile.cache_read_price_per_million,
            ),
        )
        if any(is_needed and price is None for is_needed, price in needed):
            unknown.add(node.model_id)
    return tuple(sorted(unknown))


def _used_currencies(blueprint: Blueprint, node_ids: set[str]) -> set[str]:
    models = {model.id: model for model in blueprint.models}
    currencies = {
        models[node.model_id].currency
        for node in blueprint.nodes
        if node.id in node_ids and node.model_id is not None
    }
    currencies.update(
        node.budget.fixed_tool_cost.currency
        for node in blueprint.nodes
        if node.id in node_ids and node.budget.fixed_tool_cost is not None
    )
    return currencies


def _declared_assumptions(blueprint: Blueprint) -> tuple[str, ...]:
    outgoing = _outgoing(blueprint.transitions)
    reachable_node_ids = _reachable_node_ids(blueprint)
    assumptions: list[str] = []
    for source, transitions in sorted(outgoing.items()):
        if source not in reachable_node_ids:
            continue
        choices = [
            transition
            for transition in transitions
            if transition.activation == "choice" and _transition_is_possible(transition)
        ]
        if choices and any(transition.probability is None for transition in choices):
            assumptions.append(
                f"Distribuzione uniform/inferred per i rami choice in uscita da {source} con probabilità mancanti."
            )
        elif choices and not any(
            transition.probability.typical
            for transition in choices
            if transition.probability is not None
        ):
            assumptions.append(
                f"Distribuzione uniform/inferred per i rami choice in uscita da {source} con pesi typical nulli."
            )
    return tuple(assumptions)


def _profile_hash(models: tuple[ModelProfile, ...]) -> str:
    payload = [model.model_dump(mode="json") for model in sorted(models, key=lambda item: item.id)]
    return _stable_hash(payload)


def _transition_basis_key(transition: Transition) -> str:
    """Identifica un arco senza dipendere dalla sua posizione nella collezione."""
    identity = (
        transition.source,
        transition.target,
        transition.activation,
        transition.parallel_group,
    )
    return "transition:" + json.dumps(
        identity, ensure_ascii=False, separators=(",", ":")
    )


def _quantitative_basis(
    blueprint: Blueprint, reachable_node_ids: set[str]
) -> tuple[QuantitativeBasis, ...]:
    entries: list[QuantitativeBasis] = []
    for node in blueprint.nodes:
        if node.id not in reachable_node_ids:
            continue
        entries.append(
            NodeQuantitativeBasis(
                key=f"node:{node.id}",
                instructions=node.budget.instructions,
                dynamic_context=node.budget.dynamic_context,
                output=node.budget.output,
                cacheable_fraction=node.budget.cacheable_fraction,
                latency_ms=node.budget.latency_ms,
                retry_probability=node.budget.retry_probability,
                max_retries=node.budget.max_retries,
                fixed_tool_cost=node.budget.fixed_tool_cost,
            )
        )

    reachable_transitions = [
        transition
        for transition in blueprint.transitions
        if transition.source in reachable_node_ids
        and transition.target in reachable_node_ids
        and _transition_is_possible(transition)
    ]
    entries.extend(
        TransitionQuantitativeBasis(
            key=_transition_basis_key(transition),
            source=transition.source,
            target=transition.target,
            activation=transition.activation,
            parallel_group=transition.parallel_group,
            probability=transition.probability,
            max_traversals=transition.max_traversals,
        )
        for transition in reachable_transitions
    )

    choice_by_source: dict[str, list[Transition]] = defaultdict(list)
    for transition in reachable_transitions:
        if transition.activation == "choice":
            choice_by_source[transition.source].append(transition)
    for source, choices in choice_by_source.items():
        ordered = sorted(choices, key=_transition_basis_key)
        weights, fallback = _effective_choice_weights(ordered)
        if fallback is None:
            continue
        entries.append(
            ChoiceGroupQuantitativeBasis(
                key=f"choice-group:{source}",
                source=source,
                fallback=fallback,
                branches=tuple(
                    ChoiceBranchWeight(
                        transition_key=_transition_basis_key(transition),
                        weight=weight,
                    )
                    for transition, weight in zip(ordered, weights, strict=True)
                ),
            )
        )
    return tuple(sorted(entries, key=lambda entry: entry.key))


def _assumptions_hash(
    quantitative_basis: tuple[QuantitativeBasis, ...],
    assumptions: tuple[str, ...],
) -> str:
    payload = {
        "algorithm_version": SIMULATION_ALGORITHM_VERSION,
        "quantitative_basis": [
            entry.model_dump(mode="json") for entry in quantitative_basis
        ],
        "fallback_assumptions": sorted(assumptions),
    }
    return _stable_hash(payload)


def _stable_hash(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _overall_confidence(
    blueprint: Blueprint, reachable_node_ids: set[str]
) -> Literal["high", "medium", "low"]:
    ranks = {"high": 0, "medium": 1, "low": 2}
    observed = [
        estimate.confidence
        for node in blueprint.nodes
        if node.id in reachable_node_ids
        for estimate in (
            node.budget.instructions,
            node.budget.dynamic_context,
            node.budget.output,
            node.budget.cacheable_fraction,
            node.budget.latency_ms,
            node.budget.retry_probability,
        )
    ]
    observed.extend(
        transition.probability.confidence
        for transition in blueprint.transitions
        if transition.source in reachable_node_ids
        and _transition_is_possible(transition)
        and transition.probability is not None
    )
    observed.extend(
        node.budget.fixed_tool_cost.confidence
        for node in blueprint.nodes
        if node.id in reachable_node_ids and node.budget.fixed_tool_cost is not None
    )
    if any(
        node.id in reachable_node_ids
        and node.kind == "tool"
        and node.budget.fixed_tool_cost is None
        for node in blueprint.nodes
    ):
        observed.append("low")
    return max(observed, key=ranks.__getitem__) if observed else "low"
