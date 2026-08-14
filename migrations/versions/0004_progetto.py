"""v2: l'asse non e' l'utente, e' il progetto

In locale l'utente e' una COSTANTE: una colonna che conterrebbe sempre lo stesso valore
non distingue niente. L'asse utile lo porta gia' il transcript, nel campo `cwd`.
Misurato sul traffico reale: 30 progetti distinti.

Si fa adesso perche' il database di produzione ha UNA riga: rinominare oggi e' una
migrazione senza dati da preservare, farlo dopo la pubblicazione significa migrare lo
storico di chi ha installato il plugin.

**`batch_alter_table` non e' ornamentale:** SQLite non ha `ALTER TABLE RENAME COLUMN`
in tutte le versioni supportate, e Alembic in modalita' batch ricostruisce la tabella.
Verificato eseguendola: la ricostruzione conserva le chiavi primarie composte e — cosa
che non era ovvia — anche la clausola `WHERE` degli indici parziali di `alerts`.

**I DUE indici sulla colonna, non uno.** Oltre a `ix_actions_agent_time`, dalla v0
esiste `ix_agent_actions_agent_name`: lo crea da solo il modello ORM con `index=True`, e
SQLAlchemy ne deriva il nome DALLA COLONNA. Rinominando solo la colonna, sul disco resta
un indice che si chiama `..._agent_name` mentre `create_all` (cioe' i test) ne produce
uno che si chiama `..._project`: due schemi diversi, che e' esattamente cio' che
l'invariante 7 vieta. Misurato eseguendo la migrazione e leggendo il DDL rimasto.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABELLE = ("agent_actions", "alerts", "rule_status", "agent_watermark")


def upgrade() -> None:
    op.drop_index("ix_actions_agent_time", table_name="agent_actions")
    op.drop_index("ix_agent_actions_agent_name", table_name="agent_actions")
    for tabella in TABELLE:
        with op.batch_alter_table(tabella) as batch:
            batch.alter_column("agent_name", new_column_name="project")
    op.create_index("ix_agent_actions_project", "agent_actions", ["project"])
    op.create_index("ix_actions_project_time", "agent_actions", ["project", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_actions_project_time", table_name="agent_actions")
    op.drop_index("ix_agent_actions_project", table_name="agent_actions")
    for tabella in TABELLE:
        with op.batch_alter_table(tabella) as batch:
            batch.alter_column("project", new_column_name="agent_name")
    op.create_index("ix_agent_actions_agent_name", "agent_actions", ["agent_name"])
    op.create_index("ix_actions_agent_time", "agent_actions", ["agent_name", "timestamp"])
