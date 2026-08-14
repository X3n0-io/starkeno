"""Genera il conto come pagina HTML locale, senza avviare alcun server."""
from __future__ import annotations

import argparse
import calendar
import html
import os
import time
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
import webbrowser

from starkeno import db
from starkeno.config import MAX_PLAUSIBLE_TOKENS, TOKEN_COST_WEIGHTS
from starkeno.conto import Conto, RitmoGiorno, VoceConto, calcola_conto
from starkeno.percorsi import percorso_database


class FusoLocaleSistema(tzinfo):
    """Fuso locale concreto con le regole DST applicate dall'OS per ogni istante.

    ``datetime.now().astimezone().tzinfo`` su Windows e' un offset fisso. Questa classe
    cattura offset e nomi al confine CLI e usa ``time.localtime`` per scegliere la regola
    storica corretta in ``fromutc``. Il modello puro riceve quindi un normale ``tzinfo``
    esplicito e continua a usare soltanto ``astimezone(fuso)``.
    """

    def __init__(self):
        self._standard = timedelta(seconds=-time.timezone)
        self._legale = (
            timedelta(seconds=-time.altzone) if time.daylight else self._standard
        )
        self._differenza = self._legale - self._standard
        self._nomi = tuple(time.tzname)

    def fromutc(self, istante):
        if istante.tzinfo is not self:
            raise ValueError("fromutc richiede questo fuso come tzinfo")
        naive_utc = istante.replace(tzinfo=None)
        timestamp = calendar.timegm(naive_utc.timetuple()) + naive_utc.microsecond / 1_000_000
        locale = time.localtime(timestamp)
        fold = 0
        differenza = int(self._differenza.total_seconds())
        if differenza:
            precedente = time.localtime(timestamp - differenza)
            fold = int(locale[:6] == precedente[:6])
        return datetime(*locale[:6], microsecond=istante.microsecond,
                        tzinfo=self, fold=fold)

    def utcoffset(self, istante):
        return self._legale if self._ora_legale(istante) else self._standard

    def dst(self, istante):
        return self._differenza if self._ora_legale(istante) else timedelta(0)

    def tzname(self, istante):
        indice = 1 if self._ora_legale(istante) and len(self._nomi) > 1 else 0
        return self._nomi[indice]

    @staticmethod
    def _ora_legale(istante) -> bool:
        if istante is None:
            return False
        locale = istante.replace(tzinfo=None)
        tupla = (
            locale.year, locale.month, locale.day, locale.hour, locale.minute,
            locale.second, locale.weekday(), 0, -1,
        )
        return time.localtime(time.mktime(tupla)).tm_isdst > 0


def _esc(valore) -> str:
    return html.escape(str(valore), quote=True)


def _numero(valore: float | int) -> str:
    if isinstance(valore, int):
        return f"{valore:,}".replace(",", ".")
    numero = float(valore)
    if numero.is_integer():
        return f"{int(numero):,}".replace(",", ".")
    intero, decimali = f"{numero:,.1f}".split(".")
    return intero.replace(",", ".") + "," + decimali


def _tabella(titolo: str, intestazioni, righe, *, vuoto: str) -> str:
    corpo = "".join(
        "<tr>" + "".join(f"<td>{_esc(cella)}</td>" for cella in riga) + "</tr>"
        for riga in righe
    )
    if not corpo:
        corpo = f'<tr><td colspan="{len(intestazioni)}" class="vuoto">{_esc(vuoto)}</td></tr>'
    testa = "".join(f"<th scope=\"col\">{_esc(voce)}</th>" for voce in intestazioni)
    return (
        f"<section><h2>{_esc(titolo)}</h2><div class=\"tabella\"><table>"
        f"<thead><tr>{testa}</tr></thead><tbody>{corpo}</tbody></table></div></section>"
    )


def _righe_voci(voci: tuple[VoceConto, ...]):
    return [
        (
            voce.nome, _numero(voce.chiamate), _numero(voce.azioni),
            _numero(voce.totale_pesato), _numero(voce.lavoro_pesato),
            _numero(voce.caricamento_pesato), _numero(voce.riletture_pesate),
        )
        for voce in voci
    ]


def _righe_etichette(voci: tuple[VoceConto, ...]):
    return [
        (
            voce.nome, _numero(voce.chiamate), _numero(voce.azioni),
            _numero(voce.lavoro_pesato), _numero(voce.caricamento_pesato),
            _numero(voce.marginale_pesato),
        )
        for voce in voci
    ]


