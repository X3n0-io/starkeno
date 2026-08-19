import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


RADICE = Path(__file__).resolve().parent.parent
RISORSE_RUNTIME = (
    "starkeno/static/index.html",
    "starkeno/static/style.css",
    "migrations/env.py",
    "migrations/versions/0005_ingestione.py",
)
RISORSE_PLUGIN_WHEEL = (
    "starkeno/plugin_bundle/.codex-plugin/plugin.json",
    "starkeno/plugin_bundle/hooks/hooks.json",
    # Il bundle Claude Code non era verificato da nessuno: una skill che esiste solo in
    # sviluppo e' la stessa forma di difetto gia' pagata due volte il 19/08/2026 —
    # corretto nel repository, assente sulla macchina.
    "starkeno/plugin_bundle/plugin-claude-code/hooks/hooks.json",
    "starkeno/plugin_bundle/plugin-claude-code/skills/starkeno/SKILL.md",
)
RISORSE_PLUGIN_SDIST = (
    ".codex-plugin/plugin.json",
    "hooks/hooks.json",
    "plugin-claude-code/hooks/hooks.json",
    "plugin-claude-code/skills/starkeno/SKILL.md",
)


def _contiene_tutte(nomi, attesi):
    normalizzati = {nome.replace("\\", "/") for nome in nomi}
    return all(
        any(nome == atteso or nome.endswith("/" + atteso) for nome in normalizzati)
        for atteso in attesi
    )


def test_build_produces_wheel_and_sdist_with_all_runtime_resources(tmp_path):
    risultato = subprocess.run(
        [
            sys.executable, "-m", "build", "--outdir", str(tmp_path),
        ],
        cwd=RADICE,
        text=True,
        capture_output=True,
        check=False,
    )

    assert risultato.returncode == 0, risultato.stdout + risultato.stderr
    (wheel,) = tmp_path.glob("starkeno-*.whl")
    (sdist,) = tmp_path.glob("starkeno-*.tar.gz")
    with zipfile.ZipFile(wheel) as archivio:
        assert _contiene_tutte(
            archivio.namelist(), RISORSE_RUNTIME + RISORSE_PLUGIN_WHEEL,
        )
    with tarfile.open(sdist, "r:gz") as archivio:
        assert _contiene_tutte(
            archivio.getnames(), RISORSE_RUNTIME + RISORSE_PLUGIN_SDIST,
        )
