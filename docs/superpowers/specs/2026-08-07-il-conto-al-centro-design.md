# StarkEno — Trovare gli sprechi veri (design)

> Data: 2026-08-07. **Chiude i quattro punti aperti del §9 di
> `2026-08-07-aggancio-agenti-design.md`.** Quel documento resta valido su **come i dati
> entrano** — hook, grana, identità, schema, errori, dove vivono i dati. Questo dice
> **cosa si cerca dentro**, e la risposta non è quella che il §9 dava per scontata.
>
> **Seconda stesura.** La prima è stata demolita da una critica in sedici punti, quasi
> tutti fondati; le correzioni sono elencate in appendice B, ognuna con la misura che l'ha
> confermata o smentita. Il difetto peggiore era mio: dodici cifre diverse prodotte da
> script con filtri diversi. Adesso **ogni numero esce da una passata sola**,
> `scripts/misure/00_passata_canonica.py`.

---

## 1. A cosa serve StarkEno

**Trovare sprechi ed errori nel modo in cui lavori con Claude Code, e dire cosa fare.**
Non contare i token: contarli è il mezzo, non il fine — e contarli e basta è un problema
già affollato.

Fino a oggi il progetto cercava gli sprechi con quattro regole scritte **prima che
qualcuno avesse visto un transcript vero**, pensate per un «agente autonomo» generico. Su
27,6 giorni di lavoro reale non hanno trovato niente (§2). Non perché non ci fosse niente:
perché **guardavano dalla parte sbagliata**.

Lo spreco c'è, è grosso, ed è misurato. Sono cinque cose, e nessuna delle quattro regole
vecchie ne guarda una.

## 2. Perché le quattro regole vecchie non servono

Percorso completo, seconda volta e stavolta **con i timestamp veri**: i transcript in un
database usa-e-getta, 111 giri di `run_once`, **zero regole in errore**. L'infrastruttura
regge. Contando **tutte** le valutazioni, non solo l'ultima:

| Regola | Ha potuto valutare | Verdetto |
|---|---|---|
| R2 `expensive_model` | **207 volte su 2.055 (10%)** | mai una violazione. **Non è muta: è cieca** — nel 90% dei casi si astiene per «nessun modello frontier nella finestra» |
| R3 `spend_anomaly` | 2.055 su 2.055 (100%) | mai una violazione. Questa ha davvero guardato, e non ha trovato niente |
| R1 `loop` (asse progetto) | 748 su 2.055 (36%) | mai una violazione |
| R4 `steady_waste` | 2.055 | **153 violazioni → 14 alert su 13 progetti** |

> **La deduplica degli allarmi funziona, ed è dimostrato:** 153 valutazioni in violazione
> hanno prodotto **14 alert**, non 153. È `upsert_alert` con l'indice «un solo alert vivo».
> La prima stesura di questo documento citava «227 allarmi» — era il conteggio degli
> *istanti* di una prova diagnostica che scavalca il ciclo di vita. Etichetta sbagliata,
> codice sano.

E R4, l'unica che parla, parla a vuoto: `HEAVY_TOKENS` vale 25.000 token pesati per
chiamata, ma **la chiamata mediana ne vale 29.676**. La soglia sta sotto la mediana. Il
56,4% delle chiamate la supera. Non è tarata male: **descrive la normalità**, perché Claude
Code rimanda l'intera conversazione a ogni turno e dopo pochi scambi ogni chiamata è pesante
per costruzione.

*(Le 14 segnalazioni riguardano **13 progetti su 22 valutabili** — dei 30 presenti, 8 hanno
meno di 15 chiamate e restano sotto ogni soglia di occorrenza. La prima stesura diceva «13
su 13»: sovrastimato.)*

## 3. I cinque sprechi veri

Misurati chiedendo ai dati *cosa c'è*, invece di chiedere alle regole *se trovano qualcosa*.

### 3.1 Paghi per quello che non usi — e vale per sempre

```
strumenti offerti a Claude Code  1.128        skill elencate  185
strumenti davvero usati            123        skill usate      28
mai usati                        1.042 (92%)  mai usate       161 (87%)
```

Interi server collegati e **mai toccati in un mese**: Higgsfield AI (169 strumenti),
Adobe for creativity (82), un secondo Adobe (75), Vercel (33), un secondo Vercel (33),
Canva (32), computer-use (27), Motion (18), Gmail (16), Windsor.ai (16). **Circa 500
strumenti a zero utilizzi.**

Più **sei server che chiedono l'autenticazione e non possono funzionare** — peso morto
certo — presenti fino a **247 conversazioni**: Microsoft 365, Airtable, due di Airwallex,
Linear, Kling.

**Quanto costa, in base marginale.** La prima stesura diceva «~64.000 token pesati su una
sessione da 300 turni» — ed era **il gonfiaggio da rilettura appena bandito dal §6**,
commesso una sezione dopo averlo vietato. L'elenco sta nel prefisso più cacheabile che
esista: si paga una volta in `cache_write`, poi si rilegge a un decimo.

Rifatto (`10_le_regole_in_marginale.py`):

| | pesati |
|---|---|
| l'elenco messo in cache **una volta** | 2.669 |
| ~~lo stesso elenco riletto per 300 turni~~ | ~~64.050~~ ← contabilità sbagliata |
| **rimesso in cache ai cambi**, misurato: l'elenco cambia **594 volte**, in **99 sessioni più di una** | 2.669 × ~3,9 |
| **totale marginale per sessione** | **~12.963** |

Su 154 sessioni: **2,00 M marginali, l'1,59% della spesa marginale** — e attribuendo solo
la quota mai usata (92,4%), **l'1,47%**.

**Cade la classifica, non lo spreco.** La prima stesura lo promuoveva a «spreco col ritorno
migliore»: era una graduatoria costruita sulla base pesata, cioè sull'errore n° 5. **S1 vale
~1,5%, e la promozione era falsa.** Resta però l'unico dei cinque che si sistema **una volta
e vale per sempre** — che è un merito diverso, e va detto come tale.