def _righe_ritmo(ritmo: tuple[RitmoGiorno, ...]):
    return [
        (
            giorno.giorno.isoformat(), _numero(giorno.chiamate),
            _numero(giorno.azioni), _numero(giorno.lavoro_pesato),
            _numero(giorno.caricamento_pesato), _numero(giorno.riletture_pesate),
            _numero(giorno.totale_pesato),
        )
        for giorno in ritmo
    ]


def renderizza_html(conto: Conto) -> str:
    """Renderizza il modello puro; tutti i valori dinamici passano da ``html.escape``."""
    intestazioni_partizione = (
        "Nome", "Chiamate", "Azioni", "Totale pesato", "Costo di lavoro",
        "Costo di caricamento", "Costo di rilettura",
    )
    intestazioni_etichetta = (
        "Nome", "Chiamate", "Azioni", "Costo di lavoro",
        "Costo di caricamento", "Costo marginale",
    )
    nome_azioni = "azione" if conto.azioni == 1 else "azioni"
    nome_chiamate = "chiamata" if conto.chiamate == 1 else "chiamate"
    stato_vuoto = (
        '<p class="vuoto evidenza">Nessun dato disponibile: il conto si riempirà '
        "dopo le prime chiamate registrate.</p>" if conto.chiamate == 0 else ""
    )

    sezioni = [
        _tabella("Per progetto", intestazioni_partizione,
                 _righe_voci(conto.per_progetto), vuoto="Nessun progetto registrato"),
        _tabella("Per modello", intestazioni_partizione,
                 _righe_voci(conto.per_modello), vuoto="Nessun modello registrato"),
        _tabella("Per sessione", intestazioni_partizione,
                 _righe_voci(conto.per_sessione), vuoto="Nessuna sessione registrata"),
        '<section><h2>Etichette</h2><p class="nota"><strong>Le etichette si '
        "sovrappongono</strong>: skill, plugin, server MCP e sub-agente non sono una "
        "partizione e non vanno sommati. La rilettura è attribuita alla sessione, non "
        "allo strumento.</p></section>",
        _tabella("Per skill", intestazioni_etichetta,
                 _righe_etichette(conto.per_skill), vuoto="Nessuna skill attribuita"),
        _tabella("Per plugin", intestazioni_etichetta,
                 _righe_etichette(conto.per_plugin), vuoto="Nessun plugin attribuito"),
        _tabella("Per server MCP", intestazioni_etichetta,
                 _righe_etichette(conto.per_mcp_server), vuoto="Nessun server MCP attribuito"),
        _tabella("Per sub-agente", intestazioni_etichetta,
                 _righe_etichette(conto.per_subagente), vuoto="Nessun sub-agente attribuito"),
        _tabella(
            "Ritmo locale degli ultimi 7 giorni",
            ("Giorno", "Chiamate", "Azioni", "Costo di lavoro",
             "Costo di caricamento", "Costo di rilettura", "Totale pesato"),
            _righe_ritmo(conto.ritmo), vuoto="Nessun giorno disponibile",
        ),
    ]

    return """<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Il conto · StarkEno</title>
  <style>
    :root { color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: #101216; color: #f3f4f6; }
    main { width: min(1120px, calc(100%% - 32px)); margin: 0 auto; padding: 48px 0 72px; }
    h1 { margin: 0 0 8px; font-size: clamp(2rem, 5vw, 4rem); }
    h2 { margin-top: 36px; }
    .sottotitolo, .nota, footer { color: #b7beca; }
    .evidenza { font-size: 1.2rem; }
    .metriche { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 28px 0; }
    .metrica, .nota { background: #1a1e25; border: 1px solid #303744; border-radius: 12px; padding: 16px; }
    .metrica strong { display: block; font-size: 1.35rem; margin-top: 6px; }
    .tabella { overflow-x: auto; border: 1px solid #303744; border-radius: 12px; }
    table { border-collapse: collapse; width: 100%%; background: #161a20; }
    th, td { padding: 11px 13px; text-align: right; border-bottom: 1px solid #2a303a; white-space: nowrap; }
    th:first-child, td:first-child { text-align: left; }
    th { color: #a9b7d0; font-size: .82rem; text-transform: uppercase; letter-spacing: .04em; }
    tr:last-child td { border-bottom: 0; }
    .vuoto { color: #8e98a8; }
    footer { margin-top: 44px; padding-top: 20px; border-top: 1px solid #303744; }
  </style>
</head>
<body><main>
  <header>
    <p class="sottotitolo">StarkEno · il conto locale</p>
    <h1>%(azioni)s %(nome_azioni)s in %(chiamate)s %(nome_chiamate)s</h1>
    %(stato_vuoto)s
  </header>
  <div class="metriche">
    <div class="metrica">Totale pesato<strong>%(totale)s</strong></div>
    <div class="metrica">Costo di lavoro<strong>%(lavoro)s</strong></div>
    <div class="metrica">Costo di caricamento<strong>%(caricamento)s</strong></div>
    <div class="metrica">Costo di rilettura<strong>%(riletture)s</strong></div>
    <div class="metrica">Esiti ignoti<strong>%(ignoti)s</strong></div>
    <div class="metrica">Righe non classificabili<strong>%(non_classificabili)s</strong></div>
  </div>
  <p class="nota"><strong>Tetto non configurato.</strong> Il conto resta disponibile; la previsione tace.</p>
  %(sezioni)s
  <footer>StarkEno misura quello che spendi, non quello che ottieni.</footer>
</main></body>
</html>
""" % {
        "azioni": _esc(_numero(conto.azioni)),
        "nome_azioni": _esc(nome_azioni),
        "chiamate": _esc(_numero(conto.chiamate)),
        "nome_chiamate": _esc(nome_chiamate),
        "stato_vuoto": stato_vuoto,
        "totale": _esc(_numero(conto.totale_pesato)),
        "lavoro": _esc(_numero(conto.lavoro_pesato)),
        "caricamento": _esc(_numero(conto.caricamento_pesato)),
        "riletture": _esc(_numero(conto.riletture_pesate)),
        "ignoti": _esc(_numero(conto.esiti_ignoti)),
        "non_classificabili": _esc(_numero(conto.righe_non_classificabili)),
        "sezioni": "".join(sezioni),
    }


