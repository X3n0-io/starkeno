"""Task 1 — lo schema della v1: colonne dei token e tabelle del Supervisore.

I test qui dentro passano tutti da **SQLite vero**, mai da liste costruite a mano.
Non e' pedanteria: i difetti che questo schema puo' avere sono per costruzione
invisibili a un test in memoria, perche' nascono nel round-trip col database.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from starkeno import db
from starkeno.db import Alert, AgentWatermark, AgentAction, RuleStatus, SupervisorState


def _alert(**override):
    adesso = datetime.now(timezone.utc)
    valori = dict(
        project="scraper",
        rule="loop",
        status="candidate",
        detail="read:app.py ripetuta 12 volte",
        evidence="{}",
        episodes=1,
        observed_rounds=1,
        first_seen=adesso,
        last_seen=adesso,
    )
    valori.update(override)
    return Alert(**valori)


# ------------------------------------------------------------------- il fuso orario
def test_alert_datetimes_roundtrip_as_aware_utc(session):
    """**Il test che nessuna lista scritta a mano puo' dare.**

    Il blocco di codice di §3.3 dello spec dichiara `Column(DateTime)` nudo. Misurato:
    quelle colonne tornano da SQLite con `tzinfo=None`, e la sottrazione da un `now`
    aware solleva `TypeError`.

    Dove fa male: `now - first_seen >= PROMOTE_MIN_MINUTES` e' la condizione di
    promozione, girerebbe a OGNI giro per OGNI alert, l'eccezione verrebbe inghiottita
    dal try/except per-regola (§7), e **nessun candidate diventerebbe mai open**. Zero
    alert aperti per sempre, che sullo schermo e' identico a una flotta sana.

    La v0 ha gia' il TypeDecorator che risolve il problema: le tabelle nuove devono
    usarlo, non ricominciare da capo.
    """
    session.add(_alert())
    session.commit()
    session.expire_all()  # forza la rilettura dal database, non dalla cache di sessione

    alert = session.query(Alert).one()
    adesso = datetime.now(timezone.utc)

    assert alert.first_seen.tzinfo is not None, "first_seen riletto naive: promozione rotta"
    assert alert.last_seen.tzinfo is not None, "last_seen riletto naive: risoluzione rotta"

    # e' letteralmente l'aritmetica della riconciliazione, a ogni giro
    assert (adesso - alert.first_seen) < timedelta(minutes=15)


def test_supervisor_state_and_rule_status_datetimes_are_aware(session):
    """Lo stesso vale per le altre due tabelle: il confronto dell'heartbeat e' un delta."""
    adesso = datetime.now(timezone.utc)
    session.add(SupervisorState(id=1, last_run_at=adesso, last_run_ms=12,
                                agents_evaluated=3, rules_failed=0, consecutive_errors=0))
    session.add(RuleStatus(project="scraper", rule="loop", state="ok", updated_at=adesso))
    session.commit()
    session.expire_all()

    stato = session.query(SupervisorState).one()
    regola = session.query(RuleStatus).one()

    # "Supervisore: ultimo giro N minuti fa", la riga di stato della dashboard
    assert (datetime.now(timezone.utc) - stato.last_run_at) < timedelta(minutes=1)
    assert (datetime.now(timezone.utc) - regola.updated_at) < timedelta(minutes=1)


def test_nullable_datetimes_survive_the_roundtrip(session):
    """`resolved_at` e `muted_until` sono nulli su ogni alert non risolto.

    E' il caso NORMALE, non un caso limite: dal primo minuto di vita della v1 ogni
    alert aperto ha entrambi a NULL. Il TypeDecorator deve lasciarli passare.
    """
    session.add(_alert())
    session.commit()
    session.expire_all()

    alert = session.query(Alert).one()
    assert alert.resolved_at is None
    assert alert.muted_until is None
    assert alert.resolution is None
    assert alert.user_note is None


# --------------------------------------------------------- un solo alert vivo per coppia
def test_only_one_live_alert_per_agent_and_rule(session):
    """L'indice unico parziale impedisce due alert vivi sulla stessa coppia.

    E' cio' che obbliga la scrittura a essere un upsert invece di una INSERT: senza,
    il supervisore aprirebbe un alert nuovo a ogni giro sulla stessa violazione.
    """
    session.add(_alert())
    session.commit()

    session.add(_alert())
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_a_candidate_and_an_open_alert_cannot_coexist(session):
    """L'indice copre `candidate` E `open`: sono due facce dello stesso alert vivo."""
    session.add(_alert(status="candidate"))
    session.commit()

    session.add(_alert(status="open"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_dismissed_and_resolved_alerts_coexist_with_a_live_one(session):
    """`dismissed` resta FUORI dall'indice, di proposito.

    Un falso positivo ignorato dall'utente deve poter convivere con un alert futuro
    sulla stessa coppia: altrimenti il dismiss occuperebbe l'unico posto vivo e la
    violazione successiva non avrebbe dove nascere.
    """
    session.add(_alert(status="dismissed", user_note="eval-runner: 25 chiamate piccole per progetto"))
    session.add(_alert(status="resolved", resolution="recovery",
                       resolved_at=datetime.now(timezone.utc)))
    session.commit()

    session.add(_alert(status="candidate"))
    session.commit()  # non deve sollevare

    assert session.query(Alert).count() == 3


def test_the_same_agent_can_violate_two_different_rules(session):
    """Un incidente vero fa scattare piu' regole insieme (§3.7): non devono collidere."""
    session.add(_alert(rule="loop"))
    session.add(_alert(rule="steady_waste"))
    session.commit()

    assert session.query(Alert).count() == 2


def test_data_quality_is_a_valid_rule_value(session):
    """Il guard MAX_TRACKED_AGENTS apre un alert che non appartiene a nessuna delle 4 regole.

    Se `rule` fosse vincolata ai soli quattro nomi, quell'alert non sarebbe scrivibile
    e il caso "4.000 agenti finti, zero alert" resterebbe invisibile.
    """
    session.add(_alert(project="__sistema__", rule="data_quality",
                       detail="1.284 agenti distinti in 24h: probabile id di sessione in project"))
    session.commit()

    assert session.query(Alert).one().rule == "data_quality"


# --------------------------------------------------------------- colonne dei token
def test_new_token_columns_default_to_null_not_zero(session):
    """Un chiamante che non dichiara la scomposizione deve produrre NULL, non 0.

    La differenza non e' cosmetica: `tutti e tre NULL` significa "nessuna dichiarazione"
    e `effective_tokens` ricade sul costo pieno, mentre degli 0 verrebbero letti come
    una dichiarazione valida che azzera cache e output — sottostimando la spesa.
    """
    session.add(AgentAction(project="a", action="x", model_used="m", tokens_used=9000,
                            timestamp=datetime.now(timezone.utc)))
    session.commit()
    session.expire_all()

    azione = session.query(AgentAction).one()
    assert azione.cache_read_tokens is None
    assert azione.cache_write_tokens is None
    assert azione.output_tokens is None


def test_token_breakdown_roundtrips(session):
    session.add(AgentAction(project="a", action="x", model_used="m", tokens_used=13000,
                            cache_read_tokens=0, cache_write_tokens=0, output_tokens=8000,
                            timestamp=datetime.now(timezone.utc)))
    session.commit()
    session.expire_all()

    azione = session.query(AgentAction).one()
    assert (azione.cache_read_tokens, azione.cache_write_tokens, azione.output_tokens) == (0, 0, 8000)


# ------------------------------------------------------------------------ watermark
def test_watermark_is_per_agent(session):
    """R3 valuta tutte le azioni non ancora esaminate, e il segnaposto e' per agente.

    In `supervisor_state` non ci starebbe: quella tabella ha una riga sola.
    """
    session.add(AgentWatermark(project="scraper", last_evaluated_action_id=1200))
    session.add(AgentWatermark(project="writer", last_evaluated_action_id=48))
    session.commit()
    session.expire_all()

    per_agente = {w.project: w.last_evaluated_action_id for w in session.query(AgentWatermark)}
    assert per_agente == {"scraper": 1200, "writer": 48}


# ------------------------------------------------------ colonne dell'ingestione (0005)
def test_le_colonne_dell_ingestione_esistono_e_stanno_in_coda(session):
    """Le colonne nuove vanno IN CODA, o i due schemi divergono.

    `ADD COLUMN` accoda in fondo. Se il modello ORM le dichiarasse prima, `create_all`
    (che i test usano) produrrebbe un ordine diverso da quello che esiste in produzione,
    e ogni SELECT * posizionale restituirebbe campi diversi nei due ambienti.
    """
    colonne = [r[1] for r in session.execute(
        db.text("PRAGMA table_info(agent_actions)")).all()]
    attese_in_coda = ["session_id", "message_id", "azione_fallita", "esito_noto",
                      "azioni_nella_chiamata", "skill", "plugin", "mcp_server",
                      "is_sidechain"]
    assert colonne[-len(attese_in_coda):] == attese_in_coda


def test_una_chiamata_non_puo_essere_scritta_due_volte(session):
    """`(session_id, message_id)` e' la chiave di idempotenza: una riesecuzione
    dell'hook sullo stesso transcript deve essere un no-op, non un raddoppio."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    for _ in range(2):
        session.add(db.AgentAction(
            project="p", action="read:a.py", model_used="claude-opus-5",
            tokens_used=100, session_id="s1", message_id="msg_1",
            azione_fallita=0, esito_noto=1, azioni_nella_chiamata=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_la_sentinella_e_la_stringa_vuota_mai_null(session):
    """In SQLite due NULL sono DISTINTI: un indice unico che contiene NULL smette di
    vincolare in silenzio. Le colonne di questa chiave usano la stringa vuota."""
    colonne = {r[1]: r for r in session.execute(
        db.text("PRAGMA table_info(agent_actions)")).all()}
    for nome in ("session_id", "message_id"):
        assert colonne[nome][3] == 1, "%s deve essere NOT NULL" % nome
