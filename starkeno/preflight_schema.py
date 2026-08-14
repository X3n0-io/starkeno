"""Contratto immutabile e serializzazione sicura del Blueprint Preflight."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Provenance = Literal["measured", "declared", "inferred", "default"]
Confidence = Literal["high", "medium", "low"]


class FrozenModel(BaseModel):
    """Base comune: i dati validati non cambiano e non accettano campi impliciti."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class IntEstimate(FrozenModel):
    min: int = Field(ge=0)
    typical: int = Field(ge=0)
    max: int = Field(ge=0)
    provenance: Provenance
    confidence: Confidence
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordinato(self) -> IntEstimate:
        if not self.min <= self.typical <= self.max:
            raise ValueError("min, typical e max devono essere ordinati")
        return self


class RatioEstimate(FrozenModel):
    min: float = Field(ge=0, le=1)
    typical: float = Field(ge=0, le=1)
    max: float = Field(ge=0, le=1)
    provenance: Provenance
    confidence: Confidence
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordinato(self) -> RatioEstimate:
        if not self.min <= self.typical <= self.max:
            raise ValueError("min, typical e max devono essere ordinati")
        return self


class MoneyEstimate(FrozenModel):
    min: Decimal = Field(ge=0)
    typical: Decimal = Field(ge=0)
    max: Decimal = Field(ge=0)
    currency: str = Field(min_length=1)
    provenance: Provenance
    confidence: Confidence
    reason: str = Field(min_length=1)

    @field_validator("currency")
    @classmethod
    def valuta_non_vuota(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("currency non puo essere vuota")
        return value

    @model_validator(mode="after")
    def ordinato(self) -> MoneyEstimate:
        if not self.min <= self.typical <= self.max:
            raise ValueError("min, typical e max devono essere ordinati")
        return self


class Goal(FrozenModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    deliverable: str = Field(min_length=1)
    success_criteria: tuple[str, ...] = Field(default_factory=tuple)


class Agent(FrozenModel):
    id: str = Field(min_length=1)
    responsibility: str = Field(min_length=1)
    inputs: tuple[str, ...] = Field(default_factory=tuple)
    output: str = Field(min_length=1)
    model_id: str | None = None
    tool_ids: tuple[str, ...] = Field(default_factory=tuple)
    skill_ids: tuple[str, ...] = Field(default_factory=tuple)


class ToolSpec(FrozenModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class SkillSpec(FrozenModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ContextSource(FrozenModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source: Provenance


class NodeBudget(FrozenModel):
    instructions: IntEstimate
    dynamic_context: IntEstimate
    output: IntEstimate
    cacheable_fraction: RatioEstimate
    latency_ms: IntEstimate
    retry_probability: RatioEstimate
    max_retries: int | None = Field(default=None, ge=0)
    fixed_tool_cost: MoneyEstimate | None = None


class WorkflowNode(FrozenModel):
    id: str = Field(min_length=1)
    kind: Literal["llm", "tool", "deterministic", "human", "gate", "handoff"]
    description: str = Field(min_length=1)
    agent_id: str | None = None
    model_id: str | None = None
    tool_id: str | None = None
    skill_ids: tuple[str, ...] = Field(default_factory=tuple)
    context_ids: tuple[str, ...] = Field(default_factory=tuple)
    budget: NodeBudget

    @model_validator(mode="after")
    def costo_fisso_solo_tool(self) -> WorkflowNode:
        if self.kind != "tool" and self.budget.fixed_tool_cost is not None:
            raise ValueError("fixed_tool_cost puo essere dichiarato solo da un nodo tool")
        return self


class Transition(FrozenModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    activation: Literal["choice", "always"]
    probability: RatioEstimate | None = None
    parallel_group: str | None = None
    max_traversals: int | None = Field(default=None, ge=1)


class ModelProfile(FrozenModel):
    id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    name: str = Field(min_length=1)
    input_price_per_million: Decimal | None = Field(default=None, ge=0)
    output_price_per_million: Decimal | None = Field(default=None, ge=0)
    cache_read_price_per_million: Decimal | None = Field(default=None, ge=0)
    cache_write_price_per_million: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(min_length=1)
    price_verified_at: date | None = None
    source: str | None = None


def _duplicate_ids(items: tuple[Any, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        if item.id in seen and item.id not in duplicates:
            duplicates.append(item.id)
        seen.add(item.id)
    return tuple(duplicates)


class Blueprint(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    revision: int = Field(ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    confirmed: bool
    goal: Goal
    agents: tuple[Agent, ...] = Field(default_factory=tuple)
    tools: tuple[ToolSpec, ...] = Field(default_factory=tuple)
    skills: tuple[SkillSpec, ...] = Field(default_factory=tuple)
    contexts: tuple[ContextSource, ...] = Field(default_factory=tuple)
    nodes: tuple[WorkflowNode, ...] = Field(default_factory=tuple)
    transitions: tuple[Transition, ...] = Field(default_factory=tuple)
    models: tuple[ModelProfile, ...] = Field(default_factory=tuple)
    entry_node_ids: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def riferimenti_validi(self) -> Blueprint:
        if self.parent_revision is not None and self.parent_revision >= self.revision:
            raise ValueError("parent_revision deve essere strettamente minore di revision")
        collections = (
            ("agents", self.agents),
            ("tools", self.tools),
            ("skills", self.skills),
            ("contexts", self.contexts),
            ("nodes", self.nodes),
            ("models", self.models),
        )
        for name, items in collections:
            if duplicates := _duplicate_ids(items):
                raise ValueError(f"ID duplicati in {name}: {', '.join(duplicates)}")

        seen_transition_keys: set[tuple[str, str, str, str | None]] = set()
        duplicate_transition_keys: list[tuple[str, str, str, str | None]] = []
        for transition in self.transitions:
            key = (
                transition.source,
                transition.target,
                transition.activation,
                transition.parallel_group,
            )
            if key in seen_transition_keys and key not in duplicate_transition_keys:
                duplicate_transition_keys.append(key)
            seen_transition_keys.add(key)
        if duplicate_transition_keys:
            details = "; ".join(
                f"source={source}, target={target}, activation={activation}, "
                f"parallel_group={parallel_group!r}"
                for source, target, activation, parallel_group in duplicate_transition_keys
            )
            raise ValueError(
                "transizioni duplicate per "
                "(source, target, activation, parallel_group): " + details
            )

        agent_ids = {agent.id for agent in self.agents}
        tool_ids = {tool.id for tool in self.tools}
        skill_ids = {skill.id for skill in self.skills}
        context_ids = {context.id for context in self.contexts}
        node_ids = {node.id for node in self.nodes}
        model_ids = {model.id for model in self.models}

        for agent in self.agents:
            _require_references(f"agent {agent.id}", agent.tool_ids, tool_ids, "tool")
            _require_references(f"agent {agent.id}", agent.skill_ids, skill_ids, "skill")
            _require_optional_reference(f"agent {agent.id}", agent.model_id, model_ids, "model")
        for node in self.nodes:
            _require_optional_reference(f"node {node.id}", node.agent_id, agent_ids, "agent")
            _require_optional_reference(f"node {node.id}", node.model_id, model_ids, "model")
            _require_optional_reference(f"node {node.id}", node.tool_id, tool_ids, "tool")
            _require_references(f"node {node.id}", node.skill_ids, skill_ids, "skill")
            _require_references(f"node {node.id}", node.context_ids, context_ids, "context")
        _require_references("entry_node_ids", self.entry_node_ids, node_ids, "node")
        for transition in self.transitions:
            _require_references("transition source", (transition.source,), node_ids, "node")
            _require_references("transition target", (transition.target,), node_ids, "node")
        return self


def _require_references(owner: str, references: tuple[str, ...], known: set[str], kind: str) -> None:
    missing = sorted(set(references) - known)
    if missing:
        raise ValueError(f"{owner} riferisce {kind} inesistente: {', '.join(missing)}")


def _require_optional_reference(owner: str, reference: str | None, known: set[str], kind: str) -> None:
    if reference is not None:
        _require_references(owner, (reference,), known, kind)


def _format_hint(text: str, format_hint: str | None) -> Literal["json", "yaml"]:
    if format_hint is None:
        return "json" if text.lstrip().startswith(("{", "[")) else "yaml"
    normalized = format_hint.lower()
    if normalized not in {"json", "yaml"}:
        raise ValueError(f"Formato Blueprint non supportato: {format_hint}")
    return normalized  # type: ignore[return-value]


def load_blueprint(text: str, *, format_hint: str | None = None) -> Blueprint:
    """Carica un Blueprint JSON o YAML senza eseguire costruttori arbitrari."""
    format = _format_hint(text, format_hint)
    try:
        payload = json.loads(text) if format == "json" else yaml.safe_load(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON non valido alla posizione {exc.pos}: {exc.msg}") from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        position = ""
        if mark is not None:
            position = f" alla riga {mark.line + 1}, colonna {mark.column + 1}"
        raise ValueError(f"YAML non valido{position}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"La radice {format.upper()} deve essere una mapping")
    return Blueprint.model_validate(payload)


def dump_blueprint(blueprint: Blueprint, *, format: Literal["json", "yaml"]) -> str:
    """Serializza in forma stabile un Blueprint gi\u00e0 validato."""
    payload = blueprint.model_dump(mode="json")
    if format == "json":
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    if format == "yaml":
        return yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)
    raise ValueError(f"Formato Blueprint non supportato: {format}")


def blueprint_hash(blueprint: Blueprint) -> str:
    """Restituisce SHA-256 del JSON canonico, usabile come seed riproducibile."""
    payload = blueprint.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
