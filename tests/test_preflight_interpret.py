# tests/test_preflight_interpret.py
"""L'interprete: orchestrazione pura, e il confine che tiene fuori la rete."""
from __future__ import annotations

import ast
import tomllib
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


def test_l_sdk_non_e_piu_una_dipendenza():
    """L'inverso del test che stava qui, e non la sua cancellazione.

    Fino al 15/08/2026 StarkEno doveva chiamare l'API con una PROPRIA chiave, e questo
    test pretendeva l'SDK fra le dipendenze. Il cambio di architettura di quel giorno lo
    ha reso inutile: l'agente genera, StarkEno valida, e nessun modello viene chiamato.
    Il briefing del 16/08 lo aveva gia' scritto — «andra' rimossa con un commit di revert
    dedicato» — e il client `preflight_anthropic.py` non e' mai stato costruito.

    Rovesciato invece che tolto perche' l'invariante che conta e' cambiato di segno: non
    «l'SDK c'e'», ma «non serve». E' la promessa che il README fa a chi installa, e una
    promessa senza guardia si perde alla prima aggiunta distratta.

    Letto con tomllib e non cercando la stringa nel file: un rilievo di revisione del
    16/08 osservava che la ricerca testuale passa anche su un commento che nomina l'SDK.
    """
    dipendenze = tomllib.loads(
        (RADICE / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["dependencies"]

    colpevoli = [d for d in dipendenze if "anthropic" in d.lower()]
    assert not colpevoli, (
        "StarkEno dichiara di non chiamare nessun modello, ma installa un client di API "
        "LLM: %r" % colpevoli
    )


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
from starkeno.preflight_schema import FrozenModel, Provenance, load_blueprint  # noqa: E402


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


def test_il_compito_contiene_le_regole_lo_schema_e_il_testo_ed_e_stabile():
    """Il compito e' cio' che l'agente legge per produrre l'Interpretation: deve
    portare le regole del SYSTEM_PROMPT, lo schema JSON e il testo dell'utente."""
    primo = interprete.interpretation_task("un agente scrive una nota di rilascio")
    secondo = interprete.interpretation_task("un agente scrive una nota di rilascio")

    assert primo == secondo, "lo stesso testo deve produrre lo stesso compito"
    assert "Never claim a number was measured" in primo, "mancano le regole"
    assert '"open_questions"' in primo, "manca lo schema"
    assert "un agente scrive una nota di rilascio" in primo, "manca il testo dell'utente"


def test_il_compito_non_porta_nient_altro_di_locale_oltre_al_testo_utente():
    """L'unica differenza fra due compiti con testi diversi deve essere il testo:
    niente timestamp, id o altro dato che varierebbe da una chiamata all'altra e
    romperebbe la cache del fornitore lato agente."""
    con_a = interprete.interpretation_task("AAAAAAAAAA")
    con_b = interprete.interpretation_task("BBBBBBBBBB")

    assert con_a.replace("AAAAAAAAAA", "BBBBBBBBBB") == con_b


def test_read_interpretation_e_il_nome_pubblico_della_validazione():
    """`read_interpretation` sostituisce `_leggi` come punto d'ingresso pubblico: deve
    fare esattamente cio' che faceva prima, validazione pydantic e rifiuto di measured
    inclusi, perche' e' quello che i tool MCP della parte B chiameranno direttamente."""
    interpretazione = interprete.read_interpretation(_interpretazione())
    assert interpretazione.blueprint.goal.id == "goal-release"

    bugiardo = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bugiardo["nodes"][0]["budget"]["output"]["provenance"] = "measured"
    payload = json.dumps({"blueprint": bugiardo, "assumptions": [], "open_questions": []})

    with pytest.raises(ValueError):
        interprete.read_interpretation(payload)


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


def test_un_provenance_measured_in_transitions_probability_viene_rifiutato():
    """Il secondo affioramento del difetto: `blueprint.transitions[].probability.provenance`
    e' un `Provenance` come quelli di `NodeBudget`, ma `_rifiuta_measured` iterava solo
    su `nodo.budget` e non lo vedeva mai. Una probabilita' di transizione dichiarata
    'measured' e' altrettanto inventata di un budget 'measured'."""
    bugiardo = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bugiardo["transitions"][0]["probability"] = {
        "min": 0.1, "typical": 0.5, "max": 0.9,
        "provenance": "measured", "confidence": "high",
        "reason": "Osservata nei log di produzione.",
    }
    client = ClientFinto(
        json.dumps({"blueprint": bugiardo, "assumptions": [], "open_questions": []}),
        _interpretazione(),
    )

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is True, (
        "un `measured` nella probabilita' di transizione deve essere corretto"
    )


def test_un_provenance_measured_in_contexts_source_viene_rifiutato():
    """Il terzo affioramento: `blueprint.contexts[].source` e' tipizzato `Provenance`
    esattamente come `NodeBudget.instructions.provenance`, ma il campo si chiama
    `source`, non `provenance` - un'enumerazione per nome non lo avrebbe mai trovato."""
    bugiardo = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bugiardo["contexts"][0]["source"] = "measured"
    client = ClientFinto(
        json.dumps({"blueprint": bugiardo, "assumptions": [], "open_questions": []}),
        _interpretazione(),
    )

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is True, "un `measured` in contexts[].source deve essere corretto"


class _RamoSconosciuto(FrozenModel):
    """Estraneo allo schema Preflight per costruzione: serve solo al test che segue,
    per provare che il cercatore di `Provenance` segue il TIPO del campo e non un
    elenco di percorsi noti."""

    grado: Provenance


class _AlberoSconosciuto(FrozenModel):
    """Un contenitore che nidifica `_RamoSconosciuto` in una forma che nessun punto
    reale dello schema di Preflight usa."""

    rami: tuple[_RamoSconosciuto, ...]


def test_il_rifiuto_di_measured_segue_il_tipo_non_un_elenco_di_percorsi():
    """Regressione strutturale, non tautologica: se `_rifiuta_measured` tornasse a
    un'enumerazione a mano dei punti noti - i campi di `NodeBudget`,
    `transitions[].probability`, `contexts[].source`, cioe' esattamente i tre
    affioramenti gia' corretti - i due test sopra continuerebbero comunque a
    passare, perche' quei tre punti sarebbero di nuovo elencati a mano. Un campo
    `Provenance` in una posizione mai vista - come questa, costruita apposta e del
    tutto estranea allo schema di Preflight - e' cio' che un'enumerazione, per
    quanto aggiornata, non puo' coprire per costruzione. Il meccanismo su cui
    `_rifiuta_measured` si appoggia deve trovarlo lo stesso, perche' segue
    l'annotazione di tipo del campo e non il suo nome o la sua posizione
    nell'albero."""
    albero = _AlberoSconosciuto(
        rami=(_RamoSconosciuto(grado="declared"), _RamoSconosciuto(grado="measured"))
    )

    trovati = list(interprete._ogni_provenance(albero, "radice"))

    assert any(valore == "measured" for _, valore in trovati), (
        "il cercatore strutturale non ha trovato un campo Provenance annidato in una "
        "forma mai vista prima: e' rimasto legato ai percorsi noti"
    )


def test_measured_dentro_reason_non_e_un_falso_positivo():
    """Il criterio deve essere il TIPO del campo, non il valore trovato in giro: un
    `reason` di testo libero puo' legittimamente contenere la parola 'measured' (per
    esempio per spiegare perche' una stima non lo e') senza che il Draft venga
    rifiutato."""
    onesto = json.loads(FIXTURE.read_text(encoding="utf-8"))
    onesto["nodes"][0]["budget"]["output"]["reason"] = (
        "Non e' measured: e' una stima inferita dalla lunghezza del testo utente."
    )
    client = ClientFinto(
        json.dumps({"blueprint": onesto, "assumptions": [], "open_questions": []})
    )

    esito = interprete.interpret_text("testo", client=client)

    assert esito.repaired is False, (
        "la parola 'measured' dentro reason non deve scatenare una riparazione"
    )
    assert "measured" in esito.interpretation.blueprint.nodes[0].budget.output.reason
