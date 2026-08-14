"""Cosa sa gia' il transcript che nessuno sta usando?

Due domande:
 1) esiste un segnale sui LIMITI di piano (quanto ne resta)? -> forecast possibile?
 2) quanto e' ricca l'attribuzione: skill, plugin, sub-agente, server MCP?
"""
import json, os, glob
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.expanduser("~/.claude/projects")
PESI = {"input": 1.0, "cache_read": 0.1, "cache_write": 1.25, "output": 5.0}

campi_radice = Counter()
sospetti_limite = Counter()
esempi_limite = []
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
            for k in d:
                campi_radice[k] += 1
            testo = line.lower()
            for parola in ("ratelimit", "rate_limit", "usage_limit", "usagelimit",
                           "quota", "resets", "limit_reached", "weekly"):
                if parola in testo:
                    sospetti_limite[parola] += 1
                    if len(esempi_limite) < 6 and parola in ("resets", "usagelimit", "rate_limit"):
                        esempi_limite.append(line[:400])

            m = d.get("message")
            if not isinstance(m, dict):
                continue
            u = m.get("usage")
            if not isinstance(u, dict) or (m.get("model") or "") == "<synthetic>":
                continue
            sid, mid = d.get("sessionId"), m.get("id")
            if not sid or not mid:
                continue
            pesati = (int(u.get("input_tokens") or 0) * PESI["input"]
                      + int(u.get("cache_read_input_tokens") or 0) * PESI["cache_read"]
                      + int(u.get("cache_creation_input_tokens") or 0) * PESI["cache_write"]
                      + int(u.get("output_tokens") or 0) * PESI["output"])
            chiamate[(sid, mid)] = {
                "pesati": pesati, "modello": m.get("model"),
                "ts": d.get("timestamp"),
                "cwd": d.get("cwd"), "sidechain": bool(d.get("isSidechain")),
                "skill": d.get("attributionSkill"),
                "plugin": d.get("attributionPlugin"),
                "mcp": d.get("attributionMcpServer"),
                "tool": d.get("attributionTool"),
            }

print("CAMPI PRESENTI ALLA RADICE DELLE RIGHE (i piu' frequenti):")
for k, n in campi_radice.most_common(28):
    print("   %-28s %6d" % (k, n))
print()
print("PAROLE LEGATE AI LIMITI DI PIANO trovate nei file:", dict(sospetti_limite))
for e in esempi_limite[:3]:
    print("   ESEMPIO:", e[:300])
print()

tot = sum(c["pesati"] for c in chiamate.values())
print("=" * 74)
print("DOVE VANNO I TOKEN (pesati). Totale: %.1f milioni su %d chiamate"
      % (tot / 1e6, len(chiamate)))
print("=" * 74)


def classifica(campo, etichetta):
    agg = defaultdict(lambda: [0, 0.0])
    for c in chiamate.values():
        k = c.get(campo) or "(nessuno)"
        agg[k][0] += 1
        agg[k][1] += c["pesati"]
    ordinati = sorted(agg.items(), key=lambda kv: -kv[1][1])
    print()
    print("Per %s:" % etichetta)
    print("   %-46s %7s %10s %7s" % ("", "chiamate", "Mtoken", "quota"))
    for k, (n, p) in ordinati[:12]:
        print("   %-46s %7d %10.2f %6.1f%%" % (str(k)[:46], n, p / 1e6, 100 * p / tot))


classifica("skill", "SKILL")
classifica("plugin", "PLUGIN")
classifica("mcp", "SERVER MCP")

agg = defaultdict(lambda: [0, 0.0])
for c in chiamate.values():
    k = "sub-agente" if c["sidechain"] else "conversazione principale"
    agg[k][0] += 1
    agg[k][1] += c["pesati"]
print()
print("Sub-agenti contro conversazione principale:")
for k, (n, p) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
    print("   %-46s %7d %10.2f %6.1f%%" % (k, n, p / 1e6, 100 * p / tot))

agg = defaultdict(lambda: [0, 0.0])
for c in chiamate.values():
    agg[c["modello"] or "?"][0] += 1
    agg[c["modello"] or "?"][1] += c["pesati"]
print()
print("Per MODELLO:")
for k, (n, p) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
    print("   %-46s %7d %10.2f %6.1f%%" % (k, n, p / 1e6, 100 * p / tot))

# ---- ritmo giornaliero: si puo' fare una previsione? ------------------------
per_giorno = defaultdict(float)
for c in chiamate.values():
    if c["ts"]:
        per_giorno[c["ts"][:10]] += c["pesati"]
print()
print("=" * 74)
print("RITMO GIORNALIERO (serve a capire se una previsione avrebbe senso)")
print("=" * 74)
giorni = sorted(per_giorno)
print("giorni con attivita': %d, su un arco di %s -> %s" % (len(giorni), giorni[0], giorni[-1]))
val = sorted(per_giorno.values())
print("mediana %.2f Mtoken/giorno, massimo %.2f, minimo %.2f"
      % (val[len(val) // 2] / 1e6, val[-1] / 1e6, val[0] / 1e6))
print()
print("Gli ultimi 14 giorni:")
for g in giorni[-14:]:
    barre = int(per_giorno[g] / max(val) * 46)
    print("   %s  %6.2f M  %s" % (g, per_giorno[g] / 1e6, "#" * barre))
