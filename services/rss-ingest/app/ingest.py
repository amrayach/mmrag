import hashlib
import logging
import os
import time as _time
import urllib.parse
from typing import Any, Dict, Optional

import requests

from app.config import (
    ASSETS_DIR, CAPTION_IMAGES, CHUNK_CHARS, CHUNK_OVERLAP,
    FEED_DELAY_SECS, FETCH_DELAY_SECS, MAX_ARTICLES_PER_FEED,
    MAX_ARTICLES_PER_RUN, MAX_IMAGES_PER_ARTICLE, RSS_FEEDS_ENABLED,
)
from app.db import (
    delete_doc_chunks, get_rss_doc_id, insert_chunk,
    should_process, upsert_doc,
)
from app.feeds import FeedConfig, get_enabled_feeds
from app.ollama import (
    _retry, ollama_caption_image, ollama_caption_image_contextual,
    ollama_embeddings, enriched_image_embedding_text,
)
from app.scraper import (
    MIN_IMAGE_BYTES, extract_article_content, fetch_article, parse_feed,
    sha256_text,
)
from app.text import split_text

logger = logging.getLogger("rss-ingest")

# ---------------------------------------------------------------------------
# Image dedup helpers
# ---------------------------------------------------------------------------
_THUMB_SIZE = 16
_VISUAL_THRESHOLD = 0.95

# Global thumbnail cache: asset_name -> flat pixel list.
# Populated lazily on first call to _save_deduped_image.
_global_thumb_cache: dict = {}
_cache_loaded = False


def _thumb_from_bytes(img_bytes: bytes) -> list:
    """Return a small grayscale thumbnail as a flat pixel list, or [] on error."""
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(img_bytes)).convert("L").resize(
            (_THUMB_SIZE, _THUMB_SIZE), Image.LANCZOS,
        )
        return list(img.getdata())
    except Exception:
        return []


def _thumb_from_file(path: str) -> list:
    """Return thumbnail from an on-disk image file."""
    try:
        from PIL import Image
        img = Image.open(path).convert("L").resize(
            (_THUMB_SIZE, _THUMB_SIZE), Image.LANCZOS,
        )
        return list(img.getdata())
    except Exception:
        return []


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _load_thumb_cache():
    """Scan all existing images in _shared/ and build the thumbnail cache."""
    global _cache_loaded
    shared_dir = os.path.join(ASSETS_DIR, "rss", "_shared")
    if not os.path.isdir(shared_dir):
        _cache_loaded = True
        return
    count = 0
    for fname in os.listdir(shared_dir):
        fpath = os.path.join(shared_dir, fname)
        if not os.path.isfile(fpath):
            continue
        asset_name = f"rss/_shared/{fname}"
        if asset_name not in _global_thumb_cache:
            t = _thumb_from_file(fpath)
            if t:
                _global_thumb_cache[asset_name] = t
                count += 1
    _cache_loaded = True
    logger.info("Global thumb cache loaded: %d images", count)


def _find_visual_match(thumb: list) -> str | None:
    """Return asset_name of a visually matching image, or None."""
    for asset_name, cached_thumb in _global_thumb_cache.items():
        if _cosine(thumb, cached_thumb) >= _VISUAL_THRESHOLD:
            return asset_name
    return None


def _save_deduped_image(img_bytes: bytes, ext: str) -> str:
    """Save image to shared dedup directory, returning relative asset_name.

    Dedup layers:
      1. SHA-256 content hash — exact byte match
      2. Global visual similarity — catches CDN resize variants
    """
    global _cache_loaded

    # Lazy-load the thumbnail cache on first call
    if not _cache_loaded:
        _load_thumb_cache()

    # Layer 1: exact content hash
    content_hash = hashlib.sha256(img_bytes).hexdigest()[:16]
    asset_name = f"rss/_shared/{content_hash}.{ext}"
    asset_path = os.path.join(ASSETS_DIR, asset_name)

    if os.path.exists(asset_path):
        logger.debug("Reusing exact-match image: %s", asset_name)
        return asset_name

    # Layer 2: visual similarity against all known images
    thumb = _thumb_from_bytes(img_bytes)
    if thumb:
        match = _find_visual_match(thumb)
        if match:
            logger.debug("Reusing visually-matched image: %s (new was %s)", match, asset_name)
            return match

    # No match — save new file and register in cache
    os.makedirs(os.path.dirname(asset_path), exist_ok=True)
    with open(asset_path, "wb") as f:
        f.write(img_bytes)
    if thumb:
        _global_thumb_cache[asset_name] = thumb
    logger.debug("Saved new image: %s", asset_name)
    return asset_name


