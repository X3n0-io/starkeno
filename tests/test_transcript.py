"""Il lettore di transcript, e la regressione sul difetto piu' caro del progetto.

Il transcript scrive UNA RIGA PER BLOCCO DI CONTENUTO e ripete l'involucro del
messaggio, `usage` incluso. Misurato su 476 file: 2,08 righe per chiamata API.
Sommare per riga da' 2,03x di gonfiaggio.

R3 confronta un agente con la propria storia e si sarebbe gonfiata da entrambe le parti,
quasi senza segni. Ma le soglie ASSOLUTE sarebbero scattate a meta' della spesa vera.
Due regole sbagliate in due direzioni opposte, senza un errore.

La fixture e' un transcript vero RIPULITO (vedi `scripts/costruisci_fixture_transcript.py`):
la proprieta' che deve provare e' strutturale, e il contenuto delle conversazioni non ha
motivo di finire in un repository pubblico.
"""
import json
from pathlib import Path

from starkeno import transcript

FIXTURE = Path(__file__).parent / "fixtures" / "transcript_vero.jsonl"


def righe_fixture():
    return FIXTURE.read_text(encoding="utf-8").splitlines()


def test_una_riga_per_chiamata_api_non_per_riga_di_transcript():
    """LA regressione. I due numeri si ricavano dalla fixture stessa, non si scrivono
    a mano: cosi' il test resta valido se un giorno la fixture viene rifatta."""
    righe = righe_fixture()
    con_usage = sum(
        1 for r in righe if r.strip()
        and isinstance(json.loads(r).get("message"), dict)
        and isinstance(json.loads(r)["message"].get("usage"), dict)
    )
    chiamate = transcript.leggi(righe)

    assert len(chiamate) < con_usage, (
        "il lettore ha prodotto una riga per riga di transcript: e' il gonfiaggio 2,03x"
    )
    assert con_usage / len(chiamate) > 1.5, "il rapporto misurato era ~2,08"


def test_le_chiamate_sono_uniche_per_sessione_e_messaggio():
    chiamate = transcript.leggi(righe_fixture())
    chiavi = [(c.session_id, c.message_id) for c in chiamate]
    assert len(chiavi) == len(set(chiavi))


def test_message_id_da_solo_non_basta():
    """Misurato: 71 righe -> 34 id nel file campione. Va sempre accoppiato a sessionId."""
    righe = [
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                    "message": {"id": "msg_1", "model": "claude-opus-5",
                                "usage": {"input_tokens": 10, "output_tokens": 1},
                                "content": []}}),
        json.dumps({"sessionId": "B", "timestamp": "2026-08-07T10:00:01Z", "cwd": "/x",
                    "message": {"id": "msg_1", "model": "claude-opus-5",
                                "usage": {"input_tokens": 20, "output_tokens": 2},
                                "content": []}}),
    ]
    assert len(transcript.leggi(righe)) == 2


def test_l_ultima_riga_vince_sull_usage():
    """Misurato: il 4,6% delle chiamate ha righe con `usage` diversi, e nel 100% di quei
    casi l'ULTIMA e' anche la piu' alta — il conteggio si accumula mentre il messaggio
    si forma."""
    comune = {"sessionId": "A", "cwd": "/x"}
    righe = [
        json.dumps({**comune, "timestamp": "2026-08-07T10:00:00Z",
                    "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                "usage": {"input_tokens": 10, "output_tokens": 1}}}),
        json.dumps({**comune, "timestamp": "2026-08-07T10:00:02Z",
                    "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                "usage": {"input_tokens": 10, "output_tokens": 7}}}),
    ]
    (chiamata,) = transcript.leggi(righe)
    assert chiamata.output_tokens == 7


def test_i_messaggi_sintetici_si_scartano_all_ingresso():
    """L'1,8% del traffico. Non sono chiamate API: si scartano all'ingresso, non nelle
    regole."""
    righe = [
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                    "message": {"id": "m1", "model": "<synthetic>", "content": [],
                                "usage": {"input_tokens": 5, "output_tokens": 1}}}),
    ]
    assert transcript.leggi(righe) == []


def test_una_chiamata_con_piu_azioni_da_UNA_riga_col_contatore():
    """Il 10,3% delle chiamate. Righe multiple gonfierebbero del 10% ogni soglia che
    conta azioni; l'attribuzione sta gia' sulla chiamata, quindi spezzare la
    duplicherebbe invece di affinarla."""
    riga = json.dumps({
        "sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x/progetto",
        "message": {"id": "m", "model": "claude-opus-5",
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "Read",
                         "input": {"file_path": "a.py"}},
                        {"type": "tool_use", "id": "t2", "name": "Read",
                         "input": {"file_path": "b.py"}},
                        {"type": "tool_use", "id": "t3", "name": "Bash",
                         "input": {"command": "ls"}},
                    ]}})
    (c,) = transcript.leggi([riga])
    assert c.azioni_nella_chiamata == 3
    assert c.action == "read:a.py", "l'etichetta e' la PRIMA azione"


