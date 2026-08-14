from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from starkeno.preflight_patch import (
    Correction,
    PatchOperation,
    apply_corrections,
    compare_reports,
)
from starkeno.preflight_schema import Blueprint
from starkeno.preflight_simulate import (
    SIMULATION_ALGORITHM_VERSION,
    ScenarioTotals,
    SimulationReport,
    TransitionQuantitativeBasis,
    simulate_blueprint,
)


FIXTURE = Path(__file__).parent / "fixtures" / "preflight" / "minimal.json"


def make_blueprint(*, confirmed: bool = True) -> Blueprint:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = confirmed
    frontier = dict(payload["models"][0])
    frontier.update({"id": "frontier", "name": "Example Frontier"})
    payload["models"].append(frontier)
    payload["agents"][0]["model_id"] = "frontier"
    payload["nodes"][0]["model_id"] = "frontier"
    return Blueprint.model_validate(payload)


def correction(
    correction_id: str,
    *operations: PatchOperation,
) -> Correction:
    return Correction(
        id=correction_id,
        evidence="Il modello costa piu del necessario.",
        expected_impact="Riduzione del costo.",
        confidence="high",
        tradeoff="Minore capacita del modello.",
        operations=operations,
    )


def operation(op: str, path: str, value: object | None = None) -> PatchOperation:
    if op == "remove":
        return PatchOperation(op=op, path=path)
    return PatchOperation(op=op, path=path, value=value)


def scenario(
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    llm_calls: int = 1,
    tool_calls: int = 0,
    latency_ms: int = 100,
    cost: Decimal | None = Decimal("1.20"),
) -> ScenarioTotals:
    return ScenarioTotals(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=0,
        cache_write_tokens=0,
        llm_calls=llm_calls,
        tool_calls=tool_calls,
        latency_ms=latency_ms,
        cost=cost,
        currency="USD" if cost is not None else None,
        nodes=(),
        agents=(),
    )


def report(
    *,
    blueprint_hash: str = "before",
    effective_seed: int = 7,
    samples: int = 20,
    profile_hash: str = "profile",
    assumptions_hash: str = "assumptions",
    algorithm_version: str = SIMULATION_ALGORITHM_VERSION,
    quantitative_basis: tuple[object, ...] = (),
    optimistic: ScenarioTotals | None = None,
    typical: ScenarioTotals | None = None,
    prudent: ScenarioTotals | None = None,
    maximum: ScenarioTotals | None = None,
) -> SimulationReport:
    return SimulationReport(
        blueprint_hash=blueprint_hash,
        effective_seed=effective_seed,
        samples=samples,
        completed_samples=samples,
        profile_hash=profile_hash,
        assumptions_hash=assumptions_hash,
        algorithm_version=algorithm_version,
        quantitative_basis=quantitative_basis,
        optimistic=optimistic,
        typical=typical,
        prudent=prudent,
        maximum_status="finite" if maximum is not None else "unbounded",
        maximum=maximum,
        unknown_prices=(),
        assumptions=(),
        confidence="high",
    )


def test_remove_di_un_campo_top_level_e_rifiutato_perche_non_invertibile():
    """L'inversa di un remove testa il contenitore genitore: per un campo di primo
    livello quel contenitore e la radice, che porta revision e parent_revision sempre
    diversi, quindi il ripristino falliva in silenzio e il contenuto restava perso."""
    original = make_blueprint()

    result = apply_corrections(
        original, (correction("svuota-entry", operation("remove", "/entry_node_ids")),)
    )

    assert result.blueprint == original
    assert result.applied_correction_ids == ()
    assert result.inverse == ()
    assert result.conflicts[0].correction_id == "svuota-entry"
    assert result.conflicts[0].path == "/entry_node_ids"
    assert "replace" in result.conflicts[0].reason


def test_test_su_campo_protetto_e_ammesso_perche_non_scrive():
    """Una precondizione di sola lettura non e una scrittura: vietarla impediva di
    ancorare una correzione allo stato di conferma della revisione."""
    original = make_blueprint()

    result = apply_corrections(
        original,
        (
            correction(
                "ancorata-alla-conferma",
                operation("test", "/confirmed", True),
                operation("replace", "/goal/deliverable", "Nota rivista."),
            ),
        ),
    )

    assert result.conflicts == ()
    assert result.applied_correction_ids == ("ancorata-alla-conferma",)
    assert result.blueprint.goal.deliverable == "Nota rivista."


