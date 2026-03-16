"""
One-shot deduplication of RSS images.

Run inside the rss-ingest container:
    docker exec ammer_mmragv2_rss_ingest python /app/scripts/dedup_rss_images.py

What it does:
  1. Hashes every image file in /kb/assets/rss/ (excluding _shared/)
  2. Copies one canonical copy to rss/_shared/{sha256_16}.{ext}
  3. Updates rag_chunks.asset_path in Postgres
  4. Removes old per-article directories
"""

import hashlib
import os
import shutil
import sys

import psycopg

ASSETS_DIR = os.environ.get("ASSETS_DIR", "/kb/assets")
RSS_DIR = os.path.join(ASSETS_DIR, "rss")
SHARED_DIR = os.path.join(RSS_DIR, "_shared")

DB_HOST = os.environ.get("DATABASE_HOST", "postgres")
DB_PORT = int(os.environ.get("DATABASE_PORT", "5432"))
DB_NAME = os.environ.get("DATABASE_NAME", "rag")
DB_USER = os.environ.get("DATABASE_USER", "rag_user")
DB_PASS = os.environ.get("DATABASE_PASSWORD", "")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_rss_images():
    """Scan all image files in rss/ subdirs (excluding _shared/)."""
    results = []
    for root, dirs, files in os.walk(RSS_DIR):
        # Skip _shared
        if os.path.basename(root) == "_shared" or "/_shared/" in root:
            dirs.clear()
            continue
        for fname in files:
            if os.path.splitext(fname)[1].lower() in IMAGE_EXTS:
                results.append(os.path.join(root, fname))
    return results


def main():
    print("=== RSS Image Deduplication ===")
    print(f"Assets dir: {RSS_DIR}")

    if not os.path.isdir(RSS_DIR):
        print(f"ERROR: {RSS_DIR} does not exist")
        sys.exit(1)

    os.makedirs(SHARED_DIR, exist_ok=True)

    # Step 1: Hash all images
    print("\nStep 1: Scanning and hashing images...")
    image_files = scan_rss_images()
    print(f"Found {len(image_files)} image files")

    if not image_files:
        print("Nothing to do.")
        return

    # Build hash -> [filepaths] mapping
    hash_map = {}  # hash -> list of absolute paths
    for fpath in image_files:
        h = hash_file(fpath)
        hash_map.setdefault(h, []).append(fpath)

    unique_count = len(hash_map)
    dup_groups = sum(1 for paths in hash_map.values() if len(paths) > 1)
    dup_files = sum(len(paths) - 1 for paths in hash_map.values() if len(paths) > 1)
    print(f"Unique images: {unique_count}")
    print(f"Duplicate groups: {dup_groups}")
    print(f"Duplicate files to remove: {dup_files}")

    # Step 2: Copy canonical files and build path mapping
    print("\nStep 2: Creating canonical copies...")
    # old_asset_path -> new_asset_path
    path_updates = {}
    copied = 0

    for content_hash, filepaths in hash_map.items():
        ext = os.path.splitext(filepaths[0])[1].lower()
        short_hash = content_hash[:16]
        canonical_name = f"rss/_shared/{short_hash}{ext}"
        canonical_path = os.path.join(ASSETS_DIR, canonical_name)

        if not os.path.exists(canonical_path):
            shutil.copy2(filepaths[0], canonical_path)
            copied += 1

        for fpath in filepaths:
            old_name = os.path.relpath(fpath, ASSETS_DIR)
            if old_name != canonical_name:
                path_updates[old_name] = canonical_name

    print(f"Canonical files created: {copied}")
    print(f"Path updates needed: {len(path_updates)}")

    # Step 3: Update database
    print("\nStep 3: Updating database...")
    conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS}"
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            params = [(new, old) for old, new in path_updates.items()]
            cur.executemany(
                "UPDATE rag_chunks SET asset_path = %s WHERE asset_path = %s",
                params,
            )
            conn.commit()
            print(f"Database rows processed: {len(params)}")

            # Verify
            cur.execute(
                "SELECT COUNT(*) FROM rag_chunks "
                "WHERE asset_path LIKE 'rss/%%' "
                "AND asset_path NOT LIKE 'rss/_shared/%%' "
                "AND chunk_type = 'image'"
            )
            remaining = cur.fetchone()[0]
            print(f"Remaining chunks with old paths: {remaining}")

            if remaining > 0:
                cur.execute(
                    "SELECT DISTINCT asset_path FROM rag_chunks "
                    "WHERE asset_path LIKE 'rss/%%' "
                    "AND asset_path NOT LIKE 'rss/_shared/%%' "
                    "AND chunk_type = 'image' LIMIT 5"
                )
                print("Sample old paths still in DB:")
                for row in cur.fetchall():
                    print(f"  {row[0]}")

    # Step 4: Remove old directories
    print("\nStep 4: Cleaning up old per-article directories...")
    dirs_removed = 0
    for entry in os.listdir(RSS_DIR):
        if entry == "_shared":
            continue
        full_path = os.path.join(RSS_DIR, entry)
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
            dirs_removed += 1
    print(f"Removed {dirs_removed} old directories")

    # Step 5: Final report
    print("\nStep 5: Final stats...")
    shared_files = [f for f in os.listdir(SHARED_DIR) if os.path.isfile(os.path.join(SHARED_DIR, f))]
    print(f"Unique images in _shared/: {len(shared_files)}")

    total_bytes = sum(os.path.getsize(os.path.join(SHARED_DIR, f)) for f in shared_files)
    print(f"Total size: {total_bytes / 1024 / 1024:.1f} MB")

    print("\n=== Deduplication complete ===")


if __name__ == "__main__":
    main()
