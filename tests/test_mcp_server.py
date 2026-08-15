import json
from pathlib import Path

from starkeno.db import get_agent_summaries
import starkeno.mcp_server as mcp_server_module
from starkeno.mcp_server import log_agent_action_impl
from starkeno.preflight_interpret import interpretation_task
from starkeno.preflight_schema import load_blueprint


FIXTURE_PREFLIGHT = Path(__file__).parent / "fixtures" / "preflight" / "minimal.json"


def _interpretazione_valida(**modifiche) -> str:
    """Una risposta d'agente ben formata, modificabile per rompere un pezzo solo.

    Stesso spirito di `_interpretazione` in `test_preflight_interpret.py`, ma definita
    qui: nessun file di test in questo repository importa helper da un altro (vedi
    `test_preflight_cli.py`, che carica `FIXTURE` per conto proprio)."""
    blueprint = json.loads(FIXTURE_PREFLIGHT.read_text(encoding="utf-8"))
    blueprint.update(modifiche)
    return json.dumps({
        "blueprint": blueprint,
        "assumptions": ["Il revisore e' una persona."],
        "open_questions": ["Quante modifiche entrano di solito nella nota?"],
    })


def test_log_agent_action_impl_records_to_db(session_factory, monkeypatch):
    test_session_factory = session_factory
    monkeypatch.setattr(mcp_server_module, "get_session_factory", lambda: test_session_factory)

    result = log_agent_action_impl(
        project="scraper",
        action="fetch_page",
        model_used="claude-haiku-4-5",
        tokens_used=150,
    )

    assert "scraper" in result
    assert "150" in result

    session = test_session_factory()
    summaries = get_agent_summaries(session)
    assert summaries == [{
        "project": "scraper", "total_tokens": 150, "action_count": 1,
        "total_effective_tokens": 150,
    }]
    session.close()


# ==================================================== porta d'ingresso Preflight
#
# StarkEno non chiama alcun modello: l'agente che l'utente sta gia' usando (Claude
# Code, Codex, ...) legge `preflight_interpretation_task`, produce da solo il JSON
# dell'Interpretation, e lo passa a `preflight_save_draft`. Stesso pattern di
# `log_agent_action`: un `_impl` provabile senza MCP, un tool decorato che delega.


def test_preflight_interpretation_task_impl_delega_a_interpretation_task():
    testo = "un agente scrive una nota di rilascio"
    assert (
        mcp_server_module.preflight_interpretation_task_impl(testo)
        == interpretation_task(testo)
    )


def test_preflight_interpretation_task_docstring_dice_di_produrre_solo_json_e_passarlo_a_save_draft():
    """La docstring e' l'interfaccia per l'agente: deve dirgli cosa fare col compito."""
    documentazione = mcp_server_module.preflight_interpretation_task.__doc__ or ""

    assert "preflight_save_draft" in documentazione, "non dice a chi passare il JSON"
    assert "JSON" in documentazione
    assert "only" in documentazione.lower(), "non dice che va prodotto SOLO il JSON"


def test_preflight_save_draft_impl_un_json_valido_salva_un_draft_non_confermato(tmp_path):
    output = tmp_path / "draft.json"

    risposta = mcp_server_module.preflight_save_draft_impl(
        _interpretazione_valida(), str(output)
    )

    salvato = load_blueprint(output.read_text(encoding="utf-8"), format_hint="json")
    assert salvato.confirmed is False
    assert str(output) in risposta
    assert "Il revisore e' una persona." in risposta, "mancano le assumptions"
    assert "Quante modifiche entrano di solito nella nota?" in risposta, "mancano le open_questions"
    assert "--confirmed" in risposta, "non dice che il Draft resta da confermare"


def test_preflight_save_draft_impl_supporta_yaml(tmp_path):
    output = tmp_path / "draft.yaml"

    mcp_server_module.preflight_save_draft_impl(
        _interpretazione_valida(), str(output), format="yaml"
    )

    salvato = load_blueprint(output.read_text(encoding="utf-8"), format_hint="yaml")
    assert salvato.confirmed is False


def test_preflight_save_draft_impl_un_json_rotto_non_solleva_e_non_lascia_file(tmp_path):
    """`{non e' json` non e' JSON valido: nessuna eccezione deve attraversare il tool."""
    output = tmp_path / "draft.json"

    risposta = mcp_server_module.preflight_save_draft_impl("{non e' json", str(output))

    assert isinstance(risposta, str) and risposta
    assert not output.exists()


def test_preflight_save_draft_impl_un_riferimento_rotto_produce_un_errore_leggibile(tmp_path):
    rotto = json.loads(FIXTURE_PREFLIGHT.read_text(encoding="utf-8"))
    rotto["nodes"][0]["agent_id"] = "fantasma"
    payload = json.dumps({"blueprint": rotto, "assumptions": [], "open_questions": []})
    output = tmp_path / "draft.json"

    risposta = mcp_server_module.preflight_save_draft_impl(payload, str(output))

    assert "fantasma" in risposta
    assert "inesistente" in risposta
    assert not output.exists()


def test_preflight_save_draft_impl_un_provenance_measured_viene_rifiutato_anche_da_qui(tmp_path):
    """La garanzia del Task 3 (niente `measured` inventato) non si aggira entrando
    dal lato MCP invece che da `interpret_text`."""
    bugiardo = json.loads(FIXTURE_PREFLIGHT.read_text(encoding="utf-8"))
    bugiardo["nodes"][0]["budget"]["output"]["provenance"] = "measured"
    payload = json.dumps({"blueprint": bugiardo, "assumptions": [], "open_questions": []})
    output = tmp_path / "draft.json"

    risposta = mcp_server_module.preflight_save_draft_impl(payload, str(output))

    assert "measured" in risposta
    assert not output.exists()


def test_preflight_save_draft_impl_un_formato_ignoto_non_solleva(tmp_path):
    output = tmp_path / "draft.txt"

    risposta = mcp_server_module.preflight_save_draft_impl(
        _interpretazione_valida(), str(output), format="xml"
    )

    assert isinstance(risposta, str) and risposta
    assert not output.exists()


def test_preflight_save_draft_impl_non_tocca_il_database(tmp_path, monkeypatch):
    """Preflight e' offline: nessuno dei due tool deve chiamare `get_session_factory`."""
    def esplode():
        raise AssertionError("preflight_save_draft non deve toccare il database")

    monkeypatch.setattr(mcp_server_module, "get_session_factory", esplode)

    output = tmp_path / "draft.json"
    risposta = mcp_server_module.preflight_save_draft_impl(
        _interpretazione_valida(), str(output)
    )

    assert output.exists()
    assert "Draft" in risposta or str(output) in risposta


def test_preflight_save_draft_docstring_dice_cosa_fare_con_un_errore():
    """Tre proprieta' che il chiamante non puo' verificare da solo: che il tool non
    solleva, che l'errore torna come testo da correggere, e che si riprova."""
    documentazione = mcp_server_module.preflight_save_draft.__doc__ or ""

    assert "does not raise" in documentazione.lower(), "non dichiara il contratto di non sollevare"
    assert "again" in documentazione.lower(), "non dice di riprovare"
    assert "--confirmed" in documentazione, "non dice che il Draft resta da confermare"
