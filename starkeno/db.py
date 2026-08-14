import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, event, Column, Integer, String, DateTime, Index, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.types import TypeDecorator

from starkeno.config import SQLITE_BUSY_TIMEOUT_SECONDS
from starkeno.conto import AzioneConto
from starkeno.rules import ActionRecord, WindowStats

Base = declarative_base()


class UTCDateTime(TypeDecorator):
    """Datetime sempre aware-UTC sopra questo modulo, sempre naive-UTC nel database.

    SQLite non conserva il fuso: un `datetime.now(timezone.utc)` scritto in una
    `Column(DateTime)` semplice torna indietro NAIVE. Sottrarlo da un datetime aware
    solleva `TypeError: can't subtract offset-naive and offset-aware datetimes`.

    Questo e' il difetto piu' pericoloso del progetto perche' e' silenzioso: il codice
    che confronta finestre temporali sta dentro un try/except (il logging non deve mai
    fallire), quindi l'eccezione viene inghiottita, non viene prodotto alcun risultato,
    e "nessun problema trovato" e' indistinguibile da "tutto funziona".

    La normalizzazione avviene qui, in un punto solo, al confine col database: sopra
    questo modulo nessuno deve piu' pensarci ne' chiamare `.replace(tzinfo=...)`.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            # Un chiamante che passa naive non deve far fallire la scrittura: viene
            # interpretato come UTC. Rifiutarlo violerebbe "il log non fallisce mai".
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True)
    project = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    model_used = Column(String, nullable=False)

    # Token TOTALI, cache read inclusi. E' la misura che usa R2 ("quanto e' grosso il
    # task?"): un contesto da 80k non e' banale nemmeno se arriva tutto dalla cache.
    tokens_used = Column(Integer, nullable=False)

    # Momento dell'INGESTIONE, non del lavoro: lo assegna db.py all'insert. Un chiamante
    # che bufferizza o fa backfill comprime ore di lavoro in pochi secondi, e le regole a
    # finestra corta lo vedono come una raffica.
    timestamp = Column(UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # ATTENZIONE ALL'ORDINE: queste tre vanno DOPO `timestamp`, non raggruppate con
    # `tokens_used` dove starebbero meglio a leggersi. Alembic le aggiunge con
    # ADD COLUMN, che accoda in fondo; se il modello le dichiarasse prima, `create_all`
    # (che i test usano) produrrebbe un ordine di colonne diverso da quello che esiste in
    # produzione, e ogni SELECT * posizionale restituirebbe campi diversi nei due
    # ambienti. Verificato: il test che confronta i due schemi lo prende.
    #
    # Scomposizione opzionale, ma O TUTTA O NIENTE: una dichiarazione parziale viene
    # trattata come nessuna dichiarazione. `nullable=True` senza default e' deliberato —
    # NULL significa "non dichiarato", 0 significherebbe "dichiarato pari a zero", e
    # confonderli sottostima la spesa. R3 e R4 misurano su `effective_tokens`, che pesa
    # questi componenti: i cache WRITE costano 1.25x l'input, non 0.1x, e l'output ~5x.
    cache_read_tokens = Column(Integer, nullable=True)
    cache_write_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)

    # ---- Colonne dell'ingestione dal transcript (migrazione 0005) ----
    # IN CODA per l'invariante 7: ADD COLUMN accoda, e i due schemi devono coincidere.
    #
    # Sentinella STRINGA VUOTA, mai NULL: in SQLite due NULL sono distinti, quindi
    # l'indice unico su (session_id, message_id) smetterebbe di vincolare in silenzio.
    session_id = Column(String, nullable=False, server_default="")
    message_id = Column(String, nullable=False, server_default="")

    # DUE colonne, non un booleano a tre stati. L'esito di uno strumento arriva nel
    # messaggio successivo: quando non c'e' ancora, `esito_noto` vale 0 e `azione_fallita`
    # NON va letta. Scriverla "falso" per "non lo so" renderebbe ottimisti per costruzione
    # sia R1 sia il costo degli errori.
    #
    # `text("0")` e NON la stringa "0": su una colonna intera `server_default="0"` emette
    # `DEFAULT '0'` — il numero zero scritto come TESTO — mentre la migrazione 0005 emette
    # `DEFAULT 0`. Misurato confrontando i due schemi colonna per colonna: e' esattamente
    # la divergenza silenziosa che l'invariante 7 vieta, e SQLite non se ne lamenta perche'
    # l'affinita' di tipo converte '0' in 0 all'insert.
    azione_fallita = Column(Integer, nullable=False, server_default=text("0"))
    esito_noto = Column(Integer, nullable=False, server_default=text("0"))

    # Il 10,3% delle chiamate contiene piu' di un'azione. Una riga per chiamata (la grana
    # della spesa) piu' questo contatore: righe multiple gonfierebbero del 10% ogni soglia
    # che conta azioni, senza che nessuno l'abbia deciso.
    azioni_nella_chiamata = Column(Integer, nullable=False, server_default=text("1"))

    # Attribuzione. Nessuna regola le interroga: sono il materiale del conto.
    skill = Column(String, nullable=False, server_default="")
    plugin = Column(String, nullable=False, server_default="")
    mcp_server = Column(String, nullable=False, server_default="")
    is_sidechain = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        # Serve le finestre temporali di R1/R2/R4. Misurato: la SUM di una finestra da
        # 24h su 86.400 righe passa da qui in 0,048 s, e l'indice elimina anche il
        # "USE TEMP B-TREE FOR ORDER BY" dalla query che la dashboard esegue gia'.
        #
        # NON serve un indice (project, id): `id INTEGER PRIMARY KEY` E' il rowid, e
        # SQLite lo accoda a ogni voce di indice non-unico, quindi
        # ix_agent_actions_project e' gia' di fatto (project, rowid) ordinato.
        # Misurato: "SEARCH ... USING INDEX ix_agent_actions_project (project=?
        # AND rowid<?)". Aggiungerlo costerebbe una scrittura di b-tree in piu' su OGNI
        # log_agent_action senza comprare niente.
        Index("ix_actions_project_time", "project", "timestamp"),
        # R1 legge la sequenza di UNA sessione, non del progetto: una sequenza
        # interlacciata da piu' esecuzioni parallele non e' di nessuno.
        Index("ix_actions_project_session_time", "project", "session_id", "timestamp"),
        # L'unico UNICO: e' cio' che rende l'hook rieseguibile senza duplicare.
        Index("ix_actions_chiamata", "session_id", "message_id", unique=True,
              sqlite_where=text("session_id != '' AND message_id != ''")),
    )


class Alert(Base):
    """Un EVENTO: qualcosa non va.

    Da distinguere da `RuleStatus`, che e' uno STATO. La differenza governa dove vive
    `NON_VALUTABILE`: se stesse qui occuperebbe l'unico posto vivo dell'indice unico
    parziale per quella coppia (agent, rule), cosi' che quando l'agente violasse davvero
    la riconciliazione aggiornerebbe la riga di astensione invece di aprire un alert vero.
    """

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)

    # Niente index=True: i due indici parziali sotto coprono entrambe le query, e
    # misurando il piano si vede che un indice pieno su project non viene mai scelto
    # ("SEARCH alerts USING COVERING INDEX ix_alerts_open" per la lookup in linea,
    # "USING INDEX ix_alerts_one_live" per get_live_alert).
    project = Column(String, nullable=False)

    # loop | expensive_model | spend_anomaly | steady_waste | data_quality
    # Il quinto non e' una regola: e' il guard MAX_TRACKED_AGENTS, che apre una singola
    # segnalazione leggibile quando un chiamante mette un id di sessione in project.
    rule = Column(String, nullable=False)

    # candidate | open | resolved | dismissed
    status = Column(String, nullable=False)

    detail = Column(String, nullable=False)
    evidence = Column(String, nullable=False)  # JSON, serializzato da un solo helper

    # Episodi DISTINTI, incrementato solo sulla transizione non-violazione -> violazione,
    # mai sul semplice permanere. Contando i giri, un episodio di loop da 9 minuti darebbe
    # 9 e uno di spreco darebbe 1440 (la finestra da 24h tiene viva la violazione per 1440
    # tick), facendo sembrare il secondo 160 volte piu' grave a parita' di gravita' reale.
    episodes = Column(Integer, nullable=False, server_default="1")

    # Giri effettivamente osservati: e' la meta' della doppia condizione di promozione che
    # regge quando il portatile si sospende.
    observed_rounds = Column(Integer, nullable=False, server_default="1")

    first_seen = Column(UTCDateTime, nullable=False)

    # Timestamp dell'AZIONE piu' recente che ha contribuito alla violazione, NON l'ora del
    # giro del supervisore. E' la definizione che fa funzionare la chiusura: quando il
    # comportamento cattivo cessa, last_seen smette di avanzare e la finestra pulita dopo
    # di esso puo' crescere. Col tempo del ciclo, un agente fermo sembrerebbe guarito.
    last_seen = Column(UTCDateTime, nullable=False)

    resolved_at = Column(UTCDateTime, nullable=True)
    resolution = Column(String, nullable=True)  # recovery | stale | dismissed
    muted_until = Column(UTCDateTime, nullable=True)
    user_note = Column(String, nullable=True)

    __table_args__ = (
        # Un solo alert VIVO per (agente, regola). E' cio' che obbliga la scrittura a
        # essere un upsert: una INSERT ingenua solleverebbe IntegrityError nel caso
        # normale, cioe' ogni volta che il supervisore rivede una violazione gia' nota.
        #
        # 'dismissed' resta fuori di proposito: un falso positivo ignorato dall'utente
        # deve poter convivere con un alert futuro sulla stessa coppia.
        Index("ix_alerts_one_live", "project", "rule",
              unique=True, sqlite_where=text("status IN ('candidate','open')")),

        # Serve la lookup in linea di log_agent_action, l'unica query sul percorso
        # critico. Misurato: COVERING INDEX, non tocca mai la tabella.
        #
        # Solo 'open', mai 'candidate': includendo i candidate, una raffica che si
        # risolve da sola (429 + retry, poi successo) avviserebbe l'agente fino a
        # PROMOTE_MIN_MINUTES prima di svanire, reintroducendo la classe di falsi
        # positivi che la separazione in linea/periodico esiste per uccidere.
        Index("ix_alerts_open", "project", sqlite_where=text("status = 'open'")),
    )


class RuleStatus(Base):
    """Uno STATO: come sta andando la valutazione. Riscritto a ogni giro.

    E' la casa di `NON_VALUTABILE` e di `error`. Senza `error`, una regola che solleva
    un'eccezione e' visivamente identica a una regola che dice OK — e il fallimento
    peggiore di questo sistema non e' un alert sbagliato, e' il silenzio indistinguibile
    dalla salute.
    """

    __tablename__ = "rule_status"

    project = Column(String, primary_key=True)
    rule = Column(String, primary_key=True)
    state = Column(String, nullable=False)  # ok | violating | non_valutabile | error
    reason = Column(String, nullable=True)  # perche' non valutabile, o il messaggio d'errore
    updated_at = Column(UTCDateTime, nullable=False)


class SupervisorState(Base):
    """L'heartbeat. Una riga sola, id sempre 1.

    Un supervisore morto e un sistema sano mostrano la stessa schermata: zero alert.
    E' lo stesso errore che il ciclo di vita rifiuta di fare sugli agenti — non trattare
    il silenzio come salute — applicato al supervisore stesso.
    """

    __tablename__ = "supervisor_state"

    id = Column(Integer, primary_key=True)
    last_run_at = Column(UTCDateTime, nullable=False)
    last_run_ms = Column(Integer, nullable=False)
    agents_evaluated = Column(Integer, nullable=False)
    rules_failed = Column(Integer, nullable=False)
    last_error = Column(String, nullable=True)
    consecutive_errors = Column(Integer, nullable=False, server_default="0")


class AgentWatermark(Base):
    """Fin dove R3 ha gia' esaminato le azioni di un agente.

    Senza, un agente veloce (40 azioni al minuto) nasconde la chiamata da 600k token
    dietro le successive: al giro dopo "l'ultima azione" e' un'altra, e l'anomalia piu'
    cara della giornata non viene valutata da nessuno — un buco che PEGGIORA al crescere
    del throughput.

    Tabella separata e non colonna di `supervisor_state` perche' e' per agente, mentre
    quella ha una riga sola.
    """

    __tablename__ = "agent_watermark"

    project = Column(String, primary_key=True)
    last_evaluated_action_id = Column(Integer, nullable=False)


def make_session_factory(db_path: str, busy_timeout: float | None = None) -> sessionmaker:
    """La factory di sessioni. `busy_timeout` esplicito solo per chi non puo' aspettare.

    Il default e' quello del demone (30 s): chi ha tempo preferisce accodarsi piuttosto
    che perdere una scrittura. L'hook di fine turno passa il suo, molto piu' corto —
    li' aspettare e' il danno, non il rimedio (invariante I7).
    """
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": busy_timeout
                      if busy_timeout is not None else SQLITE_BUSY_TIMEOUT_SECONDS},
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    # NIENTE create_all(): Alembic e' l'unica autorita' sullo schema.
    #
    # create_all() crea le tabelle mancanti ma NON altera quelle esistenti e NON aggiunge
    # indici a una tabella che esiste gia'. Verificato eseguendo il codice sul database
    # reale: colonna non aggiunta, indice non aggiunto, nessun errore. Tenerlo qui
    # significherebbe che ogni modifica di schema successiva viene ignorata in silenzio
    # su starkeno.db, che e' gia' popolato.
    #
    # Peggio ancora su un database pulito: create_all() costruisce lo schema SENZA
    # alembic_version, e il successivo `alembic upgrade head` muore su "table already
    # exists" lasciando la catena delle migrazioni inapplicabile.
    #
    # Lo schema si crea con `alembic upgrade head`. I test lo creano dalla fixture
    # `session_factory` in tests/conftest.py, che e' l'unico posto rimasto che chiama
    # create_all.
    return sessionmaker(bind=engine)


def make_readonly_session_factory(db_path: str) -> sessionmaker:
    """Factory SQLite in sola lettura, senza PRAGMA che mutino file o sidecar.

    Il report non e' un processo di scrittura: `mode=ro` fa rispettare questo confine
    direttamente a SQLite. L'URI usa un percorso assoluto POSIX anche su Windows e
    quota i caratteri che altrimenti avrebbero significato dentro una URI.
    """
    assoluto = Path(db_path).resolve().as_posix()
    percorso_uri = quote(assoluto, safe="/:")
    engine = create_engine(f"sqlite:///file:{percorso_uri}?mode=ro&uri=true")
    return sessionmaker(bind=engine)


MAX_AGENT_NAME = 128
AGENTE_SENZA_NOME = "(senza nome)"


def normalizza_progetto(nome) -> str:
    """Le difese al confine di scrittura su `project`.

    E' la chiave di partizione di ogni regola e meta' dell'identita' di ogni alert, ed e'
    una stringa libera senza vincoli: `"scraper"` e `"scraper "` sarebbero due agenti
    diversi con due storie separate, entrambe troppo corte per far scattare qualunque
    soglia.

    **Un nome vuoto non fa fallire la scrittura**, diventa un segnaposto visibile.
    Rifiutare la riga farebbe perdere l'azione dell'agente per un bug del chiamante,
    e "il log non deve mai fallire" viene prima. Sotto il segnaposto il problema si vede
    in dashboard invece di sparire.

    Normalizzare qui e' sicuro, e non ha il rovescio che ha reso stretta la
    normalizzazione dei dettagli di R1: `project` e' un'IDENTITA', non la descrizione
    di un oggetto su cui misurare il progresso.
    """
    testo = (nome or "").strip()
    if not testo:
        return AGENTE_SENZA_NOME
    return testo[:MAX_AGENT_NAME]


def record_action(
    session: Session,
    project: str,
    action: str,
    model_used: str,
    tokens_used: int,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    output_tokens: int | None = None,
) -> AgentAction:
    """Scrive un'azione. I tre componenti sono opzionali, ma O TUTTI O NESSUNO.

    Il default e' `None` e non `0`, ed e' deliberato: NULL significa "non dichiarato" e
    fa ricadere `effective_tokens` sul costo pieno, mentre degli 0 verrebbero letti come
    una dichiarazione valida che azzera cache e output — sottostimando la spesa.
    """
    entry = AgentAction(
        project=normalizza_progetto(project),
        action=action,
        model_used=model_used,
        tokens_used=tokens_used,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        output_tokens=output_tokens,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def get_azioni_conto(session: Session) -> list[AzioneConto]:
    """Lo snapshot immutabile che il modello puro del conto puo' consumare."""
    righe = session.query(AgentAction).order_by(AgentAction.id.asc()).all()
    return [AzioneConto(
        project=riga.project, session_id=riga.session_id, model_used=riga.model_used,
        timestamp=riga.timestamp, tokens_used=riga.tokens_used,
        cache_read_tokens=riga.cache_read_tokens,
        cache_write_tokens=riga.cache_write_tokens, output_tokens=riga.output_tokens,
        azioni_nella_chiamata=riga.azioni_nella_chiamata, skill=riga.skill,
        plugin=riga.plugin, mcp_server=riga.mcp_server, is_sidechain=riga.is_sidechain,
        esito_noto=riga.esito_noto,
    ) for riga in righe]


