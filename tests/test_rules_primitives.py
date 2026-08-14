"""Task 3 — le primitive pure di rules.py.

`rules.py` non tocca il database, non importa SQLAlchemy e non legge l'orologio: e'
l'unica parte del sistema verificabile senza infrastruttura, ed e' per questo che tutto
cio' che puo' starci ci sta.

Le soglie arrivano sempre come PARAMETRI, mai lette da `config`. Senza, una `rules.py`
che ignorasse del tutto la configurazione e usasse costanti scritte a mano passerebbe
tutti i test, e alzare una soglia dopo due settimane di dati veri non cambierebbe
niente — rendendo inutile il compito dichiarato della v1.
"""
import pytest

from starkeno.config import MODEL_TIERS
from starkeno.rules import (
    effective_tokens,
    fascia,
    normalizza_modello,
    parse_action,
    percentile_nearest_rank,
)

PESI = {"input": 1.0, "cache_read": 0.1, "cache_write": 1.25, "output": 5.0}
TETTO = 2_000_000
BARRA = chr(92)  # backslash


# =============================================================== purezza del modulo
def moduli_importati(modulo):
    """I nomi dei moduli importati da un file, letti dall'AST.

    Non dal testo: una ricerca testuale di "sqlalchemy" trova anche il commento che dice
    di non usarlo, e un test che fallisce sulla propria documentazione e' inservibile.
    """
    import ast

    with open(modulo.__file__, encoding="utf-8") as f:
        albero = ast.parse(f.read())

    nomi = set()
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Import):
            nomi.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nomi.add(nodo.module.split(".")[0])
            if nodo.module.startswith("starkeno"):
                nomi.add(nodo.module)
    return nomi


def test_rules_imports_neither_sqlalchemy_nor_the_database():
    """`db.py` resta l'unico modulo che parla con SQLAlchemy (invariante 5).

    Vale anche per rules.py e supervisor.py. Un import qui dentro non romperebbe niente
    subito: aprirebbe la porta a una query "solo per comodita'", e da li' la parte
    testabile senza infrastruttura smette di esserlo.
    """
    import starkeno.rules as modulo

    vietati = {"sqlalchemy", "starkeno.db"} & moduli_importati(modulo)

    assert not vietati, "rules.py importa %r" % sorted(vietati)


def test_rules_never_reads_the_clock():
    """`now` e' sempre un parametro, mai `datetime.now()`.

    Il divieto e' sulla CHIAMATA, non sull'import: `datetime` serve per le annotazioni e
    per l'aritmetica delle finestre, ed e' legittimo. Una prima versione di questo test
    vietava l'import e falliva appena `rules.py` ha avuto bisogno di `timedelta` — un
    divieto tarato sulla cosa sbagliata.

    Cio' che conta e' che una regola non legga l'orologio di sistema: altrimenti non
    sarebbe testabile facendo avanzare il tempo a mano, e il ciclo di vita degli alert si
    prova solo cosi'.
    """
    import ast

    import starkeno.rules as modulo

    with open(modulo.__file__, encoding="utf-8") as f:
        albero = ast.parse(f.read())

    orologio = []
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.Call):
            continue
        bersaglio = nodo.func
        if isinstance(bersaglio, ast.Attribute) and bersaglio.attr in {"now", "utcnow", "today", "time", "monotonic"}:
            orologio.append(ast.unparse(bersaglio))

    assert not orologio, "rules.py legge l'orologio: %r" % orologio


# ============================================================ normalizzazione modelli
# Gli ID sono quelli veri dei provider, non esempi da manuale: e' il punto in cui la
# revisione precedente si era ingannata due volte.
IDENTIFICATIVI_REALI = [
    ("us.anthropic.claude-opus-4-5-20251101-v1:0", "claude-opus-4-5", "Bedrock"),
    ("publishers/anthropic/models/claude-opus-4-5", "claude-opus-4-5", "Vertex"),
    ("anthropic/claude-sonnet-4-5", "claude-sonnet-4-5", "OpenRouter"),
    ("claude-opus-4-5-20251101", "claude-opus-4-5", "diretto, con data"),
    ("claude-haiku-4-5-20251001", "claude-haiku-4-5", "diretto, con data"),
    ("claude-opus-4-5", "claude-opus-4-5", "gia' normalizzato"),
    ("CLAUDE-OPUS-4-5", "claude-opus-4-5", "maiuscolo"),
]


