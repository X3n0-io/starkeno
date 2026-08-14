"""Da un transcript di Codex o Claude Code alle chiamate API che contiene.

**Modulo puro:** niente database, niente orologio, niente variabili d'ambiente. Prende
righe di testo e restituisce dati. E' cosi' che la regressione sul doppio conteggio si
prova in memoria, senza toccare il disco.

Per Claude la grana e' `(sessionId, message.id)`; per Codex e'
`(session_id, response_item.id)`. In entrambi i casi e' la chiave di idempotenza e mai
la singola riga del file.
"""
import json
import re
from dataclasses import dataclass
from itertools import chain

# Il parametro che identifica un'azione, in ordine di preferenza. Il primo che c'e' vince.
CHIAVI_DETTAGLIO = (
    "file_path", "path", "notebook_path", "pattern", "command", "url",
    "query", "prompt", "skill", "subagent_type", "file", "filePath",
)

MODELLO_SINTETICO = "<synthetic>"
LUNGHEZZA_MASSIMA_DETTAGLIO = 300


@dataclass(frozen=True)
class Chiamata:
    """Una chiamata API, cioe' UNA riga di `agent_actions`."""

    session_id: str
    message_id: str
    timestamp: str          # ISO 8601 come lo scrive il transcript. Chi scrive converte.
    project: str
    action: str
    model_used: str
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    azione_fallita: int
    esito_noto: int
    azioni_nella_chiamata: int
    skill: str
    plugin: str
    mcp_server: str
    is_sidechain: int

    @property
    def tokens_used(self) -> int:
        """Il totale, cache read inclusi: e' la misura di «quanto e' grosso il task»."""
        return (self.input_tokens + self.cache_read_tokens
                + self.cache_write_tokens + self.output_tokens)


def _dettaglio(parametri) -> str | None:
    if not isinstance(parametri, dict):
        return None
    for chiave in CHIAVI_DETTAGLIO:
        valore = parametri.get(chiave)
        if isinstance(valore, str) and valore.strip():
            return valore.strip()[:LUNGHEZZA_MASSIMA_DETTAGLIO]
    return None


def _progetto(cwd: str) -> str:
    """L'ultimo segmento del percorso di lavoro.

    L'utente in locale e' una costante e non distingue niente; il progetto si'.
    Misurato: 30 progetti distinti sul traffico reale.
    """
    ripulito = (cwd or "").rstrip("\\/").replace("/", "\\")
    return ripulito.split("\\")[-1] or "?"


def _parametri_codex(valore):
    if isinstance(valore, dict):
        return valore
    if isinstance(valore, str):
        try:
            decodificato = json.loads(valore)
        except Exception:
            return {}
        return decodificato if isinstance(decodificato, dict) else {}
    return {}


def _esito_codex(output) -> tuple[int, int]:
    """Un output presente rende noto l'esito; gli errori espliciti restano errori."""
    testi = []
    if isinstance(output, str):
        testi.append(output)
    elif isinstance(output, list):
        testi.extend(
            blocco.get("text", "") for blocco in output
            if isinstance(blocco, dict) and isinstance(blocco.get("text"), str)
        )
    elif isinstance(output, dict):
        if output.get("isError") or output.get("is_error"):
            return 1, 1
        testi.append(json.dumps(output))
    testo = "\n".join(testi)
    fallita = bool(
        "Script failed" in testo
        or re.search(r"Exit code:\s*(?!0(?:\D|$))\d+", testo)
        or '"isError":true' in testo.replace(" ", "")
        or '"is_error":true' in testo.replace(" ", "")
    )
    return 1, 1 if fallita else 0


