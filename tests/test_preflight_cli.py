from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from starkeno.preflight_cli import main
from starkeno.preflight_schema import dump_blueprint, load_blueprint
from starkeno.preflight_service import analyze_confirmed, normalize_draft


FIXTURE = Path(__file__).parent / "fixtures" / "preflight" / "minimal.json"
MINIMAL_BLUEPRINT = FIXTURE.read_text(encoding="utf-8")


def _blueprint_text(*, confirmed: bool, revision: int = 1) -> str:
    payload = json.loads(MINIMAL_BLUEPRINT)
    payload["confirmed"] = confirmed
    payload["revision"] = revision
    payload["parent_revision"] = revision - 1 if revision > 1 else None
    return json.dumps(payload, ensure_ascii=False)


def _write_blueprint(
    directory: Path,
    *,
    confirmed: bool = False,
    revision: int = 1,
    name: str = "blueprint.json",
) -> Path:
    source = directory / name
    source.write_text(
        _blueprint_text(confirmed=confirmed, revision=revision),
        encoding="utf-8",
    )
    return source


def test_normalize_draft_preserva_la_revisione_di_un_draft():
    normalized = normalize_draft(MINIMAL_BLUEPRINT, format_hint="json")

    assert normalized.confirmed is False
    assert normalized.revision == 1
    assert normalized.parent_revision is None


def test_normalize_draft_disconferma_creando_una_nuova_revisione():
    normalized = normalize_draft(
        _blueprint_text(confirmed=True, revision=4), format_hint="json"
    )

    assert normalized.confirmed is False
    assert normalized.revision == 5
    assert normalized.parent_revision == 4


def test_analyze_confirmed_rifiuta_un_blueprint_non_confermato():
    blueprint = load_blueprint(MINIMAL_BLUEPRINT, format_hint="json")

    with pytest.raises(ValueError, match="confermato"):
        analyze_confirmed(blueprint, samples=20, seed=7)


def test_analyze_confirmed_esegue_lint_simulazione_e_conserva_source_path(tmp_path):
    source = tmp_path / "origine.json"
    blueprint = load_blueprint(
        _blueprint_text(confirmed=True), format_hint="json"
    )

    analysis = analyze_confirmed(
        blueprint, samples=20, seed=7, source_path=source
    )

    assert analysis.blueprint == blueprint
    assert analysis.simulation.samples == 20
    assert analysis.simulation.effective_seed == 7
    assert analysis.source_path == source
    assert all(finding.blueprint_hash == analysis.simulation.blueprint_hash for finding in analysis.findings)


def test_draft_normalizza_ma_non_chiama_il_simulatore(tmp_path, monkeypatch):
    source = _write_blueprint(tmp_path)
    output = tmp_path / "draft.json"
    monkeypatch.setattr(
        "starkeno.preflight_service.simulate_blueprint",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("simulato")),
    )

    assert main([
        "draft", "--input", str(source), "--format", "json",
        "--output", str(output),
    ]) == 0
    written = load_blueprint(output.read_text(encoding="utf-8"), format_hint="json")
    assert written.confirmed is False


def test_draft_confermato_viene_disconfermato_con_lineage(tmp_path):
    source = _write_blueprint(tmp_path, confirmed=True, revision=4)
    output = tmp_path / "nuovo draft.yaml"

    assert main([
        "draft", "--input", str(source), "--format", "yaml",
        "--output", str(output),
    ]) == 0
    written = load_blueprint(output.read_text(encoding="utf-8"), format_hint="yaml")
    assert (written.revision, written.parent_revision, written.confirmed) == (5, 4, False)


def test_analyze_rifiuta_senza_confirmed(tmp_path, capsys):
    source = _write_blueprint(tmp_path)
    output = tmp_path / "report.json"

    assert main([
        "analyze", "--input", str(source), "--output", str(output),
        "--format", "json",
    ]) == 2
    captured = capsys.readouterr()
    assert "--confirmed" in captured.err
    assert captured.out == ""
    assert not output.exists()


