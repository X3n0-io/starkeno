"""Quali sprechi ed errori ci sono DAVVERO nei dati?

Le quattro regole della v1 sono state progettate prima che qualcuno avesse visto
un transcript vero, e infatti non trovano niente. Questo script fa il contrario:
non chiede "le mie regole trovano qualcosa?", chiede "che cosa c'e' da trovare?".

Sei cacce:
  A  quanto costano i fallimenti, e il rimedio che li segue
  B  quanto costa una sessione lunga rispetto a farne due corte
  C  il costo COMPOSTO di un singolo risultato grosso, riletto a ogni turno
  D  riletture identiche dello stesso file nella stessa sessione
  E  quali strumenti falliscono, e quanto
  F  modello di fascia alta su lavoro meccanico
"""
import json, os, glob
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.expanduser("~/.claude/projects")
PESI = {"input": 1.0, "cache_read": 0.1, "cache_write": 1.25, "output": 5.0}
FRONTIER = ("opus", "fable", "mythos")
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


chiamate = {}
esiti = {}          # tool_use_id -> (fallito, dimensione_risultato_in_caratteri)

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
            m = d.get("message")
            if not isinstance(m, dict):
                continue
            cont = m.get("content")
            if isinstance(cont, list):
                for b in cont:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                        c = b.get("content")
                        esiti[b["tool_use_id"]] = (bool(b.get("is_error")),
                                                   len(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)))
            u = m.get("usage")
            if not isinstance(u, dict) or (m.get("model") or "") == "<synthetic>":
                continue
            sid, mid, ts = d.get("sessionId"), m.get("id"), parse_ts(d.get("timestamp"))
            if not sid or not mid or ts is None:
                continue
            tools = []
            if isinstance(cont, list):
                for b in cont:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        nome = (b.get("name") or "?").lower()
                        tools.append((nome, dettaglio_di(b.get("input")), b.get("id")))
            q = (int(u.get("input_tokens") or 0), int(u.get("cache_read_input_tokens") or 0),
                 int(u.get("cache_creation_input_tokens") or 0), int(u.get("output_tokens") or 0))
            r = chiamate.get((sid, mid))
            if r is None:
                chiamate[(sid, mid)] = {"sid": sid, "ts": ts, "cwd": d.get("cwd") or "?",
                                        "modello": m.get("model") or "?", "tools": list(tools), "q": q}
            else:
                r["ts"] = min(r["ts"], ts)
                r["tools"].extend(tools)
                r["q"] = q


def pes(q):
    i, cr, cw, o = q
    return i * PESI["input"] + cr * PESI["cache_read"] + cw * PESI["cache_write"] + o * PESI["output"]


def marg(q):
    i, cr, cw, o = q
    return i * PESI["input"] + cw * PESI["cache_write"] + o * PESI["output"]


sess = defaultdict(list)
for r in chiamate.values():
    sess[r["sid"]].append(r)
for s in sess:
    sess[s].sort(key=lambda r: r["ts"])

TOT_P = sum(pes(r["q"]) for r in chiamate.values())
print("Campione: %d chiamate, %d sessioni, %.1f M token pesati"
      % (len(chiamate), len(sess), TOT_P / 1e6))
print()

# =============================================================================
print("=" * 76)
print("A) QUANTO COSTANO I FALLIMENTI (e il rimedio subito dopo)")
print("=" * 76)
costo_fall = costo_rimedio = 0.0
n_fall = n_rimedio = 0
for s, lista in sess.items():
    for i, r in enumerate(lista):
        if not r["tools"]:
            continue
        nome, det, tid = r["tools"][0]
        if not esiti.get(tid, (False, 0))[0]:
            continue
        n_fall += 1
        costo_fall += marg(r["q"])
        # il rimedio: la chiamata dopo che rifa' la STESSA azione
        if i + 1 < len(lista) and lista[i + 1]["tools"]:
            n2, d2, _ = lista[i + 1]["tools"][0]
            if n2 == nome and d2 == det:
                n_rimedio += 1
                costo_rimedio += marg(lista[i + 1]["q"])
TOT_M = sum(marg(r["q"]) for r in chiamate.values())
print("  azioni fallite                        %6d" % n_fall)
print("  costo diretto                         %6.2f M marginali (%.2f%% del totale)"
      % (costo_fall / 1e6, 100 * costo_fall / TOT_M))
print("  di cui seguite da un rifacimento identico %d volte" % n_rimedio)
print("  costo del rifacimento                 %6.2f M marginali (%.2f%%)"
      % (costo_rimedio / 1e6, 100 * costo_rimedio / TOT_M))
print("  SPRECO TOTALE DA FALLIMENTO           %6.2f M  (%.2f%% della spesa marginale)"
      % ((costo_fall + costo_rimedio) / 1e6, 100 * (costo_fall + costo_rimedio) / TOT_M))
print()

# =============================================================================
print("=" * 76)
print("B) LA SESSIONE LUNGA COSTA PIU' DI DUE CORTE?")
print("=" * 76)
print("  Il contesto si ripaga a ogni turno: il costo del turno N contiene tutto")
print("  quello che e' successo prima. Se e' vero, il costo per azione cresce.")
print()
fasce = [(1, 10), (11, 30), (31, 60), (61, 120), (121, 300), (301, 10000)]
print("  posizione del turno | chiamate | costo medio per chiamata | di cui rilettura")
for a, b in fasce:
    tot = n = ricache = 0.0
    for s, lista in sess.items():
        for i, r in enumerate(lista):
            if a <= i + 1 <= b:
                tot += pes(r["q"]); n += 1; ricache += r["q"][1] * PESI["cache_read"]
    if n:
        print("     %4d - %-5d      | %8d | %20.0f     | %5.1f%%"
              % (a, b, n, tot / n, 100 * ricache / tot))