> ⚠️ **È un pavimento, non il costo vero.** Il transcript registra l'**elenco** dei nomi,
> non le definizioni complete nel prompt di sistema — quelle non le scrive. Il costo reale è
> più alto di 1,47% e StarkEno **non può misurarlo**. Va scritto nella pagina, o il primo che
> confronta con `/cost` trova una discrepanza e smette di fidarsi.

### 3.2 La sessione lunga costa 3,6 volte per la stessa azione

| Posizione del turno | Costo medio per chiamata | Quota di rilettura |
|---|---|---|
| 1º – 10º | 15.825 | 29,8% |
| 31º – 60º | 27.325 | 52,8% |
| 121º – 300º | 49.253 | 65,6% |
| dal 301º | **72.914** | 57,0% |

La stessa identica azione costa **4,6 volte tanto** al turno 300 rispetto al turno 5. Non
perché sia più difficile: perché ti porti dietro la conversazione e la ripaghi ogni giro.

> **La quota di rilettura scende dal 65,6% al 57,0% dopo il turno 300 mentre il costo
> continua a salire.** Non è l'agente che diventa efficiente: `cache_read` **continua a
> crescere** (322.931 → 415.683 per chiamata), ma `cache_write` **raddoppia** (9.801 →
> 20.938) e pesa 1,25 contro 0,1. La quota scende perché gli altri pezzi crescono più in
> fretta — il contesto viene **rimesso in cache più spesso**.

**Il controfattuale, che alla prima stesura mancava.** Dire «questa sessione è cara» senza
sapere quanto costa ricominciare è un consiglio cieco: riavviare sposta la spesa dalla
rilettura (0,1) alla rimessa in cache (1,25) e a letture fresche. Misurato, **in marginale**:

| Turno | Costo marginale per chiamata |
|---|---|
| 1º – 3º | **18.761** ← si stabilisce il contesto |
| 4º – 10º | **6.675** ← il punto più economico |
| 61º – 120º | 15.202 |
| dal 301º | **31.346** |

Ricominciare costa ~56.000 marginali (i primi tre turni), poi si scende a ~6.675 contro i
31.346 che pagheresti restando: **il riavvio si ripaga in circa 3 turni.**

> ⚠️ **Quello che questa misura NON dice.** Il costo in token del riavvio è misurato; il
> costo di **ricostruire la comprensione** — la sessione nuova non sa cosa stavi facendo —
> non è nei dati e non lo sarà. Il consiglio va dato con questo limite scritto accanto.

> ⚠️ **S2 e S3 spingono in direzioni opposte**, e la prima stesura non lo notava: S3 dice
> «non rileggere», S2 dice «ricomincia», e ricominciare **obbliga** a rileggere. Convivono
> solo perché parlano di cose diverse — S3 della rilettura *inutile* dentro una sessione,
> S2 del costo di *restare*. La pagina deve poterlo spiegare in una riga, o si contraddice
> da sola davanti al primo utente attento.

### 3.3 Un quarto delle letture sono riletture inutili — non un terzo

La prima stesura diceva 35% e **contava anche `leggi → modifica → rileggi`**, che è il gesto
che questo stesso documento difende come il più comune che esista: dopo la modifica il file
**non è più lo stesso**, e rileggerlo non ricompra niente. Contarlo sarebbe stato ripetere
il peccato originale di R1.

Rimisurato col filtro:

```
letture con percorso                          1.370
riletture grezze                                453   33,1%
di cui dopo una SCRITTURA sullo stesso file     120   ← lavoro sano, il file è cambiato
RILETTURE VERE (nulla è cambiato)               333   24,3%
```

> ⚠️ **E anche 24,3% è ancora alto.** Dopo una **compattazione** il contenuto precedente
> non è più in contesto e rileggere è corretto. Il mio filtro sulle compattazioni **non ha
> funzionato** — ne ha trovate zero, che è falso — quindi la cifra vera è più bassa di
> 24,3%. **Va rifatto prima di tarare S3.**

### 3.4 Alcuni strumenti falliscono, ma non tutti i fallimenti sono guasti

La prima stesura mescolava tre cose diverse e ne deduceva «guasto nella configurazione».
Classificati i 475 fallimenti:

```
errore vero            232   48,8%
oggetto non trovato    151   31,8%     ← spesso il passo successivo va a segno
scaduto                 52   10,9%
permesso negato         29    6,1%
rifiuto dell'utente     11    2,3%     ← il sistema che FUNZIONA, non che si rompe
```

Ricalcolati i tassi **sui soli errori veri** e applicando il minimo di campione che S4
stessa impone (≥20 usi):

| Strumento | Usi | Falliti | Errori veri | Tasso vero |
|---|---|---|---|---|
| `mcp__claude_browser__computer` | 121 | 47 | 46 | **38,0%** ← regge |
| `preview_start` | 47 | 14 | 13 | 27,7% |
| `webfetch` | 77 | 20 | 20 | 26,0% |
| `powershell` | 503 | 44 | 35 | 7,0% |
| `mcp__claude_browser__navigate` | 82 | 18 | **5** | **6,1%** ← crolla da 22,0% |
| `bash` | 2.181 | 165 | 89 | **4,1%** ← da 7,6% |

**Il caso peggiore regge** (i suoi fallimenti sono quasi tutti errori veri), ma `navigate` e
`bash` si dimezzano o peggio. E **`readmcpresourcetool` al 100% esce**: n=5, sotto il minimo
che la regola stessa impone — era il caso più clamoroso della prima stesura, ed era rumore.

### 3.5 I fallimenti: due numeri, non uno

La prima stesura annunciava «i fallimenti costano il 7%». È quasi la riscrittura di «il 6,3%
delle chiamate fallisce»: 8,06 M su 443 chiamate fa **~18k marginali l'una** contro una media
di ~16k. **Una chiamata fallita costa quanto una qualsiasi.**

