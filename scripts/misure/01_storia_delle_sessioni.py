"""Quanta storia ha davvero R1 se la si lega alla singola sessione?

Domanda: LOOP_MIN_HISTORY = 20 azioni. Le sessioni vere ci arrivano?
Metodo: grana (sessionId, message.id), <synthetic> escluso, come da spec §4.
"""
import json, os, sys, glob
from collections import defaultdict
from datetime import datetime

ROOT = os.path.expanduser("~/.claude/projects")

# (sessionId, message.id) -> dict
chiamate = {}
righe_totali = 0
righe_con_usage = 0
scartate_synthetic = 0

for path in glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True):
    try:
        f = open(path, encoding="utf-8")
    except OSError:
        continue
    with f:
        for line in f:
            righe_totali += 1
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            righe_con_usage += 1
            modello = msg.get("model") or ""
            if modello == "<synthetic>":
                scartate_synthetic += 1
                continue
            sid = d.get("sessionId")
            mid = msg.get("id")
            if not sid or not mid:
                continue
            chiave = (sid, mid)

            # tool_use presenti in questa riga
            strumenti = []
            content = msg.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        strumenti.append(c.get("name") or "?")

            rec = chiamate.get(chiave)
            if rec is None:
                rec = chiamate[chiave] = {
                    "sid": sid, "ts": d.get("timestamp"), "cwd": d.get("cwd"),
                    "modello": modello, "strumenti": [],
                    "sidechain": bool(d.get("isSidechain")),
                }
            rec["strumenti"].extend(strumenti)
            # timestamp: tieni il primo non nullo
            if not rec["ts"]:
                rec["ts"] = d.get("timestamp")

print("righe totali            %8d" % righe_totali)
print("righe con usage         %8d" % righe_con_usage)
print("scartate <synthetic>    %8d" % scartate_synthetic)
print("CHIAMATE API (uniche)   %8d" % len(chiamate))
print("righe per chiamata      %8.2f" % ((righe_con_usage - scartate_synthetic) / max(1, len(chiamate))))
print()

# ---- raggruppa per sessione -------------------------------------------------
sessioni = defaultdict(list)
for rec in chiamate.values():
    sessioni[rec["sid"]].append(rec)


def parse(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


righe = []
for sid, recs in sessioni.items():
    recs.sort(key=lambda r: (r["ts"] or ""))
    n = len(recs)
    con_tool = sum(1 for r in recs if r["strumenti"])
    tempi = [parse(r["ts"]) for r in recs]
    tempi = [t for t in tempi if t]
    durata_min = (max(tempi) - min(tempi)).total_seconds() / 60 if len(tempi) > 1 else 0.0
    righe.append({
        "sid": sid, "n": n, "con_tool": con_tool,
        "durata_min": durata_min,
        "cwd": recs[0]["cwd"],
        "sidechain": sum(1 for r in recs if r["sidechain"]),
        "tempi": tempi,
        "recs": recs,
    })

righe.sort(key=lambda r: -r["n"])
tot_sessioni = len(righe)
tot_chiamate = sum(r["n"] for r in righe)

print("SESSIONI distinte       %8d" % tot_sessioni)
print()


def quota(soglia, campo="n"):
    ok = [r for r in righe if r[campo] >= soglia]
    return len(ok), sum(r["n"] for r in ok)


print("Quante sessioni arrivano a N azioni? (e quanta spesa vive li' dentro)")
print("  soglia | sessioni |   %  | chiamate dentro |   % del traffico")
for soglia in (1, 5, 10, 20, 45, 100, 200):
    ns, nc = quota(soglia)
    print("  %6d | %8d | %4.1f%% | %15d | %6.1f%%"
          % (soglia, ns, 100 * ns / tot_sessioni, nc, 100 * nc / tot_chiamate))
print()

print("Stessa cosa contando SOLO le azioni con un tool_use (quelle che R1 sa leggere):")
print("  soglia | sessioni |   %  ")
for soglia in (1, 5, 10, 20, 45):
    ok = [r for r in righe if r["con_tool"] >= soglia]
    print("  %6d | %8d | %4.1f%%" % (soglia, len(ok), 100 * len(ok) / tot_sessioni))
print()

ns = sorted(r["n"] for r in righe)


def pct(p):
    return ns[min(len(ns) - 1, int(len(ns) * p / 100))]


print("Azioni per sessione: mediana %d, p75 %d, p90 %d, p95 %d, max %d"
      % (pct(50), pct(75), pct(90), pct(95), ns[-1]))
ds = sorted(r["durata_min"] for r in righe)
print("Durata sessione (min): mediana %.1f, p90 %.1f, max %.1f"
      % (ds[len(ds) // 2], ds[int(len(ds) * 0.9)], ds[-1]))
print()

# ---- densita': azioni nella finestra di 10 minuti del rilevatore B ----------
print("Rilevatore B guarda 45 azioni e vuole il ciclo dentro 10 minuti.")
print("Massimo numero di azioni in una qualunque finestra di 10 minuti, per sessione:")
dense = []
for r in righe:
    t = r["tempi"]
    best = 0
    j = 0
    for i in range(len(t)):
        while (t[i] - t[j]).total_seconds() > 600:
            j += 1
        best = max(best, i - j + 1)
    r["densita10"] = best
    dense.append(best)
dense.sort()
print("  mediana %d, p90 %d, p95 %d, max %d"
      % (dense[len(dense) // 2], dense[int(len(dense) * 0.9)],
         dense[int(len(dense) * 0.95)], dense[-1]))
for soglia in (10, 20, 45):
    ok = sum(1 for d in dense if d >= soglia)
    print("  sessioni con >= %d azioni in 10 minuti: %d (%.1f%%)"
          % (soglia, ok, 100 * ok / tot_sessioni))
print()

print("Le 15 sessioni piu' lunghe:")
print("   azioni  con_tool  durata_min  dens10  cwd")
for r in righe[:15]:
    print("  %7d  %8d  %10.1f  %6d  %s"
          % (r["n"], r["con_tool"], r["durata_min"], r["densita10"],
             (r["cwd"] or "?")[-45:]))
