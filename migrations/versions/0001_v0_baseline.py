"""v0 baseline: lo schema che la v0 ha lasciato su starkeno.db

Questa revisione ha due consumatori diversi, ed e' importante non confonderli:

- **database nuovo** -> viene ESEGUITA, e costruisce lo schema v0 da zero.
- **`starkeno.db` gia' esistente** -> NON viene mai eseguita: si fa
  `alembic stamp 0001`, che scrive solo la riga in `alembic_version` dichiarando
  "questo database e' gia' a questo punto". Poi `alembic upgrade head` applica
  il resto della catena.

Percio' il DDL qui dentro deve corrispondere ESATTAMENTE a quello che c'e' gia' sul
disco: se divergesse, i due percorsi di primo avvio produrrebbero schemi diversi e
nessun test lo vedrebbe. `test_both_startup_paths_produce_the_same_schema` esiste
per questo.

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("model_used", sa.String(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        # sa.DateTime e non db.UTCDateTime: il TypeDecorator della v0 ha `impl = DateTime`,
        # quindi il DDL emesso e' identico. La normalizzazione del fuso e' un
        # comportamento Python, non una proprieta' della colonna sul disco.
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_actions_agent_name", "agent_actions", ["agent_name"])


def downgrade() -> None:
    op.drop_index("ix_agent_actions_agent_name", table_name="agent_actions")
    op.drop_table("agent_actions")
