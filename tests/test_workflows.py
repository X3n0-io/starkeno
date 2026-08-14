from pathlib import Path

import yaml


def _workflow(nome):
    return yaml.safe_load(
        Path(".github/workflows", nome).read_text(encoding="utf-8")
    )


def test_ci_covers_supported_os_and_python_versions():
    ci = _workflow("ci.yml")
    matrice = ci["jobs"]["tests"]["strategy"]["matrix"]

    assert set(matrice["os"]) == {
        "ubuntu-latest", "windows-latest", "macos-latest",
    }
    assert set(map(str, matrice["python"])) == {"3.12", "3.13", "3.14"}
    comando = "\n".join(
        step.get("run", "") for step in ci["jobs"]["tests"]["steps"]
    )
    assert "pytest -q -W error" in comando


def test_ci_has_stable_package_and_audit_jobs_with_real_smoke_commands():
    ci = _workflow("ci.yml")

    assert {"tests", "package", "audit"} <= set(ci["jobs"])
    package = "\n".join(
        step.get("run", "") for step in ci["jobs"]["package"]["steps"]
    )
    audit = "\n".join(
        step.get("run", "") for step in ci["jobs"]["audit"]["steps"]
    )
    assert "python -m build" in package
    assert "starkeno doctor --json" in package
    assert "starkeno report" in package
    assert "pip_audit" in audit
    assert "verifica_segreti.py --tracked" in audit
    assert "verifica_pubblicazione.py" in audit
    assert "git diff --exit-code -- requirements/ci.txt" in audit


def test_stress_runs_on_windows_and_linux():
    workflow = _workflow("stress.yml")

    assert set(workflow["jobs"]["stress"]["strategy"]["matrix"]["os"]) == {
        "ubuntu-latest", "windows-latest",
    }
