# StarkEno

**Quanto costerà questo lavoro dell'agente — prima di lanciarlo?**

Tutti gli altri strumenti rispondono dopo. Leggono gli stessi transcript locali che il tuo
agente già scrive e ti dicono, con precisione, quanto hai speso. È un problema risolto, e
ci sono buoni strumenti che lo fanno.

StarkEno è costruito attorno alla domanda che non fanno. È l'unica cosa qui che meriti la
tua attenzione, ed è agli inizi.

> **Stato: Fase 2.** La raccolta funziona e il conto locale è reale e installabile. La
> previsione è costruita e raggiungibile a mano, ed è stata confrontata con un'esecuzione
> vera **una volta sola** — quella misura è la prossima cosa su questa pagina.

## L'unica misura vera

> StarkEno aveva previsto un'esecuzione a **331.500 token** al massimo.
> L'esecuzione ne è costati **3.035.535**. La previsione ha sbagliato di **9 volte**.

Un'esecuzione, una macchina, un agente. Sta in cima a questo README invece che sepolta in
fondo, perché uno strumento di previsione che nasconde il proprio errore non vale niente —
e perché l'errore si è rivelato la parte interessante.

**Non era rumore. Era strutturale, e la struttura si conosce.**

Il simulatore conta il contesto scritto in cache una volta per invocazione, e il contesto
riletto solo sui ritentativi. Un agente vero fa una cosa completamente diversa: non ha
memoria fra un turno e l'altro, quindi rispedisce tutto quello che sa a **ogni** turno.
Sulla macchina dove è stato misurato, quella rilettura è stata il **60% della spesa di una
settimana intera** — esattamente la quantità che il simulatore quasi non conta.

Quindi il modello non stava sbagliando i conti. Stava descrivendo l'animale sbagliato.

La distinzione conta, ed è il motivo per cui questo progetto esiste invece di essere stato
abbandonato: **un errore casuale è un vicolo cieco, uno strutturale è un coefficiente.**
La domanda aperta è quale forma abbia —

- se lo scarto è una **costante moltiplicativa**, la correzione è un numero solo e la
  previsione diventa utile subito;
- se **dipende dalla forma del lavoro** — un'esecuzione lunga, una con molte riletture,
  una piena di ritentativi — allora serve un modello per forma.

Distinguere i due casi richiede più esecuzioni vere. È il lavoro in corso, ed è lo stato
onesto del progetto: una misura, un meccanismo noto, e una domanda senza risposta.

## Cosa puoi davvero usare oggi

