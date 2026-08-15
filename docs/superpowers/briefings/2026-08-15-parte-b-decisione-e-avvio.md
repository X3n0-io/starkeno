# Parte B — la decisione che la sblocca, e la parte C che ne deriva

> Data: 2026-08-15. Documento di consegna, non un piano.
>
> La specifica di riferimento è
> [`specs/2026-08-14-multi-harness-e-preflight-esecuzione-design.md`](../specs/2026-08-14-multi-harness-e-preflight-esecuzione-design.md).
> Qui non si ripete: si dice **cos'è già fatto**, **cosa manca per poter pianificare la
> parte B**, e **come la parte C dipende dalla B**.
>
> **Non esiste un piano per la parte B, ed è voluto.** Un piano scritto oggi conterrebbe
> segnaposto al posto di una decisione, e un segnaposto in un piano è un difetto del
> piano.

---

## 1. Da dove si riparte

La **parte A è consegnata e verificata**: registro degli harness, `leggi()` come
dispatcher, `doctor` che dichiara gli harness rilevati, Claude Code installabile, README
in inglese. Verbale della prova live in
[`../../verification/2026-08-15-claude-code-live.md`](../../verification/2026-08-15-claude-code-live.md).

Il fatto da cui la parte B parte, e che vale la pena ripetere: **in tutto `starkeno/` non
esiste una chiamata a un modello.** Non c'è un client, non c'è una chiave, non c'è una
dipendenza da un fornitore. La parte B è il primo posto in cui StarkEno parlerebbe con la
rete.

---

## 2. La decisione che blocca la parte B

Una sola, e appartiene al proprietario del progetto:

> **Quale fornitore, quale client per l'unica chiamata al modello, e come si configura la
> chiave.**

È più piccola di quanto sembri, perché la specifica ne ha già fissato tre quarti. **Non
sono in discussione:**

- una sola chiamata al modello nel percorso standard, e un solo retry di riparazione,
  soltanto se l'uscita non valida contro lo schema (§3.2);
- la chiave si prende **dall'ambiente dell'utente**: StarkEno non la legge da un file, non
  la scrive, non la registra, non la stampa (§3.3);
- il client vive in un modulo suo, dietro un'interfaccia sottile, così che il resto di
  Preflight resti testabile senza rete e senza chiave (§3.3);
- assenza di chiave o di rete non è un errore da nascondere: il comando lo dice e si
  ferma. Non esiste un ripiego che indovini un Blueprint senza modello (§3.3).

Resta aperto **solo** questo:

| Da decidere | Perché non può deciderlo chi implementa |
|---|---|
| Quale fornitore | Determina costo, latenza e qualità dell'interpretazione, e vincola l'utente finale a un account. È una scelta di prodotto. |
| Quale client | Determina se il progetto acquisisce una dipendenza nuova o riusa `httpx`, che è **già** fra le dipendenze. |
| Nome della variabile d'ambiente | Diventa contratto pubblico verso l'utente: cambiarla dopo rompe le installazioni. |

### Elementi utili alla decisione, non una raccomandazione

- `httpx` è **già** una dipendenza dichiarata in `pyproject.toml`. Un client scritto su
  `httpx` non aggiunge nulla al peso dell'installazione; un SDK di fornitore sì.
- Una sola chiamata, con prompt di sistema e schema come prefisso stabile, è un uso
  abbastanza semplice da non richiedere le comodità di un SDK.
- Il vincolo «prefisso stabile, niente timestamp o id dinamici» (§3.2) esiste per non
  rompere la cache del fornitore: qualunque client si scelga, deve permettere di
  controllare esattamente cosa va nel prompt.
- Il preventivo di token va dichiarato **prima** della chiamata e il consumo osservato
  **dopo**, entrambi mostrati all'utente: il client deve restituire l'uso reale, non solo
  il testo.

Finché questa decisione non è presa, **non si scrive un piano e non si scrive codice**.

---

## 3. Cosa consegna la parte B

Ingresso: testo libero — un obiettivo, un workflow a parole, un prompt esistente, un JSON
o YAML altrui. Uscita: un **Draft Blueprint** che valida contro lo schema esistente, con
assunzioni esplicite e domande aperte.

Il Draft **non viene simulato**. Resta in vigore la regola già costruita: `analyze`
richiede il flag letterale `--confirmed`, e solo quella conferma crea una revisione ed
esegue lint e simulazione. L'interpretazione di un modello non diventa mai verità
strutturata senza che una persona l'abbia guardata.

