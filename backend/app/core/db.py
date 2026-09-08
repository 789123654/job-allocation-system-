from collections.abc import Generator

from sqlmodel import Session, create_engine

from app.core.config import settings

# Migrations (Alembic) own schema creation, not create_all() (fastapi/sql-databases.md).
engine = create_engine(str(settings.DATABASE_URL))


def get_session() -> Generator[Session]:
    # expire_on_commit=False (SQLAlchemy default is True) — every request gets its own fresh
    # session here that never outlives that request (`with Session(...)`, closed at request end),
    # so there's no cross-request staleness risk to trade away. What the default *would* cost:
    # any attribute read on an ORM object after a mid-request commit() silently fires a fresh
    # SELECT to reload it — and get_current_profile's tenant context (`app.current_tenant`,
    # api/deps.py) is deliberately transaction-scoped (SET LOCAL-style), so that implicit SELECT
    # runs with no tenant context at all. Depending on whether the pooled connection had ever seen
    # a tenant context before, that either matched 0 rows or crashed on a raw uuid cast — the real
    # mechanism behind 4 crashes Schemathesis found (2026-09-08, docs/SECURITY_AUDIT_CHECKLIST.md).
    # This is the root-cause fix — it also protects every future create/update handler that
    # commits then returns the object, not just the ones already found and fixed at the call site.
    with Session(engine, expire_on_commit=False) as session:
        yield session
