"""Il sito non deve far scaricare niente da terzi a chi lo apre.

Un sito che promette «nessuna telemetria» e poi carica un font da un CDN ha gia' detto a
quel CDN chi lo sta leggendo, quando e da quale indirizzo. Il cancello serve a rendere
quella promessa verificabile invece che dichiarata.

La distinzione che conta e' fra **sottorisorsa** e **collegamento**:

* una *sottorisorsa* la scarica il browser da solo, senza che nessuno la chieda — un
  foglio di stile, un'icona, un'immagine, uno script. Deve stare su un host ammesso,
  oppure essere relativa a questo sito;
* un *collegamento* lo segue una persona che ha deciso di cliccarlo. Un link a PyPI non
  fa sapere niente a nessuno finche' qualcuno non lo apre, quindi e' permesso — ma viene
  **elencato** nel log, perche' un elenco che nessuno stampa non e' un controllo.

La versione precedente cercava `https?://` in tutto il testo con un'espressione regolare.
Falliva in due direzioni: vietava di linkare PyPI, e non guardava dentro `url()` di un
CSS ne' dentro `srcset`, che sono esattamente i posti da cui un font o un pixel di
tracciamento entrerebbe senza farsi notare.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator, Sequence
from urllib.parse import urlsplit

HOST_AMMESSI = frozenset({"github.com", "raw.githubusercontent.com"})

# Attributi che il browser scarica da solo, senza che nessuno clicchi niente.
SOTTORISORSE: dict[str, tuple[str, ...]] = {
    "audio": ("src",),
    "embed": ("src",),
    "iframe": ("src",),
    "img": ("src", "srcset"),
    "input": ("src",),
    "object": ("data",),
    "script": ("src",),
    "source": ("src", "srcset"),
    "track": ("src",),
    "use": ("href", "xlink:href"),
    "video": ("src", "poster"),
}

# `rel` di <link> che provocano un download. Gli altri (canonical, alternate, license…)
# sono metadati: dichiarano un indirizzo, non lo chiedono.
REL_CHE_SCARICANO = frozenset({
    "apple-touch-icon", "dns-prefetch", "icon", "manifest", "mask-icon",
    "modulepreload", "preconnect", "prefetch", "preload", "stylesheet",
})

# <meta> il cui contenuto viene scaricato da chi genera l'anteprima del link.
META_CHE_SCARICANO = frozenset({
    "og:audio", "og:image", "og:image:secure_url", "og:image:url", "og:video",
    "twitter:image",
})

URL_IN_CSS = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""", re.IGNORECASE)
IMPORT_IN_CSS = re.compile(r"""@import\s+(?:url\(\s*)?['"]([^'"]+)['"]""", re.IGNORECASE)


@dataclass(frozen=True)
class Riferimento:
    percorso: Path
    origine: str
    url: str
    sottorisorsa: bool


@dataclass(frozen=True)
class Rilievo:
    percorso: Path
    origine: str
    url: str
    motivo: str


