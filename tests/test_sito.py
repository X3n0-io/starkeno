"""Il cancello del sito vale solo se qualcuno prova a scavalcarlo.

Il controllo vero e' `scripts/verifica_sito.py`, che gira anche nel workflow di Pages.
Qui lo si esercita contro le violazioni che ci si aspetta davvero — un font da un CDN,
un pixel dentro un `url()`, uno script in linea — perche' un cancello mai visto fallire
non e' distinguibile da uno rotto.
"""
from pathlib import Path

import pytest

from scripts.verifica_sito import analizza

SITO = Path("sito")


def scrivi(radice: Path, nome: str, testo: str) -> None:
    percorso = radice / nome
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(testo, encoding="utf-8")


def motivi(radice: Path) -> list[str]:
    rilievi, _ = analizza(radice)
    return [r.motivo for r in rilievi]


# -- il sito vero ------------------------------------------------------------


def test_il_sito_pubblicato_non_ha_rilievi():
    rilievi, _ = analizza(SITO)
    assert rilievi == [], [f"{r.percorso}: {r.url} — {r.motivo}" for r in rilievi]


def test_il_sito_scarica_solo_da_host_ammessi():
    _, riferimenti = analizza(SITO)
    host = {
        r.url.split("/")[2]
        for r in riferimenti
        if r.sottorisorsa and r.url.startswith("https://")
    }
    assert host <= {"raw.githubusercontent.com", "github.com"}


def test_entrambe_le_lingue_sono_pubblicate():
    assert (SITO / "index.html").is_file()
    assert (SITO / "en" / "index.html").is_file()


@pytest.mark.parametrize("pagina", ["index.html", "en/index.html"])
def test_ogni_pagina_dichiara_l_anteprima_e_l_altra_lingua(pagina):
    testo = (SITO / pagina).read_text(encoding="utf-8")
    assert 'property="og:image"' in testo
    assert 'name="twitter:card"' in testo
    assert 'hreflang="it"' in testo and 'hreflang="en"' in testo


# -- le violazioni che il cancello deve vedere -------------------------------


def test_un_font_da_un_cdn_e_un_rilievo(tmp_path):
    scrivi(tmp_path, "index.html", (
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Inter">'
    ))
    assert any("host non ammesso" in m for m in motivi(tmp_path))


def test_un_pixel_dentro_un_css_e_un_rilievo(tmp_path):
    scrivi(tmp_path, "index.html", "<p>niente</p>")
    scrivi(tmp_path, "stile.css", "body{background:url(https://tracker.example/p.gif)}")
    assert any("host non ammesso" in m for m in motivi(tmp_path))


def test_un_import_dentro_un_css_e_un_rilievo(tmp_path):
    scrivi(tmp_path, "index.html", "<p>niente</p>")
    scrivi(tmp_path, "stile.css", '@import "https://cdn.example/reset.css";')
    assert any("host non ammesso" in m for m in motivi(tmp_path))


def test_un_srcset_estraneo_e_un_rilievo(tmp_path):
    scrivi(tmp_path, "index.html", (
        '<img src="a.png" srcset="a.png 1x, https://cdn.example/a@2x.png 2x">'
    ))
    assert any("host non ammesso" in m for m in motivi(tmp_path))


def test_uno_stile_in_linea_e_controllato(tmp_path):
    scrivi(tmp_path, "index.html", (
        '<style>@font-face{src:url(https://cdn.example/f.woff2)}</style>'
    ))
    assert any("host non ammesso" in m for m in motivi(tmp_path))


def test_uno_script_in_linea_e_un_rilievo(tmp_path):
    scrivi(tmp_path, "index.html", "<script>console.log(1)</script>")
    assert any("non eseguire script" in m for m in motivi(tmp_path))


def test_una_sottorisorsa_in_chiaro_e_un_rilievo(tmp_path):
    scrivi(tmp_path, "index.html", (
        '<img src="http://raw.githubusercontent.com/x/y/z.png">'
    ))
    assert any("non cifrata" in m for m in motivi(tmp_path))


def test_un_anteprima_social_su_host_estraneo_e_un_rilievo(tmp_path):
    scrivi(tmp_path, "index.html", (
        '<meta property="og:image" content="https://cdn.example/anteprima.png">'
    ))
    assert any("host non ammesso" in m for m in motivi(tmp_path))


def test_una_cartella_senza_pagine_e_un_rilievo(tmp_path):
    assert any("nessuna pagina HTML" in m for m in motivi(tmp_path))


# -- quello che invece e' permesso, e va dichiarato --------------------------


def test_un_collegamento_a_un_sito_terzo_e_permesso(tmp_path):
    scrivi(tmp_path, "index.html", '<a href="https://pypi.org/project/starkeno/">PyPI</a>')
    assert motivi(tmp_path) == []


def test_i_collegamenti_in_uscita_sono_elencati(tmp_path):
    scrivi(tmp_path, "index.html", '<a href="https://pypi.org/project/starkeno/">PyPI</a>')
    _, riferimenti = analizza(tmp_path)
    uscita = [r.url for r in riferimenti if not r.sottorisorsa]
    assert "https://pypi.org/project/starkeno/" in uscita


def test_canonical_e_alternate_non_sono_sottorisorse(tmp_path):
    scrivi(tmp_path, "index.html", (
        '<link rel="canonical" href="https://x3n0-io.github.io/starkeno/">'
        '<link rel="alternate" hreflang="en" href="https://esempio.invalid/en/">'
    ))
    assert motivi(tmp_path) == []


def test_un_icona_relativa_e_permessa(tmp_path):
    scrivi(tmp_path, "index.html", '<link rel="icon" href="favicon.svg">')
    assert motivi(tmp_path) == []