def _leggi_codex(voci) -> list[Chiamata]:
    sessione = ""
    cwd_sessione = ""
    turno_corrente = ""
    contesti: dict[str, dict] = {}
    stati: dict[str, dict] = {}
    esiti: dict[str, tuple[int, int]] = {}
    grezze: dict[tuple[str, str], dict] = {}
    ordine: list[tuple[str, str]] = []

    for voce in voci:
        tipo = voce.get("type")
        payload = voce.get("payload")
        if not isinstance(payload, dict):
            continue
        sottotipo = payload.get("type")
        if tipo == "session_meta":
            sessione = payload.get("session_id") or payload.get("id") or sessione
            cwd_sessione = payload.get("cwd") or cwd_sessione
            continue
        if tipo == "event_msg" and sottotipo == "task_started":
            turno_corrente = payload.get("turn_id") or ""
            stati.setdefault(turno_corrente, {"strumenti": [], "ultimo_id": "",
                                              "timestamp": ""})
            continue
        if tipo == "turn_context":
            turno = payload.get("turn_id") or turno_corrente
            if turno:
                contesti[turno] = payload
            continue
        if tipo == "response_item":
            meta = payload.get("internal_chat_message_metadata_passthrough")
            turno = meta.get("turn_id") if isinstance(meta, dict) else turno_corrente
            if not turno:
                continue
            stato = stati.setdefault(turno, {"strumenti": [], "ultimo_id": "",
                                             "timestamp": ""})
            if sottotipo in {"custom_tool_call_output", "function_call_output"}:
                if payload.get("call_id"):
                    esiti[payload["call_id"]] = _esito_codex(payload.get("output"))
                continue
            generato = (
                sottotipo in {"reasoning", "custom_tool_call", "function_call"}
                or (sottotipo == "message" and payload.get("role") == "assistant")
            )
            if generato and payload.get("id"):
                stato["ultimo_id"] = payload["id"]
                stato["timestamp"] = stato["timestamp"] or voce.get("timestamp") or ""
            if sottotipo in {"custom_tool_call", "function_call"}:
                parametri = _parametri_codex(payload.get("input", payload.get("arguments")))
                nome = (payload.get("name") or "?").lower()
                dettaglio = _dettaglio(parametri)
                azione = "%s:%s" % (nome, dettaglio) if dettaglio else nome
                stato["strumenti"].append((azione, payload.get("call_id")))
            continue
        if tipo == "event_msg" and sottotipo == "token_count":
            turno = turno_corrente
            stato = stati.get(turno) or {}
            identificativo = stato.get("ultimo_id")
            info = payload.get("info")
            uso = info.get("last_token_usage") if isinstance(info, dict) else None
            if not (sessione and turno and identificativo and isinstance(uso, dict)):
                continue
            chiave = (sessione, identificativo)
            if chiave not in grezze:
                ordine.append(chiave)
            contesto = contesti.get(turno, {})
            ingresso_totale = int(uso.get("input_tokens") or 0)
            lettura = int(uso.get("cached_input_tokens") or 0)
            scrittura = int(uso.get("cache_write_input_tokens") or 0)
            strumenti = list(stato.get("strumenti") or [])
            grezze[chiave] = {
                "timestamp": stato.get("timestamp") or voce.get("timestamp") or "",
                "project": _progetto(contesto.get("cwd") or cwd_sessione),
                "model_used": contesto.get("model") or "",
                "strumenti": strumenti,
                "usage": (max(0, ingresso_totale - lettura - scrittura), lettura,
                          scrittura, int(uso.get("output_tokens") or 0)
                          + int(uso.get("reasoning_output_tokens") or 0)),
            }
            stato["strumenti"] = []
            stato["ultimo_id"] = ""
            stato["timestamp"] = ""
            continue
        if tipo == "event_msg" and sottotipo in {"task_complete", "turn_aborted"}:
            turno_corrente = ""

    chiamate = []
    for chiave in ordine:
        record = grezze[chiave]
        strumenti = record["strumenti"]
        azione, chiamata_strumento = strumenti[0] if strumenti else ("risposta", None)
        noto, fallita = esiti.get(chiamata_strumento, (1, 0) if not strumenti else (0, 0))
        ingresso, lettura, scrittura, uscita = record["usage"]
        chiamate.append(Chiamata(
            session_id=chiave[0], message_id=chiave[1], timestamp=record["timestamp"],
            project=record["project"], action=azione, model_used=record["model_used"],
            input_tokens=ingresso, cache_read_tokens=lettura,
            cache_write_tokens=scrittura, output_tokens=uscita,
            azione_fallita=fallita, esito_noto=noto,
            azioni_nella_chiamata=max(1, len(strumenti)), skill="", plugin="",
            mcp_server="", is_sidechain=0,
        ))
    return chiamate