def test_batch_applica_correzioni_in_ordine_con_una_sola_revisione():
    original = make_blueprint()
    first = correction(
        "economy-model",
        operation("test", "/nodes/0/model_id", "frontier"),
        operation("replace", "/nodes/0/model_id", "economy"),
    )
    second = correction(
        "shorter-output",
        operation("test", "/nodes/0/budget/output/typical", 150),
        operation("replace", "/nodes/0/budget/output/typical", 120),
    )

    result = apply_corrections(original, (first, second))

    assert result.applied_correction_ids == ("economy-model", "shorter-output")
    assert result.conflicts == ()
    assert result.blueprint.revision == original.revision + 1
    assert result.blueprint.parent_revision == original.revision
    assert result.blueprint.nodes[0].model_id == "economy"
    assert result.blueprint.nodes[0].budget.output.typical == 120
    assert original.nodes[0].model_id == "frontier"
    assert original.nodes[0].budget.output.typical == 150


def test_correzione_e_atomica_e_il_conflitto_non_annulla_quella_precedente():
    original = make_blueprint()
    accepted = correction(
        "accepted",
        operation("replace", "/nodes/0/description", "Bozza economica."),
    )
    conflicting = correction(
        "conflicting",
        operation("replace", "/goal/deliverable", "Testo breve."),
        operation("test", "/nodes/0/model_id", "missing"),
        operation("replace", "/nodes/0/model_id", "economy"),
    )

    result = apply_corrections(original, (accepted, conflicting))

    assert result.blueprint.nodes[0].description == "Bozza economica."
    assert result.blueprint.goal.deliverable == original.goal.deliverable
    assert result.blueprint.nodes[0].model_id == "frontier"
    assert result.applied_correction_ids == ("accepted",)
    assert result.conflicts[0].correction_id == "conflicting"


def test_se_nessuna_correzione_riesce_restituisce_l_originale_invariato():
    original = make_blueprint()
    bad = correction(
        "stale",
        operation("test", "/nodes/0/model_id", "missing"),
        operation("replace", "/nodes/0/model_id", "economy"),
    )

    result = apply_corrections(original, (bad,))

    assert result.blueprint is original
    assert result.inverse == ()
    assert result.applied_correction_ids == ()
    assert result.conflicts[0].correction_id == "stale"


@pytest.mark.parametrize(
    "path",
    ["", "/schema_version", "/revision", "/parent_revision", "/confirmed"],
)
def test_radice_e_campi_di_lineage_sono_protetti(path: str):
    original = make_blueprint()
    protected = correction("protected", operation("replace", path, {}))

    result = apply_corrections(original, (protected,))

    assert result.blueprint is original
    assert result.conflicts[0].path == path


def test_inverse_ripristina_remove_e_replace_in_ordine_interno_e_globale_inverso():
    original = make_blueprint()
    first = correction(
        "first",
        operation("test", "/goal/success_criteria/0", "Contiene le modifiche verificabili."),
        operation("remove", "/goal/success_criteria/0"),
        operation("add", "/goal/success_criteria/0", "Criterio temporaneo."),
        operation("replace", "/goal/description", "Preparare la pubblicazione."),
    )
    second = correction(
        "second",
        operation("test", "/goal/description", "Preparare la pubblicazione."),
        operation("replace", "/goal/description", "Pubblicare una nota."),
    )

    applied = apply_corrections(original, (first, second))
    restored = apply_corrections(applied.blueprint, applied.inverse)

    assert tuple(item.id for item in applied.inverse) == (
        "inverse:second",
        "inverse:first",
    )
    assert restored.conflicts == ()
    assert restored.blueprint.model_dump(exclude={"revision", "parent_revision"}) == (
        original.model_dump(exclude={"revision", "parent_revision"})
    )
    assert restored.blueprint.revision == applied.blueprint.revision + 1
    assert restored.blueprint.parent_revision == applied.blueprint.revision


