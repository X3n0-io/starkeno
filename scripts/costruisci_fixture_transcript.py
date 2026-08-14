"""Costruisce `tests/fixtures/transcript_vero.jsonl` da un transcript vero, RIPULITO.

**Perche' ripulito e non copiato.** Il piano diceva di copiare 400 righe di un transcript
vero dentro il repository. Ma StarkEno e' destinato a diventare pubblico su GitHub, e un
transcript contiene tutto: i prompt dell'utente, il ragionamento del modello, il contenuto
dei file letti, i comandi eseguiti, i percorsi con dentro il nome utente. Pubblicare una
fixture cosi' significa pubblicare le proprie conversazioni, per sempre e senza accorgersene.

**Cosa si conserva, ed e' tutto cio' che serve al test.** La proprieta' che la fixture deve
provare e' STRUTTURALE: il transcript scrive piu' righe per la stessa chiamata API, e ogni
riga ripete `usage`. Quindi si conservano intatti — perche' sono la misura — i valori di
`usage`, i modelli, i timestamp, la struttura delle righe, i nomi degli strumenti, l'esito
`is_error`, e quali righe condividono lo stesso messaggio.

**Cosa si sostituisce.** Ogni testo scritto da una persona o restituito da uno strumento:
i blocchi `text` e `thinking` spariscono (il lettore non li guarda), gli identificativi
diventano progressivi, il `cwd` diventa un percorso neutro, e i parametri degli strumenti
mantengono la CHIAVE — che serve a `_dettaglio` — ma con un valore pseudonimo stabile, cosi'
due letture dello stesso file restano due letture dello stesso file.

Uso:  python scripts/costruisci_fixture_transcript.py
"""
import glob
import json
import os
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "tests" / "fixtures" / "transcript_vero.jsonl"
RIGHE_VOLUTE = 400

# Le uniche chiavi di primo livello che il lettore guarda. Tutto il resto — `lastPrompt`,
# `toolUseResult`, `gitBranch`, `customTitle`, `slug` — porta contenuto e non entra.
CHIAVI_TENUTE = ("timestamp", "isSidechain",
                 "attributionSkill", "attributionPlugin", "attributionMcpServer")


def _scegli() -> str:
    """Un transcript che contenga sia chiamate multi-strumento sia almeno un fallimento."""
    for percorso in sorted(glob.glob(
            os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True)):
        testo = open(percorso, encoding="utf-8", errors="replace").read()
        if '"is_error":true' in testo.replace(" ", "") and testo.count('"tool_use"') > 20:
            return percorso
    raise SystemExit("nessun transcript adatto trovato")


class _Pseudonimi:
    """Nomi progressivi e STABILI: lo stesso valore vero da sempre lo stesso pseudonimo."""

    def __init__(self, formato):
        self._formato = formato
        self._visti = {}

    def __call__(self, valore):
        if valore is None:
            return None
        if valore not in self._visti:
            self._visti[valore] = self._formato % (len(self._visti) + 1)
        return self._visti[valore]


def main() -> None:
    sorgente = _scegli()
    righe = open(sorgente, encoding="utf-8", errors="replace").read().splitlines()

    # Una finestra che contiene di sicuro il primo fallimento: se si prendessero le prime
    # 400 righe e l'errore stesse alla 900esima, la fixture non proverebbe gli esiti.
    primo_errore = next((i for i, r in enumerate(righe) if '"is_error":true' in r.replace(" ", "")),
                        0)
    inizio = max(0, primo_errore - RIGHE_VOLUTE // 2)
    finestra = righe[inizio:inizio + RIGHE_VOLUTE]

    sessioni = _Pseudonimi("sessione-%03d")
    messaggi = _Pseudonimi("msg-%04d")
    strumenti = _Pseudonimi("tool-%04d")
    cartelle = _Pseudonimi("/progetti/progetto-%02d")
    dettagli = _Pseudonimi("oggetto-%04d")

    fuori = []
    for riga in finestra:
        if not riga.strip():
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

        ridotta = {"sessionId": sessioni(voce.get("sessionId")),
                   "cwd": cartelle(voce.get("cwd"))}
        for chiave in CHIAVI_TENUTE:
            if chiave in voce:
                ridotta[chiave] = voce[chiave]

        blocchi = []
        contenuto = messaggio.get("content")
        if isinstance(contenuto, list):
            for blocco in contenuto:
                if not isinstance(blocco, dict):
                    continue
                if blocco.get("type") == "tool_use":
                    parametri = blocco.get("input")
                    ridotti = {}
                    if isinstance(parametri, dict):
                        for chiave, valore in parametri.items():
                            if isinstance(valore, str) and valore.strip():
                                ridotti[chiave] = dettagli(valore)
                    blocchi.append({"type": "tool_use", "id": strumenti(blocco.get("id")),
                                    "name": blocco.get("name"), "input": ridotti})
                elif blocco.get("type") == "tool_result":
                    blocchi.append({"type": "tool_result",
                                    "tool_use_id": strumenti(blocco.get("tool_use_id")),
                                    "is_error": bool(blocco.get("is_error"))})
                # `text` e `thinking` non entrano: il lettore non li guarda e sono
                # esattamente la parte che non va pubblicata.

        ridotto = {"id": messaggi(messaggio.get("id")), "content": blocchi}
        for chiave in ("role", "model"):
            if chiave in messaggio:
                ridotto[chiave] = messaggio[chiave]
        if isinstance(messaggio.get("usage"), dict):
            ridotto["usage"] = messaggio["usage"]       # INTATTO: e' la misura
        ridotta["message"] = ridotto
        fuori.append(json.dumps(ridotta, ensure_ascii=False))

    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text("\n".join(fuori) + "\n", encoding="utf-8")

    con_usage = sum(1 for r in fuori
                    if isinstance(json.loads(r)["message"].get("usage"), dict))
    chiamate = {(json.loads(r)["sessionId"], json.loads(r)["message"]["id"])
                for r in fuori
                if isinstance(json.loads(r)["message"].get("usage"), dict)
                and (json.loads(r)["message"].get("model") or "") != "<synthetic>"}
    errori = sum(1 for r in fuori if '"is_error": true' in r)
    print("sorgente        :", sorgente)
    print("righe scritte   :", len(fuori))
    print("righe con usage :", con_usage)
    print("chiamate uniche :", len(chiamate))
    print("righe/chiamata  : %.2f" % (con_usage / len(chiamate)))
    print("tool_result falliti:", errori)


if __name__ == "__main__":
    main()
