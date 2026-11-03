"""
Database connection.

- `engine`       : the connection pool to PostgreSQL.
- `SessionLocal` : creates a "session" (a conversation with the database).
- `get_db()`     : gives each API request its own session and always
                   closes it afterwards, even if an error happens.
"""
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO_SQL,
    pool_pre_ping=True,   # checks a connection is alive before using it
    pool_size=10,         # connections kept open
    max_overflow=20,      # extra connections allowed under heavy load
    pool_recycle=1800,    # refresh connections every 30 minutes
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database_connection() -> tuple[bool, str | None]:
    """Runs 'SELECT 1'. Returns (ok, postgres_version_or_error)."""
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar_one()
        return True, str(version)
    except Exception as exc:  # noqa: BLE001
        return False, exc.__class__.__name__
