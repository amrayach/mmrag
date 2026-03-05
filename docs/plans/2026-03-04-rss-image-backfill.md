# RSS Image Backfill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix missing RSS images in search results by adding an image backfill endpoint and triggering re-processing of 909 existing articles.

**Architecture:** The RSS ingest service already has `CAPTION_IMAGES=true` and all feed configs include `img_selector`, but all 909 articles were ingested before captioning was enabled. The dedup check (`should_process`) compares text hashes and skips re-ingestion. We add a dedicated `/ingest/backfill-images` endpoint that efficiently adds image chunks to existing text-only articles without re-processing text. We also add `CAPTION_IMAGES` to `.env.example` for documentation.

**Tech Stack:** Python/FastAPI (rss-ingest service), PostgreSQL (pgvector), Ollama (qwen2.5vl:7b for captioning, nomic-embed-text for embedding)

**Root Cause Summary:**
- `CAPTION_IMAGES=true` is set in docker-compose.yml and confirmed inside the container
- `qwen2.5vl:7b` vision model is available in Ollama
- All 14 feed configs have `img_selector` configured
- **BUT:** All 909 RSS docs (3,898 text chunks) were ingested before captioning was enabled
- `should_process()` skips them because text hash is unchanged
- Result: 0 RSS image chunks, no `data/assets/rss/` directory

**DB state:**
- `chunk_type=text, content_type=rss_article`: 3,898 chunks (909 docs)
- `chunk_type=image, content_type=rss_article`: 0 chunks
- `chunk_type=image, content_type=null (PDF)`: 22 chunks

---

### Task 1: Add CAPTION_IMAGES to .env.example

**Files:**
- Modify: `.env.example:27` (after SPOOF_USER_AGENT line)

**Step 1: Add the env var documentation**

Add after the `SPOOF_USER_AGENT` line in `.env.example`:

```
# Enable RSS image captioning via vision model (qwen2.5vl:7b).
# Causes model swap thrash with OLLAMA_MAX_LOADED_MODELS=1 — slow but needed for multimodal.
CAPTION_IMAGES=true
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add CAPTION_IMAGES to .env.example"
```

---

### Task 2: Add backfill-images endpoint to rss-ingest

**Files:**
- Modify: `services/rss-ingest/app/db.py` — add `get_docs_missing_images()` query
- Modify: `services/rss-ingest/app/ingest.py` — add `backfill_images()` function
- Modify: `services/rss-ingest/app/main.py` — add `/ingest/backfill-images` endpoint

**Step 1: Add DB query to find articles without image chunks**

In `services/rss-ingest/app/db.py`, add after the `should_process` function:

```python
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
```

**Step 2: Add backfill function in ingest.py**

In `services/rss-ingest/app/ingest.py`, add after the `ingest_article` function:

```python
def backfill_images_for_doc(pool, doc_id, url: str, lang: str = "de") -> dict:
    """
    Add image chunks to an existing RSS article that was ingested text-only.
    Does NOT re-process text — only fetches images, captions, embeds, and inserts.
    """
    from app.feeds import FEEDS

    # Find matching feed config by URL
    feed_config = None
    for fc in FEEDS.values():
        # Match by domain
        feed_domain = urllib.parse.urlparse(fc.feed_url).netloc.replace("www.", "")
        url_domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        if feed_domain == url_domain:
            feed_config = fc
            break

    if not feed_config or not feed_config.img_selector:
        return {"status": "skipped", "reason": "no feed config or img_selector"}

    # Fetch the article page
    page = fetch_article(url, feed_config)
    if page is None:
        return {"status": "skipped", "reason": "fetch failed"}

    # Extract image URLs
    _, image_urls = extract_article_content(
        page, feed_config, fallback_summary="", content_encoded=""
    )

    if not image_urls:
        return {"status": "skipped", "reason": "no images found"}

    # Get article title from existing text chunks
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT meta->>'title' FROM rag_chunks WHERE doc_id=%s AND chunk_type='text' LIMIT 1",
                (doc_id,),
            )
            row = cur.fetchone()
            title = row[0] if row else ""

            rss_assets_dir = os.path.join(ASSETS_DIR, "rss", str(doc_id)[:8])
            os.makedirs(rss_assets_dir, exist_ok=True)
            written_assets = []
            image_count = 0

            try:
                for im_i, img_url in enumerate(image_urls[:MAX_IMAGES_PER_ARTICLE]):
                    try:
                        img_resp = requests.get(img_url, timeout=30)
                        if img_resp.status_code != 200:
                            continue
                        img_bytes = img_resp.content

                        clean_path = urllib.parse.urlparse(img_url).path
                        ext = clean_path.rsplit(".", 1)[-1][:4] if "." in clean_path else "jpg"
                        asset_name = f"rss/{str(doc_id)[:8]}/{im_i}.{ext}"
                        asset_path = os.path.join(ASSETS_DIR, asset_name)
                        with open(asset_path, "wb") as f:
                            f.write(img_bytes)
                        written_assets.append(asset_path)

                        caption = _retry(lambda ib=img_bytes, la=lang: ollama_caption_image(ib, la))
                        emb = _retry(lambda c=caption: ollama_embeddings(c)) if caption else None

                        meta = {
                            "source": "rss_image",
                            "content_type": "rss_article",
                            "feed_name": feed_config.name,
                            "title": title,
                            "url": url,
                            "image_index": im_i,
                        }
                        insert_chunk(cur, doc_id, "image", 1, None, caption, asset_name, emb, meta)
                        image_count += 1
                    except Exception as e:
                        logger.warning("Backfill image %s failed: %s", img_url, e)

                conn.commit()
                logger.info("Backfill: %s — %d images added", title[:60], image_count)

            except Exception:
                conn.rollback()
                for path in written_assets:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                logger.warning("Backfill failed for %s, rolled back", url)
                raise

    return {"status": "ok", "images_added": image_count}
```