| | |
|---|---|
| costo diretto dei fallimenti | 8,06 M (6,4%) — **misura la frequenza, non lo spreco** |
| **costo dei rifacimenti identici** (46 volte) | **0,69 M — lo 0,55%** |

**Solo il secondo è recuperabile**, e parte del primo è informativa: i tre `navigate` falliti
che portano alla strada giusta sono esplorazione, non spreco. **Promettere un recupero del 7%
sarebbe una bugia.**

## 4. Le cinque segnalazioni

Ognuna nasce da una misura del §3, non da un'idea. Tutte confrontano **la sessione o il
progetto con se stesso**, mai con una soglia assoluta — è la lezione di R4.

| # | Nome | Scatta quando | Base misurata |
|---|---|---|---|
| **S1** | *Paghi per quello che non usi* | un server MCP o una skill sono presenti da N conversazioni con **zero** utilizzi, o un server chiede autenticazione e non l'ha | 92% strumenti, 87% skill; **~1,47% della spesa marginale** |
| **S2** | *Restare costa più che ricominciare* | il costo marginale per chiamata supera quello del **riavvio ammortizzato**. Una volta sola per sessione | riavvio ~56k, poi 6.675 contro 31.346: si ripaga in ~3 turni |
| **S3** | *Stai ricomprando quello che hai già* | un file già letto viene riletto **senza scritture né compattazioni in mezzo**, e il costo cumulato supera la soglia | 24,3% delle letture (e ancora da abbassare) |
| **S4** | *Questo strumento ti sta fallendo* | il tasso di **errori veri** — esclusi rifiuti, non-trovati e permessi — supera la soglia, su almeno **20 usi** | 38,0% sul peggiore; `navigate` scende a 6,1% |
| **S5** | *L'agente sbatte contro un errore* | la stessa azione si ripete **e fallisce** oltre `LOOP_MIN_FAILURES` | peggior caso sano = 2, sulla grana di produzione |

### S2 non è un rapporto, o sarebbe R4 un piano più in alto

La prima stesura la definiva «il costo per azione supera di N volte quello dei primi 10
turni». **Sembra un confronto interno ed è un timer travestito:** il rapporto cresce in modo
monotono per costruzione — è il contesto rimandato, che il §3.2 chiama giustamente
strutturale. Quindi **ogni sessione lunga e produttiva lo prenderebbe, prima o poi.** È
esattamente il timbro che ricevono tutti, cioè la malattia di R4.

**La forma corretta è una condizione con un significato, non una soglia:**

> scatta quando **continuare costa dimostrabilmente più che ricominciare** — cioè quando il
> costo marginale per chiamata attuale supera il costo di riavvio ammortizzato sui turni che
> la sessione sta ancora facendo.

Sono due numeri che StarkEno misura entrambi dallo storico dell'utente (§3.2), non una
costante. E **parla una volta sola per sessione**: il consiglio è un bivio, non un allarme
che si ripete.

> ⚠️ Il consiglio va dato con il suo limite accanto: **il costo in token del riavvio è
> misurato, quello di ricostruire la comprensione no.**

### S5 è R1 corretta, e il nome nuovo non è cosmetico

R1 contava le ripetizioni e per questo chiamava «bloccato» il lavoro normale: `read:App.tsx
→ edit:App.tsx` ripetuto tre volte in 42 secondi è il gesto più comune che esista. **Su
7.583 azioni: 0 catture giuste, 5 sbagliate.**

La correzione è che la ripetizione conta solo se **fallisce**. Ma questo **cambia il
fenomeno rilevato, non lo affina**, e va detto:

> ⚠️ **Punto cieco dichiarato: il loop silenzioso e riuscito.** Un agente che rilegge e
> riscrive lo stesso file all'infinito, con ogni azione «riuscita», **non viene preso da
> nessuno**. Non è una svista: con i segnali disponibili non è distinguibile dal lavoro
> sano — è la stessa sequenza. Per questo la regola cambia nome: non dice più «l'agente è
> bloccato», dice **«l'agente sbatte contro un errore»**, che è quello che sa vedere.

**Il rilevatore B (cicli) si spegne, esplicitamente.** Con la guardia sui fallimenti
servirebbero 4 fallimenti su 6 azioni coinvolte — il 67% — contro un tasso base del 6,3%.
Misurato sui dati veri: **5 finestre su 6.424, lo 0,078%**. Lasciarlo acceso significa
tenere in vita codice testato che non scatterà mai, e un invariante in `config.py` che
passa mentre la regola è morta. **Si disattiva con una costante, e il perché sta scritto
accanto.**

**La calibrazione, rifatta sulla grana giusta.** La prima stesura misurava azione per
azione, ma §5 decide che in produzione esiste **una riga per chiamata**: R1 vedrà meno
azioni e meno fallimenti. Rimisurato su quel modello — 7.027 righe, 443 fallite (6,3%),
**il 6,7% dei fallimenti invisibile per costruzione** — il peggior caso sano è **ancora 2**:
158 finestre lo toccano, **nessuna arriva a 3**. `LOOP_MIN_FAILURES = 4`, il doppio, con
margine.

> ⚠️ **Invariante nuovo in `config.py`.** `LOOP_MIN_FAILURES` deve restare sotto
> `LOOP_MIN_REPEATS` (10), altrimenti chiede più fallimenti di quante azioni il rilevatore
> possa coinvolgere e S5 diventa **impossibile da far scattare**, muta senza che nessun
> test lo dica. Margine atteso: +6.

### Quello che StarkEno può consigliare, e quello che non può

S1 mantiene la promessa del progetto — *suggerire cosa installare e cosa usare al posto di
cos'altro* — dentro un confine che va dichiarato:

