"""Task 2 — le costanti controllate INSIEME, non una alla volta.

Sei relazioni fra costanti devono valere perche' il sistema funzioni. Nessuna di esse
e' visibile guardando una costante da sola, e romperne una non produce un errore:
produce un comportamento sbagliato in silenzio.

Non e' teorico. Nella versione precedente dello spec `PROMOTE_MIN_MINUTES` e
`LOOP_CYCLE_WINDOW_MINUTES` valevano entrambe 10 — margine ZERO, per coincidenza, e
nessuna riga lo diceva. Alzare la seconda, che e' esattamente cio' che si fara' quando
arriveranno dati veri da tarare, avrebbe distrutto la difesa anti-raffica dell'altra
senza un errore e senza un avviso.

Ogni test qui dentro rompe UN invariante e verifica che il controllo se ne accorga.
Senza, il controllo potrebbe essere vacuo e nessuno lo saprebbe.
"""
import subprocess
import sys

import pytest

from starkeno import config
from starkeno.config import InvariantError, check_invariants


def costanti(**override):
    """La configurazione reale, con qualche valore perturbato."""
    valori = {n: v for n, v in vars(config).items() if n.isupper()}
    valori.update(override)
    return valori


def test_the_shipped_constants_satisfy_every_invariant():
    check_invariants(costanti())  # non deve sollevare


# ------------------------------------------------------------------ i sei invarianti
def test_promotion_must_outlast_every_short_window():
    """I1 — margine +5.

    E' cio' che fa funzionare la difesa anti-raffica: una raffica deve uscire da OGNI
    finestra corta prima di poter essere promossa. Con `PROMOTE_MIN_MINUTES` sotto la
    finestra piu' lunga di R1, un burst che si auto-risolve verrebbe promosso a `open`
    prima di svanire — cioe' esattamente la classe di falsi positivi che la separazione
    fra percorso in linea e periodico esiste per uccidere.
    """
    with pytest.raises(InvariantError) as errore:
        check_invariants(costanti(PROMOTE_MIN_MINUTES=10))  # == LOOP_CYCLE_WINDOW_MINUTES

    assert "PROMOTE_MIN_MINUTES" in str(errore.value)
    assert "LOOP_CYCLE_WINDOW_MINUTES" in str(errore.value)


def test_the_sequence_must_be_long_enough_to_see_the_longest_cycle():
    """I2 — margine +9.

    Un ciclo di lunghezza `LOOP_CYCLE_MAX_LEN` ripetuto `K_MIXED_DETAIL` volte occupa
    `6 x 6 = 36` azioni. Con `LOOP_SEQUENCE_LEN` sotto quel prodotto il rilevatore B non
    puo' MAI osservare abbastanza ripetizioni di un ciclo lungo: la regola c'e', la
    soglia c'e', e non scatta mai. Verificato in revisione: con 30 un ciclo da 6 era
    irrilevabile.
    """
    with pytest.raises(InvariantError) as errore:
        check_invariants(costanti(LOOP_SEQUENCE_LEN=30))

    assert "LOOP_SEQUENCE_LEN" in str(errore.value)


def test_the_active_window_must_cover_every_rule_window():
    """I3 — margine +24.

    Il supervisore valuta solo gli agenti attivi nelle ultime
    `SUPERVISOR_ACTIVE_AGENT_HOURS`. Se quella finestra fosse piu' corta di quella di una
    regola, la regola guarderebbe dati che il supervisore non e' andato a prendere.
    §13 lo scrive a parole ("oltre max(finestre)") ma niente lo verificava.
    """
    with pytest.raises(InvariantError) as errore:
        check_invariants(costanti(SUPERVISOR_ACTIVE_AGENT_HOURS=12))

    assert "SUPERVISOR_ACTIVE_AGENT_HOURS" in str(errore.value)


