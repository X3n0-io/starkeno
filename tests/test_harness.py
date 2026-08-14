"""Il registro degli harness: identita' e riconoscimento, senza lettura."""
from starkeno import harness


def test_riconosce_codex_dalla_prima_voce():
    assert harness.riconosci({"type": "session_meta"}).nome == "codex"
    assert harness.riconosci({"type": "turn_context"}).nome == "codex"


def test_riconosce_claude_code_dal_messaggio():
    voce = {"sessionId": "s1", "message": {"id": "m1", "usage": {}}}
    assert harness.riconosci(voce).nome == "claude-code"


def test_antigravity_e_riconosciuto_ma_non_misurabile():
    """Riconosciuto SERVE: senza, l'utente vede zero e sospetta un difetto.

    Il suo transcript ha `step_index` e `created_at` e non ha `message`.
    """
    voce = {"type": "PLANNER_RESPONSE", "step_index": 0, "created_at": "2026-08-14",
            "source": "agent", "status": "done"}
    trovato = harness.riconosci(voce)
    assert trovato.nome == "antigravity"
    assert trovato.misurabile is False
    assert "token" in trovato.motivo.lower()


def test_un_formato_ignoto_ricade_su_claude_code():
    """La ricaduta e' deliberata: vedi `_e_claude_code`. Che non produca chiamate lo
    prova il Task 2, non questo test."""
    assert harness.riconosci({"pippo": 1}).nome == "claude-code"


def test_ogni_harness_misurabile_dichiara_un_lettore():
    for h in harness.REGISTRO:
        if h.misurabile:
            assert h.lettore, "%s e' misurabile ma non dice con cosa leggerlo" % h.nome
        else:
            assert h.motivo, "%s non e' misurabile e non dice perche'" % h.nome


def test_i_nomi_sono_unici():
    nomi = [h.nome for h in harness.REGISTRO]
    assert len(nomi) == len(set(nomi))
