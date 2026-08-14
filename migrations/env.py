"""Ambiente Alembic di StarkEno.

Due sole differenze rispetto allo scheletro generato da `alembic init`:

1. **L'URL del database.** Se `sqlalchemy.url` e' gia' impostato nella Config (e' cosi'
   nei test, che ne passano uno su `tmp_path`) viene usato quello. Altrimenti si prende
   `starkeno.config.DB_PATH`, che a sua volta rispetta `STARKENO_DB_PATH`.
   Senza il primo ramo, un test che chiama `command.upgrade` migrerebbe il database di
   PRODUZIONE — l'invariante 3 di CLAUDE.md ("i test non toccano mai DB_PATH").

2. **`render_as_batch=True`.** SQLite non ha una `ALTER TABLE` completa: senza questo,
   ogni operazione che non sia una pura `ADD COLUMN` fallisce. Le migrazioni della v1
   aggiungono solo colonne e indici, ma il costo di averlo acceso e' zero e il costo di
   scoprirlo mancante nel mezzo di una migrazione e' alto.

`target_metadata` resta `None`: le migrazioni sono scritte a mano, non autogenerate.
L'autogenerazione confronta i modelli col database e produce diff plausibili ma non
sempre corretti su SQLite; qui le revisioni sono poche e vale la pena leggerle.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url", default=None)
    if url:
        return url

    from starkeno.config import DB_PATH

    return "sqlite:///%s" % DB_PATH.replace("\\", "/")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
