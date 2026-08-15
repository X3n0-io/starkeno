# Verifica live Claude Code — 15 agosto 2026

Stato: **completata**. Il plugin è installato, gli hook sono approvati e la raccolta è
stata osservata su turni veri.

| Evidenza | Risultato |
|---|---|
| Versione plugin | 0.3.2, allineata al manifest Codex e a `starkeno.__version__` |
| Variabile espansa dagli hook | `${CLAUDE_PLUGIN_ROOT}`, mai `${PLUGIN_ROOT}` |
| Manifest validati | `claude plugin validate` su marketplace e bundle |
| Chiamate prima della prova | 699 |
| Chiamate dopo un turno | 700 |
| Righe attribuite al progetto di prova | 1, con `(session_id, message_id)` nuova |
| Exit code `starkeno doctor` | 0 |

## Cosa la verifica ha impedito di spedire

La prova ha trovato **tre difetti**, tutti dello stesso tipo: raccolta perduta senza
emettere un segnale. Nessuno sarebbe emerso da un test della suite, e nessuno avrebbe
prodotto un errore visibile all'utente. Due su tre avrebbero colpito ogni installazione.

### 1. L'hook non bloccante non sopravvive

L'avviatore usato da Codex stacca un processo figlio e rientra subito. Misurato su un
turno vero: rientra in **354 ms** mentre l'ingestione ne richiede **circa 1600**. La
variante `async: true` rientra ugualmente subito. In entrambi i casi il processo non
sopravvive e non arriva nessuna riga.

Claude Code non raccoglie l'esito di un hook `async`: la lista degli errori resta vuota
perché non è stata osservata, non perché sia andata bene.

Correzione: su Claude Code gli hook sono **sincroni** e chiamano l'ingestione
direttamente. Costa circa 1,6 s a fine turno, quando l'utente sta già leggendo la
risposta. Su Codex l'avviatore resta: lì serve, perché Codex blocca sull'hook.

### 2. `Stop` scatta prima che il turno sia sul disco

Misurato: una chiamata con timestamp `14:21:17,8` e l'hook partito alle `14:21:18,7` su
un transcript che non la conteneva ancora. Poiché l'ingestione rilegge tutto ed è
idempotente, il turno N viene recuperato allo `Stop` del turno N+1 — ma l'**ultimo turno
di ogni sessione** non ha un giro successivo e si perderebbe per sempre.

Correzione: un hook `SessionEnd`, che scatta a transcript chiuso.

### 3. `%LOCALAPPDATA%` è virtualizzato per gli host impacchettati

Il difetto più grave, e il meno visibile. Lo stesso identico script, stesso interprete,
stesso percorso:

| Eseguito da | Righe contate |
|---|---|
| Hook di Claude Code | 12 |
| Shell normale | 699 |

Un processo lanciato da un host impacchettato MSIX scrive sotto `AppData\Local`
nell'overlay privato del pacchetto. L'hook leggeva, ingeriva e scriveva **senza un
errore**, in un database che `report` e `doctor` non guardavano. `doctor` avrebbe
dichiarato «raccolta recente» osservando il file sbagliato.

Correzione: su Windows il database vive in `%USERPROFILE%\.starkeno\`. La home non è
virtualizzata — verificato scrivendo un file da dentro l'hook e rileggendolo da una
shell esterna. L'inventario di `doctor` guarda anche la vecchia cartella, così chi
aggiorna vede lo storico e se lo riprende con il recupero esplicito.

## Note di metodo

L'installazione locale di un plugin Claude Code ha due comportamenti che vale la pena
sapere prima di rifare una prova simile:

- `claude plugin update` **non copia niente** se la versione del manifest non è cambiata.
  Durante lo sviluppo serve disinstallare e reinstallare.
- Per un marketplace di tipo `directory`, `${CLAUDE_PLUGIN_ROOT}` risolve al **sorgente**,
  non alla copia in cache. Modificare la copia non ha effetto. Su un'installazione da git
  la copia sarebbe invece l'unica cosa presente, ed è il motivo per cui gli hook si
  invocano per modulo e non per percorso.

I primi tentativi di diagnosi sono stati condotti per ipotesi successive e non hanno
prodotto nulla. La causa è emersa appena l'hook è stato **strumentato**, facendogli
scrivere cosa riceveva e cosa faceva invece di assorbire in silenzio. È lo stesso
principio che il progetto applica altrove: dichiarare, non nascondere.

Questo rapporto non contiene transcript, prompt, username o percorsi assoluti.