def conta_chiamate(session: Session) -> int:
    """Il numero di righe di spesa, distinto dal numero di azioni etichettate."""
    return session.query(func.count(AgentAction.id)).scalar() or 0


def _quando(iso: str) -> datetime | None:
    """Il timestamp del transcript, come datetime aware-UTC. `None` se illeggibile.

    Sopra `db.py` tutto e' aware-UTC (invariante 1): la conversione avviene qui, al
    confine, e non si ripete da nessun'altra parte.
    """
    try:
        quando = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if quando.tzinfo is None:
        return quando.replace(tzinfo=timezone.utc)
    return quando.astimezone(timezone.utc)


def scrivi_chiamate(session: Session, chiamate) -> int:
    """Scrive le chiamate nuove. Restituisce quante ne ha scritte.

    **Idempotente per costruzione**, non per accortezza del chiamante: l'indice unico
    `ix_actions_chiamata` su `(session_id, message_id)` fa rispettare la regola al
    database. E' cio' che rende l'hook rieseguibile a ogni turno sullo stesso file, che
    nel frattempo cresce.

    Il `timestamp` scritto e' quello del TRANSCRIPT, non l'ora di ingestione: l'hook
    processa in un istante ore di lavoro, e col default della colonna le regole a
    finestra corta vedrebbero una raffica che non e' mai esistita.

    Le chiamate gia' presenti si scartano PRIMA dell'insert invece di lasciar sollevare
    l'indice: un `IntegrityError` invaliderebbe l'intera transazione, e le chiamate nuove
    che seguono andrebbero perse insieme a quella duplicata.
    """
    if not chiamate:
        return 0

    chiavi = {(c.session_id, c.message_id) for c in chiamate}
    gia_presenti = set()
    # A blocchi: SQLite ha un tetto sul numero di parametri di una query.
    elenco = list(chiavi)
    for inizio in range(0, len(elenco), 400):
        blocco = elenco[inizio:inizio + 400]
        condizione = " OR ".join(
            "(session_id = :s%d AND message_id = :m%d)" % (i, i) for i in range(len(blocco))
        )
        parametri = {}
        for i, (sessione, messaggio) in enumerate(blocco):
            parametri["s%d" % i] = sessione
            parametri["m%d" % i] = messaggio
        righe = session.execute(
            text("SELECT session_id, message_id FROM agent_actions WHERE " + condizione),
            parametri,
        ).all()
        gia_presenti.update((r[0], r[1]) for r in righe)

    nuove = []
    viste = set()
    for chiamata in chiamate:
        chiave = (chiamata.session_id, chiamata.message_id)
        if chiave in gia_presenti or chiave in viste:
            continue
        quando = _quando(chiamata.timestamp)
        if quando is None:
            # Senza un momento credibile la riga e' inutile a ogni regola a finestra:
            # meglio perderne una che avvelenare la finestra di tutte.
            continue
        viste.add(chiave)
        nuove.append(AgentAction(
            project=normalizza_progetto(chiamata.project),
            action=chiamata.action,
            model_used=chiamata.model_used,
            tokens_used=chiamata.tokens_used,
            timestamp=quando,
            cache_read_tokens=chiamata.cache_read_tokens,
            cache_write_tokens=chiamata.cache_write_tokens,
            output_tokens=chiamata.output_tokens,
            session_id=chiamata.session_id,
            message_id=chiamata.message_id,
            azione_fallita=chiamata.azione_fallita,
            esito_noto=chiamata.esito_noto,
            azioni_nella_chiamata=chiamata.azioni_nella_chiamata,
            skill=chiamata.skill,
            plugin=chiamata.plugin,
            mcp_server=chiamata.mcp_server,
            is_sidechain=chiamata.is_sidechain,
        ))

    if not nuove:
        return 0
    session.add_all(nuove)
    session.commit()
    return len(nuove)