def _leggi_azioni(percorso_db: str | Path):
    fabbrica = db.make_readonly_session_factory(str(percorso_db))
    sessione = fabbrica()
    try:
        return db.get_azioni_conto(sessione)
    finally:
        sessione.close()
        fabbrica.kw["bind"].dispose()


def genera_report(
    percorso_db: str | Path,
    percorso_output: str | Path,
    *,
    fuso,
    now: datetime,
) -> Path:
    """Scrive il conto su richiesta; un database assente non viene creato."""
    database = Path(percorso_db)
    destinazione = Path(percorso_output)
    database_canonico = os.path.normcase(str(database.resolve(strict=False)))
    output_canonico = os.path.normcase(str(destinazione.resolve(strict=False)))
    stesso_file = database_canonico == output_canonico
    if not stesso_file and database.exists() and destinazione.exists():
        stesso_file = os.path.samefile(database, destinazione)
    if stesso_file:
        raise ValueError("il percorso di output coincide con il database")
    if database.exists() and not database.is_file():
        raise ValueError("il percorso del database esiste ma non e' un file")

    azioni = _leggi_azioni(database) if database.exists() else ()
    conto = calcola_conto(
        azioni, fuso=fuso, now=now, weights=TOKEN_COST_WEIGHTS,
        max_plausible=MAX_PLAUSIBLE_TOKENS,
    )
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    destinazione.write_text(renderizza_html(conto), encoding="utf-8")
    return destinazione


def apri_report(path: str | Path) -> None:
    """Apre la pagina nel browser predefinito senza avviare un server."""
    webbrowser.open(Path(path).resolve().as_uri())


def _database_runtime() -> str:
    return os.environ.get("STARKENO_DB_PATH", percorso_database())


def _fuso_locale() -> tzinfo:
    return FusoLocaleSistema()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Genera il conto HTML locale di StarkEno")
    parser.add_argument("--output", type=Path, default=Path.cwd() / "starkeno-conto.html")
    parser.add_argument("--no-open", action="store_true", help="non aprire il browser")
    argomenti = parser.parse_args(argv)

    destinazione = genera_report(
        _database_runtime(), argomenti.output, fuso=_fuso_locale(),
        now=datetime.now(timezone.utc),
    )
    print(destinazione.resolve())
    if not argomenti.no_open:
        apri_report(destinazione)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
