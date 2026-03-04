import json
import uuid
from typing import Any, Dict, List, Optional, Tuple


def get_rss_doc_id(article_url: str) -> uuid.UUID:
    """Generate a deterministic UUID for an RSS article URL."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mmrag:rss:{article_url}")


def upsert_doc(cur, doc_id: uuid.UUID, filename: str, sha: str, lang: str, pages: int):
    cur.execute(
        """
        INSERT INTO rag_docs(doc_id, filename, sha256, lang, pages, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (doc_id) DO UPDATE
        SET filename=EXCLUDED.filename,
            sha256=EXCLUDED.sha256,
            lang=EXCLUDED.lang,
            pages=EXCLUDED.pages,
            updated_at=now()
        """,
        (doc_id, filename, sha, lang, pages),
    )


def delete_doc_chunks(cur, doc_id: uuid.UUID):
    cur.execute("DELETE FROM rag_chunks WHERE doc_id=%s", (doc_id,))


def insert_chunk(
    cur,
    doc_id: uuid.UUID,
    chunk_type: str,
    page: int,
    content_text: Optional[str],
    caption: Optional[str],
    asset_path: Optional[str],
    embedding: Optional[List[float]],
    meta: Dict[str, Any],
):
    cur.execute(
        """
        INSERT INTO rag_chunks(doc_id, chunk_type, page, content_text, caption, asset_path, embedding, meta)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (doc_id, chunk_type, page, content_text, caption, asset_path, embedding, json.dumps(meta)),
    )


def should_process(cur, doc_id: uuid.UUID, sha: str) -> Tuple[bool, Optional[str]]:
    cur.execute("SELECT sha256 FROM rag_docs WHERE doc_id=%s", (doc_id,))
    row = cur.fetchone()
    if not row:
        return True, None
    existing = row[0]
    return existing != sha, existing


def get_docs_missing_images(cur, limit: int = 0) -> list:
    """Find RSS docs that have text chunks but no image chunks."""
    sql = """
        SELECT d.doc_id, d.filename AS url
        FROM rag_docs d
        WHERE d.doc_id IN (
            SELECT doc_id FROM rag_chunks
            WHERE meta->>'content_type' = 'rss_article' AND chunk_type = 'text'
        )
        AND d.doc_id NOT IN (
            SELECT doc_id FROM rag_chunks
            WHERE meta->>'content_type' = 'rss_article' AND chunk_type = 'image'
        )
        ORDER BY d.updated_at DESC
    """
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    cur.execute(sql)
    return [{"doc_id": row[0], "url": row[1]} for row in cur.fetchall()]


def get_all_image_chunks(cur, limit: int = 0) -> list:
    """Get all RSS image chunks for re-captioning."""
    sql = """
        SELECT id, doc_id, caption, asset_path, meta
        FROM rag_chunks
        WHERE chunk_type = 'image'
          AND asset_path IS NOT NULL
        ORDER BY id
    """
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    cur.execute(sql)
    return [
        {
            "id": row[0],
            "doc_id": row[1],
            "caption": row[2],
            "asset_path": row[3],
            "meta": row[4] if isinstance(row[4], dict) else {},
        }
        for row in cur.fetchall()
    ]


def update_chunk_caption_embedding(cur, chunk_id: int, caption: str, embedding: Optional[list]):
    """Update an existing chunk's caption and embedding in-place."""
    cur.execute(
        "UPDATE rag_chunks SET caption = %s, embedding = %s WHERE id = %s",
        (caption, embedding, chunk_id),
    )
