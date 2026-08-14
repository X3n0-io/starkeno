"""Regressioni concrete per il simulatore deterministico Preflight."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest

from starkeno import preflight_simulate
from starkeno.preflight_patch import compare_reports
from starkeno.preflight_schema import (
    Blueprint,
    blueprint_hash,
    dump_blueprint,
    load_blueprint,
)
from starkeno.preflight_simulate import (
    ChoiceGroupQuantitativeBasis,
    TransitionQuantitativeBasis,
    _MutableTotals,
    simulate_blueprint,
)


FIXTURE = Path(__file__).parent / "fixtures" / "preflight" / "minimal.json"


def _payload(*, confirmed: bool = True) -> dict[str, object]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = confirmed
    return payload


def make_blueprint(*, confirmed: bool) -> Blueprint:
    return Blueprint.model_validate(_payload(confirmed=confirmed))


def probabilistic_blueprint(*, confirmed: bool) -> Blueprint:
    payload = _payload(confirmed=confirmed)
    review = payload["nodes"][1]
    rejected = json.loads(json.dumps(review))
    rejected.update({"id": "rejected", "description": "Rifiuta la bozza."})
    payload["nodes"].append(rejected)
    payload["transitions"] = [
        {
            "source": "draft",
            "target": "review",
            "activation": "choice",
            "probability": {
                "min": 0.6,
                "typical": 0.7,
                "max": 0.8,
                "provenance": "declared",
                "confidence": "medium",
                "reason": "Esiti sintetici.",
            },
            "parallel_group": None,
            "max_traversals": None,
        },
        {
            "source": "draft",
            "target": "rejected",
            "activation": "choice",
            "probability": {
                "min": 0.2,
                "typical": 0.3,
                "max": 0.4,
                "provenance": "declared",
                "confidence": "medium",
                "reason": "Esiti sintetici.",
            },
            "parallel_group": None,
            "max_traversals": None,
        },
    ]
    return Blueprint.model_validate(payload)


def make_cyclic_blueprint(*, confirmed: bool, max_traversals: int | None) -> Blueprint:
    payload = _payload(confirmed=confirmed)
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


def blueprint_with_unknown_price(*, confirmed: bool) -> Blueprint:
    payload = _payload(confirmed=confirmed)
    payload["models"][0]["id"] = "model-without-price"
    payload["nodes"][0]["model_id"] = "model-without-price"
    payload["agents"][0]["model_id"] = "model-without-price"
    return Blueprint.model_validate(payload)


def _set_known_prices(payload: dict[str, object]) -> None:
    profile = payload["models"][0]
    profile.update(
        {
            "input_price_per_million": "1.0",
            "output_price_per_million": "2.0",
            "cache_read_price_per_million": "0.5",
            "cache_write_price_per_million": "1.5",
        }
    )


def test_stesso_seed_produce_lo_stesso_report_e_le_somme_quadrano():
    """Un RNG o un aggregatore instabile romperebbe report e subtotali riproducibili."""
    blueprint = probabilistic_blueprint(confirmed=True)

    a = simulate_blueprint(blueprint, samples=200, seed=42)
    b = simulate_blueprint(blueprint, samples=200, seed=42)

    assert a == b
    assert a.blueprint_hash == blueprint_hash(blueprint)
    assert a.typical is not None
    assert a.typical.input_tokens == sum(node.input_tokens for node in a.typical.nodes)
    assert a.typical.output_tokens == sum(node.output_tokens for node in a.typical.nodes)
    assert a.typical.cache_read_tokens == sum(node.cache_read_tokens for node in a.typical.nodes)
    assert a.typical.cache_write_tokens == sum(node.cache_write_tokens for node in a.typical.nodes)


def test_condizioni_di_simulazione_sono_materializzate_stabili_e_json():
    """Un confronto non deve dipendere da seed impliciti o hash non serializzabili."""
    blueprint = probabilistic_blueprint(confirmed=True)

    first = simulate_blueprint(blueprint, samples=25)
    second = simulate_blueprint(blueprint, samples=25)

    assert first.effective_seed == int(blueprint_hash(blueprint)[:16], 16)
    assert (
        first.effective_seed,
        first.samples,
        first.profile_hash,
        first.assumptions_hash,
    ) == (
        second.effective_seed,
        second.samples,
        second.profile_hash,
        second.assumptions_hash,
    )
    dumped = first.model_dump(mode="json")
    json.dumps(dumped)
    assert dumped["effective_seed"] == first.effective_seed


def _blueprint_con_collisione_testuale_transizioni(kind: str) -> Blueprint:
    payload = _payload()
    if kind == "parallel-group":
        payload["transitions"][0]["activation"] = "choice"
        gruppo_vuoto = json.loads(json.dumps(payload["transitions"][0]))
        gruppo_vuoto["parallel_group"] = ""
        payload["transitions"].append(gruppo_vuoto)
    else:
        template = payload["nodes"][1]
        payload["nodes"] = []
        for node_id in ("a->b", "c", "a", "b->c"):
            node = json.loads(json.dumps(template))
            node.update({"id": node_id, "description": f"Nodo {node_id}."})
            payload["nodes"].append(node)
        payload["entry_node_ids"] = ["a->b", "a"]
        payload["transitions"] = [
            {
                "source": "a->b",
                "target": "c",
                "activation": "choice",
                "probability": None,
                "parallel_group": None,
                "max_traversals": None,
            },
            {
                "source": "a",
                "target": "b->c",
                "activation": "choice",
                "probability": None,
                "parallel_group": None,
                "max_traversals": None,
            },
        ]
    return Blueprint.model_validate(payload)


@pytest.mark.parametrize(
    ("kind", "expected_keys"),
    [
        (
            "parallel-group",
            {
                'transition:["draft","review","choice",null]',
                'transition:["draft","review","choice",""]',
            },
        ),
        (
            "delimiters",
            {
                'transition:["a->b","c","choice",null]',
                'transition:["a","b->c","choice",null]',
            },
        ),
    ],
)
def test_chiavi_transizione_canoniche_sono_iniettive_stabili_e_confrontabili(
    kind: str, expected_keys: set[str]
):
    """None, stringa vuota e delimitatori negli ID non devono collidere nel report."""
    blueprint = _blueprint_con_collisione_testuale_transizioni(kind)
    from_json = load_blueprint(
        dump_blueprint(blueprint, format="json"), format_hint="json"
    )
    from_yaml = load_blueprint(
        dump_blueprint(blueprint, format="yaml"), format_hint="yaml"
    )
    assert from_json == from_yaml == blueprint

    report = simulate_blueprint(from_json, samples=4, seed=37)
    transition_keys = {
        entry.key
        for entry in report.quantitative_basis
        if isinstance(entry, TransitionQuantitativeBasis)
    }
    branch_keys = {
        branch.transition_key
        for entry in report.quantitative_basis
        if isinstance(entry, ChoiceGroupQuantitativeBasis)
        for branch in entry.branches
    }

    assert transition_keys == expected_keys
    assert branch_keys == expected_keys
    assert compare_reports(report, report).algorithm_version == "preflight-simulate-v5"


def test_hash_condizioni_separa_catalogo_fallback_e_modifiche_intenzionali():
    """Budget e fallback cambiano la base; il solo routing modello no."""
    payload = _payload()
    alternate = json.loads(json.dumps(payload["models"][0]))
    alternate.update({"id": "alternate", "name": "Alternate"})
    payload["models"].append(alternate)
    before = Blueprint.model_validate(payload)

    changed = json.loads(json.dumps(payload))
    changed["nodes"][0]["budget"]["dynamic_context"]["typical"] = 110
    after = Blueprint.model_validate(changed)

    before_report = simulate_blueprint(before, samples=10, seed=5)
    after_report = simulate_blueprint(after, samples=10, seed=5)

    assert before_report.profile_hash == after_report.profile_hash
    assert before_report.assumptions_hash != after_report.assumptions_hash

    rerouted = json.loads(json.dumps(payload))
    rerouted["nodes"][0]["model_id"] = "alternate"
    rerouted["agents"][0]["model_id"] = "alternate"
    rerouted_report = simulate_blueprint(
        Blueprint.model_validate(rerouted), samples=10, seed=5
    )
    assert rerouted_report.assumptions_hash == before_report.assumptions_hash

    catalog_changed = json.loads(json.dumps(payload))
    catalog_changed["models"][1]["name"] = "Alternate v2"
    catalog_report = simulate_blueprint(
        Blueprint.model_validate(catalog_changed), samples=10, seed=5
    )
    assert catalog_report.profile_hash != before_report.profile_hash

    fallback_changed = json.loads(json.dumps(payload))
    fallback_changed["transitions"][0]["activation"] = "choice"
    fallback_report = simulate_blueprint(
        Blueprint.model_validate(fallback_changed), samples=10, seed=5
    )
    assert fallback_report.assumptions_hash != before_report.assumptions_hash


def test_non_simula_un_blueprint_non_confermato():
    """Saltare il confine umano renderebbe definitiva un'interpretazione ancora draft."""
    with pytest.raises(ValueError, match="confermato"):
        simulate_blueprint(make_blueprint(confirmed=False), samples=10, seed=1)