def leggi(righe) -> list[Chiamata]:
    """Le chiamate API contenute in queste righe di transcript, in ordine di comparsa.

    Le righe malformate si saltano: questo codice gira a casa d'altri, e una riga rotta
    non deve costare un turno all'utente.
    """
    iteratore = iter(righe)
    prefisso = []
    prima_voce = None
    for riga in iteratore:
        prefisso.append(riga)
        try:
            voce = json.loads(riga.strip()) if isinstance(riga, str) else None
        except Exception:
            continue
        if isinstance(voce, dict):
            prima_voce = voce
            break
    righe = chain(prefisso, iteratore)
    if prima_voce and prima_voce.get("type") in {"session_meta", "turn_context"}:
        def voci_codex():
            for riga in righe:
                try:
                    voce = json.loads(riga.strip()) if isinstance(riga, str) else None
                except Exception:
                    continue
                if isinstance(voce, dict):
                    yield voce
        return _leggi_codex(voci_codex())

    grezze: dict[tuple[str, str], dict] = {}
    esiti: dict[str, bool] = {}
    ordine: list[tuple[str, str]] = []

    for riga in righe:
        riga = riga.strip() if isinstance(riga, str) else ""
        if not riga:
            continue
        try:
            voce = json.loads(riga)
        except Exception:
            continue
        if not isinstance(voce, dict):
            continue
        messaggio = voce.get("message")
        if not isinstance(messaggio, dict):
            continue
        contenuto = messaggio.get("content")

        # Gli esiti stanno nei messaggi dell'utente, e arrivano DOPO la chiamata che li
        # ha prodotti: si raccolgono in una passata sola e si riconciliano alla fine.
        if isinstance(contenuto, list):
            for blocco in contenuto:
                if (isinstance(blocco, dict) and blocco.get("type") == "tool_result"
                        and blocco.get("tool_use_id")):
                    esiti[blocco["tool_use_id"]] = bool(blocco.get("is_error"))

        uso = messaggio.get("usage")
        if not isinstance(uso, dict):
            continue
        modello = messaggio.get("model") or ""
        if modello == MODELLO_SINTETICO:
            # Non e' una chiamata API. Si scarta all'ingresso, non nelle regole.
            continue
        sessione, identificativo = voce.get("sessionId"), messaggio.get("id")
        if not sessione or not identificativo:
            continue

        strumenti = []
        if isinstance(contenuto, list):
            for blocco in contenuto:
                if isinstance(blocco, dict) and blocco.get("type") == "tool_use":
                    nome = (blocco.get("name") or "?").lower()
                    dettaglio = _dettaglio(blocco.get("input"))
                    strumenti.append((
                        "%s:%s" % (nome, dettaglio) if dettaglio else nome,
                        blocco.get("id"),
                    ))

        chiave = (sessione, identificativo)
        if chiave not in grezze:
            ordine.append(chiave)
            grezze[chiave] = {
                "timestamp": voce.get("timestamp") or "",
                "project": _progetto(voce.get("cwd")),
                "model_used": modello,
                "strumenti": [],
                "skill": voce.get("attributionSkill") or "",
                "plugin": voce.get("attributionPlugin") or "",
                "mcp_server": voce.get("attributionMcpServer") or "",
                "is_sidechain": 1 if voce.get("isSidechain") else 0,
            }
        record = grezze[chiave]
        record["strumenti"].extend(strumenti)
        # L'ULTIMA riga vince sull'usage: misurato, il conteggio si accumula mentre il
        # messaggio si forma, e nel 100% dei casi discordi l'ultima e' anche la piu' alta.
        record["usage"] = (
            int(uso.get("input_tokens") or 0),
            int(uso.get("cache_read_input_tokens") or 0),
            int(uso.get("cache_creation_input_tokens") or 0),
            int(uso.get("output_tokens") or 0),
        )
        # Il primo timestamp non nullo: le righe successive sono la stessa chiamata.
        if not record["timestamp"]:
            record["timestamp"] = voce.get("timestamp") or ""

    chiamate = []
    for sessione, identificativo in ordine:
        record = grezze[(sessione, identificativo)]
        strumenti = record["strumenti"]
        # UNA riga per chiamata, etichettata con la PRIMA azione. L'attribuzione sta gia'
        # sulla chiamata: spezzare la duplicherebbe invece di affinarla.
        if strumenti:
            azione, identificativo_strumento = strumenti[0]
        else:
            azione, identificativo_strumento = "risposta", None

        if identificativo_strumento in esiti:
            noto, fallita = 1, 1 if esiti[identificativo_strumento] else 0
        elif identificativo_strumento is None:
            # Una risposta senza strumenti non ha un esito da conoscere: e' riuscita.
            noto, fallita = 1, 0
        else:
            # Mai «falso» per «non lo so».
            noto, fallita = 0, 0

        ingresso, lettura, scrittura, uscita = record["usage"]
        chiamate.append(Chiamata(
            session_id=sessione,
            message_id=identificativo,
            timestamp=record["timestamp"],
            project=record["project"],
            action=azione,
            model_used=record["model_used"],
            input_tokens=ingresso,
            cache_read_tokens=lettura,
            cache_write_tokens=scrittura,
            output_tokens=uscita,
            azione_fallita=fallita,
            esito_noto=noto,
            azioni_nella_chiamata=max(1, len(strumenti)),
            skill=record["skill"],
            plugin=record["plugin"],
            mcp_server=record["mcp_server"],
            is_sidechain=record["is_sidechain"],
        ))
    return chiamate
