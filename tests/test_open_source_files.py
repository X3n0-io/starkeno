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