def get_agent_summaries(session: Session, *, weights: dict | None = None,
                        max_plausible: int | None = None) -> list[dict]:
    """Il riepilogo per agente, con i token GREZZI e quelli PESATI accanto.

    Le due colonne servono entrambe perche' misurano cose diverse: R2 ragiona sui grezzi
    ("quanto e' grosso il task"), R3 e R4 sui pesati ("quanto sto spendendo"). Con i soli
    grezzi, il numero piu' grande della dashboard sarebbe in un'unita' diversa da quella
    con cui ragionano gli alert, e una segnalazione da 500k pesati sembrerebbe sbagliata.
    """
    from starkeno.config import MAX_PLAUSIBLE_TOKENS, TOKEN_COST_WEIGHTS

    effective = espressione_effective_sql(
        weights or TOKEN_COST_WEIGHTS,
        max_plausible if max_plausible is not None else MAX_PLAUSIBLE_TOKENS,
    )
    righe = session.execute(
        text(
            "SELECT project, SUM(tokens_used) AS total_tokens, COUNT(id) AS action_count, "
            "COALESCE(SUM(%s), 0) AS total_effective "
            "FROM agent_actions GROUP BY project ORDER BY project" % effective
        )
    ).all()
    return [
        {
            "project": r.project,
            "total_tokens": r.total_tokens,
            "action_count": r.action_count,
            "total_effective_tokens": round(r.total_effective),
        }
        for r in righe
    ]


