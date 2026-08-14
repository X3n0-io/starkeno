"""Task 5 — R2 `expensive_model` e R4 `steady_waste`.

Le due regole che parlano di soldi. Condividono le guardie (modelli non mappati, righe a
token non utilizzabili) e ricevono una `WindowStats` GIA' AGGREGATA.

**Perche' aggregata e non una lista di record.** Misurato su una finestra di 24h di un
agente a 1 azione/secondo (86.400 righe): caricarla come oggetti ORM costa 1,17 s,
come tuple grezze 0,15 s, mentre la stessa aggregazione fatta in SQL costa 0,048 s. Con
200 agenti a giro, caricare le finestre non e' praticabile. `rules.py` resta comunque
pura e testabile: riceve una struct che i test costruiscono a mano.

**Dove finisce ciascuna soglia**, perche' e' un seam che si sbaglia facilmente:

  soglie di VALORE   (EXPENSIVE_TRIVIAL_TOKENS, HEAVY_TOKENS, MAX_PLAUSIBLE_TOKENS)
      -> applicate in SQL da db.py, che le riceve come parametri
  soglie di CONTEGGIO e QUOTA  (MIN_OCCURRENCES, MIN_SHARE, MAX_ZERO_SHARE,
                                DAILY_TOKENS, MIN_ACTIONS_FOR_SUM, MAX_UNMAPPED_SHARE)
      -> applicate qui, in rules.py
"""
from datetime import datetime, timedelta, timezone

from starkeno.config import snapshot
from starkeno.rules import (
    NON_VALUTABILE,
    OK,
    VIOLAZIONE,
    WindowStats,
    classifica_modelli,
    valuta_r2,
    valuta_r4,
)

ORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)

# Valori DIVERSI dai default, cosi' che una regola che li ignorasse fallisca.
CONF = snapshot(
    EXPENSIVE_TRIVIAL_TOKENS=800,
    EXPENSIVE_MIN_OCCURRENCES=12,
    EXPENSIVE_MIN_SHARE=0.50,
    EXPENSIVE_MAX_ZERO_SHARE=0.25,
    MAX_UNMAPPED_SHARE=0.30,
    HEAVY_TOKENS=20_000,
    HEAVY_MIN_OCCURRENCES=10,
    HEAVY_DAILY_TOKENS=400_000,
    HEAVY_MIN_ACTIONS_FOR_SUM=4,
)

TIERS = {"claude-opus-4-5": "frontier", "claude-sonnet-4-5": "standard",
         "claude-haiku-4-5": "economy"}


def stats(**override):
    """Una WindowStats plausibile, con i campi che il test vuole cambiare."""
    valori = dict(
        righe_totali=100,
        frontier_valide=50,
        frontier_scartate_zero=0,
        frontier_banali=0,
        frontier_pesanti=0,
        somma_effective_frontier=0.0,
        ultimo_frontier=ORA,
        ultimo_frontier_banale=None,
        ultimo_frontier_pesante=None,
    )
    valori.update(override)
    return WindowStats(**valori)


# =============================================================== classificazione
def test_unmapped_models_are_named_in_the_classification():
    """Il motivo deve NOMINARE le stringhe non riconosciute.

    Senza, l'astensione e' un vicolo cieco: si sa che qualcosa non e' mappato ma non
    cosa. Con i nomi, la correzione e' una riga di MODEL_TIERS.
    """
    c = classifica_modelli(
        {"claude-opus-4-5": 30, "gpt-5.2-turbo": 10, "un-modello-nuovo": 5}, TIERS
    )

    assert set(c.frontier) == {"claude-opus-4-5"}
    assert set(c.non_mappati) == {"gpt-5.2-turbo", "un-modello-nuovo"}
    assert abs(c.quota_non_mappata - 15 / 45) < 1e-9