def test_json_pointer_gestisce_array_append_e_indici_e_rifiuta_escape_malformato():
    original = make_blueprint()
    append = correction(
        "append",
        operation("add", "/goal/success_criteria/-", "Revisionata da una persona."),
    )
    malformed = correction(
        "bad-escape",
        operation("replace", "/goal/description~2", "Non applicare."),
    )

    result = apply_corrections(original, (append, malformed))

    assert result.blueprint.goal.success_criteria == (
        "Contiene le modifiche verificabili.",
        "Revisionata da una persona.",
    )
    assert result.conflicts[0].correction_id == "bad-escape"
    restored = apply_corrections(result.blueprint, result.inverse)
    assert restored.conflicts == ()
    assert restored.blueprint.goal.success_criteria == original.goal.success_criteria


def test_json_pointer_decodifica_escape_tilde_e_slash_rfc6901():
    original = make_blueprint()
    escaped = correction(
        "escaped",
        operation("add", "/goal/temporary~0key", "tilde"),
        operation("test", "/goal/temporary~0key", "tilde"),
        operation("remove", "/goal/temporary~0key"),
        operation("add", "/goal/temporary~1key", "slash"),
        operation("test", "/goal/temporary~1key", "slash"),
        operation("remove", "/goal/temporary~1key"),
    )

    result = apply_corrections(original, (escaped,))

    assert result.conflicts == ()
    assert result.applied_correction_ids == ("escaped",)
    assert result.blueprint.goal == original.goal


def test_precondizione_json_distingue_booleano_da_numero():
    original = make_blueprint()
    bool_as_number = correction(
        "bool-as-number",
        operation("add", "/goal/temporary", True),
        operation("test", "/goal/temporary", 1),
        operation("remove", "/goal/temporary"),
    )

    result = apply_corrections(original, (bool_as_number,))

    assert result.blueprint is original
    assert result.applied_correction_ids == ()
    assert result.conflicts[0].correction_id == "bool-as-number"


def test_precondizione_json_confronta_strutture_annidate_per_tipo_e_valore():
    original = make_blueprint()
    nested_mismatch = correction(
        "nested-mismatch",
        operation(
            "add",
            "/goal/temporary",
            {"items": [{"enabled": False, "amount": Decimal("1.0")}], "end": None},
        ),
        operation(
            "test",
            "/goal/temporary",
            {"items": [{"enabled": 0, "amount": 1}], "end": None},
        ),
        operation("remove", "/goal/temporary"),
    )

    result = apply_corrections(original, (nested_mismatch,))

    assert result.blueprint is original
    assert result.conflicts[0].correction_id == "nested-mismatch"


def test_precondizione_json_equipara_numeri_serializzabili_anche_annidati():
    original = make_blueprint()
    numeric_match = correction(
        "numeric-match",
        operation("add", "/goal/temporary", {"values": [1, Decimal("2.50")]}),
        operation("test", "/goal/temporary", {"values": [1.0, 2.5]}),
        operation("remove", "/goal/temporary"),
    )

    result = apply_corrections(original, (numeric_match,))

    assert result.conflicts == ()
    assert result.applied_correction_ids == ("numeric-match",)


@pytest.mark.parametrize(
    ("changed", "updates"),
    [
        ("effective_seed", {"effective_seed": 8}),
        ("samples", {"samples": 21, "completed_samples": 21}),
        ("profile_hash", {"profile_hash": "other"}),
        ("algorithm_version", {"algorithm_version": "preflight-simulate-v999"}),
    ],
)
def test_confronto_rifiuta_ognuna_delle_condizioni_esterne_diverse(
    changed: str, updates: dict[str, object]
):
    before = report(typical=scenario())
    after = before.model_copy(update={"blueprint_hash": "after", **updates})

    with pytest.raises(ValueError, match="stesse condizioni"):
        compare_reports(before, after)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("nodes", 0, "budget", "dynamic_context", "typical"), 90),
        (("nodes", 0, "budget", "max_retries"), 0),
        (("transitions", 0, "probability", "typical"), 0.4),
    ],
    ids=("budget", "retry", "probability"),
)
def test_confronto_rifiuta_basi_quantitative_diverse_sulla_stessa_entita(
    path: tuple[object, ...], replacement: object
):
    """Abbassare una base sullo stesso ID non deve essere attribuito alla patch confrontata."""
    payload = make_blueprint().model_dump(mode="json")
    if path[0] == "transitions":
        payload["transitions"][0]["activation"] = "choice"
        payload["transitions"][0]["probability"] = {
            "min": 0.2,
            "typical": 0.6,
            "max": 0.8,
            "provenance": "declared",
            "confidence": "medium",
            "reason": "Fixture sintetica.",
        }
    before = Blueprint.model_validate(payload)
    changed = json.loads(json.dumps(payload))
    cursor = changed
    for token in path[:-1]:
        cursor = cursor[token]
    cursor[path[-1]] = replacement

    before_report = simulate_blueprint(before, samples=10, seed=17)
    after_report = simulate_blueprint(
        Blueprint.model_validate(changed), samples=10, seed=17
    )

    with pytest.raises(ValueError, match="stesse condizioni"):
        compare_reports(before_report, after_report)


