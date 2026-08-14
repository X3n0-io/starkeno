"""Task 7 — `db.py`: caricamento e aggregazione per il Supervisore.

Due proprieta' di questo modulo non sono verificabili altrove, e sono entrambe silenziose.

**`effective_tokens` ora vive in DUE posti.** In Python dentro `rules.py`, perche' le
regole devono restare pure e testabili; in SQL dentro `db.py`, perche' aggregare una
finestra da 24h caricando le righe non e' praticabile — misurato su 86.400 righe: ORM
1,17 s, tuple grezze 0,15 s, `SUM` in SQL 0,048 s. Due definizioni della stessa formula
divergono al primo cambio di pesi, e nessun test che ne guardi una sola se ne accorge.
Il test differenziale e' l'unica cosa che le tiene insieme.

**La baseline di R3 dev'essere deterministica ed escludere il candidato NELLA QUERY.**
Fatta nel chiamante, un test su liste scritte a mano la verificherebbe banalmente senza
dire niente sul codice vero.
"""
import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from starkeno.config import TOKEN_COST_WEIGHTS
from starkeno.db import (
    AgentAction,
    espressione_effective_sql,
    get_actions_since,
    get_active_projects,
    get_distinct_models,
    get_live_alert,
    get_open_alerts,
    get_spend_baseline,
    get_window_stats,
    record_action,
    resolve_alert,
    set_rule_status,
    upsert_alert,
    write_heartbeat,
)
from starkeno.rules import effective_tokens

ORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
TETTO = 2_000_000


def scrivi(session, *, agente="a", azione="read:x.py", modello="claude-opus-4-5",
           token=1000, cr=None, cw=None, ou=None, quando=None):
    riga = AgentAction(
        project=agente, action=azione, model_used=modello, tokens_used=token,
        cache_read_tokens=cr, cache_write_tokens=cw, output_tokens=ou,
        timestamp=quando or ORA,
    )
    session.add(riga)
    session.commit()
    return riga


# ==================================================== il test che tiene insieme le due
def test_the_sql_and_python_definitions_of_effective_tokens_agree(session):
    """**Il test piu' importante di questo modulo.**

    L'espressione CASE in SQL e `rules.effective_tokens` in Python devono dare lo stesso
    numero su ogni input, compresi quelli patologici. Senza, cambiare un peso in
    `TOKEN_COST_WEIGHTS` correggerebbe una delle due e non l'altra: R2 e R3/R4
    misurerebbero grandezze diverse credendo di misurare la stessa, e nessun errore
    verrebbe prodotto da nessuna parte.

    Gli input non sono casuali e basta: includono i cinque rami della tabella di
    decisione piu' NULL parziali, componenti negativi e somme che superano il totale.
    """
    random.seed(20260806)
    casi = [
        (9000, None, None, None),                    # nessuna dichiarazione
        (13000, 0, 0, 8000),                         # dichiarazione completa e valida
        (9000, None, None, 1200),                    # NULL parziale: la forma piu' comune
        (60000, 0, 0, -40000),                       # componente negativo
        (5000, 3000, 3000, 3000),                    # la somma supera il totale
        (20000, 0, 20000, 0),                        # cache write
        # Sopra il tetto di plausibilita' CON una scomposizione valida. E' l'unico input
        # che distingue "il tetto c'e'" da "il tetto non c'e'": senza il ramo, il SQL
        # applicherebbe la formula pesata e restituirebbe 7.000.000 invece di 3.000.000.
        # La prima versione di questo test non ne aveva nessuno sopra il tetto, e
        # rimuovere quel ramo non faceva fallire niente. Verificato mutando il codice.
        (3_000_000, 0, 0, 1_000_000),
        (2_000_001, 0, 0, 1),
        (5_000_000, None, None, None),
    ]
    for _ in range(1500):
        tu = random.choice([0, 1, 500, 9000, 60000, 1_999_999, 2_000_001, 4_000_000,
                            random.randint(0, 300_000), random.randint(0, 6_000_000)])
        def comp():
            return random.choice([None, 0, 1, 100, 5000, -40000, random.randint(0, 90_000)])
        casi.append((tu, comp(), comp(), comp()))

    for tu, cr, cw, ou in casi:
        session.add(AgentAction(project="diff", action="x", model_used="m",
                                tokens_used=tu, cache_read_tokens=cr,
                                cache_write_tokens=cw, output_tokens=ou, timestamp=ORA))
    session.commit()

    espressione = espressione_effective_sql(TOKEN_COST_WEIGHTS, TETTO)
    righe = session.execute(
        text("SELECT tokens_used, cache_read_tokens, cache_write_tokens, output_tokens, "
             "%s AS effective FROM agent_actions WHERE project='diff' ORDER BY id"
             % espressione)
    ).all()

    assert len(righe) == len(casi)
    divergenze = []
    for riga, (tu, cr, cw, ou) in zip(righe, casi):
        atteso, _ = effective_tokens(tu, cr, cw, ou, weights=TOKEN_COST_WEIGHTS,
                                     max_plausible=TETTO)
        if abs(float(riga.effective) - float(atteso)) > 1e-6:
            divergenze.append((tu, cr, cw, ou, atteso, riga.effective))

    assert not divergenze, "SQL e Python divergono su %d input, primi tre: %r" % (
        len(divergenze), divergenze[:3])


