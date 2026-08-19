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
            # Il README e' in italiano dal 19/08/2026: i marcatori sono quelli.
            assert "non ancora" in contesto or "non supportat" in contesto, (
                "%s compare senza dire che non e' supportato" % nome
            )


def test_readme_links_the_public_project_docs():
    readme = Path("README.md").read_text(encoding="utf-8")

    for nome in ("SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md"):
        assert nome in readme


def test_il_readme_dichiara_la_superficie_supportata_del_confronto():
    """Il rovescio di `test_il_readme_dichiara_gli_harness_supportati`: un README che
    promette meno di quanto il codice fa e' una funzione che nessuno trova. `AGENTS.md` e
    `CHANGELOG.md` erano stati aggiornati e il README no, quindi un visitatore del
    repository pubblico non poteva scoprire ne' il comando ne' i tre tool MCP."""
    readme = Path("README.md").read_text(encoding="utf-8")

    for atteso in (
        "starkeno consuntivo",
        "blueprint_run_start", "blueprint_run_node", "blueprint_run_end",
        "--elenco", "--run", "--json",
    ):
        assert atteso in readme, "il README non nomina %s" % atteso


@pytest.mark.parametrize("nome", ["bug.yml", "feature.yml"])
def test_issue_forms_are_valid_and_require_privacy_confirmation(nome):
    form = yaml.safe_load(
        Path(".github/ISSUE_TEMPLATE", nome).read_text(encoding="utf-8")
    )

    assert form["name"] and form["description"]
    assert any(blocco.get("id") == "privacy" for blocco in form["body"])


# ============================ le due lingue del README non devono divergere
#
# Questo progetto ha gia' pagato DUE volte per due copie di una regola che divergono, e la
# skill esiste in doppia copia solo perche' un test le tiene identiche. README.md e
# README.en.md sono la stessa trappola in forma nuova: non si possono confrontare byte per
# byte, quindi si confronta cio' che una traduzione non ha il diritto di cambiare.

def _readme_it() -> str:
    return Path("README.md").read_text(encoding="utf-8")


def _readme_en() -> str:
    return Path("README.en.md").read_text(encoding="utf-8")


def _intestazioni(testo: str) -> int:
    return sum(1 for riga in testo.splitlines() if riga.startswith(("## ", "### ")))


def _blocchi_codice(testo: str) -> int:
    return sum(1 for riga in testo.splitlines() if riga.startswith("```"))


def test_le_due_lingue_del_readme_si_rimandano():
    """Una traduzione che non si annuncia e' una traduzione che nessuno trova, e la
    versione italiana resta quella autoritativa: va detto, non lasciato dedurre."""
    assert "README.en.md" in _readme_it(), "l'italiano non rimanda all'inglese"
    assert "README.md" in _readme_en(), "l'inglese non rimanda all'italiano"


def test_le_due_lingue_del_readme_hanno_la_stessa_struttura():
    """La deriva realistica non e' una parola tradotta male: e' una SEZIONE aggiunta a una
    sola delle due, che rende la traduzione una promessa diversa dall'originale."""
    it, en = _intestazioni(_readme_it()), _intestazioni(_readme_en())
    assert it == en, (
        "README.md ha %d intestazioni e README.en.md ne ha %d: una sezione e' stata "
        "aggiunta o tolta da una sola delle due" % (it, en)
    )


def test_le_due_lingue_del_readme_danno_gli_stessi_comandi():
    """I comandi non sono prosa e non si traducono. Un'installazione che diverge fra le
    due pagine manda meta' dei lettori contro un comando che non esiste."""
    it, en = _readme_it(), _readme_en()

    for comando in (
        "pip install git+https://github.com/X3n0-io/starkeno.git",
        "claude plugin marketplace add X3n0-io/starkeno",
        "claude plugin install starkeno@starkeno-local",
        "starkeno doctor",
        "starkeno consuntivo --elenco",
    ):
        assert comando in it, "manca da README.md: %s" % comando
        assert comando in en, "manca da README.en.md: %s" % comando

    assert _blocchi_codice(it) == _blocchi_codice(en), (
        "le due pagine non hanno lo stesso numero di blocchi di codice"
    )


def test_la_versione_inglese_avverte_che_il_prodotto_e_in_italiano():
    """Il difetto che questa pagina rischiava di reintrodurre: un lettore inglese che
    installa e scopre un conto in italiano. E' la stessa incoerenza appena sanata, solo
    rivolta all'altro pubblico."""
    assert "speaks Italian" in _readme_en(), (
        "README.en.md non avverte che l'output dello strumento e' in italiano"
    )
