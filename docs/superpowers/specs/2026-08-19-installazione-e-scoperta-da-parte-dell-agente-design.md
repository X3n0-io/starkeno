# L'agente installa StarkEno e sa quando usarlo — design

**Data:** 19/08/2026. **Stato:** approvato l'impianto, specifica da rivedere.

## Il problema

Oggi il plugin StarkEno spedisce **due file**: un manifest e `hooks.json`. Non spedisce
skill, comandi, né una registrazione MCP. Quindi anche a installazione perfettamente
riuscita l'agente **non sa che StarkEno esista**: raccoglie in silenzio, e nessuno gli
dice mai a cosa serva quel database né quando guardarlo. I tre tool MCP esistono nel
codice e sono documentati nel README, ma niente li registra: sono irraggiungibili.

L'obiettivo: l'utente incolla l'URL del progetto nel suo agente o nel terminale, e da lì
in poi l'agente installa, verifica, e sa da solo quando StarkEno è la risposta.

## Le tre decisioni prese

1. **Perimetro: solo la metà osservativa.** L'agente mostra il conto su richiesta e
   segnala da solo qualcosa di misurato. Il ciclo Blueprint (`preflight` → nodi →
   `consuntivo`) resta fuori: è la metà mai verificata su dati reali.
2. **La proattività parla all'avvio, una volta, e solo con un fatto misurato.** Niente
   allarmi su soglia: `config.py` dichiara in testa che le sue soglie non sono tarate, e
   un avviso su una soglia non tarata insegna a ignorare gli avvisi.
3. **Installa l'agente, guidato dal repository.** Nessun installer da scaricare, nessuno
   script da mantenere su tre sistemi operativi.

## Cosa è stato misurato prima di progettare

Fatti verificati il 19/08/2026 su questa macchina, non dedotti:

- `claude plugin marketplace add` accetta letteralmente «a URL, path, or GitHub repo»
  (dal suo `--help`), e offre `--sparse` per i monorepo.
- **Codex consuma le `skills/` dei plugin nello stesso formato di Claude Code**: 140
  `SKILL.md` nella sua cache, sotto `plugins/cache/<mercato>/<plugin>/<versione>/skills/
  <nome>/SKILL.md`, e monta marketplace in formato Claude da URL GitHub
  (`config.toml`, `[marketplaces.claude-plugins-official]`).
  **Conseguenza di progetto: una sola cartella `skills/` serve entrambi gli harness.**
  L'asimmetria dichiarata in fase di proposta non esiste.
- Il formato è `skills/<nome>/SKILL.md` con frontmatter YAML `name` e `description`,
  scoperto per convenzione: il manifest del plugin **non** lo dichiara, esattamente come
  già accade per `hooks/hooks.json`.
- `hook_inizio_sessione.esegui()` emette il benvenuto **solo** quando il database è
  assente o vuoto (`chiamate in (None, 0)`), e da lì in poi tace per sempre — cioè si
  zittisce esattamente quando comincerebbe ad avere qualcosa da dire.

## Componente A — una skill, per entrambi gli harness

`plugin-claude-code/skills/starkeno/SKILL.md`, in inglese.

Il `description` del frontmatter **è** l'interfaccia: è ciò che l'agente legge per
decidere se invocarla, quindi elenca i momenti reali («how much did this cost», «where am
I wasting tokens», «why was this session so expensive», «show me the bill») invece di
descrivere il prodotto.

Il corpo dice:

- quali comandi eseguire — `starkeno report --no-open`, `starkeno doctor`,
  `starkeno consuntivo --elenco` — e cosa risponde ciascuno;
- che il conto è **locale e non esce dalla macchina**, e che non va inventato: se un
  numero non c'è, si dice che non c'è;
- che StarkEno **non** guarda l'utente digitare e **non** avvolge l'agente: rilegge i
  transcript che l'agente scrive da sé;
- **cosa fare se `starkeno` non è installato**: dirlo e rimandare alla sezione
  d'installazione. È questo che trasforma il fallimento silenzioso di oggi — plugin
  installato, pacchetto assente, hook muti — in qualcosa che l'agente nomina.

Il file vive nel bundle Claude Code, che è già quello che entrambi gli harness montano.

## Componente B — la riga proattiva all'avvio

Estensione di `hook_inizio_sessione.esegui()`. Quando c'è storia, invece di `None`
restituisce **una riga con un fatto misurato**, del tipo «negli ultimi 7 giorni il 58%
della spesa pesata è stata rilettura di contesto».

Quattro vincoli, ognuno con la sua ragione:

1. **È un fatto, non un giudizio.** Nessuna soglia di allarme, quindi non eredita il
   problema dichiarato di `config.py`.
2. **Il numero viene dalla stessa autorità del conto**, cioè da `conto.py` / dalle query
   già esistenti — **mai** da un secondo calcolo scritto qui. Questo progetto ha già
   pagato due volte per due implementazioni della stessa regola che divergono
   (`effective_tokens`, il parsing di `model_map`).
3. **Al massimo una volta al giorno, senza scrivere niente.** «Prima sessione del
   giorno» si deduce in sola lettura: l'ultima riga raccolta è più vecchia di N ore.
   L'hook resta read-only come è oggi — non crea il database, non migra, non scrive
   stato.
4. **Tace se non ha abbastanza dati** per dire qualcosa di vero, e tace se il calcolo
   fallisce. Vale l'invariante 12: esce `0`, niente su stderr.

Il benvenuto attuale per il database vuoto resta invariato.

## Componente C — il README eseguibile da un agente

Una sezione in cima al README, in inglese, scritta **perché la esegua un agente** che ha
appena scaricato il repository da un URL:

1. una frase che dice cosa fare («install StarkEno for this machine»);
2. i due comandi esatti, in ordine: il pacchetto (`pip install git+<URL>`) e il plugin
   (`claude plugin marketplace add <repo>` / l'equivalente Codex);
3. `starkeno doctor` come **cancello**, con una tabella di cosa significa ogni esito
   rosso e cosa fare;
4. la ragione per cui i passi sono due e non uno, così l'agente non conclude di aver
   finito a metà.

## Fuori perimetro, esplicitamente

- Allarmi a metà sessione: richiederebbero di far parlare l'hook, contro l'invariante 12.
- Il ciclo Blueprint e la registrazione del server MCP.
- Soglie tarate: appartengono alla fase che userà la storia di chi installa.
- Un installer scaricabile.

## Regressioni concrete che i test devono uccidere

1. Una skill il cui `description` non nomina i momenti d'uso: sarebbe una skill che
   nessun agente invoca. Il test controlla che i trigger ci siano.
2. Il `SessionStart` che torna a tacere quando c'è storia.
3. La riga proattiva emessa **due volte nello stesso giorno**.
4. Un secondo calcolo della quota di rilettura che diverge da `conto.py`: test
   differenziale fra i due, come già esiste per `effective_tokens`.
5. L'hook che scrive qualcosa, o che solleva, o che rallenta l'avvio oltre il budget.
6. La skill che non c'è nel bundle spedito: `test_packaging` deve vederla dentro il
   wheel, o esisterebbe solo in sviluppo — la stessa forma di difetto già pagata due
   volte oggi.

## Rischi

- **Non verificato:** che Codex *invochi* una skill spedita da un marketplace montato da
  URL, non solo che ne legga il file. Da provare su un'installazione vera prima di
  dichiarare Codex supportato, con la stessa regola già usata per gli harness: se non è
  misurato, non si promette.
- Una riga all'avvio, anche vera, diventa carta da parati se ripetuta. Il limite
  giornaliero è la difesa; se non basta, la successiva è dirla solo quando cambia.
