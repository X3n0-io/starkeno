"""v1: scomposizione dei token e indice temporale su agent_actions

Un solo `tokens_used` non puo' rappresentare fedelmente il costo, perche' i componenti
hanno prezzi che differiscono di oltre un ordine di grandezza. R2 chiede "quanto e'
grosso il task?" e usa i TOTALI; R3 e R4 chiedono "quanto sto spendendo?" e useranno
`effective_tokens`, che pesa questi tre componenti.

Le colonne sono `nullable=True` senza server_default: NULL significa "non dichiarato",
e la tabella di decisione lo distingue da uno 0 dichiarato. Sono anche l'unica forma
possibile — `ADD COLUMN NOT NULL` senza default fallisce su una tabella che ha gia'
delle righe.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_actions", sa.Column("cache_read_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_actions", sa.Column("cache_write_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_actions", sa.Column("output_tokens", sa.Integer(), nullable=True))

    # Le finestre temporali di R1/R2/R4 passano tutte da qui. Misurato su 86.400 righe:
    # "SEARCH agent_actions USING INDEX ix_actions_agent_time (agent_name=? AND
    # timestamp>?)", SUM in 0,048 s. Come effetto collaterale toglie il
    # "USE TEMP B-TREE FOR ORDER BY" alla query che api.py esegue gia' a ogni
    # caricamento della dashboard: e' un guadagno sulla v0 che arriva gratis.
    op.create_index("ix_actions_agent_time", "agent_actions", ["agent_name", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_actions_agent_time", table_name="agent_actions")
    op.drop_column("agent_actions", "output_tokens")
    op.drop_column("agent_actions", "cache_write_tokens")
    op.drop_column("agent_actions", "cache_read_tokens")
