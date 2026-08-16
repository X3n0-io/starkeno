# starkeno/preflight_interpret.py
"""Da testo libero a Draft Blueprint: contratto, prompt e orchestrazione.

**Qui non c'e' rete, non c'e' ambiente e non c'e' orologio.** Il client e' un
`Protocol`, quindi tutto questo modulo si prova con un oggetto finto: e' la ragione per
cui la §3.3 della specifica chiede un'interfaccia sottile, e la ragione per cui i test
della parte B non spendono soldi e non richiedono una chiave.

Il vincolo economico della §3.2 vive qui e in nessun altro posto: **una** chiamata nel
percorso standard, **un solo** retry, e soltanto se l'uscita non valida.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol

from starkeno.preflight_schema import Blueprint, FrozenModel, Provenance
from starkeno.preflight_service import BlueprintInputError, normalize_draft


class InterpretationError(ValueError):
    """L'interpretazione non ha prodotto un Blueprint valido, nemmeno dopo il retry."""


@dataclass(frozen=True)
class ModelUsage:
    """Il consumo osservato. Sempre misurato dalla risposta, mai stimato."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def piu(self, altro: ModelUsage) -> ModelUsage:
        return ModelUsage(
            input_tokens=self.input_tokens + altro.input_tokens,
            output_tokens=self.output_tokens + altro.output_tokens,
            cache_read_tokens=self.cache_read_tokens + altro.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + altro.cache_write_tokens,
        )


@dataclass(frozen=True)
class ModelReply:
    text: str
    usage: ModelUsage
    model: str


class ModelClient(Protocol):
    """Il minimo che serve per interpretare un testo. Deliberatamente povero.

    `previous` porta la coppia (uscita rifiutata, errore di validazione) e vale solo
    per il retry: e' l'unica forma di conversazione che la §3.2 ammette.
    """

    def complete(
        self,
        *,
        system: str,
        schema: dict,
        user_text: str,
        previous: tuple[str, str] | None = None,
    ) -> ModelReply: ...


class Interpretation(FrozenModel):
    """Il Draft piu' cio' che il modello ha dovuto assumere per produrlo.

    Assunzioni e domande stanno qui e non dentro `Blueprint`, che ha `extra="forbid"`
    ed e' un contratto immutabile: allargarlo per comodita' di questo comando
    significherebbe cambiare lo schema di tutti gli altri.

    Eredita `FrozenModel` da `preflight_schema`, quindi `frozen=True` e `extra="forbid"`
    arrivano da li': lo schema che il modello riceve avra' `additionalProperties: false`
    su ogni oggetto, che gli structured output richiedono.
    """

    blueprint: Blueprint
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()


# Stima locale, non una misura. Ricalibrala dai numeri del verbale del Task 2.
CHARACTERS_PER_TOKEN = 3.5

SYSTEM_PROMPT = """You turn a free-text description of an agent workflow into a Draft \
Blueprint that validates against the given JSON schema.

Rules you must not break:

