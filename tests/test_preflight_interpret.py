# tests/test_preflight_interpret.py
"""L'interprete: orchestrazione pura, e il confine che tiene fuori la rete."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


RADICE = Path(__file__).resolve().parent.parent
PACCHETTO = RADICE / "starkeno"

# L'unico modulo autorizzato a importare l'SDK e a nominare le variabili d'ambiente.
MODULO_CLIENT = "preflight_anthropic.py"


def moduli_importati(percorso: Path) -> set[str]:
    """I nomi dei moduli importati da un file, letti dall'AST.

    Non dal testo: una ricerca testuale di "anthropic" trova anche il commento che dice
    dove si puo' importare, e un test che fallisce sulla propria documentazione e'
    inservibile. Stessa tecnica di `tests/test_rules_primitives.py`.
    """
    albero = ast.parse(percorso.read_text(encoding="utf-8"))
    nomi: set[str] = set()
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Import):
            nomi.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nomi.add(nodo.module.split(".")[0])
    return nomi


def test_anthropic_e_dichiarato_come_dipendenza():
    testo = (RADICE / "pyproject.toml").read_text(encoding="utf-8")
    assert "anthropic" in testo, "l'SDK non e' dichiarato: l'installazione non lo avra'"


def test_solo_il_modulo_client_importa_lo_sdk():
    """Se l'SDK trapela altrove, il resto di Preflight smette di essere testabile
    senza rete e senza chiave — che e' il punto della §3.3 della specifica."""
    colpevoli = []
    for modulo in sorted(PACCHETTO.glob("*.py")):
        if modulo.name == MODULO_CLIENT:
            continue
        if "anthropic" in moduli_importati(modulo):
            colpevoli.append(modulo.name)
    assert not colpevoli, "importano anthropic fuori dal client: %r" % colpevoli


def test_solo_il_modulo_client_nomina_le_variabili_della_chiave():
    """Il nome della variabile e' contratto pubblico: deve vivere in un posto solo,
    altrimenti cambiarlo significa cercarlo."""
    colpevoli = []
    for modulo in sorted(PACCHETTO.glob("*.py")):
        if modulo.name == MODULO_CLIENT:
            continue
        testo = modulo.read_text(encoding="utf-8")
        if "ANTHROPIC_API_KEY" in testo:
            colpevoli.append(modulo.name)
    assert not colpevoli, "nominano la variabile fuori dal client: %r" % colpevoli


import json  # noqa: E402

from starkeno import preflight_interpret as interprete  # noqa: E402
from starkeno.preflight_schema import load_blueprint  # noqa: E402


FIXTURE = RADICE / "tests" / "fixtures" / "preflight" / "minimal.json"


def _interpretazione(**modifiche) -> str:
    """Una risposta del modello ben formata, modificabile per rompere un pezzo solo."""
    blueprint = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blueprint.update(modifiche)
    return json.dumps({
        "blueprint": blueprint,
        "assumptions": ["Il revisore e' una persona."],
        "open_questions": ["Quante modifiche entrano di solito nella nota?"],
    })


class ClientFinto:
    """Un `ModelClient` che risponde da un copione. Non tocca la rete."""

    def __init__(self, *risposte: str) -> None:
        self.risposte = list(risposte)
        self.chiamate: list[dict] = []

    def complete(self, *, system, schema, user_text, previous=None):
        self.chiamate.append({"system": system, "schema": schema,
                              "user_text": user_text, "previous": previous})
        testo = self.risposte.pop(0)
        return interprete.ModelReply(
            text=testo,
            usage=interprete.ModelUsage(input_tokens=100, output_tokens=200),
            model="modello-finto",
        )


def test_una_sola_chiamata_quando_l_uscita_e_valida():
    """Il vincolo economico della §3.2 e' il punto, non un dettaglio."""
    client = ClientFinto(_interpretazione())

    esito = interprete.interpret_text("un agente scrive una nota", client=client)

    assert len(client.chiamate) == 1
    assert esito.repaired is False
    assert esito.interpretation.blueprint.goal.id == "goal-release"
    assert esito.interpretation.open_questions


def test_un_solo_retry_di_riparazione_e_il_secondo_fallimento_e_dichiarato():
    """Due fallimenti non diventano tre chiamate: si dichiara e ci si ferma."""
    client = ClientFinto("{non e' json", "nemmeno questo")

    with pytest.raises(interprete.InterpretationError) as errore:
        interprete.interpret_text("testo", client=client)

    assert len(client.chiamate) == 2, "il retry deve essere UNO"
    assert "riparazione" in str(errore.value).lower()


def test_il_retry_riceve_l_uscita_precedente_e_l_errore():
    """Un retry che non dice cosa e' andato storto e' una seconda estrazione a caso."""
    client = ClientFinto("{rotto", _interpretazione())

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is True
    precedente = client.chiamate[1]["previous"]
    assert precedente is not None
    uscita, errore = precedente
    assert uscita == "{rotto"
    assert errore, "il retry non sa cosa correggere"


