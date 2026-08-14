from datetime import datetime, timedelta, timezone

import pytest

from starkeno.conto import AzioneConto, calcola_conto
from starkeno.db import AgentAction, conta_chiamate, get_azioni_conto


ORA = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
PESI = {"input": 1.0, "cache_read": 0.1, "cache_write": 1.25, "output": 2.0}
TETTO = 2_000_000


def azione(**sovrascrivi):
    valori = {
        "project": "progetto", "session_id": "sessione", "model_used": "modello",
        "timestamp": ORA, "tokens_used": 1_000, "cache_read_tokens": 0,
        "cache_write_tokens": 0, "output_tokens": 0,
        "azioni_nella_chiamata": 1, "skill": "", "plugin": "", "mcp_server": "",
        "is_sidechain": 0, "esito_noto": 1,
    }
    valori.update(sovrascrivi)
    return AzioneConto(**valori)


def test_partizioni_quadrano_mentre_etichette_si_sovrappongono():
    conto = calcola_conto(
        [azione(project="alfa", model_used="m1", session_id="s1",
                tokens_used=1_000, azioni_nella_chiamata=1,
                skill="analisi", plugin="p", mcp_server="m"),
         azione(project="beta", model_used="m1", session_id="s2",
                tokens_used=2_000, azioni_nella_chiamata=3,
                skill="analisi", is_sidechain=1),
         azione(project="alfa", model_used="m2", session_id="s2",
                tokens_used=3_000, azioni_nella_chiamata=2)],
        fuso=timezone.utc, now=ORA, weights=PESI, max_plausible=TETTO,
    )

    assert [(v.nome, v.chiamate, v.azioni) for v in conto.per_progetto] == [
        ("alfa", 2, 3), ("beta", 1, 3)]
    assert [v.totale_pesato for v in conto.per_progetto] == pytest.approx([4_000, 2_000])
    assert [(v.nome, v.chiamate, v.azioni) for v in conto.per_modello] == [
        ("m1", 2, 4), ("m2", 1, 2)]
    assert [v.totale_pesato for v in conto.per_modello] == pytest.approx([3_000, 3_000])
    assert [(v.nome, v.chiamate, v.azioni) for v in conto.per_sessione] == [
        ("s1", 1, 1), ("s2", 2, 5)]
    assert [v.totale_pesato for v in conto.per_sessione] == pytest.approx([1_000, 5_000])
    for partizione in (conto.per_progetto, conto.per_modello, conto.per_sessione):
        assert len(partizione) == 2
        assert conto.chiamate == sum(voce.chiamate for voce in partizione)
        assert conto.azioni == sum(voce.azioni for voce in partizione)
        assert conto.totale_pesato == pytest.approx(
            sum(voce.totale_pesato for voce in partizione))
    assert conto.per_skill[0].chiamate == 2
    assert conto.per_plugin[0].chiamate == 1
    assert conto.per_subagente[0].nome == "sub-agente"


def test_marginale_esclude_cache_read_e_separa_lavoro_da_caricamento():
    conto = calcola_conto(
        [azione(tokens_used=1700, cache_read_tokens=1000,
                cache_write_tokens=200, output_tokens=100)],
        fuso=timezone.utc, now=ORA, weights=PESI, max_plausible=TETTO,
    )

    assert conto.riletture_pesate == 100
    assert conto.caricamento_pesato == 250
    assert conto.lavoro_pesato == 600
    assert conto.marginale_pesato == 850


def test_etichette_attribuiscono_solo_il_marginale_senza_riletture():
    conto = calcola_conto(
        [azione(tokens_used=1700, cache_read_tokens=1000,
                cache_write_tokens=200, output_tokens=100,
                skill="analisi", plugin="p", mcp_server="m", is_sidechain=1)],
        fuso=timezone.utc, now=ORA, weights=PESI, max_plausible=TETTO,
    )

    voci = (conto.per_skill[0], conto.per_plugin[0],
            conto.per_mcp_server[0], conto.per_subagente[0])
    for voce in voci:
        assert voce.totale_pesato == pytest.approx(voce.marginale_pesato)
        assert voce.totale_pesato == pytest.approx(850)
        assert voce.lavoro_pesato == pytest.approx(600)
        assert voce.caricamento_pesato == pytest.approx(250)
        assert voce.riletture_pesate == 0


def test_righe_non_classificabili_restano_nel_totale_ma_non_nel_marginale():
    conto = calcola_conto(
        [azione(tokens_used=900, cache_read_tokens=None,
                cache_write_tokens=None, output_tokens=100)],
        fuso=timezone.utc, now=ORA, weights=PESI, max_plausible=TETTO,
    )

    assert conto.totale_pesato == 900
    assert conto.marginale_pesato == 0
    assert conto.righe_non_classificabili == 1


def test_ritmo_raggruppa_giorni_locali_negli_ultimi_sette_giorni():
    fuso = timezone(timedelta(hours=2))
    conto = calcola_conto(
        [azione(timestamp=ORA - timedelta(days=6, hours=13)),
         azione(timestamp=ORA - timedelta(days=7))],
        fuso=fuso, now=ORA, weights=PESI, max_plausible=TETTO,
    )

    assert len(conto.ritmo) == 7
    assert conto.ritmo[-1].giorno == ORA.astimezone(fuso).date()
    assert sum(giorno.chiamate for giorno in conto.ritmo) == 1


def test_il_fuso_e_sempre_un_input_esplicito_del_modello_puro():
    class DataSpia:
        def __init__(self, giorno):
            self.giorno = giorno
            self.chiamate = []

        def astimezone(self, *argomenti):
            self.chiamate.append(argomenti)
            return self

        def date(self):
            return self.giorno

    giorno = ORA.date()
    ora = DataSpia(giorno)
    timestamp = DataSpia(giorno)
    fuso = object()

    calcola_conto(
        [azione(timestamp=timestamp)], fuso=fuso, now=ora,
        weights=PESI, max_plausible=TETTO,
    )

    assert ora.chiamate == [(fuso,)]
    assert timestamp.chiamate == [(fuso,)]


def test_snapshot_db_e_conteggio_chiamate(session):
    session.add(AgentAction(
        project="db", action="x", model_used="m", tokens_used=100,
        timestamp=ORA, session_id="s", azioni_nella_chiamata=3,
        skill="skill", plugin="plugin", mcp_server="server", is_sidechain=1,
        esito_noto=0,
    ))
    session.commit()

    azioni = get_azioni_conto(session)

    assert conta_chiamate(session) == 1
    assert azioni[0] == azione(
        project="db", session_id="s", model_used="m", timestamp=ORA,
        tokens_used=100, cache_read_tokens=None, cache_write_tokens=None,
        output_tokens=None, azioni_nella_chiamata=3, skill="skill", plugin="plugin",
        mcp_server="server", is_sidechain=1, esito_noto=0,
    )
    assert azioni[0].timestamp.tzinfo is not None
