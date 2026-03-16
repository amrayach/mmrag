import logging
from typing import Optional

from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

from . import config

logger = logging.getLogger("controlcenter.db")

pool: Optional[AsyncConnectionPool] = None


async def _configure_conn(conn):
    """Register pgvector type adapter on each new connection."""
    await register_vector_async(conn)


async def init_pool():
    global pool
    conninfo = (
        f"host={config.DATABASE_HOST} "
        f"port={config.DATABASE_PORT} "
        f"dbname={config.DATABASE_NAME} "
        f"user={config.DATABASE_USER} "
        f"password={config.DATABASE_PASSWORD}"
    )
    pool = AsyncConnectionPool(
        conninfo, min_size=1, max_size=3, open=False,
        configure=_configure_conn,
    )
    await pool.open()
    logger.info("Async DB pool initialized (min=1, max=3, pgvector=on)")


async def close_pool():
    global pool
    if pool:
        await pool.close()
        pool = None
        logger.info("DB pool closed")


async def fetch_one(query: str, params: tuple = ()):
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchone()


async def fetch_all(query: str, params: tuple = ()):
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchall()


async def fetch_all_dicts(query: str, params: tuple = ()) -> list[dict]:
    """Execute query and return results as list of dicts."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            cols = [desc[0] for desc in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]


async def fetch_one_dict(query: str, params: tuple = ()) -> dict | None:
    """Execute query and return single result as dict, or None."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))


async def get_doc_counts() -> dict:
    """Get aggregate counts for dashboard metrics."""
    try:
        row = await fetch_one(
            "SELECT COUNT(*) FROM rag_docs"
        )
        total_docs = row[0] if row else 0

        row = await fetch_one(
            "SELECT COUNT(*) FROM rag_chunks"
        )
        total_chunks = row[0] if row else 0

        row = await fetch_one(
            "SELECT COUNT(*) FROM rag_chunks WHERE chunk_type = 'image'"
        )
        total_images = row[0] if row else 0

        return {
            "total_docs": total_docs,
            "total_chunks": total_chunks,
            "total_images": total_images,
        }
    except Exception as e:
        logger.error("Failed to get doc counts: %s", e)
        return {"total_docs": 0, "total_chunks": 0, "total_images": 0}
