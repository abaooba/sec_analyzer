"""Database engine + session factory.

This is the one place the SQLAlchemy `engine` (the connection pool to the DB)
and `SessionLocal` (a factory that hands out Session objects) are created. Every
module that needs DB access imports `SessionLocal` from here and uses it as a
context manager: `with SessionLocal() as session: ...`.

`future=True` opts into SQLAlchemy 2.0-style behavior.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import Base

# The engine lazily manages connections to the DB at settings.database_url.
engine = create_engine(settings.database_url, future=True)
# A configured factory; calling SessionLocal() opens a new unit-of-work session.
SessionLocal = sessionmaker(bind=engine, future=True)


def init_db():
    """Create any tables that don't exist yet (idempotent).

    Reads the table definitions registered on Base.metadata (i.e. the models)
    and issues CREATE TABLE IF NOT EXISTS for each. Safe to call on every run.
    """
    Base.metadata.create_all(engine)
