"""Regressioni per gli export Preflight riproducibili e sicuri."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

import starkeno.preflight_report as preflight_report
from starkeno.preflight_lint import Finding, lint_blueprint
from starkeno.preflight_patch import compare_reports
from starkeno.preflight_report import PreflightAnalysis, render_analysis, write_analysis
from starkeno.preflight_schema import Blueprint
from starkeno.preflight_simulate import SimulationReport, simulate_blueprint


FIXTURE = Path(__file__).parent / "fixtures" / "preflight" / "minimal.json"


def make_analysis(
    *,
    goal: str = "Preparare una nota verificabile.",
    source_path: Path | None = None,
    assumption: str = "Assunzione <img src=\"https://evil.test/a\"> dichiarata.",
    finding_message: str = "Rilievo <script src=\"https://evil.test/x\"></script>.",
) -> PreflightAnalysis:
    """Costruisce dati reali di dominio, incluso Decimal e scenari completi."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["confirmed"] = True
    payload["goal"]["description"] = goal
    payload["models"][0].update(
        {
            "input_price_per_million": "1.25",
            "output_price_per_million": "2.50",
            "cache_read_price_per_million": "0.50",
            "cache_write_price_per_million": "1.00",
        }
    )
    blueprint = Blueprint.model_validate(payload)
    simulation = simulate_blueprint(blueprint, samples=2, seed=9).model_copy(
        update={"assumptions": (assumption,)}
    )
    finding = Finding(
        rule_id="PF-TEST-001",
        severity="warning",
        category="test",
        message=finding_message,
        evidence={"amount": Decimal("1.50"), "note": "evidenza"},
        locations=("nodes/draft",),
        suggestion="Riduci il contesto.",
        source="deterministic",
        blueprint_hash=simulation.blueprint_hash,
    )
    return PreflightAnalysis(
        blueprint=blueprint,
        findings=(finding, *lint_blueprint(blueprint)),
        simulation=simulation,
        comparison=compare_reports(simulation, simulation),
        source_path=source_path,
    )


@pytest.mark.parametrize("format", ["json", "yaml", "markdown", "html"])
def test_ogni_formato_contiene_ipotesi_confidenza_scenari_e_limiti(format: str):
    """Omettere in un export incertezze o scenari renderebbe il preventivo fuorviante."""
    output = render_analysis(make_analysis(), format=format)  # type: ignore[arg-type]

    assert "typical" in output.lower()
    assert "confidence" in output.lower() or "confidenza" in output.lower()
    assert "declared" in output.lower()
    assert "unknown" in output.lower() or "sconosciut" in output.lower()
    assert "maximum" in output.lower() or "massimo" in output.lower()
    assert "comparison" in output.lower() or "confronto" in output.lower()


@pytest.mark.parametrize("format", ["json", "yaml"])
def test_json_e_yaml_sono_parseabili_deterministici_e_non_esportano_source_path(
    format: str, tmp_path: Path
):
    """Un artefatto deve restare parseabile e non rivelare metadati locali dell'I/O."""
    source_path = tmp_path / "input-riservato.json"
    analysis = make_analysis(source_path=source_path)

    first = render_analysis(analysis, format=format)  # type: ignore[arg-type]
    second = render_analysis(analysis, format=format)  # type: ignore[arg-type]
    decoded = json.loads(first) if format == "json" else yaml.safe_load(first)

    assert first == second
    assert isinstance(decoded, dict)
    assert decoded["simulation"]["typical"]["cost"] == str(analysis.simulation.typical.cost)
    assert "source_path" not in decoded
    assert str(source_path) not in first


@pytest.mark.parametrize("format", ["markdown", "html"])
def test_formati_leggibili_escludono_source_path_e_scenari_assenti(tmp_path: Path, format: str):
    """Il report umano non deve nascondere né il path locale né scenari non disponibili."""
    source_path = tmp_path / "input-riservato.json"
    analysis = make_analysis(source_path=source_path)
    missing = analysis.simulation.model_copy(
        update={"maximum_status": "unbounded", "maximum": None}
    )
    without_maximum = analysis.model_copy(update={"simulation": missing})

    output = render_analysis(without_maximum, format=format)  # type: ignore[arg-type]

    assert "source_path" not in output
    assert str(source_path) not in output
    assert "maximum" in output.lower() or "massimo" in output.lower()
    assert "absent" in output.lower() or "assente" in output.lower()


def test_html_escapa_tutto_l_input_dinamico_e_non_carica_asset_remoti():
    """Goal, finding e assunzioni non fidati non devono diventare markup eseguibile."""
    html = render_analysis(
        make_analysis(goal='<script src="https://evil.test/x"></script>'), format="html"
    )

    assert '<script src=' not in html.lower()
    assert "&lt;script" in html
    assert "&lt;img" in html
    assert "<link" not in html.lower()
    assert ' src="' not in html.lower()
    assert "https://evil.test/x" in html
    assert "default-src 'none'" in html
    assert "<style>" in html


def test_html_e_byte_stabile_e_non_ha_timestamp_o_tag_caricabili():
    """Un render ripetuto non deve cambiare né introdurre superfici di rete."""
    analysis = make_analysis()

    first = render_analysis(analysis, format="html")
    second = render_analysis(analysis, format="html")

    assert first == second
    assert "timestamp" not in first.lower()
    for tag in ("<script", "<link", "<img", "<iframe", "<object", "<embed"):
        assert tag not in first.lower()


