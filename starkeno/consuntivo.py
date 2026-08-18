"""Il confronto fra il preventivo di un Blueprint e il lavoro davvero osservato.

**Modulo puro**, come `conto.py`: riceve snapshot gia' letti e restituisce dati. Niente
SQLAlchemy, niente orologio, niente filesystem. E' cosi' che l'attribuzione si prova in
memoria, e che una dichiarazione sbagliata si corregge ricalcolando invece di restare
incisa su una riga.

**I DUE OROLOGI, assunzione dichiarata.** `Marcatore.declared_at` viene dal processo che
serve MCP; `RigaOsservata.timestamp` viene dal transcript scritto dall'agente. Il server
ascolta su `127.0.0.1`, quindi e' la stessa macchina e lo stesso orologio. Si sa anche
come rompe: se il server girasse altrove, sbaglierebbero **solo le righe a cavallo di un
confine fra nodi**, e in silenzio. Se un giorno il server non fosse piu' locale, questa
regola va rivista insieme.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Mapping, Sequence

from starkeno.rules import COMPONENTI_PARZIALI, effective_tokens

if TYPE_CHECKING:  # pragma: no cover - solo per i tipi
    from starkeno.preflight_schema import Blueprint
    from starkeno.preflight_simulate import SimulationReport


@dataclass(frozen=True)
class RigaOsservata:
    """Una riga di `agent_actions`, ridotta a cio' che il confronto usa."""

    session_id: str
    timestamp: datetime          # aware-UTC (invariante 1)
    model_used: str
    tokens_used: int
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    azioni_nella_chiamata: int


@dataclass(frozen=True)
class Marcatore:
    """«Da adesso sto lavorando su questo nodo», dichiarato dall'agente."""

    node_id: str
    declared_at: datetime
    seq: int


@dataclass(frozen=True)
class Esecuzione:
    """Il perimetro dichiarato di un'esecuzione. `ended_at` None significa aperta."""

    run_key: str
    project: str
    blueprint_hash: str
    started_at: datetime
    ended_at: datetime | None
    model_map: Mapping[str, str]


@dataclass(frozen=True)
class Attribuzione:
    """Chi ha prodotto cosa, e cosa non si sa attribuire.

    `per_nodo` segue l'ordine di prima comparsa dei marcatori. Un nodo dichiarato piu'
    volte compare UNA volta con le righe di tutti i suoi intervalli: due voci `review`
    nel confronto sarebbero due nodi che non esistono.
    """

    stato: str                   # ok | aperta | ambigua | senza_osservazioni
    motivo: str
    per_nodo: tuple[tuple[str, tuple[RigaOsservata, ...]], ...]
    non_attribuite: tuple[RigaOsservata, ...]
    senza_sessione: tuple[RigaOsservata, ...]
    sessioni: tuple[str, ...]


@dataclass(frozen=True)
class TotaliOsservati:
    """I totali di un insieme di righe, con la stessa scomposizione della stima.

    `totale_tokens` segue sempre `tokens_used`, anche quando la scomposizione manca o
    e' difettosa: una riga difettosa resta visibile nel totale grezzo invece di sparire.
    Le quattro classi accolgono solo le righe scomposte per intero E accettate dalle
    guardie di qualita' dati, e i due contatori dicono perche' le altre sono fuori:

    - `righe_non_scomposte`: la scomposizione non e' dichiarata (assente o parziale, che
      per `rules.effective_tokens` sono la stessa cosa). E' la forma piu' comune e non e'
      un difetto: nell'SDK i campi cache valgono None su ogni chiamata che non tocca la
      cache;
    - `righe_rifiutate`: la scomposizione e' dichiarata ma si contraddice — un componente
      negativo, una somma dei componenti sopra il totale, un `tokens_used` oltre il tetto
      di plausibilita'. Quello si', e' un difetto, e ha un rimedio diverso.

    Due contatori e non uno perche' i due casi si guardano in modo diverso; ma la regola
    che li separa e' UNA, e sta in `rules.effective_tokens` come per `conto.calcola_conto`.
    """

    chiamate: int
    azioni: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    totale_tokens: int
    righe_non_scomposte: int
    # Senza default, di proposito: un contatore che dice «qualcosa e' stato buttato via»
    # non deve poter valere zero perche' qualcuno ha dimenticato di passarlo.
    righe_rifiutate: int


TOTALI_VUOTI = TotaliOsservati(0, 0, 0, 0, 0, 0, 0, 0, 0)

