"""Configurazione Alembic portabile, indipendente dalla radice del repository."""
from contextlib import nullcontext, redirect_stderr
from importlib.resources import files
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def configurazione_alembic(db_path: str | Path) -> Config:
    """Costruisce una Config completa usando le migrazioni incluse nel pacchetto."""
    configurazione = Config()
    configurazione.set_main_option("script_location", str(files("migrations")))
    percorso = str(Path(db_path)).replace("\\", "/")
    configurazione.set_main_option("sqlalchemy.url", "sqlite:///%s" % percorso)
    return configurazione


def revisione_head() -> str:
    """La revisione di testa distribuita con questa versione di StarkEno."""
    configurazione = configurazione_alembic(":memory:")
    return ScriptDirectory.from_config(configurazione).get_current_head()


def upgrade_head(db_path: str | Path, *, silenzioso: bool = False) -> None:
    """Migra il database a head, silenziando Alembic quando gira dentro un hook."""
    contesto = redirect_stderr(StringIO()) if silenzioso else nullcontext()
    with contesto:
        command.upgrade(configurazione_alembic(db_path), "head")