@pytest.mark.parametrize("grezzo,atteso,provenienza", IDENTIFICATIVI_REALI)
def test_real_model_ids_normalize_to_the_expected_key(grezzo, atteso, provenienza):
    assert normalizza_modello(grezzo) == atteso, "fallisce su %s" % provenienza


def test_bedrock_id_keeps_neither_the_date_nor_the_version_suffix():
    """Il caso che la pipeline dello spec sbagliava, isolato.

    §4/R2 dichiara che `us.anthropic.claude-opus-4-5-20251101-v1:0` diventa
    `claude-opus-4-5-v1`. Eseguendo i suoi cinque passi alla lettera si ottiene invece
    `claude-opus-4-5-20251101-v1`: il passo che toglie la data cerca un suffisso FINALE,
    ma dopo la rimozione del `:0` la data non e' piu' in fondo — c'e' `-v1`.

    Il risultato sarebbe finito fra i "non mappati" e, oltre MAX_UNMAPPED_SHARE, R2 e R4
    si sarebbero astenute per sempre su ogni agente che usa Bedrock.
    """
    assert normalizza_modello("us.anthropic.claude-opus-4-5-20251101-v1:0") == "claude-opus-4-5"
    assert normalizza_modello("eu.anthropic.claude-sonnet-4-5-20250929-v1:0") == "claude-sonnet-4-5"


@pytest.mark.parametrize("grezzo", ["gpt-5.2-turbo", "gemini-2.5-pro", "mistral-7b-v0.3"])
def test_version_dots_in_non_anthropic_names_are_preserved(grezzo):
    """L'altro difetto della pipeline dello spec: il passo "dopo l'ULTIMO punto".

    Esiste solo per togliere il prefisso `us.anthropic.` di Bedrock, ma applicato senza
    guardia distrugge ogni nome che contiene un punto di VERSIONE:
    `gpt-5.2-turbo` -> `2-turbo`, `gemini-2.5-pro` -> `5-pro`, `mistral-7b-v0.3` -> `3`.
    Tutti irriconoscibili, quindi non mappati, quindi astensione permanente delle due
    sole regole che parlano di soldi.

    Qui il prefisso regionale si toglie con una guardia esplicita, e i punti restano.
    """
    assert normalizza_modello(grezzo) == grezzo


def test_every_model_tiers_key_is_already_normalized():
    """Una chiave non normalizzata non puo' MAI essere trovata.

    `fascia()` cerca la forma normalizzata dentro MODEL_TIERS: se una chiave del dict
    fosse scritta con la data o col prefisso del provider, quel modello risulterebbe
    "non mappato" per sempre — e non ci sarebbe alcun errore, solo un'astensione
    inspiegabile su un modello che qualcuno era certo di aver configurato.
    """
    non_normalizzate = {k: normalizza_modello(k) for k in MODEL_TIERS if normalizza_modello(k) != k}
    assert not non_normalizzate, "chiavi irraggiungibili in MODEL_TIERS: %r" % non_normalizzate


# ---------------------------------------------------------------------------- fasce
def test_unmapped_model_is_never_frontier():
    """Sconosciuto significa nessuna prova, non colpevole.

    Un modello non mappato viene escluso da numeratore E denominatore di R2/R4: non e'
    frontier, e non abbassa nemmeno la share facendo tacere la regola per caso.
    """
    assert fascia("gpt-5.2-turbo", MODEL_TIERS) is None
    assert fascia("un-modello-mai-visto", MODEL_TIERS) is None


def test_fascia_resolves_real_ids_through_normalization():
    assert fascia("us.anthropic.claude-opus-4-5-20251101-v1:0", MODEL_TIERS) == "frontier"
    assert fascia("anthropic/claude-sonnet-4-5", MODEL_TIERS) == "standard"
    assert fascia("claude-haiku-4-5-20251001", MODEL_TIERS) == "economy"


def test_fascia_uses_the_injected_mapping_not_the_global_one():
    """La mappa arriva come parametro: e' cio' che rende tarabile MODEL_TIERS."""
    finto = {"claude-opus-4-5": "economy"}
    assert fascia("claude-opus-4-5", finto) == "economy"
    assert fascia("claude-sonnet-4-5", finto) is None


# ================================================================= parsing di `action`
def test_action_with_a_detail_splits_on_the_first_colon():
    assert parse_action("read_file:src/app.py") == ("read_file", "src/app.py")
    assert parse_action("fetch:https://x.dev/a:b") == ("fetch", "https://x.dev/a:b")


