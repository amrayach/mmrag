"""
Visual deduplication using thumbnail comparison.

Resizes all images to a small grayscale thumbnail and compares
normalized pixel distances. Handles different resolutions/crops
of the same image.

Run inside the rss-ingest container:
    docker exec ammer_mmragv2_rss_ingest python /tmp/dedup_rss_visual.py
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

THUMB_SIZE = 16  # 16x16 grayscale thumbnail
SIMILARITY_THRESHOLD = 0.92  # Cosine similarity; 0.92+ = same image


def thumbnail_vector(image_path: str) -> list[float] | None:
    """Convert image to a normalized 16x16 grayscale vector."""
    try:
        img = Image.open(image_path).convert("L").resize(
            (THUMB_SIZE, THUMB_SIZE), Image.LANCZOS
        )
        pixels = list(img.getdata())
        # Normalize to unit vector
        norm = sum(p * p for p in pixels) ** 0.5
        if norm == 0:
            return None
        return [p / norm for p in pixels]
    except Exception as e:
        print(f"  WARNING: Cannot process {os.path.basename(image_path)}: {e}")
        return None


def cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two unit vectors (already normalized)."""
    return sum(x * y for x, y in zip(a, b))


def find_duplicate_groups(files: list[str]) -> list[list[str]]:
    """Find groups of visually similar images."""
    # Compute thumbnail vectors
    vectors = {}
    for i, f in enumerate(files):
        if i % 200 == 0:
            print(f"  Hashing {i}/{len(files)}...")
        v = thumbnail_vector(f)
        if v is not None:
            vectors[f] = v

    print(f"  Computed vectors for {len(vectors)} images")

    # Union-Find
    parent = {f: f for f in vectors}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Pairwise comparison
    items = list(vectors.items())
    n = len(items)
    print(f"  Comparing {n * (n - 1) // 2} pairs...")
    matches = 0
    for i in range(n):
        for j in range(i + 1, n):
            sim = cosine_sim(items[i][1], items[j][1])
            if sim >= SIMILARITY_THRESHOLD:
                union(items[i][0], items[j][0])
                matches += 1

    print(f"  Found {matches} matching pairs")

    # Collect groups
    groups = defaultdict(list)
    for f in vectors:
        groups[find(f)].append(f)

    return [g for g in groups.values() if len(g) > 1]


def main():
    print("=== Visual Deduplication (thumbnail comparison) ===")

    if not os.path.isdir(SHARED_DIR):
        print(f"ERROR: {SHARED_DIR} not found")
        sys.exit(1)

    files = sorted(
        os.path.join(SHARED_DIR, f)
        for f in os.listdir(SHARED_DIR)
        if os.path.isfile(os.path.join(SHARED_DIR, f))
    )
    print(f"Total files: {len(files)}")

    # Step 1: Find duplicate groups
    print("\nStep 1: Finding visual duplicates...")
    dup_groups = find_duplicate_groups(files)

    total_dups = sum(len(g) - 1 for g in dup_groups)
    print(f"\nDuplicate groups: {len(dup_groups)}")
    print(f"Files to remove: {total_dups}")

    if not dup_groups:
        print("No visual duplicates found.")
        return

    # Show examples
    print("\nSample groups (keeping largest):")
    for g in dup_groups[:8]:
        items = [(os.path.basename(f), os.path.getsize(f)) for f in g]
        items.sort(key=lambda x: x[1], reverse=True)
        print(f"  KEEP {items[0][0]} ({items[0][1]}B) | DROP: {', '.join(f'{n} ({s}B)' for n, s in items[1:])}")

    # Step 2: Build remap (keep largest file in each group)
    print("\nStep 2: Building remap...")
    remap = {}  # old_asset_path -> keeper_asset_path
    files_to_delete = []

    for group in dup_groups:
        group.sort(key=lambda f: os.path.getsize(f), reverse=True)
        keeper = group[0]
        keeper_name = f"rss/_shared/{os.path.basename(keeper)}"
        for dup in group[1:]:
            dup_name = f"rss/_shared/{os.path.basename(dup)}"
            remap[dup_name] = keeper_name
            files_to_delete.append(dup)

    # Step 3: Update database
    print(f"\nStep 3: Updating {len(remap)} database references...")
    conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS}"
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            params = [(new, old) for old, new in remap.items()]
            cur.executemany(
                "UPDATE rag_chunks SET asset_path = %s WHERE asset_path = %s",
                params,
            )
            conn.commit()

            cur.execute(
                "SELECT COUNT(DISTINCT asset_path) FROM rag_chunks "
                "WHERE chunk_type='image' AND asset_path LIKE 'rss/%%'"
            )
            unique_paths = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE chunk_type='image'"
            )
            total_chunks = cur.fetchone()[0]
            print(f"DB: {total_chunks} image chunks -> {unique_paths} unique asset paths")

    # Step 4: Delete files
    print(f"\nStep 4: Removing {len(files_to_delete)} duplicate files...")
    for f in files_to_delete:
        try:
            os.remove(f)
        except OSError:
            pass

    remaining = len([f for f in os.listdir(SHARED_DIR) if os.path.isfile(os.path.join(SHARED_DIR, f))])
    print(f"Files remaining in _shared/: {remaining}")
    print("\n=== Visual deduplication complete ===")


if __name__ == "__main__":
    main()
