"""Le cinque regole rimisurate con la contabilita' che il design dichiara giusta.

Accusa: il §6 ha bandito la base pesata per l'attribuzione, ma il §3 — che
giustifica le regole nuove — usa ancora quella. Cinque conti da rifare:

  A  S1: l'elenco degli strumenti sta nel prefisso cacheabile. In marginale
     quanto vale davvero? E quanto costa RIMETTERLO quando cambia a meta' sessione?
  B  S3: le riletture separate da una SCRITTURA sullo stesso file non ricomprano
     niente — il file e' cambiato. Quanto resta del 35%?
  C  S4: rifiuto dell'utente, oggetto non trovato ed errore vero non sono la stessa
     cosa. E n=5 sta sotto il minimo che S4 stessa impone.
  D  S2: quanto costa RICOMINCIARE? Senza il controfattuale il consiglio e' cieco.
  E  la quota di rilettura scende dopo il turno 300 mentre il costo sale: perche'?
"""
import json, os, glob
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.expanduser("~/.claude/projects")
PESI = {"input": 1.0, "cache_read": 0.1, "cache_write": 1.25, "output": 5.0}
CHIAVI = ("file_path", "path", "notebook_path", "pattern", "command", "url",
          "query", "prompt", "skill", "subagent_type", "file", "filePath")


def det_di(inp):
    if not isinstance(inp, dict):
        return None
    for k in CHIAVI:
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:300]
    return None


def pts(t):
    try:
        return datetime.fromisoformat((t or "").replace("Z", "+00:00"))
    except Exception:
        return None


chiamate = {}
esiti = {}
delta_strumenti = defaultdict(int)      # sid -> quante volte l'elenco e' cambiato
compattazioni = defaultdict(int)

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
            sid = d.get("sessionId")
            a = d.get("attachment")
            if isinstance(a, dict) and sid:
                if a.get("type") == "deferred_tools_delta":
                    delta_strumenti[sid] += 1
                if "compact" in json.dumps(a)[:200].lower():
                    compattazioni[sid] += 1
            if d.get("isCompactSummary") or d.get("type") == "compact-summary":
                compattazioni[sid] += 1
            m = d.get("message")
            if not isinstance(m, dict):
                continue
            cont = m.get("content")
            if isinstance(cont, list):
                for b in cont:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                        c = b.get("content")
                        esiti[b["tool_use_id"]] = (bool(b.get("is_error")),
                                                   (c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))[:400])
            u = m.get("usage")
            if not isinstance(u, dict) or (m.get("model") or "") == "<synthetic>":
                continue
            mid, ts = m.get("id"), pts(d.get("timestamp"))
            if not sid or not mid or ts is None:
                continue
            tools = []
            if isinstance(cont, list):
                for b in cont:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tools.append(((b.get("name") or "?").lower(), det_di(b.get("input")), b.get("id")))
            q = (int(u.get("input_tokens") or 0), int(u.get("cache_read_input_tokens") or 0),
                 int(u.get("cache_creation_input_tokens") or 0), int(u.get("output_tokens") or 0))
            r = chiamate.get((sid, mid))
            if r is None:
                chiamate[(sid, mid)] = {"sid": sid, "ts": ts, "tools": list(tools), "q": q}
            else:
                r["ts"] = min(r["ts"], ts)
                r["tools"].extend(tools)
                r["q"] = q

sess = defaultdict(list)
for r in chiamate.values():
    sess[r["sid"]].append(r)
for s in sess:
    sess[s].sort(key=lambda r: r["ts"])


def pes(q):
    i, cr, cw, o = q
    return i * PESI["input"] + cr * PESI["cache_read"] + cw * PESI["cache_write"] + o * PESI["output"]


def marg(q):
    i, cr, cw, o = q
    return i * PESI["input"] + cw * PESI["cache_write"] + o * PESI["output"]


TOT_P = sum(pes(r["q"]) for r in chiamate.values())
TOT_M = sum(marg(r["q"]) for r in chiamate.values())
print("chiamate %d, sessioni %d, pesati %.1f M, marginali %.1f M"
      % (len(chiamate), len(sess), TOT_P / 1e6, TOT_M / 1e6))
print()

# =============================================================================
print("=" * 76)
print("A) S1 IN MARGINALE — l'elenco sta nel prefisso cacheabile")
print("=" * 76)
tot_cw = sum(r["q"][2] for r in chiamate.values())
tot_cr = sum(r["q"][1] for r in chiamate.values())
print("  cache_write TOTALE (contesto messo in cache) %12d token  = %.1f M pesati"
      % (tot_cw, tot_cw * PESI["cache_write"] / 1e6))