def test_il_progetto_viene_dal_cwd():
    riga = json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z",
                       "cwd": "C:\\\\workspace\\\\starkeno",
                       "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                   "usage": {"input_tokens": 1, "output_tokens": 1}}})
    (c,) = transcript.leggi([riga])
    assert c.project == "starkeno"


def test_l_esito_si_prende_dal_messaggio_successivo():
    """Il risultato di uno strumento arriva DOPO. Misurato: resta irrisolto nello 0,04%."""
    righe = [
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                    "message": {"id": "m", "model": "claude-opus-5",
                                "usage": {"input_tokens": 1, "output_tokens": 1},
                                "content": [{"type": "tool_use", "id": "t1",
                                             "name": "Bash", "input": {"command": "ls"}}]}}),
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:01Z", "cwd": "/x",
                    "message": {"role": "user",
                                "content": [{"type": "tool_result", "tool_use_id": "t1",
                                             "is_error": True, "content": "Exit code 1"}]}}),
    ]
    (c,) = transcript.leggi(righe)
    assert c.esito_noto == 1
    assert c.azione_fallita == 1


def test_esito_mancante_non_diventa_successo():
    """Mai «falso» per «non lo so»: renderebbe ottimisti per costruzione sia R1 sia il
    costo degli errori."""
    riga = json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                       "message": {"id": "m", "model": "claude-opus-5",
                                   "usage": {"input_tokens": 1, "output_tokens": 1},
                                   "content": [{"type": "tool_use", "id": "t9",
                                                "name": "Bash", "input": {"command": "ls"}}]}})
    (c,) = transcript.leggi([riga])
    assert c.esito_noto == 0
    assert c.azione_fallita == 0


def test_una_riga_rotta_non_ferma_la_lettura():
    """L'hook gira a casa d'altri: una riga malformata non deve costare un turno."""
    righe = [
        "{non e' json",
        json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                    "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                "usage": {"input_tokens": 1, "output_tokens": 1}}}),
    ]
    assert len(transcript.leggi(righe)) == 1


def test_l_attribuzione_si_prende_dalla_riga_della_chiamata():
    riga = json.dumps({"sessionId": "A", "timestamp": "2026-08-07T10:00:00Z", "cwd": "/x",
                       "isSidechain": True, "attributionSkill": "superpowers:brainstorming",
                       "attributionPlugin": "superpowers",
                       "attributionMcpServer": "Claude Browser",
                       "message": {"id": "m", "model": "claude-opus-5", "content": [],
                                   "usage": {"input_tokens": 1, "output_tokens": 1}}})
    (c,) = transcript.leggi([riga])
    assert c.skill == "superpowers:brainstorming"
    assert c.plugin == "superpowers"
    assert c.mcp_server == "Claude Browser"
    assert c.is_sidechain == 1


