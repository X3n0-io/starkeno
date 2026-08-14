"""Quali harness StarkEno riconosce, e quali sa misurare.

**Qui non si legge niente.** Questo modulo contiene identita' e riconoscimento; i
lettori vivono in `transcript.py`, che resta puro. La separazione non e' estetica: se
il registro importasse i lettori e `transcript` importasse il registro avremmo un
ciclo, e la diagnostica ha bisogno del registro senza aver bisogno dei lettori.

Un harness NON misurabile sta comunque nel registro. Antigravity ne e' il motivo: il
suo transcript non contiene conteggi di token da nessuna parte — verificato il
14/08/2026 cercando per nome file e per contenuto in tutta la sua cartella dati, incluse
le chiavi native di Gemini `promptTokenCount`, `candidatesTokenCount` e
`cachedContentTokenCount`. Senza questa voce l'utente vedrebbe zero chiamate e
sospetterebbe un difetto di StarkEno: il silenzio indistinguibile dalla salute e' il
fallimento che questo progetto rifiuta ovunque.
"""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Harness:
    """Un agente di coding che StarkEno sa riconoscere."""

    nome: str
    riconosce: Callable[[dict], bool]
    # Il nome del lettore in `transcript`, non la funzione: tenere qui un riferimento
    # alla funzione richiederebbe l'import che questo modulo esiste per evitare.
    lettore: str = ""
    misurabile: bool = True
    motivo: str = ""


def _e_codex(voce: dict) -> bool:
    return voce.get("type") in {"session_meta", "turn_context"}


def _e_antigravity(voce: dict) -> bool:
    """I passi dell'agente: `step_index` e `created_at`, mai un `message`."""
    return "step_index" in voce and "created_at" in voce and "message" not in voce


def _e_claude_code(voce: dict) -> bool:
    """Ultimo della fila, e deliberatamente largo.

    Era il ramo di ricaduta di `leggi()` prima del registro. Restringerlo a un predicato
    stretto cambierebbe il comportamento su file che oggi vengono letti, ed e' proprio
    cio' che il test differenziale del Task 2 vieta.
    """
    return True


REGISTRO: tuple[Harness, ...] = (
    Harness(nome="codex", riconosce=_e_codex, lettore="codex"),
    Harness(
        nome="antigravity",
        riconosce=_e_antigravity,
        misurabile=False,
        motivo="il transcript di Antigravity non contiene conteggi di token",
    ),
    Harness(nome="claude-code", riconosce=_e_claude_code, lettore="claude-code"),
)


def riconosci(prima_voce: dict) -> Harness | None:
    """Il primo harness che riconosce la voce. `None` se nessuno la riconosce."""
    if not isinstance(prima_voce, dict):
        return None
    for candidato in REGISTRO:
        if candidato.riconosce(prima_voce):
            return candidato
    return None


def per_nome(nome: str) -> Harness | None:
    for candidato in REGISTRO:
        if candidato.nome == nome:
            return candidato
    return None