def test_il_draft_resta_non_confermato():
    """L'interpretazione di un modello non diventa mai verita' strutturata da sola."""
    client = ClientFinto(_interpretazione(confirmed=True, revision=3))

    esito = interprete.interpret_text("testo", client=client)

    assert esito.interpretation.blueprint.confirmed is False


def test_un_riferimento_rotto_provoca_la_riparazione_non_un_errore_interno():
    """Il validatore semantico di pydantic e' cio' che lo schema JSON non puo' imporre:
    e' il caso d'uso vero del retry."""
    rotto = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rotto["nodes"][0]["agent_id"] = "fantasma"
    client = ClientFinto(
        json.dumps({"blueprint": rotto, "assumptions": [], "open_questions": []}),
        _interpretazione(),
    )

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is True


def test_un_provenance_measured_viene_rifiutato():
    """Un modello non ha misurato niente. `measured` da' a un numero inventato l'aria
    di un numero osservato, che e' il fallimento peggiore per questo progetto."""
    bugiardo = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bugiardo["nodes"][0]["budget"]["output"]["provenance"] = "measured"
    client = ClientFinto(
        json.dumps({"blueprint": bugiardo, "assumptions": [], "open_questions": []}),
        _interpretazione(),
    )

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is True, "un `measured` inventato deve essere corretto"


def test_il_consumo_somma_le_due_chiamate():
    client = ClientFinto("{rotto", _interpretazione())

    esito = interprete.interpret_text("testo", client=client)

    assert esito.usage.input_tokens == 200
    assert esito.usage.output_tokens == 400


def test_il_prefisso_e_stabile_fra_chiamate_diverse():
    """Niente timestamp o id: un prefisso che cambia rompe la cache del fornitore,
    e la cache e' cio' che rende quasi gratis il retry di riparazione."""
    primo = ClientFinto(_interpretazione())
    secondo = ClientFinto(_interpretazione())

    interprete.interpret_text("testo A", client=primo)
    interprete.interpret_text("testo B", client=secondo)

    assert primo.chiamate[0]["system"] == secondo.chiamate[0]["system"]
    assert primo.chiamate[0]["schema"] == secondo.chiamate[0]["schema"]


def test_il_preventivo_e_una_stima_dichiarata_non_una_misura():
    assert interprete.estimate_tokens("") > 0, "lo schema e il prompt costano comunque"
    assert interprete.estimate_tokens("x" * 3500) > interprete.estimate_tokens("x")


def test_l_interprete_non_tocca_rete_ambiente_ne_orologio():
    """Purezza: e' cio' che rende questi test eseguibili senza chiave (§8)."""
    vietati = {"os", "anthropic", "httpx", "requests", "socket", "time", "datetime"}
    trovati = vietati & moduli_importati(PACCHETTO / "preflight_interpret.py")
    assert not trovati, "preflight_interpret importa %r" % sorted(trovati)


def test_un_provenance_measured_in_fixed_tool_cost_viene_rifiutato():
    """`fixed_tool_cost` e' un settimo campo con `provenance`, portato da un nodo
    `kind="tool"`: non e' fra i sei nomi elencati a mano, ma il rifiuto di `measured`
    deve valere anche li', non solo sui campi che qualcuno si e' ricordato di scrivere."""
    bugiardo = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bugiardo["nodes"].append({
        "id": "invoke-tool",
        "kind": "tool",
        "description": "Chiama uno strumento a pagamento.",
        "agent_id": None,
        "model_id": None,
        "tool_id": None,
        "skill_ids": [],
        "context_ids": [],
        "budget": {
            "instructions": {"min": 0, "typical": 0, "max": 0, "provenance": "declared", "confidence": "high", "reason": "Nessun prompt."},
            "dynamic_context": {"min": 0, "typical": 0, "max": 0, "provenance": "declared", "confidence": "high", "reason": "Nessun contesto."},
            "output": {"min": 0, "typical": 0, "max": 0, "provenance": "declared", "confidence": "high", "reason": "Nessun output LLM."},
            "cacheable_fraction": {"min": 0.0, "typical": 0.0, "max": 0.0, "provenance": "declared", "confidence": "high", "reason": "Nessuna cache."},
            "latency_ms": {"min": 100, "typical": 300, "max": 1000, "provenance": "declared", "confidence": "medium", "reason": "Chiamata allo strumento."},
            "retry_probability": {"min": 0.0, "typical": 0.0, "max": 0.0, "provenance": "declared", "confidence": "high", "reason": "Nessun retry."},
            "max_retries": 0,
            "fixed_tool_cost": {
                "min": 1, "typical": 1, "max": 1, "currency": "USD",
                "provenance": "measured", "confidence": "high",
                "reason": "Prezzo dello strumento.",
            },
        },
    })
    client = ClientFinto(
        json.dumps({"blueprint": bugiardo, "assumptions": [], "open_questions": []}),
        _interpretazione(),
    )

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is True, "un `measured` in fixed_tool_cost deve essere corretto"
