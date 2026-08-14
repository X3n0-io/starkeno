"""Correzioni JSON Patch atomiche e confronti puri per Preflight."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import math
from typing import Any, Literal

from pydantic import Field, model_validator

from starkeno.preflight_schema import Blueprint, Confidence, FrozenModel
from starkeno.preflight_simulate import ScenarioTotals, SimulationReport


PatchOp = Literal["test", "add", "remove", "replace"]
_PROTECTED_FIELDS = {"schema_version", "revision", "parent_revision", "confirmed"}


class PatchOperation(FrozenModel):
    """Una operazione del sottoinsieme JSON Patch supportato da Preflight."""

    op: PatchOp
    path: str
    value: Any = None

    @model_validator(mode="after")
    def value_compatibile(self) -> PatchOperation:
        if self.op in {"test", "add", "replace"} and "value" not in self.model_fields_set:
            raise ValueError(f"L'operazione {self.op} richiede value")
        if self.op == "remove" and "value" in self.model_fields_set:
            raise ValueError("L'operazione remove non accetta value")
        return self


class Correction(FrozenModel):
    """Correzione proposta, applicata atomicamente rispetto alle altre."""

    id: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    expected_impact: str = Field(min_length=1)
    confidence: Confidence
    tradeoff: str = Field(min_length=1)
    operations: tuple[PatchOperation, ...] = Field(min_length=1)


class PatchConflict(FrozenModel):
    """Motivo strutturato per cui una correzione non e stata applicata."""

    correction_id: str
    operation_index: int = Field(ge=0)
    path: str
    reason: str


class PatchResult(FrozenModel):
    """Esito del batch e correzioni capaci di ripristinarne il contenuto."""

    blueprint: Blueprint
    applied_correction_ids: tuple[str, ...]
    conflicts: tuple[PatchConflict, ...]
    inverse: tuple[Correction, ...]


class NumericDelta(FrozenModel):
    """Variazione assoluta e percentuale rispetto al valore precedente."""

    absolute: int | Decimal
    percent: Decimal | None


class ScenarioComparison(FrozenModel):
    """Delta di uno scenario; i valori restano assenti se manca uno dei lati."""

    before_present: bool
    after_present: bool
    input_tokens: NumericDelta | None
    output_tokens: NumericDelta | None
    cache_read_tokens: NumericDelta | None
    cache_write_tokens: NumericDelta | None
    total_tokens: NumericDelta | None
    llm_calls: NumericDelta | None
    tool_calls: NumericDelta | None
    latency_ms: NumericDelta | None
    cost: NumericDelta | None


class Comparison(FrozenModel):
    """Confronto fra tutte le viste simulate alle medesime condizioni."""

    before_blueprint_hash: str
    after_blueprint_hash: str
    effective_seed: int
    samples: int
    profile_hash: str
    algorithm_version: str
    before_assumptions_hash: str
    after_assumptions_hash: str
    optimistic: ScenarioComparison
    typical: ScenarioComparison
    prudent: ScenarioComparison
    maximum: ScenarioComparison


class _PatchError(ValueError):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(reason)
        self.path = path


def apply_corrections(
    blueprint: Blueprint,
    corrections: tuple[Correction, ...],
) -> PatchResult:
    """Applica un batch ordinato senza mutare l'originale o sollevare sui conflitti."""
    working = blueprint.model_dump(mode="json")
    applied_ids: list[str] = []
    conflicts: list[PatchConflict] = []
    inverse_corrections: list[Correction] = []

    for item in corrections:
        candidate = deepcopy(working)
        inverse_chunks: list[tuple[PatchOperation, ...]] = []
        operation_index = 0
        operation_path = ""
        try:
            for operation_index, patch in enumerate(item.operations):
                operation_path = patch.path
                _ensure_writable_path(patch.path, patch.op)
                inverse = _apply_operation(candidate, patch)
                if inverse:
                    inverse_chunks.append(inverse)
            Blueprint.model_validate(candidate)
        except ValueError as exc:
            path = exc.path if isinstance(exc, _PatchError) else operation_path
            conflicts.append(
                PatchConflict(
                    correction_id=item.id,
                    operation_index=operation_index,
                    path=path,
                    reason=str(exc),
                )
            )
            continue

        working = candidate
        applied_ids.append(item.id)
        inverse_operations = tuple(
            inverse_operation
            for chunk in reversed(inverse_chunks)
            for inverse_operation in chunk
        )
        if inverse_operations:
            inverse_corrections.append(
                Correction(
                    id=f"inverse:{item.id}",
                    evidence=f"Ripristina la correzione {item.id}.",
                    expected_impact="Ripristino del contenuto precedente.",
                    confidence="high",
                    tradeoff="Annulla l'impatto della correzione originale.",
                    operations=inverse_operations,
                )
            )

    if not applied_ids:
        return PatchResult(
            blueprint=blueprint,
            applied_correction_ids=(),
            conflicts=tuple(conflicts),
            inverse=(),
        )

    working["revision"] = blueprint.revision + 1
    working["parent_revision"] = blueprint.revision
    revised = Blueprint.model_validate(working)
    return PatchResult(
        blueprint=revised,
        applied_correction_ids=tuple(applied_ids),
        conflicts=tuple(conflicts),
        inverse=tuple(reversed(inverse_corrections)),
    )