def test_output_non_puo_sovrascrivere_input_anche_con_percorso_risolto(tmp_path: Path):
    """Un report non deve mai sovrascrivere il Blueprint scelto come input."""
    source = tmp_path / "blueprint.json"
    source.write_text("originale", encoding="utf-8")

    with pytest.raises(ValueError, match="input"):
        write_analysis(make_analysis(source_path=source), source / ".." / source.name, format="json")

    assert source.read_text(encoding="utf-8") == "originale"


def test_output_non_puo_raggiungere_input_attraverso_symlink(tmp_path: Path):
    """Una destinazione equivalente via symlink non deve aggirare la protezione I/O."""
    source = tmp_path / "blueprint.json"
    alias = tmp_path / "alias.json"
    source.write_text("originale", encoding="utf-8")
    try:
        alias.symlink_to(source)
    except OSError as exc:
        pytest.skip(f"Symlink non disponibile: {exc}")

    with pytest.raises(ValueError, match="input"):
        write_analysis(make_analysis(source_path=source), alias, format="json")

    assert source.read_text(encoding="utf-8") == "originale"


def test_write_crea_solo_il_genitore_scrive_utf8_e_non_muta_l_analisi(tmp_path: Path):
    """La scrittura al confine crea il solo parent e mantiene immutabili i dati del core."""
    analysis = make_analysis()
    destination = tmp_path / "reports" / "analysis.json"
    before = analysis.model_dump(mode="json", exclude={"source_path"})

    written = write_analysis(analysis, destination, format="json")

    assert written == destination.resolve()
    assert json.loads(written.read_text(encoding="utf-8"))["blueprint"]["goal"]["description"] == (
        "Preparare una nota verificabile."
    )
    assert analysis.model_dump(mode="json", exclude={"source_path"}) == before
    assert not (tmp_path / "reports" / "analysis.json" / "child").exists()


def test_errore_di_render_non_sovrascrive_una_destinazione_esistente(tmp_path: Path):
    """La validazione del formato deve avvenire prima di aprire il file di destinazione."""
    destination = tmp_path / "report.txt"
    destination.write_text("conserva", encoding="utf-8")

    with pytest.raises(ValueError, match="Formato"):
        write_analysis(make_analysis(), destination, format="invalido")

    assert destination.read_text(encoding="utf-8") == "conserva"


def test_formato_non_supportato_viene_rifiutato():
    """Accettare un nome non contrattuale produrrebbe artefatti ambigui."""
    with pytest.raises(ValueError, match="Formato"):
        render_analysis(make_analysis(), format="pdf")  # type: ignore[arg-type]


def test_preflight_analysis_e_frozen_extra_forbid():
    """Dati analizzati mutabili o impliciti spezzerebbero riproducibilità e confine I/O."""
    analysis = make_analysis()

    with pytest.raises(Exception):
        analysis.source_path = Path("altro.json")  # type: ignore[misc]
    with pytest.raises(ValueError):
        PreflightAnalysis(
            blueprint=analysis.blueprint,
            findings=analysis.findings,
            simulation=analysis.simulation,
            comparison=analysis.comparison,
            source_path=None,
            extra="vietato",
        )


def test_markdown_neutralizza_payload_ostili_in_tutti_i_campi_dinamici():
    """Dati non fidati non devono creare Markdown attivo, HTML o righe di tabella aggiuntive."""
    hostile = "[link](https://evil.test) ![image](https://evil.test/i) <img src=x> | cell\n```fence```"
    analysis = make_analysis(goal=hostile, assumption=hostile, finding_message=hostile)
    hostile_currency = analysis.simulation.typical.model_copy(update={"currency": hostile})
    hostile_simulation = analysis.simulation.model_copy(update={"typical": hostile_currency})
    hostile_comparison = analysis.comparison.model_copy(
        update={"before_blueprint_hash": hostile}
    )
    analysis = analysis.model_copy(
        update={"simulation": hostile_simulation, "comparison": hostile_comparison}
    )

    markdown = render_analysis(analysis, format="markdown")

    assert "<img src=x>" not in markdown
    assert "| cell\n" not in markdown
    assert "\n```fence```" not in markdown
    assert "\\[link\\]\\(https://evil.test\\)" in markdown
    assert "\\!\\[image\\]\\(https://evil.test/i\\)" in markdown
    assert "&lt;img src=x&gt;" in markdown
    assert markdown.count("| Scenario |") == 1


@pytest.mark.parametrize("format", ["markdown", "html"])
def test_report_umano_mostra_dettagli_findings_e_audit_stime(format: str):
    """Rilievi incompleti o stime senza provenienza impedirebbero un audit del preventivo."""
    output = render_analysis(make_analysis(), format=format)  # type: ignore[arg-type]

    for value in (
        "test",
        "Rilievo",
        "amount",
        "nodes/draft",
        "Riduci il contesto.",
        "deterministic",
        "instructions",
        "min",
        "typical",
        "max",
        "declared",
        "high",
    ):
        assert value in output


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_scrittura_atomica_non_tocca_destinazione_ne_lascia_temporanei(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
):
    """Un errore nell'ultimo miglio non deve troncare il report precedente né lasciare file temp."""
    destination = tmp_path / "report.json"
    destination.write_text("precedente", encoding="utf-8")
    if failure == "replace":
        monkeypatch.setattr(
            preflight_report.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("replace fallito")),
        )
    else:
        monkeypatch.setattr(
            preflight_report.os,
            "fsync",
            lambda _descriptor: (_ for _ in ()).throw(OSError("fsync fallito")),
        )

    with pytest.raises(OSError, match=failure):
        write_analysis(make_analysis(), destination, format="json")

    assert destination.read_text(encoding="utf-8") == "precedente"
    assert tuple(path.name for path in tmp_path.iterdir()) == ("report.json",)