print()
lunghe = [s for s in sess if len(sess[s]) >= 200]
corte = [s for s in sess if len(sess[s]) <= 30]
def cpa(gruppo):
    t = sum(pes(r["q"]) for s in gruppo for r in sess[s])
    n = sum(len(sess[s]) for s in gruppo)
    return t / max(1, n), n
cl, nl = cpa(lunghe); cc, nc = cpa(corte)
print("  sessioni da >=200 azioni (%d sess., %d azioni): %.0f token per azione" % (len(lunghe), nl, cl))
print("  sessioni da <=30  azioni (%d sess., %d azioni): %.0f token per azione" % (len(corte), nc, cc))
if cc:
    print("  -> una sessione lunga paga %.1fx per la stessa azione" % (cl / cc))
print()

# =============================================================================
print("=" * 76)
print("C) IL COSTO COMPOSTO DI UN SINGOLO RISULTATO GROSSO")
print("=" * 76)
print("  Un risultato entra nel contesto e viene RILETTO a ogni turno successivo.")
print("  Costo composto ~= dimensione x 0,1 x turni rimanenti.")
print()
compost = []
for s, lista in sess.items():
    n = len(lista)
    for i, r in enumerate(lista):
        rim = n - i - 1
        if rim <= 0:
            continue
        for nome, det, tid in r["tools"]:
            fall, dim = esiti.get(tid, (False, 0))
            tok = dim / 4.0                      # stima grezza: 4 caratteri per token
            if tok < 2000:
                continue
            compost.append((tok * PESI["cache_read"] * rim, tok, rim, nome, det, s))
compost.sort(reverse=True)
somma = sum(c[0] for c in compost)
print("  risultati sopra i 2.000 token stimati: %d" % len(compost))
print("  costo composto complessivo: %.1f M pesati (%.1f%% di tutta la spesa)"
      % (somma / 1e6, 100 * somma / TOT_P))
print()
print("  I 12 risultati piu' cari da portarsi dietro:")
print("   costo comp. | dimens. | turni | azione")
for c, tok, rim, nome, det, s in compost[:12]:
    print("   %8.0f k  | %6.0f k | %5d | %s:%s"
          % (c / 1000, tok / 1000, rim, nome, (det or "")[:52]))
print()

# =============================================================================
print("=" * 76)
print("D) RILETTURE IDENTICHE NELLA STESSA SESSIONE")
print("=" * 76)
sprecate = 0
esempi = []
for s, lista in sess.items():
    visto = {}
    for r in lista:
        for nome, det, tid in r["tools"]:
            if nome not in ("read", "glob") or not det:
                continue
            fall, dim = esiti.get(tid, (False, 0))
            k = (nome, det)
            if k in visto:
                sprecate += 1
                if dim > 8000:
                    esempi.append((dim / 4.0, visto[k] + 1, nome, det))
            visto[k] = visto.get(k, 0) + 1
letture = sum(1 for r in chiamate.values() for n_, d_, _ in r["tools"] if n_ == "read" and d_)
print("  letture totali con percorso: %d" % letture)
print("  letture dello STESSO file gia' letto nella stessa sessione: %d (%.1f%%)"
      % (sprecate, 100 * sprecate / max(1, letture)))
esempi.sort(reverse=True)
print("  I 10 casi piu' grossi (file grande riletto piu' volte):")
for tok, volte, nome, det in esempi[:10]:
    print("   %6.0f k token, %2da rilettura  %s" % (tok / 1000, volte, det[-58:]))
print()

# =============================================================================
print("=" * 76)
print("E) QUALI STRUMENTI FALLISCONO")
print("=" * 76)
per_tool = defaultdict(lambda: [0, 0])
for r in chiamate.values():
    for nome, det, tid in r["tools"]:
        if tid in esiti:
            per_tool[nome][0] += 1
            per_tool[nome][1] += 1 if esiti[tid][0] else 0
print("  strumento                          usi   falliti   tasso")
for nome, (n, f) in sorted(per_tool.items(), key=lambda kv: -kv[1][1])[:14]:
    print("   %-32s %6d %6d   %5.1f%%" % (nome[:32], n, f, 100 * f / n))
print()

# =============================================================================
print("=" * 76)
print("F) FASCIA ALTA SU LAVORO MECCANICO")
print("=" * 76)
MECCANICI = ("read", "glob", "grep", "ls", "taskupdate", "taskcreate", "todowrite")
n_m = 0
costo_m = 0.0
for r in chiamate.values():
    if not any(k in r["modello"] for k in FRONTIER):
        continue
    if not r["tools"]:
        continue
    if all(n_ in MECCANICI for n_, _, _ in r["tools"]) and r["q"][3] < 600:
        n_m += 1
        costo_m += pes(r["q"])
print("  chiamate di fascia alta che fanno SOLO lettura/ricerca/lista")
print("  con meno di 600 token di output: %d (%.1f%% delle chiamate)"
      % (n_m, 100 * n_m / len(chiamate)))
print("  costo: %.1f M pesati (%.1f%% del totale)" % (costo_m / 1e6, 100 * costo_m / TOT_P))
print("  NOTA: non e' spreco dimostrato — il modello lo sceglie la sessione, non la")
print("  singola chiamata, e cambiarlo a meta' sessione ricostruirebbe la cache.")
