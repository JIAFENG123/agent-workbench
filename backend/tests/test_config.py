from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings


def test_database_url_normalization_postgres_scheme() -> None:
    s = Settings(database_url="postgres://user:pass@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://user:pass@host:5432/db"
    engine = create_async_engine(s.database_url)
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "asyncpg"


def test_database_url_normalization_postgresql_scheme() -> None:
    s = Settings(database_url="postgresql://user:pass@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://user:pass@host:5432/db"
    engine = create_async_engine(s.database_url)
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "asyncpg"


def test_database_url_normalization_psycopg_to_asyncpg() -> None:
    s = Settings(database_url="postgresql+psycopg://user:pass@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_database_url_normalization_sslmode_to_ssl() -> None:
    s = Settings(
        database_url="postgresql://user:pass@ep-cool-frost.neon.tech/neondb?sslmode=require&channel_binding=require"
    )
    assert s.database_url == "postgresql+asyncpg://user:pass@ep-cool-frost.neon.tech/neondb?ssl=require"


def test_database_url_normalization_sslmode_disable() -> None:
    s = Settings(database_url="postgresql://user:pass@localhost:5432/db?sslmode=disable")
    assert s.database_url == "postgresql+asyncpg://user:pass@localhost:5432/db"


def test_database_url_preserves_existing_asyncpg() -> None:
    s = Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/workbench")
    assert s.database_url == "postgresql+asyncpg://postgres:postgres@localhost:5432/workbench"
