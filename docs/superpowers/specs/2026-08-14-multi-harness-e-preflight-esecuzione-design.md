# Multi-harness e Preflight eseguito — progetto

> Data: 2026-08-14.
>
> Tre parti separabili, in un solo documento perché condividono un'idea: **StarkEno
> misura, non indovina.** La parte A estende la misura ad altri harness, la parte B dà a
> Preflight una porta d'ingresso in linguaggio naturale, la parte C chiude il ciclo
> facendo eseguire davvero il Blueprint e confrontando previsione e misura.
>
> Ogni parte ha il suo gate e può essere consegnata da sola. La parte C dipende dalla B
> per l'ingresso naturale, ma non viceversa; la parte A è indipendente da entrambe.

---

## 1. Stato verificato il 14/08/2026

Non ipotesi: misure fatte su questa macchina prima di scrivere.

| Harness | Hook di fine turno | Token nel transcript | Esito |
|---|---|---|---|
| Codex | `Stop` | sì | in produzione |
| Claude Code | `Stop` | sì | **parser già completo**, manca l'installazione |
| Antigravity | `Stop` | **no** | non misurabile, vedi §5 |
| OpenClaw | sì | sì (documentazione) | schema non verificato |
| Cursor | `stop` | non esposto dagli hook | schema non verificato |
| OpenCode | plugin | sì, ma in SQLite | schema non verificato |

**Claude Code, prova su transcript reale** (837 righe): 164 chiamate lette, modello
`claude-opus-5` su tutte, chiave `(session_id, message_id)` unica su 164 di 164, esito
noto su 164 di 164, 14 azioni fallite riconosciute, 2 chiamate attribuite a un server
MCP, zero timestamp vuoti. Il ramo Claude Code popola `skill`, `plugin`, `mcp_server` e
`is_sidechain`, che il ramo Codex lascia vuoti.

**Antigravity, prova negativa.** Il transcript (`transcript.jsonl` e `transcript_full.jsonl`)
contiene `type`, `content`, `created_at`, `status`, `step_index`, `tool_calls`,
`thinking`, `exit_code`, `error`. Ricerca su tutta la cartella dati per nome file
(`*token*`, `*usage*`, `*metric*`, `*cost*`) e per contenuto, incluse le chiavi native di
Gemini `promptTokenCount`, `candidatesTokenCount`, `cachedContentTokenCount`: **zero
riscontri.** Il transcript registra i passi dell'agente, non la spesa.

**In tutto `starkeno/` non esiste una chiamata a un modello.** Gli unici riscontri su
`anthropic` sono una regex che normalizza i nomi Bedrock in `rules.py`. È il fatto da cui
parte la parte B.

---

## 2. Parte A — Il seam multi-harness

### 2.1 Il confine è `Chiamata`, non il formato del file

`transcript.leggi()` oggi distingue Codex da Claude Code annusando la prima voce, con un
`if` dentro la funzione. Aggiungere harness per accumulo di rami rende quella funzione il
posto dove ogni formato futuro deve passare — e OpenCode, che vive in SQLite, non ha
righe da annusare.

Il seam corretto è il tipo che tutti producono: `Chiamata`. Un harness JSONL e un harness
SQLite sono lo stesso oggetto rispetto al resto del sistema.

### 2.2 `starkeno/harness.py`

Modulo nuovo. Un `Harness` dichiara:

- `nome`: identificatore stabile (`"codex"`, `"claude-code"`, …), usato in diagnostica e
  documentazione, mai nello schema del database;
- `riconosce(prima_voce: dict) -> bool`: predicato sul primo oggetto JSON utile;
- `leggi(righe) -> list[Chiamata]`: la lettura pura, per gli harness a righe;
- `misurabile: bool` e `motivo_non_misurabile: str | None`: vedi §5.

Il registro è una tupla ordinata. Il primo `riconosce` che risponde vince; nessun harness
riconosciuto significa **zero chiamate**, mai una stima.

### 2.3 Cosa NON cambia

- `transcript.py` resta un modulo puro: niente disco, niente orologio, niente ambiente.
  Le due letture esistenti diventano funzioni del registro senza cambiare comportamento.
- `leggi(righe)` **mantiene la firma pubblica attuale** e diventa un dispatcher sottile.
  Nessun chiamante a valle cambia.
- Lo schema del database non cambia. L'harness non diventa una colonna: `agent_actions`
  descrive chiamate, e un campo che nessuna query legge sarebbe peso senza uso.

### 2.4 Harness con sorgente non testuale

Un harness che non ha righe (OpenCode: SQLite) non implementa `leggi(righe)` ma un
lettore proprio che produce `list[Chiamata]`. Il registro lo ammette perché il contratto
è il tipo restituito. Nessun harness di questo genere è incluso qui: la voce esiste
perché il seam deve reggerlo senza essere riscritto.

### 2.5 Claude Code come harness installabile

Il parser c'è; manca l'installazione. Serve un manifest per plugin Claude Code.

