"""
Recovery script: re-download RSS images to fix broken asset_path references.

Only re-downloads files and fixes DB paths — does NOT re-caption or re-embed.
Uses content-hash dedup to avoid storing duplicates.

Run inside the rss-ingest container:
    docker exec ammer_mmragv2_rss_ingest python /tmp/recover_rss_images.py
"""

import hashlib
import os
import sys
import time
import urllib.parse
from collections import defaultdict

import psycopg
import requests

# Re-use the app's scraper for article fetching
sys.path.insert(0, "/app")
from app.feeds import FEEDS, FeedConfig
from app.scraper import (
    MIN_IMAGE_BYTES, _is_junk_image_url, extract_article_content,
    fetch_article,
)

ASSETS_DIR = os.environ.get("ASSETS_DIR", "/kb/assets")
SHARED_DIR = os.path.join(ASSETS_DIR, "rss", "_shared")
MAX_IMAGES = int(os.environ.get("MAX_IMAGES_PER_ARTICLE", "3"))

DB_HOST = os.environ.get("DATABASE_HOST", "postgres")
DB_PORT = int(os.environ.get("DATABASE_PORT", "5432"))
DB_NAME = os.environ.get("DATABASE_NAME", "rag")
DB_USER = os.environ.get("DATABASE_USER", "rag_user")
DB_PASS = os.environ.get("DATABASE_PASSWORD", "")


def save_deduped(img_bytes: bytes, ext: str) -> str:
    """Save image with content-hash dedup. Returns relative asset name."""
    content_hash = hashlib.sha256(img_bytes).hexdigest()[:16]
    asset_name = f"rss/_shared/{content_hash}.{ext}"
    asset_path = os.path.join(ASSETS_DIR, asset_name)
    if not os.path.exists(asset_path):
        os.makedirs(os.path.dirname(asset_path), exist_ok=True)
        with open(asset_path, "wb") as f:
            f.write(img_bytes)
    return asset_name


def find_feed_config(article_url: str) -> FeedConfig | None:
    """Match an article URL to its feed config."""
    url_domain = urllib.parse.urlparse(article_url).netloc.replace("www.", "")
    for fc in FEEDS.values():
        feed_domain = urllib.parse.urlparse(fc.feed_url).netloc.replace("www.", "")
        if feed_domain == url_domain:
            return fc
    return None


def main():
    print("=== RSS Image Recovery ===")
    os.makedirs(SHARED_DIR, exist_ok=True)

    conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS}"

    # Step 1: Get all RSS image chunks grouped by article URL
    print("Step 1: Loading image chunks from DB...")
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, doc_id, asset_path, meta
                FROM rag_chunks
                WHERE chunk_type = 'image'
                  AND meta->>'source' = 'rss_image'
                ORDER BY doc_id, (meta->>'image_index')::int
            """)
            all_chunks = []
            for row in cur.fetchall():
                all_chunks.append({
                    "id": row[0],
                    "doc_id": row[1],
                    "asset_path": row[2],
                    "meta": row[3] if isinstance(row[3], dict) else {},
                })

    print(f"Total RSS image chunks: {len(all_chunks)}")

    # Group by article URL
    by_url = defaultdict(list)
    for c in all_chunks:
        url = c["meta"].get("url", "")
        if url:
            by_url[url].append(c)

    print(f"Unique article URLs: {len(by_url)}")

    # Step 2: Force re-download ALL articles to fix incorrect mappings
    # (visual dedup pointed many chunks to wrong files)
    broken_urls = by_url
    print(f"Articles to re-fetch: {len(broken_urls)}")

    # Step 3: Re-fetch articles and re-download images
    print(f"\nStep 3: Re-downloading images for {len(broken_urls)} articles...")
    recovered = 0
    failed_articles = 0
    updates = []  # (new_asset_path, chunk_id)

    for i, (url, chunks) in enumerate(broken_urls.items()):
        if i % 50 == 0:
            print(f"  Processing {i}/{len(broken_urls)}...")

        fc = find_feed_config(url)
        if not fc:
            failed_articles += 1
            continue

        try:
            page = fetch_article(url, fc)
            if page is None:
                failed_articles += 1
                continue

            _, image_urls = extract_article_content(
                page, fc, fallback_summary="", content_encoded=""
            )
            if not image_urls:
                failed_articles += 1
                continue

            # Match chunks to images by image_index
            for chunk in chunks:
                im_idx = chunk["meta"].get("image_index", 0)
                if im_idx >= len(image_urls) or im_idx >= MAX_IMAGES:
                    continue

                img_url = image_urls[im_idx]
                try:
                    resp = requests.get(img_url, timeout=30)
                    if resp.status_code != 200:
                        continue
                    img_bytes = resp.content
                    if len(img_bytes) < MIN_IMAGE_BYTES:
                        continue

                    clean_path = urllib.parse.urlparse(img_url).path
                    ext = clean_path.rsplit(".", 1)[-1][:4] if "." in clean_path else "jpg"
                    asset_name = save_deduped(img_bytes, ext)
                    updates.append((asset_name, chunk["id"]))
                    recovered += 1
                except Exception:
                    pass

            # Be polite
            time.sleep(0.5)

        except Exception as e:
            failed_articles += 1

    print(f"\nRecovered: {recovered}")
    print(f"Failed articles: {failed_articles}")

    # Step 4: Update database
    if updates:
        print(f"\nStep 4: Updating {len(updates)} chunk paths in DB...")
        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE rag_chunks SET asset_path = %s WHERE id = %s",
                    updates,
                )
                conn.commit()
                print("Database updated.")

                cur.execute(
                    "SELECT COUNT(DISTINCT asset_path) FROM rag_chunks "
                    "WHERE chunk_type='image' AND asset_path LIKE 'rss/%%'"
                )
                print(f"Unique asset paths: {cur.fetchone()[0]}")

    # Step 5: Clean up files not referenced by any chunk
    print("\nStep 5: Cleaning orphan files...")
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT asset_path FROM rag_chunks "
                "WHERE chunk_type='image' AND asset_path LIKE 'rss/_shared/%%'"
            )
            referenced = {row[0] for row in cur.fetchall()}

    on_disk = set()
    for f in os.listdir(SHARED_DIR):
        on_disk.add(f"rss/_shared/{f}")

    orphans = on_disk - referenced
    for orphan_path in orphans:
        full = os.path.join(ASSETS_DIR, orphan_path)
        try:
            os.remove(full)
        except OSError:
            pass
    print(f"Removed {len(orphans)} orphan files")

    final_count = len([f for f in os.listdir(SHARED_DIR) if os.path.isfile(os.path.join(SHARED_DIR, f))])
    print(f"\nFinal unique files on disk: {final_count}")
    print("=== Recovery complete ===")


if __name__ == "__main__":
    main()