def test_ciclo_illimitato_non_inventa_un_massimo():
    """Un ciclo senza uscita non deve diventare un massimo finito per via della guardia."""
    report = simulate_blueprint(
        make_cyclic_blueprint(confirmed=True, max_traversals=None),
        samples=20,
        seed=1,
    )

    assert report.maximum_status == "unbounded"
    assert report.maximum is None


def test_prezzo_sconosciuto_resta_sconosciuto():
    """Una categoria necessaria senza prezzo non deve essere valorizzata come zero."""
    report = simulate_blueprint(
        blueprint_with_unknown_price(confirmed=True),
        samples=20,
        seed=1,
    )

    assert report.typical is not None
    assert report.typical.cost is None
    assert "model-without-price" in report.unknown_prices


@pytest.mark.parametrize("samples", [0, 10_001])
def test_numero_campioni_fuori_limite_viene_rifiutato(samples: int):
    """Campioni nulli o eccessivi aggirerebbero i limiti espliciti della simulazione."""
    with pytest.raises(ValueError, match="samples"):
        simulate_blueprint(make_blueprint(confirmed=True), samples=samples, seed=1)


def test_scenario_ottimistico_e_massimo_usano_estremi_retry_e_decimal():
    """Estremi, retry e prezzi devono produrre valori contabili derivati senza float."""
    payload = _payload()
    _set_known_prices(payload)
    payload["nodes"][0]["budget"]["retry_probability"].update(
        {"min": 1.0, "typical": 1.0, "max": 1.0}
    )
    blueprint = Blueprint.model_validate(payload)

    report = simulate_blueprint(blueprint, samples=10, seed=7)

    assert report.optimistic is not None
    assert report.maximum is not None
    optimistic_draft = next(node for node in report.optimistic.nodes if node.node_id == "draft")
    maximum_draft = next(node for node in report.maximum.nodes if node.node_id == "draft")
    assert optimistic_draft.executions == 1
    assert maximum_draft.executions == 2
    assert report.maximum_status == "finite"
    assert isinstance(report.maximum.cost, Decimal)
    assert report.maximum.cost == Decimal("0.0014800")


