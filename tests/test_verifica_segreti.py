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


# I valori finti si compongono a pezzi, come quelli sopra: scritti per intero
# renderebbero questo file un rilievo per lo scanner stesso, e
# `test_every_tracked_text_file_is_public_safe` diventerebbe rosso per sempre.
# Sono comunque i valori d'esempio che AWS pubblica nella propria documentazione.


def test_riconosce_access_key_id_aws(tmp_path):
    segreto = "AKIA" + "IOSFODNN7EXAMPLE"
    file = tmp_path / "config.txt"
    file.write_text(f"aws_access_key_id = {segreto}", encoding="utf-8")

    rilievi = scansiona([file])

    assert [(r.percorso, r.tipo) for r in rilievi] == [(file, "aws_access_key_id")]
    assert segreto not in repr(rilievi)


def test_riconosce_anche_le_credenziali_temporanee_aws(tmp_path):
    file = tmp_path / "sessione.txt"
    file.write_text("ASIA" + "Y34FZKBOKMUTVV7A", encoding="utf-8")

    assert [r.tipo for r in scansiona([file])] == ["aws_access_key_id"]


def test_riconosce_la_chiave_segreta_aws_accanto_al_suo_nome(tmp_path):
    segreto = "wJalrXUtnFEMI/K7MDENG/bPx" + "RfiCYEXAMPLEKEY"
    file = tmp_path / "credentials"
    file.write_text(f'aws_secret_access_key = "{segreto}"', encoding="utf-8")

    rilievi = scansiona([file])

    assert [r.tipo for r in rilievi] == ["aws_secret_access_key"]
    assert segreto not in repr(rilievi)


def test_la_chiave_segreta_aws_lontana_dal_suo_nome_non_viene_vista(tmp_path):
    # Limite dichiarato, non difetto nascosto: senza il nome accanto la chiave
    # segreta e' indistinguibile da qualunque stringa base64 di quaranta caratteri.
    # L'identificativo `AKIA...`, che invece si riconosce da solo, resta la rete.
    segreto = "wJalrXUtnFEMI/K7MDENG/bPx" + "RfiCYEXAMPLEKEY"
    file = tmp_path / "sparso.txt"
    file.write_text(f"chiave:\n\n    {segreto}\n", encoding="utf-8")

    assert scansiona([file]) == ()


def test_una_stringa_qualunque_di_quaranta_caratteri_non_e_una_chiave_aws(tmp_path):
    # Cercare quaranta caratteri base64 da soli farebbe scattare il cancello su ogni
    # sha1, hash o blob base64 del repository. Un cancello che urla sempre si impara
    # a scavalcare, ed e' peggio di non averlo.
    file = tmp_path / "innocuo.txt"
    file.write_text(
        "commit da39a3ee5e6b4b0d3255bfef95601890afd80709\n"
        "digest = 2fd4e1c67a2d28fced849ee1bb76e7391b93eb12\n",
        encoding="utf-8",
    )

    assert scansiona([file]) == ()