def _is_visual_dup(img_bytes: bytes, seen_thumbs: list, threshold: float = 0.95) -> bool:
    """Check if img_bytes is a visual duplicate of any image in seen_thumbs.

    Uses cosine similarity of 16x16 grayscale thumbnails.  Only used to compare
    images within the SAME article (max 3), so the cost is negligible.
    """
    thumb = _thumb_from_bytes(img_bytes)
    if not thumb:
        return False
    for prev in seen_thumbs:
        if _cosine(thumb, prev) >= threshold:
            return True
    seen_thumbs.append(thumb)
    return False


def ingest_all_feeds(
    pool, lang: str = "de", max_articles: Optional[int] = None,
) -> Dict[str, Any]:
    """Iterate enabled feeds, ingest articles, respect global cap."""
    feeds = get_enabled_feeds(RSS_FEEDS_ENABLED)
    cap = max_articles or MAX_ARTICLES_PER_RUN
    total_ingested = 0
    total_skipped = 0
    total_errors = 0
    total_chunks = 0
    feed_results = []

    t0 = _time.monotonic()

    for i, feed_config in enumerate(feeds):
        if total_ingested >= cap:
            logger.info("Global article cap (%d) reached, stopping", cap)
            break

        remaining = cap - total_ingested
        per_feed_max = min(MAX_ARTICLES_PER_FEED, remaining)

        feed_stats = ingest_single_feed(pool, feed_config, lang, per_feed_max)
        total_ingested += feed_stats["ingested"]
        total_skipped += feed_stats["skipped"]
        total_errors += feed_stats["errors"]
        total_chunks += feed_stats["chunks"]
        feed_results.append({"feed": feed_config.name, **feed_stats})

        if i < len(feeds) - 1:
            _time.sleep(FEED_DELAY_SECS)

    elapsed = _time.monotonic() - t0
    logger.info(
        "Ingestion run complete: %d ingested, %d skipped, %d errors, %d chunks in %.1fs",
        total_ingested, total_skipped, total_errors, total_chunks, elapsed,
    )

    return {
        "feeds_processed": len(feed_results),
        "articles_ingested": total_ingested,
        "articles_skipped": total_skipped,
        "articles_errored": total_errors,
        "total_chunks": total_chunks,
        "elapsed_secs": round(elapsed, 1),
        "feeds": feed_results,
    }


def ingest_single_feed(
    pool, feed_config: FeedConfig, lang: str, max_articles: int,
) -> Dict[str, Any]:
    """Parse one feed and ingest up to max_articles new articles."""
    logger.info("Processing feed: %s (%s)", feed_config.name, feed_config.feed_url)
    entries = parse_feed(feed_config)
    logger.info("Feed %s: %d entries found", feed_config.name, len(entries))

    ingested = 0
    skipped = 0
    errors = 0
    chunks = 0

    for entry in entries[:MAX_ARTICLES_PER_FEED]:
        if ingested >= max_articles:
            break
        try:
            result = ingest_article(pool, entry, feed_config, lang)
            if result == "ingested":
                ingested += 1
            elif result == "skipped":
                skipped += 1
            if isinstance(result, dict):
                chunks += result.get("chunks", 0)
                ingested += 1
        except Exception as e:
            logger.error("Error ingesting %s: %s", entry.get("url", "?"), e)
            errors += 1

        if ingested < max_articles:
            _time.sleep(FETCH_DELAY_SECS)

    return {"ingested": ingested, "skipped": skipped, "errors": errors, "chunks": chunks}


