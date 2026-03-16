"""
Perceptual deduplication of RSS images using dhash (difference hash).

Images that look the same but differ in encoding/metadata/compression
will have matching dhashes. Groups near-duplicates, keeps one canonical
copy, updates rag_chunks, and removes the rest.

Run inside the rss-ingest container:
    docker exec ammer_mmragv2_rss_ingest python /tmp/dedup_rss_perceptual.py
"""

import os
import sys
from collections import defaultdict

import psycopg
from PIL import Image

ASSETS_DIR = os.environ.get("ASSETS_DIR", "/kb/assets")
SHARED_DIR = os.path.join(ASSETS_DIR, "rss", "_shared")

DB_HOST = os.environ.get("DATABASE_HOST", "postgres")
DB_PORT = int(os.environ.get("DATABASE_PORT", "5432"))
DB_NAME = os.environ.get("DATABASE_NAME", "rag")
DB_USER = os.environ.get("DATABASE_USER", "rag_user")
DB_PASS = os.environ.get("DATABASE_PASSWORD", "")

# dhash size — 8x9 produces a 64-bit hash; hamming distance <= 4 = same image
HASH_SIZE = 8
HAMMING_THRESHOLD = 4


def dhash(image_path: str) -> int | None:
    """Compute difference hash (dhash) for an image file."""
    try:
        img = Image.open(image_path).convert("L").resize(
            (HASH_SIZE + 1, HASH_SIZE), Image.LANCZOS
        )
        pixels = list(img.getdata())
        w = HASH_SIZE + 1
        bits = 0
        for row in range(HASH_SIZE):
            for col in range(HASH_SIZE):
                idx = row * w + col
                if pixels[idx] < pixels[idx + 1]:
                    bits |= 1 << (row * HASH_SIZE + col)
        return bits
    except Exception as e:
        print(f"  WARNING: Cannot hash {image_path}: {e}")
        return None


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def group_by_perceptual_hash(files: list[str]) -> list[list[str]]:
    """Group files that are perceptual duplicates (hamming distance <= threshold)."""
    hashes = {}
    for f in files:
        h = dhash(f)
        if h is not None:
            hashes[f] = h

    # Union-Find for grouping
    parent = {f: f for f in hashes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Compare all pairs — for ~1700 files, ~1.5M comparisons, fast with int ops
    items = list(hashes.items())
    n = len(items)
    print(f"  Computing pairwise hamming distances for {n} images...")
    for i in range(n):
        for j in range(i + 1, n):
            if hamming(items[i][1], items[j][1]) <= HAMMING_THRESHOLD:
                union(items[i][0], items[j][0])

    # Collect groups
    groups = defaultdict(list)
    for f in hashes:
        groups[find(f)].append(f)

    # Only return groups with duplicates
    return [g for g in groups.values() if len(g) > 1]


def main():
    print("=== Perceptual Deduplication ===")

    if not os.path.isdir(SHARED_DIR):
        print(f"ERROR: {SHARED_DIR} not found")
        sys.exit(1)

    # Collect all image files
    files = []
    for fname in os.listdir(SHARED_DIR):
        fpath = os.path.join(SHARED_DIR, fname)
        if os.path.isfile(fpath):
            files.append(fpath)
    print(f"Total files in _shared/: {len(files)}")

    # Find perceptual duplicate groups
    print("\nStep 1: Computing perceptual hashes...")
    dup_groups = group_by_perceptual_hash(files)

    total_dups = sum(len(g) - 1 for g in dup_groups)
    print(f"\nPerceptual duplicate groups: {len(dup_groups)}")
    print(f"Files to remove: {total_dups}")

    if not dup_groups:
        print("No perceptual duplicates found.")
        return

    # Show a few examples
    print("\nSample groups:")
    for g in dup_groups[:5]:
        sizes = [os.path.getsize(f) for f in g]
        names = [os.path.basename(f) for f in g]
        print(f"  {names} (sizes: {sizes})")

    # Step 2: For each group, keep the largest file, remap the rest
    print("\nStep 2: Building remap table...")
    remap = {}  # old_asset_path -> new_asset_path
    files_to_delete = []

    for group in dup_groups:
        # Keep the largest file (highest quality)
        group.sort(key=lambda f: os.path.getsize(f), reverse=True)
        keeper = group[0]
        keeper_name = f"rss/_shared/{os.path.basename(keeper)}"
        for dup in group[1:]:
            dup_name = f"rss/_shared/{os.path.basename(dup)}"
            remap[dup_name] = keeper_name
            files_to_delete.append(dup)

    print(f"Remaps: {len(remap)}")

    # Step 3: Update database
    print("\nStep 3: Updating database...")
    conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS}"
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            params = [(new, old) for old, new in remap.items()]
            cur.executemany(
                "UPDATE rag_chunks SET asset_path = %s WHERE asset_path = %s",
                params,
            )
            conn.commit()
            print(f"Database rows processed: {len(params)}")

            # Verify
            cur.execute(
                "SELECT COUNT(DISTINCT asset_path) FROM rag_chunks "
                "WHERE chunk_type='image' AND asset_path LIKE 'rss/%%'"
            )
            print(f"Unique asset paths in DB: {cur.fetchone()[0]}")

    # Step 4: Delete duplicate files
    print("\nStep 4: Removing duplicate files...")
    removed = 0
    for fpath in files_to_delete:
        try:
            os.remove(fpath)
            removed += 1
        except OSError as e:
            print(f"  WARNING: Could not remove {fpath}: {e}")
    print(f"Removed {removed} files")

    # Final stats
    remaining = len([f for f in os.listdir(SHARED_DIR) if os.path.isfile(os.path.join(SHARED_DIR, f))])
    print(f"\nFinal unique images: {remaining}")
    print("=== Perceptual deduplication complete ===")


if __name__ == "__main__":
    main()