def test_the_recovery_window_must_be_large_enough_to_show_a_violation():
    """I4 — **margine ZERO**. E' il piu' fragile dei sei.

    Un alert si chiude per recupero quando ci sono `RESOLVE_MIN_HEALTHY_ACTIONS` azioni
    dopo `last_seen` E la regola rivalutata su quella sola finestra ristretta dice OK.
    Ma se la finestra ristretta e' piu' piccola del numero di occorrenze che la regola
    richiede per violare, la rivalutazione dice OK **per costruzione**: l'alert si chiude
    da solo mentre il comportamento continua, e riapre al giro dopo. E' il lampeggio che
    il ciclo di vita esiste per impedire, spostato dal tempo al conteggio.

    R2 e' il caso peggiore: `EXPENSIVE_MIN_OCCURRENCES` vale 20 e
    `RESOLVE_MIN_HEALTHY_ACTIONS` vale 20. Uguali. Abbassare il secondo a 15 per
    "rendere il sistema piu' reattivo" e' una modifica ragionevole da fare e romperebbe
    R2 senza un errore.
    """
    with pytest.raises(InvariantError) as errore:
        check_invariants(costanti(RESOLVE_MIN_HEALTHY_ACTIONS=15))

    messaggio = str(errore.value)
    assert "RESOLVE_MIN_HEALTHY_ACTIONS" in messaggio
    assert "EXPENSIVE_MIN_OCCURRENCES" in messaggio, "il messaggio non nomina il vincolo attivo"


def test_the_recovery_window_invariant_also_covers_the_aggregate_branch_of_r4():
    """I4 copre anche `HEAVY_MIN_ACTIONS_FOR_SUM`, che e' una costante nuova.

    Senza, il ramo aggregato di R4 sarebbe l'unico a poter sfuggire al controllo.
    """
    with pytest.raises(InvariantError):
        check_invariants(costanti(HEAVY_MIN_ACTIONS_FOR_SUM=25, RESOLVE_MIN_HEALTHY_ACTIONS=20))


def test_stale_archiving_must_outlast_the_active_window():
    """I5 — margine +120.

    `RESOLVE_STALE_DAYS` (7 giorni) e' molto oltre `SUPERVISOR_ACTIVE_AGENT_HOURS` (48h):
    un agente fermo esce dall'insieme degli attivi PRIMA di poter essere archiviato. E'
    la ragione per cui l'insieme valutato include anche "gli agenti con un alert non
    risolto" — quella clausola non e' ornamentale, e questo invariante e' cio' che
    la rende necessaria. Se qualcuno la rimuovesse credendola ridondante, gli alert di
    un agente spento non si chiuderebbero mai.
    """
    with pytest.raises(InvariantError) as errore:
        check_invariants(costanti(RESOLVE_STALE_DAYS=1))

    assert "RESOLVE_STALE_DAYS" in str(errore.value)


def test_the_round_count_must_not_make_the_time_condition_dead():
    """I6 — margine -720 secondi.

    La promozione richiede ENTRAMBE le condizioni: tempo trascorso e giri osservati.
    Se `PROMOTE_MIN_ROUNDS x SUPERVISOR_INTERVAL_SECONDS` superasse
    `PROMOTE_MIN_MINUTES`, il conteggio dei giri sarebbe sempre l'ultimo a maturare e la
    condizione temporale diventerebbe morta: resterebbe scritta, non vincolerebbe piu'
    niente, e chi la taresse non otterrebbe alcun effetto.
    """
    with pytest.raises(InvariantError) as errore:
        check_invariants(costanti(SUPERVISOR_INTERVAL_SECONDS=600))  # 3 giri = 30 min > 15

    assert "PROMOTE_MIN_ROUNDS" in str(errore.value)


