# Verifica live Codex — 12 agosto 2026

Stato: **in attesa di attivazione manuale nell'app Codex**.

Questa verifica non viene simulata e non modifica file di configurazione a mano. Va
completata dopo il riavvio dell'app, l'installazione tramite `StarkEno Local` e
l'approvazione esplicita degli hook con `/hooks`.

| Evidenza | Risultato |
|---|---|
| Versione plugin | 0.3.0, da confermare nella cache installata |
| Revisione schema | `0005`, verificata dopo recupero conservativo |
| Chiamate prima dei tre turni | 1 |
| Chiamate dopo i tre turni | da misurare |
| Duplicati `(session_id, message_id)` | 0 prima della prova live |
| Exit code `starkeno doctor` | 1: plugin, fiducia hook e freschezza ancora mancanti |
| `PRAGMA quick_check` | `ok` |

Il recupero ha copiato un unico candidato integro a revisione `0003`, lo ha migrato a
`0005` e ha preservato la riga esistente. La sorgente è rimasta byte per byte invariata;
la diagnosi non crea sidecar SQLite accanto allo storico legacy.

Per completare la prova live:

1. riavvia l'app Codex;
2. installa `starkeno` da `/plugins` → **StarkEno Local**;
3. apri una nuova sessione e approva `SessionStart` e `Stop` da `/hooks`;
4. completa tre turni normali;
5. esegui `starkeno doctor` e misura conteggio finale e duplicati.

Il rapporto finale non conterrà transcript, prompt, username o percorsi assoluti.
