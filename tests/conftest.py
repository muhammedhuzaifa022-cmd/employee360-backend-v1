"""
Shared test setup.

- `client`      : talks to the API without starting a real server.
- `test_engine` : connection to the TEST database (never the real one).
                  At the start it rebuilds all tables from the migrations
                  (downgrade to empty, then upgrade to latest).
- `db`          : a database session whose changes are ALWAYS rolled back
                  after each test, so tests never affect each other.
"""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def alembic_config(db_url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["db_url"] = db_url
    return cfg


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = settings.TEST_DATABASE_URL
    if not url:
        pytest.exit("TEST_DATABASE_URL is missing in .env", returncode=1)
    if url == settings.DATABASE_URL:
        pytest.exit("TEST_DATABASE_URL must be DIFFERENT from DATABASE_URL", returncode=1)
    return url


@pytest.fixture(scope="session")
def test_engine(test_db_url):
    cfg = alembic_config(test_db_url)
    command.downgrade(cfg, "base")   # empty the test database
    command.upgrade(cfg, "head")     # create every table again
    engine = create_engine(test_db_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(test_engine):
    connection = test_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint",
                      expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


# ---------------- Module 3: API client on the TEST database ----------------
@pytest.fixture()
def api(db):
    """
    A test client whose requests use the rolled-back `db` session,
    so API tests write to the TEST database and leave nothing behind.
    """
    from app.core.rate_limit import login_limiter
    from app.db.session import get_db

    app.dependency_overrides[get_db] = lambda: db
    login_limiter.clear_all()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)
    login_limiter.clear_all()
