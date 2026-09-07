from pydantic import PostgresDsn, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_ignore_empty=True, extra="ignore")

    # fastapi_app role connection string — never the Supabase `postgres` superuser role,
    # which carries BYPASSRLS (ARCHITECTURE.md §5).
    DATABASE_URL: PostgresDsn

    # Alembic only, never used by the running app. Needs privileges fastapi_app deliberately lacks
    # (CREATE ROLE, writes to Supabase's `auth` schema) — DEPLOYMENT.md §2.
    MIGRATIONS_DATABASE_URL: PostgresDsn

    # e.g. "https://xxxx.supabase.co" — used to derive the JWKS URL and expected issuer.
    SUPABASE_URL: str

    # Tauri webview origin(s), explicit allowlist only — never "*" (API_SPEC.md §1).
    CORS_ORIGINS: list[str]

    # Supabase's "secret" key (sb_secret_..., replaces the legacy service_role key) — bypasses RLS,
    # server-only, used solely for the Auth Admin API (create/reset employee accounts). Never the
    # publishable key, never exposed to the frontend (supabase/auth/users.md).
    SUPABASE_SECRET_KEY: str

    # Optional — error/performance monitoring (DEPLOYMENT.md §6). None (the default) means Sentry
    # is never initialized at all: local dev and CI have no reason to send anything anywhere.
    SENTRY_DSN: str | None = None

    @field_validator("DATABASE_URL", "MIGRATIONS_DATABASE_URL")
    @classmethod
    def _require_psycopg_driver(cls, v: PostgresDsn) -> PostgresDsn:
        # SQLAlchemy defaults a bare "postgresql://" scheme to psycopg2, which this project
        # doesn't install (psycopg v3 is the actual dependency) — Supabase's dashboard hands out
        # exactly that bare form, so this is a real, easy copy-paste mistake. Fail loudly here,
        # not three layers deep inside SQLAlchemy's engine creation with a bare
        # "ModuleNotFoundError: No module named 'psycopg2'".
        if v.scheme != "postgresql+psycopg":
            raise ValueError(
                f"must use postgresql+psycopg://, got {v.scheme}:// (psycopg2 isn't installed)"
            )
        return v

    @computed_field
    @property
    def JWKS_URL(self) -> str:
        return f"{self.SUPABASE_URL}/auth/v1/.well-known/jwks.json"

    @computed_field
    @property
    def JWT_ISSUER(self) -> str:
        return f"{self.SUPABASE_URL}/auth/v1"


settings = Settings()  # type: ignore[call-arg]  # fields come from the environment, not literals
