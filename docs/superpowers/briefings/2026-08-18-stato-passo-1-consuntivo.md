# Stato del Passo 1 al 18/08/2026 — leggere prima di riprendere

Il **Passo 1** descritto in
[2026-08-16-prossimi-passi-simulazione-costi.md](2026-08-16-prossimi-passi-simulazione-costi.md)
è **consegnato e pubblicato**. Questo documento dice cosa esiste, cosa non è stato verificato,
e in che ordine affrontarlo.

## Cosa esiste adesso

Il ponte fra la metà osservativa e quella predittiva. `origin/main` è a `38fd187`, 23 commit
pubblicati il 18/08/2026 con consenso esplicito. Suite da 601 a **680 passed, 2 skipped**
sotto `-W error`.

- `starkeno/consuntivo.py` — modulo **puro** (niente SQLAlchemy, orologio, filesystem):
  attribuisce le chiamate raccolte ai nodi del Blueprint, le somma, le confronta con i
  quattro scenari simulati, le prezza, e rende il risultato come testo.
- Tabelle `blueprint_runs` e `blueprint_run_markers`, migrazione `0006`, e le loro
  letture e scritture in `db.py`.
- Tre tool MCP: `blueprint_run_start`, `blueprint_run_node`, `blueprint_run_end`.
- Il comando `starkeno consuntivo --elenco | --run <chiave> [--json]`.
- `preflight_service.validate_stored_analysis`: **un solo** validatore per entrambe le porte.

`agent_actions`, gli hook, `conto.py` e `report_conto.py` non sono stati toccati.

Specifica: [../specs/2026-08-16-consuntivo-esecuzione-blueprint-design.md](../specs/2026-08-16-consuntivo-esecuzione-blueprint-design.md).
Piano eseguito: [../plans/2026-08-16-passo-1-consuntivo.md](../plans/2026-08-16-passo-1-consuntivo.md).
Ledger con tutti i rilievi minori residui: `.superpowers/sdd/progress.md` — **non tracciato,
vive solo nel repository di lavoro.**

## Le due decisioni portanti, da non disfare

**L'attribuzione è una VISTA, mai una colonna.** La riga raccolta non viene mai timbrata.
L'esecuzione dichiara quando è iniziata, quando ha cambiato nodo e quando è finita;
l'attribuzione si calcola al momento del confronto incrociando quegli intervalli con i
`timestamp` già raccolti. È per questo che l'hook — il codice che gira a casa d'altri — non
deve sapere cosa sia un Blueprint, e che una dichiarazione sbagliata si corregge ricalcolando
invece di restare incisa.

**Quando l'attribuzione è incerta, si dichiara.** Più di una sessione nella finestra ferma il
confronto invece di sommarlo. Le invocazioni di nodo stimate e le chiamate API osservate si
stampano affiancate e non si sottraggono mai: sono unità diverse.

## I problemi aperti, in ordine

### 1. Il close a metà turno — costa una riga, ed è il primo che si incontra

`blueprint_run_end` lo chiama l'agente **durante** un turno. Le righe le scrive l'hook `Stop`
**dopo**. Quindi nel momento in cui l'agente chiude l'esecuzione e legge il confronto, le
chiamate del suo ultimo turno — spesso le più grosse — non sono ancora nel database.

**Il primo close reale stamperà probabilmente `senza_osservazioni` o un totale corto.**