def compare_reports(before: SimulationReport, after: SimulationReport) -> Comparison:
    """Confronta report prodotti con condizioni esterne e basi condivise uguali."""
    conditions_before = (
        before.effective_seed,
        before.samples,
        before.profile_hash,
        before.algorithm_version,
    )
    conditions_after = (
        after.effective_seed,
        after.samples,
        after.profile_hash,
        after.algorithm_version,
    )
    if conditions_before != conditions_after:
        raise ValueError(
            "I report devono essere simulati alle stesse condizioni "
            "(effective_seed, samples, profile_hash e algorithm_version)."
        )
    _ensure_same_shared_quantitative_basis(before, after)
    _ensure_same_scenario_currencies(before, after)
    return Comparison(
        before_blueprint_hash=before.blueprint_hash,
        after_blueprint_hash=after.blueprint_hash,
        effective_seed=before.effective_seed,
        samples=before.samples,
        profile_hash=before.profile_hash,
        algorithm_version=before.algorithm_version,
        before_assumptions_hash=before.assumptions_hash,
        after_assumptions_hash=after.assumptions_hash,
        optimistic=_compare_scenario(before.optimistic, after.optimistic),
        typical=_compare_scenario(before.typical, after.typical),
        prudent=_compare_scenario(before.prudent, after.prudent),
        maximum=_compare_scenario(before.maximum, after.maximum),
    )


def _ensure_same_shared_quantitative_basis(
    before: SimulationReport, after: SimulationReport
) -> None:
    before_by_key = _unique_quantitative_basis(before, label="before")
    after_by_key = _unique_quantitative_basis(after, label="after")
    for key in sorted(before_by_key.keys() & after_by_key.keys()):
        if before_by_key[key] != after_by_key[key]:
            raise ValueError(
                "I report devono essere simulati alle stesse condizioni: "
                f"la base quantitativa condivisa {key} e diversa."
            )


def _unique_quantitative_basis(
    report: SimulationReport, *, label: str
) -> dict[str, object]:
    by_key: dict[str, object] = {}
    duplicates: set[str] = set()
    for entry in report.quantitative_basis:
        if entry.key in by_key:
            duplicates.add(entry.key)
        else:
            by_key[entry.key] = entry
    if duplicates:
        raise ValueError(
            "I report devono essere simulati alle stesse condizioni: "
            f"la base quantitativa {label} contiene chiavi duplicate: "
            + ", ".join(sorted(duplicates))
            + "."
        )
    return by_key


def _ensure_writable_path(path: str, op: PatchOp) -> None:
    """Vieta le sole scritture: una precondizione test non muta il documento."""
    tokens = _pointer_tokens(path)
    if op == "test":
        return
    if not tokens:
        raise _PatchError(path, "La radice del Blueprint e protetta")
    if tokens[0] in _PROTECTED_FIELDS:
        raise _PatchError(path, f"Il campo {tokens[0]} e protetto")
    if op == "remove" and len(tokens) == 1:
        raise _PatchError(
            path,
            f"Il campo di primo livello {tokens[0]} si sostituisce con replace: "
            "un remove alla radice non e invertibile perche il contenitore genitore "
            "porta revision e parent_revision, diversi a ogni revisione",
        )


