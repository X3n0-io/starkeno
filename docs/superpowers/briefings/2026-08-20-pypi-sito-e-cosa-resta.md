# Stato al 20/08/2026 — PyPI e sito fatti, restano i post

Sessione successiva a `2026-08-19-presentazione-verticale-previsione.md`. Quella aveva
lasciato tre cose in sospeso; due sono chiuse.

## Dove sta il codice

`origin/main` a `7af6c99`, tag `v0.4.0` e `v0.4.1`. Suite a **714 passed, 2 skipped**
sotto `-W error`. CI, SQLite stress e Pages verdi. Niente di locale non pubblicato.

## Cosa è stato consegnato

**Il pacchetto è su PyPI**: <https://pypi.org/project/starkeno/>, `pip install starkeno`,
wheel e sdist. Pubblicato dal workflow via **Trusted Publishing**: nessun token è mai
esistito. Si rilascia spingendo un tag `v*`, e i cancelli girano dentro il workflow prima
del caricamento.

Verificato da fuori e non a parola: `pip install starkeno` in un virtualenv vuoto, 26
secondi, e i tre comandi del README tornano tutti `0` producendo il report.

**Il sito è online**: <https://x3n0-io.github.io/starkeno/>, deployato da `sito/` con un
workflow. Apre con la domanda, mette i due scarti uno accanto all'altro e dichiara cosa
non è fatto. **Nessuna richiesta a terze parti** — font di sistema, zero CDN, zero
analytics — e un cancello nel workflow fa fallire il deploy se la pagina contatta un host
estraneo. La homepage del repository ci punta.

**La GIF dei tre comandi** (`docs/immagini/simulatore.gif`), con comandi e risposte veri,
nei due README e nel sito.

## Il difetto che la pubblicazione ha creato, e la lezione

Appena la 0.4.0 è stata pubblicata, la sua pagina PyPI rendeva il README che diceva
`pip install git+https://…` e **«Nessun rilascio appuntabile. Non c'è un pacchetto
PyPI»** — sulla pagina del pacchetto PyPI. Chi arrivava lì installava `main` invece di
una versione, senza accorgersene.

La 0.4.1 esiste solo per correggerlo. **Pubblicare rende false delle frasi**, e nessuna
suite lo cattura: il README non è codice. La prossima volta che si spedisce qualcosa,
prima si cerca cosa quella spedizione smentisce.

## Cosa resta, in ordine

1. **I post.** È l'unica cosa rimasta, e passa dalle mani dell'utente: sono a suo nome,
   sui suoi account. Bozze pronte in `docs/presentazione/candidature.md`, con PyPI già
   barrato. **Liste prima, Hacker News dopo, una volta sola.** Su awesome-claude-code si
   segnala per **issue, non per PR**.
2. **La terza misura**, fatta come si deve: Blueprint scritto *prima*, marcatori sui nodi,
   un `consuntivo` vero. Le prime due dicono che lo scarto non è costante (9,15x contro
   3,1x); la terza inizia a dire da cosa dipende.
3. **Togliere la ricorsione dal simulatore.** Oggi regge fino a ~150 passaggi di ciclo e
   poi sfonda lo stack; il limite è dichiarato con exit 2, ma resta. È una riscrittura
   algoritmica su codice che produce il numero portante del progetto: **merita un piano
   suo**, con i test che fissano le stime attuali come riferimento prima di toccare nulla.
4. **Le stelle sono 0.** Arrivano dopo i post, da persone. Nessun agente può produrle, e
   nessuno deve provarci.

## Cosa non rifare

- `license = { file = "LICENSE" }` in `pyproject.toml` fa comparire tutto il testo MIT nel
  campo licenza della pagina PyPI. Cosmetico, si sistema con `license = "MIT"` alla
  prossima versione.
- Il ramo `fix/connessioni-sqlite-non-chiuse` è **interamente dentro `main`** (zero commit
  propri): si può cancellare.
- L'anteprima social (`docs/immagini/anteprima-social.png`) va caricata **a mano** da
  Settings → General: l'API di GitHub ignora quel campo, provato.
- Secret scanning e push protection sono **disattivati**: su un repository pubblico sono
  gratuiti, e sono due interruttori in Settings → Security.

## Vincoli che restano in vigore

- **Nessun push e nessuna modifica remota senza consenso esplicito.**
- **Nessun agente inserisce credenziali**, e i post li manda l'utente.
- **Non iniziare la parte C** (esecuzione vera dei workflow): spende soldi veri.
- **Niente dashboard** prima dei feedback.
- L'attribuzione è una **vista** calcolata al confronto; quando è incerta **si dichiara**.
- Prima di dichiarare completo: test pertinenti, `python -m pytest -q -W error`,
  `git diff --check`. Prima di pubblicare, anche i due scanner.
