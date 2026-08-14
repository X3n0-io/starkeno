from pathlib import Path
import subprocess
import sys

from scripts.verifica_pubblicazione import scansiona_pubblico, tracked_text_files


def test_every_tracked_text_file_is_public_safe():
    paths = tracked_text_files(Path.cwd())

    rilievi = scansiona_pubblico(paths)

    assert rilievi == (), "\n".join(
        f"{rilievo.percorso}:{rilievo.tipo}" for rilievo in rilievi
    )


def test_scanner_flags_a_literal_home_without_printing_the_username(tmp_path):
    file = tmp_path / "doc.md"
    file.write_text(
        "C:" + "\\" + "Users" + "\\" + "nome-reale"
        + "\\" + "Documents" + "\\" + "note-personali",
        encoding="utf-8",
    )

    rilievi = scansiona_pubblico([file])

    assert [r.tipo for r in rilievi] == ["windows_home_letterale"]
    assert "nome-reale" not in repr(rilievi)


def test_public_scanner_reuses_the_redacted_secret_detection(tmp_path):
    file = tmp_path / "doc.md"
    valore = "sk-" + "Z" * 40
    file.write_text(valore, encoding="utf-8")

    rilievi = scansiona_pubblico([file])

    assert [r.tipo for r in rilievi] == ["segreto_openai_key"]
    assert valore not in repr(rilievi)


def test_publication_scanner_runs_as_a_standalone_script():
    risultato = subprocess.run(
        [sys.executable, "-I", "scripts/verifica_pubblicazione.py"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert risultato.returncode == 0, risultato.stdout + risultato.stderr
