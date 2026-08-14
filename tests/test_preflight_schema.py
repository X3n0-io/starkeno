import json
from decimal import Decimal
from pathlib import Path

import pytest

from starkeno.preflight_schema import (
    Blueprint,
    IntEstimate,
    MoneyEstimate,
    blueprint_hash,
    dump_blueprint,
    load_blueprint,
)


FIXTURE = Path(__file__).parent / "fixtures" / "preflight" / "minimal.json"


def test_round_trip_json_yaml_preserva_il_blueprint_e_hash():
    """Una serializzazione non deve perdere dati o cambiare il seed deterministico."""
    originale = load_blueprint(FIXTURE.read_text(encoding="utf-8"), format_hint="json")
    da_json = load_blueprint(dump_blueprint(originale, format="json"), format_hint="json")
    da_yaml = load_blueprint(dump_blueprint(originale, format="yaml"), format_hint="yaml")

    assert da_json == da_yaml == originale
    assert blueprint_hash(da_json) == blueprint_hash(da_yaml)


def test_riferimento_a_nodo_inesistente_viene_rifiutato():
    """Un arco verso un nodo assente renderebbe il grafo non simulabile."""
    dati = json.loads(FIXTURE.read_text(encoding="utf-8"))
    dati["transitions"][0]["target"] = "manca"

    with pytest.raises(ValueError, match="manca"):
        Blueprint.model_validate(dati)


def test_transizioni_duplicate_per_chiave_stabile_vengono_rifiutate():
    """Due archi indistinguibili colliderebbero nella base quantitativa del report."""
    dati = json.loads(FIXTURE.read_text(encoding="utf-8"))
    duplicata = json.loads(json.dumps(dati["transitions"][0]))
    duplicata["max_traversals"] = 2
    dati["transitions"].append(duplicata)

    with pytest.raises(
        ValueError,
        match=r"transizioni duplicate.*draft.*review.*always",
    ):
        Blueprint.model_validate(dati)


def test_transizioni_distinte_per_group_source_target_o_activation_fanno_roundtrip():
    """La chiave univoca non deve vietare archi semanticamente distinguibili."""
    dati = json.loads(FIXTURE.read_text(encoding="utf-8"))
    originale = dati["transitions"][0]
    gruppo_diverso = json.loads(json.dumps(originale))
    gruppo_diverso["parallel_group"] = "secondario"
    estremi_diversi = json.loads(json.dumps(originale))
    estremi_diversi.update({"source": "review", "target": "draft"})
    activation_diversa = json.loads(json.dumps(originale))
    activation_diversa["activation"] = "choice"
    dati["transitions"].extend(
        (gruppo_diverso, estremi_diversi, activation_diversa)
    )

    blueprint = Blueprint.model_validate(dati)

    assert load_blueprint(
        dump_blueprint(blueprint, format="json"), format_hint="json"
    ) == blueprint
    assert load_blueprint(
        dump_blueprint(blueprint, format="yaml"), format_hint="yaml"
    ) == blueprint


def test_intervallo_deve_essere_ordinato():
    """Una stima con tipico fuori intervallo renderebbe ambigui gli scenari."""
    with pytest.raises(ValueError, match="min.*typical.*max"):
        IntEstimate(
            min=10,
            typical=4,
            max=8,
            provenance="declared",
            confidence="high",
            reason="test",
        )


@pytest.mark.parametrize("parent_revision", [1, 2])
def test_revisione_padre_deve_essere_anteriore(parent_revision):
    """Un padre uguale o successivo renderebbe impossibile la genealogia del Blueprint."""
    dati = json.loads(FIXTURE.read_text(encoding="utf-8"))
    dati["revision"] = 1
    dati["parent_revision"] = parent_revision

    with pytest.raises(ValueError, match="parent_revision.*revision"):
        Blueprint.model_validate(dati)


def test_yaml_non_costruisce_oggetti_python():
    """Blueprint YAML non deve eseguire costruttori arbitrari."""
    with pytest.raises(ValueError, match="YAML"):
        load_blueprint("!!python/object/apply:os.system ['whoami']", format_hint="yaml")


def test_money_estimate_decimal_roundtrip_frozen_e_ordinato():
    """Il costo tool deve conservare Decimal e non accettare valuta vuota o intervalli invertiti."""
    estimate = MoneyEstimate(
        min=Decimal("0.010"),
        typical=Decimal("0.025"),
        max=Decimal("0.090"),
        currency="EUR",
        provenance="declared",
        confidence="high",
        reason="Tariffa sintetica.",
    )

    assert MoneyEstimate.model_validate_json(estimate.model_dump_json()) == estimate
    assert estimate.typical == Decimal("0.025")
    with pytest.raises(Exception):
        estimate.max = Decimal("1")  # type: ignore[misc]
    with pytest.raises(ValueError, match="min.*typical.*max"):
        MoneyEstimate(
            min=Decimal("2"), typical=Decimal("1"), max=Decimal("3"), currency="EUR",
            provenance="declared", confidence="high", reason="Errata.",
        )
    with pytest.raises(ValueError, match="currency"):
        MoneyEstimate(
            min=Decimal("0"), typical=Decimal("0"), max=Decimal("0"), currency="",
            provenance="declared", confidence="high", reason="Errata.",
        )


def test_solo_i_nodi_tool_possono_dichiarare_fixed_tool_cost():
    """Un costo fisso su nodi non-tool confonderebbe costo modello e costo tool."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["nodes"][0]["budget"]["fixed_tool_cost"] = {
        "min": "0",
        "typical": "0",
        "max": "0",
        "currency": "USD",
        "provenance": "declared",
        "confidence": "high",
        "reason": "Gratuito.",
    }

    with pytest.raises(ValueError, match="tool"):
        Blueprint.model_validate(payload)
