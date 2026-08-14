"""Qual e' il PEGGIOR caso sano? Cioe': quante volte, al massimo, un agente che
sta lavorando bene sbaglia la STESSA identica azione prima di venirne fuori?

Questo numero e' la calibrazione: la soglia di R1 deve stare sopra di esso.
"""
import json, os, glob
from collections import defaultdict, Counter
from datetime import datetime, timedelta

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


def parse_ts(ts):
    try:
        return datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except Exception:
        return None


azioni = defaultdict(list)
esiti = {}
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
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            u = msg.get("usage")
            if isinstance(u, dict) and (msg.get("model") or "") != "<synthetic>":
                sid, ts = d.get("sessionId"), parse_ts(d.get("timestamp"))
                if sid and ts:
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "tool_use":
                            nome = (c.get("name") or "?").lower()
                            det = dettaglio_di(c.get("input"))
                            azioni[sid].append(
                                (ts, "%s:%s" % (nome, det) if det else nome, c.get("id")))
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id"):
                    esiti[c["tool_use_id"]] = bool(c.get("is_error"))

LIMITE = timedelta(minutes=10)   # LOOP_CYCLE_WINDOW_MINUTES
print("A) STESSA AZIONE FALLITA PIU' VOLTE nella stessa finestra di 10 minuti")
print("   (non serve che siano consecutive: e' 'ci ha riprovato e ha ripreso l'errore')")
peggiori = []
for sid, lista in azioni.items():
    lista.sort(key=lambda x: x[0])
    for i in range(len(lista)):
        now = lista[i][0]
        j = i
        while j > 0 and now - lista[j - 1][0] <= LIMITE:
            j -= 1
        fin = lista[j: i + 1]
        c = Counter(t for _, t, k in fin if esiti.get(k))
        if c:
            testo, n = c.most_common(1)[0]
            peggiori.append((n, sid, testo))
peggiori.sort(reverse=True)
dist = Counter(n for n, _, _ in peggiori)
massimo = max(dist) if dist else 0
print("   Distribuzione del massimo per finestra:")
for n in sorted(dist, reverse=True):
    print("      %d fallimenti della stessa azione -> %d finestre" % (n, dist[n]))
print()
print("   IL PEGGIOR CASO OSSERVATO E': %d" % massimo)
print()
visti = set()
print("   I casi al massimo osservato:")
for n, sid, testo in peggiori:
    if n < massimo:
        break
    if (sid, testo) in visti:
        continue
    visti.add((sid, testo))
    print("      %dx  %s" % (n, testo[:92]))
print()

print("B) FALLIMENTI TOTALI nella finestra, di qualunque azione")
tot = []
for sid, lista in azioni.items():
    for i in range(len(lista)):
        now = lista[i][0]
        j = i
        while j > 0 and now - lista[j - 1][0] <= LIMITE:
            j -= 1
        tot.append(sum(1 for _, _, k in lista[j: i + 1] if esiti.get(k)))
d = Counter(tot)
print("   massimo fallimenti in una finestra di 10 minuti: %d" % max(d))
for n in sorted(d, reverse=True)[:8]:
    print("      %2d fallimenti -> %d finestre" % (n, d[n]))
print()

print("C) QUOTA DI FALLIMENTO nella finestra (fallite / totali), sulle finestre")
print("   con almeno 10 azioni — serve a vedere se esiste una coda 'malata'")
quote = []
for sid, lista in azioni.items():
    for i in range(len(lista)):
        now = lista[i][0]
        j = i
        while j > 0 and now - lista[j - 1][0] <= LIMITE:
            j -= 1
        fin = lista[j: i + 1]
        if len(fin) >= 10:
            quote.append(sum(1 for _, _, k in fin if esiti.get(k)) / len(fin))
quote.sort()
if quote:
    print("   finestre considerate: %d" % len(quote))
    for p in (50, 90, 95, 99, 100):
        v = quote[min(len(quote) - 1, int(len(quote) * p / 100))]
        print("      p%-3d  %.1f%% di azioni fallite" % (p, 100 * v))