| Può | Come |
|---|---|
| «hai questo e non l'hai mai usato: toglilo» | misurato, offerto contro usato |
| «questo server non è autenticato: autorizzalo o rimuovilo» | misurato, `needsAuthMcpServers` |
| «questa skill costa caricarla, quest'altra costa usarla» | misurato, §6 |
| **Non ancora** | |
| «hai installata una skill che fa il lavoro che stai facendo a mano» | **nessuna misura sotto.** È l'unica capacità che richiede un giudizio **semantico** sulle descrizioni; le altre righe sono conteggi. Sta nei punti aperti (§10), non fra le promesse |
| **Non può** | |
| «installa una skill che non hai» | servirebbe un catalogo esterno. **Fuori scope**, e va scritto invece di essere scoperto |

### Le soglie non sono le mie — StarkEno se le calcola a casa di chi lo installa

**Ogni numero di questo documento viene dai transcript di una persona sola.** Un altro
utente ha altre skill, altri server MCP, altre abitudini: il suo `bash` può fallire il 20%
per ragioni di sistema, può lavorare solo in sessioni corte, può usare tutto ciò che ha
installato. **Spedirgli le mie soglie sarebbe l'errore di R4 un livello più in alto** — una
soglia tarata su un caso e applicata a tutti.

**Due regole di costruzione, non negoziabili:**

1. **Nessuna regola nomina uno strumento, una skill o un server.** S1 confronta offerto e
   usato *qualunque cosa siano*; S4 calcola una frazione *su qualunque strumento tu usi*.
   Un elenco di nomi dentro il codice sarebbe il mio setup spedito a sconosciuti.
2. **Ogni soglia si deriva dallo storico di chi installa.** StarkEno fa sulla macchina
   dell'utente ciò che `scripts/misure/` ha fatto qui.

> ⚠️ **Ma NON con la formula «il massimo osservato, per due».** Qui ha funzionato perché
> **ho guardato i 5 casi uno per uno e li ho giudicati sani.** Sulla macchina dell'utente
> non c'è nessuno che etichetta: la formula diventa «2× il massimo», e **se in quello
> storico c'è una patologia vera, la soglia si alza sopra la patologia e S5 tace proprio
> per l'unico utente che aveva qualcosa da trovare.** L'autotaratura si disarmerebbe da
> sola davanti al caso che deve prendere.
>
> **Serve una statistica robusta** — un quantile alto (p99), che una manciata di casi
> patologici non sposta — **più un tetto assoluto oltre il quale la soglia non sale**,
> qualunque cosa dica lo storico. Il tetto è la sola difesa contro uno storico già malato.

> ⚠️ **E la tabella di stabilità qui sotto dimostra meno di quanto sembri.** Un massimo è
> **monotono non decrescente**: «non si è mosso per 25 giorni» significa solo che niente di
> più grande è comparso. È fortuna documentata, non una proprietà. Con un quantile la
> verifica va **rifatta**, e stavolta dirà qualcosa.

**Quanto ci mette a tararsi** (`09_quanto_serve_per_tararsi.py`, formula del massimo):

| Giorni | Righe viste | Peggior caso sano di S5 |
|---|---|---|
| 1 | 312 | 1 |
| 2 | 644 | 2 |
| **3** | **651** | **2** ← da qui non si muove più |
| 28 | 8.057 | 2 |

Indicativamente **tre giorni, ~650 azioni**. S4 invece non dipende dai giorni ma dagli
**usi**: dopo 3 giorni solo 7 strumenti avevano ≥20 utilizzi, dopo 28 giorni 28. Quindi
**S4 giudica uno strumento alla volta, quando quello strumento ha abbastanza usi** — non
quando è passato abbastanza tempo.

**Cosa succede prima che sia tarata.** Il conto **non ha soglie**: è conteggio, funziona
dal primo minuto. E due segnalazioni non richiedono taratura perché non hanno una soglia
da tarare: **un server che chiede autenticazione** (binario) e **un server con zero
utilizzi** (zero non è una soglia). Quindi:

| Quando | Cosa dice StarkEno |
|---|---|
| primo avvio | il conto, i server non autenticati, quelli a zero utilizzi |
| dopo ~3 giorni | S5, S2, S3 con le soglie dell'utente |
| appena uno strumento arriva a ~20 usi | S4 su quello strumento |

### Cosa è strutturale e cosa è mio

| Fatto | Vale per chiunque? |
|---|---|
| il costo per azione cresce col numero del turno | **sì, strutturale**: è il contesto rimandato. Verificato su 5 settimane separate, sessioni lunghe in tutte (4, 6, 5, 5, 5) |
| i fallimenti costano una chiamata intera | **sì, strutturale** |
| strumenti e skill non usati occupano il contesto | **sì, strutturale** |
| rileggere un file già letto lo ricompra | **sì, strutturale** |
| 92% inutilizzato, 3,6×, 35%, 38,8%, caso sano = 2 | **no, sono miei.** Sono la prova che il metodo funziona, **non costanti universali**, e nel codice non ci devono entrare |

## 5. Come i dati entrano (chiude i punti 1 e 2 del §9)

**Una riga per `(sessionId, message.id)`.** Il §4 del documento precedente aveva ragione:
è la grana della spesa e la chiave di idempotenza.

**Punto 2 — le chiamate con più azioni dentro.** La misura che decide: **l'attribuzione sta
sulla riga della chiamata, non sulla singola azione** (righe `assistant`). Spezzare non
affinerebbe l'attribuzione, **la duplicherebbe**. E dentro le chiamate multiple — 10,3% del
totale — il **61,6% ripete lo stesso strumento**: non sono cose diverse, è la stessa cosa
in parallelo su più file.

Quindi: **una riga**, con il primo `tool_use` come etichetta.

> ⚠️ **`azione_fallita` ha UN solo significato: l'esito dell'azione etichettata.** Con tre
> azioni in una riga, due lettori ne costruirebbero due sistemi diversi. Conseguenza
> dichiarata e misurata: **il 6,7% dei fallimenti resta invisibile**.

