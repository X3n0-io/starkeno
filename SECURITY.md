# Politica di sicurezza

## Versioni supportate

La linea supportata è `0.3.x`. Le versioni precedenti sono prototipi e non ricevono
correzioni di sicurezza.

## Segnalare una vulnerabilità

Quando il repository pubblico sarà disponibile, usa esclusivamente
**Security → Report a vulnerability** su GitHub. Non aprire issue pubbliche per
vulnerabilità non corrette.
Prima che quel canale privato esista non viene distribuita alcuna release pubblica.

Indica versione, sistema operativo, impatto e una riproduzione minima sintetica. Non
allegare mai transcript, prompt, database SQLite, token, credenziali, nomi utente,
percorsi home o altri dati personali. L'output di `starkeno doctor --json` va revisionato
e redatto prima dell'invio.

La presa in carico e la correzione avvengono best-effort: non è garantito uno SLA. Il
segnalante riceverà comunque, tramite il canale privato, conferma dell'impatto stimato e
dell'eventuale versione corretta prima della divulgazione coordinata.
