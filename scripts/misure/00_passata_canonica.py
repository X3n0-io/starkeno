"""UNA passata, UN insieme di numeri. Ogni cifra del design esce da qui.

Nasce da una critica giusta: la prima campagna produceva 7.595 / 7.599 / 7.583 /
7.007 / 8.014 da sei script con filtri leggermente diversi, e nessuno poteva dire
quale fosse quale. Numeri che non tornano fra loro non si difendono.

Risponde anche alle obiezioni che rimettono in discussione le decisioni:
  A) l'attribuzione e' gonfiata dal contesto riportato a ogni turno?
  B) la calibrazione di R1 e' stata presa su una grana che in produzione non esiste
  C) il rilevatore B (ciclo) e' raggiungibile o e' morto?
  D) R2 era muta o non calcolabile?
  E) 22 progetti nel campione ma 13 segnalati: dove sono gli altri 9?
  F) 474 transcript e 474 fallimenti: coincidenza o difetto dello script?
"""
import json, os, glob
from collections import Counter, defaultdict
from datetime import datetime, timedelta

ROOT = os.path.expanduser("~/.claude/projects")
PESI = {"input": 1.0, "cache_read": 0.1, "cache_write": 1.25, "output": 5.0}
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


def parse_ts(t):
    try:
        return datetime.fromisoformat((t or "").replace("Z", "+00:00"))
    except Exception:
        return None


# =============================================================================
# UNA passata sui file
# =============================================================================
n_file = n_righe = n_usage = n_synth = 0
chiamate = {}          # (sid, mid) -> record
esiti = {}             # tool_use_id -> is_error
n_tool_result = 0

for path in glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True):
    n_file += 1
    try:
        f = open(path, encoding="utf-8")
    except OSError:
        continue
    with f:
        for line in f:
            n_righe += 1
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get("message")
            if not isinstance(m, dict):
                continue
            cont = m.get("content")

            # --- esiti (stanno nei messaggi utente) ---
            if isinstance(cont, list):
                for b in cont:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                        n_tool_result += 1
                        esiti[b["tool_use_id"]] = bool(b.get("is_error"))

            # --- chiamate API (messaggi assistente con usage) ---
            u = m.get("usage")
            if not isinstance(u, dict):
                continue
            n_usage += 1
            if (m.get("model") or "") == "<synthetic>":
                n_synth += 1
                continue
            sid, mid, ts = d.get("sessionId"), m.get("id"), parse_ts(d.get("timestamp"))
            if not sid or not mid or ts is None:
                continue

            tools = []
            if isinstance(cont, list):
                for b in cont:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        nome = (b.get("name") or "?").lower()
                        det = dettaglio_di(b.get("input"))
                        tools.append(("%s:%s" % (nome, det) if det else nome, b.get("id")))

            q = (int(u.get("input_tokens") or 0),
                 int(u.get("cache_read_input_tokens") or 0),
                 int(u.get("cache_creation_input_tokens") or 0),
                 int(u.get("output_tokens") or 0))
            r = chiamate.get((sid, mid))
            if r is None:
                chiamate[(sid, mid)] = {
                    "sid": sid, "ts": ts, "cwd": d.get("cwd") or "?",
                    "modello": m.get("model") or "?", "tools": list(tools), "usage": q,
                    "skill": d.get("attributionSkill"), "plugin": d.get("attributionPlugin"),
                    "mcp": d.get("attributionMcpServer"), "sidechain": bool(d.get("isSidechain")),
                }
            else:
                r["ts"] = min(r["ts"], ts)
                r["tools"].extend(tools)
                r["usage"] = q                    # l'ULTIMA riga vince (spec §4)
                for campo, chiave in (("skill", "attributionSkill"),
                                      ("plugin", "attributionPlugin"),
                                      ("mcp", "attributionMcpServer")):
                    if r[campo] is None and d.get(chiave):
                        r[campo] = d.get(chiave)

print("=" * 74)
print("IL CAMPIONE — un numero per cosa, e ogni cosa ha un nome")
print("=" * 74)
print("  file .jsonl letti                                %7d" % n_file)
print("  righe totali                                     %7d" % n_righe)
print("  righe con `usage` (comprese le <synthetic>)       %7d" % n_usage)
print("  di cui <synthetic>, scartate                      %7d" % n_synth)
print("  CHIAMATE API uniche (sessionId, message.id)      %7d" % len(chiamate))
print("  righe per chiamata                               %7.2f"
      % ((n_usage - n_synth) / len(chiamate)))