def test_massimo_non_inventa_retry_con_probabilita_zero():
    """Un limite configurato non implica retry quando la probabilità massima è nulla."""
    payload = _payload()
    payload["nodes"][0]["budget"]["retry_probability"].update(
        {"min": 0.0, "typical": 0.0, "max": 0.0}
    )
    payload["nodes"][0]["budget"]["max_retries"] = 4

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=10, seed=2)

    assert report.maximum is not None
    draft = next(node for node in report.maximum.nodes if node.node_id == "draft")
    assert draft.executions == 1


def test_scenari_estremi_scelgono_il_costo_dell_intero_ramo():
    """Valutare solo il primo nodo sceglierebbe il ramo economico con coda più costosa."""
    payload = _payload()
    cheap = payload["nodes"][1]
    cheap.update({"id": "cheap", "description": "Ramo economico."})
    expensive = json.loads(json.dumps(cheap))
    expensive.update({"id": "expensive", "description": "Ramo costoso."})
    expensive["budget"]["output"].update({"min": 1, "typical": 1, "max": 1})
    tail = json.loads(json.dumps(cheap))
    tail.update({"id": "tail", "description": "Coda molto costosa."})
    tail["budget"]["output"].update({"min": 10_000, "typical": 10_000, "max": 10_000})
    payload["nodes"].extend([expensive, tail])
    payload["transitions"] = [
        {
            "source": "draft",
            "target": "cheap",
            "activation": "choice",
            "probability": None,
            "parallel_group": None,
            "max_traversals": None,
        },
        {
            "source": "draft",
            "target": "expensive",
            "activation": "choice",
            "probability": None,
            "parallel_group": None,
            "max_traversals": None,
        },
        {
            "source": "cheap",
            "target": "tail",
            "activation": "always",
            "probability": None,
            "parallel_group": None,
            "max_traversals": None,
        },
    ]

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=10, seed=2)

    assert report.optimistic is not None
    assert report.maximum is not None
    assert "expensive" in {node.node_id for node in report.optimistic.nodes}
    assert "cheap" not in {node.node_id for node in report.optimistic.nodes}
    assert "tail" in {node.node_id for node in report.maximum.nodes}