# =============================================================================
# Supervisore: caricamento e aggregazione
# =============================================================================
#
# Perche' qui c'e' del SQL scritto a mano invece dell'ORM.
#
# Misurato su una finestra di 24h di un agente a 1 azione/secondo (86.400 righe):
#     oggetti ORM       1,173 s
#     tuple grezze      0,146 s
#     aggregazione SQL  0,048 s   ("SEARCH ... USING INDEX ix_actions_project_time")
#
# Con 200 agenti valutati ogni 60 secondi, caricare le finestre non e' praticabile. R2 e
# R4 non caricano nessuna riga: ricevono conteggi e somme calcolati dal database. R1 ne
# carica al massimo LOOP_SEQUENCE_LEN, R3 la baseline piu' i candidati nuovi.


def espressione_effective_sql(weights: dict, max_plausible: int) -> str:
    """L'espressione SQL che replica `rules.effective_tokens`, generata dai PESI VERI.

    **Questa formula esiste in due posti**, ed e' una scelta deliberata con un prezzo:
    in `rules.py` perche' le regole devono restare pure e testabili su liste scritte a
    mano, e qui perche' aggregare una finestra da 24h caricando le righe costa 24 volte
    di piu' (misurato sopra).

    Il prezzo e' che due definizioni della stessa formula divergono al primo cambio di
    pesi, senza che nessun errore venga prodotto: R2 misurerebbe una grandezza e R3/R4
    un'altra, credendo entrambe di misurare la stessa. Il test differenziale di
    `test_db_supervisor.py` e' l'unica cosa che le tiene insieme, ed e' per questo che
    entrambe leggono `TOKEN_COST_WEIGHTS` invece di avere numeri scritti dentro.

    I rami sono nello stesso ordine di `rules.effective_tokens`, e tutti tranne l'ultimo
    ricadono sul totale grezzo: mai un'eccezione, mai un indovinello.
    """
    return (
        "CASE"
        "  WHEN tokens_used > {tetto} THEN tokens_used"
        "  WHEN cache_read_tokens IS NULL AND cache_write_tokens IS NULL"
        "       AND output_tokens IS NULL THEN tokens_used"
        "  WHEN cache_read_tokens IS NULL OR cache_write_tokens IS NULL"
        "       OR output_tokens IS NULL THEN tokens_used"
        "  WHEN cache_read_tokens < 0 OR cache_write_tokens < 0 OR output_tokens < 0"
        "       OR tokens_used < 0 THEN tokens_used"
        "  WHEN cache_read_tokens + cache_write_tokens + output_tokens > tokens_used"
        "       THEN tokens_used"
        "  ELSE (tokens_used - cache_read_tokens - cache_write_tokens - output_tokens) * {w_in}"
        "       + cache_read_tokens * {w_cr} + cache_write_tokens * {w_cw}"
        "       + output_tokens * {w_ou}"
        " END"
    ).format(
        tetto=int(max_plausible),
        w_in=float(weights["input"]),
        w_cr=float(weights["cache_read"]),
        w_cw=float(weights["cache_write"]),
        w_ou=float(weights["output"]),
    )


