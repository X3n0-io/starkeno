# -*- coding: utf-8 -*-
"""Stress della concorrenza: cinque processi su un solo file SQLite.

    python scripts/stress_concorrenza.py

Non sta nella suite di pytest perche' avvia processi veri e ci mette qualche secondo, ma
verifica la premessa su cui poggia tutta la gestione della concorrenza — WAL, busy
timeout, upsert con rollback — che nessun test unitario esercita: SQLite resta a
scrittore singolo, e senza timeout esplicito il perdente riceve subito
"database is locked".

La proprieta' che conta e' una sola: **zero log falliti**. Un layer di osservabilita' che
rompe la cosa che osserva e' peggio che inutile, perche' si perdono sia i dati sia il
lavoro dell'agente.

Misurato il 07/08/2026 — 3 scrittori + supervisore + dashboard, 4,4 s:
    900/900 log riusciti, latenza peggiore 0,128 s, 0 giri falliti,
    0 risposte non-200 su 160, integrity_check ok.
"""
import multiprocessing as mp
import os
import sys
import time

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def scrittore(percorso_db, quante, risultati, indice):
    """Simula un agente che logga senza sosta: e' l'operazione critica."""
    sys.path.insert(0, RADICE)
    os.environ["STARKENO_DB_PATH"] = percorso_db
    from starkeno.db import make_session_factory
    import starkeno.mcp_server as m

    m._session_factory = make_session_factory(percorso_db)
    falliti, latenza_max = 0, 0.0
    for i in range(quante):
        t = time.perf_counter()
        try:
            m.log_agent_action_impl("agente-%d" % indice, "read:file_%d.py" % i,
                                    "claude-opus-4-5", 3000)
        except Exception as e:
            falliti += 1
            if falliti <= 2:
                print("   scrittore %d: %s" % (indice, e))
        latenza_max = max(latenza_max, time.perf_counter() - t)
    risultati[indice] = (falliti, latenza_max)


def supervisore(percorso_db, giri, risultati):
    sys.path.insert(0, RADICE)
    os.environ["STARKENO_DB_PATH"] = percorso_db
    from datetime import datetime, timedelta, timezone
    from starkeno.db import make_session_factory
    from starkeno.config import snapshot
    from starkeno.supervisor import run_once

    S = make_session_factory(percorso_db)
    C = snapshot()
    falliti = 0
    for g in range(giri):
        s = S()
        try:
            run_once(s, now=datetime.now(timezone.utc) + timedelta(minutes=g), config=C)
        except Exception as e:
            falliti += 1
            print("   supervisore: %s" % e)
        finally:
            s.close()
        time.sleep(0.05)
    risultati["supervisore"] = falliti


def lettore(percorso_db, letture, risultati):
    sys.path.insert(0, RADICE)
    os.environ["STARKENO_DB_PATH"] = percorso_db
    from starkeno.db import make_session_factory
    import starkeno.api as api
    from fastapi.testclient import TestClient

    api._session_factory = make_session_factory(percorso_db)
    c = TestClient(api.app)
    falliti = 0
    for _ in range(letture):
        for rotta in ("/api/agents", "/api/alerts", "/api/rule-status",
                      "/api/supervisor/status"):
            if c.get(rotta).status_code != 200:
                falliti += 1
        time.sleep(0.01)
    risultati["lettore"] = falliti


if __name__ == "__main__":
    import shutil
    import subprocess
    import tempfile

    cartella = tempfile.mkdtemp()
    db = os.path.join(cartella, "starkeno.db")
    ambiente = {**os.environ, "STARKENO_DB_PATH": db, "PYTHONPATH": RADICE}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   cwd=RADICE, env=ambiente, capture_output=True)

    with mp.Manager() as manager:
        risultati = manager.dict()
        processi = [
            mp.Process(target=scrittore, args=(db, 300, risultati, 0)),
            mp.Process(target=scrittore, args=(db, 300, risultati, 1)),
            mp.Process(target=scrittore, args=(db, 300, risultati, 2)),
            mp.Process(target=supervisore, args=(db, 12, risultati)),
            mp.Process(target=lettore, args=(db, 40, risultati)),
        ]
        inizio = time.perf_counter()
        for p in processi:
            p.start()
        for p in processi:
            p.join(timeout=300)
        durata = time.perf_counter() - inizio
        esiti = dict(risultati)

    print()
    print("5 processi in parallelo su un solo file SQLite, %.1f s" % durata)
    totale_falliti = 0
    for i in range(3):
        falliti, latenza = esiti.get(i, (None, None))
        totale_falliti += falliti or 0
        print("  scrittore %d: %3d/300 log falliti | latenza peggiore %.3f s"
              % (i, falliti, latenza))
    print("  supervisore: %s giri falliti su 12" % esiti.get("supervisore"))
    print("  lettore    : %s richieste HTTP non-200 su 160" % esiti.get("lettore"))

    import sqlite3
    c = sqlite3.connect(db)
    print("  righe scritte: %d (attese 900)" %
          c.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0])
    print("  journal_mode : %s" % c.execute("PRAGMA journal_mode").fetchone()[0])
    print("  integrita'   : %s" % c.execute("PRAGMA integrity_check").fetchone()[0])
    print("  alert aperti : %d" % c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
    c.close()
    shutil.rmtree(cartella, ignore_errors=True)