def test_empty_detail_means_absent_not_identical():
    """`plan:` / `act:` / `observe:` sono categorie NUDE, non dettagli vuoti uguali fra loro.

    Un agente che costruisce le etichette come f"{step}:{target}" con `target` vuoto
    emetterebbe dettagli tutti identici (tutti "") e finirebbe nel ramo piu' sensibile
    del rilevatore di cicli sui dati MENO informativi: un agente sano a tre fasi
    accusato di loop.
    """
    for grezzo in ("plan:", "act:", "observe:", "step:   "):
        categoria, dettaglio = parse_action(grezzo)
        assert dettaglio is None, "%r ha prodotto un dettaglio" % grezzo
        assert categoria == grezzo


def test_a_windows_path_is_a_bare_category_not_category_C():
    """L'immagine speculare del caso precedente.

    Senza la guardia sui separatori di percorso, ogni azione di un agente su Windows
    collassa sulla categoria `C` con dettagli tutti distinti, e R1 si spegne del tutto
    senza che niente lo dica.
    """
    percorso = "C:" + BARRA + "Users" + BARRA + "esempio" + BARRA + "src" + BARRA + "app.py"
    assert parse_action(percorso) == (percorso, None)
    assert parse_action("/usr/local:bin") == ("/usr/local:bin", None)


def test_query_string_and_fragment_are_stripped():
    """Il rumore variabile va dopo un `?`, dov'e' rimosso: e' il contratto col chiamante."""
    assert parse_action("read_file:app.py?line=12")[1] == "app.py"
    assert parse_action("read_file:app.py?line=47")[1] == "app.py"
    assert parse_action("search:query#frammento")[1] == "query"


def test_digits_are_never_normalized_away():
    """**La decisione piu' importante del parsing, e va nella direzione opposta all'istinto.**

    Una versione precedente normalizzava anche cifre, timestamp e UUID. Sembrava piu'
    robusta ed era attivamente dannosa: un batch sano `fetch/validate/save:user_1..100`
    collassava su `user_N`, i dettagli risultavano identici, e il rilevatore scattava
    con la soglia piu' bassa su un ciclo ripetuto cento volte.

    Il batch non rivisita mai lo stesso oggetto, il loop rivisita sempre lo stesso: e'
    esattamente la distinzione che le cifre portano e che azzerarle cancella.
    """
    dettagli = {parse_action("fetch:user_%d" % i)[1] for i in range(1, 101)}
    assert len(dettagli) == 100, "le cifre sono state normalizzate: i batch sani diventano loop"


def test_detail_normalization_makes_the_same_object_look_the_same():
    """Il complemento del test precedente: separatori e maiuscole SI' normalizzano."""
    a = parse_action("read:src" + BARRA + "App.py")[1]
    b = parse_action("read:src/app.py")[1]
    assert a == b == "src/app.py"


# ============================================================== effective_tokens
def eff(tu, cr, cw, ou):
    return effective_tokens(tu, cr, cw, ou, weights=PESI, max_plausible=TETTO)


def test_all_components_null_means_full_cost():
    """Ramo 1: nessuna dichiarazione. Il totale vale per intero, senza segnalazioni."""
    assert eff(9000, None, None, None) == (9000, None)


def test_complete_declaration_uses_the_weighted_formula():
    """Ramo 2, con l'esempio numerico dichiarato: 5k input + 8k output valgono ~45k."""
    valore, flag = eff(13000, 0, 0, 8000)
    assert valore == 45000, "l'output non e' pesato: 13k invece di 45k"
    assert flag is None


def test_cache_write_costs_more_than_plain_input_not_less():
    """L'errore da non fare e' mettere i cache WRITE insieme ai read.

    Costano piu' dell'input normale (1.25x), non meno (0.1x), e confonderli sottostima
    la spesa di oltre dieci volte — cieca proprio sul caso caro.
    """
    scrittura, _ = eff(20000, 0, 20000, 0)
    ingresso, _ = eff(20000, 0, 0, 0)
    assert scrittura > ingresso
    assert (scrittura, ingresso) == (25000, 20000)


