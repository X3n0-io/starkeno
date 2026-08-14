# StarkEno v1 — Agente Supervisore: piano di implementazione

> **Per chi esegue:** usare `superpowers:executing-plans` o `superpowers:subagent-driven-development`.
> Ogni task ha il test che lo dimostra, e il test si scrive **prima**.
>
> Fonte di verità del design: `docs/superpowers/specs/2026-08-05-supervisor-agent-design.md`.
> Questo piano **corregge lo spec in dodici punti**, tutti elencati in §C con la misura che
> li ha prodotti. Dove piano e spec divergono, vince il piano.

---

## §A — Gli errori di ragionamento di §12, e come questo piano li evita

Prima di tutto il resto, perché sono la ragione per cui il piano è scritto così.

| # | L'errore | Come lo evita questo piano |
|---|---|---|
| 1 | **Due orologi che non si capiscono**, con una rete di sicurezza che nasconde il bug | Nessuna colonna `DateTime` nuda: le tre tabelle nuove usano `db.UTCDateTime`, già esistente e già testato nella v0. Task 1. Il test gira su SQLite vero, non su liste. |
| 2 | **Due meccanismi che comandano la stessa cosa** (`create_all` + Alembic) | Task 0 rimuove `create_all` **nello stesso commit** che introduce Alembic. Non esistono task in cui convivono. |
| 3 | **Prosa al posto di pseudocodice** | Ogni regola è in passi numerati eseguibili (§E). Nessuna frase del tipo "esiste un ciclo ripetuto K volte". |
| 4 | **Una cosa nuova senza una casa** | §D è una tabella di tracciabilità: ogni stato, campo ed esito nuovo ha una riga con *dove si salva → come esce dall'API → come si vede in dashboard*. Un task non è finito finché la sua riga non è piena. |
| 5 | **Dati immaginati invece che veri** | Ogni affermazione su SQL, datetime, parsing o soglie in questo piano è stata **eseguita**. §B riporta output, non ragionamenti. Tre difetti nuovi sono usciti proprio da lì. |
| 6 | **Numeri giusti da soli, sbagliati insieme** | §F.2 verifica **sei** invarianti fra costanti come `assert` all'import — non i due dichiarati in §13. Uno dei quattro nuovi ha **margine zero** ed era vero per coincidenza. |

Il filo comune di §12 — *«il percorso completo con dati veri non era mai stato simulato»* — è il
motivo per cui questo piano è stato scritto eseguendo codice prima di ogni sezione.

---

## §B — Cosa ho misurato eseguendo codice

Nessuna riga di questa tabella è un ragionamento. Gli script sono nello scratchpad di sessione.

### B.1 — Confermato: lo spec aveva ragione

| Verifica | Misura |
|---|---|
| Indice unico parziale su SQLite | `candidate`+`open` collidono → `IntegrityError`; `dismissed`/`resolved` convivono. Funziona come progettato |
| `ix_alerts_open` sul percorso critico | `SEARCH alerts USING **COVERING INDEX** ix_alerts_open` — la lookup non tocca mai la tabella |
| Nessun indice `(agent_name, id)` | `SEARCH ... USING INDEX ix_agent_actions_agent_name (agent_name=? AND rowid<?)` — riconfermato indipendentemente |
| `create_all()` prima di Alembic avvelena il DB | `alembic upgrade head` → `rc=1`, catena inapplicabile |
| Procedura di §3.0 su una **copia del `starkeno.db` reale** | `stamp 0001` + `upgrade head` → `rc=0`, 1 riga preservata, revisione `0002` |
| DB esistente-migrato vs DB nuovo | firme `sqlite_master` **identiche** |
| `effective_tokens`, i 5 rami | tutti e cinque danno il valore atteso |
| `5k in + 8k out ⇒ ~45k` (§9) | `45000` ✓ |
| `20k cache_write > 20k input` (§9) | `25000 > 20000` ✓ |
| `output=-40000` senza guardia | `effective = -100000`, sotto `HEAVY_TOKENS`: la riga sparisce da R4 ✓ |
| `MAX_TRACKED_AGENTS`, volumi | finestra 24h di un agente a 1 az/s = **86.400 righe** |

### B.2 — Smentito: difetti nuovi, non presenti in §12

