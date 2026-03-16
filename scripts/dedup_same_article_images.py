"""
Remove within-article visual duplicate image chunks.

Many RSS articles have the same photo at different sizes (thumbnail + full).
This script keeps the largest version per visual group within each article,
deletes the duplicate chunks from the DB, and cleans up orphaned files.

Run inside the rss-ingest container:
    docker exec ammer_mmragv2_rss_ingest python /tmp/dedup_same_article_images.py
"""

import os
import sys
from collections import defaultdict
from io import BytesIO

import psycopg
from PIL import Image

ASSETS_DIR = os.environ.get("ASSETS_DIR", "/kb/assets")
SHARED_DIR = os.path.join(ASSETS_DIR, "rss", "_shared")

DB_HOST = os.environ.get("DATABASE_HOST", "postgres")
DB_PORT = int(os.environ.get("DATABASE_PORT", "5432"))
DB_NAME = os.environ.get("DATABASE_NAME", "rag")
DB_USER = os.environ.get("DATABASE_USER", "rag_user")
DB_PASS = os.environ.get("DATABASE_PASSWORD", "")

THUMB_SIZE = 16
COSINE_THRESHOLD = 0.95


def thumbnail(path: str) -> list:
    try:
        img = Image.open(path).convert("L").resize(
            (THUMB_SIZE, THUMB_SIZE), Image.LANCZOS
        )
        return list(img.getdata())
    except Exception:
        return []


def cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def main():
    print("=== Within-Article Visual Dedup ===")

    conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS}"

    # Step 1: Get all RSS image chunks grouped by doc_id
    print("Step 1: Loading image chunks...")
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, doc_id, asset_path
                FROM rag_chunks
                WHERE chunk_type = 'image'
                  AND asset_path IS NOT NULL
                  AND meta->>'source' = 'rss_image'
                ORDER BY doc_id, id
            """)
            all_chunks = [
                {"id": r[0], "doc_id": str(r[1]), "asset_path": r[2]}
                for r in cur.fetchall()
            ]

    by_doc = defaultdict(list)
    for c in all_chunks:
        by_doc[c["doc_id"]].append(c)

    multi_image_docs = {k: v for k, v in by_doc.items() if len(v) > 1}
    print(f"Total image chunks: {len(all_chunks)}")
    print(f"Articles with multiple images: {len(multi_image_docs)}")

    # Step 2: For each article, find visual duplicates
    print("\nStep 2: Finding within-article duplicates...")
    chunks_to_delete = []

    for doc_id, chunks in multi_image_docs.items():
        # Load thumbnails for each chunk's image
        chunk_thumbs = []
        for c in chunks:
            fpath = os.path.join(ASSETS_DIR, c["asset_path"])
            t = thumbnail(fpath) if os.path.exists(fpath) else []
            fsize = os.path.getsize(fpath) if os.path.exists(fpath) else 0
            chunk_thumbs.append((c, t, fsize))

        # Group visually similar images
        groups = []  # list of lists of (chunk, thumb, size)
        for item in chunk_thumbs:
            c, t, sz = item
            if not t:
                continue
            placed = False
            for group in groups:
                rep_thumb = group[0][1]
                if rep_thumb and cosine(t, rep_thumb) >= COSINE_THRESHOLD:
                    group.append(item)
                    placed = True
                    break
            if not placed:
                groups.append([item])

        # For each group with >1 members, keep the largest, delete the rest
        for group in groups:
            if len(group) <= 1:
                continue
            group.sort(key=lambda x: x[2], reverse=True)  # largest first
            for c, _, _ in group[1:]:
                chunks_to_delete.append(c["id"])

    print(f"Duplicate chunks to delete: {len(chunks_to_delete)}")

    if not chunks_to_delete:
        print("No duplicates found!")
        return

    # Step 3: Delete duplicate chunks from DB
    print(f"\nStep 3: Deleting {len(chunks_to_delete)} chunks from DB...")
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            # Delete in batches
            for i in range(0, len(chunks_to_delete), 500):
                batch = chunks_to_delete[i:i + 500]
                cur.execute(
                    "DELETE FROM rag_chunks WHERE id = ANY(%s)",
                    (batch,),
                )
            conn.commit()

            # Check remaining
            cur.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE chunk_type='image'"
            )
            remaining_chunks = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(DISTINCT asset_path) FROM rag_chunks "
                "WHERE chunk_type='image' AND asset_path IS NOT NULL"
            )
            unique_paths = cur.fetchone()[0]

    print(f"Remaining image chunks: {remaining_chunks}")
    print(f"Unique asset paths: {unique_paths}")

    # Step 4: Clean up orphaned files
    print("\nStep 4: Cleaning orphaned files...")
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT asset_path FROM rag_chunks "
                "WHERE chunk_type='image' AND asset_path LIKE 'rss/_shared/%%'"
            )
            referenced = {r[0] for r in cur.fetchall()}

    on_disk = {f"rss/_shared/{f}" for f in os.listdir(SHARED_DIR)
               if os.path.isfile(os.path.join(SHARED_DIR, f))}

    orphans = on_disk - referenced
    for p in orphans:
        try:
            os.remove(os.path.join(ASSETS_DIR, p))
        except OSError:
            pass
    print(f"Removed {len(orphans)} orphan files")

    final_files = len([f for f in os.listdir(SHARED_DIR)
                       if os.path.isfile(os.path.join(SHARED_DIR, f))])
    print(f"\nFinal state:")
    print(f"  Image chunks in DB: {remaining_chunks}")
    print(f"  Unique files on disk: {final_files}")
    print("=== Done ===")


if __name__ == "__main__":
    main()
