# Lo scarto 9x

*Ultimo aggiornamento: 19/08/2026. Misure: 2.*

*Read this in [English](the-9x-gap.en.md).*

StarkEno prova a dire quanto costerà un lavoro di un agente di codice **prima** che parta.
La prima volta che quella previsione è stata confrontata con un'esecuzione vera, ha
sbagliato di nove volte.

```
previsto (massimo stimato)      331.500 token
osservato (esecuzione reale)  3.035.535 token
                              ─────────────────
scarto                              9,15x
```

Questa pagina dice **perché**, e chiede aiuto per rispondere alla domanda che ne segue.

> **Il 331.500 non è una stima media: è lo scenario `maximum`.** Il simulatore non
> produce un numero, produce quattro scenari — `optimistic`, `typical`, `prudent`,
> `maximum` — e quello che ha sbagliato di nove volte era già il suo caso peggiore.
>
> Puoi lanciarlo tu in due comandi, senza installare plugin né hook: vedi
> [Prova la simulazione](../README.md#prova-la-simulazione-adesso).

---

## Perché non è un errore di calcolo

La tentazione, davanti a 9x, è cercare un bug nell'aritmetica. Non c'è. Il simulatore fa
esattamente quello per cui è stato scritto — è quello per cui è stato scritto a essere
sbagliato.

Il simulatore conta:

- il **contesto scritto in cache** (`cache_write`) **una volta per invocazione**;
- il **contesto riletto** (`cache_read`) **solo sui ritentativi**.

È il modello di una chiamata a un modello: mandi un prompt, ricevi una risposta, e se
qualcosa va storto ritenti.

Un agente di codice non fa così. **Non ha memoria fra un turno e l'altro**, quindi a ogni
turno rispedisce tutto quello che sa: i file che ha aperto, le istruzioni, la
conversazione fino a lì. Non sui ritentativi — **sempre**.

Sulla macchina dove è stato misurato, quella rilettura è stata il **60% della spesa di una
settimana intera**. Il simulatore la conta quasi mai.

> Il modello non stava sbagliando i conti. Stava descrivendo l'animale sbagliato: una
> chiamata a un modello invece di una conversazione con un agente.

## Perché questo è il contenuto, non l'imbarazzo

Un errore **casuale** è un vicolo cieco: se la previsione sbaglia in modo imprevedibile,
non c'è niente da correggere e lo strumento non serve.

Un errore **strutturale** è un coefficiente. Se sai *quale* quantità il modello non conta,
e quella quantità è misurabile, la correzione è aritmetica.

Ed è per questo che la misura sta in cima al README invece che in fondo a un backlog: uno
strumento di previsione che nasconde il proprio errore non vale niente. Il numero che
conta di un forecaster non è quanto ci prende — è **di quanto sbaglia, e se sbaglia
sempre nello stesso modo.**

## La domanda aperta

Delle due, una:

**Ipotesi A — è una costante moltiplicativa.** Lo scarto è più o meno 9x su qualunque
lavoro. Allora la correzione è un numero solo, e la previsione diventa utile subito.

**Ipotesi B — dipende dalla forma del lavoro.** Un lavoro lungo rilegge più di uno corto;
uno con molti ritentativi si comporta diversamente da uno lineare; uno che tiene aperti
venti file non è come uno che ne tocca due. Allora serve un modello per forma, e il
lavoro è molto più grande.

**Con una misura sola non si distinguono.** È letteralmente impossibile: un punto non
determina una pendenza.

## Come puoi rispondere tu

Servono esecuzioni vere, di **forme diverse**. Se ne fai una, il progetto avanza; se ne
fanno cinque persone diverse, la domanda si chiude.

Non serve che tu mi mandi il tuo database, e non lo voglio. Servono **otto numeri e una
descrizione**.

### 1. Registra un'esecuzione

Segui [la sezione sulla previsione nel README](../README.md#la-previsione-preventivo-contro-consuntivo).
In breve: un Blueprint strutturato, `preflight analyze --confirmed`, poi i tre tool MCP
`blueprint_run_start` / `blueprint_run_node` / `blueprint_run_end` attorno al lavoro vero.

### 2. Leggi il confronto

```bash
starkeno consuntivo --run <run_key> --json
```

### 3. Manda solo questo

Da quell'output servono i totali, **non le righe**:

| Campo | Da dove |
|---|---|
| `input_tokens`, `output_tokens` | stima e osservato |
| `cache_read_tokens`, `cache_write_tokens` | stima e osservato |
| `totale_tokens` | stima e osservato |
| `righe_non_scomposte`, `righe_rifiutate` | osservato — dicono quanto fidarsi del resto |
| harness | Claude Code o Codex |

E una riga sulla **forma del lavoro**: quanto è durato, quanti file toccati, se ci sono
stati ritentativi, se era lineare o pieno di rami.

### 4. Togli quello che ti riguarda

Prima di incollare, **cancella `project`, `session_id`, `run_key` e `blueprint_hash`**: i
primi due dicono a cosa stavi lavorando e su cosa. Gli otto numeri sopra non dicono niente
di te.

> Se ti sembra strano che un progetto sulla privacy chieda dati, hai ragione a farci caso.
> Per questo la richiesta è manuale, volontaria, e limitata a numeri che non descrivono
> nessuno. StarkEno non manda niente da solo, e non lo farà mai: se un giorno lo facesse,
> avrebbe smesso di essere questo progetto.

### 5. Aprine una issue

Usa il template **«Una misura»** su
[github.com/X3n0-io/starkeno/issues/new/choose](https://github.com/X3n0-io/starkeno/issues/new/choose).

Ogni misura ricevuta finisce nella tabella qui sotto, con il credito a chi l'ha mandata.

## Le misure finora

| # | Data | Harness | Forma del lavoro | Previsto | Osservato | Scarto | Da |
|---|---|---|---|---|---|---|---|
| 1 | 18/08/2026 | Codex | 7 nodi, lineare, senza ritentativi | 331.500 | 3.035.535 | **9,15x** | l'autore |
| 2 | 19/08/2026 | Claude Code | sessione lunga, 150 turni, ciclo con ritentativi | 11.098.500 | 34.303.668 | **3,1x** | l'autore |

## Cosa dicono due punti

Due misure non fanno una curva, ma **bastano a escludere qualcosa**: 9,15x e 3,1x non
sono lo stesso numero. Lo scarto **non è una costante moltiplicativa**, e l'ipotesi A —
quella che avrebbe reso la correzione un numero solo — è la meno probabile delle due.

Il che significa che il lavoro davanti è quello grande: capire **da cosa** dipende. Le
due misure differiscono in tutto — harness, forma, presenza di ritentativi, lunghezza —
quindi non isolano ancora nessuna variabile.

Altri numeri della misura 2, che valgono più del rapporto:

- **La rilettura osservata è il 97,0% della spesa.** Non il 60%: in una sessione lunga il
  contesto accumulato divora tutto. Il 60% era la media di una settimana, e mescolava
  sessioni corte e lunghe.
- **Sulla sola rilettura lo scarto è 5,4x** (33.273.660 osservati contro 6.168.350
  stimati), mentre sul totale è 3,1x. Il simulatore sbaglia *di più* proprio sulla voce
  che pesa di più.
- **Rispetto allo scenario `typical` lo scarto è 44x.** Chi guardasse il tipico invece
  del massimo sbaglierebbe di quasi due ordini di grandezza.

### Cosa NON è questa misura, detto prima che lo chieda qualcuno

- **Non è un `consuntivo` attribuito ai nodi.** È un confronto fra totali: nessun
  marcatore `blueprint_run_node`, nessuna attribuzione. La misura 1 è più forte.
- **Il Blueprint è stato scritto dopo**, descrivendo la forma della sessione. I budget per
  turno sono quelli che scriverebbe chi pianifica — il materiale che un turno usa — non
  il contesto accumulato, che è la conseguenza che il simulatore non modella. Ma resta una
  descrizione a posteriori, e chi la rifà con numeri diversi ottiene rapporti diversi.
- **La finestra conteneva due sessioni.** Un `consuntivo` vero si sarebbe rifiutato di
  attribuire, e avrebbe avuto ragione.

Serve una misura fatta come si deve — Blueprint scritto **prima**, marcatori sui nodi — e
serve da qualcuno che non sia l'autore.



---

## Cosa già sappiamo, e che non va rimisurato

Perché nessuno spenda tempo su domande chiuse:

- **Il consuntivo funziona su dati veri.** Stato `ok`, righe attribuite ai nodi attraverso
  il database, `righe_rifiutate = 0` e `righe_non_scomposte = 0`. Il timore che i dati veri
  facessero saltare le guardie non si è avverato.
- **Il rifiuto per sessioni multiple non è un problema di frequenza.** Scatta sul 10–25%
  delle finestre fra un quarto d'ora e un'ora, e la causa dominante è vera concorrenza fra
  sessioni, non la compattazione del contesto.
- **Lo scarto è nella direzione attesa.** Le riletture osservate sono più grandi di quelle
  stimate, sempre. Se qualcuno misura il contrario, quella è una notizia grossa e va
  segnalata subito.
