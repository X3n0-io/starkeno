"""Risoluzione delle risorse del plugin in sorgente e nel pacchetto installato."""
from importlib.resources import files
from pathlib import Path


def _radice_sorgente() -> Path:
    return Path(__file__).resolve().parent.parent


def _radice_pacchetto() -> Path:
    return Path(str(files("starkeno"))) / "plugin_bundle"


def plugin_root() -> Path:
    """Restituisce la radice che contiene il manifest Codex effettivamente disponibile."""
    for candidato in (_radice_sorgente(), _radice_pacchetto()):
        if (candidato / ".codex-plugin" / "plugin.json").is_file():
            return candidato
    raise FileNotFoundError("manifest Codex di StarkEno non trovato")
