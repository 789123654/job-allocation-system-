import pytest
from pydantic import ValidationError

from app.core.config import Settings

_BASE_KWARGS = {
    "MIGRATIONS_DATABASE_URL": "postgresql+psycopg://test:test@localhost:5432/test",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_SECRET_KEY": "sb_secret_test",
    "CORS_ORIGINS": ["http://localhost"],
}


def test_bare_postgresql_scheme_is_rejected() -> None:
    """SQLAlchemy would otherwise silently pick psycopg2, which isn't installed — Supabase's
    dashboard hands out exactly this bare form, so it's a real copy-paste mistake to guard.
    """
    with pytest.raises(ValidationError, match="psycopg2 isn't installed"):
        Settings(DATABASE_URL="postgresql://test:test@localhost:5432/test", **_BASE_KWARGS)  # type: ignore[arg-type]


def test_psycopg_scheme_is_accepted() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+psycopg://test:test@localhost:5432/test",  # type: ignore[arg-type]
        **_BASE_KWARGS,
    )
    assert settings.DATABASE_URL.scheme == "postgresql+psycopg"