CLASSIFICABILE = "classificabile"
NON_SCOMPOSTA = "non_scomposta"
RIFIUTATA = "rifiutata"


def _esito_riga(riga: RigaOsservata, *, weights, max_plausible) -> str:
    """Se una riga entra nelle quattro classi, e altrimenti perche' no.

    UNICA autorita' del modulo: `totali` e la moneta chiamano questa, cosi' una riga
    esclusa dalle classi e' esattamente una riga non prezzata. La decisione non e' presa
    qui ma da `rules.effective_tokens`, la stessa che usa `conto.calcola_conto`: i suoi
    quattro rami di qualita' dati esistono gia', e una seconda serie di controlli scritta
    a mano qui divergerebbe come e' gia' successo.

    `COMPONENTI_PARZIALI` non e' un rifiuto ma un'assenza — «una scomposizione parziale
    vale come nessuna scomposizione», la regola dichiarata da `effective_tokens` stesso —
    e finisce in `righe_non_scomposte` insieme alle righe che non dichiarano niente.
    """
    _valore, flag = effective_tokens(
        riga.tokens_used, riga.cache_read_tokens, riga.cache_write_tokens,
        riga.output_tokens, weights=weights, max_plausible=max_plausible,
    )
    if flag is not None and flag != COMPONENTI_PARZIALI:
        return RIFIUTATA
    componenti = (riga.cache_read_tokens, riga.cache_write_tokens, riga.output_tokens)
    if any(componente is None for componente in componenti):
        return NON_SCOMPOSTA
    return CLASSIFICABILE


def totali(
    righe: Sequence[RigaOsservata], *, weights, max_plausible,
) -> TotaliOsservati:
    """Somma le righe, con le stesse guardie di qualita' dati del conto.

    `weights` e `max_plausible` arrivano come PARAMETRI e non da `config`, come in
    `conto.calcola_conto` e per lo stesso motivo: questo modulo e' puro, e un modulo che
    legge la configurazione non si prova in memoria. Le porte (`cli.py`, `mcp_server.py`)
    la leggono e la passano.
    """
    chiamate = azioni = ingresso = uscita = lettura = scrittura = 0
    totale = non_scomposte = rifiutate = 0
    for riga in righe:
        chiamate += 1
        azioni += riga.azioni_nella_chiamata
        totale += riga.tokens_used
        esito = _esito_riga(riga, weights=weights, max_plausible=max_plausible)
        if esito == RIFIUTATA:
            rifiutate += 1
            continue
        if esito == NON_SCOMPOSTA:
            non_scomposte += 1
            continue
        cache_read = riga.cache_read_tokens
        cache_write = riga.cache_write_tokens
        output = riga.output_tokens
        lettura += cache_read
        scrittura += cache_write
        uscita += output
        ingresso += riga.tokens_used - cache_read - cache_write - output
    return TotaliOsservati(
        chiamate=chiamate, azioni=azioni, input_tokens=ingresso, output_tokens=uscita,
        cache_read_tokens=lettura, cache_write_tokens=scrittura, totale_tokens=totale,
        righe_non_scomposte=non_scomposte, righe_rifiutate=rifiutate,
    )


def totali_per_modello(
    righe: Sequence[RigaOsservata], *, weights, max_plausible,
) -> tuple[tuple[str, TotaliOsservati], ...]:
    """I totali separati per `model_used`, che e' la grana su cui si applica un prezzo."""
    raccolta: dict[str, list[RigaOsservata]] = {}
    for riga in righe:
        raccolta.setdefault(riga.model_used, []).append(riga)
    return tuple(
        (nome, totali(raccolta[nome], weights=weights, max_plausible=max_plausible))
        for nome in sorted(raccolta)
    )


def _vuota(stato: str, motivo: str, senza_sessione=()) -> Attribuzione:
    return Attribuzione(
        stato=stato, motivo=motivo, per_nodo=(), non_attribuite=(),
        senza_sessione=tuple(senza_sessione), sessioni=(),
    )


