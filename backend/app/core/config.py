from pydantic import Field, PostgresDsn, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.dsn import require_tls_for_remote_hosts


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
    # Which build/environment an event came from (DEPLOYMENT.md §6). None lets the Sentry SDK fall
    # back to its own SENTRY_RELEASE/SENTRY_ENVIRONMENT process env vars, then its defaults.
    SENTRY_RELEASE: str | None = None
    SENTRY_ENVIRONMENT: str | None = None

    # DB connection pool (core/db.py). Defaults are SQLAlchemy's own (5 + 10), stated here so the
    # readiness probe and the pool-utilization warning read the SAME capacity the engine was built
    # with instead of re-deriving it. Production sizing is a deployment decision bounded by
    # Postgres's max_connections (60 on the current Supabase project, read live 2026-09-19):
    # (pool_size + max_overflow) x worker processes must stay under ~80% of it (Supabase's
    # connection-management guide), leaving room for Auth's own connections.
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)
    # Warn (app.pool log) when checked-out / capacity reaches this — leading indicator, not failure.
    DB_POOL_WARN_RATIO: float = Field(default=0.7, gt=0, le=1)
    # Bounds how long opening a NEW physical connection (pool exhausted, or a stale one recycled)
    # may block, in libpq's own units (seconds). Without this, psycopg's connect() has no
    # application-level bound at all — confirmed live (2026-09-22) via a faulthandler thread-stack
    # dump during a schemathesis fuzz run: `get_current_profile` (api/deps.py) sat inside
    # `psycopg.connection.connect` -> `selectors.select`, blocked for the full ~260s Windows took to
    # give up the TCP handshake on its own, not any timeout this app set. Denial_of_Service_Cheat_
    # Sheet.md ("Define an absolute connection timeout") and ASVS 13.1.3/13.2.6 (short timeouts,
    # documented behavior at the connection limit, on every external sync connection) both name this
    # exact gap. Same value `ops/db_check.py` already uses for its own separate diagnostic
    # connection (_CONNECT_TIMEOUT_SECONDS = 10) — kept in sync, not independently chosen.
    DB_CONNECT_TIMEOUT_SECONDS: int = Field(default=10, ge=1)

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

    @field_validator("DATABASE_URL", "MIGRATIONS_DATABASE_URL")
    @classmethod
    def _require_tls_to_remote_db(cls, v: PostgresDsn) -> PostgresDsn:
        # The rule and its reasoning live in core/dsn.py, shared with ops/db_check.py — same
        # fail-loud-at-startup stance as `_require_psycopg_driver` above.
        return require_tls_for_remote_hosts(v)

    @computed_field
    @property
    def JWKS_URL(self) -> str:
        return f"{self.SUPABASE_URL}/auth/v1/.well-known/jwks.json"

    @computed_field
    @property
    def JWT_ISSUER(self) -> str:
        return f"{self.SUPABASE_URL}/auth/v1"


settings = Settings()  # type: ignore[call-arg]  # fields come from the environment, not literals