> ⚠️ **Quando si conosce l'esito.** Il risultato di uno strumento arriva nel messaggio
> *successivo*: al momento in cui l'hook scrive la riga potrebbe non esserci. Misurato:
> **3 esiti su 8.053 restano irrisolti (0,04%)** — nella pratica arriva quasi sempre. Ma
> `azione_fallita` **non deve valere «falso» per «non lo so»**, o sia S5 sia il costo degli
> errori diventano ottimisti per costruzione. Si registra `esito_noto` accanto, e **la
> pagina dichiara quanti esiti mancano.**

**`azioni_nella_chiamata`: decisa, non rimandata.** La prima stesura scriveva «se non entra
nella pagina non si aggiunge», che è una regola, non una decisione — e il §7 non la nominava.
**Decisione: si aggiunge, e il suo lettore è la riga d'intestazione del conto** («8.053
azioni in 7.027 chiamate»), che serve a spiegare perché il numero di azioni e quello di
chiamate non coincidono. Senza quella riga il lettore attento trova due totali diversi e non
sa quale credere. **È in §7 fra i contenuti della pagina, o non si aggiunge davvero.**

## 6. Il conto — e l'errore che lo rendeva un artefatto

> **Questa è la correzione più importante della seconda stesura.** La prima annunciava
> «Claude Browser ti costa il 12,1% di tutto» come numero-bandiera del progetto. **Era un
> artefatto.**

Claude Code rimanda l'intera conversazione a ogni turno, e la rilettura della cache è
**il 58,8% di tutta la spesa pesata** (178,9 M su 304,3 M). Attribuire i token pesati di
una chiamata allo strumento invocato in quella chiamata significa **addebitargli tutta la
storia precedente della sessione**, e ri-addebitarla a ogni turno successivo.

| | base pesata (sbagliata) | base marginale (corretta) |
|---|---|---|
| Claude Browser | 12,0% | **4,5%** |
| improve-animations | 2,2% | **0,3%** |
| ui-ux-pro-max | 1,4% | 0,4% |
| superpowers:subagent-driven-development | 2,0% | **2,3%** |
| handoff | 1,2% | **2,2%** |

**Non è un ridimensionamento, è un riordino:** `handoff` sembrava quasi gratis e costa il
doppio del previsto; `improve-animations` sembrava caro sette volte più del vero.

**Regola: l'attribuzione a skill, plugin, server MCP e sub-agente usa la base MARGINALE** —
`input + cache_write + output`, senza la rilettura. La rilettura è causata dalla sessione,
non dallo strumento, e ha già la sua voce: §3.2.

### Ma il marginale va spaccato in due, o nasce l'artefatto opposto

`cache_write` atterra sulla **prima chiamata che provoca il caricamento**, etichettata con
lo strumento che capita lì. Misurato, la composizione del marginale cambia radicalmente da
skill a skill:

| Skill | `cache_write` | `output` | Come si legge |
|---|---|---|---|
| `handoff` | **90%** | 10% | costa **caricarla** |
| `claude-handoff` | 97% | 3% | idem, estremo |
| `superpowers:subagent-driven-development` | 78% | 22% | |
| `ui-ux-pro-max` | 32% | **68%** | costa **usarla** |
| `improve-animations` | 29% | 71% | idem |

`handoff` era «raddoppiato» rispetto alla base pesata (1,2% → 2,2%) — ed era questo: **la
messa in cache di un documento grosso, non lavoro svolto.**

**Il conto mostra due colonne, non una:** *costo di caricamento* (`cache_write`) e *costo di
lavoro* (`input + output`). Una skill cara da caricare e leggera da usare è un problema
diverso da una leggera da caricare e cara da usare — e il consiglio che ne deriva è
opposto. **Sommarle in un numero solo rifà l'errore n° 5 in direzione contraria.**

### Partizioni ed etichette non sono la stessa cosa

| Ripartizione | Tipo | Somma al totale? |
|---|---|---|
| progetto, modello, sessione | **partizione** | **sì**, ed è un test |
| skill, plugin, server MCP, sub-agente | **etichetta** | **no**: si sovrappongono e non coprono tutto |

Una chiamata può stare insieme nella skill `loop`, in un sub-agente e nel server Claude
Browser. **La pagina deve dirlo**, e il test §8 deve pretendere la somma **solo dalle
partizioni**, o fallirà a ragione o si sommerà due volte.

### Il tetto, in euro e non in token

Il tetto va chiesto in una **unità che l'utente conosce**. Nessuno sa rispondere a «quanti
token pesati alla settimana?». Serve una **tabella prezzi per modello** in `config.py`: un
conto senza valuta è un altro numero grande, e il §11 esclude la *fatturazione*, non la
*stima di costo*.

> ⚠️ **Ma gli euro non risolvono il problema per chi è su abbonamento**, e sono la
> maggioranza. Chi usa Claude Code con un piano **non paga per token**: gli euro derivati
> dai prezzi API sono un costo **nozionale**, non la sua bolletta, e il vincolo che sente è
> il limite di piano — che il transcript non contiene. Per lui «quanto vuoi spendere» resta
> senza risposta utile.
>
> **Tre forme, e vanno offerte tutte e tre invece di sceglierne una sbagliata per due terzi
> degli utenti:**
>
> | Chi | Tetto |
> |---|---|
> | utente API | **in euro**, dalla tabella prezzi |
> | utente su abbonamento | **relativo**: «non più della tua media a 4 settimane» — non serve conoscere il piano |
> | chi non configura niente | **nessun tetto**: il conto c'è lo stesso, la previsione tace |

> ⚠️ **La tabella prezzi invecchia in silenzio.** Porta una **data**, e vale la regola della
> sentinella applicata qui: **prezzo sconosciuto → dichiarato come sconosciuto, mai zero.**
> Un modello nuovo con prezzo zero farebbe sparire una fetta di spesa dal conto senza un
> errore — è l'invariante 9 in forma nuova.

