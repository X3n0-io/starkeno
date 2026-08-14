from pathlib import Path

import pytest

from scripts.costruisci_snapshot_pubblico import costruisci_snapshot
from scripts.verifica_pubblicazione import scansiona_pubblico, tracked_text_files


def test_public_snapshot_contains_head_without_private_history(tmp_path):
    if not Path(".git").exists():
        pytest.skip("git archive richiede un checkout sorgente")
    destinazione = costruisci_snapshot(tmp_path / "pubblico")

    assert (destinazione / "pyproject.toml").is_file()
    assert not (destinazione / ".git").exists()
    assert not (destinazione / "starkeno.db").exists()
    assert not list(destinazione.rglob("*.log"))
    assert scansiona_pubblico(tracked_text_files(destinazione)) == ()


def test_nonempty_destination_is_rejected_without_deleting_its_files(tmp_path):
    destinazione = tmp_path / "esistente"
    destinazione.mkdir()
    sentinella = destinazione / "non-toccare.txt"
    sentinella.write_text("resta", encoding="utf-8")

    with pytest.raises(ValueError, match="non e vuota"):
        costruisci_snapshot(destinazione)

    assert sentinella.read_text(encoding="utf-8") == "resta"


def test_revision_cannot_be_interpreted_as_a_git_option(tmp_path):
    destinazione = tmp_path / "pubblico"

    with pytest.raises(ValueError, match="revisione non valida"):
        costruisci_snapshot(destinazione, revisione="--list")

    assert not destinazione.exists()