Also add the import for `fetch_article` and `extract_article_content` — these are already imported at the top of `ingest.py` via `from app.scraper import ...`.

**Step 3: Add the API endpoint in main.py**

In `services/rss-ingest/app/main.py`, add after the `ingest_feeds` endpoint:

```python
@app.post("/ingest/backfill-images")
def backfill_images(limit: int = 50, lang: str = "de"):
    """Add image chunks to RSS articles that were ingested without images."""
    from app.db import get_docs_missing_images
    from app.ingest import backfill_images_for_doc

    with ingestion_lock():
        with app.state.pool.connection() as conn:
            with conn.cursor() as cur:
                docs = get_docs_missing_images(cur, limit=limit)

        results = {"total_candidates": len(docs), "processed": 0, "images_added": 0, "skipped": 0}
        for doc in docs:
            try:
                r = backfill_images_for_doc(app.state.pool, doc["doc_id"], doc["url"], lang)
                if r.get("status") == "ok":
                    results["processed"] += 1
                    results["images_added"] += r.get("images_added", 0)
                else:
                    results["skipped"] += 1
            except Exception as e:
                logger.warning("Backfill error for %s: %s", doc["url"], e)
                results["skipped"] += 1

    return results
```

**Step 4: Commit**

```bash
git add services/rss-ingest/app/db.py services/rss-ingest/app/ingest.py services/rss-ingest/app/main.py
git commit -m "feat(rss-ingest): add /ingest/backfill-images endpoint for text-only articles"
```

---

### Task 3: Rebuild and deploy rss-ingest container

**Step 1: Rebuild the image**

```bash
cd /srv/projects/ammer/mmrag-n8n-demo-v2
docker compose build rss-ingest
```

**Step 2: Restart the service (ask user first!)**

```bash
docker compose up -d rss-ingest
```

**Step 3: Verify container is running**

```bash
docker compose logs rss-ingest --tail 10
```

Expected: startup logs showing "rss-ingest starting"

---

### Task 4: Trigger backfill and verify results

**Step 1: Run a small test backfill (5 articles)**

```bash
curl -s -X POST "http://127.0.0.1:56156/ingest/backfill-images?limit=5&lang=de" | python3 -m json.tool
```

Wait — rss-ingest has no host port! It's internal only. Use docker exec:

```bash
docker exec ammer_mmragv2_rss_ingest curl -s -X POST "http://localhost:8002/ingest/backfill-images?limit=5&lang=de"
```

Expected: JSON with `images_added > 0`

**Step 2: Verify image chunks in database**

```sql
SELECT chunk_type, meta->>'content_type', COUNT(*)
FROM rag_chunks
WHERE chunk_type = 'image' AND meta->>'content_type' = 'rss_article'
GROUP BY chunk_type, meta->>'content_type';
```

Expected: at least a few rows

**Step 3: Verify assets on disk**

```bash
ls -la data/assets/rss/
```

Expected: subdirectories with image files

**Step 4: Test via chat query**

Ask a question about a recently ingested RSS article and verify the response includes `![caption](url)` image references.

**Step 5: If working, run full backfill**

```bash
docker exec ammer_mmragv2_rss_ingest curl -s -X POST "http://localhost:8002/ingest/backfill-images?limit=0&lang=de"
```

Note: `limit=0` means unlimited. This will take a long time (~909 docs, each requiring page fetch + vision model calls). Consider running with `limit=50` batches.

**Step 6: Commit any remaining changes**

```bash
git add -A
git commit -m "feat: RSS image backfill complete"
```

---

### Performance Notes

- Each image backfill requires: HTTP fetch of article page + image download + Ollama vision model call (qwen2.5vl:7b) + Ollama embedding call (nomic-embed-text)
- With `OLLAMA_MAX_LOADED_MODELS=1`, model swapping between vision and embed adds ~10-30s per article
- For 909 articles at ~3 images each, expect several hours for full backfill
- Run in batches of 50 to avoid long-running requests timing out
- Future ingestion runs will automatically include images since `CAPTION_IMAGES=true` is already set