Il rimedio esiste già ed è gratuito, perché l'attribuzione è una vista: `starkeno consuntivo
--run <chiave>` ricalcola più tardi, quando le righe sono arrivate. Ma **non è scritto da
nessuna parte**, e chi lo incontra penserà che il consuntivo non funzioni. Una riga nel
docstring di `blueprint_run_end` chiude il problema.

### 2. La prima esecuzione vera — è la prima misura seria

**Tutti e 680 i test girano su fixture sintetiche.** Nessun test esercita il percorso completo
con righe davvero attribuite ai nodi attraverso il database: il modulo puro è provato su righe
costruite a mano, il livello database su righe che scrive lui, e i due non si incontrano mai
con un risultato non banale.

In un progetto la cui regola è «misura, non assumere», questo è il buco vero. Serve una
esecuzione reale, non altri test.

Quello che si scoprirà lì, prevedibilmente:

- **`tokens_used` sotto dati veri.** Ogni riga sintetica della suite soddisfa
  `cache_read + cache_write + output <= tokens_used` con componenti non negativi. Le righe
  vere sono l'intera ragione per cui `rules.py` porta quattro guardie e `conto.py` conta
  `righe_non_classificabili`. Il consuntivo ora instrada sulle stesse guardie e conta le righe
  rifiutate: quel contatore è la prima cosa da guardare.
- **L'allineamento degli orologi ai confini.** `declared_at` è `datetime.now(timezone.utc)`
  preso al momento della chiamata al tool; `timestamp` viene dal transcript per un percorso
  diverso. Uno scarto sotto il secondo è invisibile ovunque tranne che su un confine fra nodi,
  che è l'unico posto dove cambia una risposta.

### 3. La frequenza dei rifiuti — la domanda che decide se il Passo 1 serve a qualcosa

Compattazione e riavvii cambiano `session_id` a metà lavoro. La specifica lo accetta e lo
dichiara. **Quello che nessuno ha misurato è quanto spesso accade.**

Se una normale sessione lunga ruota `session_id` anche una sola volta, il confronto risponde
`ambigua` e non produce niente. La logica del rifiuto è dimostrata corretta; la sua frequenza
è completamente ignota. Se scatta quasi sempre, il risultato è un sistema corretto che non
consegna mai il suo output — e allora va ripensata la regola, non il codice.

Si misura durante il punto 2, non prima.

### 4. I rilievi minori residui

Nel ledger, con la triage già fatta dalla revisione finale. Il più concreto: un Blueprint con
soli costi di tool e senza listino modelli completo non mostra alcun costo stimato, perché i
costi per scenario si stampano solo nel ramo `else`. Lasciato fuori perimetro di proposito.

## Cosa NON fare prima

- **La parte C** (esecuzione vera dei workflow). Spende soldi veri ed esegue tool veri.
  Vincoli duri già stabiliti: flag letterale separato, tetto di spesa obbligatorio senza
  default, mai avviata da hook, report, doctor o dashboard.
- **La dashboard**, che viene dopo i primi feedback per decisione dell'utente.
- **I Passi 2, 3 e 4** (`measured` prodotto, calibrazione dei default, prezzi che scadono):
  dipendono tutti da scarti osservati veri, che il punto 2 qui sopra deve ancora produrre.

## Cosa ha insegnato questa sessione

Quindici rilievi Important più un Critical, **tutti dettati dal piano scritto prima di
implementare, nessuno introdotto da chi implementava**. Due meritano di essere ricordati
perché descrivono come nascono i difetti in questo progetto:

- **Il Critical l'ha trovato solo la revisione dell'intero ramo**, non le dieci revisioni per
  task: `starkeno consuntivo` si schiantava con una traccia SQLAlchemy su un database
  inesistente, cioè sullo stato di ogni nuovo utente al primo avvio. Nessuna revisione per
  task poteva vederlo, perché il difetto stava nell'incontro fra il comando nuovo e
  l'installazione vuota.
- **Il secondo l'ha trovato eseguendo, non leggendo:** `consuntivo.totali()` applicava una
  sola delle quattro guardie sui dati, producendo conteggi di token **negativi** con
  `righe_non_scomposte = 0` — nessun segnale — e prezzando quelle righe.

Entrambi hanno la forma che questo progetto continua a pagare: qualcosa si perde senza
emettere un segnale.

## Vincoli sempre in vigore

- **Nessun push e nessuna modifica remota senza consenso esplicito.** Il push del 18/08/2026
  è stato autorizzato per quell'occasione e non vale come autorizzazione permanente.
- Non tracciare dati personali, transcript reali, database, log, segreti o percorsi home.
- Prima di dichiarare completo un lavoro: test pertinenti, `python -m pytest -q -W error` e
  `git diff --check`. Prima di pubblicare, anche `scripts/verifica_segreti.py --tracked` e
  `scripts/verifica_pubblicazione.py`.
