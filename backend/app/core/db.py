from collections.abc import Generator

from sqlmodel import Session, create_engine

from app.core.config import settings

# Migrations (Alembic) own schema creation, not create_all() (fastapi/sql-databases.md).
engine = create_engine(str(settings.DATABASE_URL))


def get_session() -> Generator[Session]:
    with Session(engine) as session:
        yield session