def test_classification_resolves_provider_specific_ids():
    """I nomi grezzi restituiti sono quelli DEL DATABASE, non quelli normalizzati.

    Servono a costruire la clausola `model_used IN (...)` della query successiva: se
    tornassero normalizzati, quella query non troverebbe nessuna riga.
    """
    c = classifica_modelli(
        {"us.anthropic.claude-opus-4-5-20251101-v1:0": 20, "anthropic/claude-sonnet-4-5": 5},
        TIERS,
    )

    assert c.frontier == ("us.anthropic.claude-opus-4-5-20251101-v1:0",)
    assert c.non_mappati == ()


# ============================================================= R2 expensive_model
def test_r2_fires_on_repeated_trivial_frontier_calls():
    esito = valuta_r2(
        stats(frontier_valide=20, frontier_banali=CONF.EXPENSIVE_MIN_OCCURRENCES,
              ultimo_frontier_banale=ORA - timedelta(minutes=3)),
        classificazione=classifica_modelli({"claude-opus-4-5": 20}, TIERS),
        config=CONF,
    )

    assert esito.stato == VIOLAZIONE
    assert esito.ultimo_contributo == ORA - timedelta(minutes=3)


def test_r2_needs_both_the_count_and_the_share():
    """Le due condizioni sono congiuntive, e il confine e' esatto su entrambe."""
    n = CONF.EXPENSIVE_MIN_OCCURRENCES
    cls = classifica_modelli({"claude-opus-4-5": 100}, TIERS)

    # conteggio sotto soglia, share altissima
    sotto = valuta_r2(stats(frontier_valide=n - 1, frontier_banali=n - 1,
                            ultimo_frontier_banale=ORA), classificazione=cls, config=CONF)
    assert sotto.stato == OK

    # conteggio a soglia, share appena sotto
    totali = int(n / CONF.EXPENSIVE_MIN_SHARE) + 1     # share < MIN_SHARE
    share_bassa = valuta_r2(stats(frontier_valide=totali, frontier_banali=n,
                                  ultimo_frontier_banale=ORA), classificazione=cls, config=CONF)
    assert share_bassa.stato == OK
    assert n / totali < CONF.EXPENSIVE_MIN_SHARE

    # conteggio a soglia, share esattamente a soglia
    esatti = int(n / CONF.EXPENSIVE_MIN_SHARE)
    a_soglia = valuta_r2(stats(frontier_valide=esatti, frontier_banali=n,
                               ultimo_frontier_banale=ORA), classificazione=cls, config=CONF)
    assert n / esatti >= CONF.EXPENSIVE_MIN_SHARE
    assert a_soglia.stato == VIOLAZIONE


def test_r2_abstains_when_too_many_models_are_unmapped():
    """**Il buco che il terzo stato esiste per chiudere.**

    Un agente i cui nomi modello non normalizzano ha denominatore zero. Senza questa
    guardia la protezione anti-divisione restituirebbe OK, e R2 e R4 — le due sole regole
    che parlano di soldi — sarebbero cieche per sempre senza nemmeno un'astensione.
    """
    cls = classifica_modelli({"un-modello-ignoto": 50, "claude-opus-4-5": 10}, TIERS)
    assert cls.quota_non_mappata > CONF.MAX_UNMAPPED_SHARE

    esito = valuta_r2(stats(frontier_valide=10), classificazione=cls, config=CONF)

    assert esito.stato == NON_VALUTABILE
    assert "un-modello-ignoto" in esito.motivo, "il motivo non nomina il modello sconosciuto"


def test_r2_abstains_when_the_window_is_entirely_unmapped():
    cls = classifica_modelli({"solo-questo": 40}, TIERS)
    esito = valuta_r2(stats(frontier_valide=0), classificazione=cls, config=CONF)

    assert esito.stato == NON_VALUTABILE
    assert esito.stato != OK


def test_r2_abstains_when_too_many_rows_have_unusable_tokens():
    """Zero e' dato mancante, non task piccolo: la colonna e' nullable=False senza validazione."""
    cls = classifica_modelli({"claude-opus-4-5": 40}, TIERS)
    esito = valuta_r2(
        stats(frontier_valide=30, frontier_scartate_zero=20, frontier_banali=30,
              ultimo_frontier_banale=ORA),
        classificazione=cls, config=CONF,
    )

    assert esito.stato == NON_VALUTABILE
    assert "token" in esito.motivo.lower()


