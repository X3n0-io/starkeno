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
)
RISORSE_PLUGIN_SDIST = (
    ".codex-plugin/plugin.json",
    "hooks/hooks.json",
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