print("  cache_read  TOTALE (contesto riletto)        %12d token  = %.1f M pesati"
      % (tot_cr, tot_cr * PESI["cache_read"] / 1e6))
print("  -> la rilettura costa 1/10, la scrittura in cache costa 1,25.")
print()
n_delta = sum(delta_strumenti.values())
sess_con_delta = len([s for s in delta_strumenti if delta_strumenti[s] > 1])
print("  L'elenco strumenti CAMBIA a meta' sessione: %d volte in totale," % n_delta)
print("  in %d sessioni piu' di una volta. Ogni cambio invalida la cache a valle." % sess_con_delta)
print()
ELENCO_TOK = 2135      # mediana misurata in 08_
print("  Stima onesta del costo di un elenco (mediana ~%d token):" % ELENCO_TOK)
print("     una volta, in cache_write:      %8.0f pesati" % (ELENCO_TOK * PESI["cache_write"]))
print("     riletto per 300 turni:          %8.0f pesati" % (ELENCO_TOK * PESI["cache_read"] * 300))
print("     rimesso in cache a ogni cambio: %8.0f pesati x %d cambi medi"
      % (ELENCO_TOK * PESI["cache_write"], n_delta / max(1, len(sess))))
print()
print("  IN BASE MARGINALE (senza rilettura), per sessione:")
cambi_medi = 1 + n_delta / max(1, len(sess))
costo_marg = ELENCO_TOK * PESI["cache_write"] * cambi_medi
print("     %.0f pesati marginali per sessione, non 64.000." % costo_marg)
print("     Su %d sessioni: %.2f M marginali = %.2f%% della spesa marginale."
      % (len(sess), costo_marg * len(sess) / 1e6, 100 * costo_marg * len(sess) / TOT_M))
print("     NOTA: quota degli strumenti MAI usati = 92,4%% -> %.2f%% attribuibile a S1"
      % (100 * costo_marg * len(sess) * 0.924 / TOT_M))
print()

# =============================================================================
print("=" * 76)
print("B) S3 CON IL FILTRO — le riletture dopo una scrittura non sono sprechi")
print("=" * 76)
tot_let = ril_grezze = ril_dopo_scrittura = ril_vere = 0
esempi = []
for s, lista in sess.items():
    ultima_lettura = {}
    ultima_scrittura = {}
    for idx, r in enumerate(lista):
        for nome, det, tid in r["tools"]:
            if not det:
                continue
            if nome in ("write", "edit", "notebookedit", "multiedit"):
                ultima_scrittura[det] = idx
            if nome != "read":
                continue
            tot_let += 1
            if det in ultima_lettura:
                ril_grezze += 1
                sc = ultima_scrittura.get(det)
                if sc is not None and sc > ultima_lettura[det]:
                    ril_dopo_scrittura += 1
                else:
                    ril_vere += 1
                    dim = len(esiti.get(tid, (False, ""))[1])
                    if dim > 300:
                        esempi.append((dim, det))
            ultima_lettura[det] = idx
print("  letture con percorso                       %6d" % tot_let)
print("  riletture GREZZE (come misurate prima)     %6d  (%.1f%%)"
      % (ril_grezze, 100 * ril_grezze / max(1, tot_let)))
print("  di cui dopo una SCRITTURA sullo stesso file %5d  <- lavoro sano, il file e' cambiato"
      % ril_dopo_scrittura)
print("  riletture VERE (nulla e' cambiato)         %6d  (%.1f%%)"
      % (ril_vere, 100 * ril_vere / max(1, tot_let)))
print()
print("  -> il 35%% era gonfiato: lo spreco vero e' il %.1f%% delle letture."
      % (100 * ril_vere / max(1, tot_let)))
print("  (le compattazioni non sono filtrate: %d sessioni ne hanno almeno una,"
      % len([s for s in compattazioni if compattazioni[s]]))
print("   quindi la cifra vera e' ancora un po' piu' bassa)")
print()

# =============================================================================
print("=" * 76)
print("C) S4 CON GLI ESITI CLASSIFICATI e il minimo di campione")
print("=" * 76)


