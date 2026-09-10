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


def test_remote_db_without_verify_full_is_rejected() -> None:
    """ASVS 12.3.1/12.3.2 + DEPLOYMENT.md §2 — a non-loopback Postgres host must carry
    sslmode=verify-full, or the app refuses to boot (fail loud, like the psycopg2 guard).
    """
    with pytest.raises(ValidationError, match="sslmode=verify-full"):
        _settings("postgresql+psycopg://u:p@db.abcdefgh.supabase.co:5432/postgres")


def test_remote_db_with_sslmode_require_is_still_rejected() -> None:
    # `require` encrypts but does not validate the cert — satisfies 12.3.1, fails 12.3.2.
    with pytest.raises(ValidationError, match="sslmode=verify-full"):
        _settings("postgresql+psycopg://u:p@db.abcdefgh.supabase.co:5432/postgres?sslmode=require")


def test_remote_db_with_verify_full_is_accepted() -> None:
    settings = _settings(
        "postgresql+psycopg://u:p@db.abcdefgh.supabase.co:5432/postgres?sslmode=verify-full"
    )
    assert settings.DATABASE_URL.hosts()[0]["host"] == "db.abcdefgh.supabase.co"


def test_loopback_db_without_tls_is_allowed() -> None:
    # local dev + CI's postgres service container — the connection never crosses a network
    settings = _settings("postgresql+psycopg://test:test@127.0.0.1:5432/test")
    assert settings.DATABASE_URL.query is None