def test_archi_choice_senza_probabilita_dichiarano_assunzione_uniforme():
    """Una probabilità mancante non deve essere presentata come dato dichiarato."""
    payload = _payload()
    terminal = json.loads(json.dumps(payload["nodes"][1]))
    terminal.update({"id": "alternate", "description": "Alternativa."})
    payload["nodes"].append(terminal)
    for transition in payload["transitions"]:
        transition["activation"] = "choice"
    payload["transitions"].append(
        {
            "source": "draft",
            "target": "alternate",
            "activation": "choice",
            "probability": None,
            "parallel_group": None,
            "max_traversals": None,
        }
    )
    blueprint = Blueprint.model_validate(payload)

    report = simulate_blueprint(blueprint, samples=30, seed=3)

    assert any("uniform" in assumption.casefold() for assumption in report.assumptions)


def test_rami_paralleli_sommano_token_ma_usano_la_latenza_critica():
    """Serializzare per errore rami paralleli gonfierebbe la latenza del report."""
    payload = _payload()
    payload["nodes"][0]["budget"]["retry_probability"].update(
        {"min": 0.0, "typical": 0.0, "max": 0.0}
    )
    second = json.loads(json.dumps(payload["nodes"][1]))
    second.update({"id": "second-review", "description": "Seconda approvazione."})
    second["budget"]["latency_ms"].update({"min": 200, "typical": 2000, "max": 6000})
    payload["nodes"].append(second)
    payload["transitions"][0]["parallel_group"] = "approvals"
    payload["transitions"].append(
        {
            "source": "draft",
            "target": "second-review",
            "activation": "always",
            "probability": None,
            "parallel_group": "approvals",
            "max_traversals": None,
        }
    )
    blueprint = Blueprint.model_validate(payload)

    report = simulate_blueprint(blueprint, samples=10, seed=9)

    assert report.typical is not None
    assert report.typical.latency_ms == 2300
    assert {node.node_id for node in report.typical.nodes} == {
        "draft",
        "review",
        "second-review",
    }
    writer = next(agent for agent in report.typical.agents if agent.agent_id == "writer")
    draft = next(node for node in report.typical.nodes if node.node_id == "draft")
    assert writer.input_tokens == draft.input_tokens
    assert writer.output_tokens == draft.output_tokens


def test_dag_finito_con_fan_out_non_viene_troncato_dalla_guardia():
    """Un DAG con molti cammini resta finito anche se supera una soglia lineare di visite."""
    payload = _payload()
    template = json.loads(json.dumps(payload["nodes"][1]))
    start = json.loads(json.dumps(template))
    start.update({"id": "level-0", "description": "Ingresso."})
    nodes = [start]
    transitions = []
    previous = ["level-0"]
    for level in range(1, 9):
        current = [f"level-{level}-left", f"level-{level}-right"]
        for node_id in current:
            node = json.loads(json.dumps(template))
            node.update({"id": node_id, "description": f"Livello {level}."})
            nodes.append(node)
        transitions.extend(
            {
                "source": source,
                "target": target,
                "activation": "always",
                "probability": None,
                "parallel_group": f"level-{level}",
                "max_traversals": None,
            }
            for source in previous
            for target in current
        )
        previous = current
    payload["nodes"] = nodes
    payload["transitions"] = transitions
    payload["entry_node_ids"] = ["level-0"]

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=5, seed=4)

    assert report.optimistic is not None
    assert report.completed_samples == 5
    assert report.maximum_status == "finite"
    assert report.maximum is not None
    assert report.maximum.nodes[-1].executions == 128


