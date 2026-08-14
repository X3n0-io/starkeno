# Le misure — si rieseguono, non si citano a memoria

Questi script hanno prodotto ogni numero di
`docs/superpowers/specs/2026-08-07-il-conto-al-centro-design.md`.

Stanno qui perché il metodo del progetto è **verificare eseguendo codice**, e un numero
che nessuno può rifare è un'opinione con una cifra decimale. Chi riprende il progetto fra
sei mesi li rilancia sui propri transcript invece di fidarsi.

Leggono i transcript di Claude Code da `~/.claude/projects/**/*.jsonl`. **Non scrivono
niente in nessun database di produzione**: il solo che scrive è `05`, e usa un file
usa-e-getta nella cartella temporanea.

| Script | Risponde a |
|---|---|
| `01_storia_delle_sessioni.py` | Quanto sono lunghe le sessioni vere? R1 ha abbastanza materiale? |
| `02_r1_sui_dati_veri.py` | Che cosa dice R1 sui dati veri, e cosa cambia abbassando `LOOP_MIN_HISTORY`? Stampa le azioni dietro ogni violazione |
| `03_segnale_di_fallimento.py` | I fallimenti separano chi lavora da chi è bloccato? |
| `04_calibrazione_fallimenti.py` | Qual è il peggior caso sano? È il numero che tara `LOOP_MIN_FAILURES` |
| `05_pagella_percorso_completo.py` | Percorso completo: transcript veri → database → `run_once`. Chi parla, quando, dicendo cosa |
| `06_dove_vanno_i_soldi.py` | Dove vanno i token: skill, plugin, server MCP, sub-agenti, modelli, ritmo giornaliero |

Si lanciano uno alla volta, dalla radice del repository:

```bash
python scripts/misure/02_r1_sui_dati_veri.py
```

`05` ha bisogno di Alembic sul percorso e crea lo schema da solo.

**Attenzione:** dentro c'è un percorso assoluto alla radice del repository, scritto a mano.
Su un'altra macchina va corretto — è codice di misura, non di produzione, e ha la cura che
merita.

## La seconda campagna (07/08/2026, dopo la critica)

La prima campagna produceva cinque totali diversi da script con filtri leggermente
diversi. `00_passata_canonica.py` esiste per questo: **una passata, un insieme di numeri,
ognuno col suo nome.** Ogni cifra del design esce da lì.

| Script | Risponde a |
|---|---|
| `00_passata_canonica.py` | **Il campione, e le sei obiezioni che rimettevano in causa le decisioni.** Si esegue per primo |
| `07_caccia_agli_sprechi.py` | Non «le mie regole trovano qualcosa?» ma «**che cosa c'è da trovare?**». I cinque sprechi veri |
| `08_installato_contro_usato.py` | Quanto di ciò che hai installato usi davvero — strumenti, skill, server MCP |
| `09_quanto_serve_per_tararsi.py` | **Quanti giorni servono perché un utente qualunque si calcoli le soglie da solo.** È ciò che impedisce di spedire a tutti le soglie di uno |

**Il corpus cresce mentre lo si misura:** le sessioni in corso scrivono sul proprio file.
Fra due esecuzioni a un'ora di distanza i totali si muovono di qualche unità — per questo
ogni cifra va citata con la data della passata.