def classe(testo):
    t = (testo or "").lower()
    if "doesn't want to proceed" in t or "rejected" in t or "user has requested" in t:
        return "rifiuto dell'utente"
    if "not found" in t or "no such file" in t or "does not exist" in t or "non trovat" in t:
        return "oggetto non trovato"
    if "permission" in t or "denied" in t or "not allowed" in t:
        return "permesso negato"
    if "timeout" in t or "timed out" in t:
        return "scaduto"
    return "errore vero"


per_tool = defaultdict(lambda: defaultdict(int))
usi = Counter()
for r in chiamate.values():
    for nome, det, tid in r["tools"]:
        if tid not in esiti:
            continue
        usi[nome] += 1
        fall, testo = esiti[tid]
        if fall:
            per_tool[nome][classe(testo)] += 1
tot_classi = Counter()
for n, dd in per_tool.items():
    for k, v in dd.items():
        tot_classi[k] += v
print("  Come si dividono i 475 fallimenti:")
for k, v in tot_classi.most_common():
    print("     %-24s %4d  (%.1f%%)" % (k, v, 100 * v / sum(tot_classi.values())))
print()
MIN_USI = 20
print("  S4 con il proprio minimo di campione applicato (>= %d usi):" % MIN_USI)
print("    strumento                          usi  falliti  di cui errori veri   tasso vero")
righe4 = []
for nome, n in usi.most_common():
    if n < MIN_USI:
        continue
    dd = per_tool.get(nome, {})
    tot_f = sum(dd.values())
    veri = dd.get("errore vero", 0) + dd.get("scaduto", 0)
    righe4.append((veri / n, nome, n, tot_f, veri))
righe4.sort(reverse=True)
for t, nome, n, tot_f, veri in righe4[:10]:
    print("    %-32s %5d %8d %18d %10.1f%%" % (nome[:32], n, tot_f, veri, 100 * t))
print()
sotto = [n for n, c in usi.items() if c < MIN_USI and per_tool.get(n)]
print("  strumenti ESCLUSI perche' sotto %d usi: %d (fra cui il 100%% di readmcpresourcetool, n=5)"
      % (MIN_USI, len(sotto)))
print()

# =============================================================================
print("=" * 76)
print("D) S2 — QUANTO COSTA RICOMINCIARE? (il controfattuale mancante)")
print("=" * 76)
print("  Ricominciare sposta il costo dalla rilettura (0,1) alla rimessa in cache (1,25).")
print("  Il prezzo del riavvio si legge nel cache_write dei primi turni.")
print()
print("  turno | chiamate | cache_write medio | cache_read medio | marginale medio")
for a, b in ((1, 3), (4, 10), (11, 30), (31, 60), (61, 120), (121, 300), (301, 99999)):
    cw = cr = mg = n = 0
    for s, lista in sess.items():
        for i, r in enumerate(lista):
            if a <= i + 1 <= b:
                cw += r["q"][2]; cr += r["q"][1]; mg += marg(r["q"]); n += 1
    if n:
        print("  %4d-%-5d| %8d | %17.0f | %16.0f | %15.0f"
              % (a, b, n, cw / n, cr / n, mg / n))
print()
print("  Costo di avviare una sessione = cache_write dei primi 3 turni, in pesati:")
cw3 = n3 = 0
for s, lista in sess.items():
    for r in lista[:3]:
        cw3 += r["q"][2] * PESI["cache_write"]; n3 += 1
print("     %.0f pesati per chiamata nei primi 3 turni (%d chiamate)" % (cw3 / max(1, n3), n3))
print()

# =============================================================================
print("=" * 76)
print("E) PERCHE' LA QUOTA DI RILETTURA SCENDE DOPO IL TURNO 300")
print("=" * 76)
print("  turno | cache_read medio | output medio | il contesto e' fermo o cresce?")
for a, b in ((1, 10), (11, 30), (31, 60), (61, 120), (121, 300), (301, 99999)):
    cr = out = n = 0
    for s, lista in sess.items():
        for i, r in enumerate(lista):
            if a <= i + 1 <= b:
                cr += r["q"][1]; out += r["q"][3]; n += 1
    if n:
        print("  %4d-%-5d| %16.0f | %12.0f |" % (a, b, cr / n, out / n))
print()
print("  Se cache_read smette di crescere ma output cresce, la QUOTA di rilettura")
print("  scende senza che il costo scenda: e' la finestra di contesto che satura")
print("  (o una compattazione), non l'agente che diventa piu' efficiente.")