@pytest.mark.parametrize("already_confirmed", [False, True])
def test_analyze_flag_crea_sempre_una_nuova_revisione_confermata(
    tmp_path, already_confirmed
):
    source = _write_blueprint(tmp_path, confirmed=already_confirmed, revision=4)
    output = tmp_path / "report.json"

    assert main([
        "analyze", "--input", str(source), "--confirmed", "--output", str(output),
        "--format", "json", "--samples", "20", "--seed", "11",
    ]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["blueprint"]["revision"] == 5
    assert payload["blueprint"]["parent_revision"] == 4
    assert payload["blueprint"]["confirmed"] is True
    assert payload["simulation"]["effective_seed"] == 11


def test_analyze_confirmed_scrive_artefatto_e_stdout_conciso(tmp_path, capsys):
    source = _write_blueprint(tmp_path)
    output = tmp_path / "cartella con spazi" / "report finale.json"

    assert main([
        "analyze", "--input", str(source), "--confirmed", "--output", str(output),
        "--format", "json", "--samples", "20",
    ]) == 0
    assert output.exists()
    captured = capsys.readouterr()
    assert len(captured.out.encode("utf-8")) <= 2_000
    assert str(output.resolve()) in captured.out
    assert "simulation" not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("suffix", ["yaml", "yml"])
def test_input_yaml_e_suffisso_yml_sono_inferiti(tmp_path, suffix):
    blueprint = load_blueprint(MINIMAL_BLUEPRINT, format_hint="json")
    source = tmp_path / f"input.{suffix}"
    source.write_text(dump_blueprint(blueprint, format="yaml"), encoding="utf-8")
    output = tmp_path / "draft.json"

    assert main([
        "draft", "--input", str(source), "--format", "json", "--output", str(output),
    ]) == 0
    assert load_blueprint(output.read_text(encoding="utf-8"), format_hint="json") == blueprint


def test_input_format_sovrascrive_un_suffisso_ignoto(tmp_path):
    source = _write_blueprint(tmp_path, name="input.data")
    output = tmp_path / "draft.yaml"

    assert main([
        "draft", "--input", str(source), "--input-format", "json",
        "--format", "yaml", "--output", str(output),
    ]) == 0
    assert yaml.safe_load(output.read_text(encoding="utf-8"))["confirmed"] is False


def test_stdin_utf8_richiede_input_format_e_funziona(monkeypatch, tmp_path, capsys):
    output = tmp_path / "bozza.json"
    monkeypatch.setattr("sys.stdin.read", lambda: MINIMAL_BLUEPRINT)

    assert main(["draft", "--format", "json", "--output", str(output)]) == 2
    assert "--input-format" in capsys.readouterr().err
    assert not output.exists()

    assert main([
        "draft", "--input-format", "json", "--format", "json",
        "--output", str(output),
    ]) == 0
    assert load_blueprint(output.read_text(encoding="utf-8"), format_hint="json").goal.id == "goal-release"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["draft", "--format", "json"], "--output"),
        (["draft", "--output", "x.json"], "--format"),
        (["analyze", "--format", "json", "--output", "x.json"], "--confirmed"),
        (["draft", "--format", "html", "--output", "x.html"], "--format"),
        (["design", "--format", "json", "--output", "x.json"], "invalid choice"),
    ],
)
def test_uso_scorretto_ritorna_due_senza_system_exit(argv, expected, capsys):
    assert main(argv) == 2
    captured = capsys.readouterr()
    assert expected in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "extra",
    [
        ["--samples", "0"],
        ["--samples", "10001"],
        ["--samples", "non-numero"],
        ["--seed", "-1"],
        ["--seed", "non-numero"],
        ["--input-format", "toml"],
    ],
)
def test_parametri_analyze_invalidi_non_creano_artefatto(tmp_path, extra, capsys):
    source = _write_blueprint(tmp_path)
    output = tmp_path / "report.json"

    assert main([
        "analyze", "--input", str(source), "--confirmed", "--format", "json",
        "--output", str(output), *extra,
    ]) == 2
    assert capsys.readouterr().err
    assert not output.exists()


def test_suffisso_ignoto_senza_override_e_utf8_invalido_sono_errori_utente(tmp_path, capsys):
    unknown = _write_blueprint(tmp_path, name="input.unknown")
    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"\xff\xfe")
    output = tmp_path / "draft.json"

    assert main([
        "draft", "--input", str(unknown), "--format", "json", "--output", str(output),
    ]) == 2
    assert "--input-format" in capsys.readouterr().err
    assert not output.exists()

    assert main([
        "draft", "--input", str(invalid), "--format", "json", "--output", str(output),
    ]) == 2
    assert capsys.readouterr().err
    assert not output.exists()


def test_input_output_alias_sono_rifiutati_senza_modificare_input(tmp_path, capsys):
    source = _write_blueprint(tmp_path)
    before = source.read_bytes()

    assert main([
        "draft", "--input", str(source), "--format", "json", "--output", str(source),
    ]) == 2
    assert "input" in capsys.readouterr().err.lower()
    assert source.read_bytes() == before