def attribuisci(
    esecuzione: Esecuzione,
    marcatori: Sequence[Marcatore],
    righe: Sequence[RigaOsservata],
) -> Attribuzione:
    """Attribuisce le righe ai nodi dichiarati, o dichiara perche' non lo fa.

    La finestra AUTOREVOLE e' qui: chi legge dal database pre-filtra con un indice, ma
    l'unica regola che conta e' questa, cosi' i confini sono provabili in memoria.

    Le righe con `session_id` vuota vanno in un secchio proprio e **non contano per
    l'ambiguita'**: `record_action` non imposta mai `session_id`, quindi ogni riga
    scritta dal tool `log_agent_action` ha sessione vuota, e una sola di esse renderebbe
    ambigua ogni esecuzione per sempre.
    """
    if esecuzione.ended_at is None:
        return _vuota("aperta", "L'esecuzione non e' stata chiusa: manca ended_at.")

    dentro = [
        riga for riga in righe
        if esecuzione.started_at <= riga.timestamp <= esecuzione.ended_at
    ]
    senza_sessione = tuple(riga for riga in dentro if not riga.session_id)
    con_sessione = [riga for riga in dentro if riga.session_id]

    if not con_sessione:
        return _vuota(
            "senza_osservazioni",
            "Nessuna chiamata con una sessione nota nella finestra dell'esecuzione.",
            senza_sessione,
        )

    sessioni = tuple(sorted({riga.session_id for riga in con_sessione}))
    if len(sessioni) > 1:
        return Attribuzione(
            stato="ambigua",
            motivo=(
                "Nella finestra ci sono %d sessioni distinte (%s): attribuire una di "
                "esse al Blueprint sarebbe un'ipotesi, quindi non se ne attribuisce "
                "nessuna." % (len(sessioni), ", ".join(sessioni))
            ),
            per_nodo=(), non_attribuite=(), senza_sessione=senza_sessione,
            sessioni=sessioni,
        )

    ordinati = sorted(marcatori, key=lambda m: (m.declared_at, m.seq))
    confini = [m.declared_at for m in ordinati] + [esecuzione.ended_at]

    raccolta: dict[str, list[RigaOsservata]] = {}
    for marcatore in ordinati:
        raccolta.setdefault(marcatore.node_id, [])
    non_attribuite: list[RigaOsservata] = []

    for riga in sorted(con_sessione, key=lambda r: r.timestamp):
        indice = _intervallo(riga.timestamp, confini)
        if indice is None:
            non_attribuite.append(riga)
        else:
            raccolta[ordinati[indice].node_id].append(riga)

    return Attribuzione(
        stato="ok", motivo="",
        per_nodo=tuple((nodo, tuple(righe)) for nodo, righe in raccolta.items()),
        non_attribuite=tuple(non_attribuite),
        senza_sessione=senza_sessione,
        sessioni=sessioni,
    )


def _intervallo(quando: datetime, confini: list[datetime]) -> int | None:
    """L'indice dell'intervallo SEMIAPERTO che contiene `quando`, o None.

    Semiaperto a destra: una riga esattamente sul `declared_at` di un marcatore
    appartiene al nodo NUOVO. L'ultimo intervallo chiude su `ended_at` incluso, perche'
    la finestra e' chiusa a destra.
    """
    if len(confini) < 2 or quando < confini[0]:
        return None
    for indice in range(len(confini) - 1):
        inizio, fine = confini[indice], confini[indice + 1]
        ultimo = indice == len(confini) - 2
        if inizio <= quando < fine or (ultimo and quando == fine):
            return indice
    return None


SCENARI = ("optimistic", "typical", "prudent", "maximum")


@dataclass(frozen=True)
class StimaScenario:
    """Un scenario della simulazione, ridotto alle grandezze confrontabili."""

    nome: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    totale_tokens: int
    executions: int
    llm_calls: int
    tool_calls: int
    costo: Decimal | None
    valuta: str | None


@dataclass(frozen=True)
class ConfrontoNodo:
    """Un nodo del Blueprint, con l'osservato accanto allo scenario `typical`.

    NON esiste uno scarto fra chiamate: `executions_stimate` conta invocazioni di nodo
    (una piu' i retry), `chiamate_osservate` conta chiamate API, e un nodo `llm` in una
    sessione reale sono decine di chiamate. Si stampano affiancate e non si sottraggono
    mai — e' il punto in cui sarebbe piu' facile produrre un numero preciso e falso.
    """

    node_id: str
    osservato: TotaliOsservati | None
    stima_typical: StimaScenario | None
    scarto_totale_tokens: int
    executions_stimate: int
    chiamate_osservate: int


MILIONE = Decimal("1000000")