- Never claim a number was measured. Every estimate carries a `provenance` of \
"declared" when the user stated it, "inferred" when you derived it from what they \
wrote, or "default" when you had nothing to go on. "measured" is reserved for numbers \
StarkEno observed itself and is never correct in your output.
- Set `confidence` honestly. "low" is the right answer more often than not.
- Every assumption you had to make goes in `assumptions`, in the user's own terms.
- Everything you could not determine goes in `open_questions`, phrased so a person can \
answer it in one line.
- Prefer a small honest Blueprint over a large invented one. Do not add nodes, agents, \
tools or models the text does not support.
- `confirmed` is always false. `revision` is always 1 and `parent_revision` is null.
- Prices you do not know stay null. Do not guess them.
"""


def estimate_tokens(user_text: str) -> int:
    """Preventivo **stimato** dei token in ingresso, calcolato in locale.

    Non chiama `count_tokens`: sarebbe una seconda richiesta di rete prima della sola
    chiamata che la §3.2 concede. Chi la mostra deve dire che e' una stima — un numero
    stimato presentato come misurato e' esattamente cio' che questo progetto rifiuta.
    """
    caratteri = len(SYSTEM_PROMPT) + len(_schema_text()) + len(user_text)
    return int(caratteri / CHARACTERS_PER_TOKEN) + 1


def _schema_text() -> str:
    import json

    return json.dumps(interpretation_schema(), sort_keys=True, separators=(",", ":"))


def interpretation_schema() -> dict:
    """Lo schema che il modello deve rispettare. Stabile: nessun dato dinamico."""
    return Interpretation.model_json_schema()


def interpretation_task(user_text: str) -> str:
    """Compone il compito per un agente che non ha un `ModelClient`: le regole del
    `SYSTEM_PROMPT`, lo schema JSON di `Interpretation` e il testo dell'utente.

    E' la controparte «senza rete» di `interpret_text`: la porta MCP della parte B
    restituisce questa stringa a un agente (Claude Code, Codex, ...) che la legge, la
    esegue con le proprie capacita' di interpretazione e rimanda il JSON risultante a
    `read_interpretation`. StarkEno non genera mai il Draft da solo.

    Prefisso stabile per costruzione: dipende solo da `SYSTEM_PROMPT`, dallo schema (che
    non cambia a runtime) e da `user_text`. Nessun timestamp, id o percorso — un compito
    che varia fra due chiamate con lo stesso testo romperebbe la cache del fornitore
    lato agente, esattamente cio' che la stabilita' del prefisso in `interpret_text`
    protegge gia' lato modello diretto.
    """
    return (
        f"{SYSTEM_PROMPT}\n"
        "JSON schema the output must validate against "
        "(additionalProperties: false on every object):\n"
        f"{_schema_text()}\n\n"
        "User text:\n"
        f"{user_text}"
    )


def _ogni_provenance(valore: object, percorso: str) -> Iterator[tuple[str, str]]:
    """Percorre ricorsivamente `valore` e produce `(percorso, valore_letto)` per ogni
    campo tipizzato `Provenance`, ovunque compaia nell'albero.

    Non enumera i punti noti per nome o posizione: guarda l'annotazione dichiarata di
    ogni campo, `type(istanza).model_fields[nome].annotation` (mai l'attributo di
    istanza `istanza.model_fields`, deprecato da pydantic 2.11 e quindi fatale sotto
    `-W error`). Un campo `Provenance` aggiunto domani in un punto nuovo dello schema
    viene trovato senza che questa funzione debba ricordarsene.

    **Il limite di quella promessa, detto invece che scoperto al quarto giro.** La ricerca
    copre i campi annotati **esattamente** `Provenance` dentro un `FrozenModel`, anche
    annidato in liste o tuple: sono le 4 dichiarazioni e i 9 percorsi che lo schema usa
    oggi, verificati. **Non** coprirebbe un campo dichiarato `Provenance | None` oppure
    `tuple[Provenance, ...]` direttamente su un modello, perche' quell'annotazione non e'
    `Provenance` e una stringa nuda non viene attraversata dalla discesa. Oggi nessun
    punto dello schema usa quelle forme; se un giorno servissero, questa funzione va
    estesa insieme. Enumerare i punti a mano ha gia' riaperto lo stesso difetto tre volte:
    la promessa va tenuta stretta a cio' che il codice mantiene davvero.

    La discesa dentro i modelli e le sequenze segue invece il VALORE a runtime, non
    l'annotazione statica del campo che lo contiene: e' cosi' che un campo opzionale
    come `NodeBudget.fixed_tool_cost` (`MoneyEstimate | None`) o `Transition.probability`
    si attraversa quando vale qualcosa e si salta silenziosamente quando vale `None`,
    senza bisogno di un caso speciale per l'`Optional`.
    """
    if isinstance(valore, FrozenModel):
        for nome, campo in type(valore).model_fields.items():
            valore_campo = getattr(valore, nome)
            figlio = f"{percorso}.{nome}"
            if campo.annotation is Provenance:
                yield figlio, valore_campo
            else:
                yield from _ogni_provenance(valore_campo, figlio)
    elif isinstance(valore, (list, tuple)):
        for indice, elemento in enumerate(valore):
            etichetta = getattr(elemento, "id", indice)
            yield from _ogni_provenance(elemento, f"{percorso}[{etichetta}]")


def _rifiuta_measured(interpretazione: Interpretation) -> None:
    """Un modello non misura niente. `measured` renderebbe un numero inventato
    indistinguibile da uno osservato, e su questo il progetto non transige.

    Percorre l'intero Blueprint con `_ogni_provenance` e rifiuta 'measured' ovunque
    compaia un campo tipizzato `Provenance` - i campi di `NodeBudget` (compreso
    l'opzionale `fixed_tool_cost`), `transitions[].probability.provenance`,
    `contexts[].source` e qualunque punto aggiunto in futuro - senza enumerarli per
    nome: e' il tipo del campo a deciderlo, non la sua posizione nell'albero."""
    for percorso, valore in _ogni_provenance(interpretazione.blueprint, "blueprint"):
        if valore == "measured":
            raise ValueError(
                f"{percorso} dichiara provenance 'measured', ma nulla e' stato "
                "misurato. Usa 'declared', 'inferred' o 'default'."
            )


def read_interpretation(text: str) -> Interpretation:
    """Valida un JSON candidato e lo trasforma in un'`Interpretation` fidata.

    Nome pubblico di quella che era `_leggi`: e' il punto d'ingresso che sia
    `interpret_text` (via un `ModelClient`) sia il tool MCP `preflight_save_draft`
    (via un JSON che l'agente ha prodotto da solo, senza `ModelClient`) chiamano per
    passare dal testo grezzo a un Draft fidato. Fa sempre tutte e tre le cose, nello
    stesso ordine: validazione pydantic contro lo schema, `normalize_draft` (che
    garantisce `confirmed=False` su un Draft), e `_rifiuta_measured` — nessuna via
    d'ingresso puo' saltarne una.

    Solleva su qualunque fallimento — JSON malformato, schema non rispettato,
    riferimenti rotti, `measured` inventato — sempre con un `ValueError` (diretto o
    tramite `pydantic.ValidationError`, che ne e' una sottoclasse): il chiamante decide
    se propagarlo o trasformarlo in testo per l'agente.
    """
    import json

    dati = json.loads(text)
    interpretazione = Interpretation.model_validate(dati)
    normalizzato = normalize_draft(
        interpretazione.blueprint.model_dump_json(), format_hint="json"
    )
    interpretazione = interpretazione.model_copy(update={"blueprint": normalizzato})
    _rifiuta_measured(interpretazione)
    return interpretazione


@dataclass(frozen=True)
class InterpretationResult:
    interpretation: Interpretation
    usage: ModelUsage
    repaired: bool
    model: str


def interpret_text(user_text: str, *, client: ModelClient) -> InterpretationResult:
    """Una chiamata; se l'uscita non valida, **una** riparazione; poi si dichiara.

    Non esiste un terzo tentativo e non esiste un ripiego che indovini un Blueprint
    senza modello: la §3.3 lo vieta, perche' un Draft inventato in silenzio e' peggio
    di un comando che si ferma.
    """
    schema = interpretation_schema()
    prima = client.complete(system=SYSTEM_PROMPT, schema=schema, user_text=user_text)
    try:
        return InterpretationResult(
            interpretation=read_interpretation(prima.text),
            usage=prima.usage,
            repaired=False,
            model=prima.model,
        )
    except (ValueError, BlueprintInputError) as primo_errore:
        motivo = " ".join(str(primo_errore).splitlines())[:2000]

    seconda = client.complete(
        system=SYSTEM_PROMPT,
        schema=schema,
        user_text=user_text,
        previous=(prima.text, motivo),
    )
    consumo = prima.usage.piu(seconda.usage)
    try:
        return InterpretationResult(
            interpretation=read_interpretation(seconda.text),
            usage=consumo,
            repaired=True,
            model=seconda.model,
        )
    except (ValueError, BlueprintInputError) as secondo_errore:
        raise InterpretationError(
            "L'interpretazione non ha prodotto un Blueprint valido nemmeno dopo la "
            f"riparazione. Primo errore: {motivo}. Secondo errore: {secondo_errore}"
        ) from secondo_errore