**Da verificare, non da assumere.** `hooks/hooks.json` usa `${PLUGIN_ROOT}` e
`%PLUGIN_ROOT%`; i plugin Claude Code usano `${CLAUDE_PLUGIN_ROOT}`. I due manifest si
somigliano abbastanza da sembrare compatibili, ed è esattamente la trappola che
`AGENTS.md` vieta: «Non assumere che payload, hook o manifest di un agente siano
compatibili con un altro.» L'implementazione deve provare l'installazione vera prima di
dichiararla supportata; se le variabili divergono servono due manifest distinti, non uno
con sostituzioni condizionali.

### 2.6 README in inglese

Il README passa all'inglese e descrive **lo stato verificato del §1**, non l'ambizione di
questo documento: Codex e Claude Code supportati e misurati, Antigravity rilevato e
dichiarato non misurabile col motivo, gli altri tre non ancora.

Deve spiegare in modo comprensibile a chi arriva da fuori tre cose che oggi il README
italiano dà per scontate: **che cosa** StarkEno osserva (le chiamate che il tuo agente fa
già, rilette dai transcript che scrive da sé), **come** ci arriva (un hook di fine turno,
fail-open, che non rallenta il lavoro) e **perché** i token non sono il fine (sono
l'unità in cui si misurano spreco ed errore).

Le sezioni su rete e privacy restano quelle vere di oggi. Si correggono quando esce la
parte B, non prima — vedi §6.

---

## 3. Parte B — La porta d'ingresso in linguaggio naturale

Completa il §1 della specifica Preflight del 13/08/2026, che la prevedeva e non è mai
stata costruita.

### 3.1 Contratto

Ingresso: testo libero — un obiettivo, un workflow descritto a parole, un prompt
esistente, un JSON o YAML altrui. Uscita: un **Draft Blueprint** che valida contro lo
schema esistente, accompagnato da assunzioni esplicite e domande aperte.

Il Draft **non viene simulato**. Vale la regola già in vigore: `analyze` richiede il flag
letterale `--confirmed`, e solo quella conferma crea una revisione ed esegue lint e
simulazione. L'interpretazione di un modello non diventa mai verità strutturata senza
che una persona l'abbia guardata.

### 3.2 Disciplina economica

La specifica del 13/08 impone al progetto di dimostrare ciò che predica. Vincoli
vincolanti, non aspirazioni:

- **una** chiamata al modello nel percorso standard;
- **un solo** retry di riparazione, e soltanto quando l'uscita non valida contro lo schema;
- il preventivo di token è dichiarato **prima** della chiamata e il consumo osservato
  **dopo**, entrambi visibili all'utente;
- prompt di sistema e schema restano un prefisso stabile: niente timestamp, niente id di
  richiesta, niente metadati dinamici che rompano la cache;
- nessun team interno di agenti.

### 3.3 Confine di rete

È l'unica superficie di StarkEno che parla con la rete, ed è **esplicita e opt-in**.

- Hook, `report`, dashboard e `doctor` restano offline. L'invariante «nessuna richiesta di
  rete nel percorso predefinito» resta intatta perché questo non è il percorso predefinito.
- Il client vive in un modulo suo, isolato dietro un'interfaccia sottile, così che
  il resto di Preflight resti testabile senza rete e senza chiave.
- Nessuna chiave viene letta, scritta o registrata da StarkEno: si usa quella già presente
  nell'ambiente dell'utente.
- **Nulla del secondo cervello, dei transcript o del database viene inviato.** Va al
  modello soltanto il testo che l'utente passa a quel comando.
- Assenza di chiave o di rete non è un errore da nascondere: il comando lo dice e si
  ferma. Non esiste un ripiego che indovini un Blueprint senza modello.

---

## 4. Parte C — Esecuzione reale misurata

### 4.1 Cosa NON è

Non è StarkEno che diventa un framework di agenti. Non implementa un loop, non chiama
tool, non decide cosa eseguire.

### 4.2 Cosa è

StarkEno **fa eseguire il Blueprint a un harness che già sa osservare** — Codex o Claude
Code — e poi legge il risultato con l'ingestione che esiste dalla Fase 2. Il ciclo si
chiude da sé:

```
Blueprint --> Preflight simula  --> previsione (token, costo, latenza)
          --> harness esegue    --> transcript --> ingestione --> misura
                                                  confronto --> calibrazione
```

Questo soddisfa la condizione che il §16 della specifica del 13/08 poneva al dry-run
reale: senza esecuzioni vere non esiste l'errore misurato che avrebbe dovuto
autorizzarlo. La parte C è ciò che rende quella decisione decidibile.

### 4.3 Vincoli

- **Conferma esplicita**, sullo stile di `--confirmed` già in uso: un flag letterale e
  separato, perché qui si spendono soldi veri dell'utente e si eseguono tool veri.
- Il preventivo della simulazione viene mostrato **prima** e la conferma lo cita.
- L'esecuzione avviene nell'harness dell'utente, con i suoi permessi e le sue approvazioni
  di tool. StarkEno non aggira né allarga nulla.
- Un tetto di spesa è **obbligatorio**, non opzionale con un default: lo passa l'utente
  sul comando, e superarlo interrompe la corsa. Un default significherebbe che qualcuno
  spende quella cifra senza averla scelta.
- L'esecuzione **non parte mai** da un hook, da `report`, da `doctor` o dalla dashboard.
- Le righe misurate finiscono in `agent_actions` come qualsiasi altra chiamata: sono
  spesa reale e devono comparire nel conto.

### 4.4 Il confronto

Il prodotto della parte C non è "il workflow è girato". È il **delta**: previsto contro
misurato, sulle stesse assunzioni, per nodo e per scenario. Un errore sistematico è il
dato che serve a tarare le stime; oggi le soglie di `config.py` derivano dallo storico di
una persona sola, e questo è il primo meccanismo che può sostituirle con qualcosa di
ricavato.

Uno scarto oltre soglia non è un fallimento del sistema: è il suo output più utile, e va
mostrato come tale invece di essere assorbito.

---

## 5. Antigravity: non misurabile, e detto

Antigravity non entra fra gli harness misurabili. La prova è al §1: non espone i token da
nessuna parte.

Ma non deve sparire in silenzio, perché **il silenzio è indistinguibile dalla salute** — è
l'errore che questo progetto rifiuta ovunque. Un utente che installa StarkEno avendo
Antigravity deve capire *perché* non vede numeri, invece di vedere zero e sospettare un
difetto.

- `starkeno doctor` riconosce Antigravity se presente e dichiara: rilevato, non
  misurabile, con il motivo — il suo transcript non contiene conteggi di token.
- Gli hook restano muti: l'invariante 12 vieta stderr e rumore, e vale anche qui.
- Il registro porta la voce con `misurabile = False`, così il fatto vive nel codice
  accanto agli altri harness invece che solo nella documentazione, dove invecchierebbe.

Se una versione futura di Antigravity esporrà i token, cambia il predicato, non
l'architettura.

---

## 6. Invarianti toccati

| Invariante | Effetto |
|---|---|
| Nessuna rete nel percorso predefinito | **Retto.** Parti B e C sono superfici esplicite, mai il default. |
| Nessun dato lascia la macchina | **Vero oggi; ristretto quando esce la parte B.** Resta vero per hook, conto, dashboard e doctor. Diventa falso per il solo comando che interpreta il testo, che invia il testo dato dall'utente. Il README va corretto **nella consegna della parte B**, non prima, e deve dirlo esattamente così senza attenuarlo. |
| Hook fail-open e silenziosi | **Retto.** Nessuna delle tre parti aggiunge lavoro agli hook. |
| Solo `db.py` importa SQLAlchemy | **Retto.** |
| Alembic unica autorità sullo schema | **Retto:** nessuna migrazione richiesta. |
| I test non toccano il database reale | **Retto:** fixture sintetiche. |
| Test e fixture senza dati personali | **Vincolante qui.** Le prove del §1 sono state fatte su transcript reali e **nessuno di essi entra nel repository**: le fixture per harness sono scritte a mano. |

---

## 7. Fuori ambito

- Cursor, OpenCode e OpenClaw: una specifica ciascuno, quando esiste un transcript vero
  da cui leggere lo schema. Dedurlo dalla documentazione produce numeri plausibili e
  sbagliati, che è il fallimento peggiore possibile per questo progetto.
- L'harness come colonna del database.
- Team interno di agenti nella parte B.
- Esecuzione di workflow che non passi da un harness già osservabile.
- Probabilità di successo e suggerimento di skill non installate: restano rinviate con le
  condizioni del §16 della specifica del 13/08.

---

## 8. Test

- **Differenziale sul dispatch**: il registro deve produrre esattamente ciò che
  `leggi()` produce oggi sulle fixture esistenti. È la rete che rende sicuro il
  rifacimento della parte A.
- **Fixture sintetiche per harness**, mai transcript reali.
- **Formato ignoto**: zero chiamate, nessuna eccezione, nessuna stima.
- **Parte B senza rete**: il client è sostituibile; i test non fanno richieste e non
  richiedono chiavi. Un'uscita che non valida deve provocare un solo retry, e il secondo
  fallimento deve essere dichiarato.
- **Parte C**: il confronto previsto/misurato si prova su una corsa registrata, non su
  una esecuzione vera dentro la suite. Nessun test spende soldi.
- Ogni test deve avere una regressione concreta che lo renda rosso (invariante 13).

---

## 9. Rischi

1. **La parte C spende soldi veri dell'utente.** Mitigazione: flag letterale separato,
   preventivo mostrato prima, tetto di spesa, mai da un percorso automatico.
2. **La parte B invia testo dell'utente a un fornitore esterno.** Mitigazione: solo il
   testo passato a quel comando, opt-in, e la promessa del README corretta invece che
   difesa.
3. **Il manifest Claude Code potrebbe non essere compatibile.** Mitigazione: provarlo
   davvero prima di dichiararlo, §2.5.
4. **Tre parti in un documento invitano a consegnarle insieme.** Mitigazione: gate
   separati; la parte A è utile da sola e non dipende dalle altre.
