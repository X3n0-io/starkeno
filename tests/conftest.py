"""Fixture condivise.

Da quando `make_session_factory` non chiama piu' `create_all` (task 0: Alembic e'
l'unica autorita' sullo schema), i test hanno bisogno di un posto dove costruire lo
schema. Questo e' quel posto, e l'unico.

**Perche' i test non passano da Alembic.** Sarebbe piu' fedele, ma legherebbe ogni test
unitario alla catena delle migrazioni: una revisione rotta farebbe fallire tutta la
suite invece dei soli test delle migrazioni, che e' esattamente il segnale che serve.
`tests/test_migrations.py` copre la catena vera, su database usa e getta.
"""
import sqlite3
import sqlite3.dbapi2

import pytest

from starkeno.db import Base, make_session_factory


def _e_chiusa(connessione) -> bool:
    """Sonda non invasiva: su una connessione chiusa ogni attributo solleva.

    `in_transaction` e' una lettura pura — non apre transazioni, non tocca il file e non
    cambia lo stato di una connessione viva (verificato). Serve una sonda e non un flag
    perche' `sqlite3.Connection` non espone "sono chiusa?".
    """
    try:
        connessione.in_transaction
    except sqlite3.ProgrammingError:
        return True
    return False


@pytest.fixture(autouse=True)
def nessuna_connessione_lasciata_aperta():
    """Fallisce il test che lascia aperta una connessione SQLite.

    **Perche' esiste.** Da Python 3.13 una `sqlite3.Connection` raccolta dal GC senza
    `close()` emette `ResourceWarning: unclosed database`; sotto `-W error` pytest lo
    rilancia come `PytestUnraisableExceptionWarning` e uccide il test che stava girando
    quando il GC e' partito — non quello che ha perso la connessione. Nella CI del
    14/08/2026 questo ha prodotto 42 fallimenti e 8 errori con tracce che puntano a
    `<frozen os>`, cioe' senza alcuna indicazione del colpevole.

    Questo guardiano sposta il controllo dal GC al confine del test: deterministico,
    attribuito al test giusto, e **rosso anche su Python 3.12**, dove il warning non
    esiste e dove Simone sviluppa. Non e' un filtro che silenzia il warning — e' la
    stessa invariante dichiarata prima e meglio.

    La trappola che rende necessaria la sonda: `session.close()` restituisce la
    connessione al POOL, non la chiude. Solo `engine.dispose()` la chiude. Allo stesso
    modo `with sqlite3.connect(...)` gestisce la TRANSAZIONE, non la risorsa: all'uscita
    dal blocco la connessione e' ancora aperta (verificato — su Windows tiene pure il
    lock sul file e fa fallire la pulizia di `tmp_path`).

    Si intercetta `sqlite3.dbapi2.connect` e non solo `sqlite3.connect`: sono la stessa
    funzione sotto due nomi, ma SQLAlchemy risolve `dbapi2` e patchare il solo `sqlite3`
    non intercetta nulla di cio' che apre l'ORM (misurato: zero connessioni viste).

    Le superstiti vengono chiuse dopo essere state contate. Lasciarle aperte farebbe
    incolpare un test successivo — esattamente il difetto di attribuzione che questo
    guardiano esiste per eliminare — e su Windows bloccherebbe la rimozione di `tmp_path`.
    """
    aperte = []
    vera_connect = sqlite3.dbapi2.connect

    def traccia(*args, **kwargs):
        connessione = vera_connect(*args, **kwargs)
        aperte.append(connessione)
        return connessione

    sqlite3.dbapi2.connect = traccia
    sqlite3.connect = traccia
    try:
        yield
    finally:
        sqlite3.dbapi2.connect = vera_connect
        sqlite3.connect = vera_connect

    superstiti = [c for c in aperte if not _e_chiusa(c)]
    for connessione in superstiti:
        connessione.close()
    assert not superstiti, (
        "%d connessione/i SQLite su %d lasciate aperte dal test. "
        "Una sessione va chiusa con session.close() E l'engine con "
        "engine.dispose(); una sqlite3.Connection con close(), che `with` NON fa."
        % (len(superstiti), len(aperte))
    )


@pytest.fixture
def session_factory(tmp_path):
    """Session factory su un database usa e getta, con lo schema gia' creato.

    Usa `make_session_factory` vero — quindi WAL, busy timeout e il TypeDecorator dei
    datetime sono quelli di produzione — e ci aggiunge solo la creazione dello schema.

    `yield` e non `return`: l'engine tiene una connessione viva nel pool finche' non viene
    disposto, e questa fixture ne creava una per test senza chiuderla mai. Era la singola
    fonte piu' grossa delle connessioni perse.
    """
    factory = make_session_factory(str(tmp_path / "test.db"))
    Base.metadata.create_all(factory.kw["bind"])
    try:
        yield factory
    finally:
        factory.kw["bind"].dispose()


@pytest.fixture
def session(session_factory):
    """Una sessione aperta sul database usa e getta, chiusa a fine test."""
    sessione = session_factory()
    try:
        yield sessione
    finally:
        sessione.close()