def test_output_esistente_viene_sostituito_atomicamente(tmp_path):
    source = _write_blueprint(tmp_path)
    output = tmp_path / "draft.json"
    output.write_text("contenuto precedente", encoding="utf-8")

    assert main([
        "draft", "--input", str(source), "--format", "json", "--output", str(output),
    ]) == 0
    assert load_blueprint(output.read_text(encoding="utf-8"), format_hint="json").confirmed is False
    assert not tuple(tmp_path.glob(f".{output.name}.*.tmp"))


def test_errore_interno_restituisce_uno_senza_traceback_o_stdout(
    tmp_path, monkeypatch, capsys
):
    source = _write_blueprint(tmp_path)
    output = tmp_path / "draft.json"

    def esplode(*args, **kwargs):
        raise RuntimeError("dettaglio interno sensibile")

    monkeypatch.setattr("starkeno.preflight_cli.normalize_draft", esplode)

    assert main([
        "draft", "--input", str(source), "--format", "json", "--output", str(output),
    ]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert "dettaglio interno sensibile" not in captured.err
    assert not output.exists()


@pytest.mark.parametrize(
    ("command", "target"),
    [
        ("draft", "starkeno.preflight_cli.normalize_draft"),
        ("analyze", "starkeno.preflight_cli.analyze_confirmed"),
        ("analyze", "starkeno.preflight_report.write_analysis"),
    ],
)
def test_value_error_interno_resta_generico_e_non_crea_artefatti(
    tmp_path, monkeypatch, capsys, command, target
):
    source = _write_blueprint(tmp_path)
    output = tmp_path / "artefatto.json"

    def esplode(*args, **kwargs):
        raise ValueError("segreto-interno-da-non-esporre")

    monkeypatch.setattr(target, esplode)
    argv = [
        command, "--input", str(source), "--format", "json",
        "--output", str(output),
    ]
    if command == "analyze":
        argv.extend(("--confirmed", "--samples", "20"))

    assert main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Errore interno durante preflight.\n"
    assert "segreto-interno-da-non-esporre" not in captured.err
    assert not output.exists()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("{non-json", "JSON non valido"),
        ('{"schema_version": "1.0"}', "Field required"),
    ],
)
def test_input_blueprint_invalido_resta_un_errore_utente_utile(
    tmp_path, capsys, payload, expected
):
    source = tmp_path / "input.json"
    source.write_text(payload, encoding="utf-8")
    output = tmp_path / "draft.json"

    assert main([
        "draft", "--input", str(source), "--format", "json", "--output", str(output),
    ]) == 2
    captured = capsys.readouterr()
    assert expected in captured.err
    assert captured.out == ""
    assert not output.exists()


@pytest.mark.parametrize(
    ("operation", "expected_loaded"),
    [
        ("import-service", False),
        ("normalize", False),
        ("draft", False),
        ("analyze", True),
    ],
)
def test_simulatore_viene_caricato_solo_dall_analisi_fresca(
    tmp_path, operation, expected_loaded
):
    output = tmp_path / f"{operation}.json"
    probe = """
import sys
from pathlib import Path

operation, source, output = sys.argv[1:]
if operation == "import-service":
    import starkeno.preflight_service
elif operation == "normalize":
    from starkeno.preflight_service import normalize_draft
    normalize_draft(Path(source).read_text(encoding="utf-8"), format_hint="json")
elif operation == "draft":
    from starkeno.preflight_cli import main
    if main(["draft", "--input", source, "--format", "json", "--output", output]) != 0:
        raise SystemExit(8)
else:
    from starkeno.preflight_cli import main
    if main(["analyze", "--input", source, "--confirmed", "--samples", "1",
             "--format", "json", "--output", output]) != 0:
        raise SystemExit(9)
loaded = "starkeno.preflight_simulate" in sys.modules
raise SystemExit(0 if loaded is EXPECTED else 7)
""".replace("EXPECTED", repr(expected_loaded))

    completed = subprocess.run(
        [sys.executable, "-c", probe, operation, str(FIXTURE), str(output)],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_system_exit_e_keyboard_interrupt_non_vengono_nascosti(tmp_path, monkeypatch):
    source = _write_blueprint(tmp_path)
    output = tmp_path / "draft.json"

    for exception in (SystemExit(9), KeyboardInterrupt()):
        def interrompe(*args, _exception=exception, **kwargs):
            raise _exception

        monkeypatch.setattr("starkeno.preflight_cli.normalize_draft", interrompe)
        with pytest.raises(type(exception)):
            main([
                "draft", "--input", str(source), "--format", "json",
                "--output", str(output),
            ])
