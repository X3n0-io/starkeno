"""Fixture condivise.

Da quando `make_session_factory` non chiama piu' `create_all` (task 0: Alembic e'
l'unica autorita' sullo schema), i test hanno bisogno di un posto dove costruire lo
schema. Questo e' quel posto, e l'unico.

**Perche' i test non passano da Alembic.** Sarebbe piu' fedele, ma legherebbe ogni test
unitario alla catena delle migrazioni: una revisione rotta farebbe fallire tutta la
suite invece dei soli test delle migrazioni, che e' esattamente il segnale che serve.
`tests/test_migrations.py` copre la catena vera, su database usa e getta.
"""
import pytest

from starkeno.db import Base, make_session_factory


@pytest.fixture
def session_factory(tmp_path):
    """Session factory su un database usa e getta, con lo schema gia' creato.

    Usa `make_session_factory` vero — quindi WAL, busy timeout e il TypeDecorator dei
    datetime sono quelli di produzione — e ci aggiunge solo la creazione dello schema.
    """
    factory = make_session_factory(str(tmp_path / "test.db"))
    Base.metadata.create_all(factory.kw["bind"])
    return factory


@pytest.fixture
def session(session_factory):
    """Una sessione aperta sul database usa e getta, chiusa a fine test."""
    sessione = session_factory()
    try:
        yield sessione
    finally:
        sessione.close()
