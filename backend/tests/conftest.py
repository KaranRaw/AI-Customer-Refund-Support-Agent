"""Pytest fixtures for database-backed tests.

Tests run against a dedicated refund_agent_test database, freshly seeded per test, so
each test starts from a known state and never touches development data.
"""

from datetime import datetime, timezone

import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import models  # noqa: F401 - import registers models on Base.metadata
from app.db.database import Base
from app.db.seed import _build_customers, _build_orders


def _test_database_url() -> str:
    base, _, _name = get_settings().database_url.rpartition("/")
    return f"{base}/refund_agent_test"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(_test_database_url())
    async with engine.begin() as conn:
        # Drop first so model changes (e.g. new columns) take effect on a reused test DB.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        session.add_all(_build_customers())
        session.add_all(_build_orders(datetime.now(timezone.utc)))
        await session.commit()
        yield session

    await engine.dispose()
