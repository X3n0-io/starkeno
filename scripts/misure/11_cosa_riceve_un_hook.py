"""Che cosa riceve un hook di Claude Code, davvero.

Non lo dice nessun documento del progetto, e assumerlo e' l'errore che questo progetto
ha gia' pagato tre volte. Questa sonda non fa niente: scrive quello che ha ricevuto e
esce 0, come dovra' fare l'hook vero.

## MISURATO l'08/08/2026, su tre scatti veri. Non dedotto: eseguito.

`Stop` — la fine di un turno. Undici chiavi:

    background_tasks, cwd, effort, hook_event_name, last_assistant_message,
    permission_mode, prompt_id, session_crons, session_id, stop_hook_active,
    transcript_path

`SessionStart` — cinque chiavi: `cwd`, `hook_event_name`, `session_id`,
`transcript_path`, `source` (che valeva `startup`).

Cio' che l'ingestione usa, e come si presenta davvero:

- `hook_event_name` = `"Stop"`;
- `transcript_path` = percorso ASSOLUTO del `.jsonl` della sessione in corso, con le
  barre rovesciate di Windows. Verificato che il file esista e sia leggibile;
- `cwd` e `session_id` ci sono: l'hook non deve dedurli.

**Due cose che il riferimento ufficiale diceva e la misura ha smentito**, ed e' il motivo
per cui questo task esiste:

1. `Stop` **NON** porta `reason`, che l'esempio ufficiale mostrava. Un hook che ci
   contasse leggerebbe sempre `None`.
2. Gli hook **non** hanno richiesto un riavvio per entrare in funzione: il primo scatto
   e' arrivato alla fine dello stesso turno in cui il file di configurazione e' stato
   scritto.

`timeout` nella dichiarazione dell'hook e' in **secondi** (gli esempi ufficiali usano
10, 30, 60; un plugin installato scrive 5000, ed e' un difetto di quel plugin).

**Conseguenza per l'attribuzione, misurata:** `cwd` e' la cartella da cui Claude Code e'
stato APERTO, non quella del file su cui si lavora. Chi apre la cartella padre vede tutto
il lavoro attribuito a un progetto solo. Il lettore non usa comunque questo `cwd` — legge
quello di ogni riga del transcript — ma la riga del transcript riporta lo stesso valore.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

USCITA = Path.home() / ".starkeno_sonda_hook.jsonl"


def main() -> int:
    try:
        grezzo = sys.stdin.read()
    except Exception:
        grezzo = "<stdin illeggibile>"
    try:
        voce = {
            "quando": datetime.now(timezone.utc).isoformat(),
            "argv": sys.argv[1:],
            "stdin": grezzo[:4000],
            "variabili_claude": {k: v for k, v in os.environ.items()
                                 if "CLAUDE" in k.upper()},
        }
        with open(USCITA, "a", encoding="utf-8") as f:
            f.write(json.dumps(voce, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # SEMPRE zero: l'hook non deve mai rompere la sessione di chi lo usa.
    return 0


if __name__ == "__main__":
    sys.exit(main())