def test_scoring_estremo_non_tronca_un_ramo_finito_profondo():
    """Il ramo minimo può superare 128 nodi senza ricevere un costo sentinella arbitrario."""
    payload = _payload()
    template = json.loads(json.dumps(payload["nodes"][1]))
    expensive = json.loads(json.dumps(template))
    expensive.update({"id": "expensive", "description": "Terminale costoso."})
    expensive["budget"]["output"].update({"min": 1, "typical": 1, "max": 1})
    nodes = [payload["nodes"][0], expensive]
    transitions = [
        {
            "source": "draft",
            "target": "expensive",
            "activation": "choice",
            "probability": None,
            "parallel_group": None,
            "max_traversals": None,
        }
    ]
    for index in range(130):
        node = json.loads(json.dumps(template))
        node_id = f"cheap-{index:03d}"
        node.update({"id": node_id, "description": "Passo economico."})
        nodes.append(node)
        source = "draft" if index == 0 else f"cheap-{index - 1:03d}"
        transitions.append(
            {
                "source": source,
                "target": node_id,
                "activation": "choice" if index == 0 else "always",
                "probability": None,
                "parallel_group": None,
                "max_traversals": None,
            }
        )
    payload["nodes"] = nodes
    payload["transitions"] = transitions

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=2, seed=6)

    assert report.optimistic is not None
    assert "cheap-129" in {node.node_id for node in report.optimistic.nodes}
    assert "expensive" not in {node.node_id for node in report.optimistic.nodes}


def test_nodo_irraggiungibile_non_contamina_limiti_prezzi_o_valuta():
    """Dati isolati dal grafo eseguito non devono cambiare massimo, campioni o costo."""
    payload = _payload()
    _set_known_prices(payload)
    unreachable_model = json.loads(json.dumps(payload["models"][0]))
    unreachable_model.update(
        {
            "id": "unreachable-model",
            "name": "Unreachable",
            "currency": "EUR",
            "input_price_per_million": None,
            "output_price_per_million": None,
            "cache_read_price_per_million": None,
            "cache_write_price_per_million": None,
        }
    )
    payload["models"].append(unreachable_model)
    orphan = json.loads(json.dumps(payload["nodes"][0]))
    orphan.update({"id": "orphan", "model_id": "unreachable-model"})
    orphan["budget"]["retry_probability"].update(
        {"min": 1.0, "typical": 1.0, "max": 1.0}
    )
    orphan["budget"]["max_retries"] = None
    payload["nodes"].append(orphan)

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=5, seed=8)

    assert report.maximum_status == "finite"
    assert report.maximum is not None
    assert report.completed_samples == 5
    assert "unreachable-model" not in report.unknown_prices
    assert report.typical is not None
    assert report.typical.currency == "USD"
    assert report.typical.cost is not None


def test_choice_impossibile_non_rende_raggiungibile_un_ciclo_illimitato():
    """Un ramo con probabilità massima zero non esiste in alcuno scenario supportato."""
    payload = _payload()
    payload["transitions"][0].update(
        {
            "activation": "choice",
            "probability": {
                "min": 1.0,
                "typical": 1.0,
                "max": 1.0,
                "provenance": "declared",
                "confidence": "high",
                "reason": "Percorso certo.",
            },
        }
    )
    impossible = json.loads(json.dumps(payload["nodes"][1]))
    impossible.update({"id": "impossible", "description": "Ramo impossibile."})
    payload["nodes"].append(impossible)
    payload["transitions"].extend(
        [
            {
                "source": "draft",
                "target": "impossible",
                "activation": "choice",
                "probability": {
                    "min": 0.0,
                    "typical": 0.0,
                    "max": 0.0,
                    "provenance": "declared",
                    "confidence": "high",
                    "reason": "Ramo disabilitato.",
                },
                "parallel_group": None,
                "max_traversals": None,
            },
            {
                "source": "impossible",
                "target": "impossible",
                "activation": "always",
                "probability": None,
                "parallel_group": None,
                "max_traversals": None,
            },
        ]
    )

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=5, seed=10)

    assert report.maximum_status == "finite"
    assert report.maximum is not None
    assert report.completed_samples == 5
    assert "impossible" not in {node.node_id for node in report.maximum.nodes}