> ⚠️ **Verificato: il transcript non sa niente dei limiti di piano.** Cercati tutti i campi
> che contengono `limit`, `quota`, `reset`, `remaining`, `plan`, `tier`: gli unici riscontri
> sono parametri degli strumenti e file della modalità piano. **Il tetto lo dà l'utente.**

> ⚠️ **La settimana mobile non ha un residuo, e la prima stesura prometteva una scadenza
> che non poteva mantenere** («hai consumato il 68% della settimana e mancano 3 giorni»: su
> una finestra mobile mancano sempre zero giorni). La forma corretta è **la proiezione
> dell'attraversamento**: la somma mobile a 7 giorni contro il tetto, più il ritmo, dà una
> data di sorpasso senza bisogno di sapere quando il piano si rinnova. Se l'utente
> configura la data di rinnovo, si usa quella ed è esatta.

### Il fuso e il confine del giorno

Tutto è **UTC** fino a `db.UTCDateTime` (invariante 1). **Il conto è l'unico posto che
converte**, e converte nel fuso locale della macchina: «ieri» deve voler dire ieri per chi
legge. Il confine del giorno cambia il ritmo giornaliero, la finestra a 7 giorni e la riga
di inizio sessione — **va deciso qui, non tre volte in tre posti.**

## 7. La faccia

Due facce, **nessun processo acceso** — il §3 del documento precedente resta intatto.

| Faccia | Cosa | Quando |
|---|---|---|
| **la riga** | una riga a inizio sessione: la segnalazione più cara aperta, o niente | automatica, hook di inizio sessione |
| **la pagina** | un comando **scrive** un file HTML e lo apre: i cinque sprechi, le ripartizioni, il ritmo, il tetto | su richiesta |

La pagina si scrive, non si serve: nessun `api.py` acceso, nessuna porta. Screenshot per il
README senza reintrodurre il demone.

La pagina porta anche la riga d'intestazione **«N azioni in M chiamate»** — il lettore di
`azioni_nella_chiamata` (§5), senza il quale due totali diversi restano inspiegati.

**La riga tace quando non c'è niente da dire.** Una riga a ogni avvio diventa rumore di
fondo e si smette di leggerla — che è il fallimento peggiore secondo il progetto stesso.

> ⚠️ **«La riga tace» più «tre giorni di taratura» fa un plugin muto appena installato**, che
> è il momento in cui si decide se tenerlo. Regge **solo** perché al primo avvio S1 ha già
> qualcosa da dire senza taratura: server non autenticati e server a zero utilizzi. **È
> quello a salvare l'avvio, e va detto** — se un utente li avesse tutti a posto, il primo
> avvio sarebbe silenzioso e va previsto un messaggio di benvenuto che almeno mostri il conto.

> **Una riga di onestà che la pagina deve portare:** *StarkEno misura quello che spendi, non
> quello che ottieni.* Tutte e cinque le segnalazioni guardano il costo e nessuna il valore:
> la sessione lunga è cara ma può essere quella che ha finito il lavoro; la skill mai usata
> è gratis da tenere e utile il giorno che serve; parte dei fallimenti è esplorazione. Un
> ottimizzatore con una metrica sola spinge verso «lavora meno». **Dirlo per primi costa
> poco, ed è la prima obiezione di ogni lettore scettico.**

**La dashboard esistente mostra il prodotto vecchio** — allarmi per agente, stato regole,
battito. Resta dov'è, opzionale e non aggiornata, come già il §3 dice per il server MCP e
il demone.

## 8. Come si verifica

Restano le quattro prove sull'hook del §10 precedente.

> La prima stesura ne aggiungeva cinque, e **quattro regole su cinque restavano senza
> prova**: copriva S5 — l'unica che non scatterà mai — e lasciava scoperte le quattro che
> scatteranno. Un contratto di verifica che protegge solo il codice morto.

**Una prova per ogni regola, al confine.** Ognuna ha la stessa forma: il caso sano peggiore
misurato deve dare `OK`, il caso appena oltre deve violare. È l'unico modo di testare la
soglia invece che il ramo.

| Regola | Deve dare `OK` | Deve violare |
|---|---|---|
| **S1** | server usato anche una volta sola | server a **zero** usi da N conversazioni; server non autenticato |
| **S2** | sessione dove restare costa **meno** del riavvio | sessione oltre il pareggio — **e parla una volta sola**: il test lo pretende |
| **S3** | `leggi → modifica → rileggi` sullo stesso file; rilettura dopo compattazione | rilettura senza niente in mezzo |
| **S4** | strumento con 19 usi e 19 fallimenti (**sotto il minimo di campione**); strumento i cui fallimenti sono **rifiuti dell'utente** | 20+ usi e tasso di **errori veri** oltre soglia |
| **S5** | **2 fallimenti** della stessa azione — il peggior caso sano reale | **4 fallimenti** |

> Le due prove di S5 sostituiscono le tre della prima stesura: «l'agente finto nel vicolo
> cieco» e la regressione a 4 fallimenti **erano la stessa prova scritta due volte**.
> E rigiocare i 5 falsi positivi **non basta**: hanno ~0 fallimenti e passerebbero con
> qualunque soglia ≥1, quindi **non testano il 4**. Serve il confine.

**Più tre prove sui conti:**

6. **Le partizioni quadrano, le etichette no** — progetto e modello sommano al totale;
   skill/MCP/sub-agente **non devono** essere sommate, e il test lo pretende.
7. **L'attribuzione è marginale, e spaccata in due** — fallisce se qualcuno rimette i
   pesati, o se somma caricamento e lavoro in un numero solo. Stessa classe
   dell'invariante 10: due grandezze diverse che si somigliano.
8. **La regressione sul doppio conteggio** — 2,04 righe di transcript, 1 riga scritta.

Metodo, invariato: **rieseguire la misura su transcript veri.** `scripts/misure/`.

