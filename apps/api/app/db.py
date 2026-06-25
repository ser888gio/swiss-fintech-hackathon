"""Async SQLAlchemy session factory and DB lifecycle.

Backed by Postgres (asyncpg) in production. Gracefully degrades to in-memory-only
if the DB is unreachable — the store's write-through cache keeps the app working
without a DB; Postgres just adds durability across restarts.

`init_db(url)` is called once at FastAPI startup (`main.py lifespan`). After that
`get_session()` and the module-level `session_factory` are usable. If `init_db`
failed (no DB), they are None and every caller must guard with `if session_factory`.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

log = logging.getLogger(__name__)

# Module-level: set by init_db on first successful connection. None means no DB.
session_factory: async_sessionmaker[AsyncSession] | None = None
DB_STARTUP_TIMEOUT_SECONDS = 5.0


async def init_db(database_url: str) -> bool:
    """Create tables and wire the session factory. Returns True on success.

    Uses `checkfirst=True` so create_all is safe to call on an existing schema.
    Caller (main.py lifespan) catches exceptions; this function only logs and
    returns False on DB error so the app starts in graceful in-memory mode.
    """
    global session_factory
    engine = None
    try:
        engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
        async with asyncio.timeout(DB_STARTUP_TIMEOUT_SECONDS):
            async with engine.begin() as conn:
                await _prepare_schema(conn)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        log.info("Postgres connected; audit store ready.")
        return True
    except Exception as exc:
        session_factory = None
        if engine is not None:
            await engine.dispose()
        log.warning("DB unavailable — running in-memory only: %s", exc)
        return False


async def _prepare_schema(conn) -> None:
    await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    if conn.dialect.name == "postgresql":
        await _run_postgres_migrations(conn)
    elif conn.dialect.name == "sqlite":
        await _run_sqlite_migrations(conn)


async def _run_postgres_migrations(conn) -> None:
    """Apply additive migrations that SQLAlchemy create_all will not backfill."""
    statements = (
        "ALTER TABLE service_payments ADD COLUMN IF NOT EXISTS agent_id VARCHAR",
        "ALTER TABLE service_payments ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'settled'",
        "ALTER TABLE service_payments ADD COLUMN IF NOT EXISTS cover JSON",
        "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS user_id VARCHAR",
        "CREATE INDEX IF NOT EXISTS ix_credentials_user_id ON credentials (user_id)",
        "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS subject_country VARCHAR",
        "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS subject_entity_type VARCHAR",
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS auto_insure JSON",
    )
    for statement in statements:
        await conn.execute(text(statement))


async def _run_sqlite_migrations(conn) -> None:
    """Apply local SQLite-only migrations, tolerating already-existing columns."""
    try:
        await conn.execute(text("ALTER TABLE agents ADD COLUMN auto_insure JSON"))
    except Exception:
        pass
