"""Gestión de conexión SQLAlchemy 2.0 para PostgreSQL 16 (y SQLite en pruebas)."""

from __future__ import annotations

from collections.abc import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import settings


class Base(DeclarativeBase):
    """Base declarativa SQLAlchemy 2.0."""


def create_db_engine(database_url: str | None = None):
    url = database_url or settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection(target_engine=None) -> bool:
    eng = target_engine or engine
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