def test_the_differential_test_would_notice_a_changed_weight(session):
    """Il complemento: con pesi diversi i due risultati DEVONO differire.

    Senza questa verifica il test sopra potrebbe confrontare due costanti sempre uguali
    per un motivo che non c'entra con la formula.
    """
    scrivi(session, agente="peso", token=13000, cr=0, cw=0, ou=8000)
    doppi = {k: v * 2 for k, v in TOKEN_COST_WEIGHTS.items()}

    normale = session.execute(text(
        "SELECT %s FROM agent_actions WHERE project='peso'"
        % espressione_effective_sql(TOKEN_COST_WEIGHTS, TETTO))).scalar()
    raddoppiato = session.execute(text(
        "SELECT %s FROM agent_actions WHERE project='peso'"
        % espressione_effective_sql(doppi, TETTO))).scalar()

    assert raddoppiato == normale * 2


# ============================================================== baseline di R3
def test_the_r3_baseline_excludes_the_candidate_and_is_deterministic(session):
    """201 azioni, molte nello stesso secondo, con la baseline limitata a 200.

    Le collisioni di timestamp sono il caso NORMALE per un agente in loop, cioe'
    esattamente il caso interessante. L'ordinamento e' su `id` perche' e' garantito da
    una chiave unica; su `timestamp` sarebbe stabile solo per come SQLite ordina oggi.
    """
    for i in range(201):
        quando = ORA if i < 40 else ORA + timedelta(seconds=i)
        scrivi(session, agente="base", token=1000 + i, quando=quando)

    candidato = session.query(AgentAction).order_by(AgentAction.id.desc()).first()

    letture = [
        tuple(get_spend_baseline(session, "base", before_id=candidato.id, limit=200,
                                 weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO))
        for _ in range(8)
    ]

    assert len(letture[0]) == 200
    assert len(set(letture)) == 1, "la baseline non e' deterministica su chiamate ripetute"
    assert float(candidato.tokens_used) not in letture[0], "il candidato e' nella propria baseline"


def test_the_r3_baseline_drops_non_positive_and_implausible_rows(session):
    """Il filtro e' su `effective_tokens`, non su `tokens_used`: e' la grandezza confrontata."""
    scrivi(session, agente="filtro", token=5000)
    scrivi(session, agente="filtro", token=0)                       # non positiva
    scrivi(session, agente="filtro", token=TETTO + 1)               # implausibile
    scrivi(session, agente="filtro", token=7000)
    ultimo = scrivi(session, agente="filtro", token=9000)

    baseline = get_spend_baseline(session, "filtro", before_id=ultimo.id, limit=200,
                                  weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO)

    assert sorted(baseline) == [5000.0, 7000.0]


# ============================================================== aggregati di finestra
def test_window_stats_counts_only_the_frontier_models_it_was_given(session):
    for _ in range(3):
        scrivi(session, agente="w", modello="claude-opus-4-5", token=500)
    for _ in range(2):
        scrivi(session, agente="w", modello="claude-haiku-4-5", token=500)

    stats = get_window_stats(session, "w", since=ORA - timedelta(hours=1),
                             frontier_raw_names=["claude-opus-4-5"],
                             weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO,
                             soglia_banale=1000, soglia_pesante=25_000)

    assert stats.righe_totali == 5
    assert stats.frontier_valide == 3
    assert stats.frontier_banali == 3