@dataclass(frozen=True)
class Moneta:
    """Il costo osservato, calcolato col listino che ha usato la stima.

    `osservata` copre SOLO le righe di un modello mappato, con un profilo esistente e un
    listino completo. Tutto il resto sta in `token_non_prezzati` e in
    `modelli_senza_prezzo`, ciascuno col MOTIVO: un costo mancante presentato come costo
    basso e' peggio di un costo dichiarato ignoto, e i tre motivi si rimediano in modo
    diverso — dichiararlo, correggere l'id, o completare il listino.
    """

    valuta: str
    osservata: Decimal
    token_non_prezzati: int
    modelli_senza_prezzo: tuple[tuple[str, int, str], ...]


LISTINO_ASSENTE = "listino assente"
VALUTE_DIVERSE = "valute diverse"


def _listini(blueprint: Blueprint):
    """I profili del Blueprint, quelli col listino COMPLETO, e le valute che usano.

    Un punto solo: `calcola_moneta` e `motivo_moneta_assente` devono decidere sugli
    stessi dati, o il costo direbbe una cosa e la spiegazione un'altra.
    """
    profili = {modello.id: modello for modello in blueprint.models}
    listini = {
        identificativo: prezzi
        for identificativo, profilo in profili.items()
        if (prezzi := _prezzi(profilo)) is not None
    }
    valute = {profili[identificativo].currency for identificativo in listini}
    return profili, listini, valute


def motivo_moneta_assente(blueprint: Blueprint) -> str | None:
    """Perche' `calcola_moneta` non puo' produrre un costo, o None se puo'.

    I due casi si rimediano in modo OPPOSTO — completare un listino, oppure riportare
    listini gia' completi a una sola valuta — e una riga sola che ne nomina uno solo
    manda a cercare nel posto sbagliato chi ha l'altro problema. Stessa disciplina dei
    tre motivi di `modelli_senza_prezzo`, applicata all'assenza intera.
    """
    _profili, listini, valute = _listini(blueprint)
    if not listini:
        return LISTINO_ASSENTE
    if len(valute) > 1:
        return VALUTE_DIVERSE
    return None


def calcola_moneta(
    righe: Sequence[RigaOsservata],
    model_map: Mapping[str, str],
    blueprint: Blueprint,
    *,
    weights,
    max_plausible,
) -> Moneta | None:
    """Prezza i token osservati, o restituisce None dichiarando che non si puo'.

    None in due casi soli, quelli che `motivo_moneta_assente` distingue: il Blueprint non
    dichiara **nessun** listino completo, oppure i suoi listini usano valute diverse —
    sommarle produrrebbe un numero che non e' denaro.

    Un modello osservato ma non prezzato non annulla la moneta: finisce in
    `modelli_senza_prezzo` coi suoi token e il MOTIVO, perche' i tre casi si rimediano in
    modo diverso — "non mappato" (assente da `model_map`, va dichiarato), "profilo
    inesistente" (mappato a un id che non e' in `blueprint.models`, l'id va corretto), o
    "listino incompleto" (il profilo esiste ma manca almeno uno dei quattro prezzi, il
    listino va completato). Restituire None qui nasconderebbe proprio la riga che serve a
    rimediare, e confondere i tre motivi farebbe applicare il rimedio sbagliato.
    """
    # La domanda «si puo' prezzare?» si fa a `motivo_moneta_assente` e non si riscrive
    # qui: e' la stessa che risponde all'utente nella resa, e due risposte diverse alla
    # stessa domanda sarebbero il difetto che questo modulo si e' gia' preso una volta.
    if motivo_moneta_assente(blueprint) is not None:
        return None
    profili, listini, valute = _listini(blueprint)

    costo = Decimal("0")
    non_prezzati = 0
    senza_prezzo: list[tuple[str, int, str]] = []

    for nome, totale in totali_per_modello(
        righe, weights=weights, max_plausible=max_plausible
    ):
        identificativo = model_map.get(nome)
        prezzi = listini.get(identificativo) if identificativo is not None else None
        if prezzi is None:
            non_prezzati += totale.totale_tokens
            if identificativo is None:
                motivo = "non mappato"
            elif identificativo not in profili:
                motivo = "profilo inesistente"
            else:
                motivo = "listino incompleto"
            senza_prezzo.append((nome, totale.totale_tokens, motivo))
            continue
        non_prezzati += _token_fuori_dalle_classi(
            righe, nome, weights=weights, max_plausible=max_plausible
        )
        ingresso, uscita, lettura, scrittura = prezzi
        costo += (
            Decimal(totale.input_tokens) * ingresso
            + Decimal(totale.output_tokens) * uscita
            + Decimal(totale.cache_read_tokens) * lettura
            + Decimal(totale.cache_write_tokens) * scrittura
        ) / MILIONE

    return Moneta(
        valuta=valute.pop(),
        osservata=costo,
        token_non_prezzati=non_prezzati,
        modelli_senza_prezzo=tuple(senza_prezzo),
    )