def test_partial_declaration_falls_back_to_the_total_with_a_flag():
    """Ramo 3, ed e' la forma PIU' COMUNE che il sistema vedra'.

    Nell'SDK i campi cache sono Optional e valgono None su ogni chiamata che non tocca
    la cache, mentre output_tokens e' sempre un int: lo snippet del contratto la produce
    a ogni chiamata non cachata. Senza questo ramo, `9000 - None` solleva TypeError,
    l'eccezione viene inghiottita, e R3 e R4 restano spente per sempre.
    """
    assert eff(9000, None, None, 1200) == (9000, "componenti_parziali")
    assert eff(9000, 500, None, 1200) == (9000, "componenti_parziali")


def test_a_negative_component_cannot_hide_a_row_from_the_rule_that_hunts_it():
    """Ramo 4, ed e' il piu' insidioso perche' e' silenzioso.

    Un chiamante con un bug di segno logga tokens_used=60000, output_tokens=-40000.
    Applicando la formula: input = 60000-(-40000) = 100000, effective =
    100000 - 200000 = -100.000. Che e' SOTTO la soglia di R4 invece che sopra: la riga
    sparisce esattamente dalla regola che esiste per catturarla.
    """
    valore, flag = eff(60000, 0, 0, -40000)
    assert valore == 60000, "la formula e' stata applicata a un componente negativo"
    assert flag == "componente_negativo"
    assert valore > 0


def test_components_summing_above_the_total_fall_back():
    """Ramo 5: la scomposizione contraddice il totale, quindi non e' utilizzabile."""
    assert eff(5000, 3000, 3000, 3000) == (5000, "somma_supera_totale")


def test_the_plausibility_ceiling_applies_to_the_raw_total_not_the_weighted_value():
    """Ramo 6, e la grandezza a cui si applica NON e' quella che dice §3.2.

    La giustificazione del tetto e' fisica: una singola chiamata non puo' superare ~2M
    token. Ma `effective_tokens` e' PESATO e puo' legittimamente arrivare a 5x il grezzo,
    perche' l'output pesa 5.0. Una chiamata valida da 2M token con meta' output da un
    effective di 6.000.000: col tetto sul valore pesato verrebbe scartata come dato
    corrotto proprio la chiamata piu' cara della giornata.
    """
    valore, flag = eff(2_000_000, 0, 0, 1_000_000)
    assert flag is None, "una chiamata grande ma plausibile e' stata segnalata come corrotta"
    assert valore == 6_000_000

    _, flag_oltre = eff(2_000_001, None, None, None)
    assert flag_oltre == "token_implausibili"


def test_weights_are_injected_not_read_from_config():
    """Senza questo, `rules.py` potrebbe ignorare i pesi e nessun test lo direbbe."""
    doppi = {"input": 2.0, "cache_read": 0.2, "cache_write": 2.5, "output": 10.0}
    normale, _ = eff(13000, 0, 0, 8000)
    raddoppiato, _ = effective_tokens(13000, 0, 0, 8000, weights=doppi, max_plausible=TETTO)
    assert raddoppiato == normale * 2


# ==================================================================== percentile
def test_percentile_method_is_nearest_rank():
    """Il metodo e' PINNATO, e la scelta non e' neutra.

    "Il 95esimo percentile" non e' una definizione: nearest-rank e interpolazione lineare
    danno numeri diversi, e misurati sulla dimensione minima della baseline
    (SPEND_MIN_HISTORY=30) divergono del 44%. Due implementatori costruirebbero due
    sistemi con soglie diverse credendo di aver scritto la stessa cosa.

    Nearest-rank: il piu' piccolo valore osservato tale che almeno il 95% della baseline
    gli stia sotto o pari. Niente interpolazione, niente numeri che non esistono nei dati.
    """
    valori = list(range(1, 101))  # 1..100
    assert percentile_nearest_rank(valori, 0.95) == 95
    assert percentile_nearest_rank(valori, 0.50) == 50

    # con 20 elementi: ceil(0.95*20) = 19 -> il 19esimo in ordine crescente
    assert percentile_nearest_rank(list(range(1, 21)), 0.95) == 19


def test_percentile_does_not_require_a_sorted_input():
    assert percentile_nearest_rank([50, 10, 90, 30, 70], 0.95) == 90


def test_percentile_of_a_single_value():
    assert percentile_nearest_rank([42], 0.95) == 42


def test_percentile_is_deterministic_on_repeated_calls():
    """Una regola che alternasse VIOLAZIONE e OK sugli stessi dati sarebbe peggio di niente."""
    valori = [7, 3, 9, 1, 5, 5, 5, 100, 2]
    risultati = {percentile_nearest_rank(list(valori), 0.95) for _ in range(20)}
    assert len(risultati) == 1