def test_r2_abstains_when_there_are_no_frontier_calls_at_all():
    """Nessuna chiamata frontier non e' salute: e' assenza di prove."""
    cls = classifica_modelli({"claude-haiku-4-5": 500}, TIERS)
    esito = valuta_r2(stats(frontier_valide=0), classificazione=cls, config=CONF)

    assert esito.stato == NON_VALUTABILE


# ================================================================ R4 steady_waste
def test_r4_count_branch_fires_on_repeated_heavy_calls():
    cls = classifica_modelli({"claude-opus-4-5": 15}, TIERS)
    esito = valuta_r4(
        stats(frontier_valide=15, frontier_pesanti=CONF.HEAVY_MIN_OCCURRENCES,
              somma_effective_frontier=15 * 60_000, ultimo_frontier_pesante=ORA),
        classificazione=cls, config=CONF,
    )

    assert esito.stato == VIOLAZIONE
    assert esito.evidenza["ramo"] == "conteggio"


def test_r4_aggregate_branch_closes_the_band_between_r2_and_r4():
    """100 chiamate da 8k al giorno: nessuna e' "grande", la spesa totale si'.

    R2 copre le chiamate sotto la soglia banale, il ramo a conteggio quelle sopra
    HEAVY_TOKENS; in mezzo nessuna regola guardava la spesa AGGREGATA. 100 x 8k = 800k
    e' praticamente la stessa spesa di 15 x 60k = 900k, ed esito opposto solo perche'
    distribuita su chiamate piu' piccole.
    """
    cls = classifica_modelli({"claude-opus-4-5": 100}, TIERS)
    esito = valuta_r4(
        stats(frontier_valide=100, frontier_pesanti=0,
              somma_effective_frontier=100 * 8_000, ultimo_frontier=ORA),
        classificazione=cls, config=CONF,
    )

    assert esito.stato == VIOLAZIONE
    assert esito.evidenza["ramo"] == "aggregato"


def test_r4_aggregate_branch_ignores_a_single_expensive_call():
    """**C11.** Una chiamata sola non e' *steady*.

    Senza `HEAVY_MIN_ACTIONS_FOR_SUM`, una singola chiamata sopra HEAVY_DAILY_TOKENS
    farebbe scattare `steady_waste`. R2 pretende venti occorrenze e R3 ne pretende due
    proprio per non trasformare un fatto isolato in un alert; il ramo aggregato di R4
    non aveva alcun conteggio minimo, e la simmetria mancava.

    Un picco isolato e' gia' il mestiere di R3.
    """
    cls = classifica_modelli({"claude-opus-4-5": 1}, TIERS)
    esito = valuta_r4(
        stats(frontier_valide=1, frontier_pesanti=1,
              somma_effective_frontier=600_000, ultimo_frontier=ORA,
              ultimo_frontier_pesante=ORA),
        classificazione=cls, config=CONF,
    )

    assert esito.stato == OK, "una chiamata sola ha fatto scattare steady_waste"


def test_r4_aggregate_branch_fires_at_exactly_the_minimum_number_of_actions():
    """Il confine di C11: a MIN_ACTIONS_FOR_SUM esatte deve scattare."""
    n = CONF.HEAVY_MIN_ACTIONS_FOR_SUM
    cls = classifica_modelli({"claude-opus-4-5": n}, TIERS)
    per_chiamata = CONF.HEAVY_DAILY_TOKENS / n

    esito = valuta_r4(
        stats(frontier_valide=n, frontier_pesanti=0,
              somma_effective_frontier=n * per_chiamata, ultimo_frontier=ORA),
        classificazione=cls, config=CONF,
    )
    assert esito.stato == VIOLAZIONE

    sotto = valuta_r4(
        stats(frontier_valide=n - 1, frontier_pesanti=0,
              somma_effective_frontier=n * per_chiamata, ultimo_frontier=ORA),
        classificazione=cls, config=CONF,
    )
    assert sotto.stato == OK