def _prezzi(profilo) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    """I quattro prezzi del profilo, o None se anche uno solo manca.

    Tutti o nessuno: prezzare l'input e ignorare l'output produce un costo che sembra
    completo e non lo e'.
    """
    if profilo is None:
        return None
    valori = (
        profilo.input_price_per_million, profilo.output_price_per_million,
        profilo.cache_read_price_per_million, profilo.cache_write_price_per_million,
    )
    if any(valore is None for valore in valori):
        return None
    return tuple(Decimal(valore) for valore in valori)  # type: ignore[return-value]


def _token_fuori_dalle_classi(
    righe: Sequence[RigaOsservata], modello: str, *, weights, max_plausible,
) -> int:
    """I token grezzi delle righe di `modello` che non sono entrate nelle quattro classi.

    Non si prezzano, e per due motivi diversi. Di una riga NON SCOMPOSTA non si sa quanto
    fosse output, e prezzarla a tariffa input mente proprio sul caso caro. Di una riga
    RIFIUTATA la scomposizione contraddice se stessa — componenti negativi, somma sopra il
    totale — e prezzarla e' peggio ancora: produce un costo con dentro un numero che non
    puo' esistere. In entrambi i casi i token finiscono in `token_non_prezzati` invece di
    sparire, che e' l'unica forma onesta di «non lo so».

    Usa lo STESSO `_esito_riga` di `totali`: una riga fuori dalle classi e' esattamente
    una riga non prezzata, per costruzione e non per coincidenza.
    """
    return sum(
        riga.tokens_used for riga in righe
        if riga.model_used == modello
        and _esito_riga(riga, weights=weights, max_plausible=max_plausible)
        != CLASSIFICABILE
    )


@dataclass(frozen=True)
class Consuntivo:
    """Il confronto completo, o la dichiarazione del perche' non c'e'.

    `motivo_moneta` e `stima_senza_prezzo` sono i due buchi DICHIARATI, uno per lato.
    Il primo dice quale dei due motivi ha reso `moneta` assente; il secondo porta
    `SimulationReport.unknown_prices`, cioe' cio' che la STIMA non ha saputo prezzare.
    Senza il secondo la resa metteva su righe adiacenti un numero onesto (l'osservato,
    che dichiara i suoi modelli senza prezzo) e uno silenziosamente incompleto.
    """

    run_key: str
    project: str
    blueprint_hash: str
    started_at: datetime
    ended_at: datetime | None
    stato: str
    motivo: str
    osservato: TotaliOsservati
    scenari: tuple[StimaScenario, ...]
    posizione: str
    nodi: tuple[ConfrontoNodo, ...]
    non_attribuite: TotaliOsservati
    senza_sessione: TotaliOsservati
    sessioni: tuple[str, ...]
    moneta: Moneta | None = None
    motivo_moneta: str = ""
    stima_senza_prezzo: tuple[str, ...] = ()


def _stima_da_scenario(nome: str, scenario) -> StimaScenario:
    return StimaScenario(
        nome=nome,
        input_tokens=scenario.input_tokens,
        output_tokens=scenario.output_tokens,
        cache_read_tokens=scenario.cache_read_tokens,
        cache_write_tokens=scenario.cache_write_tokens,
        totale_tokens=(scenario.input_tokens + scenario.output_tokens
                       + scenario.cache_read_tokens + scenario.cache_write_tokens),
        executions=sum(nodo.executions for nodo in scenario.nodes),
        llm_calls=scenario.llm_calls,
        tool_calls=scenario.tool_calls,
        costo=scenario.cost,
        valuta=scenario.currency,
    )


def stime_per_scenario(simulazione: SimulationReport) -> tuple[StimaScenario, ...]:
    """Gli scenari presenti, nell'ordine canonico. Quelli `None` restano fuori."""
    presenti = []
    for nome in SCENARI:
        scenario = getattr(simulazione, nome)
        if scenario is not None:
            presenti.append(_stima_da_scenario(nome, scenario))
    return tuple(presenti)