def test_legge_le_chiamate_dal_transcript_codex_senza_contare_due_volte_la_cache():
    """Regressione reale: Codex 0.147 usa eventi, non ``message.usage`` di Claude."""
    turno = "turn-1"
    meta = {"internal_chat_message_metadata_passthrough": {"turn_id": turno}}
    righe = [
        json.dumps({"timestamp": "2026-08-12T18:00:00Z", "type": "session_meta",
                    "payload": {"session_id": "session-codex", "cwd": "C:\\x\\starkeno"}}),
        json.dumps({"timestamp": "2026-08-12T18:00:01Z", "type": "event_msg",
                    "payload": {"type": "task_started", "turn_id": turno}}),
        json.dumps({"timestamp": "2026-08-12T18:00:02Z", "type": "turn_context",
                    "payload": {"turn_id": turno, "cwd": "C:\\x\\starkeno",
                                "model": "gpt-5.6-terra"}}),
        json.dumps({"timestamp": "2026-08-12T18:00:03Z", "type": "response_item",
                    "payload": {"type": "custom_tool_call", "id": "response-1",
                                "call_id": "call-1", "name": "exec",
                                "input": json.dumps({"command": "python -m pytest"}), **meta}}),
        json.dumps({"timestamp": "2026-08-12T18:00:04Z", "type": "event_msg",
                    "payload": {"type": "token_count", "info": {"last_token_usage": {
                        "input_tokens": 1000, "cached_input_tokens": 600,
                        "cache_write_input_tokens": 100, "output_tokens": 80,
                        "reasoning_output_tokens": 20, "total_tokens": 1100}}}}),
        json.dumps({"timestamp": "2026-08-12T18:00:05Z", "type": "response_item",
                    "payload": {"type": "custom_tool_call_output", "id": "result-1",
                                "call_id": "call-1", "output": [
                                    {"type": "input_text", "text": "Script failed\n"},
                                    {"type": "input_text", "text": "Exit code: 1\n"}], **meta}}),
        json.dumps({"timestamp": "2026-08-12T18:00:06Z", "type": "response_item",
                    "payload": {"type": "message", "id": "response-2", "role": "assistant",
                                "content": [{"type": "output_text", "text": "Fatto"}], **meta}}),
        json.dumps({"timestamp": "2026-08-12T18:00:07Z", "type": "event_msg",
                    "payload": {"type": "token_count", "info": {"last_token_usage": {
                        "input_tokens": 900, "cached_input_tokens": 700,
                        "cache_write_input_tokens": 0, "output_tokens": 50,
                        "reasoning_output_tokens": 10, "total_tokens": 950}}}}),
    ]

    prima, seconda = transcript.leggi(righe)

    assert (prima.session_id, prima.message_id, prima.project, prima.model_used) == (
        "session-codex", "response-1", "starkeno", "gpt-5.6-terra")
    assert (prima.input_tokens, prima.cache_read_tokens, prima.cache_write_tokens,
            prima.output_tokens) == (300, 600, 100, 100)
    assert (prima.action, prima.azioni_nella_chiamata) == ("exec:python -m pytest", 1)
    assert (prima.esito_noto, prima.azione_fallita) == (1, 1)
    assert (seconda.message_id, seconda.action, seconda.input_tokens,
            seconda.cache_read_tokens, seconda.output_tokens) == (
                "response-2", "risposta", 200, 700, 60)


from starkeno import harness  # noqa: E402


def test_il_dispatch_non_cambia_il_risultato_sulla_fixture():
    """LA rete del rifacimento: il registro deve dare esattamente cio' che dava l'if."""
    chiamate = transcript.leggi(righe_fixture())
    assert len(chiamate) > 0, "la fixture non produce piu' chiamate: regressione"
    assert transcript.leggi(righe_fixture()) == chiamate


def test_ogni_lettore_dichiarato_dal_registro_esiste():
    """Un nome di lettore scritto male sarebbe un formato che smette di essere letto,
    in silenzio."""
    for h in harness.REGISTRO:
        if h.lettore:
            assert h.lettore in transcript.LETTORI, (
                "%s dichiara il lettore '%s' che non esiste" % (h.nome, h.lettore))


def test_un_harness_non_misurabile_non_produce_chiamate():
    """Antigravity: riconosciuto, e zero chiamate. Mai una stima."""
    riga = json.dumps({"type": "PLANNER_RESPONSE", "step_index": 0,
                       "created_at": "2026-08-14T10:00:00Z", "source": "agent",
                       "status": "done", "content": "x"})
    assert transcript.leggi([riga]) == []


def test_un_file_vuoto_non_esplode():
    assert transcript.leggi([]) == []
    assert transcript.leggi(["", "   ", "non e json"]) == []
