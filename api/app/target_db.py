from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.settings import settings

_engines: dict[str, AsyncEngine] = {}
_sessionmakers: dict[str, async_sessionmaker[AsyncSession]] = {}


def _sessionmaker_for(url: str) -> async_sessionmaker[AsyncSession]:
    if url not in _sessionmakers:
        engine = _engines.get(url)
        if engine is None:
            engine = create_async_engine(url, pool_pre_ping=True)
            _engines[url] = engine
        _sessionmakers[url] = async_sessionmaker(engine, expire_on_commit=False)
    return _sessionmakers[url]


@asynccontextmanager
async def target_session(url: str | None):
    db_url = url or settings.target_database_url
    maker = _sessionmaker_for(db_url)
    async with maker() as session:
        yield session