### La promessa del README

Oggi il README dice `No data leaves your machine`. Resta vero per hook, conto, dashboard e
`doctor`, e diventa **falso** per il solo comando che interpreta il testo.

- La correzione va fatta **nella consegna della parte B**, non prima: anticiparla
  renderebbe il README falso in senso opposto, promettendo una superficie di rete che non
  esiste ancora.
- Va detta **senza attenuarla**. Non «i tuoi dati restano al sicuro», ma esattamente cosa
  esce: il testo che l'utente passa a quel comando, e nient'altro. Niente del secondo
  cervello, dei transcript o del database.

---

## 4. Come la parte C deriva dalla B

La parte C **dipende** dalla B per l'ingresso naturale; non vale il contrario. Chiude il
ciclo che dà senso a tutto il progetto:

```
Blueprint --> Preflight simula --> previsione (token, costo, latenza)
          --> harness esegue   --> transcript --> ingestione --> misura
                                                 confronto  --> calibrazione
```

Il prodotto della parte C **non è** «il workflow è girato»: è il **delta** fra previsto e
misurato, sulle stesse assunzioni, per nodo e per scenario. Uno scarto oltre soglia non è
un fallimento del sistema, è il suo output più utile. Oggi le soglie di `config.py`
derivano dallo storico di una persona sola: questo è il primo meccanismo capace di
sostituirle con qualcosa di ricavato.

StarkEno **non** diventa un framework di agenti: non implementa un loop, non chiama tool,
non decide cosa eseguire. Fa eseguire il Blueprint a un harness che già sa osservare —
Codex o Claude Code — e poi ne legge il risultato con l'ingestione che esiste dalla Fase 2.

### Vincoli non negoziabili della parte C

Sono già nella specifica §4.3 e non si rinegoziano in fase di piano:

1. **Flag letterale e separato** per confermare, sullo stile di `--confirmed`: qui si
   spendono soldi veri e si eseguono tool veri.
2. Il preventivo della simulazione si mostra **prima**, e la conferma lo cita.
3. **Tetto di spesa obbligatorio, senza default.** Lo passa l'utente sul comando, e
   superarlo interrompe la corsa. Un default significherebbe che qualcuno spende quella
   cifra senza averla scelta.
4. L'esecuzione **non parte mai** da un hook, da `report`, da `doctor` o dalla dashboard.
5. Si esegue nell'harness dell'utente, con i suoi permessi e le sue approvazioni di tool.
   StarkEno non aggira né allarga nulla.
6. Le righe misurate finiscono in `agent_actions` come qualsiasi altra chiamata: sono
   spesa reale e devono comparire nel conto.
7. Nella suite **nessun test spende soldi**: il confronto previsto/misurato si prova su
   una corsa registrata.

---

## 5. Cosa non fare

- Non scegliere fornitore, client o nome della variabile al posto del proprietario.
- Non scrivere un piano della parte B prima di quella decisione.
- Non iniziare la parte C prima che la B esista: senza ingresso naturale non c'è il
  Blueprint da eseguire.
- Non correggere il README sulla rete prima della consegna della parte B, e non attenuarlo
  quando lo si corregge.
- Non aggiungere Cursor, OpenCode o OpenClaw: restano fuori finché non esiste un transcript
  vero da cui leggerne lo schema. Dedurlo dalla documentazione produce numeri plausibili e
  sbagliati, che per questo progetto è il fallimento peggiore.
- Non trasformare l'harness in una colonna del database.

---

## 6. Una nota di metodo, guadagnata

La parte A ha trovato tre difetti che nessun test della suite avrebbe potuto trovare, e
tutti e tre avevano la stessa forma: **la raccolta si perdeva senza emettere un segnale.**
Uno di essi avrebbe fatto dichiarare a `doctor` «raccolta recente» mentre osservava il
database sbagliato.

Sono emersi solo perché il piano imponeva di **provare l'installazione vera prima di
dichiararla supportata**, e sono costati molti tentativi perché i primi giri sono stati
spesi in ipotesi invece che in misure. La causa è arrivata appena l'hook è stato
strumentato per raccontare cosa riceveva.

Le parti B e C hanno la stessa esposizione, aggravata: la B manda testo a un terzo, la C
spende soldi ed esegue tool veri. Vale la stessa disciplina — misurare invece di
assumere, e preferire un difetto rumoroso a un successo silenzioso.