La metà predittiva **non è spedita come funzione pronta** — vedi
[La previsione](#la-previsione-preventivo-contro-consuntivo) per cosa significa
esattamente e come raggiungerla lo stesso.

Quello che è finito, testato e installabile è l'altra metà: la misura contro cui la
previsione va confrontata.

**Un hook di fine turno rilegge il transcript che il tuo agente già scrive**, e registra
ogni chiamata API in un database SQLite locale. StarkEno non ti guarda mai digitare e non
avvolge mai il tuo agente.

**Niente lascia la tua macchina.** Nessuna chiamata di rete, nessun account, nessuna
telemetria. Il conto è un file HTML statico sul tuo disco.

**Non può costarti un turno.** Gli hook escono `0` qualunque cosa accada e non scrivono
mai su stderr. Se StarkEno si rompe, il tuo lavoro no — che è anche il motivo per cui uno
StarkEno rotto è invisibile, e per cui esiste `starkeno doctor`.

**Due agenti, un conto solo.** Claude Code e Codex finiscono nello stesso database con gli
stessi totali. Se li usi entrambi, nessun altro te li somma.

## Partenza rapida

Incolla questo a Claude Code o a Codex:

> Installa StarkEno da https://github.com/X3n0-io/starkeno su questa macchina, poi
> verifica che stia raccogliendo.

Oppure fallo a mano. **Due passi, ed entrambi sono obbligatori** — il plugin è solo un
manifest, e senza il pacchetto gli hook partono, non importano niente ed escono `0` in
silenzio:

```bash
pip install git+https://github.com/X3n0-io/starkeno.git
```

```bash
claude plugin marketplace add X3n0-io/starkeno
claude plugin install starkeno@starkeno-local
```

Riavvia l'agente, approva gli hook, lavora un turno normale, poi:

```bash
starkeno doctor     # sta raccogliendo davvero?
starkeno report     # il conto
```

Se `doctor` non è verde, credi a `doctor` — non all'assenza di errori. Uno StarkEno muto
è identico a uno che funziona.

## Il conto

```bash
starkeno report                                          # lo genera e lo apre
starkeno report --output conto.html --no-open            # oppure scrive solo il file
```

Una pagina HTML statica sul tuo disco. Non avvia server, non fa chiamate di rete e non
tocca il database. Cosa mostra, e perché ogni colonna è lì:

| Colonna | Cosa conta | Perché ti interessa |
|---|---|---|
| **Costo di lavoro** | i token che il modello ha davvero prodotto | l'unica parte che è il lavoro |
| **Costo di caricamento** | contesto scritto in cache | il prezzo di preparare il lavoro |
| **Costo di rilettura** | contesto riletto nei turni successivi | ripagato a ogni turno, per lo stesso materiale |
| Esiti ignoti | chiamate di cui non si è potuto stabilire l'esito | quanta parte del quadro è congettura |
| Righe non classificabili | chiamate la cui scomposizione dei token si contraddice | quanto diffidare |

Le ultime due righe sono quelle che gli altri strumenti non ti mostrano. Un numero che non
puoi controllare vale meno di un numero più piccolo che puoi controllare, e la previsione
vale solo quanto la misura contro cui viene giudicata.

<!-- QUI VA LA GIF/SCREENSHOT DEL CONTO.
     Sostituire questo commento con:  ![Il conto](docs/immagini/conto.gif)
     Finche' l'immagine non esiste, meglio un commento che un link rotto. -->

Una forma d'esempio — *i tuoi numeri saranno diversi, ed è il rapporto la parte
interessante*:

```
1 678 chiamate, 2 036 azioni

  costo di lavoro         10 500 000     15%
  costo di caricamento    20 150 000     28%
  costo di rilettura      41 750 000     58%   <-- lo stesso contesto, ancora e ancora
```

Gli stessi totali sono scomposti per progetto, modello, sessione, skill, plugin e server
MCP, più il ritmo locale degli ultimi sette giorni. **Le etichette skill, plugin e MCP si
sovrappongono e non vanno mai sommate** — una sola chiamata può portarle tutte e tre.

## Installazione

### Fallo fare al tuo agente

Incolla questo a Claude Code o a Codex:

> Installa StarkEno da https://github.com/X3n0-io/starkeno su questa macchina, poi
> verifica che stia raccogliendo.

**Istruzioni per l'agente.** I passi sono due e saltare il primo è il guasto tipico: il
plugin è solo un manifest, e senza il pacchetto gli hook partono, non riescono a importare
niente ed escono `0` in silenzio.

1. Installa il pacchetto. Serve Python 3.12–3.14 nel `PATH`:
   ```bash
   pip install git+https://github.com/X3n0-io/starkeno.git
   ```
   Verifica con `starkeno --help`. Se il comando non si trova, il `pip` e il `python`
   dell'utente sono installazioni diverse: risolvi quello prima di proseguire.

2. Installa il plugin per l'agente in uso. Per Claude Code:
   ```bash
   claude plugin marketplace add X3n0-io/starkeno
   claude plugin install starkeno@starkeno-local
   ```
   Per Codex, aggiungi lo stesso repository come marketplace dal suo pannello dei plugin e
   installa `starkeno`. Non modificare `~/.codex/config.toml` a mano.

3. Fai riavviare l'agente all'utente e fagli approvare gli hook quando richiesto. Gli hook
   si leggono all'avvio della sessione, quindi fino ad allora non si raccoglie niente.

4. Dopo un turno completato, verifica:
   ```bash
   starkeno doctor
   ```

| Cosa dice | Cosa significa | Cosa fare |
|---|---|---|
| `raccolta: nessun evento raccolto` | non è mai stato raccolto niente | manca il pacchetto, oppure gli hook non sono mai stati approvati |
| `plugin_claude_aggiornato: ... diverso dal pacchetto` | la copia installata del plugin è più vecchia del pacchetto | aggiornala **attraverso l'agente**; non cancellare mai la copia in cache a mano, quello disinstalla |
| `inventario_storici: la raccolta sta scrivendo altrove` | le righe finiscono in un database che nessun comando legge | non si è perso niente; i due vanno uniti |
| `schema: schema disallineato` | il database precede la revisione corrente | segnalalo all'utente invece di migrare in silenzio |

Non dichiarare il successo finché `starkeno doctor` non mostra una raccolta recente. Uno
StarkEno muto è identico a uno che funziona.

### Fallo a mano

StarkEno è **due cose separate, e ti servono entrambe**:

1. il **pacchetto Python**, che fa tutto il lavoro;
2. il **plugin** per il tuo agente, che è solo un manifest che dice quando chiamarlo.

Installare il plugin **non** installa il pacchetto. Se il pacchetto manca, gli hook partono
lo stesso, non riescono a importarlo ed escono `0` in silenzio — di proposito, perché un
hook non deve mai rompere il tuo turno. Il risultato è un agente che sembra strumentato e
non raccoglie niente, senza un errore da nessuna parte. È `starkeno doctor` che te lo dice:
lancialo dopo l'installazione.

Serve Python 3.12, 3.13 o 3.14 nel `PATH`. Non c'è ancora un rilascio su PyPI, quindi il
pacchetto arriva direttamente da git:

```bash
pip install git+https://github.com/X3n0-io/starkeno.git
```

Oppure da un clone, se vuoi il sorgente sottomano:

```bash
git clone https://github.com/X3n0-io/starkeno.git
cd starkeno
pip install .
```

Poi installa il plugin per il tuo agente — Codex qui sotto, Claude Code subito dopo.

### Codex

StarkEno si spedisce come plugin Codex con due hook:

- `Stop` avvia in background la rilettura di fine turno e registra le chiamate nuove;
- `SessionStart`, sincrono e limitato a `startup`, aggiunge contesto per una breve riga di
  benvenuto solo finché non c'è ancora storico.

1. riavvia l'app desktop ChatGPT/Codex, perché il marketplace del repository si legge
   all'avvio;
2. apri `/plugins`, scegli **StarkEno Local** e installa `starkeno`;
3. avvia una sessione nuova;
4. apri `/hooks`, controlla e approva `SessionStart` e `Stop`;
5. completa tre turni normali;
6. lancia `starkeno doctor` e controlla la revisione dello schema, una raccolta recente e
   il plugin trovato.

Non modificare `~/.codex/config.toml` a mano. Se l'app non espone il marketplace,
l'alternativa ufficiale è `codex plugin marketplace add .`, da usare solo quando il binario
locale `codex` gira senza errore `Access denied`.

### Claude Code

```bash
claude plugin marketplace add .
```

```bash
claude plugin install starkeno@starkeno-local
```

Poi avvia una sessione nuova, approva gli hook, completa un turno e controlla con
`starkeno doctor`.

Il bundle per Claude Code vive in una directory propria e i suoi hook **non** sono quelli
di Codex. Non è ordine, è misura:

- gli hook sono **sincroni**. Le varianti non bloccanti sono state provate su turni veri e
  non hanno raccolto niente: l'avviatore torna in 354 ms e `async: true` torna subito,
  mentre l'ingestione ha bisogno di circa 1600 ms, e il processo non sopravvive. Claude
  Code non raccoglie nemmeno l'esito di un hook asincrono, quindi una lista di errori vuota
  significa «non lo so», non «è andata bene»;
- c'è un `SessionEnd` oltre allo `Stop`. Lo `Stop` scatta *prima* che il turno sia su
  disco; siccome l'ingestione rilegge tutto ed è idempotente, il turno N viene preso al
  turno N+1 — ma l'ultimo turno di una sessione un turno successivo non lo avrebbe mai.
  `SessionEnd` gira a transcript chiuso.

## Controllare che stia raccogliendo

Si parte da qui:

```bash
starkeno doctor
```

Quattro dei suoi controlli rispondono a quattro domande diverse, e ognuno è stato almeno
una volta la cosa che era davvero rotta:

| Controllo | Dice |
|---|---|
| `raccolta` | se sia stato raccolto qualcosa di recente |
| `plugin_claude_aggiornato` | se la copia installata del plugin corrisponda al tuo pacchetto |
| `inventario_storici` | se *un altro* database abbia righe più recenti di quello canonico — la firma di una raccolta che scrive nel file sbagliato |
| `schema` | se il database sia stato migrato alla revisione corrente |

Una raccolta instradata male non sembra rotta. L'hook riesce, le righe sono complete, e
finiscono in un file che nessun altro legge. `inventario_storici` esiste perché è successo,
ed è passato inosservato per quattro giorni.

**Le chiamate sono raggruppate per `project`, che è l'ultimo segmento della directory di
lavoro in cui la sessione dell'agente è stata avviata** — non il repository che stai
modificando. Se apri l'agente in una cartella e lavori su codice in un'altra, le righe
portano la prima.

Per i numeri grezzi:

```bash
python -c "
import sqlite3, starkeno.config as c
con = sqlite3.connect(c.DB_PATH)
print('database:', c.DB_PATH)
print('chiamate:', con.execute('SELECT COUNT(*) FROM agent_actions').fetchone()[0])
for r in con.execute('SELECT project, COUNT(*), SUM(tokens_used) FROM agent_actions GROUP BY project ORDER BY 2 DESC'):
    print('  %-28s %5d chiamate  %12d token' % r)
"
```

## Aggiornare

**Correggere il codice non aggiorna quello che gira sulla tua macchina.** Gli agenti
installano un plugin **copiandolo** nella propria cache, e quella copia — non il tuo albero
di lavoro — è ciò che esegue. Correggere un hook nel repository, o anche fare `git pull`,
non cambia niente finché l'agente non ricopia.

È la cosa più importante da sapere su StarkEno in esecuzione, perché fallisce in silenzio
in entrambe le direzioni: il repository sembra corretto, la macchina continua a eseguire il
codice vecchio, e agli hook non è permesso lamentarsi.

Per aggiornare:

```bash
git pull
pip install .
```

poi aggiorna il plugin **attraverso l'agente stesso** — il suo comando o pannello dei
plugin — così rinfresca la propria copia. Non cancellare la copia in cache a mano:
l'agente registra il percorso d'installazione, e rimuovere la directory disinstalla il
plugin invece di aggiornarlo.

Poi verifica:

```bash
starkeno doctor
```

`plugin_claude_aggiornato` confronta la copia installata con il pacchetto che hai e dice
`attenzione` quando differiscono. È il controllo che trasforma «l'avevo corretto giorni fa»
in qualcosa che si vede.

## Agenti supportati

| Agente | Stato |
|---|---|
| Codex | Supportato. Installabile come plugin, legge il transcript a eventi. |
| Claude Code | Supportato. Installabile come plugin, legge il transcript a messaggi. |
| Antigravity | Rilevato e riportato, **non misurabile**. Il suo transcript non contiene conteggi di token in nessun punto della sua cartella dati — verificato per nome file e per contenuto, incluse le chiavi native di Gemini `promptTokenCount`, `candidatesTokenCount` e `cachedContentTokenCount`. |
| Cursor, OpenCode, OpenClaw | Non ancora. Manca un transcript vero da cui leggere uno schema. |

Un agente riconosciuto ma non misurabile produce **zero chiamate, mai una stima**.
`starkeno doctor` elenca cosa ha trovato sulla tua macchina e, per ciò che non sa misurare,
dice perché — perché gli hook devono restare muti, e zero righe senza spiegazione è
indistinguibile da un difetto.

## Dove stanno i dati

Il database non vive nella cartella del plugin: gli aggiornamenti non possono cancellare il
tuo storico.

| Sistema | Percorso |
|---|---|
| Windows | `%USERPROFILE%\.starkeno\starkeno.db` |
| macOS | `~/Library/Application Support/StarkEno/starkeno.db` |
| Linux | `$XDG_DATA_HOME/starkeno/starkeno.db`, altrimenti `~/.local/share/starkeno/starkeno.db` |

`STARKENO_DB_PATH` ha la precedenza su questi percorsi.

Su Windows il database **non** sta sotto `%LOCALAPPDATA%`, anche se è la convenzione della
piattaforma. Un processo lanciato da un host impacchettato MSIX scrive lì dentro l'overlay
privato del pacchetto: misurato, lo stesso script contava 12 righe lanciato dall'hook e 699
da una shell, allo stesso percorso. La raccolta finirebbe in un database che `report` e
`doctor` non guardano mai, senza un solo errore. Se stai aggiornando da una versione
precedente, `starkeno doctor` segnala il vecchio storico come recuperabile.

`starkeno doctor` fa un inventario in sola lettura del percorso canonico, di `starkeno.db`
accanto al codice, e di eventuali `starkeno.db.trasferito`. Nessun hook sposta o rinomina
il tuo storico. Il recupero richiede sempre un percorso esplicito e una conferma:

```bash
starkeno doctor --repair-from ./starkeno.db.trasferito --confirm-repair
```

La sorgente resta intatta; se la destinazione esiste viene prima salvata in una copia
datata. Il recupero migra e verifica la copia prima di adottarla.

## La previsione: preventivo contro consuntivo

È la metà per cui il progetto esiste.

Preflight stima quanto *dovrebbe* costare un Blueprint. Gli hook registrano quanto
l'agente ha *davvero* speso. Il confronto mette i due fianco a fianco: dove il totale
osservato cade dentro la fascia stimata, e lo scarto per nodo, ordinato per grandezza.
Rilancialo la settimana dopo e vedi se la previsione si sta avvicinando.

> ### Cosa significa «non spedita», per la precisione
>
> **Il plugin non registra questi tool.** Installa hook e una skill, non un server MCP.
> Per raggiungere la previsione devi registrare tu `python -P -m starkeno.mcp_server` come
> server MCP stdio, e devi passargli un Blueprint strutturato — Preflight non legge ancora
> un workflow descritto a parole.
>
> È deliberato, non una dimenticanza. Questa metà è stata confrontata con un'esecuzione
> vera **una volta**, e per il resto solo con fixture sintetiche. Il progetto non spedisce
> ciò che non ha misurato. Al conto e alla diagnosi non serve niente di tutto questo.
>
> Se vuoi aiutare a rispondere alla domanda aperta, è questa la parte da provare.

### Perché il confronto è affidabile anche quando la previsione sbaglia

Una previsione vale quanto vale il modo in cui si tiene il punteggio. Tre decisioni
reggono quel peso, e sono il motivo per cui il 9x qui sopra è credibile come **misura**
invece che come artefatto:

**L'attribuzione è dichiarata, mai indovinata.** L'agente segna ogni cambio di nodo mentre
lavora. Le chiamate che cadono fuori da ogni intervallo dichiarato sono riportate come non
attribuite invece di essere assegnate al vicino. Un numero sul nodo sbagliato manda la
calibrazione nella direzione sbagliata, che è peggio di un numero lasciato senza padrone.

**L'attribuzione è una vista, non un timbro.** Si calcola al momento del confronto e non
viene mai scritta come colonna sulla riga raccolta. Chiudere due volte un'esecuzione la
ricalcola. La misura grezza resta grezza, così un errore nella logica di attribuzione è
correggibile dopo, invece che cotto dentro il tuo storico.

**Quando non sa, si ferma.** Se la finestra contiene più di una sessione, il confronto si
interrompe e lo dichiara invece di sceglierne una. Osservato su dati veri: scatta sul
10–25% delle finestre, e la causa dominante è vera concorrenza fra sessioni.

Entrambi i lati dichiarano i propri buchi. Le chiamate osservate il cui modello non è
mappato a un modello del Blueprint, o la cui scomposizione dei token manca o si contraddice,
vengono contate e nominate invece che valorizzate a un numero dall'aria plausibile; e quando
il Blueprint omette un prezzo, la stima dice quale modello non ha saputo valorizzare. Il
denaro è riportato come **assente, non zero**, quando non esiste un listino completo, o
quando i listini usano più di una valuta.

### Il 9x, dentro l'output

Uno scarto è atteso e non è un difetto: la simulazione conta `cache_write` una volta per
invocazione e `cache_read` solo sui ritentativi, mentre un agente vero rispedisce il
contesto a ogni turno. Le riletture osservate saranno molto più grandi di quelle stimate,
sistematicamente. L'output lo dice, perché la prima persona che lo vede penserà di aver
sbagliato una sottrazione.

### I tool

Tre tool MCP lo guidano, accanto a `log_agent_action`. Nessuno solleva eccezioni: gli
errori tornano come testo semplice, e non viene registrato niente.

| Tool | Cosa fa |
|---|---|
| `blueprint_run_start` | Apre un'esecuzione contro un output salvato di `preflight analyze --format json` e ne restituisce il `run_key`. L'analisi è conservata alla lettera, così l'esecuzione è confrontata con la stima che ti è stata mostrata, non con una ricalcolata dopo. |
| `blueprint_run_node` | Dichiara che il lavoro è passato a un nodo. Gli id di nodo sconosciuti sono rifiutati e il messaggio elenca quelli validi. |
| `blueprint_run_end` | Chiude l'esecuzione e restituisce il confronto. Richiamarlo su un'esecuzione chiusa lo ricalcola — l'attribuzione è una vista, non un timbro sulle righe raccolte. |

Per leggere lo stesso confronto da terminale, senza spendere i token dell'agente:

```bash
starkeno consuntivo --elenco                 # elenca le esecuzioni registrate
starkeno consuntivo --run <run_key>          # il confronto come testo
starkeno consuntivo --run <run_key> --json   # lo stesso, leggibile da una macchina
```

Il comando apre il database in sola lettura: non crea niente e non migra niente. Su una
macchina dove gli hook non hanno ancora raccolto, lo dice ed esce con codice diverso da
zero.

## Preflight sperimentale

Preflight espone al momento un nucleo locale e strutturato. `draft` valida e normalizza un
Blueprint JSON o YAML senza simularlo. `analyze` richiede il flag letterale `--confirmed`:
quella conferma esplicita crea una nuova revisione, e solo allora lancia lint e simulazione.

JSON dentro, JSON fuori:

```bash
python -m starkeno preflight draft --input tests/fixtures/preflight/simple.json --format json --output preflight-draft.json
```

YAML dentro, report HTML fuori:

```bash
python -m starkeno preflight draft --input tests/fixtures/preflight/medium.json --format yaml --output preflight-draft.yaml
python -m starkeno preflight analyze --input preflight-draft.yaml --confirmed --samples 50 --format html --output preflight-report.html
```

Il nucleo non interpreta ancora descrizioni in linguaggio naturale e non esegue il
workflow: analizza soltanto Blueprint già strutturati. Le superfici naturali `design` e
`review`, la skill/plugin per Codex e il sito pubblico sono incrementi successivi, non
capacità incluse in questa versione sperimentale.

I costi dei tool mancanti restano ignoti: un tool gratuito deve dichiarare esplicitamente
un costo fisso pari a zero. Costi in valute diverse non vengono convertiti né sommati.

## Com'è fatto, e perché

Le decisioni qui sotto sono tutte misurate, e la misura è scritta accanto a ciascuna.
Stanno qui invece che nelle istruzioni d'installazione perché non ti servono per usare
StarkEno — solo per modificarlo.

### Cosa fanno gli hook, e cosa non fanno

- Su Codex, `Stop` usa un avviatore che restituisce subito il controllo e lascia
  l'ingestione a girare in background. Funziona anche sui runtime Codex che documentano
  `async` ma poi lo saltano come non supportato. L'ingestione completa ha richiesto 1,2–1,7
  s sul transcript più grande trovato (68,6 MB), e il turno non la aspetta.
- Tutti escono `0` qualunque cosa accada e non scrivono mai su stderr. Un problema in
  StarkEno non deve rompere il tuo lavoro.
- **Nessun dato lascia la tua macchina.** Le chiamate sono salvate in SQLite locale.
- L'ingestione è idempotente. Se salta un turno, il successivo rilegge lo stesso transcript
  senza duplicare le chiamate già registrate.

`SessionStart` non scrive direttamente nell'interfaccia. Il suo `additionalContext` dice al
modello di mostrare una sola riga breve nel prossimo messaggio utile. Ti dà il benvenuto
quando il database manca o è vuoto, e tace una volta che hai storico. Non crea database e
non applica migrazioni.

### Perché la skill esiste due volte

`skills/starkeno/SKILL.md` e `plugin-claude-code/skills/starkeno/SKILL.md` sono lo stesso
file, e un test fallisce se smettono di essere identici.

La duplicazione è normalmente la risposta sbagliata, e questo progetto ha già pagato due
volte per due copie di una regola che divergono. Qui è forzata: i due harness montano
**radici di plugin diverse** a partire da questo unico repository — Claude Code monta
`plugin-claude-code/`, Codex monta la radice del repository — e una skill sotto l'una è
invisibile all'altro. Non può stare solo alla radice, perché Claude Code non vede
`../skills/`; e Claude Code non può montare la radice, perché lì `hooks/hooks.json` è
quello di Codex, con `PLUGIN_ROOT`, che non espande.

Misurato il 19/08/2026, due volte: prima chiedendo a Codex una domanda sui costi e
guardando la skill **non** partire — che è come il problema delle due radici è stato
trovato — e poi, esistente la seconda copia, richiedendo e guardandola partire.

### Installare gli hook a mano

Il plugin Codex spedisce `.codex-plugin/plugin.json` e `hooks/hooks.json`, i cui comandi
usano `PLUGIN_ROOT` e le varianti dedicate per Windows. Il plugin Claude Code spedisce
`plugin-claude-code/`, i cui hook invocano i moduli direttamente e non dipendono da nessun
percorso di plugin. Per una prova manuale, usa percorsi assoluti ai file Python, poi
controlla la configurazione con `/hooks` nella CLI di Codex.

> Gli script Codex vanno invocati per percorso. `python -m starkeno.hook_ingestione` da una
> cartella estranea non troverà il pacchetto se non è installato; i punti d'ingresso
> includono il bootstrap necessario a funzionare dalla cartella di progetto aperta in Codex.

> Gli hook di Claude Code usano `python -P -m`. Il `-P` non è decorazione: senza, la prima
> voce di `sys.path` è la **directory di lavoro della sessione**, che ha la precedenza sul
> pacchetto installato. Chiunque lavori dentro un checkout di StarkEno eseguirebbe il
> codice *di quel* checkout invece di quello installato. Misurato il 19/08/2026: una
> sessione la cui directory di lavoro era un checkout più vecchio ha raccolto correttamente
> ogni chiamata e le ha scritte nel percorso dati di quel checkout, così `report`, `doctor`
> e `consuntivo` non ne hanno vista nessuna — senza un errore e senza niente su stderr,
> perché a un hook non è permesso produrre né l'uno né l'altro.

## Cosa non è ancora fatto

Detto chiaramente, perché un README che nasconde i propri buchi costa più di uno che li
nomina.

- **La previsione è stata giudicata contro la realtà una volta sola.** Un'esecuzione, una
  macchina, un agente. Tutto il resto è fixture sintetiche. Finché non ce ne sono altre,
  tratta la metà predittiva come una domanda di ricerca aperta con un banco di prova
  funzionante, non come una funzione.
- **La metà predittiva non è spedita.** I suoi tool MCP esistono e sono documentati qui
  sopra, ma il plugin non li registra, di proposito — vedi la nota in quella sezione.
- **Preflight non legge la prosa.** Analizza Blueprint già strutturati. Descrivere un
  workflow a parole e ottenerne una stima è la superficie prevista, non quella attuale.
- **Nessun rilascio appuntabile.** Non c'è un pacchetto PyPI. `pip install git+…` funziona,
  ma installa quello che `main` è in quel momento: non c'è un tag a cui appuntarsi, né un
  modo di dire quale versione stai eseguendo oltre a quella nel manifest.
- **Il conto rendiconta, non prevede.** Non esiste un tetto di spesa né un avviso su di
  esso: la pagina ti dice quanto è costata un'esecuzione, mai che sta per costare troppo.
- ~~La skill non è provata su Codex.~~ **Verificata su entrambi** il 19/08/2026: fatta una
  domanda sui costi, Claude Code e Codex hanno invocato la skill ciascuno. C'è voluta prima
  una misura negativa — vedi *Perché la skill esiste due volte*.
- **Solo due agenti sono misurati.** Codex e Claude Code. Antigravity è riconosciuto ma non
  si può misurare, perché il suo transcript non porta conteggi di token, e riporta zero
  chiamate invece di una congettura.
- **Le soglie sono ragionate, non misurate** — vedi la nota in fondo a questo file.

## Cosa c'è dentro

| | |
|---|---|
| `starkeno/harness.py` | Quali agenti sono riconosciuti, e quali si possono misurare |
| `starkeno/transcript.py` | Dal `.jsonl` alle chiamate API; un modulo puro |
| `starkeno/hook_avvia_ingestione.py` | Avviatore non bloccante, per Codex |
| `starkeno/hook_ingestione.py` | Ingestione idempotente di fine turno |
| `starkeno/hook_inizio_sessione.py` | Hook sincrono d'inizio sessione; dichiara un fatto misurato dopo una pausa |
| `plugin-claude-code/skills/starkeno/` | La skill che dice all'agente a cosa risponde StarkEno, e quando — la copia che monta Claude Code |
| `skills/starkeno/` | Lo stesso file, byte per byte, dove lo monta Codex. Un test fallisce se le due divergono |
| `starkeno/conto.py` | Modello puro del conto |
| `starkeno/consuntivo.py` | Modello puro del preventivo contro consuntivo |
| `starkeno/report_conto.py` | Generatore della pagina HTML statica |
| `starkeno/percorsi.py` | Percorsi dati per piattaforma |
| `starkeno/db.py` | Modelli e query; l'unico modulo che parla con SQLAlchemy |
| `migrations/` | Catena Alembic, unica autorità sullo schema |

```bash
python -m pytest -q
```

## Licenza

MIT — vedi [LICENSE](LICENSE).

## Progetto open source

- [Come contribuire](CONTRIBUTING.md)
- [Politica di sicurezza](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Codice di condotta](CODE_OF_CONDUCT.md)

## Una nota sulle soglie

Le soglie storiche in `config.py` non sono valori da spedire: vengono dai dati di una
persona sola. La Fase 3 userà soglie derivate dallo storico di chi installa StarkEno.
