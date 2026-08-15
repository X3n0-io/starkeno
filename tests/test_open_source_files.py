from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("path", [
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "CHANGELOG.md",
    ".gitattributes",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml",
    ".github/pull_request_template.md",
    "docs/releasing.md",
])
def test_required_open_source_file_exists(path):
    assert Path(path).is_file()


def test_security_and_contributing_docs_contain_actionable_contracts():
    security = Path("SECURITY.md").read_text(encoding="utf-8")
    contributing = Path("CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "0.3.x" in security
    assert "Report a vulnerability" in security
    assert "transcript" in security.lower()
    assert "pytest -q -W error" in contributing
    assert "Alembic" in contributing


def test_il_readme_dichiara_gli_harness_supportati():
    """Un README che promette piu' di quanto il codice misura e' una bugia lenta."""
    testo = Path("README.md").read_text(encoding="utf-8")

    for atteso in ("Codex", "Claude Code", "Antigravity"):
        assert atteso in testo, "il README non nomina %s" % atteso
    assert "MIT" in testo


def test_il_readme_non_promette_gli_harness_non_supportati():
    """Cursor, OpenCode e OpenClaw restano fuori finche' non esiste un transcript vero
    da cui leggerne lo schema: nominarli come supportati sarebbe una promessa."""
    testo = Path("README.md").read_text(encoding="utf-8")

    for nome in ("Cursor", "OpenCode", "OpenClaw"):
        if nome in testo:
            posizione = testo.index(nome)
            contesto = testo[max(0, posizione - 200):posizione + 200].lower()
            assert "not yet" in contesto or "not supported" in contesto, (
                "%s compare senza dire che non e' supportato" % nome
            )


def test_readme_links_the_public_project_docs():
    readme = Path("README.md").read_text(encoding="utf-8")

    for nome in ("SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md"):
        assert nome in readme


@pytest.mark.parametrize("nome", ["bug.yml", "feature.yml"])
def test_issue_forms_are_valid_and_require_privacy_confirmation(nome):
    form = yaml.safe_load(
        Path(".github/ISSUE_TEMPLATE", nome).read_text(encoding="utf-8")
    )

    assert form["name"] and form["description"]
    assert any(blocco.get("id") == "privacy" for blocco in form["body"])
