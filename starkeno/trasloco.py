"""Compatibilita' per il recupero esplicito del vecchio database locale.

Il recupero non appartiene al percorso automatico dell'hook: chi lo invoca ha gia'
deciso esplicitamente di adottare lo storico trovato accanto al codice.
"""
from datetime import datetime, timezone
from pathlib import Path

from starkeno import percorsi
from starkeno.migrazioni import upgrade_head
from starkeno.recupero import recupera_database


def trasloca_se_serve(radice_codice: Path | None = None) -> str | None:
    """Copia e migra lo storico noto senza rinominare o cancellare la sorgente.

    Non sovrascrive una destinazione esistente: la fusione o sostituzione di due
    storici richiede il flusso di recupero esplicito, con backup e verifica.
    """
    if radice_codice is None:
        radice_codice = Path(__file__).resolve().parent.parent
    vecchio = Path(radice_codice) / percorsi.NOME_DATABASE
    if not vecchio.exists():
        return None

    destinazione = Path(percorsi.percorso_database())
    if destinazione.exists():
        return None

    recupera_database(
        vecchio,
        destinazione,
        now=datetime.now(timezone.utc),
        migra=lambda percorso: upgrade_head(percorso, silenzioso=True),
    )
    return str(destinazione)
