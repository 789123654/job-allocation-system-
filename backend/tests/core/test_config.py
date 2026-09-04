import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(database_url: str) -> Settings:
    return Settings(
        DATABASE_URL=database_url,  # pyright: ignore[reportArgumentType]
        MIGRATIONS_DATABASE_URL="postgresql+psycopg://test:test@localhost:5432/test",  # pyright: ignore[reportArgumentType]
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_SECRET_KEY="sb_secret_test",
        CORS_ORIGINS=["http://localhost"],
    )


def test_bare_postgresql_scheme_is_rejected() -> None:
    """SQLAlchemy would otherwise silently pick psycopg2, which isn't installed — Supabase's
    dashboard hands out exactly this bare form, so it's a real copy-paste mistake to guard.
    """
    with pytest.raises(ValidationError, match="psycopg2 isn't installed"):
        _settings("postgresql://test:test@localhost:5432/test")


def test_psycopg_scheme_is_accepted() -> None:
    settings = _settings("postgresql+psycopg://test:test@localhost:5432/test")
    assert settings.DATABASE_URL.scheme == "postgresql+psycopg"
