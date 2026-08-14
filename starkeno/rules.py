"""Le regole del Supervisore, come funzioni PURE.

Ingresso: record gia' caricati, la configurazione delle soglie, e `now`.
Uscita: VIOLAZIONE, OK, o NON_VALUTABILE.

**Non tocca mai il database, mai SQLAlchemy, mai l'orologio di sistema.** E' l'unica
parte del design verificabile senza infrastruttura, ed e' per questo che tutto cio' che
puo' stare qui ci sta.

Le soglie arrivano come parametri, mai lette da `config`: una `rules.py` che ignorasse
la configurazione e usasse costanti scritte a mano passerebbe ogni test, e correggere una
soglia dopo due settimane di dati veri non cambierebbe niente — rendendo inutile il
compito dichiarato della v1.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# ---------------------------------------------------------------------- esiti
VIOLAZIONE = "violazione"
OK = "ok"
NON_VALUTABILE = "non_valutabile"

# Precedenza nella combinazione di piu' rilevatori (C12): non si dice mai OK quando
# parte delle prove era inutilizzabile.
_PRECEDENZA = {VIOLAZIONE: 2, NON_VALUTABILE: 1, OK: 0}


@dataclass(frozen=True)
class ActionRecord:
    """Una riga di `agent_actions`, gia' normalizzata.

    La costruisce `db.py`, non l'ORM: caricare 86.400 oggetti ORM per una finestra da 24h
    costa 1,17 s contro 0,15 s per le tuple grezze — misurato. `timestamp` e' sempre
    aware-UTC: sopra `db.py` non esiste nessun datetime naive.

    Vive qui e non in `db.py` perche' `rules.py` non puo' importare `db.py`; la
    dipendenza va nell'altro verso.
    """

    id: int
    project: str
    action: str
    model_used: str
    tokens_used: int
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    timestamp: datetime

    # Calcolato da `db.py` al caricamento, con la stessa formula di `effective_tokens`
    # ma valutata dal database. Sta qui e non lo ricalcola chi legge perche' altrimenti
    # esisterebbe un terzo posto in cui la formula puo' divergere.
    effective: float = 0.0


@dataclass(frozen=True)
class Esito:
    """Il risultato della valutazione di una regola su un agente.

    `ultimo_contributo` e' il timestamp dell'azione piu' recente che ha contribuito alla
    violazione, e diventa `alerts.last_seen`. Torna da qui e non dal supervisore perche'
    solo la regola sa quali azioni hanno contribuito — ed e' la definizione che fa
    funzionare la chiusura degli alert: quando il comportamento cessa, `last_seen` smette
    di avanzare e la finestra pulita dopo di esso puo' crescere.
    """

    stato: str
    motivo: str | None = None
    evidenza: dict = field(default_factory=dict)
    ultimo_contributo: datetime | None = None

# ------------------------------------------------------- flag di qualita' dati
# Prodotti da `effective_tokens`. Le regole li trattano in due modi diversi:
#
#   token_implausibili   -> la riga va ESCLUSA: non e' spesa, e' un bug del chiamante
#   gli altri tre        -> la riga vale il totale grezzo, e conta per la quota di
#                           qualita' dati che puo' portare la regola ad astenersi
#
# La distinzione conta: sommare una riga implausibile inquinerebbe la spesa aggregata di
# R4, mentre escludere una riga solo perche' la scomposizione e' parziale butterebbe via
# la forma piu' comune che il sistema vedra'.
COMPONENTI_PARZIALI = "componenti_parziali"
COMPONENTE_NEGATIVO = "componente_negativo"
SOMMA_SUPERA_TOTALE = "somma_supera_totale"
TOKEN_IMPLAUSIBILI = "token_implausibili"

_SUFFISSO_VERSIONE_PROVIDER = re.compile(r":\d+$")
_PREFISSO_REGIONALE_BEDROCK = re.compile(r"^(us|eu|apac)\.anthropic\.")
_SUFFISSO_REVISIONE = re.compile(r"-v\d+$")
_SUFFISSO_DATA = re.compile(r"-\d{8}$")

_SEPARATORI_PERCORSO = ("/", chr(92))


def normalizza_modello(nome: str) -> str:
    """Riduce un identificativo di modello alla chiave usata in MODEL_TIERS.

    L'ordine dei passi non e' libero: la pipeline dello spec toglieva il suffisso di data
    DOPO aver tolto il `:0`, quando la data non era piu' in fondo. Misurato:
    `us.anthropic.claude-opus-4-5-20251101-v1:0` usciva come
    `claude-opus-4-5-20251101-v1` invece di `claude-opus-4-5`, quindi non mappato, quindi
    — oltre MAX_UNMAPPED_SHARE — astensione permanente di R2 e R4 su Bedrock.

    E NON si prende "il segmento dopo l'ultimo punto". Quel passo esisteva solo per il
    prefisso `us.anthropic.` di Bedrock, ma applicato senza guardia distrugge ogni nome
    con un punto di versione: `gpt-5.2-turbo` -> `2-turbo`, `gemini-2.5-pro` -> `5-pro`.
    Il prefisso regionale si toglie con una guardia esplicita.
    """
    s = nome.strip().lower()
    s = _SUFFISSO_VERSIONE_PROVIDER.sub("", s)     # ':0' finale (Bedrock)
    s = s.rsplit("/", 1)[-1]                       # dopo l'ULTIMO '/' (Vertex, OpenRouter)
    s = _PREFISSO_REGIONALE_BEDROCK.sub("", s)     # 'us.anthropic.' e sorelle, e basta
    s = _SUFFISSO_REVISIONE.sub("", s)             # '-v1' finale
    s = _SUFFISSO_DATA.sub("", s)                  # '-20251101' finale
    return s


def fascia(nome: str, tiers: dict) -> str | None:
    """La fascia di un modello, o None se non e' mappato.

    None non e' mai `frontier`: sconosciuto significa nessuna prova, non colpevole. Chi
    chiama deve escludere le righe non mappate da numeratore E denominatore — includerle
    solo al denominatore abbasserebbe la share e farebbe tacere la regola per caso.
    """
    return tiers.get(normalizza_modello(nome))


def parse_action(action: str) -> tuple[str, str | None]:
    """Divide `categoria:dettaglio`, o restituisce l'azione intera come categoria nuda.

    Tre guardie, tutte per casi reali:

    - la parte sinistra non puo' contenere separatori di percorso: prende
      `/usr/local:bin`;
    - la parte sinistra non puo' essere una LETTERA SOLA seguita da un separatore:
      prende `C:\\workspace\\app.py`. Serve una guardia sua perche' quella sopra non
      lo copre — in un percorso Windows la sinistra e' `C`, che separatori non ne ha.
      Lo spec dichiara solo la prima e sostiene che basti: misurato, non basta, e senza
      questa ogni azione di un agente su Windows collassa su categoria `C` con dettagli
      tutti distinti, spegnendo R1 senza che niente lo dica;
    - la parte destra non puo' essere vuota, altrimenti `plan:` / `act:` / `observe:`
      producono dettagli tutti identici (tutti "") e un agente sano a tre fasi finisce
      nel ramo piu' sensibile del rilevatore di cicli.

    **Normalizzazione del dettaglio: query string, fragment, separatori, minuscole. E
    NIENT'ALTRO.** In particolare le cifre restano. Una versione precedente normalizzava
    anche cifre, timestamp e UUID: sembrava piu' robusta ed era attivamente dannosa,
    perche' un batch sano `fetch/validate/save:user_1..100` collassava su `user_N` e
    scattava come loop. Il batch non rivisita mai lo stesso oggetto, il loop rivisita
    sempre lo stesso: e' esattamente la distinzione che le cifre portano.

    Punto cieco dichiarato: rumore annidato DENTRO l'identificatore
    (`search:query_1730992811`) resta indistinguibile da un oggetto nuovo. La via
    d'uscita e' il contratto col chiamante, non un'euristica piu' aggressiva.
    """
    if ":" not in action:
        return action, None

    sinistra, destra = action.split(":", 1)
    if not sinistra or any(sep in sinistra for sep in _SEPARATORI_PERCORSO):
        return action, None
    if len(sinistra) == 1 and sinistra.isalpha() and destra[:1] in _SEPARATORI_PERCORSO:
        return action, None  # lettera di unita' Windows: 'C:\\...' o 'c:/...'
    if not destra.strip():
        return action, None

    dettaglio = destra.strip()
    dettaglio = dettaglio.split("?", 1)[0]
    dettaglio = dettaglio.split("#", 1)[0]
    dettaglio = dettaglio.replace(chr(92), "/").lower()
    return sinistra, dettaglio


def effective_tokens(tokens_used, cache_read, cache_write, output, *, weights, max_plausible):
    """Il costo pesato di una chiamata, e un'eventuale segnalazione di qualita' dati.

    Ritorna `(valore, flag|None)`. Sei rami, e solo UNO applica la formula: tutto il resto
    ricade sul totale grezzo con una segnalazione — mai un'eccezione, mai un indovinello.

    I pesi sono RAPPORTI, non prezzi: non introducono il listino da mantenere che il
    design rifiuta, e i rapporti fra fasce sono molto piu' stabili dei valori assoluti.

    Il tetto di plausibilita' si applica a `tokens_used` GREZZO, non al valore pesato.
    La giustificazione e' fisica — una chiamata non puo' superare ~2M token — mentre il
    valore pesato puo' legittimamente arrivare a 5x il grezzo perche' l'output pesa 5.0.
    Verificato: una chiamata valida da 2M token con meta' output da un effective di
    6.000.000, e col tetto sul valore pesato verrebbe scartata come dato corrotto proprio
    la chiamata piu' cara della giornata.
    """
    # 6. implausibile: e' un bug del chiamante (tipicamente un conteggio di byte), non spesa
    if tokens_used > max_plausible:
        return tokens_used, TOKEN_IMPLAUSIBILI

    componenti = (cache_read, cache_write, output)

    # 1. nessuna dichiarazione -> costo pieno
    if all(c is None for c in componenti):
        return tokens_used, None

    # 3. dichiarazione parziale = nessuna dichiarazione.
    #    E' la forma PIU' COMUNE: nell'SDK i campi cache sono Optional e valgono None su
    #    ogni chiamata che non tocca la cache, mentre output_tokens e' sempre un int.
    #    Senza questo ramo, `9000 - None` solleva TypeError e le regole sui soldi si
    #    spengono in silenzio.
    if any(c is None for c in componenti):
        return tokens_used, COMPONENTI_PARZIALI

    # 4. un componente negativo. Silenzioso e peggiore degli altri: applicando la formula,
    #    tokens_used=60000 con output=-40000 darebbe effective = -100.000, che e' SOTTO la
    #    soglia di R4 invece che sopra. La riga sparirebbe dalla regola che esiste apposta
    #    per catturarla.
    if any(c < 0 for c in componenti) or tokens_used < 0:
        return tokens_used, COMPONENTE_NEGATIVO

    # 5. la scomposizione contraddice il totale: non e' utilizzabile
    if cache_read + cache_write + output > tokens_used:
        return tokens_used, SOMMA_SUPERA_TOTALE

    # 2. l'unico ramo che pesa davvero
    ingresso = tokens_used - cache_read - cache_write - output
    valore = (
        ingresso * weights["input"]
        + cache_read * weights["cache_read"]
        + cache_write * weights["cache_write"]
        + output * weights["output"]
    )
    return valore, None


def percentile_nearest_rank(valori, q: float):
    """Il percentile `q` col metodo nearest-rank: `s[ceil(q*n) - 1]`.

    Il metodo e' PINNATO perche' "il 95esimo percentile" non e' una definizione.
    Misurato sulla dimensione minima della baseline (30 campioni), nearest-rank e
    interpolazione lineare divergono del 44%; a 50 campioni dello 0,2%. Due
    implementatori costruirebbero due sistemi con soglie diverse credendo di aver scritto
    la stessa cosa.

    Nearest-rank restituisce sempre un valore che esiste davvero nei dati — nessuna
    interpolazione — ed e' deterministico, che e' la proprieta' che conta: una regola che
    alternasse VIOLAZIONE e OK sugli stessi dati sarebbe peggio che assente.
    """
    ordinati = sorted(valori)
    if not ordinati:
        raise ValueError("percentile di una sequenza vuota")
    rango = max(1, math.ceil(q * len(ordinati)))
    return ordinati[rango - 1]


# =============================================================================
# R1 — loop: l'agente e' bloccato
# =============================================================================

def _classifica_posizione(valori, k):
    """Come sono i dettagli in UNA posizione del ciclo, lette le K ripetizioni.

    La classificazione e' PER POSIZIONE, ed e' la decisione che conta di piu' in tutto
    R1. Il loop piu' comune che esista — `read:app.py -> edit:app.py -> test:tests/` —
    ha dettagli identici per posizione, ma guardando l'INSIEME di tutti i dettagli della
    finestra risulterebbe "misto" ({app.py, tests/}) e la soglia richiesta
    raddoppierebbe: il doppio di sensibilita' sul caso principale a seconda di come si
    legge la stessa frase.
    """
    if all(v is None for v in valori):
        return "assente"
    if any(v is None for v in valori):
        return "misto"
    distinti = len(set(valori))
    if distinti == 1:
        return "identica"
    if distinti == k:
        return "distinta"
    return "misto"


def _rilevatore_a(azioni, *, now, config):
    """Ripetizione identica della stessa azione dentro LOOP_WINDOW_MINUTES.

    Considera SOLO le azioni che hanno un dettaglio. Su una categoria nuda si astiene
    invece di usare una soglia piu' alta (C8): senza dettaglio, «100 oggetti diversi» e
    «lo stesso oggetto 100 volte» sono la stessa identica stringa, e nessuna soglia crea
    l'informazione che non c'e'. Misurato: un indicizzatore sano a 3 azioni/secondo
    supera qualunque soglia fissa in pochi secondi.
    """
    inizio = now - timedelta(minutes=config.LOOP_WINDOW_MINUTES)
    finestra = [a for a in azioni if a.timestamp >= inizio]
    if not finestra:
        # Nessuna attivita' recente non e' un dato inutilizzabile: e' assenza di dati
        # nella finestra corta, e il rilevatore B copre l'orizzonte piu' lungo. Astenersi
        # qui renderebbe NON_VALUTABILE ogni agente fermo da cinque minuti.
        return OK, None, {}, None

    con_dettaglio = [(a, parse_action(a.action)) for a in finestra]
    con_dettaglio = [(a, c, d) for a, (c, d) in con_dettaglio if d is not None]
    if not con_dettaglio:
        return (
            NON_VALUTABILE,
            "nessuna azione con dettaglio nella finestra: R1 non puo' distinguere "
            "il progresso dalla ripetizione",
            {},
            None,
        )

    conteggi = Counter((c, d) for _, c, d in con_dettaglio)
    (categoria, dettaglio), quante = conteggi.most_common(1)[0]
    if quante >= config.LOOP_MIN_REPEATS:
        contribuenti = [a for a, c, d in con_dettaglio if (c, d) == (categoria, dettaglio)]
        return (
            VIOLAZIONE,
            "azione '%s:%s' ripetuta %d volte in %d minuti"
            % (categoria, dettaglio, quante, config.LOOP_WINDOW_MINUTES),
            {
                "rilevatore": "ripetizione",
                "azione": "%s:%s" % (categoria, dettaglio),
                "ripetizioni": quante,
                "soglia": config.LOOP_MIN_REPEATS,
            },
            max(a.timestamp for a in contribuenti),
        )
    return OK, None, {}, None


def _rilevatore_b(azioni, *, now, config):
    """Ciclo di categorie ripetuto, ancorato all'azione piu' recente.

    I passi sono numerati nel piano perche' "esiste un ciclo ripetuto K volte" lasciava
    cinque decisioni aperte, e due implementatori avrebbero costruito due sistemi diversi.
    """
    sequenza = azioni[-config.LOOP_SEQUENCE_LEN:]
    if not sequenza:
        return OK, None, {}, None

    analizzate = [parse_action(a.action) for a in sequenza]
    categorie = [c for c, _ in analizzate]
    dettagli = [d for _, d in analizzate]
    n = len(categorie)

    for lunghezza in range(config.LOOP_CYCLE_MIN_LEN, config.LOOP_CYCLE_MAX_LEN + 1):
        blocco = categorie[n - lunghezza:]

        # Un blocco a categoria unica e' un ciclo da 1 travestito, ed e' affare del
        # rilevatore A. Senza questa guardia, 200 azioni identiche producono L=2 K=100 e
        # L=3 K=66 — misurato — e il rilevatore B scavalca la soglia di A.
        if len(set(blocco)) < 2:
            continue

        k = 1
        while (k + 1) * lunghezza <= n and categorie[n - (k + 1) * lunghezza: n - k * lunghezza] == blocco:
            k += 1
        if k < 2:
            continue

        limite = timedelta(minutes=config.LOOP_CYCLE_WINDOW_MINUTES)

        # K si RESTRINGE finche' le ripetizioni non stanno nella finestra, invece di
        # scartare tutto quando non ci stanno.
        #
        # Lo pseudocodice dice "conta K, poi verifica che le K*L azioni stiano entro
        # LOOP_CYCLE_WINDOW_MINUTES", e cosi' scritto un loop che dura piu' della
        # finestra e' PIU' DIFFICILE da rilevare di uno breve: K cresce attraverso le
        # pause, l'arco supera il limite, e il rilevatore scarta. Misurato su un agente
        # che ripete lo stesso ciclo ogni quindici minuti — cioe' il caso peggiore, non
        # un caso limite — dove il rilevatore B non trovava niente.
        while k >= 2:
            coinvolte = sequenza[n - k * lunghezza:]
            if (coinvolte[-1].timestamp - coinvolte[0].timestamp) <= limite:
                break
            k -= 1
        if k < 2:
            continue

        coinvolte = sequenza[n - k * lunghezza:]
        arco = coinvolte[-1].timestamp - coinvolte[0].timestamp
        # Il ciclo dev'essere RECENTE: le azioni caricate coprono 48 ore, e senza questo
        # un blocco finito ieri verrebbe segnalato oggi come "agente fermo adesso".
        if now - coinvolte[-1].timestamp > limite:
            continue

        stati = [
            _classifica_posizione(
                [dettagli[n - (r + 1) * lunghezza + i] for r in range(k)], k
            )
            for i in range(lunghezza)
        ]

        # La prima lunghezza che combacia vince: oltre questo punto si esce comunque.
        if all(s == "distinta" for s in stati):
            return OK, None, {}, None
        if all(s == "assente" for s in stati):
            return (
                NON_VALUTABILE,
                "ciclo di %d categorie senza alcun dettaglio: R1 non puo' distinguere "
                "il progresso dalla ripetizione" % lunghezza,
                {},
                None,
            )

        if all(s == "identica" for s in stati):
            richiesto = config.LOOP_CYCLE_K_SAME_DETAIL
        else:
            richiesto = config.LOOP_CYCLE_K_MIXED_DETAIL

        if k >= richiesto:
            return (
                VIOLAZIONE,
                "ciclo di %d azioni ripetuto %d volte in %s"
                % (lunghezza, k, arco),
                {
                    "rilevatore": "ciclo",
                    "lunghezza_ciclo": lunghezza,
                    "ripetizioni": k,
                    "soglia": richiesto,
                    "dettagli_per_posizione": stati,
                    "categorie": blocco,
                },
                coinvolte[-1].timestamp,
            )
        return OK, None, {}, None

    return OK, None, {}, None


def valuta_r1(azioni, *, now, config) -> Esito:
    """R1 `loop`: l'agente non sta facendo progressi.

    `azioni` sono i record dell'agente dentro SUPERVISOR_ACTIVE_AGENT_HOURS, ordinati per
    id crescente. `LOOP_MIN_HISTORY` si misura su QUESTI (C9), non sul totale storico:
    lo spec non lo dice, e la scelta cambia quando LOOP_CYCLE_K_SAME_DETAIL diventa
    raggiungibile.

    I due rilevatori si combinano per precedenza VIOLAZIONE > NON_VALUTABILE > OK (C12).
    Lo pseudocodice non diceva come combinarli, e senza la precedenza R1 direbbe OK
    mentre meta' delle prove era inutilizzabile — il silenzio indistinguibile dalla
    salute, nella sua forma piu' piccola.
    """
    if len(azioni) < config.LOOP_MIN_HISTORY:
        return Esito(
            NON_VALUTABILE,
            "storia insufficiente: %d azioni, ne servono %d"
            % (len(azioni), config.LOOP_MIN_HISTORY),
        )

    risultati = [
        _rilevatore_a(azioni, now=now, config=config),
        _rilevatore_b(azioni, now=now, config=config),
    ]
    stato, motivo, evidenza, contributo = max(risultati, key=lambda r: _PRECEDENZA[r[0]])

    # Se entrambi i rilevatori violano, `last_seen` e' il PIU' RECENTE dei due contributi.
    #
    # Non e' un dettaglio estetico. Nel loop classico i due rilevatori scelgono azioni
    # diverse: A prende l'ultima ripetizione di `read:app.py`, B l'ultima azione del
    # ciclo, che arriva due passi dopo. Prendendo quella di A, le due azioni finali del
    # ciclo — che fanno parte della violazione — verrebbero contate come "azioni pulite
    # dopo last_seen", e la chiusura per recupero scatterebbe con due azioni sane in meno
    # del dovuto. Misurato: 21 azioni contate invece di 19, con la soglia a 20.
    if stato == VIOLAZIONE:
        contributi = [r[3] for r in risultati if r[0] == VIOLAZIONE and r[3] is not None]
        if contributi:
            contributo = max(contributi)

    return Esito(stato, motivo, evidenza, contributo)


# =============================================================================
# R2 e R4 — le due regole che parlano di soldi
# =============================================================================

@dataclass(frozen=True)
class ClassificazioneModelli:
    """Come si dividono i nomi modello osservati in una finestra.

    `frontier` contiene i nomi GREZZI, non quelli normalizzati: servono a costruire la
    clausola `model_used IN (...)` della query di aggregazione, e normalizzati non
    troverebbero nessuna riga.
    """

    frontier: tuple
    non_mappati: tuple
    quota_non_mappata: float


@dataclass(frozen=True)
class WindowStats:
    """Aggregati di una finestra, calcolati in SQL da `db.py`.

    Non una lista di record: misurato su 86.400 righe (24h di un agente a 1 az/s),
    l'ORM costa 1,17 s, le tuple grezze 0,15 s, e la stessa aggregazione fatta in SQL
    0,048 s. Con 200 agenti a giro, caricare le finestre non e' praticabile.

    Le soglie di VALORE (banale, pesante, plausibile) sono gia' state applicate da
    `db.py`, che le riceve come parametri. Qui restano solo le soglie di CONTEGGIO e di
    QUOTA. Confondere i due gruppi e' il modo piu' facile di rompere l'iniezione della
    configurazione senza che nessun test se ne accorga.
    """

    righe_totali: int
    frontier_valide: int              # frontier con effective > 0 e token plausibili
    frontier_scartate_zero: int       # frontier con effective <= 0
    frontier_banali: int              # frontier con tokens_used <= soglia banale
    frontier_pesanti: int             # frontier con effective >= soglia pesante
    somma_effective_frontier: float
    ultimo_frontier: datetime | None = None
    ultimo_frontier_banale: datetime | None = None
    ultimo_frontier_pesante: datetime | None = None

    # Conteggio per flag di qualita' dei dati sulla finestra. Non serve a decidere la
    # violazione: serve a farlo SAPERE. Senza, un chiamante che scrive componenti
    # parziali su ogni riga non produce nessun segnale visibile, e la sottostima della
    # spesa che ne deriva resta invisibile per sempre.
    flag_qualita: dict = field(default_factory=dict)


def classifica_modelli(conteggi_per_nome: dict, tiers: dict) -> ClassificazioneModelli:
    """Divide i nomi modello osservati in una finestra fra frontier e non mappati.

    Un nome non mappato non e' MAI frontier — sconosciuto significa nessuna prova, non
    colpevole — e va escluso da numeratore E denominatore: includerlo solo al
    denominatore abbasserebbe la share e farebbe tacere la regola per caso.
    """
    totale = sum(conteggi_per_nome.values()) or 1
    frontier = tuple(n for n in conteggi_per_nome if fascia(n, tiers) == "frontier")
    non_mappati = tuple(n for n in conteggi_per_nome if fascia(n, tiers) is None)
    quota = sum(conteggi_per_nome[n] for n in non_mappati) / totale
    return ClassificazioneModelli(frontier, non_mappati, quota)


def _guardie_comuni(stats, classificazione, config):
    """Le astensioni che R2 e R4 condividono. Ritorna un Esito, o None se si puo' valutare.

    Ogni ramo qui restituisce NON_VALUTABILE e mai OK: sono tutti casi in cui la regola
    non ha visto prove, e dire OK sarebbe il silenzio indistinguibile dalla salute — su
    le due sole regole che parlano di soldi.
    """
    if classificazione.quota_non_mappata > config.MAX_UNMAPPED_SHARE:
        return Esito(
            NON_VALUTABILE,
            "il %.0f%% delle chiamate usa modelli non riconosciuti: %s. "
            "Aggiungerli a MODEL_TIERS e' una riga."
            % (classificazione.quota_non_mappata * 100,
               ", ".join(sorted(classificazione.non_mappati))),
        )

    if not classificazione.frontier:
        return Esito(NON_VALUTABILE,
                     "nessun modello frontier fra quelli riconosciuti nella finestra")

    esaminate = stats.frontier_valide + stats.frontier_scartate_zero
    if esaminate == 0:
        return Esito(NON_VALUTABILE, "nessuna chiamata frontier nella finestra")

    quota_zero = stats.frontier_scartate_zero / esaminate
    if quota_zero > config.EXPENSIVE_MAX_ZERO_SHARE:
        return Esito(
            NON_VALUTABILE,
            "il %.0f%% delle chiamate frontier ha token non utilizzabili (<= 0): "
            "e' dato mancante, non spesa piccola" % (quota_zero * 100),
        )

    if stats.frontier_valide == 0:
        return Esito(NON_VALUTABILE, "nessuna chiamata frontier con token utilizzabili")

    return None


def valuta_r2(stats, *, classificazione, config) -> Esito:
    """R2 `expensive_model`: modello costoso per task banale.

    **Misura: token TOTALI** — R2 chiede quanto e' grosso il task, e un contesto da 80k
    non e' banale nemmeno se arriva tutto dalla cache. E' l'unica delle regole sui soldi
    a non usare `effective_tokens`, ed e' deliberato: misurando la dimensione del task
    sui soli token nuovi, un agente che riusa contesto in cache sembrerebbe fare task
    banali e R2 lo accuserebbe a rovescio.

    Il requisito di ripetizione e' deliberato: UNA chiamata piccola su un modello grosso
    puo' essere un giudizio difficile che vale il modello. Venti in un giorno sono
    un'abitudine.
    """
    astensione = _guardie_comuni(stats, classificazione, config)
    if astensione is not None:
        return astensione

    quota = stats.frontier_banali / stats.frontier_valide
    if (stats.frontier_banali >= config.EXPENSIVE_MIN_OCCURRENCES
            and quota >= config.EXPENSIVE_MIN_SHARE):
        return Esito(
            VIOLAZIONE,
            "%d chiamate frontier su task banali (%.0f%% delle frontier) in %d ore"
            % (stats.frontier_banali, quota * 100, config.EXPENSIVE_WINDOW_HOURS),
            {
                "regola": "expensive_model",
                "banali": stats.frontier_banali,
                "frontier_totali": stats.frontier_valide,
                "quota": round(quota, 4),
                "soglia_occorrenze": config.EXPENSIVE_MIN_OCCURRENCES,
                "soglia_quota": config.EXPENSIVE_MIN_SHARE,
                "modelli": sorted(classificazione.frontier),
                "qualita_dati": dict(stats.flag_qualita),
            },
            stats.ultimo_frontier_banale,
        )
    return Esito(OK)


def valuta_r4(stats, *, classificazione, config) -> Esito:
    """R4 `steady_waste`: spreco costante ad alto volume.

    **Misura: `effective_tokens`.** E' l'unica regola ASSOLUTA delle quattro, e serve
    perche' le altre tre sono relative: un agente sbagliato dalla prima riga non devia
    mai da se stesso, quindi R3 gli e' strutturalmente cieca.

    Due rami. Quello a conteggio prende le chiamate grandi ripetute; quello aggregato
    chiude la banda scoperta in mezzo, dove nessuna regola guardava la spesa TOTALE:
    100 chiamate da 8k costano quanto 15 da 60k, e senza il secondo ramo la prima
    situazione non produceva niente.

    Il ramo aggregato pretende `HEAVY_MIN_ACTIONS_FOR_SUM` chiamate (C11): una chiamata
    sola non e' *steady*, ed e' gia' il mestiere di R3 — che infatti pretende due
    anomalie proprio per non trasformare un fatto isolato in un alert permanente.
    """
    astensione = _guardie_comuni(stats, classificazione, config)
    if astensione is not None:
        return astensione

    comune = {
        "regola": "steady_waste",
        "frontier_totali": stats.frontier_valide,
        "somma_effective": round(stats.somma_effective_frontier),
        "modelli": sorted(classificazione.frontier),
        "qualita_dati": dict(stats.flag_qualita),
    }

    if stats.frontier_pesanti >= config.HEAVY_MIN_OCCURRENCES:
        return Esito(
            VIOLAZIONE,
            "%d chiamate frontier da almeno %d token pesati in %d ore"
            % (stats.frontier_pesanti, config.HEAVY_TOKENS, config.HEAVY_WINDOW_HOURS),
            dict(comune, ramo="conteggio", pesanti=stats.frontier_pesanti,
                 soglia=config.HEAVY_MIN_OCCURRENCES),
            stats.ultimo_frontier_pesante,
        )

    if (stats.frontier_valide >= config.HEAVY_MIN_ACTIONS_FOR_SUM
            and stats.somma_effective_frontier >= config.HEAVY_DAILY_TOKENS):
        return Esito(
            VIOLAZIONE,
            "%d token pesati su modelli frontier in %d ore, distribuiti su %d chiamate"
            % (round(stats.somma_effective_frontier), config.HEAVY_WINDOW_HOURS,
               stats.frontier_valide),
            dict(comune, ramo="aggregato", soglia=config.HEAVY_DAILY_TOKENS,
                 chiamate_minime=config.HEAVY_MIN_ACTIONS_FOR_SUM),
            stats.ultimo_frontier,
        )

    return Esito(OK)


# =============================================================================
# R3 — spend_anomaly: spesa fuori scala rispetto alla propria storia
# =============================================================================

@dataclass(frozen=True)
class CandidatoSpesa:
    """Un'azione non ancora esaminata, con la baseline contro cui misurarla.

    La baseline sono gli `effective_tokens` delle azioni PRECEDENTI dello stesso agente,
    gia' filtrati a valori positivi e limitati a SPEND_HISTORY_WINDOW. Arriva gia'
    costruita perche' l'esclusione del candidato dev'essere NELLA QUERY (`WHERE id <
    candidato`), non nel chiamante: la riga e' gia' nel database quando viene valutata, e
    una query ingenua la includerebbe alzando da sola la soglia contro cui e' misurata.
    Fatta nel chiamante, un test su liste scritte a mano la verificherebbe banalmente
    senza dire niente sul codice vero.
    """

    action_id: int
    timestamp: datetime
    effective: float
    baseline: tuple


def _anomalia_serializzabile(candidato):
    return {
        "action_id": candidato.action_id,
        "timestamp": candidato.timestamp.isoformat(),
        "effective": round(candidato.effective),
    }


def valuta_r3(candidati, *, anomalie_note, now, config) -> Esito:
    """R3 `spend_anomaly`: una chiamata fuori scala rispetto alla storia dell'agente.

    **Misura: `effective_tokens`**, sia per il candidato sia per la baseline.

    `candidati` sono le azioni con id superiore al watermark, non l'ultima soltanto: un
    agente veloce (40 azioni al minuto) nasconderebbe la chiamata da 600k dietro le
    successive, e l'anomalia piu' cara della giornata non verrebbe valutata da nessuno —
    un buco che PEGGIORA al crescere del throughput.

    `anomalie_note` sono quelle gia' registrate nell'`evidence` dell'alert. Servono
    perche' la promozione richiede piu' anomalie in una finestra di ore, mentre il
    watermark fa si' che ogni giro veda solo le azioni nuove: senza memoria, la prima
    anomalia sparirebbe prima che arrivi la seconda e il conteggio non salirebbe mai
    oltre uno. Lo spec non chiude questo punto; qui la memoria e' l'alert stesso.

    La decisione di PROMUOVERE non e' qui: la regola espone il conteggio in `evidence` ed
    e' la riconciliazione a confrontarlo con SPEND_PROMOTE_MIN_ANOMALIES. Una sola
    anomalia e' gia' una violazione — la riga esiste — ma non basta ad aprire un alert,
    perche' e' un fatto storico su una riga immutabile che non puo' auto-risolversi, e
    una singola analisi one-shot diventerebbe un alert permanente.

    Limite noto: essendo relativa alla storia dell'agente, R3 e' STRUTTURALMENTE CIECA a
    un agente che spreca dal primo giorno. E' il buco che R4 copre.
    """
    import statistics

    anomalie = []
    visti = set()
    limite = now - timedelta(hours=config.SPEND_ANOMALY_WINDOW_HOURS)

    for nota in anomalie_note:
        quando = datetime.fromisoformat(nota["timestamp"])
        if quando >= limite:                       # le scadute si potano, altrimenti il
            anomalie.append(dict(nota))            # conteggio cresce per sempre e la
            visti.add(nota["action_id"])           # promozione diventa irreversibile

    valutabili = 0
    baseline_piu_lunga = 0
    for candidato in candidati:
        if candidato.effective <= 0:
            continue                                # dato mancante, non spesa piccola
        baseline_piu_lunga = max(baseline_piu_lunga, len(candidato.baseline))
        if len(candidato.baseline) < config.SPEND_MIN_HISTORY:
            continue
        valutabili += 1

        mediana = statistics.median(candidato.baseline)
        p95 = percentile_nearest_rank(candidato.baseline, 0.95)
        anomalo = (
            candidato.effective >= config.SPEND_ABS_FLOOR_TOKENS
            and candidato.effective >= config.SPEND_MEDIAN_MULT * mediana
            and candidato.effective >= config.SPEND_P95_MULT * p95
        )
        if anomalo and candidato.action_id not in visti:
            anomalie.append(_anomalia_serializzabile(candidato))
            visti.add(candidato.action_id)

    if candidati and valutabili == 0 and not anomalie:
        positivi = [c for c in candidati if c.effective > 0]
        if positivi:
            return Esito(
                NON_VALUTABILE,
                "baseline di sole %d azioni valide, ne servono %d"
                % (baseline_piu_lunga, config.SPEND_MIN_HISTORY),
            )

    if not anomalie:
        return Esito(OK)

    anomalie.sort(key=lambda a: a["action_id"])
    evidenza = {
        "regola": "spend_anomaly",
        "anomalie": anomalie,
        "anomalie_nella_finestra": len(anomalie),
        "soglia_promozione": config.SPEND_PROMOTE_MIN_ANOMALIES,
        "finestra_ore": config.SPEND_ANOMALY_WINDOW_HOURS,
    }
    piu_recente = max(datetime.fromisoformat(a["timestamp"]) for a in anomalie)
    return Esito(
        VIOLAZIONE,
        "%d chiamate fuori scala rispetto alla storia dell'agente in %d ore"
        % (len(anomalie), config.SPEND_ANOMALY_WINDOW_HOURS),
        evidenza,
        piu_recente,
    )
