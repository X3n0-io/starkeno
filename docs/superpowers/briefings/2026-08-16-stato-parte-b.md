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

## DA FARE PER PRIMO — difetto Critico aperto su `7442c50`

`_rifiuta_measured` in `starkeno/preflight_interpret.py` itera **solo** su `nodo.budget`. Un
`provenance: "measured"` inventato dal modello passa e **viene scritto su disco** da almeno altri
due percorsi, verificati eseguendoli:

- `transitions[].probability.provenance`
- `contexts[].source`

È il terzo affioramento dello stesso bug: `fixed_tool_cost` era il primo, corretto in `0fe41cf`.
Enumerare i punti a mano continua a riaprirlo. **La correzione giusta è strutturale**: percorrere
ricorsivamente il modello e rifiutare `measured` ovunque compaia un campo `Provenance`, invece di
elencare collezioni. Serve un test per ciascuno dei vettori noti più uno che copra il caso
generale.

Perché conta più di quanto sembri: un modello non misura niente. `measured` rende un numero
inventato indistinguibile da uno osservato, ed è il fallimento che questo progetto rifiuta per
principio. Non esiste una seconda rete di sicurezza — è l'unico controllo in tutto `starkeno/`, e
`preflight_lint` non lo ripete in `analyze`.

## Altri esiti di revisione, aperti

- **Importante — superficie di scrittura di `preflight_save_draft`.** L'`output_path` arriva
  dall'agente, non da una persona che digita `--output`. Oggi: sovrascrive silenziosamente un file
  esistente, crea directory a piacere, accetta `..` e percorsi assoluti fuori dal progetto. Sulla
  CLI la stessa permissività è dietro un consenso esplicito dell'utente; qui no. Da decidere se
  confinare a una radice, se rifiutare una destinazione esistente, e intanto dirlo nella docstring,
  che per un tool MCP **è** l'interfaccia.
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
