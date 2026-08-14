# StarkEno — Agente Supervisore v1 (design)

> Data: 2026-08-05. Costruisce sopra la v0 (Agent Activity Tracker) già su `main`.
>
> **Revisione 4.** Riscritto interamente dopo una revisione di completezza su cinque lenti
> (integrazione col codice v0, esercizio, coerenza delle regole, qualità dei dati, testabilità).
> Le patch precedenti avevano reso il documento internamente incoerente — il terzo stato era
> stato aggiunto alle regole ma non allo schema, Alembic adottato ma `create_all()` mai rimosso.
> I difetti trovati sono elencati in §12, e i sei più critici sono stati **verificati eseguendo
> il codice**, non solo ragionandoci sopra.

## 1. Cosa fa e cosa non fa

Il Supervisore trova da solo quattro categorie di problema negli agenti tracciati e apre delle
segnalazioni, senza che l'utente debba chiedere niente.

**In scope v1:** quattro regole deterministiche, le tabelle `alerts` / `rule_status` /
`supervisor_state`, un processo periodico che apre e chiude le segnalazioni, gli endpoint e la
sezione di dashboard che le mostrano, e un modo per zittire un falso positivo.

**Fuori scope v1** (§11): ragionamento LLM, baseline auto-calibranti per agente, aggregazione
cross-agent, esenzioni configurabili per regola.

### Il principio che governa ogni soglia

Segnalare solo quando si è quasi certi. Poche segnalazioni, quasi tutte vere. Una dashboard
rumorosa insegna a ignorarla, e quel fallimento è peggio del mancato rilevamento di qualche spreco.

**Corollario onesto:** le soglie di questo documento sono *ragionate*, non *tarate* — oggi
`agent_actions` è quasi vuoto. Vivono tutte in `config.py` proprio perché il primo compito reale
della v1 è **raccogliere i dati che permetteranno di tararle**. Non sono verità: sono un punto
di partenza da correggere dopo l'uso vero.

### Il fallimento peggiore non è un alert sbagliato

È **il silenzio indistinguibile dalla salute**. Un sistema che non trova niente perché tutto va
bene e un sistema che non trova niente perché è rotto mostrano la stessa identica schermata.
La revisione ha trovato tre modi diversi di finire in quello stato (§12), e per questo il design
ora tratta come requisiti di prima classe: il terzo stato `NON_VALUTABILE` (§3.6), l'heartbeat
del supervisore (§3.5), e la visibilità delle regole che sollevano eccezioni (§8).

---

## 2. Architettura

```
  agente AI
     │  log_agent_action(...)                     ┌──────────────────┐
     ▼                                            │  supervisor.py   │
  mcp_server.py ──► db.py ──► agent_actions ◄─────│  (periodico)     │
     │                            │               └────────┬─────────┘
     │  lookup alert OPEN         │                        │ valuta
     │  (sola lettura)            │                        ▼
     ▼                            ▼            alerts · rule_status · supervisor_state
  warning all'agente        rules.py (puro)                 ▲
                                                            │ legge
                                                         api.py ──► dashboard
```

### `rules.py` — funzioni pure

Ingresso: una lista di record azione già caricati, la configurazione delle soglie, e `now`.
Uscita: `VIOLAZIONE`, `OK`, o `NON_VALUTABILE`. **Non tocca mai il database, mai SQLAlchemy,
mai l'orologio di sistema.**

È l'unica parte del design verificabile senza infrastruttura, ed è per questo che tutto ciò che
può stare qui ci sta.

### `supervisor.py` — il processo periodico

L'unico posto che valuta le regole. Ogni `SUPERVISOR_INTERVAL_SECONDS`:

1. determina l'insieme degli agenti attivi (§2.1)
2. per ciascuno carica le finestre necessarie **tramite funzioni di `db.py`** e le normalizza (§3.1)
3. chiama `rules.py`
4. riconcilia il risultato con `alerts` e `rule_status` (§3.6)
5. scrive l'heartbeat in `supervisor_state` (§3.5)

Firma obbligatoria: `run_once(session, now: datetime, config) -> RoundResult`.
Il loop è `run_forever(config, sleep=time.sleep, max_iterations=None)`, con i parametri iniettabili
perché altrimenti non è testabile (§9).

`supervisor.py` **non importa SQLAlchemy**: l'invariante di `CLAUDE.md` — `db.py` è l'unico modulo
che ci parla — vale anche per il codice nuovo. Le funzioni richieste sono elencate in §2.2.

### `mcp_server.py` — percorso in linea, deliberatamente stupido

`log_agent_action` **non valuta regole**. Fa solo una lookup indicizzata e, se l'agente ha un
alert con `status = 'open'`, aggiunge un warning alla risposta.

**`open`, non "non risolto".** La distinzione non è accademica: se la lookup includesse anche i
`candidate`, una raffica che si risolve da sola (429 + retry, poi successo) avviserebbe l'agente
per fino a `PROMOTE_MIN_MINUTES` prima di svanire — reintroducendo esattamente la classe di falsi
positivi che la separazione in linea/periodico esiste per uccidere. Serve l'indice dedicato di §3.4,
perché l'indice unico parziale copre `candidate + open` e chi implementa userebbe quello.

Le ragioni della separazione, in ordine:

1. **Uccide un'intera classe di falsi positivi.** Un burst che si auto-risolve non diventa mai un alert.
2. **Riduce quasi a zero il rischio sull'operazione critica.** Una lookup indicizzata non è lenta
   né esplode in modi interessanti; un motore di regole sì.
3. **Costo costante per chiamata**, indipendentemente dai dati storici.

### 2.1 Quali agenti valuta un giro

Non tutti quelli mai visti. L'insieme è:

> agenti con almeno un'azione nelle ultime `SUPERVISOR_ACTIVE_AGENT_HOURS`
> **∪** agenti con un alert non risolto (così la risoluzione continua a girare anche per loro)

Senza questo il supervisore rivaluta per sempre agenti spenti da mesi, quattro regole ciascuno,
ogni minuto. Se il numero di agenti distinti nelle ultime 24h supera `MAX_TRACKED_AGENTS`,
il supervisore **smette di valutare** e apre un unico alert di qualità dati: quasi certamente
un chiamante sta mettendo un id di sessione dentro `agent_name` (§10).

### 2.2 Funzioni nuove in `db.py`

```
get_active_agents(session, since) -> list[str]
get_actions_since(session, agent, since) -> list[ActionRecord]     # normalizzati aware-UTC
get_last_actions_by_id(session, agent, limit) -> list[ActionRecord] # ORDER BY id DESC
get_actions_after_id(session, agent, action_id) -> list[ActionRecord]
get_live_alert(session, agent, rule) -> Alert | None
upsert_alert(...) / resolve_alert(...) / bump_alert(...)
get_open_alerts(session, agent=None) -> list[Alert]
set_rule_status(session, agent, rule, state, reason, now)
write_heartbeat(session, now, duration_ms, rules_failed)
```

`get_recent_actions` **resta ordinata per `timestamp`**: è la query della dashboard, e "recenti"
per un umano significa cronologiche. R3 usa `get_last_actions_by_id`, che è una funzione diversa
con un consumatore diverso — entrambe con un commento in `db.py` che dice chi le usa e perché
l'ordinamento differisce.

---

## 3. Modello dati

### 3.0 Migrazioni: Alembic è l'unica autorità sullo schema

**`Base.metadata.create_all()` va rimosso da `make_session_factory`.**

Oggi gira al momento dell'import in `mcp_server.py` e in `api.py`, e girerebbe in `supervisor.py`
come terzo. Verificato eseguendo il codice contro il `starkeno.db` reale:

```
PRIMA  colonne: [id, agent_name, action, model_used, tokens_used, timestamp]
DOPO   colonne: [id, agent_name, action, model_used, tokens_used, timestamp]
>>> colonna aggiunta? False      >>> indice aggiunto? False
```