def test_confronto_consente_modifiche_strutturali_e_model_id_a_catalogo_uguale():
    """Entita aggiunte/rimosse e model routing sono la modifica, non basi condivise false."""
    before = make_blueprint()
    changed = before.model_dump(mode="json")
    changed["nodes"] = [node for node in changed["nodes"] if node["id"] != "review"]
    changed["transitions"] = []
    changed["nodes"][0]["model_id"] = "economy"
    changed["agents"][0]["model_id"] = "economy"
    after = Blueprint.model_validate(changed)

    before_report = simulate_blueprint(before, samples=10, seed=23)
    after_report = simulate_blueprint(after, samples=10, seed=23)
    comparison = compare_reports(before_report, after_report)

    assert before_report.assumptions_hash != after_report.assumptions_hash
    assert comparison.before_assumptions_hash == before_report.assumptions_hash
    assert comparison.after_assumptions_hash == after_report.assumptions_hash
    assert comparison.algorithm_version == SIMULATION_ALGORITHM_VERSION


def test_confronto_rifiuta_costo_tool_diverso_sullo_stesso_id():
    """Abbassare il costo tool senza cambiare entita non deve sembrare risparmio della patch."""
    payload = make_blueprint().model_dump(mode="json")
    payload["tools"] = [
        {"id": "fetch", "name": "Fetch", "description": "Tool sintetico."}
    ]
    payload["agents"][0]["tool_ids"] = ["fetch"]
    node = payload["nodes"][0]
    node.update({"kind": "tool", "tool_id": "fetch", "model_id": None})
    node["budget"]["fixed_tool_cost"] = {
        "min": "0.10", "typical": "0.20", "max": "0.30", "currency": "USD",
        "provenance": "declared", "confidence": "high", "reason": "Costo sintetico.",
    }
    payload["nodes"] = [node]
    payload["transitions"] = []
    payload["entry_node_ids"] = [node["id"]]
    before = Blueprint.model_validate(payload)
    changed = json.loads(json.dumps(payload))
    changed["nodes"][0]["budget"]["fixed_tool_cost"]["typical"] = "0.15"

    before_report = simulate_blueprint(before, samples=10, seed=29)
    after_report = simulate_blueprint(
        Blueprint.model_validate(changed), samples=10, seed=29
    )

    with pytest.raises(ValueError, match="stesse condizioni"):
        compare_reports(before_report, after_report)


def test_base_quantitativa_e_frozen_e_serializza_stabilmente():
    """Il report persistito deve materializzare basi ordinate senza mapping mutabili."""
    first = simulate_blueprint(make_blueprint(), samples=10, seed=31)
    second = simulate_blueprint(make_blueprint(), samples=10, seed=31)

    assert first.algorithm_version == SIMULATION_ALGORITHM_VERSION
    assert first.quantitative_basis == second.quantitative_basis
    assert first.model_dump_json() == second.model_dump_json()
    assert tuple(entry.key for entry in first.quantitative_basis) == tuple(
        sorted(entry.key for entry in first.quantitative_basis)
    )
    node = next(entry for entry in first.quantitative_basis if entry.key == "node:draft")
    assert node.max_retries == 1
    assert node.dynamic_context.typical == 100
    with pytest.raises(Exception):
        node.max_retries = 0  # type: ignore[misc]