def _flag_qualita_sql() -> str:
    """L'etichetta di qualita' dati, con gli stessi rami e lo stesso ordine."""
    return (
        "CASE"
        "  WHEN tokens_used > :tetto THEN 'token_implausibili'"
        "  WHEN cache_read_tokens IS NULL AND cache_write_tokens IS NULL"
        "       AND output_tokens IS NULL THEN NULL"
        "  WHEN cache_read_tokens IS NULL OR cache_write_tokens IS NULL"
        "       OR output_tokens IS NULL THEN 'componenti_parziali'"
        "  WHEN cache_read_tokens < 0 OR cache_write_tokens < 0 OR output_tokens < 0"
        "       OR tokens_used < 0 THEN 'componente_negativo'"
        "  WHEN cache_read_tokens + cache_write_tokens + output_tokens > tokens_used"
        "       THEN 'somma_supera_totale'"
        "  ELSE NULL"
        " END"
    )


def _record(riga, effective) -> ActionRecord:
    return ActionRecord(
        id=riga.id,
        project=riga.project,
        action=riga.action,
        model_used=riga.model_used,
        tokens_used=riga.tokens_used,
        cache_read_tokens=riga.cache_read_tokens,
        cache_write_tokens=riga.cache_write_tokens,
        output_tokens=riga.output_tokens,
        timestamp=riga.timestamp.replace(tzinfo=timezone.utc)
        if riga.timestamp.tzinfo is None else riga.timestamp,
        effective=float(effective),
    )


def get_active_projects(session: Session, since: datetime,
                      until: datetime | None = None) -> list[str]:
    """Gli agenti con almeno un'azione da `since` in poi.

    Chi chiama vi unisce gli agenti con un alert non risolto, cosi' che la risoluzione
    continui a girare anche per loro: RESOLVE_STALE_DAYS (7 giorni) e' molto oltre
    SUPERVISOR_ACTIVE_AGENT_HOURS (48h), quindi un agente fermo esce dall'insieme degli
    attivi PRIMA di poter essere archiviato, e senza quell'unione i suoi alert non si
    chiuderebbero mai. E' l'invariante I5 di config.py.
    """
    query = session.query(AgentAction.project).filter(AgentAction.timestamp >= since)
    if until is not None:
        query = query.filter(AgentAction.timestamp <= until)
    righe = query.distinct().order_by(AgentAction.project).all()
    return [r.project for r in righe]


def get_distinct_models(session: Session, project: str, since: datetime,
                        until: datetime | None = None) -> dict:
    """I nomi modello GREZZI osservati nella finestra, col numero di chiamate.

    Passo obbligato prima dell'aggregazione: la fascia di un modello e' una funzione
    Python (normalizzazione + MODEL_TIERS) e non e' esprimibile in SQL. Misurato, questa
    query costa nulla — su una finestra da 86.400 righe restituisce una manciata di nomi.
    """
    query = session.query(AgentAction.model_used, func.count(AgentAction.id)).filter(
        AgentAction.project == project, AgentAction.timestamp >= since)
    if until is not None:
        query = query.filter(AgentAction.timestamp <= until)
    righe = query.group_by(AgentAction.model_used).all()
    return {nome: conteggio for nome, conteggio in righe}


def get_actions_since(session: Session, project: str, since: datetime, *,
                      weights: dict, max_plausible: int,
                      until: datetime | None = None) -> list[ActionRecord]:
    """I record dell'agente dalla finestra, in ordine di `id` crescente.

    Ordine su `id` e non su `timestamp`: piu' azioni cadono nello stesso secondo — il
    caso normale per un agente in loop, cioe' quello interessante — e `id` e' garantito
    unico. Restituisce `ActionRecord`, non oggetti ORM.
    """
    effective = espressione_effective_sql(weights, max_plausible)
    query = session.query(AgentAction, text(effective)).filter(
        AgentAction.project == project, AgentAction.timestamp >= since)
    if until is not None:
        query = query.filter(AgentAction.timestamp <= until)
    righe = query.order_by(AgentAction.id.asc()).all()
    return [_record(riga, valore) for riga, valore in righe]


def get_actions_after_id(session: Session, project: str, action_id: int, *,
                         weights: dict, max_plausible: int,
                         until: datetime | None = None) -> list[ActionRecord]:
    """I record successivi a un id: i candidati non ancora esaminati da R3."""
    effective = espressione_effective_sql(weights, max_plausible)
    query = session.query(AgentAction, text(effective)).filter(
        AgentAction.project == project, AgentAction.id > action_id)
    if until is not None:
        query = query.filter(AgentAction.timestamp <= until)
    righe = query.order_by(AgentAction.id.asc()).all()
    return [_record(riga, valore) for riga, valore in righe]


def get_last_actions_by_id(session: Session, project: str, limit: int, *,
                           weights: dict, max_plausible: int) -> list[ActionRecord]:
    """Le ultime azioni per `id`, restituite in ordine crescente.

    Funzione diversa da `get_recent_actions` e con un consumatore diverso: quella serve
    la dashboard ed e' ordinata per timestamp, perche' "recenti" per un umano significa
    cronologiche. Questa serve i rilevatori, che hanno bisogno di un ordine deterministico
    garantito da una chiave unica.
    """
    effective = espressione_effective_sql(weights, max_plausible)
    righe = (
        session.query(AgentAction, text(effective))
        .filter(AgentAction.project == project)
        .order_by(AgentAction.id.desc())
        .limit(limit)
        .all()
    )
    return [_record(riga, valore) for riga, valore in reversed(righe)]