def posizione_nella_banda(totale: int, scenari: Sequence[StimaScenario]) -> str:
    """Dove cade l'osservato rispetto agli scenari. Un solo numero non dice niente.

    Gli scenari assenti si dichiarano assenti: leggerli come zero metterebbe ogni
    osservazione «oltre il massimo», che e' un giudizio, non una misura.
    """
    if not scenari:
        return "banda incompleta: nessuno scenario disponibile"
    mancanti = [nome for nome in SCENARI if nome not in {s.nome for s in scenari}]
    coda = ""
    if mancanti:
        coda = " (banda incompleta: mancano %s)" % ", ".join(mancanti)

    ordinati = sorted(scenari, key=lambda s: s.totale_tokens)
    if totale < ordinati[0].totale_tokens:
        return "sotto %s" % ordinati[0].nome + coda
    for precedente, successivo in zip(ordinati, ordinati[1:]):
        if precedente.totale_tokens <= totale < successivo.totale_tokens:
            if totale == precedente.totale_tokens:
                return "esattamente su %s" % precedente.nome + coda
            return "fra %s e %s" % (precedente.nome, successivo.nome) + coda
    if totale == ordinati[-1].totale_tokens:
        return "esattamente su %s" % ordinati[-1].nome + coda
    return "oltre %s" % ordinati[-1].nome + coda


def costruisci(
    esecuzione: Esecuzione,
    attribuzione: Attribuzione,
    simulazione: SimulationReport,
    blueprint: Blueprint,
    *,
    weights,
    max_plausible,
) -> Consuntivo:
    """Il confronto, o la dichiarazione del perche' non si puo' fare.

    `weights` e `max_plausible` attraversano tutto il modulo fino a `totali`: sono le
    guardie di qualita' dati di `rules.effective_tokens`, e arrivano dalle porte
    (`cli.py`, `mcp_server.py`) perche' un modulo puro non legge `config`.
    """
    qualita = {"weights": weights, "max_plausible": max_plausible}
    scenari = stime_per_scenario(simulazione)
    non_attribuite = totali(attribuzione.non_attribuite, **qualita)
    senza_sessione = totali(attribuzione.senza_sessione, **qualita)
    motivo_moneta = motivo_moneta_assente(blueprint) or ""

    if attribuzione.stato != "ok":
        return Consuntivo(
            run_key=esecuzione.run_key, project=esecuzione.project,
            blueprint_hash=esecuzione.blueprint_hash,
            started_at=esecuzione.started_at, ended_at=esecuzione.ended_at,
            stato=attribuzione.stato, motivo=attribuzione.motivo,
            osservato=TOTALI_VUOTI, scenari=scenari, posizione="",
            nodi=(), non_attribuite=non_attribuite, senza_sessione=senza_sessione,
            sessioni=attribuzione.sessioni, moneta=None,
            motivo_moneta=motivo_moneta,
            stima_senza_prezzo=tuple(simulazione.unknown_prices),
        )

    righe_osservate = ([riga for _, righe in attribuzione.per_nodo for riga in righe]
                       + list(attribuzione.non_attribuite))
    osservato = totali(righe_osservate, **qualita)
    moneta = calcola_moneta(
        righe_osservate, esecuzione.model_map, blueprint, **qualita
    )
    per_nodo_typical = _nodi_typical(simulazione)
    osservato_per_nodo = dict(attribuzione.per_nodo)

    nodi = []
    for nodo in blueprint.nodes:
        righe = osservato_per_nodo.get(nodo.id)
        totali_nodo = totali(righe, **qualita) if righe else None
        stima = per_nodo_typical.get(nodo.id)
        nodi.append(ConfrontoNodo(
            node_id=nodo.id,
            osservato=totali_nodo,
            stima_typical=stima,
            scarto_totale_tokens=(
                (totali_nodo.totale_tokens if totali_nodo else 0)
                - (stima.totale_tokens if stima else 0)
            ),
            executions_stimate=stima.executions if stima else 0,
            chiamate_osservate=totali_nodo.chiamate if totali_nodo else 0,
        ))
    nodi.sort(key=lambda n: (-abs(n.scarto_totale_tokens), n.node_id))

    return Consuntivo(
        run_key=esecuzione.run_key, project=esecuzione.project,
        blueprint_hash=esecuzione.blueprint_hash,
        started_at=esecuzione.started_at, ended_at=esecuzione.ended_at,
        stato="ok", motivo="",
        osservato=osservato, scenari=scenari,
        posizione=posizione_nella_banda(osservato.totale_tokens, scenari),
        nodi=tuple(nodi), non_attribuite=non_attribuite,
        senza_sessione=senza_sessione, sessioni=attribuzione.sessioni,
        moneta=moneta, motivo_moneta=motivo_moneta,
        stima_senza_prezzo=tuple(simulazione.unknown_prices),
    )