def dry_run_all_feeds(pool) -> Dict[str, Any]:
    """Parse all feeds, check dedup, report counts — no fetching, no Ollama calls."""
    feeds = get_enabled_feeds(RSS_FEEDS_ENABLED)
    feed_results = []

    for feed_config in feeds:
        entries = parse_feed(feed_config)
        new_count = 0
        existing_count = 0

        with pool.connection() as conn:
            with conn.cursor() as cur:
                for entry in entries:
                    url = entry.get("url", "")
                    if not url:
                        continue
                    doc_id = get_rss_doc_id(url)
                    cur.execute("SELECT 1 FROM rag_docs WHERE doc_id=%s", (doc_id,))
                    if cur.fetchone():
                        existing_count += 1
                    else:
                        new_count += 1

        feed_results.append({
            "feed": feed_config.name,
            "total": len(entries),
            "new": new_count,
            "existing": existing_count,
        })

    total_new = sum(f["new"] for f in feed_results)
    total_existing = sum(f["existing"] for f in feed_results)
    return {
        "feeds_checked": len(feed_results),
        "total_new": total_new,
        "total_existing": total_existing,
        "feeds": feed_results,
    }


def ingest_article(
    pool, entry: Dict, feed_config: FeedConfig, lang: str,
) -> Any:
    """
    Ingest a single article: fetch, extract, chunk, embed, store.
    Returns "skipped", or dict with chunk count on success.
    """
    url = entry.get("url", "")
    title = entry.get("title", "")
    if not url:
        return "skipped"

    doc_id = get_rss_doc_id(url)

    # Fetch the article page
    page = fetch_article(url, feed_config)

    # Extract text (3-tier fallback)
    text, image_urls = extract_article_content(
        page, feed_config,
        fallback_summary=entry.get("summary", ""),
        content_encoded=entry.get("content_encoded", ""),
    )

    if len(text) < 50:
        logger.info("Skipping %s — insufficient text (%d chars)", url, len(text))
        return "skipped"

    sha = sha256_text(text)

    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Check dedup
            process, _prev = should_process(cur, doc_id, sha)
            if not process:
                logger.info("Skipping %s — already ingested (same hash)", url)
                return "skipped"

            # Begin transactional ingestion
            chunk_count = 0
            try:
                delete_doc_chunks(cur, doc_id)
                upsert_doc(cur, doc_id, url, sha, lang, pages=1)

                # Chunk and embed text
                text_chunks = split_text(text, CHUNK_CHARS, CHUNK_OVERLAP)
                for idx, chunk in enumerate(text_chunks):
                    emb = _retry(lambda c=chunk: ollama_embeddings(c))
                    meta = {
                        "source": "rss_article",
                        "content_type": "rss_article",
                        "feed_name": feed_config.name,
                        "feed_url": feed_config.feed_url,
                        "title": title,
                        "author": entry.get("author", ""),
                        "published_at": entry.get("published", ""),
                        "url": url,
                        "chunk_index": idx,
                    }
                    insert_chunk(cur, doc_id, "text", 1, chunk, None, None, emb, meta)
                    chunk_count += 1

                # Optionally process images
                if CAPTION_IMAGES and image_urls:
                    article_thumbs = []  # for within-article visual dedup
                    for im_i, img_url in enumerate(image_urls[:MAX_IMAGES_PER_ARTICLE]):
                        try:
                            img_resp = requests.get(img_url, timeout=30)
                            if img_resp.status_code != 200:
                                continue
                            img_bytes = img_resp.content
                            if len(img_bytes) < MIN_IMAGE_BYTES:
                                logger.debug("Skipping tiny image (%d bytes): %s", len(img_bytes), img_url)
                                continue

                            # Skip if visually same as another image from this article
                            if _is_visual_dup(img_bytes, article_thumbs):
                                logger.debug("Skipping visual duplicate within article: %s", img_url)
                                continue

                            clean_path = urllib.parse.urlparse(img_url).path
                            ext = clean_path.rsplit(".", 1)[-1][:4] if "." in clean_path else "jpg"
                            asset_name = _save_deduped_image(img_bytes, ext)

                            caption = _retry(
                                lambda ib=img_bytes, t=title, fn=feed_config.name, la=lang:
                                    ollama_caption_image_contextual(ib, t, fn, la)
                            ) or ""
                            emb_text = enriched_image_embedding_text(caption, title, feed_config.name)
                            emb = _retry(lambda et=emb_text: ollama_embeddings(et)) if caption else None

                            meta = {
                                "source": "rss_image",
                                "content_type": "rss_article",
                                "feed_name": feed_config.name,
                                "title": title,
                                "url": url,
                                "image_index": im_i,
                            }
                            insert_chunk(cur, doc_id, "image", 1, None, caption, asset_name, emb, meta)
                            chunk_count += 1
                        except Exception as e:
                            logger.warning("Image %s failed: %s", img_url, e)

                conn.commit()
                logger.info(
                    "Ingested: %s — %d chunks (%s)",
                    title[:60], chunk_count, feed_config.name,
                )

            except Exception:
                conn.rollback()
                logger.warning("Ingestion failed for %s, rolled back", url)
                raise

    return {"chunks": chunk_count}