## 9. Dove vivono i dati

Il §8 del documento precedente resta parola per parola, e **va fatto prima di pubblicare**:
il database sta accanto al codice, le cartelle dei plugin sono versionate, e il primo
aggiornamento **cancella lo storico** senza errore e senza avviso.

**Aggiunta:** non basta cambiare `DB_PATH`. Chi ha già un database va **spostato**, non
lasciato indietro — serve un passo di migrazione che trovi il vecchio file, lo copi nella
cartella dati e lo dichiari. Se la storia è il prodotto, perderla all'aggiornamento è
perdere il prodotto.

## 10. Cosa resta aperto

1. **Quale ripartizione va in cima alla pagina.** Si decide guardando una bozza.
2. **Come si calcola il costo composto di un risultato grosso.** Il tentativo è fallito
   in modo istruttivo: la stima «4 caratteri = 1 token» ha prodotto **il 107% della spesa
   totale**, impossibile, perché le immagini non si contano così. Il fenomeno esiste —
   un'immagine da 150k caratteri portata per 360 turni — ma il numero è da rifare con una
   stima che distingua testo e immagini.
3. **Il valore di partenza delle soglie, prima che l'utente abbia tre giorni di storia.**
   La forma è decisa (§4: si derivano dallo storico di chi installa), ma nei primi giorni
   un valore serve. Le due possibilità sono **tacere finché non è tarata** — sicuro, ma un
   plugin muto per tre giorni si disinstalla — oppure **partire con un valore prudente e
   sostituirlo**. Va deciso, e il valore prudente **non può essere il mio**: va derivato
   dalla forma della distribuzione, non dal mio massimo.
4. **Il modello di fascia alta su lavoro meccanico** (6,4% delle chiamate, 6,2% della
   spesa) è un candidato sesto spreco, **non dimostrato**: il modello lo sceglie la
   sessione, non la chiamata, e cambiarlo a metà sessione ricostruirebbe la cache. Va
   studiato prima di diventare una regola.
5. **Il filtro sulle compattazioni per S3 non funziona.** Il mio ne ha trovate **zero**, che
   è falso, quindi il 24,3% è ancora sovrastimato. **Va rifatto prima di tarare S3**, o S3
   segnalerà come spreco una rilettura che dopo una compattazione è obbligata.
6. **La stabilità dell'autotaratura va rimisurata col quantile.** La tabella dei tre giorni
   usa il massimo, che è monotono non decrescente: dimostra fortuna, non una proprietà
   (§4). Con un p99 la verifica dirà qualcosa — e va rifatta prima di spedire.
7. **«Hai una skill che fa il lavoro che stai facendo a mano.»** È la capacità che mantiene
   davvero la promessa *suggerire cosa usare al posto di cos'altro*, ma richiede un giudizio
   semantico sulle descrizioni delle skill: costoso, non specificato, e senza una misura
   sotto. **Va dimostrata con un esempio misurato prima di essere promessa.**

## 11. Fuori scope

SaaS, autenticazione, multi-tenancy, **fatturazione** (la *stima di costo* invece serve,
§6). Provider diversi da Claude. Una quarta fascia per Fable. La dashboard sempre viva.
**Consigliare skill o plugin che l'utente non ha installato**: servirebbe un catalogo
esterno.

---

## Appendice A — le misure del 07/08/2026

Fonte unica: `scripts/misure/00_passata_canonica.py`.

**Il campione — un nome per ogni cifra**
```
475 file .jsonl · 37.692 righe · 15.835 con `usage` · 292 <synthetic> scartate
7.624 CHIAMATE API uniche  ·  7.027 con almeno uno strumento  ·  8.053 BLOCCHI tool_use
2,04 righe di transcript per chiamata  (conferma il 2,03× su dati 4× più grandi)
```
> **Il corpus cresce mentre lo si misura**: le sessioni in corso scrivono sul proprio file.
> Fra due esecuzioni a un'ora di distanza i totali si muovono di qualche unità. È il motivo
> per cui ogni cifra va accompagnata dalla data della passata.

**Chiuso il §4 del documento precedente:** il 4,6% delle chiamate ha righe con `usage`
diversi, e nel **100%** di quei casi l'**ultima** è anche la più alta.

**Sessioni** — mediana 13 azioni, p90 160, massimo 625. Solo il 31,4% arriva a 20 azioni,
ma quelle contengono l'**88,5% del lavoro**.

**S5 / R1** — soglia storia da 20 a 1: **227 istanti di violazione in entrambi i casi**,
nessuno nuovo (`LOOP_MIN_HISTORY` resta 20). 5 violazioni distinte, **tutte lavoro sano**.
11 finestre di ripetizione ≥10: 10 con zero fallimenti, 1 con uno. Peggior caso sano sulla
grana di produzione: **2**, mai 3. Rilevatore B raggiungibile nello **0,078%** dei casi.

**Spesa** — 304,3 M pesati, di cui **178,9 M (58,8%) di sola rilettura**; marginale 125,4 M.
Fasce: frontier 62,6%, standard 37,0%, economy 0,4% — sommano a 100% e **nessun modello
resta non riconosciuto** (anche `claude-haiku-4-5-20251001` col suffisso). Il punto cieco di
R4 era standard+economy = **37,4%**.

**Sprechi** — installato/usato: 1.128 strumenti offerti, 123 usati (92,4% mai);
185 skill elencate, 28 usate (87,0% mai); 6 server non autenticati fino a 247 conversazioni;
elenco mediano ~2.135 token. Sessione lunga **3,6×** per azione. Riletture **479/1.370
(35,0%)**. Fallimenti **443**, costo **8,76 M marginali (6,98%)**. Strumento peggiore
**38,8%**.

**Non trovato** — nessun campo sui limiti di piano.

## Appendice B — la critica alla prima stesura, punto per punto

