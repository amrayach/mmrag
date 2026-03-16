import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from .. import config, db

logger = logging.getLogger("controlcenter.routes.data_explorer")

router = APIRouter(prefix="/api/data-explorer", tags=["data-explorer"])


def _serialize(rows: list[dict]) -> list[dict]:
    """Convert UUID and datetime fields to JSON-safe strings."""
    for row in rows:
        for k, v in row.items():
            if isinstance(v, UUID):
                row[k] = str(v)
            elif hasattr(v, "isoformat"):
                row[k] = v.isoformat()
    return rows


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@router.get("/documents")
async def list_documents(
    source_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
    response: Response = None,
):
    """List all documents with chunk/image counts."""
    try:
        # Count query
        count_sql = """
            SELECT COUNT(DISTINCT d.doc_id) FROM rag_docs d
            LEFT JOIN rag_chunks c ON d.doc_id = c.doc_id
        """
        count_params = ()
        if source_type:
            if source_type == "rss":
                count_sql += " WHERE c.meta->>'content_type' = %s"
                count_params = ("rss_article",)
            elif source_type == "pdf":
                count_sql += " WHERE d.filename ILIKE %s"
                count_params = ("%.pdf",)

        total = (await db.fetch_one(count_sql, count_params))[0]

        sql = """
            SELECT d.doc_id, d.filename, d.lang, d.pages, d.created_at,
                   COUNT(c.id) AS chunk_count,
                   COUNT(c.id) FILTER (WHERE c.chunk_type = 'image') AS image_count,
                   MAX(c.meta->>'content_type') AS source_type
            FROM rag_docs d
            LEFT JOIN rag_chunks c ON d.doc_id = c.doc_id
        """
        params = []
        if source_type:
            if source_type == "rss":
                sql += " WHERE c.meta->>'content_type' = %s"
                params.append("rss_article")
            elif source_type == "pdf":
                sql += " WHERE d.filename ILIKE %s"
                params.append("%.pdf")
        sql += " GROUP BY d.doc_id ORDER BY d.created_at DESC OFFSET %s LIMIT %s"
        params.extend([offset, limit])

        rows = await db.fetch_all_dicts(sql, tuple(params))
        if response is not None:
            response.headers["X-Total-Count"] = str(total)
        return _serialize(rows)
    except Exception as e:
        logger.error("list_documents error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to query documents")


# ---------------------------------------------------------------------------
# Chunks for a document
# ---------------------------------------------------------------------------

@router.get("/chunks/{doc_id}")
async def get_chunks(doc_id: str):
    """Get chunks for a specific document."""
    try:
        rows = await db.fetch_all_dicts("""
            SELECT id, chunk_type, page,
                   LEFT(content_text, 500) AS content_text,
                   caption, asset_path,
                   meta->>'content_type' AS source_type
            FROM rag_chunks
            WHERE doc_id = %s::uuid
            ORDER BY page, id
        """, (doc_id,))
        return _serialize(rows)
    except Exception as e:
        logger.error("get_chunks error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to query chunks")


# ---------------------------------------------------------------------------
# Images (paginated)
# ---------------------------------------------------------------------------

@router.get("/images")
async def list_images(
    offset: int = 0,
    limit: int = 50,
    response: Response = None,
):
    """List unique images with captions and asset paths (deduplicated)."""
    try:
        total_row = await db.fetch_one(
            "SELECT COUNT(DISTINCT asset_path) FROM rag_chunks "
            "WHERE chunk_type = 'image' AND asset_path IS NOT NULL"
        )
        total = total_row[0] if total_row else 0

        rows = await db.fetch_all_dicts("""
            SELECT DISTINCT ON (c.asset_path)
                   c.id, c.doc_id, c.caption, c.asset_path, c.page,
                   d.filename, c.meta->>'content_type' AS source_type
            FROM rag_chunks c
            JOIN rag_docs d ON c.doc_id = d.doc_id
            WHERE c.chunk_type = 'image' AND c.asset_path IS NOT NULL
            ORDER BY c.asset_path, c.id DESC
        """)
        # Apply offset/limit in Python since DISTINCT ON + ORDER BY id DESC
        # needs a subquery otherwise
        rows = rows[offset:offset + limit]
        if response is not None:
            response.headers["X-Total-Count"] = str(total)
        return _serialize(rows)
    except Exception as e:
        logger.error("list_images error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to query images")


