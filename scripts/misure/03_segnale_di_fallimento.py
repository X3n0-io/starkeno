"""Il fallimento separa "chi lavora" da "chi e' bloccato"?

Ripetere e' normale. L'ipotesi da provare: ripetere OTTENENDO OGNI VOLTA UN ERRORE
non lo e'. Se l'ipotesi regge, le finestre molto ripetitive si dividono in due
gruppi netti: quasi tutte a zero errori (lavoro), poche con errori (blocco).
Se invece hanno tutte zero errori, il segnale non separa niente e va scartato.
"""
import json, os, glob
from collections import defaultdict, Counter
from datetime import datetime, timedelta

ROOT = os.path.expanduser("~/.claude/projects")
CHIAVI = ("file_path", "path", "notebook_path", "pattern", "command", "url",
          "query", "prompt", "skill", "subagent_type", "file", "filePath")
FINESTRA_MIN = 5      # LOOP_WINDOW_MINUTES
MIN_REPEATS = 10      # LOOP_MIN_REPEATS


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


# ---- passata 1: le azioni (dai messaggi dell'assistente, con usage) ----------
# ---- passata 2: gli esiti (dai messaggi dell'utente, blocchi tool_result) ----
azioni_per_sessione = defaultdict(list)   # sid -> [(ts, testo, tool_use_id)]
esiti = {}                                # tool_use_id -> (is_error, testo_errore)

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

            usage = msg.get("usage")
            if isinstance(usage, dict) and (msg.get("model") or "") != "<synthetic>":
                sid = d.get("sessionId")
                ts = parse_ts(d.get("timestamp"))
                if sid and ts:
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "tool_use":
                            nome = (c.get("name") or "?").lower()
                            det = dettaglio_di(c.get("input"))
                            testo = "%s:%s" % (nome, det) if det else nome
                            azioni_per_sessione[sid].append((ts, testo, c.get("id")))

            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    tid = c.get("tool_use_id")
                    if tid:
                        esiti[tid] = (bool(c.get("is_error")), str(c.get("content"))[:200])

tot_azioni = sum(len(v) for v in azioni_per_sessione.values())
con_esito = sum(1 for v in azioni_per_sessione.values() for _, _, i in v if i in esiti)
falliti = sum(1 for v in azioni_per_sessione.values()
              for _, _, i in v if esiti.get(i, (False, ""))[0])
print("azioni con strumento     %6d" % tot_azioni)
print("di cui con esito noto    %6d  (%.1f%%)" % (con_esito, 100 * con_esito / tot_azioni))
print("di cui FALLITE           %6d  (%.1f%% del totale)" % (falliti, 100 * falliti / tot_azioni))
print()

# ---- che tipo di errori sono? -----------------------------------------------
tipi = Counter()
for v in azioni_per_sessione.values():
    for _, _, i in v:
        e = esiti.get(i)
        if e and e[0]:
            t = e[1]
            if "doesn't want to proceed" in t or "rejected" in t:
                tipi["utente ha rifiutato"] += 1
            elif t.startswith("Exit code") or "Error" in t[:40] or "error" in t[:40]:
                tipi["errore dello strumento"] += 1
            else:
                tipi["altro"] += 1
print("Che tipo di fallimenti sono:", dict(tipi))
print()

# ---- le finestre di ripetizione, con e senza errori -------------------------
print("=" * 76)
print("OGNI FINESTRA DI 5 MINUTI IN CUI UN'AZIONE SI RIPETE >= %d VOLTE" % MIN_REPEATS)
print("(e' esattamente cio' che oggi fa scattare R1 rilevatore A)")
print("=" * 76)
limite = timedelta(minutes=FINESTRA_MIN)
trovate = []
for sid, azioni in azioni_per_sessione.items():
    azioni.sort(key=lambda x: x[0])
    visti = set()
    for i in range(len(azioni)):
        now = azioni[i][0]
        j = i
        while j > 0 and now - azioni[j - 1][0] <= limite:
            j -= 1
        fin = azioni[j: i + 1]
        conteggi = Counter(t for _, t, _ in fin if ":" in t)
        if not conteggi:
            continue
        testo, quante = conteggi.most_common(1)[0]
        if quante < MIN_REPEATS:
            continue
        chiave = (sid, testo)
        if chiave in visti:
            continue
        visti.add(chiave)
        ids = [k for _, t, k in fin if t == testo]
        err = sum(1 for k in ids if esiti.get(k, (False, ""))[0])
        noti = sum(1 for k in ids if k in esiti)
        trovate.append((sid, testo, quante, err, noti))

trovate.sort(key=lambda r: (-r[3], -r[2]))
print("Finestre trovate: %d" % len(trovate))
print()
dist = Counter(r[3] for r in trovate)
print("Quante di queste finestre contengono N ripetizioni FALLITE:")
for n in sorted(dist):
    print("   %2d errori -> %3d finestre" % (n, dist[n]))
print()
print("Le 20 finestre con piu' errori:")
print("  ripet | falliti | azione")
for sid, testo, quante, err, noti in trovate[:20]:
    print("  %5d | %7d | %s" % (quante, err, testo[:88]))
print()
print("Le 10 finestre con piu' ripetizioni (a prescindere dagli errori):")
for sid, testo, quante, err, noti in sorted(trovate, key=lambda r: -r[2])[:10]:
    print("  %5d | %7d | %s" % (quante, err, testo[:88]))
print()

# ---- e se guardassimo le ripetizioni CONSECUTIVE fallite? -------------------
print("=" * 76)
print("SEQUENZE DI AZIONI FALLITE UNA DOPO L'ALTRA (a prescindere da R1)")
print("=" * 76)
serie = []
for sid, azioni in azioni_per_sessione.items():
    corrente = []
    for ts, testo, tid in azioni:
        if esiti.get(tid, (False, ""))[0]:
            corrente.append((ts, testo))
        else:
            if len(corrente) >= 2:
                serie.append((sid, list(corrente)))
            corrente = []
    if len(corrente) >= 2:
        serie.append((sid, list(corrente)))
serie.sort(key=lambda s: -len(s[1]))
print("Serie di >=2 fallimenti consecutivi: %d" % len(serie))
d = Counter(len(s[1]) for s in serie)
print("   lunghezza -> quante:", dict(sorted(d.items())))
print()
for sid, s in serie[:6]:
    arco = (s[-1][0] - s[0][0]).total_seconds()
    print("  %d fallimenti in %.0fs, sessione %s:" % (len(s), arco, sid[:8]))
    for ts, testo in s[:8]:
        print("      %s" % testo[:88])
    print()