def backfill_images_for_doc(pool, doc_id, url: str, lang: str = "de") -> dict:
    """
    Add image chunks to an existing RSS article that was ingested text-only.
    Does NOT re-process text — only fetches images, captions, embeds, and inserts.
    """
    from app.feeds import FEEDS

    # Find matching feed config by URL
    feed_config = None
    for fc in FEEDS.values():
        feed_domain = urllib.parse.urlparse(fc.feed_url).netloc.replace("www.", "")
        url_domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        if feed_domain == url_domain:
            feed_config = fc
            break

    if not feed_config or not feed_config.img_selector:
        return {"status": "skipped", "reason": "no feed config or img_selector"}

    page = fetch_article(url, feed_config)
    if page is None:
        return {"status": "skipped", "reason": "fetch failed"}

    _, image_urls = extract_article_content(
        page, feed_config, fallback_summary="", content_encoded=""
    )

    if not image_urls:
        return {"status": "skipped", "reason": "no images found"}

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT meta->>'title' FROM rag_chunks WHERE doc_id=%s AND chunk_type='text' LIMIT 1",
                (doc_id,),
            )
            row = cur.fetchone()
            title = row[0] if row else ""

            image_count = 0

            try:
                article_thumbs = []  # for within-article visual dedup
                for im_i, img_url in enumerate(image_urls[:MAX_IMAGES_PER_ARTICLE]):
                    try:
                        img_resp = requests.get(img_url, timeout=30)
                        if img_resp.status_code != 200:
                            continue
                        img_bytes = img_resp.content
                        if len(img_bytes) < MIN_IMAGE_BYTES:
                            logger.debug("Skipping tiny image (%d bytes): %s", len(img_bytes), img_url)
                            continue

                        if _is_visual_dup(img_bytes, article_thumbs):
                            logger.debug("Skipping visual duplicate within article: %s", img_url)
                            continue

                        clean_path = urllib.parse.urlparse(img_url).path
                        ext = clean_path.rsplit(".", 1)[-1][:4] if "." in clean_path else "jpg"
                        asset_name = _save_deduped_image(img_bytes, ext)

                        caption = _retry(
                            lambda ib=img_bytes, t=title, fn=feed_config.name, la=lang:
                                ollama_caption_image_contextual(ib, t, fn, la)
                        ) or ""
                        emb_text = enriched_image_embedding_text(caption, title, feed_config.name)
                        emb = _retry(lambda et=emb_text: ollama_embeddings(et)) if caption else None

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
                logger.warning("Backfill failed for %s, rolled back", url)
                raise

    return {"status": "ok", "images_added": image_count}


def recaption_image_chunk(pool, chunk: dict, lang: str = "de") -> dict:
    """
    Re-caption a single image chunk using contextual prompt and update in-place.
    Reads saved image from disk (no re-download).
    """
    from app.db import update_chunk_caption_embedding

    asset_path = os.path.join(ASSETS_DIR, chunk["asset_path"])
    if not os.path.exists(asset_path):
        return {"status": "skipped", "reason": "asset file missing"}

    with open(asset_path, "rb") as f:
        img_bytes = f.read()

    if len(img_bytes) < MIN_IMAGE_BYTES:
        return {"status": "skipped", "reason": "image too small"}

    meta = chunk.get("meta", {})
    title = meta.get("title", "")
    feed_name = meta.get("feed_name", "RSS")

    caption = _retry(
        lambda ib=img_bytes, t=title, fn=feed_name, la=lang:
            ollama_caption_image_contextual(ib, t, fn, la)
    ) or ""
    emb_text = enriched_image_embedding_text(caption, title, feed_name)
    emb = _retry(lambda et=emb_text: ollama_embeddings(et)) if caption else None

    with pool.connection() as conn:
        with conn.cursor() as cur:
            update_chunk_caption_embedding(cur, chunk["id"], caption, emb)
        conn.commit()

    return {"status": "ok", "caption": caption[:80]}