con_tool = [r for r in chiamate.values() if r["tools"]]
n_blocchi = sum(len(r["tools"]) for r in chiamate.values())
print("  chiamate che contengono almeno uno strumento     %7d" % len(con_tool))
print("  BLOCCHI tool_use totali (piu' righe che chiamate)%7d" % n_blocchi)
print("  blocchi tool_result trovati                      %7d" % n_tool_result)
print("  esiti distinti registrati (per tool_use_id)      %7d" % len(esiti))
print()
print("  -> le cinque cifre della prima campagna erano:")
print("     chiamate API, chiamate-con-strumento, blocchi tool_use, e due varianti")
print("     con filtri diversi. Da qui in poi si citano solo queste, col nome.")
print()

# =============================================================================
# F) 474 transcript e 474 fallimenti: coincidenza?
# =============================================================================
falliti_blocchi = sum(1 for r in chiamate.values() for _, tid in r["tools"] if esiti.get(tid))
noti = sum(1 for r in chiamate.values() for _, tid in r["tools"] if tid in esiti)
print("=" * 74)
print("F) LA COINCIDENZA 474 / 474")
print("=" * 74)
print("  file .jsonl              %6d" % n_file)
print("  blocchi tool_use falliti %6d" % falliti_blocchi)
print("  esito NON risolto        %6d  (%.2f%% dei blocchi)"
      % (n_blocchi - noti, 100 * (n_blocchi - noti) / max(1, n_blocchi)))
print("  -> %s" % ("COINCIDENZA: i due numeri non hanno alcun legame causale"
                   if falliti_blocchi != n_file else
                   "SOSPETTO: identici, va aperto lo script prima di fidarsi"))
print()

# =============================================================================
# B) La grana di produzione: UNA RIGA PER CHIAMATA, esito della PRIMA azione
# =============================================================================
print("=" * 74)
print("B) CALIBRAZIONE RIMISURATA SULLA GRANA CHE ESISTERA' DAVVERO")
print("=" * 74)
righe_prod = defaultdict(list)     # sid -> [(ts, azione, fallita)]
for r in chiamate.values():
    if not r["tools"]:
        continue
    azione, tid = r["tools"][0]         # la PRIMA, come decide lo spec §4
    righe_prod[r["sid"]].append((r["ts"], azione, bool(esiti.get(tid))))
for sid in righe_prod:
    righe_prod[sid].sort(key=lambda x: x[0])

n_righe_prod = sum(len(v) for v in righe_prod.values())
falliti_prod = sum(1 for v in righe_prod.values() for _, _, f in v if f)
print("  righe che esisteranno in agent_actions   %6d" % n_righe_prod)
print("  di cui marcate fallite                   %6d  (%.1f%%)"
      % (falliti_prod, 100 * falliti_prod / n_righe_prod))
print("  fallimenti INVISIBILI a questa grana     %6d  (%.1f%% di tutti i fallimenti)"
      % (falliti_blocchi - falliti_prod,
         100 * (falliti_blocchi - falliti_prod) / max(1, falliti_blocchi)))
print()

LIM = timedelta(minutes=10)
peggiori = []
for sid, lista in righe_prod.items():
    for i in range(len(lista)):
        now = lista[i][0]
        j = i
        while j > 0 and now - lista[j - 1][0] <= LIM:
            j -= 1
        fin = lista[j:i + 1]
        c = Counter(a for _, a, f in fin if f and ":" in a)
        if c:
            peggiori.append(c.most_common(1)[0][1])
dist = Counter(peggiori)
print("  Peggior caso SANO, sulla grana di produzione:")
print("  (stessa azione con dettaglio, fallita piu' volte in 10 minuti)")
for n in sorted(dist, reverse=True):
    print("     %d fallimenti -> %5d finestre" % (n, dist[n]))
massimo = max(dist) if dist else 0
print("  MASSIMO OSSERVATO: %d   (la prima campagna, sulla grana sbagliata, diceva 2)"
      % massimo)
print()