def _pointer_tokens(path: str) -> tuple[str, ...]:
    if path == "":
        return ()
    if not path.startswith("/"):
        raise _PatchError(path, "JSON Pointer deve iniziare con '/'")
    return tuple(_unescape_token(token, path) for token in path[1:].split("/"))


def _unescape_token(token: str, path: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(token):
        if token[index] != "~":
            decoded.append(token[index])
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
            raise _PatchError(path, "Escape JSON Pointer non valido")
        decoded.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(decoded)


def _apply_operation(document: Any, patch: PatchOperation) -> tuple[PatchOperation, ...]:
    tokens = _pointer_tokens(patch.path)
    if patch.op == "test":
        actual = _read(document, tokens, patch.path)
        if not _json_equal(actual, patch.value):
            raise _PatchError(patch.path, "La precondizione test non corrisponde")
        return ()

    parent, token = _parent(document, tokens, patch.path)
    if patch.op == "add":
        return _add(parent, token, patch.path, deepcopy(patch.value))
    if patch.op == "remove":
        return _remove(parent, token, patch.path)
    return _replace(parent, token, patch.path, deepcopy(patch.value))


def _parent(document: Any, tokens: tuple[str, ...], path: str) -> tuple[Any, str]:
    if not tokens:
        raise _PatchError(path, "La radice del Blueprint e protetta")
    return _read(document, tokens[:-1], path), tokens[-1]


def _read(document: Any, tokens: tuple[str, ...], path: str) -> Any:
    current = document
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                raise _PatchError(path, f"Il percorso non esiste: {path}")
            current = current[token]
        elif isinstance(current, list):
            index = _array_index(token, len(current), path, allow_end=False)
            current = current[index]
        else:
            raise _PatchError(path, f"Il percorso attraversa un valore scalare: {path}")
    return current


def _array_index(token: str, length: int, path: str, *, allow_end: bool) -> int:
    if token == "-":
        if allow_end:
            return length
        raise _PatchError(path, "'-' e valido soltanto per add")
    if not token.isascii() or not token.isdigit() or (len(token) > 1 and token[0] == "0"):
        raise _PatchError(path, f"Indice array non valido: {token}")
    index = int(token)
    maximum = length if allow_end else length - 1
    if index > maximum:
        raise _PatchError(path, f"Indice array fuori limite: {token}")
    return index


def _add(parent: Any, token: str, path: str, value: Any) -> tuple[PatchOperation, ...]:
    if isinstance(parent, dict):
        if token in parent:
            previous = deepcopy(parent[token])
            parent[token] = value
            return (
                PatchOperation(op="test", path=path, value=deepcopy(value)),
                PatchOperation(op="replace", path=path, value=previous),
            )
        parent[token] = value
        return (
            PatchOperation(op="test", path=path, value=deepcopy(value)),
            PatchOperation(op="remove", path=path),
        )
    if isinstance(parent, list):
        index = _array_index(token, len(parent), path, allow_end=True)
        parent.insert(index, value)
        actual_path = _path_with_last_token(path, str(index))
        return (
            PatchOperation(op="test", path=actual_path, value=deepcopy(value)),
            PatchOperation(op="remove", path=actual_path),
        )
    raise _PatchError(path, "add richiede un contenitore object o array")


def _remove(parent: Any, token: str, path: str) -> tuple[PatchOperation, ...]:
    if isinstance(parent, dict):
        if token not in parent:
            raise _PatchError(path, f"Il percorso non esiste: {path}")
        removed = deepcopy(parent.pop(token))
    elif isinstance(parent, list):
        index = _array_index(token, len(parent), path, allow_end=False)
        removed = deepcopy(parent.pop(index))
    else:
        raise _PatchError(path, "remove richiede un contenitore object o array")
    parent_path = _parent_path(path)
    return (
        PatchOperation(op="test", path=parent_path, value=deepcopy(parent)),
        PatchOperation(op="add", path=path, value=removed),
    )


def _replace(parent: Any, token: str, path: str, value: Any) -> tuple[PatchOperation, ...]:
    if isinstance(parent, dict):
        if token not in parent:
            raise _PatchError(path, f"Il percorso non esiste: {path}")
        previous = deepcopy(parent[token])
        parent[token] = value
    elif isinstance(parent, list):
        index = _array_index(token, len(parent), path, allow_end=False)
        previous = deepcopy(parent[index])
        parent[index] = value
    else:
        raise _PatchError(path, "replace richiede un contenitore object o array")
    return (
        PatchOperation(op="test", path=path, value=deepcopy(value)),
        PatchOperation(op="replace", path=path, value=previous),
    )


def _parent_path(path: str) -> str:
    return path.rsplit("/", 1)[0]


def _path_with_last_token(path: str, token: str) -> str:
    return f"{_parent_path(path)}/{token}"


def _json_equal(left: Any, right: Any) -> bool:
    """Confronta valori JSON senza equiparare booleani e numeri Python."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _is_json_number(left) or _is_json_number(right):
        return (
            _is_json_number(left)
            and _is_json_number(right)
            and _finite_decimal(left) == _finite_decimal(right)
        )
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_json_equal(a, b) for a, b in zip(left, right, strict=True))
        )
    if isinstance(left, dict) or isinstance(right, dict):
        return (
            isinstance(left, dict)
            and isinstance(right, dict)
            and all(isinstance(key, str) for key in left)
            and all(isinstance(key, str) for key in right)
            and left.keys() == right.keys()
            and all(_json_equal(left[key], right[key]) for key in left)
        )
    return False


def _is_json_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Decimal):
        return value.is_finite()
    return True


def _finite_decimal(value: int | float | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _ensure_same_scenario_currencies(
    before: SimulationReport,
    after: SimulationReport,
) -> None:
    for name in ("optimistic", "typical", "prudent", "maximum"):
        before_scenario = getattr(before, name)
        after_scenario = getattr(after, name)
        if (
            before_scenario is not None
            and after_scenario is not None
            and before_scenario.currency != after_scenario.currency
        ):
            raise ValueError(
                "I report devono essere simulati alle stesse condizioni di valuta "
                f"per lo scenario {name}."
            )


def _compare_scenario(
    before: ScenarioTotals | None,
    after: ScenarioTotals | None,
) -> ScenarioComparison:
    if before is None or after is None:
        return ScenarioComparison(
            before_present=before is not None,
            after_present=after is not None,
            input_tokens=None,
            output_tokens=None,
            cache_read_tokens=None,
            cache_write_tokens=None,
            total_tokens=None,
            llm_calls=None,
            tool_calls=None,
            latency_ms=None,
            cost=None,
        )
    before_total = (
        before.input_tokens
        + before.output_tokens
        + before.cache_read_tokens
        + before.cache_write_tokens
    )
    after_total = (
        after.input_tokens
        + after.output_tokens
        + after.cache_read_tokens
        + after.cache_write_tokens
    )
    return ScenarioComparison(
        before_present=True,
        after_present=True,
        input_tokens=_delta(before.input_tokens, after.input_tokens),
        output_tokens=_delta(before.output_tokens, after.output_tokens),
        cache_read_tokens=_delta(before.cache_read_tokens, after.cache_read_tokens),
        cache_write_tokens=_delta(before.cache_write_tokens, after.cache_write_tokens),
        total_tokens=_delta(before_total, after_total),
        llm_calls=_delta(before.llm_calls, after.llm_calls),
        tool_calls=_delta(before.tool_calls, after.tool_calls),
        latency_ms=_delta(before.latency_ms, after.latency_ms),
        cost=_delta(before.cost, after.cost)
        if before.cost is not None and after.cost is not None
        else None,
    )


def _delta(before: int | Decimal, after: int | Decimal) -> NumericDelta:
    absolute = after - before
    percent = None
    if before != 0:
        percent = (Decimal(after) - Decimal(before)) * Decimal(100) / Decimal(before)
    return NumericDelta(absolute=absolute, percent=percent)