# ---------------------------------------------------------------- non sono `assert`
def test_the_invariants_are_enforced_even_under_python_dash_O():
    """`python -O` rimuove le istruzioni `assert`. Verificato eseguendolo.

    Un invariante a margine zero che sparisce sotto un flag dell'interprete e' la
    definizione del fallimento silenzioso che questo progetto continua a incontrare.
    Percio' il controllo solleva esplicitamente invece di usare `assert`.
    """
    codice = (
        "from starkeno import config\n"
        "from starkeno.config import check_invariants, InvariantError\n"
        "valori = {n: v for n, v in vars(config).items() if n.isupper()}\n"
        "valori['RESOLVE_MIN_HEALTHY_ACTIONS'] = 1\n"
        "try:\n"
        "    check_invariants(valori)\n"
        "    print('NESSUN ERRORE')\n"
        "except InvariantError:\n"
        "    print('SOLLEVATO')\n"
    )
    risultato = subprocess.run([sys.executable, "-O", "-c", codice],
                               capture_output=True, text=True)

    assert risultato.returncode == 0, risultato.stderr
    assert risultato.stdout.strip() == "SOLLEVATO", (
        "sotto -O il controllo non scatta: sono `assert`, e l'interprete li ha rimossi"
    )


def test_importing_config_runs_the_check():
    """Il controllo non basta che esista: dev'essere ESEGUITO all'import.

    Altrimenti sarebbe una funzione perfetta che non chiama nessuno.

    Il test esegue il sorgente vero di config.py con una costante perturbata, invece di
    cercare la stringa "check_invariants(" nel file. La prima versione faceva proprio
    quello ed era vacua: commentando la chiamata, il testo `# check_invariants(...)`
    contiene ancora la stringa cercata e il test passava. Un controllo testuale non
    distingue il codice da un commento; eseguirlo si'.
    """
    with open(config.__file__, encoding="utf-8") as f:
        sorgente = f.read()

    rotto = sorgente.replace("RESOLVE_MIN_HEALTHY_ACTIONS = 20", "RESOLVE_MIN_HEALTHY_ACTIONS = 1")
    assert rotto != sorgente, "la sostituzione non ha avuto effetto: il test sarebbe vacuo"

    # `__file__` va passato esplicitamente: `compile` imposta il nome del file nel codice,
    # non la variabile globale, e config.py la usa per calcolare DB_PATH.
    spazio = {"__name__": "config_perturbato", "__file__": config.__file__}

    # Si cattura RuntimeError, non InvariantError: eseguendo il sorgente si crea una
    # classe InvariantError NUOVA dentro `spazio`, che non e' la stessa importata qui e
    # che `pytest.raises(InvariantError)` non riconoscerebbe. La base comune si', e
    # l'asserzione sul messaggio impedisce che un RuntimeError qualsiasi faccia passare
    # il test per il motivo sbagliato.
    with pytest.raises(RuntimeError) as errore:
        exec(compile(rotto, config.__file__, "exec"), spazio)

    assert type(errore.value).__name__ == "InvariantError"
    assert "I4" in str(errore.value)


# --------------------------------------------------------------- costanti rimosse
def test_the_no_detail_thresholds_are_gone():
    """C8: senza dettaglio R1 si astiene, non alza la soglia.

    `LOOP_MIN_REPEATS_NO_DETAIL=40` non proteggeva nessuno: un indicizzatore sano a 3
    azioni/secondo supera 40 in 13 secondi. Nessun valore fisso separa "veloce e sano"
    da "bloccato" quando il dettaglio non c'e' — l'informazione non esiste nei dati.

    Il test e' qui e non fra i commenti perche' quelle due costanti sono esattamente il
    genere di cosa che qualcuno rimette "per completezza" leggendo lo spec.
    """
    valori = costanti()
    assert "LOOP_MIN_REPEATS_NO_DETAIL" not in valori
    assert "LOOP_CYCLE_K_NO_DETAIL" not in valori
    assert "LOOP_CYCLE_K_MIXED_DETAIL" in valori


def test_every_constant_carries_its_reasoning():
    """§13: ogni valore va accompagnato dal ragionamento e dal promemoria che non e' tarato.

    Le soglie di questo documento sono ragionate, non tarate: `agent_actions` e' quasi
    vuoto. Il primo compito reale della v1 e' raccogliere i dati per tararle, e un numero
    senza il suo perche' non e' tarabile da nessuno fra sei mesi.
    """
    with open(config.__file__, encoding="utf-8") as f:
        testo = f.read()

    assert "NON TARAT" in testo.upper(), "manca il promemoria che le soglie non sono tarate"