# =============================================================================
# C) Il rilevatore B (ciclo) e' raggiungibile?
# =============================================================================
print("=" * 74)
print("C) IL RILEVATORE B E' RAGGIUNGIBILE, O E' MORTO?")
print("=" * 74)
tasso = 100 * falliti_prod / n_righe_prod
print("  tasso base di fallimento sulle righe di produzione: %.1f%%" % tasso)
for L, K, nome in ((2, 3, "ciclo minimo, dettagli identici"),
                   (6, 6, "ciclo massimo, dettagli misti")):
    print("     %-34s %2d azioni coinvolte -> servirebbero 4 fallimenti = %.0f%%"
          % (nome, L * K, 100 * 4 / (L * K)))
finestre_ok = 0
tot_fin = 0
for sid, lista in righe_prod.items():
    for i in range(5, len(lista)):
        tot_fin += 1
        blocco = lista[max(0, i - 5):i + 1]
        if sum(1 for _, _, f in blocco if f) >= 4:
            finestre_ok += 1
print("  finestre reali da 6 righe con >=4 fallimenti: %d su %d (%.4f%%)"
      % (finestre_ok, tot_fin, 100 * finestre_ok / max(1, tot_fin)))
print()

# =============================================================================
# A) L'ATTRIBUZIONE E' GONFIATA DAL CONTESTO?
# =============================================================================
print("=" * 74)
print("A) L'ATTRIBUZIONE REGGE, O MISURA SOLO QUANTO CONTESTO C'ERA?")
print("=" * 74)


def pesati(q):
    i, cr, cw, o = q
    return i * PESI["input"] + cr * PESI["cache_read"] + cw * PESI["cache_write"] + o * PESI["output"]


def marginali(q):
    """Cio' che QUESTA chiamata ha aggiunto: niente rilettura della cache."""
    i, cr, cw, o = q
    return i * PESI["input"] + cw * PESI["cache_write"] + o * PESI["output"]


tot_p = sum(pesati(r["usage"]) for r in chiamate.values())
tot_m = sum(marginali(r["usage"]) for r in chiamate.values())
tot_cr = sum(r["usage"][1] * PESI["cache_read"] for r in chiamate.values())
print("  spesa pesata TOTALE            %8.1f M" % (tot_p / 1e6))
print("  di cui rilettura della cache   %8.1f M   (%.1f%%)  <- contesto riportato"
      % (tot_cr / 1e6, 100 * tot_cr / tot_p))
print("  spesa MARGINALE                %8.1f M   (%.1f%%)  <- causata dalla chiamata"
      % (tot_m / 1e6, 100 * tot_m / tot_p))
print()

for campo, etichetta in (("mcp", "SERVER MCP"), ("skill", "SKILL")):
    agg = defaultdict(lambda: [0, 0.0, 0.0])
    for r in chiamate.values():
        k = r.get(campo) or "(nessuno)"
        agg[k][0] += 1
        agg[k][1] += pesati(r["usage"])
        agg[k][2] += marginali(r["usage"])
    print("  %s — le due basi a confronto:" % etichetta)
    print("    %-40s %7s %8s %8s" % ("", "chiam.", "pesati", "marginali"))
    for k, (n, p, mg) in sorted(agg.items(), key=lambda kv: -kv[1][1])[:7]:
        print("    %-40s %7d %7.1f%% %7.1f%%"
              % (str(k)[:40], n, 100 * p / tot_p, 100 * mg / tot_m))
    print()

# =============================================================================
# E) 22 progetti, 13 segnalati
# =============================================================================
print("=" * 74)
print("E) 22 PROGETTI NEL CAMPIONE, 13 SEGNALATI: DOVE SONO GLI ALTRI 9?")
print("=" * 74)


def progetto(cwd):
    p = (cwd or "?").rstrip("\\/").replace("/", "\\")
    return p.split("\\")[-1] or "?"


per_prog = defaultdict(list)
for r in chiamate.values():
    per_prog[progetto(r["cwd"])].append(r)
print("  progetti distinti: %d" % len(per_prog))
mai = [p for p, v in per_prog.items() if len(v) < 15]
print("  con meno di 15 chiamate (sotto HEAVY_MIN_OCCURRENCES): %d" % len(mai))
print("     %s" % ", ".join(sorted(mai)))
print("  -> \"13 su 13\" va detto come: 13 progetti su %d che avevano abbastanza"
      % (len(per_prog) - len(mai)))
print("     lavoro da poter essere valutati. Non \"ogni singolo progetto\".")