`create_all()` crea tabelle mancanti ma **non altera quelle esistenti e non aggiunge indici a una
tabella che esiste già**. Quindi ogni modifica di questo documento sarebbe silenziosamente ignorata
su un database già popolato: nessun errore, semplicemente non succede niente. E su un database
pulito è peggio, perché `create_all()` costruisce lo schema *senza* `alembic_version`, e il
successivo `alembic upgrade head` muore su "tabella già esistente" lasciando la catena inapplicabile.

**Procedura di primo avvio, letterale:**

| Situazione | Comandi |
|---|---|
| `starkeno.db` già esistente | `alembic stamp <revisione_v0>` poi `alembic upgrade head` |
| database nuovo | `alembic upgrade head` |

**Controllo di versione all'avvio.** Ogni processo, all'avvio, confronta la revisione del database
con `head` e **si rifiuta di partire** con un messaggio esplicito se non coincidono. È l'unico
punto dove la regola di §7 ("mai far fallire un log") non si applica: fallire rumorosamente
all'avvio è infinitamente meglio di un `no such column` inghiottito da un `try/except` un'ora dopo.

**I test hanno la loro fixture di schema**, che chiama `create_all` esplicitamente su un engine
`tmp_path`. Nessun import di test deve mai toccare `DB_PATH` — oggi `tests/test_mcp_server.py`
importa `starkeno.mcp_server`, che chiama `make_session_factory(DB_PATH)` **prima** del monkeypatch:
lanciare `pytest` ricrea e riavvelena il database di produzione.

### 3.1 Contratto sui datetime — l'invariante che tiene in piedi tutto

**Questo è il difetto più grave trovato dalla revisione, e disattiva l'intero prodotto in silenzio.**

`db.py` scrive `datetime.now(timezone.utc)` (aware) in una `Column(DateTime)` semplice.
Verificato eseguendo il codice:

```
tipo scritto : datetime.now(timezone.utc)  -> aware
tzinfo letto : None
sottrazione  : TypeError: can't subtract offset-naive and offset-aware datetimes
```

`api.py:38` porta già un `.replace(tzinfo=timezone.utc)` come rimedio, prova che il problema è
vivo dalla v0. Il supervisore userebbe `datetime.now(timezone.utc)` come `now` — è l'idioma che
`db.py` usa per il proprio default. Ogni finestra di R1/R2/R4 e ogni confronto di §3.7 solleverebbe
`TypeError`; §7 impone che ogni regola sia isolata nel proprio `try/except`, quindi **tutte e quattro
verrebbero inghiottite** e il supervisore girerebbe per sempre producendo zero alert — visivamente
identico a una flotta sana. E nessun test di §9 se ne accorgerebbe, perché costruiscono liste a mano
con datetime coerenti fra loro, senza mai passare da SQLite.

**L'invariante, da rispettare in ogni punto del sistema:**

> `agent_actions.timestamp` e le colonne DateTime di `alerts` tornano **naive** da SQLite.
> Le funzioni di caricamento di `db.py` (§2.2) le normalizzano a **aware-UTC** prima di restituirle.
> Sopra `db.py`, **tutto è aware-UTC**: i record, `now`, e i valori scritti.

Nessun altro modulo fa `.replace(tzinfo=...)`: la normalizzazione avviene in un punto solo, al
confine, ed è quello che rende il resto del sistema libero di non pensarci.

**Il test che lo protegge** (§9) non può essere un test su liste scritte a mano: deve scrivere righe
tramite `db.py` su uno SQLite vero, rileggerle, e far girare tutte e quattro le regole con un `now`
aware. Nessun test in memoria può vedere questo bug, per costruzione.

**`timestamp` è il momento dell'ingestione, non del lavoro.** Lo assegna `db.py` al momento
dell'insert. Un chiamante che bufferizza o fa backfill comprime ore di lavoro in pochi secondi, e
le regole a finestra corta lo vedono come una raffica. §3.7 e `PROMOTE_MIN_ROUNDS` sono le difese.

### 3.2 Due misure diverse, non una

Un solo `tokens_used` non può rappresentare fedelmente il costo, perché i componenti hanno prezzi
che differiscono di oltre un ordine di grandezza. E le regole non chiedono tutte la stessa cosa:

| Regola | Domanda | Misura |
|---|---|---|
| R2 `expensive_model` | *quanto è grosso il task?* | **token totali**, cache inclusi |
| R3 `spend_anomaly` | *quanto sto spendendo?* | **`effective_tokens`** |
| R4 `steady_waste` | *quanto sto spendendo?* | **`effective_tokens`** |

Sbagliare misura produce falsi positivi in direzioni opposte, e le soglie non possono rimediarlo:
misurando la spesa sui token totali, un agente che riusa 80k di contesto in cache — che spende
frazioni di centesimo — farebbe scattare R4 ogni giorno; misurando la dimensione del task sui soli
token nuovi, lo stesso agente sembrerebbe fare task banali e R2 lo accuserebbe a rovescio.

```python
tokens_used        = Column(Integer, nullable=False)   # totale (già esistente, invariato)
cache_read_tokens  = Column(Integer, nullable=True)
cache_write_tokens = Column(Integer, nullable=True)
output_tokens      = Column(Integer, nullable=True)

TOKEN_COST_WEIGHTS = {"input": 1.0, "cache_read": 0.1, "cache_write": 1.25, "output": 5.0}
```

I pesi sono **rapporti, non prezzi**: non introducono il listino da mantenere che §4/R2 rifiuta,
e i rapporti fra fasce sono molto più stabili dei valori assoluti. Un peso unico sui "token cachati"
sarebbe sbagliato in due direzioni: i cache **write** costano 1.25×, non 0.1× (sottostima di oltre
dieci volte, cieca proprio sul caso caro), e l'**output** costa ~5× l'input (5k in + 8k out darebbe
13k invece di 45k).

#### Tabella di decisione completa

Solo due rami accettano la scomposizione. Tutto il resto ricade sul totale con un segnale di
qualità dati — mai un'eccezione, mai un indovinello:

| Stato dei quattro campi | `effective_tokens` |
|---|---|
| tutti e tre i componenti `NULL` | `tokens_used` (costo pieno) |
| tutti non-`NULL`, tutti `≥ 0`, somma `≤ tokens_used` | formula pesata |
| **misto `NULL`/non-`NULL`** | `tokens_used` + flag qualità dati |
| **un componente negativo** | `tokens_used` + flag qualità dati |
| somma `>` `tokens_used` | `tokens_used` + flag qualità dati |

I due rami di mezzo non sono teorici. Il **misto** è la forma **più comune** che il sistema vedrà:
nell'SDK Anthropic i campi cache sono `Optional` e valgono `None` su ogni chiamata che non tocca
la cache, mentre `output_tokens` è sempre un `int` — cioè lo snippet di §5 la produce a ogni
chiamata non cachata. Verificato: `9000 - None` → `TypeError`, inghiottito da §7, R3 e R4 spente
per sempre.

Il **negativo** è peggio perché è silenzioso: un chiamante con un bug di segno logga
`tokens_used=60000, output_tokens=-40000` → `effective = -100.000`, che è **sotto** la soglia di R4
invece che sopra. Verificato. La riga sparisce dalla regola che esiste apposta per catturarla.

Per la stessa ragione, i filtri di scarto di R3 e R4 sono su **`effective_tokens ≤ 0`**, non su
`tokens_used ≤ 0`: è la grandezza che viene poi confrontata.

Simmetricamente, `effective_tokens > MAX_PLAUSIBLE_TOKENS` è un problema di qualità dati, non una
spesa: una singola chiamata non può fisicamente superare ~2M token, quindi un valore molto sopra è
per definizione un bug (tipicamente un conteggio di byte o caratteri al posto dei token).

### 3.3 Le tre tabelle

```python
class Alert(Base):                          # un EVENTO: qualcosa non va
    __tablename__ = "alerts"
    id            = Column(Integer, primary_key=True)
    agent_name    = Column(String,  nullable=False, index=True)
    rule          = Column(String,  nullable=False)  # loop|expensive_model|spend_anomaly|steady_waste
    status        = Column(String,  nullable=False)  # candidate|open|resolved|dismissed
    detail        = Column(String,  nullable=False)
    evidence      = Column(String,  nullable=False)  # JSON (serializzato da UN helper, §9)
    episodes      = Column(Integer, nullable=False, default=1)
    observed_rounds = Column(Integer, nullable=False, default=1)
    first_seen    = Column(DateTime, nullable=False)
    last_seen     = Column(DateTime, nullable=False)   # <- tempo AZIONE, non tempo ciclo (§3.7)
    resolved_at   = Column(DateTime, nullable=True)
    resolution    = Column(String,  nullable=True)     # recovery|stale|dismissed
    muted_until   = Column(DateTime, nullable=True)
    user_note     = Column(String,  nullable=True)

class RuleStatus(Base):                     # uno STATO: come sta andando la valutazione
    __tablename__ = "rule_status"
    agent_name  = Column(String, primary_key=True)
    rule        = Column(String, primary_key=True)
    state       = Column(String, nullable=False)   # ok|violating|non_valutabile|error
    reason      = Column(String, nullable=True)    # perché non valutabile, o il messaggio d'errore
    updated_at  = Column(DateTime, nullable=False)

class SupervisorState(Base):                # l'HEARTBEAT (§3.5)
    __tablename__ = "supervisor_state"
    id                 = Column(Integer, primary_key=True)   # sempre 1
    last_run_at        = Column(DateTime, nullable=False)
    last_run_ms        = Column(Integer, nullable=False)
    agents_evaluated   = Column(Integer, nullable=False)
    rules_failed       = Column(Integer, nullable=False)
    last_error         = Column(String,  nullable=True)
    consecutive_errors = Column(Integer, nullable=False, default=0)
```

**`NON_VALUTABILE` vive in `rule_status`, non in `alerts`.** È uno stato, non un evento: viene
riscritto a ogni giro. Metterlo in `alerts` occuperebbe l'unico posto vivo dell'indice unico
parziale per quella coppia `(agent, rule)`, così che quando l'agente violasse davvero la
riconciliazione aggiornerebbe la riga di astensione invece di aprire un alert vero.

`rule_status` è anche dove finiscono le regole che **sollevano un'eccezione** (`state='error'`):
senza, una regola rotta è visivamente identica a una regola che dice OK — il fallimento di §1.

`episodes` conta **episodi distinti**, incrementato solo sulla transizione non-violazione →
violazione, mai sul semplice permanere. Se contasse i giri, un episodio di loop da 9 minuti darebbe
9 e uno di spreco darebbe 1440 (la finestra da 24h tiene viva la violazione per 1440 tick),
facendo sembrare il secondo 160 volte più grave a parità di gravità reale. La durata è già
rappresentata da `first_seen`/`last_seen`.

### 3.4 Indici

```python
# alerts
Index("ix_alerts_one_live", "agent_name", "rule",
      unique=True, sqlite_where=text("status IN ('candidate','open')"))
Index("ix_alerts_open", "agent_name", sqlite_where=text("status = 'open'"))

# agent_actions
Index("ix_actions_agent_time", "agent_name", "timestamp")
```

`ix_alerts_open` serve la lookup in linea di §2, l'unica query sul percorso critico.

`ix_actions_agent_time` serve le finestre temporali di R1/R2/R4 — e, misurato con
`EXPLAIN QUERY PLAN` su 20.000 righe, elimina anche il `USE TEMP B-TREE FOR ORDER BY` dalla query
che `api.py` esegue già a ogni caricamento della dashboard: è un guadagno di prestazioni sulla v0
che arriva gratis.

**Non serve un indice `(agent_name, id)`.** Misurato:

```
ORDER BY id        -> SEARCH agent_actions USING INDEX ix_agent_actions_agent_name (agent_name=?)
ORDER BY timestamp -> SEARCH ... ; USE TEMP B-TREE FOR ORDER BY
```

`id INTEGER PRIMARY KEY` **è** il rowid, e SQLite accoda il rowid a ogni voce di indice non-unico:
`ix_agent_actions_agent_name` è già di fatto `(agent_name, rowid)` ordinato. Aggiungerlo costerebbe
una scrittura di b-tree in più su **ogni** `log_agent_action` — cioè sull'unica operazione che §2
spende tre punti elenco a proteggere — senza comprare niente.

L'indice unico parziale è su `('candidate','open')`: `dismissed` ne resta fuori di proposito,
perché deve poter convivere con un alert futuro (§3.7).

### 3.5 L'heartbeat

Un supervisore morto e un sistema sano mostrano la stessa schermata: zero alert. È lo stesso errore
che §3.7 rifiuta di fare sugli agenti — non trattare il silenzio come salute — applicato al
supervisore stesso.

`supervisor_state` viene riscritto a fine di **ogni** giro, **dentro** il `try/except`, così che si
aggiorni anche quando il giro fallisce. `GET /api/supervisor/status` lo espone e la dashboard mostra
"Supervisore: ultimo giro N minuti fa", in rosso oltre `3 × SUPERVISOR_INTERVAL_SECONDS`.

Il logging va su file con `RotatingFileHandler` accanto a `starkeno.db`, non su `print`/stderr:
un processo periodico su Windows non ha uno stderr che qualcuno legga mai.

**Avvio.** `python -m starkeno.supervisor`, mai per percorso (rompe gli import assoluti, come già
documentato per `mcp_server`). Uno `start_starkeno.ps1` avvia i tre processi nell'ordine giusto —
migrazione, poi gli altri. **Guard di istanza singola obbligatorio**: il supervisore apre un socket
su una porta locale fissa all'avvio ed esce con un messaggio chiaro se è già occupata. Un lock file
non si pulisce dopo un kill; due copie simultanee raddoppierebbero `episodes` e, con `config.py`
diversi, aprirebbero e chiuderebbero lo stesso alert a vicenda ogni 60 secondi — il lampeggio che
§3.7 esiste per impedire, reso silenzioso dalla difesa upsert di §8.

### 3.6 I tre esiti di una regola

`VIOLAZIONE` · `OK` · **`NON_VALUTABILE`**.

Il terzo stato è necessario perché storia insufficiente o dati inutilizzabili devono dire
*"sto ancora calibrando"*, non *"tutto a posto"*. Senza, una regola tace per ignoranza e sembra
dare via libera.

Cosa fa la riconciliazione con ciascuno:

| Esito | Effetto su `alerts` | Effetto su `rule_status` |
|---|---|---|
| `OK` | avanza il conteggio verso il recupero (§3.7) | `state='ok'` |
| `VIOLAZIONE` | crea/aggiorna candidate o open | `state='violating'` |
| `NON_VALUTABILE` | **congela**: non promuove, non risolve, non cancella un candidate, **non tocca `last_seen`** | `state='non_valutabile'` + `reason` |
| eccezione | nessun effetto | `state='error'` + messaggio |

Il congelamento non è un dettaglio. Se `NON_VALUTABILE` fosse trattato come "non violazione", un
alert R2 aperto si chiuderebbe per recupero mentre un chiamante rotto scrive `tokens_used=0` e lo
spreco continua senza che nessuno lo misuri; se fosse trattato come violazione, `last_seen`
avanzerebbe a ogni giro e l'alert non si chiuderebbe mai, nemmeno per stantio.

### 3.7 Ciclo di vita di un alert

| Da | A | Quando |
|---|---|---|
| — | `candidate` | prima osservazione della violazione |
| `candidate` | `open` | **entrambe**: `now - first_seen ≥ PROMOTE_MIN_MINUTES` **e** `observed_rounds ≥ PROMOTE_MIN_ROUNDS` |
| `candidate` | *cancellato* | la violazione sparisce prima della promozione (raffica auto-risolta) |
| `open` | `open` | violazione riosservata: `last_seen`, `episodes`, `observed_rounds` aggiornati |
| `open` | `resolved` | recupero, oppure stantio (sotto) |
| `open`/`candidate` | `dismissed` | l'utente la marca come falso positivo (§6) |
| `resolved` | nuovo `candidate` | il problema ritorna |

**La doppia condizione di promozione** esiste perché il portatile si sospende. Senza il conteggio
dei giri: candidate creato alle 18:00, coperchio chiuso alle 18:01, primo giro alle 09:00 del
giorno dopo → `now - first_seen` = 15 ore ≥ 15 minuti, e per R2/R4 (finestra 24h) la violazione è
ancora "presente" → promozione **avendo osservato un solo giro**. La promozione ritardata, che è
ciò che rende il sistema prudente nei fatti, non avrebbe mai avuto luogo.

#### Il silenzio non è guarigione

Chiudere dopo N minuti senza violazioni è sbagliato: **un agente fermo non produce violazioni per
definizione**. Un agente cron orario e rotto chiuderebbe a ogni pausa e riaprirebbe a ogni
esecuzione, lampeggiando per sempre, e `episodes` non accumulerebbe niente di sensato.

**`last_seen` è il timestamp dell'azione più recente che ha contribuito alla violazione**, non
l'ora del giro del supervisore. È la definizione che fa funzionare tutto il resto: quando il
comportamento cattivo cessa, `last_seen` **smette di avanzare** e la finestra pulita dopo di esso
può crescere.

Due chiusure, entrambe con prova positiva:

1. **Recupero** — esistono almeno `RESOLVE_MIN_HEALTHY_ACTIONS` azioni dopo `last_seen`, **e** la
   regola rivalutata *su quella sola finestra ristretta* restituisce `OK`.
   La restrizione è essenziale: rivalutando sulla finestra piena, un alert R4 aperto su 15 chiamate
   pesanti non potrebbe chiudersi finché quelle 15 non escono dalle 24 ore, e per un agente
   schedulato non uscirebbero mai. Se la finestra ristretta non basta a valutare la regola,
   l'esito è `NON_VALUTABILE` e si aspetta: il meccanismo si autoregola senza costanti per regola.
