# Stato della parte B al 16/08/2026 — leggere prima di riprendere

Questo documento sostituisce il piano `docs/superpowers/plans/2026-08-15-parte-b-porta-linguaggio-naturale.md`
su un punto decisivo. **Il piano non è più eseguibile come scritto.** Quello che segue è ciò che
è stato deciso, misurato e costruito.

## Il cambio di architettura, deciso il 15/08/2026

Il piano presupponeva che **StarkEno** chiamasse l'API Anthropic con una **propria** chiave.
L'utente non ha una chiave e non intende comprarne una: vuole che il progetto funzioni **dentro
Claude Code o Codex**, usando l'abbonamento che ha già.

**L'agente genera, StarkEno valida.** StarkEno non chiama alcun modello, non apre connessioni e
non ha bisogno di credenziali. Fornisce il compito (regole più schema), riceve il JSON che
l'agente produce, lo valida e salva il Draft. Il retry di riparazione lo fa l'agente leggendo
l'errore restituito.

Conseguenze:

- I **Task 4, 5 e 6** del piano (client Anthropic, comando che chiama il modello, `doctor` che
  dichiara la superficie di rete) **non si fanno**.
- Il **Task 7** cambia in meglio: il README non deve più correggere la promessa «nessun dato
  lascia la macchina», perché con questa architettura resta vera.
- La dipendenza `anthropic` in `pyproject.toml` è probabilmente inutile e andrà rimossa con un
  commit di revert dedicato. **Non è stata rimossa**: è una decisione separata.

## Cosa è stato costruito, e dove

| Commit | Contenuto | Revisione |
|---|---|---|
| `40c54e4` | Dipendenza `anthropic` più i tre test di confine sull'AST | conformità ✅, qualità approvata |
| `eef8347` | `starkeno/preflight_interpret.py`: contratto, schema, prompt, orchestrazione. Puro | conformità ✅, un Critico trovato |
| `0fe41cf` | Correzione: `_rifiuta_measured` non copriva `fixed_tool_cost` | difetto chiuso, verificato |
| `7442c50` | Due tool MCP in `starkeno/mcp_server.py`; `write_blueprint_atomic` spostata in `preflight_service.py` | conformità ✅, **qualità NON approvata** |

Suite a **591 passed, 2 skipped** sotto `-W error`; `git diff --check` pulito.

## Il difetto del `measured`, chiuso in `3f7d663` — leggere prima di toccare quella funzione

Un modello non misura niente. `measured` rende un numero inventato indistinguibile da uno
osservato, ed è il fallimento che questo progetto rifiuta per principio. `_rifiuta_measured` in
`starkeno/preflight_interpret.py` è l'**unico** controllo del genere in tutto `starkeno/` —
`preflight_lint` non lo ripete in `analyze` — quindi non esiste una seconda rete.

Lo stesso difetto è affiorato **tre volte**, ogni volta perché la funzione enumerava i punti a
mano: prima `nodes[].budget.fixed_tool_cost`, poi `transitions[].probability.provenance` e
`contexts[].source`. In tutti i casi un `"measured"` inventato veniva **scritto su disco**.

Ora la funzione delega a `_ogni_provenance`, che percorre ricorsivamente il Blueprint e cerca i
campi la cui **annotazione** è `Provenance`, invece di elencare percorsi. Verificato in modo
indipendente: le 4 dichiarazioni di `Provenance` nello schema sono raggiungibili da `Blueprint`
per **9 percorsi**, trovati da due scanner scritti apposta, e sono tutti coperti. Nessun falso
positivo su testo libero che contenga la parola. Il test del caso generale usa modelli sintetici
mai referenziati da `Blueprint`: ripristinando un'enumerazione a mano dei punti noti, diventa
rosso — è la guardia contro il quarto giro.

**Il limite noto, dichiarato anche nel docstring:** la copertura vale per campi annotati
esattamente `Provenance` dentro un `FrozenModel`, anche annidato in liste o tuple. Un ipotetico
`Provenance | None` o `tuple[Provenance, ...]` dichiarato direttamente su un modello non sarebbe
coperto. Oggi nessun punto dello schema usa quelle forme; se un giorno servissero, `_ogni_provenance`
va estesa insieme.

## Altri esiti di revisione, aperti