def test_window_stats_thresholds_are_parameters_not_read_from_config(session):
    """Se le soglie di VALORE non arrivassero fin dentro il SQL, l'iniezione della
    configurazione si fermerebbe a meta' strada e nessun test lo direbbe."""
    for token in (500, 5_000, 50_000):
        scrivi(session, agente="soglie", token=token)

    stretta = get_window_stats(session, "soglie", since=ORA - timedelta(hours=1),
                               frontier_raw_names=["claude-opus-4-5"],
                               weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO,
                               soglia_banale=1000, soglia_pesante=25_000)
    # soglia_pesante=400 e non 1000: le righe sono 500 / 5.000 / 50.000, e con 1.000 la
    # prima non qualificherebbe. Con 400 qualificano tutte e tre, e il contrasto con la
    # configurazione stretta e' netto su entrambi i conteggi.
    larga = get_window_stats(session, "soglie", since=ORA - timedelta(hours=1),
                             frontier_raw_names=["claude-opus-4-5"],
                             weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO,
                             soglia_banale=10_000, soglia_pesante=400)

    assert (stretta.frontier_banali, stretta.frontier_pesanti) == (1, 1)
    assert (larga.frontier_banali, larga.frontier_pesanti) == (2, 3)


def test_window_stats_separates_unusable_rows_from_valid_ones(session):
    scrivi(session, agente="z", token=5_000)
    scrivi(session, agente="z", token=0)
    scrivi(session, agente="z", token=TETTO + 1)

    stats = get_window_stats(session, "z", since=ORA - timedelta(hours=1),
                             frontier_raw_names=["claude-opus-4-5"],
                             weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO,
                             soglia_banale=1000, soglia_pesante=25_000)

    assert stats.frontier_valide == 1
    assert stats.frontier_scartate_zero == 1
    assert stats.flag_qualita.get("token_implausibili") == 1


def test_window_stats_sums_the_weighted_value_not_the_raw_one(session):
    scrivi(session, agente="s", token=13_000, cr=0, cw=0, ou=8_000)   # -> 45.000 pesati

    stats = get_window_stats(session, "s", since=ORA - timedelta(hours=1),
                             frontier_raw_names=["claude-opus-4-5"],
                             weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO,
                             soglia_banale=1000, soglia_pesante=25_000)

    assert stats.somma_effective_frontier == 45_000
    assert stats.frontier_pesanti == 1, "la soglia pesante e' stata applicata ai token grezzi"


def test_window_stats_records_the_timestamps_the_lifecycle_needs(session):
    vecchia = scrivi(session, agente="t", token=500, quando=ORA - timedelta(minutes=30))
    recente = scrivi(session, agente="t", token=500, quando=ORA - timedelta(minutes=5))

    stats = get_window_stats(session, "t", since=ORA - timedelta(hours=1),
                             frontier_raw_names=["claude-opus-4-5"],
                             weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO,
                             soglia_banale=1000, soglia_pesante=25_000)

    assert stats.ultimo_frontier == recente.timestamp
    assert stats.ultimo_frontier_banale == recente.timestamp
    assert stats.ultimo_frontier != vecchia.timestamp


def test_the_window_filter_actually_filters(session):
    """**Il difetto silenzioso piu' facile da introdurre in questo modulo.**

    SQLite confronta le date come stringhe. Il formato scritto da `UTCDateTime` e'
    `2026-08-06 10:00:00.000000`, con uno SPAZIO. Passare `since.isoformat()` — che e'
    la correzione ovvia al DeprecationWarning di Python 3.12 sul passaggio di oggetti
    datetime — mette una `T`, che in ASCII sta dopo lo spazio: **nessun confronto matcha
    mai e la finestra restituisce zero righe, senza alcun errore.**

    Per il supervisore sarebbe "nessuna violazione" su ogni agente, per sempre,
    indistinguibile da una flotta sana.

    Questo test fissa entrambi i lati: le righe dentro la finestra si contano, quelle
    fuori no. Con `isoformat()` fallisce il primo; senza filtro, il secondo.
    """
    scrivi(session, agente="fin", token=5000, quando=ORA - timedelta(minutes=10))
    scrivi(session, agente="fin", token=5000, quando=ORA - timedelta(minutes=20))
    scrivi(session, agente="fin", token=5000, quando=ORA - timedelta(hours=5))

    stats = get_window_stats(session, "fin", since=ORA - timedelta(hours=1),
                             frontier_raw_names=["claude-opus-4-5"],
                             weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO,
                             soglia_banale=1000, soglia_pesante=25_000)

    assert stats.righe_totali == 2, "il filtro sulla finestra non funziona"
    assert stats.frontier_valide == 2


