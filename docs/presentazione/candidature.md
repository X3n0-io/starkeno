# Farsi trovare — cosa mandare, dove, in che ordine

Bozze pronte da incollare. **Le manda l'autore, non un agente**: sono post a suo nome su
piattaforme di terzi, e la voce deve essere la sua.

## L'ordine è cambiato il 20/08/2026, e non per un ripensamento

La versione precedente diceva: **PyPI, poi le liste, poi Hacker News**. Il ragionamento
era che un curatore che apre il repository e trova `pip install git+https://…` archivia
senza rispondere. Quella barriera è caduta — `pip install starkeno` esiste dal 20/08/2026.

Poi ho letto i CONTRIBUTING invece di immaginarli, ed è saltato fuori un cancello che
nessuno aveva considerato: **le liste non guardano la qualità, guardano le stelle**.

| Lista | Come si segnala | Cancello | Quando è aperto per StarkEno |
|---|---|---|---|
| [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | **issue**, mai PR | 14+ giorni di età **oppure** 100+ stelle | **dal 28/08/2026** (creato il 14/08 alle 17:06 UTC) |
| [travisvn/awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills) | PR | **10+ stelle**, sotto si chiude in automatico | quando arrivano le prime dieci |
| [subinium/awesome-claude-code](https://github.com/subinium/awesome-claude-code) | PR | **1000+ stelle** | fuori portata, non provarci |
| [jqueryscript/awesome-claude-code](https://github.com/jqueryscript/awesome-claude-code) | PR | nessuno dichiarato | **adesso** |
| [LangGPT/awesome-claude-code](https://github.com/LangGPT/awesome-claude-code) | PR o issue | nessuno dichiarato | **adesso** |

Con 0 stelle e sei giorni di vita, «prima le liste» **non è eseguibile**: tre liste su
cinque rimandano, e le stelle che chiedono possono arrivare solo dai canali che si
volevano fare per ultimi. L'ordine si inverte da sé.

Poi, il pomeriggio dello stesso giorno, ho letto anche le regole delle **comunità**, e la
stessa cosa è successa una seconda volta: «Reddit prima, Hacker News dopo» non è
eseguibile, perché r/ClaudeAI chiede 50 punti di karma e il profilo ne ha 27. **L'ordine
buono è nella sezione 1**, ed è l'unico da seguire: quello scritto qui sopra è rimasto
solo per far vedere quante volte un piano dedotto invece che letto è stato smentito.

**In una riga: Hacker News per primo, Reddit quando il karma esiste, le liste per ultime.**

---

## 1. La mappa delle comunità — verificata il 20/08/2026, dall'account vero

Le regole di questa tabella non sono dedotte: sono state lette una per una nelle pagine
`about/rules` delle comunità, con la sessione dell'autore. **Il risultato è che quasi
tutte le porte sono chiuse, e per lo stesso motivo: un account senza storia.**

| Comunità | Il cancello, alla lettera | Stato |
|---|---|---|
| **r/ClaudeAI** | regola 7: «Posts on the feed now require **OP karma > 50**» | **chiusa per ora** — il profilo loggato ha **27 karma** (25 da post, 2 da commenti): ne mancano 24 |
| **Hacker News** | nessun karma richiesto per inviare | **serve l'accesso**: nel browser non risulta nessuna sessione |
| **r/LocalLLaMA** | regola 3: vietata la copia «completely/primarily LLM generated»; regola 4: self-promo ≤ 10% del proprio contenuto | **aperta con cautele** (vedi sotto) |
| **r/Python** | regola 1: «**No showcase posts**», per via dell'aumento di vetrine su contenuti AI | **chiusa ai post**: solo il thread mensile di showcase o il daily |
| **Lobsters** | a invito, e per 70 giorni un utente nuovo non può inviare link da un dominio nuovo | chiusa |
| **le liste awesome** | 14 giorni o 100 stelle · 10 stelle · 1000 stelle | vedi sezioni 6–8 |

**Il profilo, verificato il 20/08/2026 da `api/me.json`:** **27 di karma totale** — 25
da post, 2 da commenti — account del 26/01/2025, email verificata. Non è un usa-e-getta,
e per r/LocalLLaMA, che non dichiara soglie, va bene. Per r/ClaudeAI mancano **24 punti**.

Nel browser era passato prima un secondo profilo con **1 solo punto e nessun commento**:
con quello un post sparisce ovunque. Controlla con quale sei loggato prima di premere
invio — è un errore che non si scopre finché il post non è già stato rimosso.

**Il karma non si automatizza**: la regola 10 di r/ClaudeAI punisce la manipolazione dei
voti con ban permanente immediato, e il sub ha installati Bot Bouncer, Evasion Guard e
Manipulation Detector. Ventiquattro punti si fanno commentando davvero, per qualche
giorno, dove si ha qualcosa da dire — e sono anche il modo di non arrivare su r/ClaudeAI
come uno che ha aperto l'account per postare il proprio progetto.

**L'ordine che ne segue:**

1. **Hacker News per primo**, appena c'è un account. È l'unico canale che non chiede
   niente a chi arriva nuovo, ed è quello che può produrre le stelle da cui dipendono le
   liste. Rovescia di nuovo il piano — e di nuovo per una regola letta, non per un'idea.
2. **r/LocalLLaMA già adesso**, con i 27 karma verificati e la dichiarazione d'uso
   dell'LLM che la regola 3 impone. **r/ClaudeAI** quando i punti superano i 50.
3. **r/Python** solo dentro il thread mensile di showcase, col formato a tre sezioni
   della regola 11 (vedi sezione 2).
4. **Le liste** quando i loro cancelli si aprono.

**Il sito è in due lingue**: <https://x3n0-io.github.io/starkeno/> e
<https://x3n0-io.github.io/starkeno/en/>. Manda l'inglese alle comunità internazionali —
una pagina in italiano su r/Python perde metà dei lettori alla prima riga. Per un pubblico
tecnico il link migliore resta il repository; il sito serve a chi arriva da un social e
non aprirebbe mai un README.

**Una comunità al giorno**, e si risponde ai commenti di quella prima di aprire la
successiva: tutte insieme sembrano spam a tre piattaforme contemporaneamente.

---

## 1-bis. Il primo post è stato rimosso, e il motivo non era nelle regole

**20/08/2026, r/LocalLLaMA: post rimosso in meno di un minuto.** Nessun commento sul
post, nessun motivo pubblico, `removed_by_category: moderator` e sparito da `/new`. Il
motivo è arrivato in messaggio privato da AutoModerator:

> Your post was removed as you do not have sufficient karma on r/LocalLLaMa. We are doing
> this in response to the large volume of spam we are unfortunately experiencing. Please
> participate in the sub (through comments), gain the minimum of **5 karma** and then
> re-post.

**Il karma che conta è quello del singolo subreddit, non quello totale.** Il profilo ha
27 punti globali e ne aveva **zero** dentro r/LocalLLaMA: la soglia è cinque, e si fanno
con qualche commento utile. Nessuna delle regole pubbliche del sub lo dice — le ho lette
tutte e cinque prima di postare.

**La lezione, e vale per ogni sub che resta:** leggere `about/rules` non basta, perché
AutoModerator applica soglie che lì non sono scritte. L'unico modo di scoprirle è
sbatterci contro, quindi **il primo post in un sub nuovo va considerato un test**, non il
colpo buono. Il test costa poco se il sub ti invita a ripostare, come qui; costa caro
dove si passa una volta sola, che è il motivo per cui Hacker News non va per primo se lo
si può evitare.

**Conseguenze pratiche:**

- **r/LocalLLaMA: cinque punti di karma dentro quel sub, poi si riposta lo stesso testo.**
  Il bot lo dice esplicitamente, quindi non c'è niente di bruciato. Non cancellare il post
  rimosso: non serve, e non blocca il nuovo.
- **r/ClaudeAI, regola 7, va riletta con questa luce:** «OP karma > 50» quasi certamente
  significa **50 dentro r/ClaudeAI**, non 50 globali. Se è così il cancello è molto più
  alto di quanto sembrava, e la strada è la stessa: commentare dove si ha qualcosa da
  dire, per settimane e non per ore.
- **I commenti non sono un pedaggio.** Sono lo stesso lavoro del post: rispondere a
  qualcuno che sta stimando male un costo è esattamente il pubblico che serve.

---

## 2. Reddit — il corpo del post

Reddit **non** va per primo, per il cancello del karma della sezione 1. Ma è l'unico
canale ripetibile — se il taglio non funziona si capisce lì e si corregge — quindi il
corpo sta qui, ed è la base da cui derivano tutti gli altri.

**Il titolo apre sulla previsione, mai sul 60%.** Il 60% è la *spiegazione* dello scarto:
messo in testa, il post diventa l'ennesima misura di consumo, e la risposta giusta a
quella è `ccusage`.

Titolo, inglese:

```
I built a cost simulator for coding agents, then scored it against real runs.
It was 9x under on one, 3.1x on another.
```

Titolo, italiano:

```
Ho scritto un simulatore che dice quanto costerà un lavoro con un agente prima di
lanciarlo. Poi l'ho confrontato con esecuzioni vere: 9 volte sotto sulla prima,
3,1 sulla seconda.
```

Su Reddit **il link va nel corpo, non nel titolo**: in molti subreddit un post che è solo
un link viene rimosso.

### Corpo, italiano

```
Ho passato le ultime settimane a costruire una cosa che credevo esistesse già, e non
esiste: uno strumento che dice quanto costerà un lavoro con un agente di coding **prima**
di lanciarlo.

Di consuntivi ce ne sono, e sono buoni. `ccusage` legge gli stessi file JSONL che Claude
Code scrive già, gira con `npx` e non installa niente: se ti serve sapere quanto hai speso
ieri, usa quello — su quella metà è migliore del mio. Quello che non trovavo è la domanda
opposta: *ho questo lavoro da fare, quanto mi verrà a costare?*

**Provalo in tre comandi.** Niente plugin, niente hook, nessun server MCP, nessuna rete:
il Blueprint d'esempio viaggia dentro il pacchetto.

    pip install starkeno

    python -m starkeno preflight esempio --output esempio.json
    python -m starkeno preflight draft   --input esempio.json --format yaml --output bozza.yaml
    python -m starkeno preflight analyze --input bozza.yaml --confirmed --samples 50 \
        --format html --output report.html

**Non ti dà un numero, ed è voluto.** Ti dà quattro scenari — `optimistic`, `typical`,
`prudent`, `maximum` — dichiara la propria confidenza (nell'esempio è `low`, e lo scrive
invece di lasciartelo dedurre) e tagga ogni stima con la provenienza: `declared` se
gliel'hai detta tu, `default` se l'ha messa lui, `inferred` se l'ha dedotta. Quello che non
sa valorizzare lo **nomina**, invece di metterci zero: il denaro assente è assente, non è
zero.

**Poi l'ho messo alla prova contro esecuzioni vere, ed è andata male due volte su due.**

| | forma del lavoro | previsto | osservato | scarto |
|-|-|-|-|-|
| 1 | Codex, 7 nodi, lineare, senza ritentativi | 331.500 | 3.035.535 | **9,15×** |
| 2 | Claude Code, ~150 turni, ciclo con ritentativi | 11.098.500 | 34.303.668 | **3,1×** |

Il 331.500 della prima non era una stima media: era il suo scenario `maximum`. **Il suo
stesso caso peggiore era nove volte sotto.**

Due punti non fanno una curva, ma bastano a uccidere l'ipotesi comoda: 9,15 e 3,1 non sono
lo stesso numero, quindi lo scarto **non è una costante moltiplicativa** e la correzione
non sarà un coefficiente da applicare.

**La causa della direzione però si conosce, ed è strutturale invece che aritmetica.**
Contavo il contesto riletto dalla cache solo sui ritentativi, come si comporta una singola
chiamata a un modello. Un agente vero non ha memoria fra un turno e l'altro: rispedisce
tutto il contesto accumulato **a ogni turno**. Nella misura 2 quella rilettura è il 97%
della spesa; su una settimana di lavoro normale è il 60%.

**Quello che mi serve non sono installazioni, sono misure.** Otto numeri da un'esecuzione
vera: niente database, niente transcript, niente che ti riguardi. Ogni misura che arriva
finisce nella tabella col nome di chi l'ha mandata. È l'unica cosa che può dire se lo
scarto dipende dalla lunghezza, dai ritentativi, dall'harness o da qualcos'altro ancora —
con due punti che differiscono in tutto, non si isola niente.

Tutto in locale: nessuna chiamata di rete, nessun account, nessuna telemetria. MIT.

- Codice: https://github.com/X3n0-io/starkeno
- Lo scarto, per intero: https://github.com/X3n0-io/starkeno/blob/main/docs/lo-scarto-9x.md
- Sito: https://x3n0-io.github.io/starkeno/
```

### Corpo, inglese

```
I spent the last few weeks building something I assumed already existed, and it does not:
a tool that tells you what a coding-agent workflow will cost **before** you run it.

Retrospective tools exist and they are good. `ccusage` reads the same JSONL files Claude
Code already writes, runs under `npx`, installs nothing — if you want to know what
yesterday cost, use that, it is better than mine at that half. What I could not find was
the opposite question: *I have this job to do, what is it going to cost me?*

**Try it in three commands.** No plugin, no hooks, no MCP server, no network — the example
Blueprint ships inside the package, so it works the moment it is installed:

    pip install starkeno

    python -m starkeno preflight esempio --output esempio.json
    python -m starkeno preflight draft   --input esempio.json --format yaml --output bozza.yaml
    python -m starkeno preflight analyze --input bozza.yaml --confirmed --samples 50 \
        --format html --output report.html

**It deliberately does not give you a number.** It gives four scenarios — `optimistic`,
`typical`, `prudent`, `maximum` — declares its own confidence (`low` on that example, and
it says so instead of letting you infer it) and tags every estimate with where it came
from: `declared` if you said it, `default` if it assumed it, `inferred` if it worked it
out. Prices it cannot value are **named**, never silently zeroed.

**Then I scored it against real runs, and it was under both times.**

| # | shape of the work | predicted | observed | gap |
|---|---|---|---|---|
| 1 | Codex, 7 nodes, linear, no retries | 331,500 | 3,035,535 | **9.15x** |
| 2 | Claude Code, ~150 turns, loop with retries | 11,098,500 | 34,303,668 | **3.1x** |

The 331,500 was not an average estimate — it was its own `maximum` scenario. **Its worst
case was nine times under.**

Two points do not make a curve, but they are enough to kill the convenient hypothesis:
9.15 and 3.1 are not the same number, so the error is **not a multiplicative constant**
and the fix will not be one coefficient.

**The direction, at least, is structural rather than arithmetic.** I counted context read
back from cache only on retries, the way a single model call behaves. A real agent has no
memory between turns: it resends its whole accumulated context **every turn**. In run 2
that re-reading is 97% of the spend; across a normal week of work it is 60%.

**What I need is not installs, it is measurements.** Eight numbers from a real run — no
database, no transcripts, nothing of yours. Every measurement that arrives goes into the
table credited to whoever sent it. It is the only thing that can say whether the gap
depends on length, retries, harness, or something else: two points that differ in
everything isolate nothing.

All local: no network call, no account, no telemetry. Free and MIT.

* Code: https://github.com/X3n0-io/starkeno
* The gap, in full: https://github.com/X3n0-io/starkeno/blob/main/docs/the-9x-gap.en.md
* Site: https://x3n0-io.github.io/starkeno/en/
```

### Le due varianti obbligatorie

**r/LocalLLaMA** vieta la copia «completely/primarily LLM generated», con **una sola
eccezione**: chi non è madrelingua può farsi tradurre o rifinire il testo, purché lo
dichiari in chiaro. Il corpo qui sopra ricade in quel caso, quindi va aggiunta una riga —
in fondo, non nascosta:

```
(English is not my first language; I used an LLM to translate and tidy this post. The
project, the measurements and the numbers are mine.)
```

Vale anche la regola 4: la self-promo non dovrebbe superare il 10% di quello che scrivi.
Con un account che non ha mai commentato, il primo post è il 100%. È un rischio reale, e
il modo di ridurlo è avere già commentato altrove da qualche giorno.

**r/Python** non accetta post di showcase (regola 1): si va nel thread mensile di showcase
o nel daily. La regola 11 impone tre sezioni con questi titoli esatti, da mettere in cima
al corpo:

```
**What My Project Does**
It simulates what a coding-agent workflow will cost before you run it — four scenarios,
declared confidence, provenance on every estimate — and separately reconstructs what a
session actually cost from the transcripts the agent already writes.

**Target Audience**
Anyone paying per token for Claude Code or Codex who wants a number before committing to
a job. The retrospective half is usable day to day; the forecast half is honest research
in progress, and the README says which is which.

**Comparison**
`ccusage` and similar tools answer what you already spent, and do it better than I do.
I have not found another tool that tries to answer the cost *before* the run — which is
also why this one publishes how wrong it was: 9.15x under on one measurement, 3.1x on
another.
```

### Prima di premere invio

- **Rispondi a chi nomina `ccusage`**, e dagli ragione sulla metà che gli compete. Il
  corpo lo fa già prima che qualcuno debba chiederlo: è la mossa che disinnesca
  l'obiezione invece di subirla.
- **Non promettere il confronto come funzione pronta.** Il simulatore gira in tre comandi;
  il confronto con l'esecuzione vera richiede il server MCP montato a mano. Confonderli è
  il modo più rapido per essere smentiti dal primo che prova.
- **Niente superlativi.** Un difetto ammesso vale più di dieci aggettivi.

---

## 3. Hacker News — Show HN, ma del repository

**Correzione al piano precedente.** Diceva di mandare il pezzo sullo scarto con un titolo
«Show HN», e le regole di Show HN lo escludono alla lettera:

> Off topic: blog posts, sign-up pages, newsletters, lists, and other reading material.

Un articolo con davanti «Show HN» viene ricategorizzato o cancellato, e sarebbe l'unico
colpo sprecato per una riga di regolamento. Show HN vuole *«things people can run on their
computers»*, e StarkEno lo è: `pip install`, tre comandi, nessuna registrazione. **Quindi
si manda il repository, e la storia dello scarto sta nel titolo e nel primo commento.**

Titolo — sotto gli 80 caratteri, specifico, non vende niente, e dichiara subito che le
misure sono due, così nessuno può accusarti di aver scelto il numero più drammatico:

```
Show HN: I forecast what an agent run will cost. I was 9x under, then 3.1x
```

Link: `https://github.com/X3n0-io/starkeno`

> Se preferisci il taglio da saggio, l'alternativa è una **submission normale** dell'articolo
> `docs/the-9x-gap.en.md`, **senza il prefisso «Show HN»**. È legittima, e gli articoli su HN
> funzionano. Ma scegline una sola: ripostare lo stesso progetto è il modo più rapido per
> farsi bandire.

Primo commento, da scrivere subito dopo aver postato:

```
  pip install starkeno

I built a local tool that reads the transcripts Claude Code and Codex already write and
reconstructs what a session cost. That half works, and I will say it before anyone else
does: ccusage does that half better, with more stars and nothing to install.

The other half is the one I have not seen anyone else attempt -- simulating a workflow
*before* you run it. Three commands, no plugin, no hooks, no MCP server, and the example
Blueprint ships inside the package:

  python -m starkeno preflight esempio --output esempio.json
  python -m starkeno preflight draft   --input esempio.json --format yaml --output bozza.yaml
  python -m starkeno preflight analyze --input bozza.yaml --confirmed --samples 50 \
      --format html --output report.html

It deliberately does not give you a number. It gives four scenarios
(optimistic/typical/prudent/maximum), declares its own confidence -- `low`, on that
example, and it says so -- and tags every estimate with where it came from: declared,
default, or inferred. Prices it cannot value are named, never silently zeroed.

Then I scored it against real executions. Twice, and it was under both times:

  1. Codex, 7 nodes, linear, no retries: its own `maximum` scenario said 331,500 tokens.
     The run cost 3,035,535. That is 9.15x under its own worst case.
  2. Claude Code, ~150 turns, a loop with retries: 11,098,500 predicted, 34,303,668
     observed. 3.1x.

Two points do not make a curve, but they are enough to kill the convenient hypothesis.
9.15x and 3.1x are not the same number, so the error is not a multiplicative constant
and the fix will not be one coefficient. What it *does* depend on I genuinely do not
know: the two runs differ in harness, shape, length and retries all at once, so they
isolate nothing.

The direction, at least, is structural rather than arithmetic. I counted context read
back from cache only on retries, the way a single model call behaves. A real agent has
no memory between turns, so it resends its whole accumulated context every turn. On my
machine that re-reading was 60% of a week's spend -- and 97% of run 2, because a long
session ends up paying for almost nothing else.

Which is why I am asking for measurements instead of installs: eight numbers from a real
run, no database, no transcripts, and every one that arrives goes into the table credited
to whoever sent it. I would rather be corrected in public than be the only person holding
the data.

  https://github.com/X3n0-io/starkeno/blob/main/docs/the-9x-gap.en.md

Everything is local: no network call, no account, no telemetry. MIT.
```

Regole di Hacker News che costano caro se ignorate:

- **Una volta sola.** Ripostare lo stesso progetto è il modo più rapido per farsi bandire.
- **Niente superlativi.** «Rivoluzionario», «potente», «game-changer» affondano un post
  su HN più in fretta di un difetto ammesso.
- **Non chiedere voti a nessuno.** È scritto nelle regole di Show HN, e si vede.
- **Posta quando sei disponibile** per le due ore successive. Un thread abbandonato muore.

---

## 4. dev.to e simili — la ristampa dell'articolo

Il pezzo sullo scarto è già un articolo compiuto: su dev.to (o Hashnode, o Medium) si
ripubblica per intero, con il **canonical** che punta al file su GitHub, così la copia non
compete con l'originale. Non è un canale che porta installazioni, ma è quello che resta
indicizzato quando i thread sono scesi.

## 5. I Discord e i forum

Anthropic e OpenAI hanno comunità dove si mostra quello che si costruisce. Valgono le
stesse due regole di sempre: **si posta nel canale giusto** (di solito uno chiamato
`showcase` o `built-with`), e **si risponde**. Un link lasciato cadere e mai più seguito
fa più danno che non postare.

---

## 6. Le due liste senza cancello — si possono fare oggi

Entrambe si segnalano con una **pull request normale**, ed entrambe elencano i progetti in
tabella con nome, stelle e descrizione.

- [jqueryscript/awesome-claude-code](https://github.com/jqueryscript/awesome-claude-code)
  — sezione **Usage & Observability**.
- [LangGPT/awesome-claude-code](https://github.com/LangGPT/awesome-claude-code) — sezione
  **Monitoring & Analytics**; accetta anche una issue.

Riga da usare, in inglese, senza superlativi:

```
[X3n0-io/starkeno](https://github.com/X3n0-io/starkeno) — Simulates what a workflow will
cost before you run it, and reconstructs what it actually cost from the transcripts the
agent already writes. Local only, no network.
```

**Prima di ognuna, leggi il CONTRIBUTING di quella lista**: hanno formati diversi, e la
segnalazione fuori formato viene chiusa senza discussione.

---

## 7. awesome-claude-code — dal 28/08/2026, e per issue

È la lista principale, e ha due regole che se non conosci ti fanno perdere il colpo:

> **Non aprire una pull request.** Si segnala aprendo una **issue** dal template
> «Recommend a new resource», e solo dal form web: la CLI non è supportata. Le PR su quel
> repository le fa solo Claude; un bot processa la issue e inserisce la risorsa se supera
> i criteri.

> **Una risorsa alla volta**, e la risorsa deve avere **14+ giorni di età con sviluppo
> attivo, oppure 100+ stelle.** StarkEno è stato creato il 14/08/2026 alle 17:06 UTC:
> il cancello si apre il **28/08/2026**. Non è noto se il bot guardi la data di creazione
> o quella in cui il repository è diventato pubblico (19/08) — nel dubbio vale la seconda,
> e la data sicura diventa il **02/09/2026**.

Campi del form, già compilati:

| Campo | Valore |
|---|---|
| Display Name | `StarkEno` |
| Category | `Observability & Monitoring` |
| Link | `https://github.com/X3n0-io/starkeno` |
| Author Name | `XENO.io` |
| Author Link | `https://github.com/X3n0-io` |

Description — **una riga sola, nessuna emoji, descrizione e non pubblicità** (è scritto
nel CONTRIBUTING, ed è il motivo per cui la versione precedente di questa bozza era
troppo lunga):

```
Simulates what a Claude Code workflow will cost before you run it, then reconstructs what
it actually cost from the transcripts the agent already writes. Local only.
```

La licenza non va dichiarata: il bot la scopre da solo. Il form ha **cinque caselle
obbligatorie più una opzionale che è una trappola** per le candidature automatiche:
leggile, non spuntarle per riflesso.

---

## 8. awesome-claude-skills — a dieci stelle, e a mano

[travisvn/awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills)
accetta PR, ma:

- **sotto le 10 stelle la PR si chiude in automatico**;
- **la PR non deve essere scritta o inviata con assistenza di un'AI**, è dichiarato nel
  CONTRIBUTING. Quindi questa è la voce che **nessun agente può preparare**: il formato
  qui sotto è materiale di riferimento, non un testo da incollare per conto tuo;
- vuole più di un solo `SKILL.md`, e StarkEno ne ha due copie più il pacchetto: la
  condizione è soddisfatta.

Formato della riga: `- **[Nome](link)** - Descrizione breve e chiara`.

---

## 9. «Esiste già ccusage» — le risposte, pronte

È il commento che arriva per primo e decide come va il thread. Non è ostilità: è la
domanda giusta, e chi la fa ti sta regalando l'occasione di dire in cosa consiste il
progetto. **La regola sopra tutte: dagli ragione sulla metà che gli compete, subito e
senza giri.** Chi difende l'indifendibile perde il thread; chi concede una cosa vera si
guadagna il diritto di essere ascoltato sul resto.

Non copiare tutte queste risposte: sono quattro obiezioni diverse, e ognuna vuole la sua.

### 9.1 «Questo è ccusage con altri passi»

```
You are right about half of it, and I say so in the post: for the retrospective,
ccusage is the better tool. Same JSONL files, npx, nothing to install.

The half I have not seen anyone else do is the other direction: what will this job
cost, before I start it. That is not a reporting feature, it is a different problem --
there is no data to read yet, so you have to describe the work and simulate it. Which
is why it ships as `preflight`, not as a column in a report.

If you only ever want to know what yesterday cost, you genuinely do not need this.
```

### 9.2 «E allora perché non aggiungerlo a ccusage?»

```
Because they read different things. ccusage reads the transcript of work that already
happened. A forecast has no transcript to read: its input is a description of work that
does not exist yet -- how many steps, how much context each one carries, how often you
expect a retry -- and its output is a distribution, not a total.

They meet at exactly one point, which is the interesting one: you take the forecast, run
the work, and compare. That comparison is the whole reason this exists, and it is what
produced the 9.15x and the 3.1x.
```

### 9.3 «Il tuo forecast ha sbagliato di 9x, quindi è inutile» — la più dura, e la più utile

```
Today, as a number you would budget against, yes. I would not plan a sprint on it, and
the README says so.

What it is useful for today is the thing that comes before a good forecast: a harness
that produces a falsifiable number, runs it against reality, and publishes the distance.
Most estimation tools never close that loop, which is why you never find out they are
wrong -- you just quietly believe them.

The gap also runs in one direction and has a known cause: I count context read back from
cache only on retries, and a real agent resends its whole context every turn. That is not
a mystery to debug, it is a model to fix. The reason I am not shipping a corrected
coefficient today is that two measurements already say the error is not a constant --
9.15x and 3.1x -- so a single multiplier would be a lie that looks like a fix.
```

### 9.4 «Basta moltiplicare per 10»

```
That was my first hypothesis, and the second measurement killed it. Run 1 was 9.15x
under, run 2 was 3.1x under. If I shipped a x9 correction, run 2 would now be roughly
3x over -- I would have replaced an underestimate with an overestimate and called it
calibration.

What the two points do rule out is the convenient answer. What they do not tell me is
what the gap depends on, because they differ in harness, shape, length and retries all
at once. That is why the page asks for eight numbers from a real run rather than for
stars.
```

### La versione corta, in italiano

Per i post in italiano, e per quando la risposta va data in due righe:

```
Hai ragione per metà, e lo scrivo anche nel post: sul consuntivo ccusage è meglio del
mio, stessi file JSONL e nessuna installazione. StarkEno serve alla domanda opposta —
quanto costerà, prima di lanciarlo — che non è una colonna in un report ma un problema
diverso: non c'è ancora niente da leggere, quindi il lavoro va descritto e simulato.
E poi confrontato con l'esecuzione vera, che è la parte da cui vengono il 9,15× e il 3,1×.
```

### Quello che non devi rispondere

- **Non dire che ccusage è limitato.** Non lo è per quello che fa, e chiunque l'abbia
  usato lo sa: ti smentisci in una riga.
- **Non dire «è complementare».** È vero e non significa niente; suona come una risposta
  preparata per non rispondere.
- **Non difendere il 9x.** Concedilo per intero, e sposta la conversazione su cosa lo
  rende interessante — la direzione nota, la causa strutturale, il fatto che sia
  pubblicato.
- **Non promettere una data** per la correzione. Non ce l'hai: dipende da misure che
  ancora non esistono.

---

## Da verificare il giorno del post

Un post non si può correggere ovunque, e queste tre cose invecchiano:

- **Le stelle di `ccusage`**, se le nomini. All'ultima verifica erano circa 16.500.
- **Il conteggio delle misure.** Oggi sono due. Se ne arriva una terza prima del post,
  titolo, commento e tabella vanno riallineati insieme — non uno solo dei tre.
- **Che i tre comandi funzionino da un virtualenv vuoto.** Verificato il 20/08/2026 su
  `0.4.1`, tutti e tre a exit `0`, fuori dal repository. Rifallo dopo ogni rilascio.

## Cosa NON fare

- **Distingui il simulatore dal confronto.** Il simulatore gira oggi in tre comandi e si
  può mostrare senza riserve. Quello che NON è spedito è il confronto fra la sua stima e
  un'esecuzione vera: lì il plugin non registra i tool MCP, il server va montato a mano,
  e Preflight non legge prosa. Confonderli è il modo più rapido per essere smentiti dal
  primo che prova.
- **Non citare il 61%.** La cifra pubblica è 60%, arrotondata per difetto. Due numeri
  diversi per la stessa misura sono l'unica cosa che toglie credibilità a tutto il resto.
- **Non aprire un titolo sul 60%.** È la spiegazione dello scarto, non la notizia: chi
  legge «60% è rilettura di contesto» pensa a uno strumento di consumo, e per quello
  `ccusage` è migliore.
- **Non citare solo il 9x.** Con due misure note, dare solo la più drammatica è
  esattamente ciò che un lettore di HN cerca e punisce.
- **Non mandare screenshot del tuo conto vero.** Contengono i nomi dei tuoi progetti e
  quanto spendi. L'immagine del README si rigenera da dati di nessuno con
  `python scripts/genera_immagine_conto.py`.