def get_spend_baseline(session: Session, project: str, before_id: int, limit: int, *,
                       weights: dict, max_plausible: int) -> tuple:
    """Gli `effective_tokens` delle azioni PRECEDENTI a `before_id`, per la baseline di R3.

    **L'esclusione del candidato e' qui, nella query (`id < before_id`), non nel
    chiamante.** La riga e' gia' nel database quando viene valutata: una query ingenua la
    include e l'anomalia alza da sola la soglia contro cui e' misurata. Fatta nel
    chiamante, un test su liste scritte a mano la verificherebbe banalmente senza dire
    niente sul codice vero.

    Le righe a `effective <= 0` e quelle implausibili sono scartate qui, non dopo: il
    limite deve valere sulle righe UTILIZZABILI, altrimenti una baseline piena di zeri
    sembrerebbe lunga abbastanza.
    """
    effective = espressione_effective_sql(weights, max_plausible)
    righe = session.execute(
        text(
            "SELECT %s AS effective FROM agent_actions "
            "WHERE project = :agente AND id < :prima AND tokens_used <= :tetto "
            "  AND %s > 0 "
            "ORDER BY id DESC LIMIT :quante" % (effective, effective)
        ),
        {"agente": project, "prima": before_id, "tetto": max_plausible, "quante": limit},
    ).all()
    return tuple(float(r.effective) for r in righe)


def get_window_stats(session: Session, project: str, since: datetime, *,
                     frontier_raw_names, weights: dict, max_plausible: int,
                     soglia_banale: int, soglia_pesante: int,
                     until: datetime | None = None) -> WindowStats:
    """Gli aggregati che R2 e R4 usano, in una query sola.

    Le soglie sono PARAMETRI e non lette da `config`: sono soglie di VALORE e devono
    arrivare fin dentro il SQL, altrimenti l'iniezione della configurazione si ferma a
    meta' strada e una regola tarata resta non tarabile senza che nessun test lo dica.

    Le righe implausibili sono escluse dai conteggi e dalla somma — non sono spesa, sono
    un bug del chiamante — ma contate in `flag_qualita`, perche' un problema invisibile
    non si corregge.
    """
    effective = espressione_effective_sql(weights, max_plausible)
    nomi = list(frontier_raw_names)

    # Una lista vuota non deve diventare "nessun filtro": senza il segnaposto, la
    # clausola IN () e' un errore di sintassi in molti dialetti, e ometterla conterebbe
    # ogni modello come frontier.
    if nomi:
        segnaposti = ", ".join(":m%d" % i for i in range(len(nomi)))
        clausola_frontier = "model_used IN (%s)" % segnaposti
        parametri_modelli = {"m%d" % i: n for i, n in enumerate(nomi)}
    else:
        clausola_frontier = "0"
        parametri_modelli = {}

    plausibile = "tokens_used <= :tetto"
    frontier_ok = "(%s) AND %s" % (clausola_frontier, plausibile)

    query = text(
        "SELECT "
        "  COUNT(*) AS righe_totali,"
        "  SUM(CASE WHEN {f} AND ({e}) > 0 THEN 1 ELSE 0 END) AS valide,"
        "  SUM(CASE WHEN {f} AND ({e}) <= 0 THEN 1 ELSE 0 END) AS zero,"
        "  SUM(CASE WHEN {f} AND ({e}) > 0 AND tokens_used <= :banale THEN 1 ELSE 0 END) AS banali,"
        "  SUM(CASE WHEN {f} AND ({e}) >= :pesante THEN 1 ELSE 0 END) AS pesanti,"
        "  COALESCE(SUM(CASE WHEN {f} AND ({e}) > 0 THEN ({e}) ELSE 0 END), 0) AS somma,"
        "  MAX(CASE WHEN {f} AND ({e}) > 0 THEN timestamp END) AS ultimo,"
        "  MAX(CASE WHEN {f} AND ({e}) > 0 AND tokens_used <= :banale THEN timestamp END) AS ultimo_banale,"
        "  MAX(CASE WHEN {f} AND ({e}) >= :pesante THEN timestamp END) AS ultimo_pesante "
        "FROM agent_actions WHERE project = :agente AND timestamp >= :da{a}"
        .format(f=frontier_ok, e=effective,
                a=" AND timestamp <= :a" if until is not None else "")
    )
    parametri = {
        "agente": project, "da": parametro_datetime(since), "tetto": max_plausible,
        "banale": soglia_banale, "pesante": soglia_pesante, **parametri_modelli,
    }
    if until is not None:
        parametri["a"] = parametro_datetime(until)
    r = session.execute(query, parametri).one()

    flag = {}
    for etichetta, quante in session.execute(
        text(
            "SELECT %s AS flag, COUNT(*) AS quante FROM agent_actions "
            "WHERE project = :agente AND timestamp >= :da%s GROUP BY flag"
            % (_flag_qualita_sql(),
               " AND timestamp <= :a" if until is not None else "")
        ),
        dict({"agente": project, "da": parametro_datetime(since),
              "tetto": max_plausible},
             **({"a": parametro_datetime(until)} if until is not None else {})),
    ).all():
        if etichetta is not None:
            flag[etichetta] = quante

    return WindowStats(
        righe_totali=r.righe_totali or 0,
        frontier_valide=r.valide or 0,
        frontier_scartate_zero=r.zero or 0,
        frontier_banali=r.banali or 0,
        frontier_pesanti=r.pesanti or 0,
        somma_effective_frontier=float(r.somma or 0),
        ultimo_frontier=_aware(r.ultimo),
        ultimo_frontier_banale=_aware(r.ultimo_banale),
        ultimo_frontier_pesante=_aware(r.ultimo_pesante),
        flag_qualita=flag,
    )


def parametro_datetime(valore: datetime) -> str:
    """Un datetime nella forma ESATTA in cui `UTCDateTime` lo scrive sul disco.

    Serve per i confronti nel SQL scritto a mano. Non e' cosmetica: passare direttamente
    un oggetto `datetime` funziona ma e' deprecato da Python 3.12, e la correzione ovvia
    — `isoformat()` — **restituisce zero righe senza alcun errore**.

    Verificato eseguendo, su una finestra che ne contiene due:
        datetime aware  -> 2 righe (con DeprecationWarning)
        isoformat()     -> 0 righe          <- silenzioso e sbagliato
        strftime        -> 2 righe

    Il motivo e' il separatore: SQLite confronta le date come stringhe, il formato sul
    disco e' `2026-08-06 10:00:00.000000` con uno SPAZIO, e `isoformat()` mette una `T`,
    che in ASCII sta dopo lo spazio — quindi nessun confronto matcha mai. Per il
    supervisore sarebbe "nessuna violazione", indistinguibile da una flotta sana.
    """
    if valore.tzinfo is not None:
        valore = valore.astimezone(timezone.utc).replace(tzinfo=None)
    return valore.strftime("%Y-%m-%d %H:%M:%S.%f")


