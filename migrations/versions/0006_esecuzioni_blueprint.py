"""v3: le esecuzioni dichiarate e i loro marcatori di nodo

Il ponte fra la meta' osservativa e quella predittiva. **Non tocca `agent_actions`**:
l'attribuzione e' una vista calcolata al momento del confronto incrociando questi
intervalli con i `timestamp` gia' raccolti, mai una colonna timbrata sulla riga. Cosi'
l'hook non deve imparare cosa sia un Blueprint, e una dichiarazione sbagliata si
corregge ricalcolando.

Le colonne temporali sono `sa.DateTime` come nella 0003: `db.UTCDateTime` ha
`impl = DateTime`, quindi il DDL emesso e' identico, ma i MODELLI devono usare
`UTCDateTime` perche' la normalizzazione del fuso e' un comportamento Python.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blueprint_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_key", sa.String(), nullable=False),
        sa.Column("project", sa.String(), nullable=False),
        sa.Column("blueprint_hash", sa.String(), nullable=False),
        sa.Column("analysis_json", sa.String(), nullable=False),
        sa.Column("model_map_json", sa.String(), nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key"),
    )
    op.create_index("ix_blueprint_runs_project_ended", "blueprint_runs",
                    ["project", "ended_at"])

    op.create_table(
        "blueprint_run_markers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("declared_at", sa.DateTime(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blueprint_run_markers_run", "blueprint_run_markers",
                    ["run_id", "declared_at", "seq"])


def downgrade() -> None:
    op.drop_index("ix_blueprint_run_markers_run", table_name="blueprint_run_markers")
    op.drop_table("blueprint_run_markers")
    op.drop_index("ix_blueprint_runs_project_ended", table_name="blueprint_runs")
    op.drop_table("blueprint_runs")