def test_no_deprecated_datetime_binding_is_used(session):
    """Il warning di Python 3.12 diventera' un errore. Meglio non averlo affatto."""
    import warnings

    with warnings.catch_warnings(record=True) as catturati:
        warnings.simplefilter("always")
        get_window_stats(session, "qualsiasi", since=ORA - timedelta(hours=1),
                         frontier_raw_names=["claude-opus-4-5"],
                         weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO,
                         soglia_banale=1000, soglia_pesante=25_000)

    deprecati = [str(c.message) for c in catturati if "deprecated" in str(c.message).lower()]
    assert not deprecati, "binding deprecato di datetime: %r" % deprecati


def test_window_stats_on_an_empty_window_does_not_explode(session):
    """`SUM` su un insieme vuoto restituisce NULL, non 0: senza coalesce si propaga un None."""
    stats = get_window_stats(session, "nessuno", since=ORA - timedelta(hours=1),
                             frontier_raw_names=["claude-opus-4-5"],
                             weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO,
                             soglia_banale=1000, soglia_pesante=25_000)

    assert stats.righe_totali == 0
    assert stats.somma_effective_frontier == 0
    assert stats.ultimo_frontier is None


def test_window_stats_with_no_frontier_names_returns_zeroes_not_everything(session):
    """Una lista vuota di modelli frontier non deve diventare "nessun filtro"."""
    scrivi(session, agente="v", token=5000)

    stats = get_window_stats(session, "v", since=ORA - timedelta(hours=1),
                             frontier_raw_names=[], weights=TOKEN_COST_WEIGHTS,
                             max_plausible=TETTO, soglia_banale=1000, soglia_pesante=25_000)

    assert stats.righe_totali == 1
    assert stats.frontier_valide == 0


# ========================================================== caricamento dei record
def test_loaded_records_carry_aware_timestamps_and_effective_tokens(session):
    scrivi(session, agente="r", token=13_000, cr=0, cw=0, ou=8_000)

    record = get_actions_since(session, "r", since=ORA - timedelta(hours=1),
                               weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO)

    assert len(record) == 1
    assert record[0].timestamp.tzinfo is not None
    assert (datetime.now(timezone.utc) - record[0].timestamp).total_seconds() != 0
    assert record[0].effective == 45_000


def test_actions_are_returned_in_ascending_id_order(session):
    for i in range(5):
        scrivi(session, agente="ord", token=100 + i, quando=ORA)  # timestamp identici

    record = get_actions_since(session, "ord", since=ORA - timedelta(hours=1),
                               weights=TOKEN_COST_WEIGHTS, max_plausible=TETTO)
    ids = [r.id for r in record]

    assert ids == sorted(ids)


def test_active_agents_are_those_seen_in_the_window(session):
    scrivi(session, agente="vivo", quando=ORA - timedelta(hours=1))
    scrivi(session, agente="spento", quando=ORA - timedelta(days=10))

    attivi = get_active_projects(session, since=ORA - timedelta(hours=48))

    assert attivi == ["vivo"]


def test_distinct_models_are_returned_with_their_counts(session):
    for _ in range(3):
        scrivi(session, agente="m", modello="claude-opus-4-5")
    scrivi(session, agente="m", modello="gpt-5.2-turbo")

    modelli = get_distinct_models(session, "m", since=ORA - timedelta(hours=1))

    assert modelli == {"claude-opus-4-5": 3, "gpt-5.2-turbo": 1}


# ================================================================ scrittura alert
def test_upsert_creates_then_updates_instead_of_failing(session):
    """La seconda violazione e' il caso NORMALE, non un'eccezione.

    L'indice unico parziale impedisce due alert vivi per (agente, regola), quindi una
    INSERT ingenua solleverebbe IntegrityError ogni volta che il supervisore rivede una
    violazione gia' nota.
    """
    primo = upsert_alert(session, project="a", rule="loop", detail="ciclo x3",
                         evidence={"k": 1}, last_seen=ORA, now=ORA)
    secondo = upsert_alert(session, project="a", rule="loop", detail="ciclo x9",
                           evidence={"k": 2}, last_seen=ORA + timedelta(minutes=1), now=ORA)

    assert primo.id == secondo.id
    assert secondo.status == "candidate"
    assert secondo.observed_rounds == 2
    assert secondo.detail == "ciclo x9"
    assert session.query(type(primo)).count() == 1