def _aware(valore):
    """SQLite restituisce i timestamp come stringa quando passano da SQL grezzo.

    Sopra `db.py` tutto e' aware-UTC: la conversione avviene qui, al confine, in un punto
    solo. E' lo stesso invariante che `UTCDateTime` fa rispettare all'ORM.
    """
    if valore is None:
        return None
    if isinstance(valore, str):
        valore = datetime.fromisoformat(valore)
    if valore.tzinfo is None:
        return valore.replace(tzinfo=timezone.utc)
    return valore


# =============================================================================
# Supervisore: scrittura di alert, stati ed heartbeat
# =============================================================================

def get_live_alert(session: Session, project: str, rule: str):
    """L'alert VIVO per questa coppia, o None.

    Vivo significa `candidate` o `open`. `resolved` e `dismissed` restano fuori: un falso
    positivo ignorato dall'utente deve poter convivere con un alert futuro sulla stessa
    coppia, e un problema che ritorna deve creare una riga nuova invece di rianimare
    quella vecchia.
    """
    return (
        session.query(Alert)
        .filter(Alert.project == project, Alert.rule == rule,
                Alert.status.in_(("candidate", "open")))
        .one_or_none()
    )


STATI_VIVI = ("candidate", "open")
STATI_ALERT = ("candidate", "open", "resolved", "dismissed")


def get_alerts(session: Session, stati) -> list:
    """Gli alert negli stati richiesti, dal piu' recente. E' la query della dashboard."""
    return (
        session.query(Alert)
        .filter(Alert.status.in_(tuple(stati)))
        .order_by(Alert.last_seen.desc(), Alert.id.desc())
        .all()
    )


def dismiss_alert(session: Session, alert, *, note: str, now: datetime):
    """L'utente marca l'alert come falso positivo.

    Non e' un lusso. Senza dismiss ne' esenzioni configurabili, un falso positivo su un
    agente sano e sempre attivo non e' chiudibile da NESSUNA via: il recupero non scatta
    perche' la violazione e' presente a ogni giro, lo stantio non scatta perche' l'agente
    gira. L'alert resterebbe per sempre — e inietterebbe un warning nella risposta di
    ogni `log_agent_action` di quell'agente, cioe' token e confusione dentro il suo loop.

    La nota e' obbligatoria e non e' burocrazia: la storia dei falsi positivi col loro
    motivo e' il dato che serve per tarare soglie che oggi non sono tarate su niente.
    """
    alert.status = "dismissed"
    alert.resolution = "dismissed"
    alert.user_note = note
    alert.resolved_at = now
    session.commit()
    session.refresh(alert)
    return alert


def mute_alert(session: Session, alert, *, until: datetime):
    alert.muted_until = until
    session.commit()
    session.refresh(alert)
    return alert


def get_open_alerts(session: Session, project: str | None = None) -> list:
    """Gli alert `open`. E' la query del percorso critico di `log_agent_action`.

    Solo `open`, mai `candidate`: includendo i candidate, una raffica che si risolve da
    sola avviserebbe l'agente fino a PROMOTE_MIN_MINUTES prima di svanire,
    reintroducendo la classe di falsi positivi che la separazione fra percorso in linea e
    periodico esiste per uccidere.

    Misurato: passa da `ix_alerts_open` come COVERING INDEX, senza toccare la tabella.
    """
    query = session.query(Alert).filter(Alert.status == "open")
    if project is not None:
        query = query.filter(Alert.project == project)
    return query.order_by(Alert.last_seen.desc()).all()


def get_live_alerts_for_agent(session: Session, project: str) -> list:
    """Tutti gli alert vivi di un agente, indipendentemente dalla regola."""
    return (
        session.query(Alert)
        .filter(Alert.project == project, Alert.status.in_(("candidate", "open")))
        .order_by(Alert.rule)
        .all()
    )


def progetti_con_alert_vivi(session: Session) -> list[str]:
    """Gli agenti che hanno almeno un alert non risolto.

    Vanno valutati anche se fermi da giorni, altrimenti i loro alert non si chiuderebbero
    mai: RESOLVE_STALE_DAYS (7 giorni) e' oltre SUPERVISOR_ACTIVE_AGENT_HOURS (48h), e un
    agente fermo esce dagli attivi prima di poter essere archiviato (invariante I5).
    """
    righe = (
        session.query(Alert.project)
        .filter(Alert.status.in_(("candidate", "open")))
        .distinct()
        .all()
    )
    return [r.project for r in righe]


def conta_azioni_dopo(session: Session, project: str, quando: datetime,
                      until: datetime | None = None) -> int:
    """Quante azioni l'agente ha prodotto DOPO un certo istante.

    E' la prova positiva che il recupero richiede: un agente fermo non ne produce, quindi
    non puo' "guarire" per silenzio.
    """
    query = session.query(func.count(AgentAction.id)).filter(
        AgentAction.project == project, AgentAction.timestamp > quando)
    if until is not None:
        query = query.filter(AgentAction.timestamp <= until)
    return query.scalar() or 0


def ultima_azione(session: Session, project: str,
                  until: datetime | None = None) -> datetime | None:
    """Il timestamp dell'azione piu' recente, per la valutazione dello stantio."""
    query = session.query(func.max(AgentAction.timestamp)).filter(
        AgentAction.project == project)
    if until is not None:
        query = query.filter(AgentAction.timestamp <= until)
    valore = query.scalar()
    return _aware(valore) if valore is not None else None


