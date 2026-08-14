"""v2: le colonne che l'ingestione dal transcript riempie

La grana della spesa e' `(sessionId, message.id)` — misurato: il transcript scrive 2,04
righe per chiamata API e sommare per riga da' 2,03x di gonfiaggio. Quella coppia e'
insieme la grana corretta e la CHIAVE DI IDEMPOTENZA: l'indice unico su di essa rende
una riesecuzione dell'hook un no-op invece di un raddoppio.

`azione_fallita` ed `esito_noto` sono DUE colonne e non una a tre stati: mai NULL per
"non lo so" su un booleano. L'esito di uno strumento arriva nel messaggio successivo, e
misurato resta irrisolto nello 0,04% dei casi — piccolo, ma se lo si scrivesse "falso"
sia R1 sia il costo degli errori diventerebbero ottimisti per costruzione.

`azioni_nella_chiamata` conta le azioni di una chiamata multipla (il 10,3% ne ha piu' di
una) senza gonfiare il numero di righe: righe multiple renderebbero le soglie che contano
azioni il 10% piu' sensibili senza che nessuno l'abbia deciso.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Stringa vuota, mai NULL: in SQLite due NULL sono DISTINTI, quindi un indice unico che
# li contiene smette di vincolare senza dire niente.
VUOTA = sa.text("''")


def upgrade() -> None:
    op.add_column("agent_actions", sa.Column("session_id", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("message_id", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("azione_fallita", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("agent_actions", sa.Column("esito_noto", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("agent_actions", sa.Column("azioni_nella_chiamata", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.add_column("agent_actions", sa.Column("skill", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("plugin", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("mcp_server", sa.String(), nullable=False, server_default=VUOTA))
    op.add_column("agent_actions", sa.Column("is_sidechain", sa.Integer(), nullable=False, server_default=sa.text("0")))

    # L'unico indice UNICO della tabella: e' cio' che rende l'hook rieseguibile.
    # Parziale, perche' la riga preesistente (e chiunque scriva senza passare
    # dall'ingestione) ha le sentinelle vuote e non deve collidere con se stessa.
    op.execute(
        "CREATE UNIQUE INDEX ix_actions_chiamata ON agent_actions (session_id, message_id) "
        "WHERE session_id != '' AND message_id != ''"
    )
    # R1 legge la sequenza di UNA sessione: senza questo indice ordina in memoria.
    op.create_index("ix_actions_project_session_time", "agent_actions",
                    ["project", "session_id", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_actions_project_session_time", table_name="agent_actions")
    op.drop_index("ix_actions_chiamata", table_name="agent_actions")
    for colonna in ("is_sidechain", "mcp_server", "plugin", "skill",
                    "azioni_nella_chiamata", "esito_noto", "azione_fallita",
                    "message_id", "session_id"):
        op.drop_column("agent_actions", colonna)
