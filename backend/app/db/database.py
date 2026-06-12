"""Async PostgreSQL engine, session factory, and declarative base."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

_settings = get_settings()

# pool_pre_ping recycles connections the server dropped (idle timeouts, restarts),
# so a stale pooled connection surfaces as a clean reconnect rather than an error.
engine = create_async_engine(_settings.database_url, pool_pre_ping=True)

# expire_on_commit=False keeps attributes accessible after commit, so objects can
# be read or serialized post-transaction without triggering a lazy reload.
SessionFactory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield a session and guarantee it is closed."""
    async with SessionFactory() as session:
        yield session


async def create_all() -> None:
    """Create all tables. Explicit by design; the app does not auto-migrate on boot."""
    from app.db import models  # noqa: F401 - import registers models on Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all() -> None:
    """Drop all tables — used by the seed to rebuild the schema from scratch."""
    from app.db import models  # noqa: F401 - import registers models on Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