| # | Difetto | Misura |
|---|---|---|
| **N1** | **§3.3 reintroduce il bug del fuso sulle tabelle nuove.** Il blocco di codice usa `Column(DateTime)` nudo | `tzinfo=None`; `now - first_seen` → `TypeError`. Inghiottito da §7 ⇒ **nessun alert viene mai promosso**, per sempre |
| **N2** | **La pipeline di normalizzazione dei modelli non produce il risultato che §4 dichiara** | `us.anthropic.claude-opus-4-5-20251101-v1:0` → `claude-opus-4-5-**20251101**-v1`, non `claude-opus-4-5-v1`. Il passo 5 toglie la data *finale*, ma dopo il passo 2 la data non è più finale |
| **N3** | **Il passo 4 distrugge ogni modello non-Anthropic con un punto di versione** | `gpt-5.2-turbo` → `2-turbo`; `gemini-2.5-pro` → `5-pro`; `mistral-7b-v0.3` → `3`. Tutti "non mappati" ⇒ oltre `MAX_UNMAPPED_SHARE` **R2 e R4 si astengono per sempre** |
| **N4** | **`LOOP_MIN_REPEATS_NO_DETAIL=40` non protegge nessuno** | Un indicizzatore a 3 az/s supera 40 in **13,3 s**; a 1 az/s in 40 s. §9 pretende «200 × `read_file` ⇒ nessun alert»: 200 ≥ 40, **il test fallirebbe** |
| **N5** | **Una corsa di categorie identiche crea un ciclo finto a ogni L** | `200 × read_file` → rilevatore B: `L=2 K=100`, `L=3 K=66`. §13 dice «i cicli da 1 li prende A», ma niente li esclude da B |
| **N6** | **Un agente sano a tre fasi viene accusato di loop** | `plan:`/`act:`/`observe:` × 8 → `K=8 ≥ K_NO_DETAIL=6` ⇒ **VIOLAZIONE**. §4 promette esattamente il contrario. La guardia sul parsing raddoppia la soglia, non la elimina |
| **N7** | **`LOOP_CYCLE_K_SAME_DETAIL=3` non è mai il vincolo attivo su un agente nuovo** | `LOOP_MIN_HISTORY=20 > LOOP_CYCLE_MAX_LEN × K_SAME_DETAIL = 18`. Il primo K osservabile per L=3 è 7, non 3. E l'esempio di §4 (ciclo × 4 = 12 azioni) è `NON_VALUTABILE`: **non fa scattare la propria regola** |
| **N8** | **`MAX_PLAUSIBLE_TOKENS` è applicato alla grandezza sbagliata** | La giustificazione è fisica («una chiamata non supera ~2M token») ma §3.2 lo applica a `effective_tokens`, che è **pesato**: 2M token con metà output → `effective = 6.000.000` ⇒ una riga valida scartata come bug |
| **N9** | **`RESOLVE_MIN_HEALTHY_ACTIONS` ha margine ZERO** — invariante non dichiarato | Serve `≥ max(EXPENSIVE_MIN_OCCURRENCES, HEAVY_MIN_OCCURRENCES, LOOP_MIN_HISTORY, LOOP_MIN_REPEATS) = 20`. Vale `20`. **Margine `+0`**, vero per coincidenza — identico all'errore 6 di §12. A 15, R2 e R1-B **si chiudono da soli** mentre il comportamento continua |
| **N10** | **§4/R4 promette una `SUM` in SQL che non è scrivibile** | `effective_tokens` e la fascia `frontier` sono entrambi calcoli Python. Misurato: ORM **1,173 s** vs `SUM` SQL **0,048 s** sulle stesse 86.400 righe (24×) |
| **N11** | **Il ramo aggregato di R4 scatta su UNA sola chiamata** | `HEAVY_DAILY_TOKENS=500k`, `MAX_PLAUSIBLE_TOKENS=2M`: una chiamata da 600k basta. R2 pretende 20 occorrenze e R3 ne pretende 2 proprio per non punire un fatto isolato. La regola si chiama `steady_waste` |
| **N12** | **Il guard di istanza singola di §3.5 non guarda niente su Windows** | `bind` semplice → `OSError(10048)` ✓. `bind` **con `SO_REUSEADDR`** (l'idioma riflesso di ogni server) → **riesce**: due supervisori girano insieme, in silenzio |
| **N13** | **La guardia sul percorso Windows di §4/R1 non cattura il percorso Windows.** Trovato eseguendo il test del task 3, non in revisione | §4 dice: *«la parte sinistra … non contiene separatori di percorso»*. In `C:\Users\<utente>\app.py` la sinistra è `C`, che separatori non ne ha: la guardia non scatta e l'azione diventa categoria `C`. Serve una **seconda** guardia (lettera sola + destra che inizia con un separatore). Senza, ogni azione di un agente su Windows collassa su `C` con dettagli distinti e **R1 si spegne del tutto** |

### B.3 — Non riprodotto: una motivazione dello spec è sbagliata (la decisione no)

§4/R3 giustifica `ORDER BY id DESC` con *«l'ordinamento per timestamp non è deterministico»*.
**Misurato su SQLite 3.49.1: entrambi stabili su 10 chiamate ripetute**, sia con che senza
`ix_actions_agent_time`. Non ho riprodotto la non-determinismo.

`ORDER BY id DESC` **resta la scelta giusta**, ma per l'altro motivo: è garantito da una chiave
unica invece che stabile per caso. La decisione non cambia, la motivazione nel codice sì.

### B.4 — Lavoro che lo spec chiede ma è già fatto

§3.1 descrive il bug del fuso come **vivo** e cita un `.replace(tzinfo=...)` in `api.py:38`.
Non è più vero: la v0 ha già `db.UTCDateTime`, e `api.py:46` porta il commento che lo dice.
Misurato: `tzinfo=UTC`, `now - row.timestamp` → `OK`, `journal_mode=wal`, `busy_timeout=30000`.

**Quindi non sono task:** il `TypeDecorator`, WAL, il busy timeout, il tiebreaker su `id`,
il pattern `get_session_factory()` lazy. Dello snippet di §8 resta **solo** la rimozione di
`create_all()`. Sono cinque voci in meno.

---

## §C — Le dodici correzioni allo spec, e perché

> **Regola 7 del brief: non riaprire decisioni chiuse senza dirlo.** Questa sezione esiste per
> quello. Le tre decisioni dichiarate intoccabili — normalizzazione stretta dei dettagli,
> Alembic adesso, R3/R4 su token pesati mentre R2 usa i totali — **non sono toccate da nessuna
> delle dodici**.

**Correzioni di difetti verificati** (nessuna scelta in gioco, lo spec è semplicemente sbagliato):

| | Correzione | Da |
|---|---|---|
| C1 | `alerts`/`rule_status`/`supervisor_state`: tutte le colonne temporali usano `db.UTCDateTime` | N1 |
| C2 | Pipeline modelli riordinata + due guardie: `^(us\|eu\|apac)\.anthropic\.` e `-v\d+$`, e **niente split sull'ultimo `.`** | N2, N3 |
| C3 | `MAX_PLAUSIBLE_TOKENS` si applica a `tokens_used`, non a `effective_tokens` | N8 |
| C4 | Rilevatore B: un blocco di L categorie tutte uguali è un ciclo da 1 ⇒ **saltato** (è affare di A) | N5 |
| C5 | `RESOLVE_MIN_HEALTHY_ACTIONS ≥ max(...)` diventa il 3° `assert`; `SUPERVISOR_ACTIVE_AGENT_HOURS ≥ max(finestre)` il 4° | N9 |
| C6 | Guard di istanza singola: `bind` **senza** `SO_REUSEADDR`, con il test che prova il fallimento del secondo | N12 |
| C7 | R2/R4 valutate su aggregati SQL, non caricando la finestra. `db.py` non restituisce mai oggetti ORM per le regole | N10 |
| C13 | `parse_action` ha **tre** guardie, non due: si aggiunge «sinistra è una lettera sola **e** destra inizia con un separatore» per l'unità Windows | N13 |

**Decisioni che cambiano il comportamento** (queste vanno approvate):

| | Decisione | Perché |
|---|---|---|
| **C8** | **Senza dettaglio, R1 si astiene** invece di usare una soglia più alta. Spariscono `LOOP_MIN_REPEATS_NO_DETAIL` e `LOOP_CYCLE_K_NO_DETAIL`; nasce `LOOP_CYCLE_K_MIXED_DETAIL=6` per il caso *misto* | N4, N6. Senza dettaglio, «100 oggetti diversi» e «lo stesso oggetto 100 volte» sono **la stessa stringa**: l'informazione non c'è, e nessuna soglia la crea. Astenersi è ciò che §3.6 prescrive per «dati inutilizzabili», e rende reale l'incentivo di §5 |
| **C9** | `LOOP_MIN_HISTORY` è misurato sulle azioni dell'agente **dentro `SUPERVISOR_ACTIVE_AGENT_HOURS`**, non sul totale storico | N7. Lo spec non lo dice, e la scelta cambia quando `K_SAME_DETAIL=3` è raggiungibile. Due implementatori sceglierebbero diversamente |
| **C10** | Il p95 di R3 è **nearest-rank** (`s[ceil(0.95·n)-1]`) | A n=30 nearest-rank e interpolazione lineare divergono del **44%** (misurato); a n≥50 dello 0,2%. «Il 95° percentile» non è una definizione |
| **C11** | Nuova costante `HEAVY_MIN_ACTIONS_FOR_SUM = 5` sul ramo aggregato di R4 | N11. La regola si chiama `steady_waste`: una chiamata sola non è *steady*, ed è già il mestiere di R3 (che infatti pretende 2 anomalie) |
| **C12** | R1 combina i due rilevatori con precedenza `VIOLAZIONE > NON_VALUTABILE > OK` | Lo pseudocodice non dice come combinarli. Senza la precedenza, R1 direbbe `OK` mentre metà delle prove era inutilizzabile — il fallimento di §1 |

**Minore, misurato:** `alerts.agent_name` non ha `index=True`. I due indici parziali coprono
entrambe le query (`SEARCH ... USING COVERING INDEX ix_alerts_open` e
`SEARCH ... USING INDEX ix_alerts_one_live`); `ix_alerts_agent_name` non viene mai scelto.

---

## §D — Tracciabilità: ogni cosa nuova arriva fino in fondo

> **Regola 4 del brief.** Un task non è finito finché la sua riga non è completa.
> Un terzo stato che vive solo in `rules.py` è invisibile all'utente.

| Cosa nuova | Dove si salva | Come esce dall'API | Come si vede in dashboard | Task |
|---|---|---|---|---|
| `NON_VALUTABILE` | `rule_status.state='non_valutabile'` + `reason` | `GET /api/rule-status` | badge grigio «in calibrazione» sulla riga agente, `reason` nel tooltip | 8, 11, 12 |
| Regola che solleva | `rule_status.state='error'` + `reason`=messaggio | `GET /api/rule-status` | badge **rosso** «regola in errore» — deve essere visivamente diverso da `ok` | 8, 11, 12 |
| `candidate` | `alerts.status='candidate'` | `GET /api/alerts?status=candidate` (nel default) | badge giallo, sezione «in osservazione», **nessun** warning all'agente | 8, 11, 12 |
| `open` | `alerts.status='open'` | `GET /api/alerts` (default) | badge rosso, in cima | 8, 11, 12 |
| `resolved` + `resolution='recovery'` | `alerts.resolution` | `?status=resolved` | «rientrato» verde | 8, 11, 12 |
| `resolved` + `resolution='stale'` | `alerts.resolution` | `?status=resolved` | «archiviato per inattività» grigio — **distinto** da recovery (§9) | 8, 11, 12 |
| `dismissed` + `user_note` | `alerts.status`, `alerts.user_note` | `POST /api/alerts/{id}/dismiss` | pulsante + campo nota obbligatorio; poi in «ignorati» con la nota visibile | 11, 12 |
| `muted_until` | `alerts.muted_until` | `POST /api/alerts/{id}/mute` | icona muto + scadenza | 11, 12 |
| `effective_tokens` | **non persistito** (i pesi devono restare tarabili, §1) | in `evidence` di ogni alert; colonna in `/api/agents` | colonna «Token pesati» accanto ai grezzi (§6) | 5, 11, 12 |
| Flag qualità dati (`componenti_parziali`, `componente_negativo`, `somma_supera_totale`, `token_implausibili`) | conteggiati per finestra; oltre soglia → `rule_status.reason` | dentro `reason` di `/api/rule-status` | testo del tooltip: «12% delle righe ha componenti parziali» | 5, 8, 11, 12 |
| `related_rule` (§3.7) | dentro `alerts.evidence` (JSON) | `evidence` deserializzato | gli alert **raggruppati per agente**, i correlati rientrati sotto il `loop` | 8, 11, 12 |
| `data_quality` — **5° valore di `alerts.rule`** (`MAX_TRACKED_AGENTS`, §2.1) | `alerts.rule='data_quality'` | come gli altri alert | riga speciale in cima, fuori dal raggruppamento per agente | 8, 11, 12 |
| Heartbeat | `supervisor_state` (riga id=1) | `GET /api/supervisor/status` | riga di stato «Supervisore: ultimo giro N min fa», **rossa oltre 3× l'intervallo** | 9, 11, 12 |
| Watermark R3 | `supervisor_state`, colonna nuova `last_evaluated_action_id` per agente → **tabella `agent_watermark`** | non esposto (interno) | non mostrato | 1, 7, 8 |
| Rename orfana gli alert (§10) | — | — | nota fissa in fondo alla sezione alert | 12 |

---

## §E — Le regole, in passi numerati

### E.0 — Primitive pure (`rules.py`)

```
normalizza_modello(m) -> str
  1. s = m.lower()
  2. s = sub(r":\d+$", "", s)                       # ':0' finale di Bedrock
  3. s = s.rsplit("/", 1)[-1]                       # dopo l'ULTIMO '/'  (Vertex, OpenRouter)
  4. s = sub(r"^(us|eu|apac)\.anthropic\.", "", s)   # SOLO il prefisso regionale Bedrock
  5. s = sub(r"-v\d+$", "", s)                       # '-v1' finale di Bedrock
  6. s = sub(r"-\d{8}$", "", s)                      # data finale
  # NIENTE split sull'ultimo '.': distruggerebbe gpt-5.2-turbo, gemini-2.5-pro  (N3)
```

Verificato su tutti e sette gli ID reali: Bedrock, Vertex, OpenRouter, data diretta, già pulito,
e due non-Anthropic che ora sopravvivono.

```
fascia(m) -> "frontier" | "standard" | "economy" | None
  None (non mappato) non è MAI frontier, ed è escluso da numeratore E denominatore.
```

```
parse_action(a) -> (categoria, dettaglio|None)
  1. se ':' non è in a                                   -> (a, None)
  2. sinistra, destra = a.split(':', 1)
  3. se sinistra == ""  oppure '/' in sinistra oppure '\' in sinistra -> (a, None)
  4. se destra.strip() == ""                             -> (a, None)
  5. d = destra.strip(); d = d.split('?')[0]; d = d.split('#')[0]
     d = d.replace('\\','/'); d = d.lower()
  6. -> (sinistra, d)
  # Le cifre NON si toccano: azzerarle rompe i job batch (decisione chiusa, §4)
```

```
effective_tokens(tokens_used, cache_read, cache_write, output) -> (valore, flag|None)
  1. se tutti e tre i componenti sono NULL          -> (tokens_used, None)
  2. se ALMENO UNO è NULL                           -> (tokens_used, "componenti_parziali")
  3. se uno qualsiasi < 0, o tokens_used < 0        -> (tokens_used, "componente_negativo")
  4. se cr+cw+ou > tokens_used                      -> (tokens_used, "somma_supera_totale")
  5. input = tokens_used - cr - cw - ou
     -> (input*1.0 + cr*0.1 + cw*1.25 + ou*5.0, None)
  # il tetto MAX_PLAUSIBLE_TOKENS si applica a tokens_used, NON al valore pesato  (N8)
```

Questa formula esiste **anche in SQL** (`db.py` la genera da `TOKEN_COST_WEIGHTS`), perché R2 e
R4 aggregano lato database (C7). Il test differenziale di §E.5 lo copre.

```
percentile_nearest_rank(valori_ordinati, q) -> valore
  k = max(1, ceil(q * n));  -> s[k-1]
```

### E.1 — R1 `loop`

**Rilevatore A — ripetizione identica** (finestra `LOOP_WINDOW_MINUTES`)

```
1. considera SOLO le azioni con dettaglio != None
2. se non ce n'è nessuna                       -> A = ASTENUTO ("nessun dettaglio")
3. conta le occorrenze di ogni (categoria, dettaglio)
4. se un conteggio >= LOOP_MIN_REPEATS         -> A = VIOLAZIONE
5. altrimenti                                  -> A = OK
```

**Rilevatore B — ciclo ripetuto** (ultime `LOOP_SEQUENCE_LEN` azioni, `ORDER BY id DESC` poi invertite)

```
1. cats = categorie della sequenza;  dets = dettagli della sequenza;  n = len(cats)
2. per L da LOOP_CYCLE_MIN_LEN a LOOP_CYCLE_MAX_LEN:
3.    block = cats[n-L:]
4.    se len(set(block)) < 2:  continua        # ciclo da 1 travestito: è affare di A   (C4)
5.    K = 1
6.    finché (K+1)*L <= n e cats[n-(K+1)*L : n-K*L] == block:  K += 1
7.    se K < 2: continua
8.    se le K*L azioni NON stanno in LOOP_CYCLE_WINDOW_MINUTES: continua
9.    per ogni posizione i in 0..L-1:
         vals = i-esimo dettaglio di ciascuna delle K ripetizioni
         tutti None                       -> "assente"
         nessun None e len(set)==1        -> "identica"
         nessun None e len(set)==K        -> "distinta"
         altrimenti                       -> "misto"
10.   se TUTTE le posizioni sono "distinta"   -> B = OK           (sta avanzando)
11.   se TUTTE le posizioni sono "assente"    -> B = ASTENUTO     (C8)
12.   se TUTTE le posizioni sono "identica"   -> K_req = LOOP_CYCLE_K_SAME_DETAIL
13.   altrimenti                              -> K_req = LOOP_CYCLE_K_MIXED_DETAIL
14.   se K >= K_req  -> B = VIOLAZIONE   altrimenti  B = OK
15.   ESCI dal ciclo su L (la prima L che combacia vince)
16. nessuna L combacia -> B = OK
```

**Combinazione** (C12) e storia:

```
0. se le azioni dell'agente dentro SUPERVISOR_ACTIVE_AGENT_HOURS < LOOP_MIN_HISTORY  (C9)
        -> NON_VALUTABILE ("storia insufficiente: N azioni")
1. se A == VIOLAZIONE oppure B == VIOLAZIONE  -> VIOLAZIONE
2. se A == ASTENUTO   oppure B == ASTENUTO    -> NON_VALUTABILE ("azioni senza dettaglio: R1 non
                                                  può distinguere progresso da ripetizione")
3. altrimenti                                 -> OK
```

Esiti misurati con questo algoritmo:

| Scenario | Prima (spec letterale) | Dopo |
|---|---|---|
| `read:app.py/edit:app.py/test:tests/` × 8 | VIOLAZIONE | **VIOLAZIONE** ✓ |
| batch `fetch/validate/save:user_1..100` | OK | **OK** ✓ |
| 200 × `read_file` (nudo) | **VIOLAZIONE** ✗ | **NON_VALUTABILE** ✓ |
| `plan:`/`act:`/`observe:` × 8 | **VIOLAZIONE** ✗ | **NON_VALUTABILE** ✓ |
| `C:\Users\<utente>\...` × 30 | OK | **OK** ✓ |
| sequenza sana a 9 passi × 3 | OK | **OK** ✓ |

### E.2 — R2 `expensive_model` (misura: **token totali**, decisione chiusa)

```
1. nomi = SELECT DISTINCT model_used  nella finestra EXPENSIVE_WINDOW_HOURS   (1 query, misurata: pochissimi nomi)
2. mappa ogni nome con normalizza_modello + fascia   (in Python, puro)
3. se quota_non_mappati > MAX_UNMAPPED_SHARE
       -> NON_VALUTABILE ("modelli non riconosciuti: <lista testuale>")
4. frontier_raw = i nomi grezzi la cui fascia è "frontier"
5. UNA query SQL con frontier_raw:
       tot_frontier, banali (tokens_used <= EXPENSIVE_TRIVIAL_TOKENS), zero (effective <= 0),
       e i conteggi dei flag di qualità
6. se tot_frontier == 0                       -> NON_VALUTABILE ("nessuna chiamata frontier")
7. se zero/tot_frontier > EXPENSIVE_MAX_ZERO_SHARE -> NON_VALUTABILE ("<X>% righe a token 0")
8. escludi le righe a effective <= 0 da numeratore E denominatore
9. VIOLAZIONE se  banali >= EXPENSIVE_MIN_OCCURRENCES  E  banali/tot_frontier >= EXPENSIVE_MIN_SHARE
```

Aritmetica verificata: la regola scatta con **20–33** chiamate frontier in 24h; a 34 la share
scende a 0,59 e tace. È una proprietà voluta (misura un'*abitudine*), va scritta nel commento.

### E.3 — R3 `spend_anomaly` (misura: `effective_tokens`)

```
1. wm = watermark dell'agente.  PRIMO AVVIO: wm = MAX(id) corrente, NON 0.       (nuovo)
      Con wm=0 il supervisore rivaluta tutto lo storico e apre oggi alert su anomalie di mesi fa.
2. candidati = azioni con id > wm, ORDER BY id ASC
3. per ogni candidato c:
4.    se effective(c) <= 0: salta
5.    baseline = SELECT ... WHERE agent=? AND id < c.id AND <effective > 0>
                 ORDER BY id DESC LIMIT SPEND_HISTORY_WINDOW
         # l'esclusione del candidato è NELLA QUERY (id < c.id), non nel chiamante  (§4)
         # ORDER BY id: garantito da chiave unica, non stabile per caso            (B.3)
6.    se len(baseline) < SPEND_MIN_HISTORY -> NON_VALUTABILE ("baseline di N azioni"); esci
7.    med = mediana(baseline); p95 = percentile_nearest_rank(baseline, 0.95)       (C10)
8.    c è anomalo se TUTTE E TRE:
         effective(c) >= SPEND_ABS_FLOOR_TOKENS
         effective(c) >= SPEND_MEDIAN_MULT * med
         effective(c) >= SPEND_P95_MULT   * p95
9. anomalie = quante in SPEND_ANOMALY_WINDOW_HOURS
10. VIOLAZIONE se anomalie >= SPEND_PROMOTE_MIN_ANOMALIES
11. wm = max(id dei candidati esaminati)     <- scritto SOLO a fine giro riuscito
```

Soglia effettiva misurata: agente leggero → vince il floor (50k); agente medio o pesante →
vince `10 × mediana` (256k e 912k). Con `SPEND_PROMOTE_MIN_ANOMALIES=2`, R3 parlerà **raramente**.
Coerente con §1, va scritto per non scambiarlo per un guasto.

**Recupero di R3** (§3.7 non lo chiude): una riga passata è immutabile e non guarisce mai.
Definizione: *nessuna nuova anomalia fra le azioni dopo `last_seen`*, con la baseline presa
**come al passo 5** (le 200 precedenti globali), non solo dalla finestra ristretta.

### E.4 — R4 `steady_waste` (misura: `effective_tokens`)

```
1-4. identici a E.2 (nomi distinti, mappatura, guardia MAX_UNMAPPED_SHARE, frontier_raw)
5. UNA query SQL: n_frontier, n_heavy (effective >= HEAVY_TOKENS), somma_effective
6. ramo a conteggio : n_heavy >= HEAVY_MIN_OCCURRENCES
7. ramo aggregato   : n_frontier >= HEAVY_MIN_ACTIONS_FOR_SUM        <- nuovo   (C11)
                      E somma_effective >= HEAVY_DAILY_TOKENS
8. VIOLAZIONE se 6 oppure 7
```

Tabella di §4/R4 riverificata con questi passi: `15×60k` → conteggio ✓ · `100×8k` → aggregato ✓ ·
`5×100k` → aggregato ✓ · **`1×600k` → tace** (era: aggregato).

### E.5 — Ciclo di vita e riconciliazione (`supervisor.py`)

```
per ogni (agente, regola):
 1. esito, motivo, evidenza = valuta()            # dentro il proprio try/except
 2. se ECCEZIONE: rule_status='error'+messaggio; NESSUN effetto su alerts; rules_failed += 1
 3. se NON_VALUTABILE:
      rule_status='non_valutabile'+motivo
      CONGELA: non promuovere, non risolvere, non cancellare il candidate, NON toccare last_seen
 4. se VIOLAZIONE:
      rule_status='violating'
      last_seen_nuovo = timestamp dell'azione più recente che ha contribuito   <- tempo AZIONE
      a = get_live_alert(agente, regola)
      se a è None:  INSERT candidate (first_seen=last_seen_nuovo, episodes=1, observed_rounds=1)
      altrimenti:   observed_rounds += 1; last_seen = last_seen_nuovo
                    se a.status == 'resolved' nel giro precedente: episodes += 1
                    se a.status == 'candidate'
                       E now - a.first_seen >= PROMOTE_MIN_MINUTES
                       E a.observed_rounds >= PROMOTE_MIN_ROUNDS:      -> status = 'open'
 5. se OK:
      rule_status='ok'
      a = get_live_alert(agente, regola)
      se a è None: niente
      se a.status == 'candidate':  DELETE      (raffica auto-risolta)
      se a.status == 'open':
         n = azioni dell'agente con timestamp > a.last_seen
         se len(n) >= RESOLVE_MIN_HEALTHY_ACTIONS:
            esito_ristretto = rivaluta la regola SOLO su n
            se esito_ristretto == OK -> resolved, resolution='recovery', resolved_at=now
            se NON_VALUTABILE        -> aspetta (non chiude)
 6. stantio, separato dalle regole:
      se l'agente non ha azioni da RESOLVE_STALE_DAYS -> resolved, resolution='stale'
      SALTA questo passo per un giro se now - heartbeat.last_run_at > 3 * INTERVAL
```

L'`INSERT` del passo 4 va dentro `try/except IntegrityError` **con `session.rollback()` prima
del ritentativo** (§8): senza, `PendingRollbackError` uccide il giro.

**`episodes` conta episodi distinti**, mai i giri: incrementato solo sulla transizione
non-violazione → violazione.

---

## §F — I task

### Task 0 — Alembic è l'unica autorità sullo schema

> **Primo, e non spostabile.** `create_all()` non altera tabelle esistenti: ogni modifica
> successiva sarebbe ignorata in silenzio. Verificato in B.1.

**File:** `requirements.txt`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_v0_baseline.py`,
`starkeno/db.py`, `starkeno/schema_version.py`, `tests/test_migrations.py`, `.gitignore`

1. `alembic` in `requirements.txt`; `alembic init migrations`; `env.py` legge l'URL da
   `config.DB_PATH`, `render_as_batch=True`.
2. `0001_v0_baseline` — ricrea **esattamente** lo schema v0 (`agent_actions` +
   `ix_agent_actions_agent_name`). Serve ai DB nuovi ed è il punto di `stamp` per quelli esistenti.
3. **Rimuovere `Base.metadata.create_all(engine)` da `make_session_factory`** (`db.py:70`),
   nello stesso commit.
4. `schema_version.check_or_die(engine)`: confronta con `head` ed esce con messaggio esplicito.
   Chiamata all'avvio di `mcp_server`, `api`, `supervisor` — **unica eccezione a §7**, deve
   fallire rumorosamente.
5. `tests/conftest.py`: fixture `db` che chiama `Base.metadata.create_all` su un engine `tmp_path`.
   I test non passano mai da Alembic né toccano `DB_PATH`.
6. `.gitignore`: già copre `*.db-wal` / `*.db-shm` ✓.

**Procedura di primo avvio** (verificata su una copia del `starkeno.db` reale, entrambi `rc=0`):

| Situazione | Comandi |
|---|---|
| `starkeno.db` esiste | `alembic stamp 0001` poi `alembic upgrade head` |
| DB nuovo | `alembic upgrade head` |

**Test:** DB con solo schema v0 → `stamp`+`upgrade` → `PRAGMA table_info`/`index_list` confermano;
un DB creato da `create_all` senza `alembic_version` → `upgrade head` **fallisce** (rc≠0);
`make_session_factory` su un percorso inesistente **non crea** il file; le firme `sqlite_master`
dei due percorsi coincidono.

---

### Task 1 — Schema v1

**File:** `migrations/versions/0002_token_breakdown.py`, `0003_supervisor_tables.py`,
`starkeno/db.py`, `tests/test_migrations.py`

`0002` — su `agent_actions`: `cache_read_tokens`, `cache_write_tokens`, `output_tokens`
(tutte `Integer, nullable=True`) + `Index("ix_actions_agent_time", "agent_name", "timestamp")`.

`0003` — le tre tabelle di §3.3 **più** `agent_watermark(agent_name PK, last_evaluated_action_id)`,
con questi scostamenti da §3.3:

- **ogni colonna temporale è `db.UTCDateTime`**, mai `DateTime` nudo (C1 — N1)
- `alerts.agent_name` **senza** `index=True` (misurato ridondante)
- `alerts.rule` ammette **cinque** valori: le quattro regole + `data_quality`
- i due indici parziali di §3.4, con `sqlite_where` (verificato funzionante in Alembic)

**Test:**
- `stamp 0001` → `upgrade head` su un DB popolato: colonne, indici e tabelle presenti, **righe preservate**
- **il test che nessuna lista scritta a mano può dare:** scrivere un `Alert` via `db.py` su SQLite
  vero, rileggerlo, e calcolare `datetime.now(timezone.utc) - alert.first_seen` — deve **non**
  sollevare `TypeError`. Con `Column(DateTime)` nudo questo test fallisce, ed è l'unico modo di vederlo
- due `candidate` sulla stessa `(agent, rule)` → `IntegrityError`; `dismissed` convive
- `resolved_at = None` sopravvive al round-trip

---

### Task 2 — `config.py`: costanti e i **sei** assert

**File:** `starkeno/config.py`, `tests/test_config_invariants.py`

Tutte le costanti di §13 con il commento del ragionamento e il promemoria «**non tarata sui dati
reali**», più: `LOOP_CYCLE_K_MIXED_DETAIL=6` (C8), `HEAVY_MIN_ACTIONS_FOR_SUM=5` (C11).
Rimosse: `LOOP_MIN_REPEATS_NO_DETAIL`, `LOOP_CYCLE_K_NO_DETAIL` (C8).

```python
# Invarianti verificati all'IMPORT. Erano commenti; erano veri per coincidenza.
assert PROMOTE_MIN_MINUTES > max(LOOP_WINDOW_MINUTES, LOOP_CYCLE_WINDOW_MINUTES)      # margine +5
assert LOOP_SEQUENCE_LEN >= LOOP_CYCLE_MAX_LEN * LOOP_CYCLE_K_MIXED_DETAIL            # margine +9
assert SUPERVISOR_ACTIVE_AGENT_HOURS >= max(EXPENSIVE_WINDOW_HOURS, HEAVY_WINDOW_HOURS,
                                            SPEND_ANOMALY_WINDOW_HOURS)               # margine +24
assert RESOLVE_MIN_HEALTHY_ACTIONS >= max(EXPENSIVE_MIN_OCCURRENCES, HEAVY_MIN_OCCURRENCES,
                                          LOOP_MIN_HISTORY, LOOP_MIN_REPEATS)         # MARGINE +0  (N9)
assert RESOLVE_STALE_DAYS * 24 > SUPERVISOR_ACTIVE_AGENT_HOURS                        # margine +120
assert PROMOTE_MIN_ROUNDS * SUPERVISOR_INTERVAL_SECONDS <= PROMOTE_MIN_MINUTES * 60   # margine -720
```

Il quarto ha **margine zero** e va commentato per esteso: sotto 20, un alert R2 o R1-B si chiude
da solo su una finestra troppo piccola per poter mostrare una violazione — il lampeggio che §3.7
esiste per impedire, spostato dal tempo al conteggio.

**Test:** per ciascun assert, un test che lo forza a fallire (monkeypatch della costante +
`importlib.reload`) e verifica che `ImportError`/`AssertionError` **arrivi**.

---

### Task 3 — `rules.py`: primitive pure

**File:** `starkeno/rules.py`, `tests/test_rules_primitives.py` · **Passi:** §E.0

`rules.py` **non importa SQLAlchemy, non tocca il DB, non legge l'orologio.**

**Test:**
- **normalizzazione modelli — tabella di ID reali:** Bedrock `us.anthropic...-v1:0`, Vertex
  `publishers/...`, OpenRouter `anthropic/...`, data diretta, `gpt-5.2-turbo`,
  `gemini-2.5-pro`, uno non mappato. Con la pipeline di §4 letterale i primi due e i due
  non-Anthropic **falliscono** (N2, N3)
- **`parse_action`:** `read_file:src/app.py` · `plan:` → categoria nuda · `C:\Users\<utente>\...` →
  categoria nuda, **non** categoria `C` · query string e fragment rimossi · **le cifre restano**
  (`user_1` ≠ `user_2`)
- **`effective_tokens`, i 5 rami** + i due esempi numerici di §9 (45000, `25000 > 20000`)
- **`output = -40000`** → `60000` col flag, non `-100000`
- **`tokens_used = 2M` con metà output** → **non** scartato come implausibile (N8)
- **percentile:** nearest-rank a n=30, 50, 200; il test dichiara il metodo scelto

---

### Task 4 — `rules.py`: R1 `loop`

**File:** `starkeno/rules.py`, `tests/test_rules_r1.py` · **Passi:** §E.1

**Test** (liste a mano, `now` come parametro, **config iniettata con valori diversi dai default**):

| Caso | Atteso |
|---|---|
| `read:app.py/edit:app.py/test:tests/` × 8 | VIOLAZIONE (B, `K_SAME_DETAIL`) |
| batch sano `fetch/validate/save:user_1..100` | **OK** — dettagli distinti per posizione |
| **200 × `read_file` nudo** | **NON_VALUTABILE**, non OK e non VIOLAZIONE (N4, C8) |
| **`plan:`/`act:`/`observe:` × 8** (≥ `LOOP_MIN_HISTORY`) | **NON_VALUTABILE** (N6) |
| `C:\Users\<utente>\...` × 30 | OK, categoria nuda |
| sequenza sana a 9 passi × 3 | OK |
| ciclo da 6 × 6 = 36 azioni | rilevabile (protegge l'invariante 2) |
| ciclo con **una** posizione a dettaglio distinto | `K_MIXED_DETAIL`, non `K_SAME_DETAIL` |
| storia < `LOOP_MIN_HISTORY` | NON_VALUTABILE, **mai** OK |

Il caso `plan:`/`act:`/`observe:` va scritto con **almeno `LOOP_MIN_HISTORY` azioni**: la versione
di §9 (× 3 = 9 azioni) passa per storia insufficiente e non esercita mai il parsing.

---

### Task 5 — `rules.py`: R2 e R4

**File:** `starkeno/rules.py`, `tests/test_rules_r2_r4.py` · **Passi:** §E.2, §E.4

Entrambe ricevono una `WindowStats` già aggregata (C7), quindi restano pure e testabili su
struct costruite a mano.

**Test:** confini esatti (19/20 occorrenze, share 0,59/0,60/0,61) · finestra 100% non mappata →
**NON_VALUTABILE, mai OK** · `EXPENSIVE_MAX_ZERO_SHARE` superata → astensione · zero frontier →
astensione, non OK · R4: la tabella di §E.4 riga per riga, **inclusa `1 × 600k` → tace** (C11) ·
`15 × 25k = 375k` scatta prima di `500k`.

---

### Task 6 — `rules.py`: R3

**File:** `starkeno/rules.py`, `tests/test_rules_r3.py` · **Passi:** §E.3

**Test:** le tre condizioni sono congiuntive (tre test, ciascuno con una sola condizione mancante
⇒ nessuna anomalia) · mediana e p95 non risentono dell'anomalia stessa · baseline < 30 ⇒
NON_VALUTABILE · una sola anomalia ⇒ nessuna violazione (`SPEND_PROMOTE_MIN_ANOMALIES=2`) ·
il metodo del percentile è quello dichiarato.

---

### Task 7 — `db.py`: caricamento e aggregazione

**File:** `starkeno/db.py`, `tests/test_db_supervisor.py`

Le funzioni di §2.2, con questi scostamenti misurati:

- **niente oggetti ORM per le regole.** `ActionRecord` è un `dataclass` leggero costruito da
  `db.py`, con `timestamp` aware-UTC ed `effective_tokens` già calcolato. Misurato: ORM 1,173 s
  vs 0,146 s su 86.400 righe
- `get_window_stats(session, agent, since, frontier_raw_names, weights, heavy_tokens,
  trivial_tokens) -> WindowStats` — **una** query con l'espressione `CASE` generata da
  `TOKEN_COST_WEIGHTS`. Misurato **0,048 s** sulla stessa finestra, con
  `SEARCH ... USING INDEX ix_actions_agent_time`
- le soglie sono **parametri**, non lette da `config`: altrimenti l'iniezione della config di §9
  non arriva fino al SQL
- `get_distinct_models(session, agent, since)` — misurato: pochi nomi, costo trascurabile
- `get_spend_baseline(session, agent, before_id, limit)` — `WHERE id < before_id`, l'esclusione
  del candidato è **nella query**. Misurato: 40 baseline da 200 righe in 0,0116 s
- `get_recent_actions` **resta ordinata per `timestamp`** (query della dashboard); accanto,
  `get_last_actions_by_id` per R3/R1-B. Commento in `db.py` su chi le usa e perché differiscono

**Test:**
- **il test differenziale che tiene insieme le due definizioni:** la `CASE` SQL e
  `rules.effective_tokens` devono coincidere sui 5 rami **e** su ≥1000 input casuali con NULL,
  negativi e somme eccedenti. Verificato: **0 divergenze su 20.000**. Senza questo test, le due
  definizioni divergono al primo cambio di pesi e nessuno se ne accorge
- baseline R3 su **SQLite vero**: 201 azioni con collisioni di timestamp ⇒ 200 righe, **senza
  l'id più alto**, identica su 8 chiamate ripetute
- `get_window_stats` con soglie diverse dai default ⇒ risultati diversi (prova che il parametro arriva)

---

### Task 8 — `supervisor.py`: riconciliazione

**File:** `starkeno/supervisor.py`, `tests/test_supervisor_lifecycle.py` · **Passi:** §E.5

`run_once(session, now: datetime, config) -> RoundResult`. **Non importa SQLAlchemy**: passa
solo per `db.py`. Include il guard `MAX_TRACKED_AGENTS` → alert `rule='data_quality'`.

**Test** (chiamando `run_once` più volte facendo avanzare `now` a mano, con i valori di
**produzione** delle costanti — mai azzerando `PROMOTE_MIN_MINUTES`):

- promozione: **entrambe** le condizioni. Un test in cui basta il tempo (1 solo giro) **non
  promuove**; un test in cui bastano i giri (3 giri in 3 minuti) **non promuove**
- `candidate` → cancellato quando la violazione sparisce prima della promozione
- **agente cron**: gira ogni ora e fallisce sempre ⇒ **un solo `open`**, `episodes` non esplode
- `NON_VALUTABILE` congela: un `open` **non** si chiude e `last_seen` **non** avanza
- recupero, quattro test separati (R1, R2, R3, R4), ciascuno con la finestra ristretta
- **il test che protegge il margine zero (N9):** un R2 aperto con l'agente che **continua** a
  violare, e `RESOLVE_MIN_HEALTHY_ACTIONS` azioni dopo `last_seen` ⇒ **resta aperto**
- stantio: saltato per un giro dopo un buco di heartbeat > `3 × INTERVAL`
- una regola che solleva ⇒ `rule_status='error'`, `alerts` **intatto**, le altre tre valutate
- upsert: seconda violazione aggiorna; `IntegrityError` forzato ⇒ il ritentativo riesce dopo il rollback
- `related_rule` scritto in `evidence` quando esiste un `loop` vivo che contiene la finestra

---

### Task 9 — `supervisor.py`: loop, heartbeat, istanza singola

**File:** `starkeno/supervisor.py`, `scripts/start_starkeno.ps1`, `tests/test_supervisor_loop.py`

- `run_forever(config, sleep=time.sleep, max_iterations=None)`; **il `try` sta dentro il `while`**
- heartbeat scritto a fine di **ogni** giro, **dentro** il `try/except`
- **guard di istanza singola:** `socket.bind` su porta locale fissa, **senza `SO_REUSEADDR`**.
  Misurato: senza → `OSError(10048)` ✓; con → **il bind riesce** e due supervisori girano insieme (N12).
  Il commento nel codice deve dire perché l'opzione è assente, o qualcuno la riaggiunge
- logging su `RotatingFileHandler` accanto a `starkeno.db`, mai `print`
- avvio solo con `python -m starkeno.supervisor`

**Test:** `sleep` finto, `max_iterations=3`, `run_once` che solleva ogni volta ⇒ **tre** chiamate,
nessuna eccezione propagata, `consecutive_errors=3`, heartbeat aggiornato lo stesso ·
**il secondo bind fallisce** · `SO_REUSEADDR` non compare nel sorgente.

---

### Task 10 — `mcp_server.py`: warning in linea

**File:** `starkeno/mcp_server.py`, `tests/test_mcp_warning.py`

Solo `get_open_alerts_lookup`, dentro `try/except`, **solo `status='open'`** (mai `candidate`).
La firma di `log_agent_action` guadagna i tre campi opzionali; la docstring porta il contratto
di §5 con lo snippet e gli `or 0`.

**Test:** `open` ⇒ warning · **`candidate` ⇒ nessun warning** · nessun alert ⇒ risposta
**byte-identica** alla v0 · **la lookup solleva ⇒ l'azione è registrata comunque e la risposta è
di successo** · i tre campi omessi ⇒ `NULL`, non `0`.

---

### Task 11 — `api.py`: gli endpoint

**File:** `starkeno/api.py`, `tests/test_api_alerts.py`

I cinque endpoint di §6. **Tutte le rotte prima di `app.mount("/")`** (`api.py:54`).
**Un solo helper** `iso_or_none(dt)` per ogni DateTime nullable.

**Test:** `resolved_at=None` ⇒ **200, non 500** · `evidence` fa round-trip · `stale` distinguibile
da `recovery` · `dismiss` senza nota ⇒ **422** · `/api/rule-status` espone `non_valutabile` **e**
`error` · `/api/supervisor/status` risponde anche con `supervisor_state` vuota · **una rotta
dichiarata dopo il mount restituirebbe 404** (test che protegge l'ordine).

---

### Task 12 — Dashboard

**File:** `starkeno/static/index.html`, `tests/test_dashboard_smoke.py`

Sezione alert sopra la tabella agenti, **raggruppata per agente** (§3.7), `setInterval(load, 15000)`,
badge distinti per `candidate`/`open`/`non_valutabile`/`error`, riga di stato del supervisore
(rossa oltre `3 × INTERVAL`), colonna «Token pesati», pulsanti dismiss/mute, nota sul rename (§10).

**Ogni riga di §D deve avere un pixel.** In particolare: `error` visivamente **diverso** da `ok`
(altrimenti una regola rotta sembra sana — il fallimento di §1), e `stale` diverso da `recovery`.

**Test:** smoke con `TestClient` — la pagina cita ogni stato di §D.

---

## §G — Ordine, e cosa succede se lo si cambia

```
0 Alembic ──► 1 schema ──► 2 config ──► 3 primitive ──► 4 R1 ──► 5 R2/R4 ──► 6 R3
                                                                              │
                              12 dashboard ◄── 11 API ◄── 10 MCP ◄── 9 loop ◄──┴─► 7 db ──► 8 riconciliazione
```

- **0 prima di tutto:** `create_all()` non altera tabelle esistenti (misurato). Ogni modifica
  successiva sarebbe ignorata in silenzio.
- **1 prima di 3:** il test del fuso sulle tabelle nuove (N1) non è scrivibile senza le tabelle.
- **2 prima di 3:** gli `assert` devono fallire prima che qualcuno scriva una regola su
  costanti incoerenti.
- **7 prima di 8:** la riconciliazione non può essere testata senza le funzioni che caricano.
- **11 e 12 per ultimi, ma non facoltativi:** senza, la v1 può avere tutti i test verdi e
  `alerts` che si riempie **senza che un solo alert raggiunga un essere umano** (§6).

**Stima:** 13 task. I task 3–6 sono i più lunghi (le regole e i loro confini); 0–2 i più rischiosi
(sbagliarli non produce errori, produce silenzio).

---

## §H — Cosa resta aperto

1. **C8, C9, C11, C12 cambiano il comportamento rispetto allo spec.** Sono in §C con la misura
   che le motiva. Se una non ti convince, il posto per fermarla è adesso: C8 in particolare
   toglie copertura a R1 sugli agenti che non passano il dettaglio, in cambio di zero falsi
   positivi su di essi.
2. **Le soglie non sono tarate** (§1). Il primo compito reale della v1 è raccogliere i dati che
   permetteranno di tararle. `SPEND_MIN_HISTORY=30` in particolare rende il p95 il 3° valore più
   alto della baseline: molto rumoroso, primo candidato alla revisione dopo due settimane di dati.
3. **`SPEND_HISTORY_WINDOW=200` con un watermark arretrato** significa una query di baseline per
   candidato. Misurato: 40 candidati = 0,0116 s. Non è un problema; lo diventerebbe con un buco
   di giorni. Il watermark inizializzato a `MAX(id)` (E.3) chiude anche questo.
4. **Fuori scope, confermato v2:** baseline auto-calibranti, aggregazione cross-agent, esenzioni
   per regola, soppressione vera fra regole correlate, idempotenza sui log, ragionamento LLM.
