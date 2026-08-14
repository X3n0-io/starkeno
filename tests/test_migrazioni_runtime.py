import sqlite3
from pathlib import Path

from starkeno.migrazioni import configurazione_alembic, revisione_head, upgrade_head


def test_runtime_config_uses_packaged_migrations(tmp_path):
    """Il runtime non deve dipendere da un alembic.ini accanto al repository."""
    cfg = configurazione_alembic(tmp_path / "runtime.db")

    assert Path(cfg.get_main_option("script_location")).name == "migrations"
    assert cfg.config_file_name is None


def test_runtime_upgrade_builds_head_schema(tmp_path):
    """La configurazione portabile deve costruire davvero lo schema completo."""
    percorso = tmp_path / "runtime.db"

    upgrade_head(percorso, silenzioso=True)

    with sqlite3.connect(percorso) as conn:
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0] == revisione_head()
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='agent_actions'"
        ).fetchone()[0] == 1
