"""Controllo di versione dello schema all'avvio.

**Questa e' l'unica eccezione ammessa alla regola "il logging non deve mai fallire"**
(invariante 4 di CLAUDE.md, §7 dello spec). Ovunque altro, un errore va inghiottito
perche' perdere l'azione di un agente e' peggio del problema che l'ha causato. Qui no:
partire con uno schema disallineato significa che ogni query successiva fallira' su un
`no such column` dentro un try/except, e il sistema produrra' zero alert restando
visivamente identico a una flotta sana.

Fallire rumorosamente all'avvio e' infinitamente meglio.
"""
from alembic.runtime.migration import MigrationContext

from starkeno.migrazioni import revisione_head


class SchemaVersionError(RuntimeError):
    """Lo schema del database non e' alla revisione attesa. Non si parte."""


def head_revision() -> str:
    return revisione_head()


def current_revision(engine) -> str | None:
    """La revisione scritta nel database, o None se `alembic_version` non c'e'."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def check_or_die(engine) -> None:
    """Confronta la revisione del database con `head`. Solleva se non coincidono.

    Va chiamata all'avvio di ogni processo (mcp_server, api, supervisor), mai
    all'import: costruire una connessione al momento dell'import e' esattamente il
    problema che l'invariante 2 di CLAUDE.md vieta.
    """
    attesa = head_revision()
    trovata = current_revision(engine)

    if trovata == attesa:
        return

    if trovata is None:
        diagnosi = (
            "il database non e' sotto il controllo di Alembic "
            "(la tabella 'alembic_version' non esiste)"
        )
    else:
        diagnosi = "il database e' alla revisione '%s'" % trovata

    raise SchemaVersionError(
        "Schema del database disallineato: %s, mentre il codice si aspetta '%s'.\n"
        "\n"
        "  database gia' esistente (creato dalla v0)   ->  alembic stamp 0001\n"
        "                                                  alembic upgrade head\n"
        "  database nuovo                              ->  alembic upgrade head\n"
        "\n"
        "Il processo non parte: proseguire produrrebbe errori inghiottiti dai try/except "
        "e zero alert, che e' indistinguibile da un sistema sano." % (diagnosi, attesa)
    )