def test_ciclo_possibile_dietro_choice_non_azzera_gli_altri_campioni():
    """Un ramo infinito opzionale rende il massimo unbounded, non ogni corsa inevitabile."""
    payload = _payload()
    payload["transitions"][0].update(
        {
            "activation": "choice",
            "probability": {
                "min": 0.8,
                "typical": 0.9,
                "max": 0.9,
                "provenance": "declared",
                "confidence": "high",
                "reason": "Percorso finito prevalente.",
            },
        }
    )
    optional_cycle = json.loads(json.dumps(payload["nodes"][1]))
    optional_cycle.update({"id": "optional-cycle", "description": "Ciclo opzionale."})
    payload["nodes"].append(optional_cycle)
    payload["transitions"].extend(
        [
            {
                "source": "draft",
                "target": "optional-cycle",
                "activation": "choice",
                "probability": {
                    "min": 0.1,
                    "typical": 0.1,
                    "max": 0.2,
                    "provenance": "declared",
                    "confidence": "high",
                    "reason": "Percorso raro.",
                },
                "parallel_group": None,
                "max_traversals": None,
            },
            {
                "source": "optional-cycle",
                "target": "optional-cycle",
                "activation": "always",
                "probability": None,
                "parallel_group": None,
                "max_traversals": None,
            },
        ]
    )

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=20, seed=16)

    assert report.maximum_status == "unbounded"
    assert report.optimistic is not None
    assert 0 < report.completed_samples < 20


def test_choice_con_pesi_typical_tutti_zero_usa_fallback_documentato():
    """Pesi dichiarati ma nulli non devono causare ValueError nel campionamento."""
    payload = _payload()
    alternate = json.loads(json.dumps(payload["nodes"][1]))
    alternate.update({"id": "alternate", "description": "Alternativa."})
    payload["nodes"].append(alternate)
    zero_probability = {
        "min": 0.0,
        "typical": 0.0,
        "max": 0.5,
        "provenance": "declared",
        "confidence": "low",
        "reason": "Peso non calibrato.",
    }
    payload["transitions"][0].update(
        {"activation": "choice", "probability": zero_probability}
    )
    payload["transitions"].append(
        {
            "source": "draft",
            "target": "alternate",
            "activation": "choice",
            "probability": zero_probability,
            "parallel_group": None,
            "max_traversals": None,
        }
    )

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=10, seed=12)

    assert report.completed_samples == 10
    assert any(
        "pesi typical nulli" in assumption.casefold() and "uniform" in assumption.casefold()
        for assumption in report.assumptions
    )


def test_cache_read_senza_retry_non_rende_il_prezzo_ignoto():
    """Una categoria mai consumabile non deve rendere sconosciuto il costo totale."""
    payload = _payload()
    _set_known_prices(payload)
    payload["models"][0]["cache_read_price_per_million"] = None
    payload["nodes"][0]["budget"]["max_retries"] = 0

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=5, seed=14)

    assert report.unknown_prices == ()
    assert report.typical is not None
    assert report.typical.cache_read_tokens == 0
    assert report.typical.cost is not None


def test_ciclo_opzionale_non_tronca_un_ramo_finito_di_oltre_300_nodi():
    """La guardia di una SCC ciclica non deve diventare il limite globale del grafo."""
    payload = _payload()
    template = json.loads(json.dumps(payload["nodes"][1]))
    cycle = json.loads(json.dumps(template))
    cycle.update({"id": "cycle", "description": "Ciclo opzionale."})
    nodes = [payload["nodes"][0], cycle]
    transitions = [
        {
            "source": "draft",
            "target": "cycle",
            "activation": "choice",
            "probability": {
                "min": 0.0,
                "typical": 0.0,
                "max": 0.1,
                "provenance": "declared",
                "confidence": "high",
                "reason": "Ramo opzionale.",
            },
            "parallel_group": None,
            "max_traversals": None,
        },
        {
            "source": "cycle",
            "target": "cycle",
            "activation": "always",
            "probability": None,
            "parallel_group": None,
            "max_traversals": None,
        },
    ]
    for index in range(320):
        node = json.loads(json.dumps(template))
        node_id = f"finite-{index:03d}"
        node.update({"id": node_id, "description": "Passo finito."})
        nodes.append(node)
        source = "draft" if index == 0 else f"finite-{index - 1:03d}"
        transitions.append(
            {
                "source": source,
                "target": node_id,
                "activation": "choice" if index == 0 else "always",
                "probability": {
                    "min": 0.9,
                    "typical": 1.0,
                    "max": 1.0,
                    "provenance": "declared",
                    "confidence": "high",
                    "reason": "Ramo normale.",
                }
                if index == 0
                else None,
                "parallel_group": None,
                "max_traversals": None,
            }
        )
    payload["nodes"] = nodes
    payload["transitions"] = transitions

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=5, seed=18)

    assert report.maximum_status == "unbounded"
    assert report.optimistic is not None
    assert "finite-319" in {node.node_id for node in report.optimistic.nodes}
    assert report.completed_samples == 5