2. **Stantio** — nessuna attività dell'agente per `RESOLVE_STALE_DAYS`. Non è guarigione, è
   archiviazione: `resolution='stale'`, marcato diversamente in dashboard.
   Al primo giro dopo un'interruzione del processo più lunga di `3 × SUPERVISOR_INTERVAL_SECONDS`
   (rilevabile dall'heartbeat) la valutazione dello stantio **si salta per un giro**, altrimenti
   dieci giorni di vacanza archiviano in blocco ogni alert aperto.

Il tempo di silenzio da solo non chiude mai un alert.

#### Un incidente, non tre righe

Un agente bloccato in `read → edit → test` su modello frontier a 30k token per chiamata fa scattare
R1 (loop), R4 (chiamate pesanti ripetute) e forse R3 — tre righe in dashboard per una causa sola e
una correzione sola, ed è il caso grave più tipico, non un limite.

Minimo sindacale in v1: quando si apre un alert mentre esiste un alert `loop` vivo per lo stesso
agente e la finestra della violazione è contenuta in quella del loop, si scrive `related_rule` in
`evidence` e la dashboard **raggruppa per agente**, così tre righe si leggono come un incidente.
La soppressione vera è rimandata (§11).

---

## 4. Le quattro regole

### R1 — `loop`: l'agente è bloccato

Un loop è **mancanza di progresso**. Con azioni specifiche si vede nella ripetizione; con categorie
grezze si vede nella **sequenza**. Due rilevatori, **un solo alert**.

```
sano:     read → edit → test → commit → read → search → edit → test → commit
bloccato: read → edit → test → read → edit → test → read → edit → test → read → edit → test → …
```

Nessuna azione si ripete 10 volte in nessuna delle due righe: il rilevatore A è cieco a entrambe.

#### Il parsing di `action`

`action` è testo libero deciso da chi chiama. Si divide sul **primo** `:`, ma **solo se**:

- la parte sinistra è non vuota e **non contiene separatori di percorso** (`/`, `\`)
- la parte destra è non vuota dopo lo strip

Altrimenti l'intera stringa è una categoria nuda. Le due guardie servono a casi reali:

| `action` | Parsing | Perché |
|---|---|---|
| `read_file:src/app.py` | cat=`read_file`, det=`src/app.py` | normale |
| `plan:` / `act:` / `observe:` | **categoria nuda** | dettaglio vuoto = *assente*, non *identico* |
| `C:\Users\<utente>\src\app.py` | **categoria nuda** | senza la guardia, categoria = `C` |

Il caso `plan:` non è teorico: un agente che costruisce le etichette come `f"{step}:{target}"` con
`target` vuoto emette dettagli tutti-identici (tutti `""`) e finirebbe nel ramo **più sensibile**
(K=3) sui dati **meno informativi** — un agente sano a tre fasi accusato di loop. Il caso Windows è
l'immagine speculare: ogni azione collassa su categoria `C` con dettagli tutti distinti, e R1 si
spegne del tutto senza che niente lo dica.

**Normalizzazione del dettaglio**, in quest'ordine: via la query string (dopo `?`), via il fragment
(dopo `#`), `\` → `/`, minuscole. **Nient'altro.**

Deve restare stretta perché nei dati grezzi i due casi problematici si distinguono già, ed è la
normalizzazione aggressiva a distruggere il segnale:

| Sequenza | Dopo normalizzazione | Esito |
|---|---|---|
| `read_file:app.py?line=12` / `?line=47` / `?line=91` | tutti **identici** | è bloccato ✓ |
| `fetch:user_1` / `fetch:user_2` / `fetch:user_3` | tutti **distinti** | sta avanzando ✓ |

Una versione precedente normalizzava anche cifre, timestamp e UUID. Sembrava più robusta ed era
**attivamente dannosa**: un batch sano `fetch/validate/save:user_1..100` collassava su `user_N`,
i dettagli risultavano identici, e il rilevatore scattava con K=3 su un ciclo ripetuto cento volte.
Il batch non rivisita mai lo stesso oggetto, il loop rivisita sempre lo stesso: è esattamente la
distinzione che le cifre portano e che azzerarle cancella.

**Punto cieco residuo, dichiarato:** rumore annidato *dentro* l'identificatore
(`search:query_1730992811`) resta indistinguibile da un oggetto nuovo. La via d'uscita è il
contratto di §5, non un'euristica più aggressiva.

#### Rilevatore A — ripetizione identica

Stessa `action` normalizzata, stesso agente, in `LOOP_WINDOW_MINUTES`:

- azione **con** dettaglio → soglia `LOOP_MIN_REPEATS`
- azione **senza** dettaglio (categoria nuda) → soglia `LOOP_MIN_REPEATS_NO_DETAIL`

La seconda soglia esiste perché senza di essa il rilevatore A **inverte l'incentivo promesso da §5**:
un indicizzatore che logga `read_file` senza dettaglio e macina 3 file al secondo violerebbe alla
decima azione e resterebbe in violazione ininterrotta, diventando un alert `loop` su un batch
perfettamente sano. Chi segue la convenzione sarebbe protetto e chi non la segue accusato —
l'opposto di quanto il documento promette.

#### Rilevatore B — ciclo ripetuto

L'algoritmo, perché "esiste un ciclo ripetuto K volte" lascia cinque decisioni aperte e due
implementatori costruirebbero due sistemi diversi:

```
1. prendi le ultime LOOP_SEQUENCE_LEN azioni dell'agente (ORDER BY id DESC, poi inverti)
2. il matching del ciclo è sulla sola CATEGORIA          <- non sulla stringa intera
3. la ricerca è ANCORATA all'azione più recente          <- le K ripetizioni finiscono in fondo
4. per L da LOOP_CYCLE_MIN_LEN a LOOP_CYCLE_MAX_LEN:     <- la prima L che combacia vince
     conta K = quante volte il blocco finale di L categorie si ripete consecutivamente
     se K >= 2 e le K*L azioni stanno entro LOOP_CYCLE_WINDOW_MINUTES:
        classifica i dettagli PER POSIZIONE nel ciclo:
          posizione i identica in tutte le K ripetizioni  -> identica
          posizione i sempre diversa                      -> distinta
        se TUTTE le posizioni sono distinte  -> nessun alert (sta avanzando)
        se TUTTE le posizioni sono identiche -> K_richiesto = LOOP_CYCLE_K_SAME_DETAIL
        altrimenti (misto, o dettagli assenti) -> K_richiesto = LOOP_CYCLE_K_NO_DETAIL
        se K >= K_richiesto: VIOLAZIONE
5. nessuna L combacia -> OK
```

La classificazione **per posizione** è la decisione che conta di più. Il loop più comune che esista,
`read:app.py → edit:app.py → test:tests/`, ha dettagli identici per posizione (K=3) ma "misti"
se si guarda l'insieme di tutti i dettagli della finestra ({app.py, tests/}, K=6). Il doppio di
soglia sul caso principale, a seconda di come si legge la stessa frase.

`NON_VALUTABILE` se l'agente ha meno di `LOOP_MIN_HISTORY` azioni.

### R2 — `expensive_model`: modello costoso per task banale

**Misura: token totali** — R2 chiede quanto è grosso il task, e un contesto da 80k non è banale
nemmeno se arriva tutto da cache.

Modello `frontier` **e** `tokens_used ≤ EXPENSIVE_TRIVIAL_TOKENS`, per `≥ EXPENSIVE_MIN_OCCURRENCES`
volte in `EXPENSIVE_WINDOW_HOURS`, e queste sono `≥ EXPENSIVE_MIN_SHARE` delle chiamate frontier
dell'agente nella finestra.

Il requisito di ripetizione è deliberato: **una** chiamata piccola su un modello grosso può essere
un giudizio difficile che vale il modello. Venti in un giorno sono un'abitudine.

**La normalizzazione dei nomi modello**, come pipeline ordinata e testabile:

```
1. minuscole
2. via un suffisso di versione finale del tipo  :<cifre>
3. prendi il segmento dopo l'ULTIMO  /
4. prendi il segmento dopo l'ULTIMO  .
5. via un suffisso di data finale  -AAAAMMGG
```

La regola precedente ("via il prefisso prima di `/` o `:`") si rompe su ID reali. Verificato:

| ID reale | Vecchia regola | Pipeline nuova |
|---|---|---|
| `us.anthropic.claude-opus-4-5-20251101-v1:0` (Bedrock) | `'0'` ✗ | `claude-opus-4-5-v1` ✓ |
| `publishers/anthropic/models/claude-opus-4-5` (Vertex) | `'anthropic/models/…'` ✗ | `claude-opus-4-5` ✓ |

Guardie:

- **`effective_tokens ≤ 0` escluso** da numeratore e denominatore. Zero è dato mancante, non task
  piccolo: la colonna è `nullable=False` senza validazione.
- **Astensione** (`NON_VALUTABILE` + motivo) se oltre `EXPENSIVE_MAX_ZERO_SHARE` delle righe ha
  `effective_tokens ≤ 0`.
- **Modello non mappato non è mai `frontier`** — sconosciuto significa nessuna prova, non colpevole.
  Escluso da numeratore **e** denominatore.
- **Astensione se oltre `MAX_UNMAPPED_SHARE` delle righe è non mappata.** Senza questa, un agente i
  cui nomi modello non normalizzano ha denominatore zero, la guardia anti-divisione restituisce `OK`,
  e R2 e R4 sono **cieche per sempre senza nemmeno un `NON_VALUTABILE`** — il fallimento che §3.6
  esiste per impedire, sulle due sole regole che parlano di soldi. Il motivo deve nominare le
  stringhe non riconosciute, così la correzione è una riga di `MODEL_TIERS`.
- `len(frontier) > 0` verificato prima della share.

Le fasce stanno in `MODEL_TIERS` (`frontier`/`standard`/`economy`). **Niente listino prezzi in
euro:** si sfasa da solo, va mantenuto, e per capire che stai sprecando basta la fascia.

### R3 — `spend_anomaly`: spesa fuori scala rispetto alla propria storia

**Misura: `effective_tokens`**, sia per il candidato sia per la baseline.

**Valutata su tutte le azioni non ancora esaminate**, non sull'ultima. Il supervisore tiene un
watermark `last_evaluated_action_id` per agente e valuta tutte le righe successive.

Senza il watermark, un agente veloce (40 azioni al minuto) nasconde la chiamata da 600k token
dietro le successive: al giro dopo "l'ultima azione" è un'altra, e l'anomalia più cara della
giornata non viene valutata da nessuno — un buco che **peggiora al crescere del throughput**.

Un'azione è anomala se soddisfa **tutte e tre**:

- `effective_tokens ≥ SPEND_ABS_FLOOR_TOKENS`
- `≥ SPEND_MEDIAN_MULT ×` la **mediana** della baseline
- `≥ SPEND_P95_MULT ×` il **95° percentile** della baseline

Mediana e percentile, non media: la media viene trascinata proprio dai valori anomali che stiamo
cercando, quindi ogni anomalia renderebbe la regola più sorda alla successiva.

**Promozione: servono `SPEND_PROMOTE_MIN_ANOMALIES` anomalie** in `SPEND_ANOMALY_WINDOW_HOURS`,
non il semplice trascorrere del tempo. Un'anomalia isolata è una violazione storica su una riga
immutabile: non può auto-risolversi, quindi la difesa anti-raffica di §2 non la coprirebbe, e una
singola analisi one-shot alle 18:00 diventerebbe un alert permanente — mentre R2 pretende venti
occorrenze per non punire lo stesso identico giudizio.

Guardie:

- **Il candidato è escluso dalla propria baseline.** La riga è già nel database quando viene
  valutata: una query ingenua la include e l'anomalia alza da sola la soglia contro cui è misurata.
  L'esclusione avviene **nella query**, non nel chiamante, altrimenti il test sulle liste a mano
  la verifica banalmente e non dice niente sul codice vero.
- **`ORDER BY id DESC`, non `timestamp DESC`.** Il timestamp è assegnato all'insert e più azioni
  cadono nello stesso secondo — normale per un agente in loop, che è il caso interessante — quindi
  l'ordinamento per timestamp non è deterministico e R3 alternerebbe VIOLAZIONE e OK sugli stessi dati.
- `effective_tokens ≤ 0` scartato dalla baseline; candidato `≤ 0` non valutato.
- `NON_VALUTABILE` sotto `SPEND_MIN_HISTORY` azioni valide.

**Limite noto:** essendo relativa alla storia dell'agente, R3 è **strutturalmente cieca** a un
agente che spreca dal primo giorno. È il buco che R4 copre.

### R4 — `steady_waste`: spreco costante ad alto volume

**Misura: `effective_tokens`.**

Modello `frontier` in `HEAVY_WINDOW_HOURS`, e **una delle due**:

- `≥ HEAVY_MIN_OCCURRENCES` chiamate con `effective_tokens ≥ HEAVY_TOKENS`   *(chiamate grandi)*
- somma degli `effective_tokens` frontier `≥ HEAVY_DAILY_TOKENS`             *(volume aggregato)*

Il secondo ramo chiude una banda scoperta fra R2 e R4. R2 copre le chiamate ≤1k, R4 quelle ≥25k;
in mezzo nessuna regola guardava la spesa **aggregata**:

| Agente frontier | R2 | R3 | R4 (solo primo ramo) |
|---|---|---|---|
| 15 × 60k/giorno = 900k | tace | tace (è la sua normalità) | **scatta** |
| 100 × 8k/giorno = 800k | tace (8k > 1k) | tace | **taceva** |

Praticamente la stessa spesa, esito opposto, solo perché distribuita su chiamate più piccole.
Nessun valore di `HEAVY_TOKENS` può chiuderla, perché qualunque soglia lascia scoperta la banda
sotto di sé — serviva un ramo che sommasse invece di contare. È una `SUM` sull'indice
`ix_actions_agent_time` che già esiste.

R4 è l'unica regola **assoluta** delle quattro, e serve perché le altre tre sono **relative**:
un agente sbagliato dalla prima riga (*born broken*) non devia mai da se stesso.

Stesse guardie di R2 su token `≤ 0`, modelli non mappati e share di non mappati.

---

## 5. Il contratto con chi chiama

Tre proprietà di cui il Supervisore ha bisogno **non sono verificabili dal Supervisore**.
Vanno nella docstring del tool MCP, che è la documentazione che gli agenti leggono davvero.

**`action` — granularità.** `categoria:dettaglio` quando esiste un oggetto
(`read_file:src/app.py`). Con sole categorie il rilevamento funziona comunque, con soglie più larghe
(§4/R1). Il rumore variabile va **dopo un `?`** (`search:query?ts=173099`), dove la normalizzazione
lo rimuove — dentro l'identificatore verrebbe scambiato per un oggetto nuovo.

**`tokens_used` — significato.** Token **totali**, cache read **inclusi**.

**La scomposizione — opzionale, ma o tutta o niente.** Una dichiarazione parziale è trattata come
nessuna dichiarazione (§3.2), quindi i tre campi vanno passati insieme:

```python
u = response.usage
log_agent_action(
    ...,
    tokens_used        = (u.input_tokens + (u.cache_read_input_tokens or 0)
                          + (u.cache_creation_input_tokens or 0) + u.output_tokens),
    cache_read_tokens  = u.cache_read_input_tokens or 0,
    cache_write_tokens = u.cache_creation_input_tokens or 0,
    output_tokens      = u.output_tokens,
)
```

Gli `or 0` non sono cosmetici: nell'SDK quei due campi sono `Optional` e valgono `None` su ogni
chiamata che non tocca la cache. L'errore da non fare è mettere i cache **write** insieme ai read:
costano più dell'input normale, non meno, e confonderli sottostima la spesa di oltre dieci volte.

---

## 6. La superficie di lettura

Senza questa sezione la v1 può essere "completa" — tutti i test verdi, il supervisore che gira,
`alerts` che si riempie — **senza che un solo alert raggiunga mai un essere umano**. Oggi la
dashboard è una tabella di tre colonne che non ha alcuna nozione di alert, e la carica una volta
sola al load, senza polling.

```
GET  /api/alerts?status=open|candidate|resolved|dismissed|all
       default: candidate+open, ordinati per last_seen desc, con evidence deserializzato
GET  /api/rule-status            stato per (agente, regola), incluso non_valutabile e error
GET  /api/supervisor/status      l'heartbeat di §3.5
POST /api/alerts/{id}/dismiss    body: {note}  -> status='dismissed', user_note obbligatoria
POST /api/alerts/{id}/mute       body: {until} -> muted_until
```

**Ordine di registrazione:** tutte le rotte vanno dichiarate **prima** di
`app.mount("/", StaticFiles(..., html=True))` (`api.py:45`), altrimenti il catch-all le oscura e
restituisce un 404 statico.

**Serializzazione:** `resolved_at` e `muted_until` sono nullable. Il pattern esistente
`a.timestamp.replace(tzinfo=timezone.utc)` applicato a `None` solleva `AttributeError` → **HTTP 500
sull'endpoint appena esiste un alert non risolto**, cioè dal primo minuto di vita della v1. Tutti i
DateTime passano da **un solo helper** che gestisce il caso nullo (§9).

**Dismiss non è un lusso.** §11 rimanda le esenzioni configurabili, e senza *né* esenzioni *né*
dismiss un falso positivo su un agente sano e sempre attivo **non è chiudibile da nessuna via**:
il recupero non scatta (la violazione è presente a ogni giro), lo stantio non scatta (l'agente
gira). L'alert resta per sempre — e siccome §2 inietta un warning nella risposta di ogni
`log_agent_action` di quell'agente, sono token e confusione **dentro il loop dell'agente**, per
sempre. Un `eval-runner` che per progetto fa 25 chiamate piccole al giorno al modello frontier è
esattamente questo caso, ed è normale scriverne uno.

La `user_note` obbligatoria non è burocrazia: la storia dei falsi positivi con il loro motivo è
il dato che serve per la taratura di §1.

**Dashboard:** sezione alert sopra la tabella agenti, raggruppata per agente (§3.7),
`setInterval(load, 15000)`, badge distinti per candidate/open/non-valutabile/error, riga di stato
del supervisore, colonna "Token pesati" accanto ai token grezzi — oggi il numero più grande della
pagina è in un'unità diversa da quella con cui ragionano gli alert.

---

## 7. Gestione errori — la regola non negoziabile

**Il Supervisore non deve mai far fallire un log.** Un layer di osservabilità che rompe la cosa che
osserva è *peggio* che inutile: perdi sia i dati sia il lavoro dell'agente.

- `log_agent_action`: la lookup degli alert è dentro `try/except`. Se fallisce, l'azione viene
  registrata comunque e la risposta è quella normale, senza warning.
- `supervisor.py`: ogni giro dentro `try/except`, eccezione catturata, loggata su file, si dorme e
  si riprova. **Il `try` sta dentro il `while`**, non fuori — con il `try` esterno, che è la forma
  più naturale da scrivere, la prima eccezione fa uscire dal loop e il supervisore muore in silenzio.
- Ogni regola isolata nel proprio `try/except`, e l'eccezione **scrive `state='error'` in
  `rule_status`** (§3.3). Senza, una regola rotta è indistinguibile da una che dice OK.

L'unica eccezione: il controllo di versione dello schema all'avvio (§3.0) **deve** fallire
rumorosamente.

---

## 8. Concorrenza

Con `supervisor.py` diventano **tre** processi sul file SQLite.

### WAL non basta

Il journal **WAL** va attivato — senza, i lettori bloccano gli scrittori. Ma WAL risolve solo la
contesa *lettore/scrittore*: **SQLite resta a scrittore singolo**, e il timeout di default è
praticamente nullo, quindi il perdente riceve subito `database is locked`.

`make_session_factory` completa, perché §7 dava lo snippet del timeout ma non diceva né dove né
come attivare WAL:

```python
def make_session_factory(db_path: str) -> sessionmaker:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": SQLITE_BUSY_TIMEOUT_SECONDS},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return sessionmaker(bind=engine)     # niente create_all: vedi §3.0
```

Con il timeout la scrittura perdente **si accoda** invece di fallire. Senza, la promessa di §7
("il log non fallisce mai") sarebbe falsa ogni volta che due agenti scrivono insieme.

WAL crea `starkeno.db-wal` e `-shm`, che **non** corrispondono a `*.db` in `.gitignore`: vanno
aggiunti, altrimenti compaiono in ogni `git status` e possono finire in un `git add .`.

### La scrittura su `alerts` deve essere un upsert

L'indice unico parziale impedisce due alert vivi per `(agent_name, rule)` — quindi una `INSERT`
ingenua solleva `IntegrityError` ogni volta che il supervisore rivede una violazione già nota,
cioè nel caso **normale**:

1. `SELECT` dell'eventuale alert vivo
2. se esiste → aggiorna
3. se no → `INSERT` di un `candidate`
4. il tutto dentro `try/except IntegrityError` **con `session.rollback()` prima del ritentativo**

Il rollback non è un dettaglio: senza, SQLAlchemy solleva `PendingRollbackError` al ritentativo e
il giro muore comunque — la rete di sicurezza farebbe esattamente il danno che deve impedire.

---

## 9. Test

| Cosa | Come |
|---|---|
| `rules.py`, tutte e 4 | liste scritte a mano, `now` come parametro, nessun DB |
| Confini | esattamente sotto soglia, esattamente sopra, finestra scaduta |
| **Configurazione iniettata** | ogni test costruisce la propria config con valori **diversi** dai default di `config.py` |
| Terzo stato | storia insufficiente ⇒ `NON_VALUTABILE`, mai `OK` |
| **Fuso orario** | righe scritte via `db.py` su SQLite vero, rilette, tutte e 4 le regole con `now` aware ⇒ nessun `TypeError` |
| **Migrazione** | DB con solo schema v0 → `alembic upgrade head` → `PRAGMA table_info` / `index_list` confermano colonne e indici |
| Rilevatore B | i tre livelli di qualità del segnale, classificati **per posizione** |
| Invariante R1 | `LOOP_SEQUENCE_LEN ≥ LOOP_CYCLE_MAX_LEN × LOOP_CYCLE_K_NO_DETAIL` |
| **Batch sano** | `fetch/validate/save:user_1..100`, ciclo × 100, dettagli distinti ⇒ **nessun alert** |
| **Batch senza dettagli** | 200 × `read_file` in 10 min ⇒ **nessun alert** (soglia no-detail) |
| **Dettaglio degenere** | `plan:` / `act:` / `observe:` × 3 ⇒ **nessun alert** |
| **Percorso Windows** | `C:\Users\<utente>\...` ⇒ categoria nuda, non categoria `C` |
| Normalizzazione modelli | tabella ID reale → fascia attesa: Bedrock, Vertex, OpenRouter, suffisso data, uno non mappato |
| **Share non mappata** | finestra 100% non mappata ⇒ `NON_VALUTABILE`, mai `OK` |
| `effective_tokens` | i cinque rami della tabella di §3.2, incluso NULL parziale e componente negativo |
| Cache write ≠ read | 20k di `cache_write` pesano **più** di 20k di input |
| Peso output | 5k in + 8k out ⇒ ≈45k, non 13k |
| Baseline R3 (a livello DB) | 201 azioni, alcune nello stesso secondo ⇒ baseline di `SPEND_HISTORY_WINDOW`, **senza l'id più alto**, identica su chiamate ripetute |
| Ciclo di vita | candidate→open, candidate→cancellato, open→resolved, resolved→riaperto, →dismissed |
| **Promozione** | richiede **entrambe** le condizioni: né il solo tempo né i soli giri promuovono |
| **Agente cron** | gira ogni ora e fallisce sempre ⇒ **un solo `open`**, non lampeggia |
| Recupero, per regola | quattro righe separate — R1, R2, R3, R4 chiudono davvero per recupero |
| Auto-risoluzione | raffica che sparisce prima della promozione ⇒ nessun alert |
| **Warning in linea** | `open` ⇒ warning; `candidate` ⇒ **nessun** warning; nessun alert ⇒ risposta byte-identica alla v0 |
| Upsert | seconda violazione aggiorna; ramo `IntegrityError` forzato ⇒ ritentativo riesce |
| **`run_forever`** | `sleep` finto, `max_iterations=3`, `run_once` che solleva ogni volta ⇒ tre chiamate, nessuna eccezione propagata |
| `PRAGMA journal_mode` | ritorna `wal` |
| **API** | alert aperto restituito; `resolved_at` nullo non dà 500; `evidence` fa round-trip; `stale` distinguibile da `recovery` |
| **Test critico** | la lookup solleva ⇒ `log_agent_action` registra comunque e risponde successo |

Le due righe sulla configurazione iniettata e sull'invariante R1 esistono per lo stesso motivo:
senza, una `rules.py` che ignora del tutto il parametro di configurazione e usa costanti hardcoded
passerebbe tutti i test, e alzare una soglia dopo due settimane di dati veri non cambierebbe niente
— rendendo inutile il compito dichiarato della v1.

Il processo periodico si testa chiamando `run_once(now=...)` più volte facendo avanzare `now` a
mano, con i valori di **produzione** delle costanti. Mai avviando il loop con `sleep`, e mai
azzerando `PROMOTE_MIN_MINUTES` nei test — sarebbe cancellare la proprietà sotto test.

---

## 10. Qualità di `agent_name`

`agent_name` è la chiave di partizione di ogni regola e metà dell'identità di ogni alert, ed è una
stringa libera senza vincoli. Tre difese al confine di scrittura in `db.py`: strip, rifiuto della
stringa vuota, tetto di lunghezza (128).

Il caso che rompe tutto è un chiamante che scrive `f"scraper-{run_id}"`: dopo una settimana ci sono
4.000 nomi distinti con 8 azioni ciascuno, tutti sotto ogni soglia di storia, quindi
`NON_VALUTABILE` ovunque e **zero alert** — mentre il supervisore fa 4.000 query al minuto in
crescita perpetua. Massimamente occupato e completamente cieco. Il guard `MAX_TRACKED_AGENTS` di
§2.1 lo trasforma in una singola segnalazione leggibile.

Normalizzare qui è sicuro e non ha il rovescio che ha reso stretta la normalizzazione di §4/R1:
`agent_name` è un'identità, non la descrizione di un oggetto su cui misurare il progresso.

**Un rename orfana i suoi alert:** `agent-v1` → `agent-v2` lascia l'alert vecchio senza possibilità
di recupero, e chiuderà per stantio dopo 7 giorni marcato "non risolto". È accettato in v1 e va
scritto in dashboard.

---

## 11. Rimandato alla v2, consapevolmente

Deriva da due revisioni multi-agente (soglie, poi completezza). Non entra nella v1 per ragioni di
**sequenza**, non di fatica: non si possono tarare soglie senza dati reali.

- **Baseline auto-calibranti per agente** — l'unica risposta vera al problema delle etichette libere.
  Attenzione al buco già trovato: un'etichetta **nuova** ha massimo storico 0, quindi un gate
  `≥ 2 × massimo_storico` diventa `≥ 0` e passa sempre. Serve `NON_VALUTABILE` per etichetta.
- **Confronti su *share* invece che su conteggi** — il volume per finestra non è stazionario.
- **Aggregazione cross-agent** — un default sbagliato condiviso da N agenti è invisibile a una
  chiave `(agent_name, rule)`.
- **Esenzioni configurabili per regola** — in v1 c'è solo dismiss/mute (§6).
- **Soppressione vera fra regole correlate** — in v1 solo `related_rule` e raggruppamento (§3.7).
- **Idempotenza sui log** — oggi un retry di trasporto scrive una riga duplicata e gonfia ogni
  soglia a conteggio. Mitigabile subito lato chiamante; la soluzione pulita è un `event_id` con
  indice unico.
- **Ritenzione e collegamento fra ricorrenze** — un problema che torna crea righe scollegate;
  un campo `recurrence_of` renderebbe la sua storia una query sola.
- **Ragionamento LLM** sopra le regole, quando le regole deterministiche funzionano.

### Limiti noti accettati in v1

- Rumore dentro l'identificatore di `action` legge come oggetto nuovo (§4/R1).
- Senza scomposizione dei token, l'output resta pesato ×1 e chi genera molto è sottostimato (§3.2).
- R3 ignora la fascia del modello: un batch da 300k su `economy` può scattare mentre un picco da
  60k su `frontier`, che costa una quindicina di volte tanto, riceve lo stesso trattamento.
  La correzione naturale in v2 è estendere il meccanismo già scelto — `MODEL_TIER_WEIGHTS`,
  non mappato ⇒ 1.0 — invece di aggiungerne uno nuovo.
- `K=3` non anticipa l'alert (la promozione resta a `PROMOTE_MIN_MINUTES`): estende la copertura
  ai cicli **lenti**. Va ricordato quando si tarerà, per non ottimizzare la variabile sbagliata.
- Un rename di agente orfana i suoi alert (§10).

---

## 12. Cosa ha trovato la revisione di completezza

Cinque lenti indipendenti (integrazione, esercizio, coerenza delle regole, qualità dei dati,
testabilità) su spec e codice v0. Sei difetti sono stati **verificati eseguendo il codice**:

| Verifica | Esito misurato |
|---|---|
| Timezone | `tzinfo` letto = `None` → `TypeError` confermato |
| `create_all()` su tabella esistente | colonna non aggiunta, indice non aggiunto |
| Parsing model ID | Bedrock → `'0'`, Vertex → `'anthropic/models/…'` |
| `(agent_name, id)` | **ridondante** — `ORDER BY id` usa già l'indice esistente senza temp b-tree |
| Aritmetica R1 | ciclo da 6 irrilevabile (36 azioni su 30); l'esempio dello spec non scattava |
| NULL parziali / negativi | `TypeError`; `output=-40000` ⇒ `effective=-100.000`, invisibile a R4 |

I sei errori di ragionamento che li hanno prodotti, perché è la parte che vale la pena ricordare:

1. **Due orologi che non si capiscono**, e una rete di sicurezza che nasconde proprio il bug che
   avrebbe dovuto rivelare.
2. **Due meccanismi che vogliono comandare la stessa cosa** — `create_all` e Alembic — perché avevo
   deciso *perché* serviva Alembic senza decidere *quando* sostituisce quello che c'era già.
3. **Prosa al posto di pseudocodice.** La prosa suona convincente anche quando nasconde un buco:
   è più facile ingannare se stessi scrivendo frasi che scrivendo numeri.
4. **Una cosa nuova senza una casa** — il terzo stato aggiunto alle regole e mai propagato allo
   schema né alla dashboard, perché ho progettato a strati senza mai rileggere la catena intera.
5. **Dati immaginati invece che veri** — la formula dei token e il parsing dei modelli funzionavano
   sugli esempi da manuale che avevo in testa, non sull'output reale degli SDK.
6. **Numeri giusti da soli, sbagliati insieme** — `PROMOTE_MIN_MINUTES` e
   `LOOP_CYCLE_WINDOW_MINUTES` erano uguali per coincidenza, e su quella coincidenza poggiava una
   delle difese principali.

Il filo comune: i pezzi singoli erano progettati bene, ma **il percorso completo con dati veri non
era mai stato simulato** — ed è lì che stavano tutti i buchi.

---

## 13. Costanti in `config.py`

Ogni valore va accompagnato in codice da un commento con il ragionamento e dal promemoria che
**non è tarato sui dati reali**.

**Invarianti da verificare all'import** (`assert` che fallisce rumorosamente, non silenziosamente):

```python
PROMOTE_MIN_MINUTES > max(LOOP_WINDOW_MINUTES, LOOP_CYCLE_WINDOW_MINUTES)
LOOP_SEQUENCE_LEN  >= LOOP_CYCLE_MAX_LEN * LOOP_CYCLE_K_NO_DETAIL
```

Il primo è ciò che fa funzionare la difesa anti-raffica di §2: una raffica deve uscire da **ogni**
finestra corta prima di poter essere promossa. Nella versione precedente i due valori erano
entrambi 10 — margine **zero**, per coincidenza, e nessuna riga lo diceva. Alzare
`LOOP_CYCLE_WINDOW_MINUTES` (esattamente ciò che §1 invita a fare quando arriveranno dati veri)
avrebbe distrutto la garanzia dell'altro senza un errore, senza un avviso.

### Ciclo di vita

| Costante | Valore | Perché |
|---|---|---|
| `SUPERVISOR_INTERVAL_SECONDS` | `60` | reattivo, carico trascurabile |
| `PROMOTE_MIN_MINUTES` | `15` | **>** la finestra corta più lunga (10), con margine reale |
| `PROMOTE_MIN_ROUNDS` | `3` | giri effettivamente osservati: chiude sospensione, riavvio e fermo del processo |
| `RESOLVE_MIN_HEALTHY_ACTIONS` | `20` | azioni pulite dopo `last_seen` per chiudere per recupero |
| `RESOLVE_STALE_DAYS` | `7` | oltre: chiusura per stantio, marcata diversamente |
| `SQLITE_BUSY_TIMEOUT_SECONDS` | `30.0` | le scritture concorrenti si accodano invece di fallire |
| `SUPERVISOR_ACTIVE_AGENT_HOURS` | `48` | oltre `max(finestre)`, così nessuna regola perde dati |
| `MAX_TRACKED_AGENTS` | `200` | oltre: alert di qualità dati, stop alla valutazione |
| `MAX_PLAUSIBLE_TOKENS` | `2_000_000` | sopra è un bug del chiamante, non spesa |
| `TOKEN_COST_WEIGHTS` | `{input 1.0, cache_read 0.1, cache_write 1.25, output 5.0}` | rapporti, non prezzi |

### R1 `loop`

| Costante | Valore | Perché |
|---|---|---|
| `LOOP_WINDOW_MINUTES` | `5` | finestra del rilevatore A |
| `LOOP_MIN_REPEATS` | `10` | ~2× il caso sano peggiore con dettagli |
| `LOOP_MIN_REPEATS_NO_DETAIL` | `40` | senza dettagli ogni oggetto collassa sulla stessa stringa |
| `LOOP_SEQUENCE_LEN` | `45` | **≥ 6 × 6** più margine: con 30 un ciclo da 6 era irrilevabile |
| `LOOP_CYCLE_WINDOW_MINUTES` | `10` | oltre è una routine lenta, non un blocco |
| `LOOP_CYCLE_MIN_LEN` / `MAX_LEN` | `2` / `6` | i cicli da 1 li prende A; sopra 6 il pattern è troppo raro |
| `LOOP_CYCLE_K_NO_DETAIL` | `6` | senza dettagli non si distingue "4 bug diversi" da "bloccato" |
| `LOOP_CYCLE_K_SAME_DETAIL` | `3` | stesso ciclo sugli stessi oggetti è quasi certezza |
| `LOOP_MIN_HISTORY` | `20` | sotto: `NON_VALUTABILE` |

### R2 `expensive_model`

| Costante | Valore | Perché |
|---|---|---|
| `EXPENSIVE_TRIVIAL_TOKENS` | `1000` | sopra, "banale" non è più difendibile |
| `EXPENSIVE_MIN_OCCURRENCES` | `20` | una è un giudizio, venti sono un'abitudine |
| `EXPENSIVE_WINDOW_HOURS` | `24` | un ciclo di lavoro intero |
| `EXPENSIVE_MIN_SHARE` | `0.60` | la maggioranza delle frontier dev'essere banale |
| `EXPENSIVE_MAX_ZERO_SHARE` | `0.20` | oltre: astensione per qualità dati |
| `MAX_UNMAPPED_SHARE` | `0.20` | oltre: `NON_VALUTABILE`, mai `OK` — vale anche per R4 |
| `MODEL_TIERS` | dict | `frontier`/`standard`/`economy`, pipeline di §4/R2. Non mappato ⇒ mai `frontier` |

### R3 `spend_anomaly`

| Costante | Valore | Perché |
|---|---|---|
| `SPEND_ABS_FLOOR_TOKENS` | `50_000` | in `effective_tokens`; sotto, uno scostamento non vale una segnalazione |
| `SPEND_MEDIAN_MULT` | `10` | |
| `SPEND_P95_MULT` | `3` | superare *anche* il p95 esclude la coda alta normale |
| `SPEND_MIN_HISTORY` | `30` | azioni valide, candidato escluso; sotto: `NON_VALUTABILE` |
| `SPEND_HISTORY_WINDOW` | `200` | ampiezza della baseline |
| `SPEND_PROMOTE_MIN_ANOMALIES` | `2` | una sola è un one-shot che non può auto-risolversi |
| `SPEND_ANOMALY_WINDOW_HOURS` | `24` | entro cui contare le anomalie |

### R4 `steady_waste`

| Costante | Valore | Perché |
|---|---|---|
| `HEAVY_TOKENS` | `25_000` | in `effective_tokens`; soglia della "chiamata grande" |
| `HEAVY_MIN_OCCURRENCES` | `15` | ramo a conteggio |
| `HEAVY_DAILY_TOKENS` | `500_000` | ramo aggregato: chiude la banda fra R2 e R4 |
| `HEAVY_WINDOW_HOURS` | `24` | allineata a R2 |
