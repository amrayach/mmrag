import logging
import os
import time as _time
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
from app.ollama import _retry, ollama_caption_image, ollama_embeddings
from app.scraper import (
    extract_article_content, fetch_article, parse_feed, sha256_text,
)
from app.text import split_text

logger = logging.getLogger("rss-ingest")


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
            written_assets = []
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
                    rss_assets_dir = os.path.join(ASSETS_DIR, "rss", str(doc_id)[:8])
                    os.makedirs(rss_assets_dir, exist_ok=True)

                    for im_i, img_url in enumerate(image_urls[:MAX_IMAGES_PER_ARTICLE]):
                        try:
                            img_resp = requests.get(img_url, timeout=30)
                            if img_resp.status_code != 200:
                                continue
                            img_bytes = img_resp.content

                            ext = img_url.rsplit(".", 1)[-1][:4] if "." in img_url else "jpg"
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
                # Clean orphan assets
                for path in written_assets:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                logger.warning("Ingestion failed for %s, rolled back", url)
                raise

    return {"chunks": chunk_count}
