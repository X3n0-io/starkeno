from pathlib import Path

from scripts.verifica_segreti import main, scansiona


def test_secret_scanner_reports_type_without_leaking_value(tmp_path):
    segreto = "sk-" + "A" * 40
    file = tmp_path / "leak.txt"
    file.write_text(segreto, encoding="utf-8")

    rilievi = scansiona([file])

    assert [(r.percorso, r.tipo) for r in rilievi] == [(file, "openai_key")]
    assert segreto not in repr(rilievi)


def test_cli_prints_only_path_and_type(tmp_path, capsys):
    segreto = "ghp_" + "B" * 36
    file = tmp_path / "leak.txt"
    file.write_text("token=" + segreto, encoding="utf-8")

    assert main([str(file)]) == 1

    uscita = capsys.readouterr().out
    assert uscita.strip() == f"{file}:github_token"
    assert segreto not in uscita


def test_sanitized_fixture_is_clean():
    assert scansiona([Path("tests/fixtures/transcript_vero.jsonl")]) == ()
