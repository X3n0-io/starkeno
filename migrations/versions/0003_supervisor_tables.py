"""v1: le tabelle del Supervisore

`alerts` (eventi) · `rule_status` (stati) · `supervisor_state` (heartbeat) ·
`agent_watermark` (fin dove R3 ha esaminato).

Le colonne temporali sono `sa.DateTime`: il TypeDecorator `db.UTCDateTime` ha
`impl = DateTime`, quindi il DDL emesso e' identico. La normalizzazione del fuso e' un
comportamento Python, non una proprieta' della colonna sul disco — ma i MODELLI devono
usare `UTCDateTime`, altrimenti `now - first_seen` solleva `TypeError` a ogni giro,
l'eccezione viene inghiottita dal try/except per-regola, e nessun candidate diventa mai
open. `test_alert_datetimes_roundtrip_as_aware_utc` protegge quel confine.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("rule", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=False),
        sa.Column("evidence", sa.String(), nullable=False),
        sa.Column("episodes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("observed_rounds", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution", sa.String(), nullable=True),
        sa.Column("muted_until", sa.DateTime(), nullable=True),
        sa.Column("user_note", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Un solo alert vivo per (agente, regola). 'dismissed' e 'resolved' restano fuori.
    op.create_index("ix_alerts_one_live", "alerts", ["agent_name", "rule"],
                    unique=True, sqlite_where=text("status IN ('candidate','open')"))
    # La lookup del percorso critico. Misurato: COVERING INDEX.
    op.create_index("ix_alerts_open", "alerts", ["agent_name"],
                    sqlite_where=text("status = 'open'"))

    op.create_table(
        "rule_status",
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("rule", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("agent_name", "rule"),
    )

    op.create_table(
        "supervisor_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_ms", sa.Integer(), nullable=False),
        sa.Column("agents_evaluated", sa.Integer(), nullable=False),
        sa.Column("rules_failed", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent_watermark",
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("last_evaluated_action_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("agent_name"),
    )


def downgrade() -> None:
    op.drop_table("agent_watermark")
    op.drop_table("supervisor_state")
    op.drop_table("rule_status")
    op.drop_index("ix_alerts_open", table_name="alerts")
    op.drop_index("ix_alerts_one_live", table_name="alerts")
    op.drop_table("alerts")
