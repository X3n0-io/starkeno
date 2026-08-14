"""Il modello puro e deterministico del conto.

Riceve snapshot gia' letti dal database: non importa SQLAlchemy, filesystem o orologio.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from starkeno.rules import effective_tokens


@dataclass(frozen=True)
class AzioneConto:
    project: str
    session_id: str
    model_used: str
    timestamp: datetime
    tokens_used: int
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    azioni_nella_chiamata: int
    skill: str
    plugin: str
    mcp_server: str
    is_sidechain: int
    esito_noto: int


@dataclass(frozen=True)
class VoceConto:
    nome: str
    chiamate: int
    azioni: int
    totale_pesato: float
    lavoro_pesato: float
    caricamento_pesato: float
    riletture_pesate: float
    marginale_pesato: float


@dataclass(frozen=True)
class RitmoGiorno:
    giorno: date
    chiamate: int
    azioni: int
    totale_pesato: float
    lavoro_pesato: float
    caricamento_pesato: float
    riletture_pesate: float
    marginale_pesato: float


@dataclass(frozen=True)
class Conto:
    chiamate: int
    azioni: int
    totale_pesato: float
    lavoro_pesato: float
    caricamento_pesato: float
    riletture_pesate: float
    marginale_pesato: float
    esiti_ignoti: int
    righe_non_classificabili: int
    per_progetto: tuple[VoceConto, ...]
    per_modello: tuple[VoceConto, ...]
    per_sessione: tuple[VoceConto, ...]
    per_skill: tuple[VoceConto, ...]
    per_plugin: tuple[VoceConto, ...]
    per_mcp_server: tuple[VoceConto, ...]
    per_subagente: tuple[VoceConto, ...]
    ritmo: tuple[RitmoGiorno, ...]


@dataclass
class _Totali:
    chiamate: int = 0
    azioni: int = 0
    totale_pesato: float = 0
    lavoro_pesato: float = 0
    caricamento_pesato: float = 0
    riletture_pesate: float = 0
    marginale_pesato: float = 0

    def aggiungi(self, azioni, totale, lavoro, caricamento, riletture):
        self.chiamate += 1
        self.azioni += azioni
        self.totale_pesato += totale
        self.lavoro_pesato += lavoro
        self.caricamento_pesato += caricamento
        self.riletture_pesate += riletture
        self.marginale_pesato += lavoro + caricamento


def _voce(nome: str, totali: _Totali) -> VoceConto:
    return VoceConto(nome, totali.chiamate, totali.azioni, totali.totale_pesato,
                      totali.lavoro_pesato, totali.caricamento_pesato,
                      totali.riletture_pesate, totali.marginale_pesato)


def _voci(totali: dict[str, _Totali]) -> tuple[VoceConto, ...]:
    return tuple(_voce(nome, totali[nome]) for nome in sorted(totali))


def calcola_conto(azioni, *, fuso, now, weights, max_plausible) -> Conto:
    """Calcola il conto da azioni gia' normalizzate.

    `totale_pesato` segue esattamente `effective_tokens`: anche una scomposizione
    difettosa resta osservabile tramite il suo totale grezzo. Solo una scomposizione
    completa e coerente entra nelle attribuzioni marginali.
    """
    complessivo = _Totali()
    per_progetto = defaultdict(_Totali)
    per_modello = defaultdict(_Totali)
    per_sessione = defaultdict(_Totali)
    per_skill = defaultdict(_Totali)
    per_plugin = defaultdict(_Totali)
    per_mcp_server = defaultdict(_Totali)
    per_subagente = defaultdict(_Totali)

    oggi = now.astimezone(fuso).date()
    giorni = [oggi - timedelta(days=offset) for offset in range(6, -1, -1)]
    ritmo = {giorno: _Totali() for giorno in giorni}
    esiti_ignoti = 0
    righe_non_classificabili = 0

    for azione in azioni:
        totale, flag = effective_tokens(
            azione.tokens_used, azione.cache_read_tokens, azione.cache_write_tokens,
            azione.output_tokens, weights=weights, max_plausible=max_plausible,
        )
        componenti = (azione.cache_read_tokens, azione.cache_write_tokens,
                      azione.output_tokens)
        completa = flag is None and all(componente is not None for componente in componenti)
        if completa:
            cache_read, cache_write, output = componenti
            ingresso = azione.tokens_used - cache_read - cache_write - output
            riletture = cache_read * weights["cache_read"]
            caricamento = cache_write * weights["cache_write"]
            lavoro = ingresso * weights["input"] + output * weights["output"]
        else:
            lavoro = caricamento = riletture = 0
            righe_non_classificabili += 1

        numero_azioni = azione.azioni_nella_chiamata
        bersagli = (complessivo, per_progetto[azione.project], per_modello[azione.model_used],
                    per_sessione[azione.session_id])
        for bersaglio in bersagli:
            bersaglio.aggiungi(numero_azioni, totale, lavoro, caricamento, riletture)
        for etichetta, raccolta in ((azione.skill, per_skill), (azione.plugin, per_plugin),
                                    (azione.mcp_server, per_mcp_server)):
            if etichetta:
                raccolta[etichetta].aggiungi(
                    numero_azioni, lavoro + caricamento, lavoro, caricamento, 0)
        if azione.is_sidechain:
            per_subagente["sub-agente"].aggiungi(
                numero_azioni, lavoro + caricamento, lavoro, caricamento, 0)
        giorno = azione.timestamp.astimezone(fuso).date()
        if giorno in ritmo:
            ritmo[giorno].aggiungi(numero_azioni, totale, lavoro, caricamento, riletture)
        if not azione.esito_noto:
            esiti_ignoti += 1

    ritmo_giorni = tuple(
        RitmoGiorno(giorno, totali.chiamate, totali.azioni, totali.totale_pesato,
                     totali.lavoro_pesato, totali.caricamento_pesato,
                     totali.riletture_pesate, totali.marginale_pesato)
        for giorno, totali in ritmo.items()
    )
    return Conto(
        complessivo.chiamate, complessivo.azioni, complessivo.totale_pesato,
        complessivo.lavoro_pesato, complessivo.caricamento_pesato,
        complessivo.riletture_pesate, complessivo.marginale_pesato, esiti_ignoti,
        righe_non_classificabili, _voci(per_progetto), _voci(per_modello),
        _voci(per_sessione), _voci(per_skill), _voci(per_plugin),
        _voci(per_mcp_server), _voci(per_subagente), ritmo_giorni,
    )
