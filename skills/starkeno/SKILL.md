---
name: starkeno
description: >
  Rispondi a quanto costa davvero il lavoro dell'utente con gli agenti di codice, a
  partire dai dati che StarkEno ha gia' raccolto su questa macchina. Usala ogni volta che
  l'utente chiede quanto e' costata una sessione o un progetto, dove finiscono i token,
  perche' qualcosa e' sembrato caro o lento, qual e' la voce di spesa maggiore, o chiede
  di vedere il conto o la scomposizione della spesa. Si attiva su "quanto e' costato",
  "dove sto sprecando token", "perche' e' stato cosi' caro", "mostrami il conto", "spesa
  in token", "scomposizione dei costi", "quanto e' costato oggi", e sugli equivalenti
  inglesi "how much did this cost", "where am I wasting tokens", "why was this so
  expensive", "show me the bill", "token spend", "cost breakdown", "what did today cost".
  Usala anche quando StarkEno sembra installato ma non sta raccogliendo niente.
---

# StarkEno

StarkEno rilegge i transcript che l'agente gia' scrive e ricostruisce quanto costa il modo
di lavorare dell'utente, scomposto per progetto, modello, sessione, skill, plugin e server
MCP. Non guarda l'utente digitare e non avvolge l'agente.

**Tutto resta su questa macchina.** StarkEno non fa nessuna chiamata di rete, e non devi
farne nemmeno tu per suo conto.

## Rispondere a una domanda sui costi

```bash
starkeno report --no-open
```

Scrive un file HTML statico e ne stampa il percorso. Non avvia server e non modifica il
database. Leggi il file e rispondi a partire da quello.

Per i numeri grezzi senza la pagina, interroga il database in sola lettura. Per le
esecuzioni confrontate con un preventivo, `starkeno consuntivo --elenco` le elenca e
`starkeno consuntivo --run <key>` ne mostra una.

## Regole che contano piu' della risposta

- **Non inventare mai un numero.** Se una cosa non e' nell'output, di' che non e'
  raccolta. Una cifra di costo sbagliata detta con sicurezza e' peggio di "StarkEno non
  misura quello".
- **I token sono l'unita', non il fine.** Nomina lo spreco — contesto riletto a ogni
  turno, un file riaperto dieci volte, un compito che ha richiesto tre tentativi — e usa i
  numeri come prova. Un totale da solo non dice all'utente niente su cui possa agire.
- **Le tre colonne di costo non sono intercambiabili.** Lavoro, caricamento e rilettura
  rispondono a domande diverse; che la rilettura sia la piu' grande e' il risultato
  normale e quello su cui si puo' agire.
- **Le etichette skill, plugin e MCP si sovrappongono.** Non sommarle mai.

## Quando i numeri sembrano sbagliati o mancanti

Lancia prima la diagnosi e correggi quello che segnala, prima di fidarti di qualunque
cifra:

```bash
starkeno doctor
```

- `starkeno: command not found` — il pacchetto Python non e' installato. Installare il
  plugin **non** lo installa; sono due passi separati. Indirizza l'utente alla sezione
  d'installazione del README del progetto e offriti di eseguirla.
- `raccolta: nessun evento raccolto` — non e' mai stato raccolto niente. Di solito manca
  il pacchetto, oppure gli hook non sono mai stati approvati in questo agente.
- `inventario_storici: la raccolta sta scrivendo altrove` — la raccolta sta finendo in un
  database che nessun comando legge. Le righe non sono perse: dillo, e di' che vanno unite.
- `plugin_claude_aggiornato: ... diverso dal pacchetto` — la copia installata del plugin e'
  piu' vecchia del pacchetto. L'agente deve aggiornare la propria copia; cancellare a mano
  la copia in cache la disinstalla invece di aggiornarla.
- `schema: schema disallineato` — il database precede la revisione corrente.

## Quando NON usare questa skill

Per domande sull'*output* dell'agente — se il codice e' giusto, se il compito e' riuscito.
StarkEno misura quanto e' stato speso, mai cosa e' stato ottenuto.

<!-- Questa skill esiste in DUE copie, e devono restare identiche:
     `skills/starkeno/SKILL.md`                      <- radice del repo, la monta Codex
     `plugin-claude-code/skills/starkeno/SKILL.md`   <- la monta Claude Code
     I due harness montano radici di plugin diverse dallo stesso repository, quindi una
     copia sola e' invisibile a uno dei due: misurato il 19/08/2026 chiedendo a Codex
     quanto avesse speso, e la skill non e' partita.
     `test_le_due_copie_della_skill_restano_identiche` diventa rosso se divergono. -->
