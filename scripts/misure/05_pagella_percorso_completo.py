"""La pagella delle quattro regole sui dati veri, percorso completo.

Carica i transcript veri in un database usa-e-getta con i timestamp VERI (non
compressi, come invece faceva la simulazione precedente), poi fa girare il
supervisore vero e conta chi parla, quando, e dicendo cosa.

Asse: il PROGETTO (cwd), come da spec §5. Grana: (sessionId, message.id), §4.
"""
import json, os, sys, glob, tempfile, subprocess, shutil
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone

# La radice si ricava da DOVE STA QUESTO FILE, non dalla macchina di chi l'ha scritto:
# `scripts/misure/x.py` -> su di tre. Cablarla rende lo script ineseguibile a chiunque
# altro, e queste misure esistono proprio per essere rieseguite.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(tempfile.gettempdir(), "pagella_starkeno.db")
for ext in ("", "-wal", "-shm"):
    if os.path.exists(DB + ext):
        os.remove(DB + ext)
os.environ["STARKENO_DB_PATH"] = DB

sys.path.insert(0, REPO)

# schema creato da Alembic, come in produzione
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   cwd=REPO, capture_output=True, text=True,
                   env={**os.environ, "STARKENO_DB_PATH": DB})
if r.returncode != 0:
    print("alembic ha fallito:\n", r.stdout[-3000:], r.stderr[-3000:])
    sys.exit(1)
print("schema creato con Alembic\n")

from starkeno import db, config as cfg
from starkeno.supervisor import run_once

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


# ---- ingestione alla grana (sessionId, message.id) ---------------------------
chiamate = {}
usage_diversi = 0
ultimo_e_massimo = 0
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
            u = m.get("usage")
            if not isinstance(u, dict) or (m.get("model") or "") == "<synthetic>":
                continue
            sid, mid, ts = d.get("sessionId"), m.get("id"), parse_ts(d.get("timestamp"))
            if not sid or not mid or ts is None:
                continue
            tool = None
            cont = m.get("content")
            if isinstance(cont, list):
                for c in cont:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        n = (c.get("name") or "?").lower()
                        det = dettaglio_di(c.get("input"))
                        tool = "%s:%s" % (n, det) if det else n
                        break
            quadrupla = (int(u.get("input_tokens") or 0),
                         int(u.get("cache_read_input_tokens") or 0),
                         int(u.get("cache_creation_input_tokens") or 0),
                         int(u.get("output_tokens") or 0))
            rec = chiamate.get((sid, mid))
            if rec is None:
                chiamate[(sid, mid)] = {
                    "sid": sid, "ts": ts, "cwd": d.get("cwd") or "?",
                    "modello": m.get("model") or "?", "azione": tool,
                    "usage": quadrupla, "usage_visti": [quadrupla],
                }
            else:
                rec["ts"] = min(rec["ts"], ts)
                if rec["azione"] is None:
                    rec["azione"] = tool
                rec["usage_visti"].append(quadrupla)
                rec["usage"] = quadrupla          # l'ULTIMA vince (§4)

# verifica la misura lasciata aperta dal §4: l'ultima riga e' anche la piu' alta?
for rec in chiamate.values():
    v = rec["usage_visti"]
    if len(set(v)) > 1:
        usage_diversi += 1
        if sum(v[-1]) == max(sum(x) for x in v):
            ultimo_e_massimo += 1
print("chiamate API: %d" % len(chiamate))
print("con usage DIVERSI fra le righe: %d (%.1f%%)"
      % (usage_diversi, 100 * usage_diversi / len(chiamate)))
print("   di queste, l'ULTIMA riga e' anche la piu' alta: %d (%.1f%%)"
      % (ultimo_e_massimo, 100 * ultimo_e_massimo / max(1, usage_diversi)))
print()


def progetto_di(cwd):
    p = (cwd or "?").rstrip("\\/").replace("/", "\\")
    return p.split("\\")[-1] or "?"


# ---- scrittura nel database, con i timestamp VERI ---------------------------
fabbrica = db.make_session_factory(DB)
sess = fabbrica()

righe = sorted(chiamate.values(), key=lambda r: r["ts"])
oggetti = []
for r in righe:
    inp, cr, cw, out = r["usage"]
    oggetti.append(db.AgentAction(
        project=db.normalizza_progetto(progetto_di(r["cwd"])),
        action=r["azione"] or "risposta",
        model_used=r["modello"],
        tokens_used=inp + cr + cw + out,
        cache_read_tokens=cr, cache_write_tokens=cw, output_tokens=out,
        timestamp=r["ts"].astimezone(timezone.utc),
    ))
sess.bulk_save_objects(oggetti)
sess.commit()
print("scritte %d azioni. Progetti distinti: %d"
      % (len(oggetti), len({o.project for o in oggetti})))
for nome, n in Counter(o.project for o in oggetti).most_common():
    print("   %-34s %5d azioni" % (nome, n))
print()

# ---- il supervisore gira, ora dopo ora ---------------------------------------
t0, t1 = righe[0]["ts"], righe[-1]["ts"]
print("arco temporale reale: da %s a %s (%.1f giorni)"
      % (t0.date(), t1.date(), (t1 - t0).total_seconds() / 86400))

passo = timedelta(hours=6)
now = t0 + passo
giri = 0
falliti = 0
stati = Counter()
while now <= t1 + passo:
    res = run_once(sess, now=now.astimezone(timezone.utc), config=cfg)
    giri += 1
    falliti += getattr(res, "rules_failed", 0) or 0
    now += passo
print("giri di supervisore: %d, regole in errore: %d" % (giri, falliti))
print()

# ---- la pagella --------------------------------------------------------------
righe_alert = sess.execute(db.text(
    "SELECT rule, project, status, detail, first_seen, last_seen "
    "FROM alerts ORDER BY rule, project")).all()
print("=" * 78)
print("ALERT PRODOTTI: %d" % len(righe_alert))
print("=" * 78)
per_regola = Counter(a.rule for a in righe_alert)
for regola in ("loop", "expensive_model", "spend_anomaly", "heavy_spend", "data_quality"):
    print("  %-16s %d" % (regola, per_regola.get(regola, 0)))
print()
for a in righe_alert:
    print("  [%s] %-16s %-28s %s" % (a.status, a.rule, a.project, (a.detail or "")[:110]))
print()

righe_stato = sess.execute(db.text(
    "SELECT rule, project, state, reason FROM rule_status ORDER BY rule, project")).all()
print("=" * 78)
print("ULTIMO STATO DI OGNI REGOLA SU OGNI PROGETTO")
print("=" * 78)
c = Counter((r.rule, r.state) for r in righe_stato)
for (regola, stato), n in sorted(c.items()):
    print("  %-16s %-16s %d" % (regola, stato, n))
print()
print("Le ragioni di chi non ha potuto valutare:")
motivi = Counter((r.rule, (r.reason or "")[:80]) for r in righe_stato
                 if r.state not in ("ok", "violation"))
for (regola, motivo), n in motivi.most_common(20):
    print("  %-16s x%-3d %s" % (regola, n, motivo))
