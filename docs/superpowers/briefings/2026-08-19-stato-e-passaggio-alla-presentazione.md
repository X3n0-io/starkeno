# Stato al 19/08/2026 — leggere prima di riprendere

La sessione che chiude qui ha lavorato sui problemi aperti dal Passo 1 e sulla scoperta
del progetto da parte degli agenti. La prossima riguarda **presentazione e
marketizzazione**: sito, spiegazione della skill, materiale pubblico.

## Dove sta il codice

`origin/main` è a `855aff1`, tag `v0.3.3` sullo stesso ramo. Suite a **698 passed,
2 skipped** sotto `-W error`. Un commit locale **non pubblicato**: `8c40425`, che registra
la verifica positiva della skill su Codex.

**Il repository GitHub è PRIVATO.** È il fatto più importante per la prossima sessione:
le istruzioni d'installazione nel README — `pip install git+https://…` e
`claude plugin marketplace add X3n0-io/starkeno` — **non funzionano per nessuno tranne il
proprietario** finché resta così. Anche la `description` del repository è vuota.

## Cosa è stato consegnato oggi

- **Il close a metà turno è documentato** dove lo si incontra, con il rimedio.
- **L'hook Claude Code non si fa più scavalcare dalla working directory** (`python -P -m`).
  Era il difetto peggiore: la raccolta funzionava e scriveva nel database sbagliato.
- **`starkeno doctor` vede due cose che prima non poteva**: uno storico più recente del
  canonico (raccolta instradata male) e una copia del plugin più vecchia del pacchetto.
- **Una skill, in due copie identiche con guardia**, che dice all'agente a cosa serve
  StarkEno e quando invocarlo. Verificata su Claude Code **e** su Codex.
- **All'avvio StarkEno dichiara un fatto misurato** invece di tacere, una volta dopo una
  pausa, senza scrivere stato.
- **Il conto smette di promettere un tetto di spesa** che non esiste.
- **README riordinato** perché si legga dall'alto.

## Le misure, che valgono più del codice

1. **Il 61% della spesa degli ultimi 7 giorni è rilettura di contesto.** È il numero su
   cui si regge qualunque presentazione del progetto: non «conta i token», ma «quasi
   due terzi di quello che paghi non è ragionamento, è ricarico di contesto».
2. **La prima esecuzione reale del consuntivo funziona.** Stato `ok`, righe attribuite ai
   nodi attraverso il database, `righe_rifiutate = 0` e `righe_non_scomposte = 0` su
   righe vere: la previsione che i dati reali facessero scattare le guardie non si è
   avverata (n=7, un harness).
3. **Il simulatore non descrive un agente conversazionale**, e adesso è misurato:
   osservato 3.035.535 token contro un massimo stimato di 331.500, perché conta
   `cache_read` solo sui ritentativi mentre un agente vero rispedisce il contesto a ogni
   turno. Non è un difetto da correggere: è la materia prima del Passo 2.
4. **Il rifiuto per sessioni multiple non scatta quasi mai**: 10–25% delle finestre fra
   15 minuti e un'ora, e la causa dominante è la concorrenza fra sessioni, non la
   compattazione. La regola non va ripensata per frequenza.

## Cosa resta aperto

- **Rendere pubblico il repository.** Decisione dell'utente. Finché è privato, tutto il
  materiale di presentazione punta a una porta chiusa.
- **La `description` del repository è vuota**: è la prima riga che un visitatore legge.
- **Più esecuzioni reali del consuntivo**, su lavori di forma diversa — uno lungo, uno
  con molte riletture, uno con ritentativi — per capire se lo scarto del simulatore è una
  costante moltiplicativa o dipende dalla forma. Se è una costante, il Passo 2 costa poco.
- **Nessun rilascio su PyPI.** Il tag `v0.3.3` esiste e si può appuntare, il pacchetto no.

## Vincoli che restano in vigore

- **Nessun push e nessuna modifica remota senza consenso esplicito.** Quelli del 19/08
  erano autorizzati per quell'occasione.
- **Non iniziare la parte C** (esecuzione vera dei workflow): spende soldi veri.
- **Niente dashboard** prima dei feedback degli utenti.
- Non tracciare dati personali, transcript reali, database, log, segreti, percorsi home.
- Le due decisioni portanti restano: l'attribuzione è una **vista** calcolata al
  confronto, mai una colonna sulla riga raccolta; e quando è incerta **si dichiara**.
- Prima di dichiarare completo un lavoro: test pertinenti, `python -m pytest -q -W error`
  e `git diff --check`. Prima di pubblicare, anche `scripts/verifica_segreti.py --tracked`
  e `scripts/verifica_pubblicazione.py`.

## Cosa ha insegnato questa sessione

Tre difetti su quattro li ha trovati **l'esecuzione, non la lettura**, e uno l'ha trovato
l'utente in trenta secondi dopo che avevo scritto specifica, commit e README convinto del
contrario: la skill non arrivava a Codex perché i due harness montano radici di plugin
diverse. Avevo misurato la cosa giusta — che Codex legge quel formato — e dedotto quella
sbagliata, cioè da dove.

Tutti hanno la stessa forma, ed è quella che il progetto continua a pagare: **qualcosa si
perde senza emettere un segnale.** L'hook che scriveva altrove, il doctor che diceva OK,
la cache del plugin ferma a una versione, `ensure_ascii=False` che avrebbe fatto sparire
un contesto intero. La contromisura che ha funzionato ogni volta non è stata rileggere il
codice: è stata eseguirlo e guardare cosa usciva.