@pytest.mark.parametrize("duplicate_side", ["before", "after"])
def test_confronto_rifiuta_chiavi_duplicate_in_report_manuali_legacy(
    duplicate_side: str,
):
    """Un dict non deve comprimere una collisione e nascondere il primo fingerprint."""
    shared = TransitionQuantitativeBasis(
        key="transition:draft->review:always:",
        source="draft",
        target="review",
        activation="always",
        parallel_group=None,
        probability=None,
        max_traversals=None,
    )
    hidden_change = shared.model_copy(update={"max_traversals": 2})
    duplicate_basis = (hidden_change, shared)
    before_basis = duplicate_basis if duplicate_side == "before" else (shared,)
    after_basis = duplicate_basis if duplicate_side == "after" else (shared,)
    before = report(
        blueprint_hash="legacy-before",
        assumptions_hash="legacy-assumptions-before",
        quantitative_basis=before_basis,
    )
    after = report(
        blueprint_hash="legacy-after",
        assumptions_hash="legacy-assumptions-after",
        quantitative_basis=after_basis,
    )

    with pytest.raises(ValueError, match="stesse condizioni.*duplicat"):
        compare_reports(before, after)


def test_confronto_accetta_hash_blueprint_diverso_e_calcola_decimal_e_baseline_zero():
    before_typical = scenario(
        input_tokens=0,
        output_tokens=10,
        llm_calls=2,
        latency_ms=100,
        cost=Decimal("1.20"),
    )
    after_typical = scenario(
        input_tokens=5,
        output_tokens=5,
        llm_calls=1,
        latency_ms=75,
        cost=Decimal("0.90"),
    )
    before = report(
        blueprint_hash="before",
        optimistic=scenario(input_tokens=1),
        typical=before_typical,
        prudent=scenario(input_tokens=20),
        maximum=scenario(input_tokens=30),
    )
    after = report(
        blueprint_hash="after",
        optimistic=scenario(input_tokens=2),
        typical=after_typical,
        prudent=scenario(input_tokens=18),
        maximum=scenario(input_tokens=25),
    )

    comparison = compare_reports(before, after)

    assert comparison.before_blueprint_hash == "before"
    assert comparison.after_blueprint_hash == "after"
    assert comparison.typical.before_present is True
    assert comparison.typical.after_present is True
    assert comparison.typical.input_tokens.absolute == 5
    assert comparison.typical.input_tokens.percent is None
    assert comparison.typical.total_tokens.absolute == 0
    assert comparison.typical.total_tokens.percent == Decimal("0")
    assert comparison.typical.llm_calls.absolute == -1
    assert comparison.typical.latency_ms.percent == Decimal("-25.00")
    assert comparison.typical.cost.absolute == Decimal("-0.30")
    assert comparison.typical.cost.percent == Decimal("-25.00")
    assert comparison.optimistic.before_present is True
    assert comparison.prudent.after_present is True
    assert comparison.maximum.before_present is True


def test_confronto_rifiuta_costi_typical_in_valute_diverse():
    before = report(blueprint_hash="before", typical=scenario(cost=Decimal("1.00")))
    after_typical = scenario(cost=Decimal("0.90")).model_copy(update={"currency": "EUR"})
    after = report(blueprint_hash="after", typical=after_typical)

    with pytest.raises(ValueError, match="stesse condizioni.*valuta"):
        compare_reports(before, after)


def test_scenario_assente_resta_dichiarato_e_non_diventa_zero():
    comparison = compare_reports(
        report(blueprint_hash="before", typical=None),
        report(blueprint_hash="after", typical=scenario()),
    )

    assert comparison.typical.before_present is False
    assert comparison.typical.after_present is True
    assert comparison.typical.input_tokens is None


def test_modelli_pubblici_sono_frozen_extra_forbid_e_serializzano_stabilmente():
    patch = PatchOperation(op="test", path="/goal/id", value="goal-release")
    encoded = patch.model_dump_json()

    assert PatchOperation.model_validate_json(encoded) == patch
    with pytest.raises(Exception):
        patch.path = "/goal/description"  # type: ignore[misc]
    with pytest.raises(ValueError):
        PatchOperation(op="remove", path="/goal/id", unexpected=True)
