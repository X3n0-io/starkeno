"""Quanto di cio' che hai installato usi davvero?

Nasce dalla dichiarazione di scopo del progetto: StarkEno deve suggerire quali
skill e plugin installare, e quali usare al posto di altri.

La forma misurabile di quella domanda e' il DIVARIO fra offerto e usato. Ogni
strumento offerto, ogni skill elencata, ogni server MCP collegato occupa spazio
nel contesto di OGNI conversazione — e il contesto si ripaga a ogni turno.
"""
import json, os, glob
from collections import Counter, defaultdict

ROOT = os.path.expanduser("~/.claude/projects")

offerti = Counter()          # nome strumento -> in quante conversazioni e' stato offerto
usati = Counter()            # nome strumento -> quante volte e' stato invocato
skill_elencate = Counter()
skill_usate = Counter()
serve_auth = Counter()
mcp_in_attesa = Counter()
righe_listing = 0
peso_listing = []            # caratteri delle liste, per stimare l'ingombro

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

            a = d.get("attachment")
            if isinstance(a, dict):
                t = a.get("type")
                if t == "deferred_tools_delta":
                    for n in (a.get("addedNames") or []):
                        offerti[n] += 1
                    for s in (a.get("needsAuthMcpServers") or []):
                        serve_auth[s] += 1
                    for s in (a.get("pendingMcpServers") or []):
                        mcp_in_attesa[s] += 1
                    peso_listing.append(len(json.dumps(a.get("addedLines") or [], ensure_ascii=False)))
                elif t == "skill_listing":
                    righe_listing += 1
                    testo = json.dumps(a, ensure_ascii=False)
                    peso_listing.append(len(testo))
                    for chiave in ("skills", "skillNames", "names", "listing", "content"):
                        v = a.get(chiave)
                        if isinstance(v, list):
                            for s in v:
                                nome = s if isinstance(s, str) else (s.get("name") if isinstance(s, dict) else None)
                                if nome:
                                    skill_elencate[nome] += 1
                        elif isinstance(v, str):
                            for riga in v.splitlines():
                                riga = riga.strip().lstrip("-* ")
                                if riga and ":" in riga[:70]:
                                    skill_elencate[riga.split(":")[0].strip()] += 1

            m = d.get("message")
            if not isinstance(m, dict):
                continue
            if (m.get("model") or "") == "<synthetic>":
                continue
            cont = m.get("content")
            if isinstance(cont, list):
                for b in cont:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        nome = b.get("name") or "?"
                        usati[nome] += 1
                        if nome.lower() == "skill":
                            inp = b.get("input") or {}
                            if isinstance(inp, dict) and inp.get("skill"):
                                skill_usate[inp["skill"]] += 1
            if d.get("attributionSkill"):
                skill_usate[d["attributionSkill"]] += 0   # registra il nome anche senza invocazione esplicita
                skill_usate[d["attributionSkill"]] += 1

print("=" * 76)
print("STRUMENTI: OFFERTI CONTRO USATI")
print("=" * 76)
mai = [n for n in offerti if n not in usati]
print("  strumenti distinti OFFERTI almeno una volta   %5d" % len(offerti))
print("  strumenti distinti effettivamente USATI       %5d" % len(usati))
print("  offerti e MAI usati                           %5d  (%.1f%%)"
      % (len(mai), 100 * len(mai) / max(1, len(offerti))))
print()
per_prefisso = defaultdict(lambda: [0, 0])
for n in offerti:
    fam = n.split("__")[1] if n.startswith("mcp__") and "__" in n[5:] else ("(nativo)" if not n.startswith("mcp__") else "?")
    per_prefisso[fam][0] += 1
    if n in usati:
        per_prefisso[fam][1] += 1
print("  Per server MCP — strumenti offerti / usati:")
print("    %-44s %8s %8s" % ("", "offerti", "usati"))
for fam, (o, u) in sorted(per_prefisso.items(), key=lambda kv: -kv[1][0])[:18]:
    stella = "   <-- zero" if u == 0 else ""
    print("    %-44s %8d %8d%s" % (str(fam)[:44], o, u, stella))
print()

print("=" * 76)
print("SERVER MCP CHE CHIEDONO AUTENTICAZIONE E NON POSSONO ESSERE USATI")
print("=" * 76)
print("  (peso morto certo: occupano posto e non funzionano)")
for s, n in serve_auth.most_common(20):
    usato = any(k.startswith("mcp__") and s.split(":")[-1].lower() in k.lower() for k in usati)
    print("    %-56s in %3d conversazioni  %s" % (s[:56], n, "" if not usato else "(usato lo stesso?)"))
print()
if mcp_in_attesa:
    print("  server ancora in connessione:", dict(mcp_in_attesa.most_common(6)))
    print()

print("=" * 76)
print("SKILL: ELENCATE CONTRO USATE")
print("=" * 76)
print("  skill distinte elencate nelle liste  %5d" % len(skill_elencate))
print("  skill distinte effettivamente usate  %5d" % len(skill_usate))
if skill_elencate:
    mai_s = [s for s in skill_elencate if s not in skill_usate]
    print("  elencate e MAI usate                 %5d  (%.1f%%)"
          % (len(mai_s), 100 * len(mai_s) / len(skill_elencate)))
print()
print("  Le skill che usi davvero:")
for s, n in skill_usate.most_common(18):
    print("    %-52s %5d" % (str(s)[:52], n))
print()

print("=" * 76)
print("QUANTO PESA L'ELENCO")
print("=" * 76)
if peso_listing:
    peso_listing.sort()
    med = peso_listing[len(peso_listing) // 2]
    print("  liste registrate: %d" % len(peso_listing))
    print("  dimensione mediana di una lista: %d caratteri (~%d token)" % (med, med // 4))
    print("  la piu' grande:                  %d caratteri (~%d token)"
          % (peso_listing[-1], peso_listing[-1] // 4))
    print()
    print("  ATTENZIONE ALLA LETTURA: questi sono gli ELENCHI registrati nel transcript,")
    print("  non la definizione completa degli strumenti nel prompt di sistema — quella")
    print("  il transcript non la scrive. E' un minimo dimostrabile, non il costo vero.")
