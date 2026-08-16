# Prossimi passi — chiudere l'anello fra costo simulato e costo reale

Documento di passaggio scritto il 16/08/2026, da leggere **prima** di iniziare il lavoro che
descrive. Lo stato del codice a oggi è in
[2026-08-16-stato-parte-b.md](2026-08-16-stato-parte-b.md).

## Il problema, con le prove

StarkEno è incentrato sulla **simulazione dei costi di workflow e automazioni**. Oggi ha due metà
che non si toccano:

- **La metà osservativa** — hook, database, `report` — sa cosa è successo davvero.
- **La metà predittiva** — Blueprint, `preflight_lint`, `preflight_simulate` — sa cosa succederebbe.

Non esiste un ponte fra le due. Verificato leggendo il codice, non supposto:

1. `starkeno/db.py`, `starkeno/conto.py` e `starkeno/report_conto.py` **non nominano mai un
   Blueprint**. La raccolta non sa che i Blueprint esistono.
2. `"measured"` è un valore di `Provenance` in `preflight_schema.py`, ma **nessun modulo di
   StarkEno lo produce**. È un tipo senza produttore: la dichiarazione più preziosa dello schema —
   «questo numero l'ho osservato io» — non è mai generata da nessuno.
3. `Comparison` in `preflight_patch.py` confronta **simulazione contro simulazione**: due
   Blueprint, stesso `effective_seed`, stesso `profile_hash`, stesso `algorithm_version`, su
   quattro scenari (`optimistic`, `typical`, `prudent`, `maximum`). È riproducibile e ben
   costruito. Ma un confronto fra **simulazione e realtà osservata** non esiste da nessuna parte.

Finché quel ponte manca, ogni numero che StarkEno stampa è un'opinione ben formattata — l'unica
cosa che questo progetto dichiara di non voler essere.

## Passo 1 — Il consuntivo: legare un'esecuzione al Blueprint che la prevedeva

Confrontare quello che una simulazione aveva stimato con quello che l'esecuzione ha consumato, e
dire dove sta lo scarto: *stimati 42k token, usati 61k, e quasi tutto sul nodo `review`*.

Serve un modo di legare le righe raccolte dagli hook a un Blueprint e ai suoi nodi — il minimo
onesto è un identificativo di esecuzione registrato accanto alle chiamate. **La decisione di come
legarli è la scelta portante di tutto ciò che viene dopo**, quindi merita un brainstorming suo e
non va presa di corsa dentro l'implementazione.

Attenzione a non barare: se l'attribuzione di una chiamata a un nodo è incerta, va detto invece di
indovinare. Uno scarto attribuito al nodo sbagliato è peggio di uno scarto non attribuito, perché
manda a ricalibrare la cosa giusta nella direzione sbagliata.

È anche il passo che produce il primo dato che valga la pena guardare — e quindi la precondizione
perché la dashboard abbia qualcosa da mostrare.

## Passo 2 — `measured` finalmente prodotto

Con osservazioni legate ai nodi, StarkEno può riscrivere i budget di un Blueprint con
`provenance: "measured"`, ed essere **l'unico soggetto autorizzato a farlo**, perché è l'unico che
ha misurato. Il Blueprint smette di essere una dichiarazione e diventa un modello tarato sui dati
di chi lo usa.

Contesto utile: `_rifiuta_measured` in `preflight_interpret.py` impedisce a un modello di
dichiarare `measured`, e quel difetto è affiorato tre volte prima di essere chiuso in modo
strutturale. Questo passo è il motivo per cui valeva la pena: `measured` sta per acquistare un
significato preciso, e un modello che se lo attribuisse lo distruggerebbe prima che nasca.

## Passo 3 — Calibrare i default invece di dichiararli

`CHARACTERS_PER_TOKEN = 3.5` in `preflight_interpret.py` è una stima dichiarata, e i profili di
rischio della simulazione vanno verificati allo stesso modo. Con gli scarti osservati dal Passo 1
diventano numeri **ricavati**. Il piano della parte B aveva già messo questa taratura fuori
perimetro «finché non ci saranno abbastanza scarti osservati»: il Passo 1 è ciò che li produce.

Regola da rispettare: un default ricavato deve dire da quante osservazioni viene. Un numero tarato
su tre esecuzioni e uno tarato su trecento non valgono uguale, e presentarli allo stesso modo è la
stessa disonestà di un `measured` inventato.

## Passo 4 — I prezzi che scadono

Lo schema ha già `price_verified_at: date | None` in `preflight_schema.py`, ma **nessuno lo
controlla**. Un preventivo calcolato su prezzi vecchi di sei mesi è sbagliato con sicurezza, ed è
la forma di errore peggiore per questo progetto: un numero preciso e falso.

Il minimo: `analyze` dichiara l'età dei prezzi che sta usando, e `doctor` avvisa quando sono
vecchi. Non serve andarli a prendere dalla rete — basta smettere di tacere su quanto sono datati.

## Dopo i quattro passi

**Deploy vero e proprio e piano di semi-marketing** per far provare il progetto: è la fase che
l'utente vuole subito dopo. Da definire con un piano suo. Nota utile per allora: prima di far
provare qualcosa a qualcuno serve che l'installazione sia riproducibile e che il primo avvio dica
da solo cosa fare — `doctor` esiste già per questo ed è un buon punto di partenza.

**La dashboard in stile Jarvis** viene **dopo i primi feedback**, per decisione dell'utente. È
anche l'ordine tecnicamente giusto: dopo il Passo 1 avrà il confronto stima/realtà da mostrare,
che è l'unica cosa che valga davvero una dashboard.

## Cosa NON fare prima

- **La parte C (esecuzione vera dei workflow).** Eseguire tool veri prima che la simulazione sia
  tarata significa spendere alla cieca proprio quando non si sa ancora di quanto si sbaglia. Dopo
  il Passo 1 il tetto di spesa obbligatorio poggerebbe su qualcosa di misurato. Restano i vincoli
  duri già stabiliti: flag letterale separato, tetto di spesa obbligatorio senza default, mai
  avviata da hook, report, doctor o dashboard.
- **Le segnalazioni misurate S1–S5.** Sono consigli, e un consiglio basato su stime non validate è
  la versione automatizzata del tirare a indovinare. Dopo i Passi 1 e 2 avrebbero dati veri sotto.

## Vincoli sempre in vigore

- **Nessun push e nessuna modifica remota senza consenso esplicito dell'utente.** Il push del
  16/08/2026 è stato autorizzato una volta, per permettere di continuare da telefono, e non vale
  come autorizzazione permanente.
- Non tracciare dati personali, transcript reali, database, log, segreti o percorsi home.
- Prima di dichiarare completo un lavoro: test pertinenti, `python -m pytest -q -W error` e
  `git diff --check`.
- Ogni test deve avere una regressione concreta che lo renda rosso.