def _nodi_typical(simulazione: SimulationReport) -> dict[str, StimaScenario]:
    """Il subtotale per nodo dello scenario `typical`, indicizzato per `node_id`."""
    scenario = simulazione.typical
    if scenario is None:
        return {}
    risultato = {}
    for nodo in scenario.nodes:
        risultato[nodo.node_id] = StimaScenario(
            nome="typical",
            input_tokens=nodo.input_tokens,
            output_tokens=nodo.output_tokens,
            cache_read_tokens=nodo.cache_read_tokens,
            cache_write_tokens=nodo.cache_write_tokens,
            totale_tokens=(nodo.input_tokens + nodo.output_tokens
                           + nodo.cache_read_tokens + nodo.cache_write_tokens),
            executions=nodo.executions,
            llm_calls=nodo.llm_calls,
            tool_calls=nodo.tool_calls,
            costo=nodo.cost,
            valuta=nodo.currency,
        )
    return risultato


NOTA_CACHE = (
    "Nota: la simulazione conta cache_write una volta per invocazione e cache_read solo "
    "sui retry, mentre un agente vero rispedisce il contesto a ogni turno. Un cache_read "
    "osservato molto piu' grande dello stimato e' atteso e sistematico, non un errore di "
    "calcolo."
)

_RIMEDIO_PER_MOTIVO = {
    "non mappato": "dichiaralo in model_map",
    "profilo inesistente": "correggi l'id dichiarato in model_map",
    "listino incompleto": "completa il listino del modello nel Blueprint",
}

# I due motivi per cui la moneta e' assente, ciascuno col SUO rimedio. Dirne uno solo per
# entrambi e' una riga falsa meta' delle volte, e manda a cercare nel posto sbagliato: un
# Blueprint con due modelli prezzati per intero in USD e in EUR ha listini completissimi.
_MONETA_ASSENTE_PER_MOTIVO = {
    LISTINO_ASSENTE: (
        "Moneta: assente — il Blueprint non dichiara un listino completo. Servono tutti "
        "e quattro i prezzi (input, output, cache read, cache write) di almeno un "
        "modello: completane uno."
    ),
    VALUTE_DIVERSE: (
        "Moneta: assente — i listini del Blueprint sono completi ma usano valute "
        "diverse, e sommarle produrrebbe un numero che non e' denaro. Riportali a una "
        "sola valuta."
    ),
}