# ---------------------------------------------------------------------------
# Latest ingestions
# ---------------------------------------------------------------------------

@router.get("/latest")
async def latest_docs():
    """Most recently ingested documents."""
    try:
        rows = await db.fetch_all_dicts("""
            SELECT d.doc_id, d.filename, d.pages, d.created_at,
                   COUNT(c.id) AS chunk_count,
                   COUNT(c.id) FILTER (WHERE c.chunk_type = 'image') AS image_count,
                   MAX(c.meta->>'content_type') AS source_type
            FROM rag_docs d
            LEFT JOIN rag_chunks c ON d.doc_id = c.doc_id
            GROUP BY d.doc_id
            ORDER BY d.created_at DESC
            LIMIT 20
        """)
        return _serialize(rows)
    except Exception as e:
        logger.error("latest_docs error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to query latest docs")


# ---------------------------------------------------------------------------
# Vector search
# ---------------------------------------------------------------------------

class VectorSearchRequest(BaseModel):
    query: str
    limit: int = 6
    threshold: float = 0.5


@router.post("/vector-search")
async def vector_search(req: VectorSearchRequest):
    """Embed a query via Ollama and run cosine similarity search."""
    # Step 1: Get embedding from Ollama
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{config.OLLAMA_BASE_URL}/api/embed",
                json={"model": config.OLLAMA_EMBED_MODEL, "input": req.query},
            )
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embeddings", [[]])[0]
            if not embedding:
                raise HTTPException(status_code=502, detail="Empty embedding returned")
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=503,
            detail="Embedding model busy — try again in a moment",
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama unavailable")

    # Step 2: Cosine similarity query
    try:
        rows = await db.fetch_all_dicts("""
            SELECT c.id, c.doc_id, c.chunk_type, c.page,
                   LEFT(c.content_text, 500) AS content_text,
                   c.caption, c.asset_path,
                   d.filename,
                   c.meta->>'content_type' AS source_type,
                   1 - (c.embedding <=> %s::vector) AS similarity
            FROM rag_chunks c
            JOIN rag_docs d ON c.doc_id = d.doc_id
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
        """, (str(embedding), str(embedding), req.limit))

        # Post-filter by threshold
        results = [r for r in rows if r.get("similarity", 0) >= req.threshold]
        return {
            "query": req.query,
            "results": _serialize(results),
            "total_before_filter": len(rows),
            "threshold": req.threshold,
        }
    except Exception as e:
        logger.error("vector_search error: %s", e)
        raise HTTPException(status_code=500, detail="Vector search failed")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
async def explorer_stats():
    """Aggregate statistics for the knowledge base."""
    try:
        total_docs = (await db.fetch_one("SELECT COUNT(*) FROM rag_docs"))[0]

        chunk_rows = await db.fetch_all(
            "SELECT chunk_type, COUNT(*) FROM rag_chunks GROUP BY chunk_type"
        )
        chunks_by_type = {row[0]: row[1] for row in chunk_rows}

        source_rows = await db.fetch_all("""
            SELECT meta->>'content_type' AS source_type, COUNT(DISTINCT doc_id)
            FROM rag_chunks GROUP BY meta->>'content_type'
        """)
        docs_by_source = {row[0] or "unknown": row[1] for row in source_rows}

        embedded = (await db.fetch_one(
            "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL"
        ))[0]

        unique_images = (await db.fetch_one(
            "SELECT COUNT(DISTINCT asset_path) FROM rag_chunks "
            "WHERE chunk_type = 'image' AND asset_path IS NOT NULL"
        ))[0]

        return {
            "total_docs": total_docs,
            "total_chunks": sum(chunks_by_type.values()),
            "chunks_by_type": chunks_by_type,
            "docs_by_source": docs_by_source,
            "embedded_chunks": embedded,
            "unique_images": unique_images,
        }
    except Exception as e:
        logger.error("explorer_stats error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to query stats")
