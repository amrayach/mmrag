import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Query

from .. import config, db

logger = logging.getLogger("controlcenter.routes.ingestion")

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


# ---------------------------------------------------------------------------
# PDF ingestion
# ---------------------------------------------------------------------------

@router.post("/pdf/upload", status_code=202)
async def pdf_upload(file: UploadFile = File(...)):
    """Stream multipart upload directly to pdf-ingest service."""
    async with httpx.AsyncClient(timeout=config.TIMEOUT_LONG) as client:
        try:
            content = await file.read()
            resp = await client.post(
                f"{config.PDF_INGEST_URL}/ingest/upload",
                files={"file": (file.filename, content, file.content_type or "application/pdf")},
            )
            return resp.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="PDF upload timed out")
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="pdf-ingest service unavailable")


@router.post("/pdf/scan")
async def pdf_scan():
    """Trigger PDF scan via n8n webhook (lights up n8n canvas)."""
    async with httpx.AsyncClient(timeout=config.TIMEOUT_N8N_WEBHOOK) as client:
        try:
            resp = await client.post(f"{config.N8N_BASE_URL}/webhook/ingest-now")
            return {"status": "ok", "n8n_status": resp.status_code}
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="n8n webhook timed out")
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="n8n unavailable")


@router.get("/pdf/status")
async def pdf_status():
    """Proxy to pdf-ingest /ingest/status."""
    async with httpx.AsyncClient(timeout=config.TIMEOUT_STANDARD) as client:
        try:
            resp = await client.get(f"{config.PDF_INGEST_URL}/ingest/status")
            return resp.json()
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="pdf-ingest service unavailable")


# ---------------------------------------------------------------------------
# RSS ingestion
# ---------------------------------------------------------------------------

@router.post("/rss/sync")
async def rss_sync():
    """Trigger RSS sync via n8n webhook (lights up n8n canvas)."""
    async with httpx.AsyncClient(timeout=config.TIMEOUT_N8N_WEBHOOK) as client:
        try:
            resp = await client.post(f"{config.N8N_BASE_URL}/webhook/rss-ingest-now")
            return {"status": "ok", "n8n_status": resp.status_code}
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="n8n webhook timed out")
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="n8n unavailable")


@router.post("/rss/backfill", status_code=202)
async def rss_backfill():
    """Fire-and-forget: trigger RSS image backfill."""
    async with httpx.AsyncClient(timeout=config.TIMEOUT_LONG) as client:
        try:
            resp = await client.post(f"{config.RSS_INGEST_URL}/ingest/backfill-images")
            return resp.json()
        except httpx.TimeoutException:
            return {"status": "accepted", "message": "Backfill started (long-running)"}
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="rss-ingest service unavailable")


@router.post("/rss/recaption", status_code=202)
async def rss_recaption():
    """Fire-and-forget: trigger RSS image recaption."""
    async with httpx.AsyncClient(timeout=config.TIMEOUT_LONG) as client:
        try:
            resp = await client.post(f"{config.RSS_INGEST_URL}/ingest/recaption-images")
            return resp.json()
        except httpx.TimeoutException:
            return {"status": "accepted", "message": "Recaption started (long-running)"}
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="rss-ingest service unavailable")


@router.get("/rss/status")
async def rss_status():
    """Proxy to rss-ingest /ingest/status."""
    async with httpx.AsyncClient(timeout=config.TIMEOUT_STANDARD) as client:
        try:
            resp = await client.get(f"{config.RSS_INGEST_URL}/ingest/status")
            return resp.json()
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="rss-ingest service unavailable")


# ---------------------------------------------------------------------------
# DB stats (cross-service)
# ---------------------------------------------------------------------------

@router.get("/db-stats")
async def db_stats():
    """Aggregate chunk counts by type and source."""
    try:
        rows = await db.fetch_all(
            "SELECT chunk_type, COUNT(*) as cnt FROM rag_chunks GROUP BY chunk_type ORDER BY chunk_type"
        )
        by_type = {row[0]: row[1] for row in rows}

        doc_rows = await db.fetch_all(
            "SELECT COUNT(*) FROM rag_docs"
        )
        total_docs = doc_rows[0][0] if doc_rows else 0

        return {
            "total_docs": total_docs,
            "chunks_by_type": by_type,
            "total_chunks": sum(by_type.values()),
        }
    except Exception as e:
        logger.error("DB stats error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to query DB stats")


# ---------------------------------------------------------------------------
# Ingestion history
# ---------------------------------------------------------------------------

@router.get("/history")
async def ingestion_history():
    """Recent document ingestions with chunk counts."""
    try:
        rows = await db.fetch_all_dicts("""
            SELECT d.doc_id, d.filename, d.pages, d.created_at,
                   COUNT(c.id) AS chunks,
                   COUNT(c.id) FILTER (WHERE c.chunk_type = 'image') AS images,
                   MAX(c.meta->>'content_type') AS source_type
            FROM rag_docs d
            LEFT JOIN rag_chunks c ON d.doc_id = c.doc_id
            GROUP BY d.doc_id
            ORDER BY d.created_at DESC
            LIMIT 20
        """)
        for row in rows:
            if isinstance(row.get("doc_id"), UUID):
                row["doc_id"] = str(row["doc_id"])
            if hasattr(row.get("created_at"), "isoformat"):
                row["created_at"] = row["created_at"].isoformat()
        return rows
    except Exception as e:
        logger.error("ingestion_history error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to query ingestion history")
