"""
database/base.py
----------------
SQLAlchemy async engine, session factory, and declarative base.
All models import Base from here to stay in the same metadata graph.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config.settings import get_settings

settings = get_settings()

# Convert sync sqlite:/// URL to async aiosqlite driver
_raw_url = settings.database_url
if _raw_url.startswith("sqlite:///"):
    ASYNC_DATABASE_URL = _raw_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
elif _raw_url.startswith("sqlite+aiosqlite:///"):
    ASYNC_DATABASE_URL = _raw_url
else:
    raise ValueError(f"Unsupported database URL scheme: {_raw_url}")


engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=settings.debug,
    # aiosqlite manages threading internally; check_same_thread is not applicable
    # future=True is the default in SQLAlchemy 2.x
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Shared declarative base — all ORM models inherit from this."""
    pass


async def init_db() -> None:
    """
    Create all tables on startup.
    In production you'd use Alembic migrations instead.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """
    FastAPI dependency that yields a transactional AsyncSession.
    Automatically commits on success, rolls back on exception.

    Usage:
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise