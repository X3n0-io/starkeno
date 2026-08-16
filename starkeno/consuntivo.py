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
from typing import Mapping, Sequence


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

    `totale_tokens` segue sempre `tokens_used`, anche quando la scomposizione manca:
    una riga difettosa resta visibile nel totale grezzo invece di sparire. Le quattro
    classi accolgono solo le righe scomposte per intero, e `righe_non_scomposte` dice
    quante sono rimaste fuori.
    """

    chiamate: int
    azioni: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    totale_tokens: int
    righe_non_scomposte: int


TOTALI_VUOTI = TotaliOsservati(0, 0, 0, 0, 0, 0, 0, 0)


def totali(righe: Sequence[RigaOsservata]) -> TotaliOsservati:
    """Somma le righe. Una scomposizione parziale vale come nessuna scomposizione."""
    chiamate = azioni = ingresso = uscita = lettura = scrittura = 0
    totale = non_scomposte = 0
    for riga in righe:
        chiamate += 1
        azioni += riga.azioni_nella_chiamata
        totale += riga.tokens_used
        componenti = (riga.cache_read_tokens, riga.cache_write_tokens, riga.output_tokens)
        if any(componente is None for componente in componenti):
            non_scomposte += 1
            continue
        cache_read, cache_write, output = componenti
        lettura += cache_read
        scrittura += cache_write
        uscita += output
        ingresso += riga.tokens_used - cache_read - cache_write - output
    return TotaliOsservati(
        chiamate=chiamate, azioni=azioni, input_tokens=ingresso, output_tokens=uscita,
        cache_read_tokens=lettura, cache_write_tokens=scrittura, totale_tokens=totale,
        righe_non_scomposte=non_scomposte,
    )


def totali_per_modello(
    righe: Sequence[RigaOsservata],
) -> tuple[tuple[str, TotaliOsservati], ...]:
    """I totali separati per `model_used`, che e' la grana su cui si applica un prezzo."""
    raccolta: dict[str, list[RigaOsservata]] = {}
    for riga in righe:
        raccolta.setdefault(riga.model_used, []).append(riga)
    return tuple((nome, totali(raccolta[nome])) for nome in sorted(raccolta))


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
