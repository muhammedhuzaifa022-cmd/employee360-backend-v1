"""
Alembic environment: tells Alembic WHICH database to change and
WHAT the tables should look like (our models).

Which database?
  alembic upgrade head              -> DATABASE_URL       (real data)
  alembic -x db=test upgrade head   -> TEST_DATABASE_URL  (tests only)
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.models import Base  # importing this loads every table

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    # 1) URL passed in by code (used by the automated tests)
    url = config.attributes.get("db_url")
    if url:
        return url
    # 2) "-x db=test" on the command line
    if context.get_x_argument(as_dictionary=True).get("db") == "test":
        if not settings.TEST_DATABASE_URL:
            raise RuntimeError("TEST_DATABASE_URL is not set in .env")
        return settings.TEST_DATABASE_URL
    # 3) default: the real database
    return settings.DATABASE_URL


COMMON_OPTIONS = dict(
    target_metadata=target_metadata,
    compare_type=True,            # notice column type changes
    compare_server_default=True,  # notice default value changes
)


def run_migrations_offline() -> None:
    """'alembic upgrade head --sql' : prints the SQL instead of running it."""
    context.configure(url=get_database_url(), literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, **COMMON_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, **COMMON_OPTIONS)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
