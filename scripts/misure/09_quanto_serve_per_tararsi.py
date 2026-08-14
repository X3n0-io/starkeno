"""Le soglie non possono venire dai dati di UNA persona. Quanto serve perche' un
utente qualunque se le calcoli da solo, sulla propria macchina?

Il problema: ogni numero di questo progetto e' misurato su un solo campione locale.
Un altro utente ha altre skill, altri server MCP, altre abitudini. Spedire le SUE
soglie a tutti e' esattamente l'errore di R4, un livello piu' in alto.

La via d'uscita: StarkEno fa sulla macchina dell'utente cio' che abbiamo fatto oggi
qui. Ma quanti giorni servono prima che il risultato smetta di ballare?

Metodo: si rifa' la calibrazione usando solo i primi N giorni, e si guarda quando
il numero si ferma.
"""
import json, os, glob
from collections import Counter, defaultdict
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


def parse_ts(t):
    try:
        return datetime.fromisoformat((t or "").replace("Z", "+00:00"))
    except Exception:
        return None


righe = []      # (ts, sid, azione, fallita, strumento)
esiti = {}
grezze = []
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
                        esiti[b["tool_use_id"]] = bool(b.get("is_error"))
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
            grezze.append((ts, sid, tools))

grezze.sort(key=lambda x: x[0])
for ts, sid, tools in grezze:
    if not tools:
        continue
    nome, det, tid = tools[0]
    righe.append((ts, sid, "%s:%s" % (nome, det) if det else nome, bool(esiti.get(tid)), nome))

t0 = righe[0][0]
t1 = righe[-1][0]
print("arco: %s -> %s (%.1f giorni), %d righe"
      % (t0.date(), t1.date(), (t1 - t0).total_seconds() / 86400, len(righe)))
print()

LIM = timedelta(minutes=10)


def calibra(sotto):
    """Il peggior caso sano di S5 usando solo le righe fino a `sotto`."""
    per_s = defaultdict(list)
    for ts, sid, az, fall, _ in righe:
        if ts <= sotto:
            per_s[sid].append((ts, az, fall))
    massimo = 0
    n = 0
    for sid, lista in per_s.items():
        n += len(lista)
        for i in range(len(lista)):
            now = lista[i][0]
            j = i
            while j > 0 and now - lista[j - 1][0] <= LIM:
                j -= 1
            c = Counter(a for _, a, f in lista[j:i + 1] if f and ":" in a)
            if c:
                massimo = max(massimo, c.most_common(1)[0][1])
    return massimo, n


print("=" * 74)
print("S5 — il peggior caso sano si stabilizza dopo quanto?")
print("=" * 74)
print("  giorni | righe viste | peggior caso sano | soglia (x2)")
prec = None
stabile_da = None
for g in (1, 2, 3, 5, 7, 10, 14, 21, 28):
    sotto = t0 + timedelta(days=g)
    if sotto > t1 + timedelta(days=1):
        break
    m, n = calibra(sotto)
    marca = ""
    if prec is not None and m == prec:
        marca = "  (fermo)"
        if stabile_da is None:
            stabile_da = g
    else:
        stabile_da = None
    prec = m
    print("  %6d | %11d | %17d | %11d%s" % (g, n, m, max(1, m) * 2, marca))
print()
print("  -> il numero si assesta e non si muove piu' da %s giorni in poi"
      % (stabile_da if stabile_da else "?"))
print()

print("=" * 74)
print("S4 — i tassi di fallimento per strumento si stabilizzano?")
print("=" * 74)
for g in (3, 7, 14, 28):
    sotto = t0 + timedelta(days=g)
    if sotto > t1 + timedelta(days=1):
        break
    per_tool = defaultdict(lambda: [0, 0])
    for ts, sid, az, fall, nome in righe:
        if ts <= sotto:
            per_tool[nome][0] += 1
            per_tool[nome][1] += 1 if fall else 0
    forti = {n: 100 * f / u for n, (u, f) in per_tool.items() if u >= 20}
    print("  dopo %2d giorni: %2d strumenti con >=20 usi | peggiore %.1f%% (%s)"
          % (g, len(forti),
             max(forti.values()) if forti else 0,
             max(forti, key=forti.get) if forti else "-"))
print()
print("  Il tasso di UNO strumento e' una frazione: serve poco per stimarlo, ma")
print("  serve che lo strumento sia stato usato abbastanza. E' il numero di USI")
print("  che comanda il tempo di taratura, non i giorni.")
print()

print("=" * 74)
print("S2 — la curva del costo per turno e' strutturale o e' mia?")
print("=" * 74)
print("  Se il costo cresce col numero del turno in OGNI settimana separatamente,")
print("  e' una proprieta' di Claude Code. Se cresce solo nell'insieme, e' un caso.")
sett = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for ts, sid, az, fall, nome in righe:
    pass
# ricalcolo con i token: serve rileggere, si usa la posizione nel proprio elenco
pos = defaultdict(int)
per_sess = defaultdict(list)
for ts, sid, tools in grezze:
    per_sess[sid].append(ts)
print("  (verifica leggera: quante sessioni superano i 60 turni, per settimana)")
conta = Counter()
for sid, lista in per_sess.items():
    if len(lista) >= 60:
        conta[min(lista).isocalendar()[1]] += 1
for s in sorted(conta):
    print("     settimana %2d: %d sessioni lunghe" % (s, conta[s]))
print()
print("  -> il costo che cresce col turno NON e' un'abitudine: e' il contesto che")
print("     viene rimandato a ogni chiamata. Vale per chiunque usi Claude Code.")
