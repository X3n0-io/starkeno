# Farsi trovare — cosa mandare, dove, in che ordine

Bozze pronte da incollare. **Le manda l'autore, non un agente**: sono post a suo nome su
piattaforme di terzi, e la voce deve essere la sua.

## L'ordine conta più del contenuto

Hai una sola prima impressione per lista, e un curatore che apre il repository e trova
`pip install git+https://…` archivia la segnalazione senza rispondere.

1. **PyPI** — vedi [releasing.md](../releasing.md). Toglie l'unica barriera vera.
2. **Le liste** — traffico costante, zero rumore, nessun rischio di reputazione.
3. **Hacker News** — una volta sola, e solo quando i primi due sono fatti.

Non invertire 1 e 3.

---

## 1. awesome-claude-code

La lista principale è [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code),
e ha una regola che se non conosci ti fa perdere il colpo:

> **Non aprire una pull request.** Si segnala aprendo una **issue** dal template
> «Recommend a new resource». Le PR su quel repository le fa solo Claude; un sistema
> automatico processa la issue e inserisce la risorsa se supera i criteri.

Cosa dichiarare:

- **Nome:** StarkEno
- **URL:** https://github.com/X3n0-io/starkeno
- **Categoria:** tooling / plugin
- **Licenza:** MIT
- **Descrizione (una riga):** Simula quanto costerà un workflow prima di lanciarlo — in
  due comandi, senza plugin — e tiene il conto locale di quanto è costato davvero, per
  poterli confrontare.

Le altre, indipendenti, che accettano PR normali:
[subinium](https://github.com/subinium/awesome-claude-code) ·
[jqueryscript](https://github.com/jqueryscript/awesome-claude-code) ·
[LangGPT](https://github.com/LangGPT/awesome-claude-code) ·
[travisvn/awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills)

Prima di ognuna, **leggi il CONTRIBUTING di quella lista**: hanno formati diversi e la
segnalazione fuori formato viene chiusa senza discussione.

---

## 2. Hacker News

**Manda il pezzo sullo scarto, non il repository.** Un altro strumento di costi non
interessa nessuno; un forecaster che pubblica il proprio errore sì.

Titolo — specifico, verificabile, non vende niente:

```
Show HN: My cost simulator for coding agents was 9x under. Here is why, and you can run it
```

Link: `https://github.com/X3n0-io/starkeno/blob/main/docs/the-9x-gap.en.md`

> **«Show HN» richiede qualcosa che si possa provare**, ed è il motivo per cui il titolo
> lo dice: il simulatore gira in due comandi, senza plugin né hook. Un «Show HN» che si
> apre su un articolo e basta viene ripreso nei commenti, e giustamente.

Primo commento, da scrivere subito dopo aver postato:

```
I build a local tool that reads the transcripts Claude Code and Codex already write
and reconstructs what a session cost. That half works.

The other half simulates a workflow before you run it. You can try it in two commands
on a fixture that ships in the repo -- no plugin, no hooks, no MCP server:

  python -m starkeno preflight draft --input tests/fixtures/preflight/medium.json \
      --format yaml --output bozza.yaml
  python -m starkeno preflight analyze --input bozza.yaml --confirmed --samples 50 \
      --format html --output report.html

It deliberately does not give you a number. It gives four scenarios, declares its own
confidence, and tags every estimate with where it came from: declared, default or
inferred. Missing prices are named, never silently zeroed.

Then I finally scored it against a real execution. Its own `maximum` scenario said
331,500 tokens. The run cost 3,035,535. Nine times under its worst case.

The cause was structural, not arithmetic. I counted context read back from cache only
on retries, the way a single model call behaves. A real agent has no memory between
turns, so it resends its whole context every turn. On my machine that re-reading was
60% of a week's spend -- the exact quantity I was not counting.

I do not know yet whether the gap is a multiplicative constant or depends on the shape
of the work, because I have one measurement and one point does not determine a slope.
That is what the page asks for: eight numbers from a real run, no database, no
transcripts.

Everything is local: no network call, no account, no telemetry. MIT.
```

Regole di Hacker News che costano caro se ignorate:

- **Una volta sola.** Ripostare lo stesso progetto è il modo più rapido per farsi bandire.
- **Niente superlativi.** «Rivoluzionario», «potente», «game-changer» affondano un post
  su HN più in fretta di un difetto ammesso.
- **Rispondi a tutti**, soprattutto a chi ti dice che esiste già `ccusage`. La risposta
  vera è: sì, e per il consuntivo è migliore — questo simula il lavoro *prima*.
- **Posta quando sei disponibile** per le due ore successive. Un thread abbandonato muore.

---

## 3. Reddit

**r/ClaudeAI** è il posto giusto, ed è un pubblico che riconosce il problema. Titolo:

```
Il 60% di quello che pago a un agente di codice non è ragionamento: è rilettura di
contesto. L'ho misurato, e la mia previsione ha sbagliato di 9 volte.
```

In inglese per il pubblico internazionale:

```
60% of what I pay a coding agent is not reasoning, it is context re-reading. I measured
it, and my own forecast was 9x off.
```

Il corpo: lo stesso del commento HN. Su Reddit **il link va nel corpo, non nel titolo**, e
in molti subreddit un post che è solo un link viene rimosso.

---

## Cosa NON fare

- **Distingui il simulatore dal confronto.** Il simulatore gira oggi in due comandi e si
  può mostrare senza riserve. Quello che NON è spedito è il confronto fra la sua stima e
  un'esecuzione vera: lì il plugin non registra i tool MCP, il server va montato a mano,
  e Preflight non legge prosa. Confonderli è il modo più rapido per essere smentiti dal
  primo che prova.
- **Non citare il 61%.** La cifra pubblica è 60%, arrotondata per difetto. Due numeri
  diversi per la stessa misura sono l'unica cosa che toglie credibilità a tutto il resto.
- **Non mandare screenshot del tuo conto vero.** Contengono i nomi dei tuoi progetti e
  quanto spendi. L'immagine del README si rigenera da dati di nessuno con
  `python scripts/genera_immagine_conto.py`.