def test_upsert_survives_a_concurrent_insert(session, monkeypatch):
    """Il ramo IntegrityError, forzato.

    Il rollback prima del ritentativo non e' un dettaglio: senza, SQLAlchemy solleva
    PendingRollbackError e il giro muore comunque — la rete di sicurezza farebbe
    esattamente il danno che deve impedire.
    """
    import starkeno.db as db

    originale = db.get_live_alert
    chiamate = {"n": 0}

    def finge_assenza(*args, **kwargs):
        """Simula il caso in cui un altro processo inserisce fra la SELECT e la INSERT."""
        chiamate["n"] += 1
        if chiamate["n"] == 1:
            return None
        return originale(*args, **kwargs)

    upsert_alert(session, project="b", rule="loop", detail="primo",
                 evidence={}, last_seen=ORA, now=ORA)

    monkeypatch.setattr(db, "get_live_alert", finge_assenza)
    risultato = upsert_alert(session, project="b", rule="loop", detail="secondo",
                             evidence={}, last_seen=ORA, now=ORA)

    assert risultato is not None
    assert risultato.detail == "secondo"
    assert session.query(db.Alert).filter_by(project="b").count() == 1


def test_get_live_alert_ignores_resolved_and_dismissed(session):
    vivo = upsert_alert(session, project="c", rule="loop", detail="x",
                        evidence={}, last_seen=ORA, now=ORA)
    resolve_alert(session, vivo, resolution="recovery", now=ORA)

    assert get_live_alert(session, "c", "loop") is None
    assert get_open_alerts(session, "c") == []


def test_rule_status_is_upserted_not_appended(session):
    from starkeno.db import RuleStatus

    set_rule_status(session, "d", "loop", state="ok", reason=None, now=ORA)
    set_rule_status(session, "d", "loop", state="error", reason="boom",
                    now=ORA + timedelta(minutes=1))

    righe = session.query(RuleStatus).filter_by(project="d", rule="loop").all()
    assert len(righe) == 1
    assert righe[0].state == "error"
    assert righe[0].reason == "boom"


def test_heartbeat_keeps_a_single_row(session):
    from starkeno.db import SupervisorState

    write_heartbeat(session, now=ORA, duration_ms=12, agents_evaluated=3, rules_failed=0,
                    last_error=None)
    write_heartbeat(session, now=ORA + timedelta(minutes=1), duration_ms=15,
                    agents_evaluated=4, rules_failed=1, last_error="regola rotta")

    righe = session.query(SupervisorState).all()
    assert len(righe) == 1
    assert righe[0].agents_evaluated == 4
    assert righe[0].consecutive_errors == 1
    assert righe[0].last_run_at.tzinfo is not None


def test_heartbeat_resets_the_error_streak_on_a_clean_round(session):
    from starkeno.db import SupervisorState

    write_heartbeat(session, now=ORA, duration_ms=1, agents_evaluated=1, rules_failed=0,
                    last_error="boom")
    write_heartbeat(session, now=ORA + timedelta(minutes=1), duration_ms=1,
                    agents_evaluated=1, rules_failed=0, last_error=None)

    assert session.query(SupervisorState).one().consecutive_errors == 0


# ============================================================ ordinamenti diversi
def test_dashboard_query_stays_chronological(session):
    """`get_recent_actions` resta ordinata per timestamp: e' la query della dashboard, e
    "recenti" per un umano significa cronologiche. R3 e R1-B usano una funzione diversa,
    con un consumatore diverso e un ordinamento diverso."""
    from starkeno.db import get_recent_actions

    vecchia = scrivi(session, agente="dash", azione="vecchia", quando=ORA - timedelta(hours=2))
    nuova = scrivi(session, agente="dash", azione="nuova", quando=ORA)

    azioni = get_recent_actions(session, "dash", limit=10)
    assert [a.action for a in azioni] == ["nuova", "vecchia"]