def upsert_alert(session: Session, *, project: str, rule: str, detail: str,
                 evidence: dict, last_seen: datetime, now: datetime):
    """Crea o aggiorna l'alert vivo per (agente, regola).

    Deve essere un upsert e non una INSERT: l'indice unico parziale impedisce due alert
    vivi per la stessa coppia, quindi una INSERT ingenua solleverebbe `IntegrityError`
    ogni volta che il supervisore rivede una violazione gia' nota — cioe' nel caso
    NORMALE.

    Il `session.rollback()` prima del ritentativo non e' un dettaglio: senza, SQLAlchemy
    solleva `PendingRollbackError` al ritentativo e il giro muore comunque, facendo alla
    rete di sicurezza esattamente il danno che deve impedire.
    """
    esistente = get_live_alert(session, project, rule)
    if esistente is not None:
        return _aggiorna_alert(session, esistente, detail, evidence, last_seen)

    nuovo = Alert(
        project=project, rule=rule, status="candidate", detail=detail,
        evidence=json.dumps(evidence, default=str), episodes=1, observed_rounds=1,
        first_seen=last_seen, last_seen=last_seen,
    )
    session.add(nuovo)
    try:
        session.commit()
    except IntegrityError:
        # Un altro processo ha inserito fra la SELECT e la INSERT. Non dovrebbe
        # succedere — il guard di istanza singola esiste per questo — ma se succede il
        # giro non deve morire.
        session.rollback()
        esistente = get_live_alert(session, project, rule)
        if esistente is None:
            raise
        return _aggiorna_alert(session, esistente, detail, evidence, last_seen)
    session.refresh(nuovo)
    return nuovo


def _aggiorna_alert(session: Session, alert, detail: str, evidence: dict, last_seen: datetime):
    alert.detail = detail
    alert.evidence = json.dumps(evidence, default=str)
    alert.observed_rounds += 1
    if last_seen is not None and (alert.last_seen is None or last_seen > alert.last_seen):
        alert.last_seen = last_seen
    session.commit()
    session.refresh(alert)
    return alert


def promote_alert(session: Session, alert, now: datetime):
    alert.status = "open"
    session.commit()
    session.refresh(alert)
    return alert


def resolve_alert(session: Session, alert, *, resolution: str, now: datetime):
    """Chiude un alert. `resolution` distingue il recupero dall'archiviazione."""
    alert.status = "resolved"
    alert.resolution = resolution
    alert.resolved_at = now
    session.commit()
    session.refresh(alert)
    return alert


def delete_alert(session: Session, alert):
    """Cancella un candidate la cui violazione e' sparita prima della promozione.

    E' la raffica auto-risolta: non deve lasciare traccia, altrimenti `episodes` conta
    episodi che non sono mai stati problemi.
    """
    session.delete(alert)
    session.commit()


def set_rule_status(session: Session, project: str, rule: str, *, state: str,
                    reason: str | None, now: datetime):
    """Scrive lo STATO di valutazione di una regola. E' un upsert: c'e' una riga per coppia.

    E' qui che vivono `non_valutabile` e `error`. Senza `error`, una regola che solleva
    un'eccezione e' visivamente identica a una che dice OK — e il fallimento peggiore di
    questo sistema non e' un alert sbagliato, e' il silenzio indistinguibile dalla salute.
    """
    riga = (
        session.query(RuleStatus)
        .filter(RuleStatus.project == project, RuleStatus.rule == rule)
        .one_or_none()
    )
    if riga is None:
        riga = RuleStatus(project=project, rule=rule)
        session.add(riga)
    riga.state = state
    riga.reason = reason
    riga.updated_at = now
    session.commit()
    return riga


def get_rule_status(session: Session, project: str | None = None) -> list:
    query = session.query(RuleStatus)
    if project is not None:
        query = query.filter(RuleStatus.project == project)
    return query.order_by(RuleStatus.project, RuleStatus.rule).all()


def write_heartbeat(session: Session, *, now: datetime, duration_ms: int,
                    agents_evaluated: int, rules_failed: int, last_error: str | None):
    """L'heartbeat del supervisore. Una riga sola, id fisso a 1.

    Un supervisore morto e un sistema sano mostrano la stessa schermata: zero alert.
    Va scritto a fine di OGNI giro, anche quando il giro fallisce — per questo il
    chiamante lo mette dentro il try/except, non dopo.
    """
    riga = session.get(SupervisorState, 1)
    if riga is None:
        riga = SupervisorState(id=1, consecutive_errors=0)
        session.add(riga)
    riga.last_run_at = now
    riga.last_run_ms = duration_ms
    riga.agents_evaluated = agents_evaluated
    riga.rules_failed = rules_failed
    riga.last_error = last_error
    riga.consecutive_errors = (riga.consecutive_errors or 0) + 1 if last_error else 0
    session.commit()
    session.refresh(riga)
    return riga


def get_heartbeat(session: Session):
    return session.get(SupervisorState, 1)


def get_watermark(session: Session, project: str) -> int | None:
    riga = session.get(AgentWatermark, project)
    return None if riga is None else riga.last_evaluated_action_id


def set_watermark(session: Session, project: str, action_id: int):
    """Scritto SOLO a fine giro riuscito.

    Un giro fallito deve far rivedere le stesse azioni al giro successivo, altrimenti
    un'eccezione transitoria fa saltare per sempre le anomalie di quella finestra.
    """
    riga = session.get(AgentWatermark, project)
    if riga is None:
        riga = AgentWatermark(project=project, last_evaluated_action_id=action_id)
        session.add(riga)
    else:
        riga.last_evaluated_action_id = action_id
    session.commit()


def get_max_action_id(session: Session, project: str) -> int:
    """L'id piu' alto dell'agente, per inizializzare il watermark al primo avvio.

    Il watermark NON parte da 0: con 0, il primo giro rivaluterebbe tutto lo storico e
    aprirebbe oggi alert su anomalie di mesi fa.
    """
    return session.query(func.coalesce(func.max(AgentAction.id), 0)).filter(
        AgentAction.project == project
    ).scalar()


def get_recent_actions(session: Session, project: str, limit: int = 20) -> list[AgentAction]:
    """Azioni piu' recenti di un agente, per la dashboard.

    Ordinate per timestamp perche' "recenti" per un umano significa cronologiche.
    Il tiebreaker sull'id non e' cosmetico: piu' azioni cadono nello stesso secondo
    (normale per un agente in loop, cioe' il caso interessante) e senza di esso la
    stessa query restituisce ordini diversi a ogni chiamata.
    """
    return (
        session.query(AgentAction)
        .filter(AgentAction.project == project)
        .order_by(AgentAction.timestamp.desc(), AgentAction.id.desc())
        .limit(limit)
        .all()
    )
