"""Async SQLAlchemy session factory and DB lifecycle.

Backed by Postgres (asyncpg) in production. Gracefully degrades to in-memory-only
if the DB is unreachable — the store's write-through cache keeps the app working
without a DB; Postgres just adds durability across restarts.

`init_db(url)` is called once at FastAPI startup (`main.py lifespan`). After that
`get_session()` and the module-level `session_factory` are usable. If `init_db`
failed (no DB), they are None and every caller must guard with `if session_factory`.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

log = logging.getLogger(__name__)

# Module-level: set by init_db on first successful connection. None means no DB.
session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(database_url: str) -> bool:
    """Create tables and wire the session factory. Returns True on success.

    Uses `checkfirst=True` so create_all is safe to call on an existing schema.
    Caller (main.py lifespan) catches exceptions; this function only logs and
    returns False on DB error so the app starts in graceful in-memory mode.
    """
    global session_factory
    try:
        engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        log.info("Postgres connected; audit store ready.")
        return True
    except Exception as exc:
        log.warning("DB unavailable — running in-memory only: %s", exc)
        return False