| # | Obiezione | Esito |
|---|---|---|
| 1 | calibrazione su una grana che §5 elimina | **fondata**, rimisurata sulla grana di produzione: peggior caso ancora 2, 6,7% dei fallimenti invisibile |
| 2 | la guardia cambia il fenomeno | **fondata in pieno**: regola rinominata, punto cieco dichiarato (§4) |
| 3 | rilevatore B morto | **fondata, confermata**: 0,078%. Si spegne esplicitamente |
| 4 | «68% e mancano 3 giorni» impossibile su finestra mobile | **fondata**: sostituita dalla proiezione di attraversamento (§6) |
| 5 | attribuzione gonfiata dal contesto | **fondata, la più grave**: base marginale, 12,0% → 4,5% (§6) |
| 6 | ripartizioni non esclusive | **fondata**: partizioni ed etichette separate, test corretto |
| 7 | sentinella ottimista | **fondata**, ma misurata piccola: 3 esiti su 8.053 (0,04%). `esito_noto` aggiunto |
| 8 | R2 non muta, non calcolabile | **fondata**, rimisurata: 207 valutazioni possibili su 2.055 |
| 9 | manca la deduplica degli allarmi | **respinta con prova**: 153 violazioni → 14 alert. Era sbagliata l'etichetta «227 allarmi» |
| 10 | il motore non produce nulla | **fondata**: le quattro regole vecchie escono, cinque nuove entrano (§4) |
| 11 | la regressione non difende il 4 | **fondata**: fixture al confine (§8.2) |
| 12 | tetto in token, inconfigurabile | **fondata**: tabella prezzi e tetto in euro (§6) |
| — | 22 progetti contro «13 su 13» | **fondata**: 30 progetti, 22 valutabili, 13 segnalati |
| — | cinque totali diversi | **fondata, colpa mia**: una passata canonica, ogni cifra col suo nome |
| — | 474/474 sospetto | **coincidenza, dimostrata**: 357 file su 475 non hanno **nessun** errore, uno ne ha 39 |
| — | fuso, migrazione, `CLAUDE.md`, colonna orfana | **fondate**: §6, §9, §5 e il `CLAUDE.md` da correggere insieme a questo |

## Appendice C — la seconda critica, punto per punto

L'accusa di fondo era una sola e giusta: **il §6 aveva bandito la base pesata per
l'attribuzione, ma il §3 — che giustifica le regole nuove — la usava ancora.** Rimisurato
tutto con `10_le_regole_in_marginale.py`.

| # | Obiezione | Esito |
|---|---|---|
| 1 | §3.1 usa la contabilità che §6 vieta | **fondata**: 64.000 → **~12.963** marginali per sessione. S1 vale **1,47%**, non è «il ritorno migliore»: la classifica era costruita sull'errore n° 5 |
| 2 | S2 è un timer travestito da rapporto | **fondata**: il rapporto cresce in modo monotono, ogni sessione lunga lo prenderebbe. Ridefinita come **«continuare costa più che ricominciare»**, una volta per sessione |
| 3 | il consiglio di S2 non ha controfattuale | **fondata, e misurato**: riavvio ~56k, poi 6.675 contro 31.346 → **si ripaga in ~3 turni**. Il consiglio regge in token; il costo di ricostruire la comprensione **resta non misurabile e va dichiarato**. Notata anche la tensione S2↔S3 |
| 4 | §3.3 ricommette il peccato di R1 | **fondata**: 120 riletture su 453 seguono una scrittura. **35% → 24,3%**, e il filtro sulle compattazioni non funziona: la cifra vera è più bassa (§10.5) |
| 5 | §3.4 confonde tre tipi di fallimento | **fondata**: classificati — 48,8% errori veri, 31,8% non trovati, 2,3% rifiuti. `navigate` **22,0% → 6,1%**, `bash` 7,6% → 4,1%; il peggiore **regge a 38,0%**. `readmcpresourcetool` al 100% **esce**: n=5, sotto il minimo che S4 stessa impone |
| 6 | l'autotaratura si disarma da chi ne ha bisogno | **fondata, ed è la più insidiosa**: «2× il massimo» si alza sopra una patologia presente nello storico. Sostituita da **quantile alto + tetto assoluto**. Concesso anche che un massimo è monotono: la tabella di stabilità **documenta fortuna** |
| 7 | il tetto in euro non serve a chi è su abbonamento | **fondata**: tre forme — euro (API), **relativa alla propria media a 4 settimane** (abbonamento), nessuna |
| 8 | §3.5 misura la frequenza, non lo spreco | **fondata**: 18k per chiamata fallita contro 16k di media. Separati: **6,4% diretto (≈ la frequenza) e 0,55% recuperabile** |
| 9 | `cache_write` attribuito a chi capita | **fondata, e confermata**: `handoff` è **90% cache_write / 10% output**, `ui-ux-pro-max` 32/68. Non si corregge: **si mostra**, in due colonne — costo di caricamento e costo di lavoro |
| 10 | quattro regole su cinque senza prova | **fondata**: una prova al confine per ognuna (§8) |
| 11 | «hai una skill che fa quel lavoro» senza misura | **fondata**: spostata nei punti aperti (§10.7) |
| 12 | colonna indecisa, tabella prezzi senza regole | **fondata**: `azioni_nella_chiamata` decisa con il suo lettore in §7; tabella prezzi **con data** e **prezzo sconosciuto → dichiarato, mai zero** |
| — | quota di rilettura non monotona dopo il turno 300 | **fondata**: spiegata — `cache_read` continua a crescere, ma `cache_write` raddoppia e pesa 1,25 contro 0,1 |
| — | §8.1 e §8.2b sono la stessa prova | **fondata**: unificate |
| — | «la riga tace» + tre giorni di taratura = plugin muto | **fondata**: regge solo perché S1 parla dal primo avvio senza taratura, **e ora è scritto** |
| — | tutte misurano il costo, nessuna il valore | **fondata**: una riga di onestà nella pagina (§7). Dirlo per primi costa poco |