def test_r4_count_branch_fires_before_the_aggregate_one():
    """`HEAVY_MIN_OCCURRENCES x HEAVY_TOKENS` sta SOTTO `HEAVY_DAILY_TOKENS`.

    Non e' un'incoerenza: sono due coperture diverse, e il ramo a conteggio e' piu'
    sensibile perche' chiamate grandi ripetute sono un segnale piu' forte della stessa
    spesa diluita. Il test fissa il rapporto cosi' che una taratura futura se ne accorga.
    """
    minimo_conteggio = CONF.HEAVY_MIN_OCCURRENCES * CONF.HEAVY_TOKENS
    assert minimo_conteggio < CONF.HEAVY_DAILY_TOKENS

    cls = classifica_modelli({"claude-opus-4-5": CONF.HEAVY_MIN_OCCURRENCES}, TIERS)
    esito = valuta_r4(
        stats(frontier_valide=CONF.HEAVY_MIN_OCCURRENCES,
              frontier_pesanti=CONF.HEAVY_MIN_OCCURRENCES,
              somma_effective_frontier=minimo_conteggio, ultimo_frontier_pesante=ORA),
        classificazione=cls, config=CONF,
    )
    assert esito.stato == VIOLAZIONE
    assert esito.evidenza["ramo"] == "conteggio"


def test_r4_shares_the_unmapped_guard_with_r2():
    cls = classifica_modelli({"ignoto": 50, "claude-opus-4-5": 10}, TIERS)
    esito = valuta_r4(stats(frontier_valide=10, somma_effective_frontier=999_999),
                      classificazione=cls, config=CONF)

    assert esito.stato == NON_VALUTABILE
    assert "ignoto" in esito.motivo


def test_r4_is_ok_when_nothing_crosses_either_branch():
    cls = classifica_modelli({"claude-opus-4-5": 30}, TIERS)
    esito = valuta_r4(
        stats(frontier_valide=30, frontier_pesanti=CONF.HEAVY_MIN_OCCURRENCES - 1,
              somma_effective_frontier=CONF.HEAVY_DAILY_TOKENS - 1, ultimo_frontier=ORA),
        classificazione=cls, config=CONF,
    )

    assert esito.stato == OK
    assert esito.motivo is None


# ============================================================ config iniettata
def test_both_rules_use_the_injected_thresholds():
    cls = classifica_modelli({"claude-opus-4-5": 40}, TIERS)
    dati_r2 = stats(frontier_valide=20, frontier_banali=15, ultimo_frontier_banale=ORA)
    dati_r4 = stats(frontier_valide=20, frontier_pesanti=0,
                    somma_effective_frontier=300_000, ultimo_frontier=ORA)

    severa = snapshot(EXPENSIVE_MIN_OCCURRENCES=15, EXPENSIVE_MIN_SHARE=0.50,
                      HEAVY_DAILY_TOKENS=300_000, HEAVY_MIN_ACTIONS_FOR_SUM=4)
    permissiva = snapshot(EXPENSIVE_MIN_OCCURRENCES=20, EXPENSIVE_MIN_SHARE=0.90,
                          HEAVY_DAILY_TOKENS=900_000, HEAVY_MIN_ACTIONS_FOR_SUM=4)

    assert valuta_r2(dati_r2, classificazione=cls, config=severa).stato == VIOLAZIONE
    assert valuta_r2(dati_r2, classificazione=cls, config=permissiva).stato == OK
    assert valuta_r4(dati_r4, classificazione=cls, config=severa).stato == VIOLAZIONE
    assert valuta_r4(dati_r4, classificazione=cls, config=permissiva).stato == OK


def test_evidence_is_json_serializable():
    import json

    cls = classifica_modelli({"claude-opus-4-5": 20}, TIERS)
    for esito in (
        valuta_r2(stats(frontier_valide=20, frontier_banali=20, ultimo_frontier_banale=ORA),
                  classificazione=cls, config=CONF),
        valuta_r4(stats(frontier_valide=20, frontier_pesanti=20,
                        somma_effective_frontier=10 ** 6, ultimo_frontier_pesante=ORA),
                  classificazione=cls, config=CONF),
    ):
        assert json.loads(json.dumps(esito.evidenza)) == esito.evidenza
