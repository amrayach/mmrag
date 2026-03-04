import logging
import os
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import Optional

import requests
from fastapi import FastAPI
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import (
    DB_HOST, DB_NAME, DB_PASS, DB_PORT, DB_USER,
    LOCK_FILE, OLLAMA_BASE,
)

# ---------------------------------------------------------------------------
# Logging (structured JSON — matches pdf-ingest)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("rss-ingest")

# ---------------------------------------------------------------------------
# Connection pool (initialized in lifespan)
# ---------------------------------------------------------------------------
pool: Optional[ConnectionPool] = None

# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app):
    global pool
    # Startup: clean stale lock (container restart = previous worker is dead)
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
        logger.info("Stale lock removed on startup")

    conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS}"
    pool = ConnectionPool(
        conninfo, min_size=2, max_size=3, open=True,
        configure=lambda conn: register_vector(conn),
    )
    logger.info("Connection pool initialized (min=2, max=3)")
    logger.info("rss-ingest starting")
    yield
    pool.close()
    logger.info("rss-ingest shutting down")


app = FastAPI(title="rss-ingest", version="0.1.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Lock (file-based, same pattern as pdf-ingest)
# ---------------------------------------------------------------------------


@contextmanager
def ingestion_lock():
    if os.path.exists(LOCK_FILE):
        raise RuntimeError("busy")
    try:
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        yield
    finally:
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat()}


@app.get("/health/ready")
def health_ready():
    checks = {}
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = str(e)
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        checks["ollama"] = "ok" if r.ok else f"status {r.status_code}"
    except Exception as e:
        checks["ollama"] = str(e)
    ok = all(v == "ok" for v in checks.values())
    return {"ok": ok, "checks": checks}


@app.post("/ingest/feeds")
def ingest_feeds(max_articles: int = 0, lang: str = "de", dry_run: bool = False):
    from app.ingest import dry_run_all_feeds, ingest_all_feeds

    if dry_run:
        stats = dry_run_all_feeds(pool)
        return {"status": "dry_run", **stats}

    try:
        with ingestion_lock():
            stats = ingest_all_feeds(pool, lang=lang, max_articles=max_articles or None)
            return {"status": "ok", **stats}
    except RuntimeError as e:
        if str(e) == "busy":
            logger.info("Lock busy, returning busy status")
            return {"status": "busy", "reason": "ingestion_in_progress"}
        raise


@app.post("/ingest/backfill-images")
def backfill_images(limit: int = 50, lang: str = "de"):
    """Add image chunks to RSS articles that were ingested without images."""
    from app.db import get_docs_missing_images
    from app.ingest import backfill_images_for_doc

    try:
        with ingestion_lock():
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    docs = get_docs_missing_images(cur, limit=limit)

            results = {"total_candidates": len(docs), "processed": 0, "images_added": 0, "skipped": 0}
            for doc in docs:
                try:
                    r = backfill_images_for_doc(pool, doc["doc_id"], doc["url"], lang)
                    if r.get("status") == "ok":
                        results["processed"] += 1
                        results["images_added"] += r.get("images_added", 0)
                    else:
                        results["skipped"] += 1
                except Exception as e:
                    logger.warning("Backfill error for %s: %s", doc["url"], e)
                    results["skipped"] += 1

        return results
    except RuntimeError:
        logger.info("Lock busy, returning busy status")
        return {"status": "busy", "reason": "ingestion_in_progress"}


@app.post("/ingest/recaption-images")
def recaption_images(limit: int = 0, lang: str = "de"):
    """Re-caption all image chunks with context-aware prompts and re-embed."""
    from app.db import get_all_image_chunks
    from app.ingest import recaption_image_chunk

    try:
        with ingestion_lock():
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    chunks = get_all_image_chunks(cur, limit=limit)

            results = {
                "total_chunks": len(chunks),
                "recaptioned": 0,
                "skipped": 0,
                "errors": 0,
            }
            for i, chunk in enumerate(chunks):
                try:
                    r = recaption_image_chunk(pool, chunk, lang)
                    if r.get("status") == "ok":
                        results["recaptioned"] += 1
                    else:
                        results["skipped"] += 1
                except Exception as e:
                    logger.warning(
                        "Recaption error for chunk %s: %s", chunk["id"], e
                    )
                    results["errors"] += 1

                if (i + 1) % 50 == 0:
                    logger.info(
                        "Recaption progress: %d/%d done", i + 1, len(chunks)
                    )

            return results
    except RuntimeError:
        logger.info("Lock busy, returning busy status")
        return {"status": "busy", "reason": "ingestion_in_progress"}


@app.get("/ingest/status")
def ingest_status():
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM rag_docs WHERE filename LIKE 'http%%'"
            )
            doc_count = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE meta->>'content_type' = 'rss_article'"
            )
            chunk_count = cur.fetchone()[0]
    return {
        "rss_documents": doc_count,
        "rss_chunks": chunk_count,
    }
