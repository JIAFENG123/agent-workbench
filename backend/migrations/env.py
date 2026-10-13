from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
settings = get_settings()


def _sync_url() -> str:
    """Alembic runs migrations through a synchronous driver.

    The application talks to Postgres over asyncpg; migrations use psycopg instead, so a
    migration never has to be written against an event loop. The two drivers also disagree on
    how TLS is requested — asyncpg reads ``ssl=require``, libpq/psycopg read ``sslmode=require``
    — so the query string is translated rather than left to fail at connect time.
    """
    url = make_url(settings.database_url)
    query = dict(url.query)
    if "ssl" in query:
        query["sslmode"] = query.pop("ssl")
    return url.set(drivername="postgresql+psycopg", query=query).render_as_string(
        hide_password=False
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_sync_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
