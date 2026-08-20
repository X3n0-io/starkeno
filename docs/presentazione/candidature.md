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

**L'ordine nuovo:**

1. ~~**PyPI**~~ — **fatto il 20/08/2026**: [`pip install starkeno`](https://pypi.org/project/starkeno/).
2. **I canali che non chiedono stelle** — Reddit prima, Hacker News dopo. Reddit si può
   sbagliare e rifare; HN no.
3. **Le due liste senza cancello**, in parallelo: costano una PR ciascuna.
4. **awesome-claude-code dal 28/08**, e awesome-claude-skills quando le stelle sono dieci.

> Il sito è online: <https://x3n0-io.github.io/starkeno/>. Per un pubblico tecnico il
> link giusto resta il repository o il pezzo sullo scarto; il sito serve a chi arriva da
> un social e non aprirebbe mai un README.

---

## 1. Reddit — r/ClaudeAI

Va per primo perché è l'unico canale ripetibile: se il taglio non funziona, si capisce
qui e si corregge prima di bruciare l'unico colpo su HN.

**Il titolo apre sulla previsione, mai sul 60%.** Il 60% è la *spiegazione* dello scarto:
messo in testa, il post diventa l'ennesima misura di consumo, e la risposta giusta a
quella è `ccusage`.

```
I built a cost simulator for coding agents, then scored it against real runs. It was
9x under on one, 3.1x on another.
```

In italiano, se il post va anche altrove:

```
Ho scritto un simulatore che dice quanto costerà un lavoro con un agente prima di
lanciarlo. Poi l'ho confrontato con esecuzioni vere: ha sbagliato di 9 volte sulla
prima, di 3,1 sulla seconda.
```

Il corpo: lo stesso del commento HN qui sotto. Su Reddit **il link va nel corpo, non nel
titolo**, e in molti subreddit un post che è solo un link viene rimosso.

---

## 2. Hacker News

**Manda il pezzo sullo scarto, non il repository.** Un altro strumento di costi non
interessa nessuno; un forecaster che pubblica il proprio errore sì.

Titolo — specifico, verificabile, non vende niente, e **dichiara subito che le misure
sono due**, così nessuno può accusarti di aver scelto il numero più drammatico:

```
Show HN: My cost simulator for coding agents was 9x under on one run, 3.1x on another
```

Link: `https://github.com/X3n0-io/starkeno/blob/main/docs/the-9x-gap.en.md`

> **«Show HN» richiede qualcosa che si possa provare**, ed è il motivo per cui il primo
> commento apre con l'installazione: il simulatore gira in tre comandi, senza plugin né
> hook. Un «Show HN» che si apre su un articolo e basta viene ripreso nei commenti, e
> giustamente.

Primo commento, da scrivere subito dopo aver postato:

```
  pip install starkeno

I built a local tool that reads the transcripts Claude Code and Codex already write and
reconstructs what a session cost. That half works, and I will say it before anyone else
does: ccusage does that half better, with more stars and no install.

The other half is the one I have not seen anyone else attempt -- simulating a workflow
*before* you run it. Three commands after `pip install starkeno`, no plugin, no hooks,
no MCP server, and the example Blueprint ships inside the package:

  python -m starkeno preflight esempio --output esempio.json
  python -m starkeno preflight draft --input esempio.json --format yaml --output bozza.yaml
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

Which is why the page asks for measurements instead of installs: eight numbers from a
real run, no database, no transcripts, and every one that arrives goes into the table
credited to whoever sent it. I would rather be corrected in public than be the only
person holding the data.

Everything is local: no network call, no account, no telemetry. MIT.
```

Regole di Hacker News che costano caro se ignorate:

- **Una volta sola.** Ripostare lo stesso progetto è il modo più rapido per farsi bandire.
- **Niente superlativi.** «Rivoluzionario», «potente», «game-changer» affondano un post
  su HN più in fretta di un difetto ammesso.
- **Rispondi a tutti**, soprattutto a chi ti dice che esiste già `ccusage`. La risposta
  vera è nel commento sopra: sì, e per il consuntivo è migliore — questo simula il lavoro
  *prima*.
- **Posta quando sei disponibile** per le due ore successive. Un thread abbandonato muore.

---

## 3. Le due liste senza cancello — si possono fare oggi

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

## 4. awesome-claude-code — dal 28/08/2026, e per issue

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

## 5. awesome-claude-skills — a dieci stelle, e a mano

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
