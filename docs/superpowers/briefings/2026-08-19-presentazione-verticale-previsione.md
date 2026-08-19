# Stato al 19/08/2026 (sera) — presentazione, verticale sulla previsione

Sessione successiva a `2026-08-19-stato-e-passaggio-alla-presentazione.md`. Quella
chiudeva chiedendo di aprire il repository; questa l'ha aperto e ha costruito il modo in
cui il progetto si fa trovare.

## Dove sta il codice

`origin/main` a `a2445f7`. Suite a **707 passed, 2 skipped** sotto `-W error`. CI e
SQLite stress verdi. Niente di locale non pubblicato.

**Il repository è pubblico**, con description, quindici topic più `italiano`, e le
istruzioni d'installazione ora funzionano per chiunque.

## La decisione portante di oggi

**Il progetto si presenta sulla previsione, non sull'osservabilità.**

Il README apriva col 61% di rilettura. È vero e misurato, ma non è nostro: è documentato
pubblicamente — 82-83% di cache read su un workflow in produzione, 72 miliardi di cache
read contro 690 milioni di output nella migrazione a Rust di Bun. E `ccusage` ha 16.500
stelle facendo la stessa lettura locale dei JSONL, meglio. Un lettore informato leggeva la
prima riga e pensava «lo so già».

La previsione invece non la sta tentando nessuno. È anche la metà meno provata — una
misura, 9x di scarto — e quello è diventato l'argomento invece dell'ostacolo: **uno
strumento di previsione che nasconde il proprio errore non vale niente.**

Il 60% resta, come spiegazione del meccanismo. Non è più il titolo.

## La mossa che vale più di tutte

**La domanda aperta è l'invito.** Con n=1 non si distingue una costante moltiplicativa da
un errore che dipende dalla forma: un punto non determina una pendenza. Quindi il progetto
non chiede installazioni, chiede **misure** — otto numeri, non il database.

È una richiesta che nessuno strumento di costi può fare, perché per farla bisogna prima
ammettere di sbagliare. `docs/lo-scarto-9x.md` (+ inglese), il template di issue «Una
misura», e il funnel in entrambi i README.

La tabella delle misure ha **una riga**. È il punto della pagina, non un difetto da
mascherare.

## Consegnato

- **Repository pubblico**, description, topic. Apertura verificata con chiamata anonima —
  prima 404, adesso 200.
- **Lo scanner dei segreti vede le chiavi AWS.** Buco trovato eseguendo, non leggendo:
  piantata una chiave finta durante l'apertura, era passata.
- **La soglia del launcher è relativa, non un secondo fisso.** Misurato 10-11x di margine
  fra launcher e ingestione; verificata per mutazione.
- **Il conto si vede**: immagine da dati di nessuno, con lo script che la rigenera.
- **Il progetto parla italiano**, con `README.en.md` come porta e quattro guardie contro
  la deriva fra le due lingue.
- **Il pacchetto si fa trovare**: keywords, classifiers, project.urls. `twine check`
  passa.

## Cosa resta, in ordine di leva

1. **PyPI.** È l'unica barriera vera rimasta: `pip install git+https://…` segnala «non
   pronto» a chi valuta. Il nome `starkeno` era **libero** il 19/08 — verificare di nuovo,
   i nomi si prendono. Procedura in `docs/releasing.md`, TestPyPI compreso. **Le
   credenziali sono dell'utente e nessun agente deve toccarle.**
2. **Le liste**, poi **Hacker News**, in quest'ordine. Bozze pronte in
   `docs/presentazione/candidature.md`. Su awesome-claude-code si segnala per **issue, non
   per PR**. Su HN si posta **una volta sola**, e si manda il pezzo sullo scarto, non il
   repository.
3. **Più misure reali.** È la ricerca vera e adesso ha un canale.
4. **Homepage vuota**, per decisione dell'utente: nessun sito finché non ce n'è uno vero.
   La landing sul Desktop dell'utente è del 18/08, vende «simulazioni predittive ad alta
   fedeltà» e una società inesistente: **non pubblicarla come sta.**

## Vincoli che restano in vigore

- **Nessun push e nessuna modifica remota senza consenso esplicito.** Quelli del 19/08
  erano autorizzati per quell'occasione.
- **Nessun agente inserisce credenziali** — PyPI, GitHub o altro.
- **I post su piattaforme di terzi li manda l'utente**, a suo nome. Le bozze sono pronte;
  mandarle non è compito di un agente.
- **Non iniziare la parte C** (esecuzione vera dei workflow): spende soldi veri.
- **Niente dashboard** prima dei feedback.
- Le due decisioni portanti: l'attribuzione è una **vista** calcolata al confronto, e
  quando è incerta **si dichiara**.
- Prima di dichiarare completo: test pertinenti, `python -m pytest -q -W error`,
  `git diff --check`. Prima di pubblicare, anche i due scanner.

## Cosa ha insegnato questa sessione

Due difetti trovati **eseguendo**, ancora: la chiave AWS piantata che passava, e lo script
delle fixture che ignora `--help` ed esegue.

Ma quello che conta di più l'ha trovato **una ricerca di dieci minuti**: il numero su cui
si reggeva tutta la presentazione era già pubblico, e nessuno se n'era accorto perché
nessuno aveva guardato fuori. La lezione delle sessioni precedenti era «esegui invece di
leggere il codice». Questa aggiunge: **guarda fuori prima di credere che una misura sia
tua.** Misurare bene una cosa che il mondo già sa non è un vantaggio: è un vantaggio solo
finché non apri il browser.
