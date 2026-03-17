#!/usr/bin/env python3
"""Re-embed all rag_chunks using bge-m3 (1024 dimensions).

Run INSIDE rag-gateway container:
  docker compose exec -T rag-gateway python3 /tmp/reembed_bge_m3.py
"""

import json
import os
import time

import httpx
import psycopg
from psycopg.rows import dict_row

# Configuration — reads from container env (set by docker-compose)
DB_HOST = os.getenv("DATABASE_HOST", "postgres")
DB_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DB_NAME = os.getenv("DATABASE_NAME", "rag")
DB_USER = os.getenv("DATABASE_USER", "rag_user")
DB_PASS = os.getenv("DATABASE_PASSWORD", "")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = "bge-m3"
BATCH_SIZE = 15
FETCH_SIZE = 100
TIMEOUT = 60.0


def get_embed_text(chunk: dict) -> str:
    """Determine the text to embed for a chunk."""
    if chunk["chunk_type"] == "image":
        caption = chunk.get("caption") or "Bild"
        meta = chunk.get("meta") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        title = meta.get("title", "")
        feed = meta.get("feed_name", "")
        if title and feed:
            return f"[{feed}] {title} — {caption}"
        elif title:
            return f"{title} — {caption}"
        return caption
    else:
        return chunk.get("content_text") or ""


def embed_batch(client: httpx.Client, texts: list) -> list:
    """Call Ollama embed API with a batch of texts."""
    resp = client.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def main():
    print(f"Re-embedding all chunks with {EMBED_MODEL} (1024 dims)")
    print(f"DB: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"Ollama: {OLLAMA_URL}")
    print()

    # Warm up model
    print("Warming up bge-m3...")
    with httpx.Client() as client:
        embed_batch(client, ["Warmup test."])
    print("Model ready.\n")

    conn = psycopg.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
        row_factory=dict_row,
    )

    # Count total
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM rag_chunks")
        total = cur.fetchone()["cnt"]
    print(f"Total chunks to re-embed: {total}")

    processed = 0
    failed = 0
    skipped = 0
    start_time = time.time()

    http_client = httpx.Client()

    # Fetch all chunks into memory (6k rows is fine)
    print("Fetching all chunks...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, chunk_type, content_text, caption, meta
            FROM rag_chunks ORDER BY id
        """)
        all_chunks = cur.fetchall()
    print(f"Fetched {len(all_chunks)} chunks.\n")

    # Prepare (id, text) pairs, skipping empty
    work = []
    for row in all_chunks:
        text = get_embed_text(row)
        if not text or not text.strip():
            skipped += 1
            continue
        work.append((row["id"], text))

    # Process in batches
    for i in range(0, len(work), BATCH_SIZE):
        batch = work[i:i + BATCH_SIZE]
        batch_ids = [w[0] for w in batch]
        batch_texts = [w[1] for w in batch]

        try:
            embeddings = embed_batch(http_client, batch_texts)
            with conn.cursor() as ucur:
                for chunk_id, emb in zip(batch_ids, embeddings):
                    ucur.execute(
                        "UPDATE rag_chunks SET embedding = %s::vector WHERE id = %s",
                        (str(emb), chunk_id),
                    )
            conn.commit()
            processed += len(batch_ids)
        except Exception as e:
            print(f"  ERROR on batch {i//BATCH_SIZE}: {e}")
            try:
                time.sleep(5)
                embeddings = embed_batch(http_client, batch_texts)
                with conn.cursor() as ucur:
                    for chunk_id, emb in zip(batch_ids, embeddings):
                        ucur.execute(
                            "UPDATE rag_chunks SET embedding = %s::vector WHERE id = %s",
                            (str(emb), chunk_id),
                        )
                conn.commit()
                processed += len(batch_ids)
            except Exception as e2:
                print(f"  RETRY FAILED: {e2}")
                failed += len(batch_ids)
                conn.rollback()

        if processed % 100 < BATCH_SIZE:
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total - processed) / rate if rate > 0 else 0
            print(f"  Progress: {processed}/{total} ({processed*100//total}%) "
                  f"| {rate:.1f} chunks/s | ETA: {eta:.0f}s")

    http_client.close()
    conn.close()

    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"Re-embedding complete in {elapsed:.1f}s")
    print(f"  Processed: {processed}")
    print(f"  Failed:    {failed}")
    print(f"  Skipped:   {skipped} (empty text)")
    print(f"  Total:     {total}")
    if failed:
        print(f"\n  WARNING: {failed} chunks have NULL embeddings!")


if __name__ == "__main__":
    main()