class _LettoreHTML(HTMLParser):
    """Raccoglie riferimenti e blocchi <style> senza valutare niente."""

    def __init__(self, percorso: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.percorso = percorso
        self.riferimenti: list[Riferimento] = []
        self.stili: list[str] = []
        self.script_in_linea = 0
        self._dentro_style = False
        self._dentro_script = False

    # -- raccolta -------------------------------------------------------------

    def _aggiungi(self, origine: str, valore: str | None, sottorisorsa: bool) -> None:
        if not valore:
            return
        for url in _url_di(valore, origine):
            self.riferimenti.append(
                Riferimento(self.percorso, origine, url, sottorisorsa)
            )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {nome: valore for nome, valore in attrs}
        if tag == "style":
            self._dentro_style = True
        if tag == "script":
            self._dentro_script = True
            if "src" not in a:
                self.script_in_linea += 1
        for attributo in SOTTORISORSE.get(tag, ()):
            self._aggiungi(f"<{tag} {attributo}>", a.get(attributo), True)
        if tag == "link":
            rel = (a.get("rel") or "").lower().split()
            scarica = any(r in REL_CHE_SCARICANO for r in rel)
            self._aggiungi(f"<link rel={' '.join(rel) or '?'}>", a.get("href"), scarica)
        if tag == "meta":
            chiave = (a.get("property") or a.get("name") or "").lower()
            scarica = chiave in META_CHE_SCARICANO
            contenuto = a.get("content") or ""
            if "://" in contenuto or scarica:
                self._aggiungi(f"<meta {chiave or '?'}>", contenuto, scarica)
        if tag == "a":
            self._aggiungi("<a href>", a.get("href"), False)
        for nome, valore in a.items():
            if nome == "style" and valore:
                self.stili.append(valore)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._dentro_style = False
        if tag == "script":
            self._dentro_script = False

    def handle_data(self, data: str) -> None:
        if self._dentro_style:
            self.stili.append(data)


def _url_di(valore: str, origine: str) -> Iterator[str]:
    """`srcset` contiene piu' URL separati da virgola, ognuno con un descrittore."""
    if origine.endswith("srcset>"):
        for pezzo in valore.split(","):
            pezzo = pezzo.strip()
            if pezzo:
                yield pezzo.split()[0]
        return
    valore = valore.strip()
    if valore:
        yield valore


def _riferimenti_css(percorso: Path, testo: str, origine: str) -> list[Riferimento]:
    trovati = []
    for espressione, etichetta in ((URL_IN_CSS, "url()"), (IMPORT_IN_CSS, "@import")):
        for url in espressione.findall(testo):
            trovati.append(
                Riferimento(percorso, f"{origine} {etichetta}", url.strip(), True)
            )
    return trovati


def _giudica(riferimento: Riferimento) -> Rilievo | None:
    pezzi = urlsplit(riferimento.url)
    schema = pezzi.scheme.lower()
    host = pezzi.hostname.lower() if pezzi.hostname else ""

    if not schema and not pezzi.netloc:
        return None  # relativo: e' questo sito
    if schema in {"data", "mailto", "tel"}:
        return None
    if schema not in {"http", "https"}:
        return _rilievo(riferimento, f"schema inatteso: {schema or '?'}")
    if not riferimento.sottorisorsa:
        return None  # un collegamento lo apre una persona, e viene elencato a parte
    if schema != "https":
        return _rilievo(riferimento, "sottorisorsa non cifrata (http)")
    if host not in HOST_AMMESSI:
        return _rilievo(riferimento, f"host non ammesso: {host}")
    return None


def _rilievo(riferimento: Riferimento, motivo: str) -> Rilievo:
    return Rilievo(riferimento.percorso, riferimento.origine, riferimento.url, motivo)


def analizza(radice: Path) -> tuple[list[Rilievo], list[Riferimento]]:
    """Torna i rilievi e tutti i riferimenti trovati, sottorisorse e collegamenti."""
    rilievi: list[Rilievo] = []
    riferimenti: list[Riferimento] = []

    pagine = sorted(radice.rglob("*.html"))
    if not pagine:
        rilievi.append(Rilievo(radice, "-", "-", "nessuna pagina HTML trovata"))

    for pagina in pagine:
        lettore = _LettoreHTML(pagina)
        lettore.feed(pagina.read_text(encoding="utf-8"))
        lettore.close()
        riferimenti.extend(lettore.riferimenti)
        for stile in lettore.stili:
            riferimenti.extend(_riferimenti_css(pagina, stile, "<style>"))
        if lettore.script_in_linea:
            rilievi.append(
                Rilievo(
                    pagina, "<script>", "-",
                    "il sito dichiara di non eseguire script: "
                    f"trovati {lettore.script_in_linea} blocchi in linea",
                )
            )

    for foglio in sorted(radice.rglob("*.css")):
        riferimenti.extend(
            _riferimenti_css(foglio, foglio.read_text(encoding="utf-8"), "css")
        )

    rilievi.extend(r for r in (_giudica(rif) for rif in riferimenti) if r is not None)
    return rilievi, riferimenti


def _host_ordinati(riferimenti: Iterable[Riferimento]) -> list[str]:
    return sorted({(urlsplit(r.url).hostname or "").lower() for r in riferimenti} - {""})


def main(argv: Sequence[str] | None = None) -> int:
    analizzatore = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizzatore.add_argument(
        "radice", nargs="?", default="sito", type=Path,
        help="cartella del sito da controllare (default: sito)",
    )
    argomenti = analizzatore.parse_args(argv)
    radice: Path = argomenti.radice

    if not radice.is_dir():
        print(f"cartella inesistente: {radice}", file=sys.stderr)
        return 2

    rilievi, riferimenti = analizza(radice)
    scaricati = _host_ordinati(r for r in riferimenti if r.sottorisorsa)
    linkati = _host_ordinati(r for r in riferimenti if not r.sottorisorsa)

    print("host scaricati dal browser:", scaricati or ["nessuno"])
    print("host solo linkati (li apre una persona):", linkati or ["nessuno"])

    if rilievi:
        print("", file=sys.stderr)
        for rilievo in rilievi:
            print(
                f"{rilievo.percorso}: {rilievo.origine} {rilievo.url} — {rilievo.motivo}",
                file=sys.stderr,
            )
        print(f"\n{len(rilievi)} rilievi: il sito non e' pubblicabile.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
