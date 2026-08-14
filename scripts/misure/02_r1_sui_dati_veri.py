"""R1 sui dati veri, seconda passata.

Corregge il difetto della prima: l'esito si conta PER ISTANTE di valutazione,
non appiccicando alla sessione il primo NON_VALUTABILE che capita.

E soprattutto: stampa la sequenza di azioni attorno a ogni violazione, per
poter giudicare a occhio se e' un agente bloccato o lavoro normale.
"""
import json, os, sys, glob
from collections import defaultdict, Counter
from datetime import datetime, timedelta

# La radice si ricava da DOVE STA QUESTO FILE, non dalla macchina di chi l'ha scritto:
# `scripts/misure/x.py` -> su di tre. Cablarla rende lo script ineseguibile a chiunque
# altro, e queste misure esistono proprio per essere rieseguite.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from starkeno import config as cfg_mod
from starkeno.rules import valuta_r1, VIOLAZIONE, NON_VALUTABILE, OK

ROOT = os.path.expanduser("~/.claude/projects")
CHIAVI = ("file_path", "path", "notebook_path", "pattern", "command", "url",
          "query", "prompt", "skill", "subagent_type", "file", "filePath")


def dettaglio_di(inp):
    if not isinstance(inp, dict):
        return None
    for k in CHIAVI:
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:300]
    return None


class Azione:
    __slots__ = ("timestamp", "action", "id")

    def __init__(self, ts, action, id_):
        self.timestamp, self.action, self.id = ts, action, id_


def parse_ts(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


chiamate = {}
for path in glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True):
    try:
        f = open(path, encoding="utf-8")
    except OSError:
        continue
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get("message")
            if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                continue
            if (msg.get("model") or "") == "<synthetic>":
                continue
            sid, mid = d.get("sessionId"), msg.get("id")
            ts = parse_ts(d.get("timestamp") or "")
            if not sid or not mid or ts is None:
                continue
            rec = chiamate.setdefault((sid, mid), {"sid": sid, "ts": ts, "tools": []})
            rec["ts"] = min(rec["ts"], ts)
            content = msg.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        nome = (c.get("name") or "?").lower()
                        det = dettaglio_di(c.get("input"))
                        rec["tools"].append("%s:%s" % (nome, det) if det else nome)

sessioni = defaultdict(list)
for rec in chiamate.values():
    sessioni[rec["sid"]].append((rec["ts"], rec["tools"][0] if rec["tools"] else "risposta"))
for sid in sessioni:
    sessioni[sid].sort(key=lambda x: x[0])


class Cfg:
    pass


def fai_config(min_history):
    c = Cfg()
    for nome in dir(cfg_mod):
        if nome.isupper():
            setattr(c, nome, getattr(cfg_mod, nome))
    c.LOOP_MIN_HISTORY = min_history
    return c


FINESTRA = timedelta(hours=cfg_mod.SUPERVISOR_ACTIVE_AGENT_HOURS)


def prova(min_history, raccogli=False):
    conf = fai_config(min_history)
    istanti = Counter()
    motivi_nv = Counter()
    finale = Counter()
    violazioni = []
    for sid, coppie in sessioni.items():
        azioni = [Azione(ts, a, i) for i, (ts, a) in enumerate(coppie)]
        ultimo = None
        gia = False
        for i in range(len(azioni)):
            now = azioni[i].timestamp
            j = i
            while j > 0 and now - azioni[j - 1].timestamp <= FINESTRA:
                j -= 1
            finestra = azioni[j: i + 1]
            e = valuta_r1(finestra, now=now, config=conf)
            istanti[e.stato] += 1
            if e.stato == NON_VALUTABILE:
                motivi_nv["storia" if "storia insufficiente" in (e.motivo or "")
                          else "senza dettaglio"] += 1
            if e.stato == VIOLAZIONE and not gia:
                gia = True
                if raccogli:
                    violazioni.append((sid, i, len(azioni), e, finestra))
            ultimo = e.stato
        finale[ultimo] += 1
    return istanti, motivi_nv, finale, violazioni


print("Sessioni: %d, azioni: %d" % (len(sessioni), sum(len(v) for v in sessioni.values())))
print()
print("ESITO PER ISTANTE DI VALUTAZIONE (ogni azione = un istante)")
print(" soglia |  VIOLAZIONE  | NON_VALUTABILE (storia / senza dettaglio) |     OK")
for mh in (20, 10, 6, 1):
    ist, nv, fin, _ = prova(mh)
    tot = sum(ist.values())
    print(" %6d | %5d %5.1f%% | %6d %5.1f%%  (%5d / %5d)          | %5d %5.1f%%"
          % (mh, ist[VIOLAZIONE], 100 * ist[VIOLAZIONE] / tot,
             ist[NON_VALUTABILE], 100 * ist[NON_VALUTABILE] / tot,
             nv["storia"], nv["senza dettaglio"],
             ist[OK], 100 * ist[OK] / tot))
print()
print("ESITO ALLA FINE DELLA SESSIONE")
for mh in (20, 1):
    ist, nv, fin, _ = prova(mh)
    print("  soglia %2d -> VIOLAZIONE %d | NON_VALUTABILE %d | OK %d"
          % (mh, fin[VIOLAZIONE], fin[NON_VALUTABILE], fin[OK]))
print()

# ---- le violazioni, guardate da vicino --------------------------------------
_, _, _, viol = prova(20, raccogli=True)
print("=" * 78)
print("LE %d VIOLAZIONI, CON LE AZIONI CHE LE HANNO PRODOTTE" % len(viol))
print("=" * 78)
for sid, i, n, e, finestra in viol:
    print()
    print("Sessione %s... (%d azioni totali), violazione alla n.%d" % (sid[:8], n, i + 1))
    print("  MOTIVO: %s" % e.motivo)
    print("  EVIDENZA: %s" % {k: v for k, v in (e.evidenza or {}).items()
                              if k != "categorie"})
    print("  Le 16 azioni precedenti (piu' recente in fondo):")
    t0 = None
    for a in finestra[-16:]:
        d = "" if t0 is None else "+%5.1fs" % (a.timestamp - t0).total_seconds()
        t0 = a.timestamp
        print("     %8s  %s" % (d, a.action[:96]))