- **Chiuso in `2ff4696` — superficie di scrittura di `preflight_save_draft`.** L'`output_path`
  arriva dall'agente, non da una persona che digita `--output`: prima sovrascriveva silenziosamente
  file esistenti e accettava `..` e percorsi assoluti fuori dal progetto. Ora le scritture sono
  **confinate alla directory di lavoro del server** (confronto su percorsi risolti, quindi i `..`
  sono normalizzati prima del controllo) e **un file esistente non viene sostituito** senza
  `overwrite=True` esplicito. Gli errori tornano come testo, mai come eccezione, e la docstring del
  tool dichiara entrambe le regole — per un tool MCP la docstring **è** l'interfaccia. Verificato
  in modo indipendente dal coordinatore, non solo dai test: percorso legittimo scritto, `..` e
  assoluto fuori radice rifiutati con il file esca rimasto intatto, sovrascrittura rifiutata senza
  `overwrite`.
  Limite noto e accettato: il controllo di esistenza e la scrittura atomica non sono un'unica
  operazione, quindi resta una finestra TOCTOU teorica. Irrilevante per un server locale a singolo
  utente; da rivedere se più processi potessero scrivere lo stesso `output_path`.
- **La CLI non è stata confinata, ed è voluto.** `preflight_cli.py` e `write_blueprint_atomic`
  restano permissivi: lì il percorso lo digita una persona con `--output`, che è consenso
  esplicito. Il confinamento è una proprietà **della porta MCP**, non della scrittura in sé.
- **Minore** — `test_preflight_save_draft_impl_supporta_yaml` resta verde anche se si smette di
  passare `format`, perché JSON è YAML valido: non protegge quanto sembra.
- **Minore** — il test «non tocca il database» dichiara di coprire entrambi i tool ma ne esercita uno.
- **Minore, dal Task 1** — `test_anthropic_e_dichiarato_come_dipendenza` asserisce su testo grezzo
  di `pyproject.toml`: passerebbe a vuoto se `anthropic` comparisse in un commento. Alternativa
  offline: parsare l'array `dependencies` con `tomllib`.
- **Minore, dal Task 3** — `load_blueprint` importato e mai usato nel file di test; `except
  (ValueError, BlueprintInputError)` ridondante.

## Misure fatte, da non ricomprare né ri-derivare

Eseguite il 15/08/2026 sull'SDK `anthropic` 0.122.0 installato, **senza spendere nulla**:

- `anthropic.Anthropic()` **non fallisce** senza credenziali: costruisce, e lascia `api_key`,
  `auth_token` e `credentials` a `None`. L'errore arriva alla **prima chiamata** ed è un
  **`builtins.TypeError`**, senza parentela con `anthropic.APIError`: nessun `except` sull'SDK lo
  cattura. Il piano dava per scontato il contrario, e il suo Task 4 avrebbe risposto «errore
  interno» a chi non ha la chiave.
- Lo schema di `Interpretation` ha **53 vincoli esatti** (`minLength` ×26, `minimum` ×17,
  `pattern` ×7, `maximum` ×3). `transform_schema` li porta a **0** spostandoli nelle description,
  e `messages.parse` lo chiama da solo: il percorso privato che il piano teneva come riserva non
  serve.
- `parse_text` su fallimento semantico **solleva `pydantic_core.ValidationError`** con un
  messaggio utile a un retry, non restituisce `None`.
- L'SDK aggiunge **5 pacchetti, non 3** — `anthropic`, `jiter`, `docstring-parser`, `distro`,
  `sniffio` — per **1,23 MB**: il peso della misura originale era esatto, il conteggio no.
  `requirements/ci.txt` passa da 79 a 84 pacchetti.
- Lo schema dichiarato dal piano a 9.137 caratteri ne misura 10.573 con pydantic 2.13.4.

## Vincoli che restano in vigore

- **Non iniziare la parte C.** Dipende dalla B, spende soldi veri ed esegue tool veri: flag
  letterale separato, tetto di spesa obbligatorio senza default, mai avviata da hook, report,
  doctor o dashboard. Merita il suo piano.
- **Nessun push e nessuna modifica remota senza consenso esplicito dell'utente.**
- La **dashboard in stile Jarvis** è la prossima direzione di prodotto, da affrontare con un
  brainstorming e un piano suoi, non come coda di questo lavoro.
- Prima di dichiarare completo un lavoro: test pertinenti, `python -m pytest -q -W error` e
  `git diff --check`.