def test_retry_geometrico_non_dipende_dalla_dimensione_del_grafo():
    """La guardia visite di un nodo singolo non deve scartare normali retry geometrici."""
    payload = _payload()
    payload["nodes"] = [payload["nodes"][0]]
    payload["transitions"] = []
    payload["nodes"][0]["budget"]["retry_probability"].update(
        {"min": 0.0, "typical": 0.5, "max": 0.5}
    )
    payload["nodes"][0]["budget"]["max_retries"] = None

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=100, seed=20)

    assert report.maximum_status == "unbounded"
    assert report.completed_samples == 100
    assert report.typical is not None


def _tool_cost_blueprint(
    fixed_cost: dict[str, object] | None | Literal["absent"],
    *,
    tool_currency: str = "USD",
    with_model: bool = False,
) -> Blueprint:
    payload = _payload()
    payload["tools"] = [
        {"id": "fetch", "name": "Fetch", "description": "Tool sintetico."}
    ]
    node = payload["nodes"][0]
    node.update(
        {
            "id": "fetch-node",
            "kind": "tool",
            "tool_id": "fetch",
            "model_id": "economy" if with_model else None,
            "description": "Esegue il tool.",
        }
    )
    payload["agents"][0]["tool_ids"] = ["fetch"]
    payload["nodes"] = [node]
    payload["transitions"] = []
    payload["entry_node_ids"] = ["fetch-node"]
    if fixed_cost != "absent":
        node["budget"]["fixed_tool_cost"] = fixed_cost
    if fixed_cost not in (None, "absent"):
        node["budget"]["fixed_tool_cost"]["currency"] = tool_currency
    return Blueprint.model_validate(payload)


def _money(minimum: str, typical: str, maximum: str) -> dict[str, object]:
    return {
        "min": minimum,
        "typical": typical,
        "max": maximum,
        "currency": "USD",
        "provenance": "declared",
        "confidence": "high",
        "reason": "Costo sintetico.",
    }


def test_tool_senza_costo_e_unknown_ma_zero_esplicito_e_noto():
    """L'assenza non deve collassare nello stesso zero di un tool dichiarato gratuito."""
    unknown = simulate_blueprint(
        _tool_cost_blueprint("absent"), samples=5, seed=41
    )
    free = simulate_blueprint(
        _tool_cost_blueprint(_money("0", "0", "0")), samples=5, seed=41
    )

    assert unknown.typical is not None and unknown.typical.cost is None
    assert unknown.typical.nodes[0].cost is None
    assert unknown.unknown_prices == ("tool:fetch",)
    assert free.typical is not None and free.typical.cost == Decimal("0")
    assert free.typical.nodes[0].cost == Decimal("0")
    assert free.typical.currency == "USD"
    assert free.unknown_prices == ()


def test_costo_tool_decimal_pagato_si_moltiplica_per_retry():
    """Ogni esecuzione e retry deve applicare esattamente il costo fisso campionato."""
    blueprint = _tool_cost_blueprint(_money("0.01", "0.025", "0.09"))
    payload = blueprint.model_dump(mode="json")
    payload["nodes"][0]["budget"]["retry_probability"].update(
        {"min": 1.0, "typical": 1.0, "max": 1.0}
    )
    payload["nodes"][0]["budget"]["max_retries"] = 2

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=3, seed=43)

    assert report.typical is not None
    assert report.typical.nodes[0].executions == 3
    assert report.typical.nodes[0].cost == Decimal("0.075")
    assert report.maximum is not None
    assert report.maximum.nodes[0].cost == Decimal("0.27")
    basis = next(entry for entry in report.quantitative_basis if entry.key == "node:fetch-node")
    assert basis.fixed_tool_cost.typical == Decimal("0.025")


def test_costo_tool_e_modello_si_sommano_solo_nella_stessa_valuta():
    """Nessuna conversione implicita deve sommare valute incompatibili."""
    same = _tool_cost_blueprint(
        _money("1", "1", "1"), tool_currency="USD", with_model=True
    )
    mixed = _tool_cost_blueprint(
        _money("1", "1", "1"), tool_currency="EUR", with_model=True
    )
    for blueprint, expected_currency in ((same, "USD"), (mixed, None)):
        payload = blueprint.model_dump(mode="json")
        _set_known_prices(payload)
        report = simulate_blueprint(Blueprint.model_validate(payload), samples=2, seed=47)
        assert report.typical is not None
        if expected_currency is None:
            assert report.typical.cost is None
            assert report.typical.nodes[0].cost is None
        else:
            assert report.typical.cost is not None
            assert report.typical.cost > Decimal("1")
            assert report.typical.currency == expected_currency