def rendi_testo(consuntivo: Consuntivo) -> str:
    """La resa condivisa da CLI e tool MCP: una sola verita', non due.

    ECCEZIONE DICHIARATA. Uno stato diverso da `ok` stampa il motivo e, quando presente,
    il conteggio diagnostico delle righe senza sessione nella finestra («Righe senza
    sessione»): spiega perche' non c'e' un confronto, non lo sostituisce. Nessun numero di
    RISULTATO — totali, per nodo, moneta — viene mai stampato quando lo stato non e' `ok`;
    quel conteggio e' l'unica eccezione, ed e' voluta.
    """
    righe = [
        "Consuntivo %s — progetto %s" % (consuntivo.run_key, consuntivo.project),
        "Blueprint %s" % consuntivo.blueprint_hash,
        "Finestra: %s → %s" % (
            consuntivo.started_at.isoformat(),
            consuntivo.ended_at.isoformat() if consuntivo.ended_at else "aperta",
        ),
        "Stato: %s" % consuntivo.stato,
    ]
    if consuntivo.stato != "ok":
        righe.append(consuntivo.motivo)
        # Diagnostico, non di risultato (vedi l'eccezione nel docstring): resta anche qui.
        if consuntivo.senza_sessione.chiamate:
            righe.append(
                "Righe senza sessione nella finestra: %d (mai attribuite)"
                % consuntivo.senza_sessione.chiamate
            )
        return "\n".join(righe)

    osservato = consuntivo.osservato
    righe.append("")
    righe.append("Osservato su %d chiamate (%d azioni):" % (osservato.chiamate, osservato.azioni))
    righe.append(
        "  input %d · output %d · cache read %d · cache write %d · totale %d"
        % (osservato.input_tokens, osservato.output_tokens, osservato.cache_read_tokens,
           osservato.cache_write_tokens, osservato.totale_tokens)
    )
    if osservato.righe_non_scomposte:
        righe.append(
            "  %d chiamate senza scomposizione: contate nel totale, fuori dalle classi"
            % osservato.righe_non_scomposte
        )
    if osservato.righe_rifiutate:
        righe.append(
            "  %d chiamate con scomposizione incoerente (componente negativo, somma "
            "sopra il totale, o totale implausibile): contate nel totale, fuori dalle "
            "classi e mai prezzate" % osservato.righe_rifiutate
        )
    righe.append("")
    righe.append("Stimato:")
    for scenario in consuntivo.scenari:
        righe.append("  %-11s totale %d" % (scenario.nome, scenario.totale_tokens))
    righe.append("L'osservato cade: %s" % consuntivo.posizione)

    righe.append("")
    righe.append("Per nodo, ordinato per scarto (stima: scenario typical):")
    for nodo in consuntivo.nodi:
        if nodo.osservato is None:
            righe.append("  %-16s nessuna osservazione" % nodo.node_id)
            continue
        righe.append(
            "  %-16s osservato %d su %d chiamate · stimato %d · scarto %+d "
            "(invocazioni stimate %d, unita' diversa dalle chiamate)"
            % (nodo.node_id, nodo.osservato.totale_tokens, nodo.chiamate_osservate,
               nodo.stima_typical.totale_tokens if nodo.stima_typical else 0,
               nodo.scarto_totale_tokens, nodo.executions_stimate)
        )

    if consuntivo.non_attribuite.chiamate:
        righe.append("")
        righe.append(
            "Non attribuite: %d chiamate, %d token (fuori da ogni intervallo dichiarato)"
            % (consuntivo.non_attribuite.chiamate, consuntivo.non_attribuite.totale_tokens)
        )
    if consuntivo.senza_sessione.chiamate:
        righe.append(
            "Senza sessione: %d chiamate, %d token (mai attribuite, non rendono ambigua)"
            % (consuntivo.senza_sessione.chiamate, consuntivo.senza_sessione.totale_tokens)
        )

    righe.append("")
    if consuntivo.moneta is None:
        # .get come sotto: un motivo che il dizionario non conosce si dichiara invece di
        # far cadere la resa, e non si spaccia per uno dei due noti.
        righe.append(_MONETA_ASSENTE_PER_MOTIVO.get(
            consuntivo.motivo_moneta,
            "Moneta: assente — motivo non riconosciuto: %s" % (
                consuntivo.motivo_moneta or "non dichiarato"),
        ))
    else:
        moneta = consuntivo.moneta
        righe.append("Moneta osservata: %s %s" % (moneta.osservata, moneta.valuta))
        for scenario in consuntivo.scenari:
            if scenario.costo is not None:
                righe.append("  stimato %-11s %s %s" % (
                    scenario.nome, scenario.costo, scenario.valuta))
        # I buchi della STIMA, accanto alla stima. L'osservato dichiara gia' i propri
        # (`modelli_senza_prezzo`); senza questa riga il costo stimato sopra sembrava
        # completo mentre non lo era, e due numeri adiacenti avevano onesta' diversa.
        # NON si sopprime il costo stimato: `preflight_simulate` e' esplicito che «uno
        # scenario con costo valorizzato non ha usato le categorie mancanti», quindi il
        # numero e' valido e sopprimerlo butterebbe via una misura per prudenza.
        if consuntivo.stima_senza_prezzo:
            righe.append(
                "  stima incompleta: nel Blueprint mancano i prezzi di %s — il costo "
                "stimato non li comprende (uno scenario con costo valorizzato non ha "
                "usato le categorie mancanti)"
                % ", ".join(consuntivo.stima_senza_prezzo)
            )
        if moneta.token_non_prezzati:
            righe.append("  %d token non prezzati" % moneta.token_non_prezzati)
        for nome, token, motivo in moneta.modelli_senza_prezzo:
            # .get, non [.]: un motivo che _RIMEDIO_PER_MOTIVO non conosce non deve far
            # cadere l'intera resa con un KeyError. Si dichiara invece di nascondere.
            rimedio = _RIMEDIO_PER_MOTIVO.get(motivo, "motivo non riconosciuto: %s" % motivo)
            righe.append(
                "  modello senza prezzo (%s): %s (%d token) — %s"
                % (motivo, nome, token, rimedio)
            )

    righe.append("")
    righe.append(NOTA_CACHE)
    return "\n".join(righe)
