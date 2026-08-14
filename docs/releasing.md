# Rilasciare StarkEno

La pubblicazione è un'azione manuale separata. Questo documento non esegue push, non
crea repository e non modifica branch protection.

1. Verifica che versione Python, `.codex-plugin/plugin.json` e changelog coincidano.
2. Installa l'ambiente vincolato ed esegui suite, stress e audit:

   ```bash
   python -m pip install -c requirements/ci.txt -e ".[dev]"
   python -m pytest -q -W error
   python scripts/stress_concorrenza.py
   python -m pip check
   python -m pip_audit -r requirements/ci.txt
   ```

3. Esegui gli scanner e costruisci uno snapshot nuovo fuori dal repository:

   ```bash
   python scripts/verifica_segreti.py --tracked
   python scripts/verifica_pubblicazione.py
   python scripts/costruisci_snapshot_pubblico.py <directory-vuota>
   ```

4. Dentro lo snapshot ripeti scanner, `python -m build` e suite strict.
5. Installa il wheel in un virtualenv vuoto e prova `starkeno doctor --json`,
   `starkeno report --no-open` e una migrazione su database temporaneo.
6. Attendi che i job `tests`, `package`, `audit` e `stress` siano verdi sulla commit.
7. Solo dopo revisione umana crea il tag SemVer e la release dal contenuto dello
   snapshot. Qualunque comando di push resta intenzionalmente fuori da questa procedura.