def test_nodo_deterministico_senza_token_resta_costo_zero_non_unknown():
    """L'assenza di fixed_tool_cost riguarda solo tool, non nodi locali senza token."""
    payload = _payload()
    node = payload["nodes"][1]
    node.update({"id": "local", "kind": "deterministic"})
    payload["nodes"] = [node]
    payload["transitions"] = []
    payload["entry_node_ids"] = ["local"]

    report = simulate_blueprint(Blueprint.model_validate(payload), samples=2, seed=53)

    assert report.typical is not None
    assert report.typical.nodes[0].cost == Decimal("0")
    assert report.unknown_prices == ()


def _ciclo_choice_blueprint(*, max_traversals: int | None) -> Blueprint:
    payload = _payload()
    node = payload["nodes"][1]
    node.update({"id": "loop", "description": "Passo opzionale ripetibile."})
    payload["nodes"] = [node]
    payload["entry_node_ids"] = ["loop"]
    payload["transitions"] = [
        {
            "source": "loop",
            "target": "loop",
            "activation": "choice",
            "probability": {
                "min": 0.0,
                "typical": 0.5,
                "max": 1.0,
                "provenance": "declared",
                "confidence": "medium",
                "reason": "Ciclo opzionale dichiarato come scelta.",
            },
            "parallel_group": None,
            "max_traversals": max_traversals,
        }
    ]
    return Blueprint.model_validate(payload)


def test_ciclo_choice_limitato_non_valuta_due_volte_lo_stesso_ramo(monkeypatch):
    """Valutare il ramo scelto sia nell'ordinamento sia nel giro dei gruppi rende la
    lookahead 2^profondita e blocca la CLI su un ciclo dichiarato come scelta."""
    blueprint = _ciclo_choice_blueprint(max_traversals=16)
    chiamate = {"totale": 0}
    originale = preflight_simulate._node_score

    def contato(node, *, mode):
        chiamate["totale"] += 1
        return originale(node, mode=mode)

    monkeypatch.setattr(preflight_simulate, "_node_score", contato)

    report = simulate_blueprint(blueprint, samples=1, seed=11)

    assert report.maximum_status == "finite"
    assert chiamate["totale"] < 5_000


def test_ciclo_choice_illimitato_termina_invece_di_bloccare_la_simulazione():
    """Con activation choice la guardia di ciclo non fermava la lookahead: la stessa
    fixture unbounded terminava con always e non terminava mai con choice."""
    report = simulate_blueprint(
        _ciclo_choice_blueprint(max_traversals=None), samples=3, seed=13
    )

    assert report.maximum_status == "unbounded"
    assert report.maximum is None


def _prezzo_cache_mancante_blueprint() -> Blueprint:
    payload = _payload()
    _set_known_prices(payload)
    payload["models"][0]["cache_read_price_per_million"] = None
    budget = payload["nodes"][0]["budget"]
    budget["retry_probability"].update({"min": 0.0, "typical": 0.0, "max": 0.5})
    budget["max_retries"] = 1
    return Blueprint.model_validate(payload)


def test_prezzo_mancante_dichiara_di_riguardare_il_caso_peggiore():
    """unknown_prices e calcolato sui massimi: senza dirlo, un costo valorizzato accanto
    a un prezzo ignoto lascia il lettore senza sapere quale dei due credere."""
    report = simulate_blueprint(_prezzo_cache_mancante_blueprint(), samples=5, seed=17)

    assert report.unknown_prices == ("economy",)
    assert report.typical is not None and report.typical.cost is not None
    assert report.maximum is not None and report.maximum.cost is None
    assert any("caso peggiore" in assunzione for assunzione in report.assumptions)


def test_merge_interno_di_costi_tool_in_valute_diverse_diventa_unknown():
    """Un futuro aggregatore cross-node non deve conservare una valuta arbitraria."""
    totals = _MutableTotals(
        fixed_tool_cost=Decimal("1.25"), fixed_tool_currency="USD"
    )
    totals.add(
        _MutableTotals(
            fixed_tool_cost=Decimal("2.50"), fixed_tool_currency="EUR"
        )
    )

    assert totals.unknown_tool_cost is True
    assert totals.fixed_tool_currency is None
