import base64
import hashlib
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time as _time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import psycopg
import requests
from fastapi import FastAPI, File, UploadFile
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from .extractor import layout_to_chunks, parse as parse_layout
from .splitter import split_text

# ---------------------------------------------------------------------------
# Logging (structured JSON)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("pdf-ingest")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DATABASE_HOST", "postgres")
DB_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DB_NAME = os.getenv("DATABASE_NAME", "rag")
DB_USER = os.getenv("DATABASE_USER", "rag_user")
DB_PASS = os.getenv("DATABASE_PASSWORD", "")

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:7b")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")

INBOX_DIR = os.getenv("INBOX_DIR", "/kb/inbox")
PROCESSED_DIR = os.getenv("PROCESSED_DIR", "/kb/processed")
ASSETS_DIR = os.getenv("ASSETS_DIR", "/kb/assets")

MAX_DOCS_PER_SCAN = int(os.getenv("MAX_DOCS_PER_SCAN", "10"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "0"))
MAX_IMAGES_PER_PAGE = int(os.getenv("MAX_IMAGES_PER_PAGE", "5"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))

LOCK_FILE = os.getenv("LOCK_FILE", "/tmp/pdf_ingest.lock")

CAPTION_TIMEOUT = 60  # seconds — skip image if vision model hangs
ERROR_DIR = os.getenv("ERROR_DIR", "/kb/error")

# ---------------------------------------------------------------------------
# Concurrency config
# ---------------------------------------------------------------------------
MAX_CONCURRENT_DOCS = int(os.getenv("MAX_CONCURRENT_DOCS", "2"))
MAX_CAPTION_WORKERS = int(os.getenv("MAX_CAPTION_WORKERS", "3"))
CAPTION_QUEUE_SIZE = int(os.getenv("CAPTION_QUEUE_SIZE", "50"))
WATCHER_POLL_INTERVAL = int(os.getenv("WATCHER_POLL_INTERVAL", "10"))
DOC_TIMEOUT = int(os.getenv("DOC_TIMEOUT", "1800"))  # 30 min per document

shutdown_event = threading.Event()
caption_q: queue.Queue = queue.Queue(maxsize=CAPTION_QUEUE_SIZE)
doc_executor: Optional[ThreadPoolExecutor] = None
_submit_lock = threading.Lock()
_submitted_paths: set[str] = set()

# Thread-safe status counters
_status_lock = threading.Lock()
_status = {
    "active_docs": 0,
    "completed_docs": 0,
    "failed_docs": 0,
    "completed_images": 0,
    "completed_text_chunks": 0,
    "skipped_images": 0,
}


def _inc(key: str, n: int = 1):
    with _status_lock:
        _status[key] = _status.get(key, 0) + n


def _dec(key: str, n: int = 1):
    with _status_lock:
        _status[key] = _status.get(key, 0) - n


MIN_IMAGE_WIDTH = 150   # pixels — skip icons, logos
MIN_IMAGE_HEIGHT = 150
MIN_IMAGE_BYTES = 5120  # 5 KB — skip spacers, lines, tracking pixels


def _should_skip_image(base: dict, xref: int, seen_xrefs: set) -> bool:
    """Return True if image should be skipped (junk, duplicate, too small)."""
    if xref in seen_xrefs:
        return True
    if base["width"] < MIN_IMAGE_WIDTH or base["height"] < MIN_IMAGE_HEIGHT:
        return True
    if len(base["image"]) < MIN_IMAGE_BYTES:
        return True
    return False


def _should_skip_external_image(path: str, seen_hashes: set) -> tuple[bool, Optional[str]]:
    """Return (skip, sha256) for an image file emitted by opendataloader."""
    if not path or not os.path.isfile(path):
        return True, None
    if os.path.getsize(path) < MIN_IMAGE_BYTES:
        return True, None
    try:
        pix = fitz.Pixmap(path)
    except Exception:
        return True, None
    if pix.width < MIN_IMAGE_WIDTH or pix.height < MIN_IMAGE_HEIGHT:
        return True, None
    with open(path, "rb") as f:
        raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    if sha in seen_hashes:
        return True, sha
    return False, sha


MAX_IMAGE_DIM = 1024  # max pixels on longest side for vision model


def downscale_image(img_bytes: bytes) -> tuple:
    """Downscale image via shrink(n), convert CMYK→RGB, drop alpha.
    Returns (jpeg_bytes, 'jpeg').
    Uses pix.shrink(n) which divides dimensions by 2^n (in-place)."""
    pix = fitz.Pixmap(img_bytes)

    # CMYK or other non-RGB colorspace → convert to RGB
    if pix.colorspace and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)

    # Drop alpha channel
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)

    # Find smallest n where max(w,h) >> n <= MAX_IMAGE_DIM
    w, h = pix.width, pix.height
    if max(w, h) > MAX_IMAGE_DIM:
        n = 1
        while max(w, h) >> n > MAX_IMAGE_DIM and n < 4:
            n += 1
        pix.shrink(n)

    return pix.tobytes(output="jpeg", jpg_quality=85), "jpeg"


# ---------------------------------------------------------------------------
# Connection pool (initialized in lifespan)
# ---------------------------------------------------------------------------
pool: Optional[ConnectionPool] = None

# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app):
    global pool, doc_executor
    # Startup: clean stale lock (backward compat)
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
        logger.info("Stale lock removed on startup")

    ensure_dirs()

    try:
        subprocess.run(["java", "-version"], check=True, capture_output=True, timeout=5)
        logger.info("Java runtime verified")
    except Exception as e:
        logger.error("Java runtime not available: %s", e)
        raise RuntimeError("Java 11+ required for opendataloader-pdf") from e

    # Init DB connection pool (max=4: 2 doc workers + 1 health + 1 spare)
    conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS}"
    pool = ConnectionPool(
        conninfo, min_size=2, max_size=4, open=True,
        configure=lambda conn: register_vector(conn),
    )
    logger.info("Connection pool initialized (min=2, max=4)")

    # Start caption worker threads
    caption_threads = []
    for i in range(MAX_CAPTION_WORKERS):
        t = threading.Thread(target=_caption_worker, name=f"caption-{i}", daemon=True)
        t.start()
        caption_threads.append(t)
    logger.info("Started %d caption workers", MAX_CAPTION_WORKERS)

    # Start doc executor
    doc_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOCS, thread_name_prefix="doc")

    # Start file watcher
    watcher_thread = threading.Thread(target=_inbox_watcher, name="watcher", daemon=True)
    watcher_thread.start()

    logger.info("pdf-ingest v0.5.0 starting (parallel: %d docs, %d caption workers, queue=%d)",
                MAX_CONCURRENT_DOCS, MAX_CAPTION_WORKERS, CAPTION_QUEUE_SIZE)
    yield

    # Shutdown: signal all threads, cancel queued docs, don't block on executor
    shutdown_event.set()
    doc_executor.shutdown(wait=False, cancel_futures=True)
    watcher_thread.join(timeout=15)
    for t in caption_threads:
        t.join(timeout=5)
    pool.close()
    logger.info("pdf-ingest shutting down")


app = FastAPI(title="pdf-ingest", version="0.5.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CAPTION_PROMPTS = {
    "de": "Beschreibe dieses Bild kurz und präzise auf Deutsch (1-2 Sätze).",
    "en": "Describe this image briefly and precisely in English (1-2 sentences).",
    "fr": "Décrivez cette image brièvement et précisément en français (1-2 phrases).",
}


def sanitize_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r'[^\w.\-]', '_', name)
    return name or "upload.pdf"


def ensure_dirs():
    for d in [INBOX_DIR, PROCESSED_DIR, ASSETS_DIR, ERROR_DIR]:
        os.makedirs(d, exist_ok=True)



def _retry(fn, max_retries=3, backoff=(2, 4, 8)):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except (requests.RequestException, requests.Timeout, ConnectionError) as e:
            if attempt == max_retries:
                raise
            delay = backoff[min(attempt, len(backoff) - 1)]
            logger.warning("Ollama call failed (attempt %d/%d), retrying in %ds: %s",
                           attempt + 1, max_retries, delay, e)
            _time.sleep(delay)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def ollama_embeddings(text: str) -> List[float]:
    resp = requests.post(
        f"{OLLAMA_BASE}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


EMBED_BATCH_SIZE = 10


def _embedding_input(text: str) -> Optional[str]:
    stripped = (text or "").strip()
    if not stripped:
        return None
    cleaned = re.sub(r"\ufffd+", " ", stripped)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    cleaned_alnum = sum(1 for c in cleaned if c.isalnum())
    if len(cleaned) > 40 and cleaned_alnum / len(cleaned) < 0.20:
        return None
    return cleaned


def _post_embed(batch: list[str]) -> list:
    resp = requests.post(
        f"{OLLAMA_BASE}/api/embed",
        json={"model": EMBED_MODEL, "input": batch},
        timeout=120,
    )
    resp.raise_for_status()
    embeddings = resp.json().get("embeddings") or []
    if len(embeddings) != len(batch):
        raise RuntimeError(
            f"Ollama returned {len(embeddings)} embeddings for {len(batch)} inputs"
        )
    return embeddings


def _embed_batch_resilient(batch: list[str]) -> list:
    try:
        return _post_embed(batch)
    except Exception as e:
        if len(batch) <= 1:
            sample = re.sub(r"\s+", " ", batch[0] if batch else "").strip()[:160]
            logger.warning(
                "Embedding failed for one chunk; storing without embedding: %s (%s)",
                sample,
                e,
            )
            return [None]

        mid = len(batch) // 2
        logger.warning(
            "Embedding batch failed for %d chunks; retrying as %d + %d chunks: %s",
            len(batch),
            mid,
            len(batch) - mid,
            e,
        )
        return _embed_batch_resilient(batch[:mid]) + _embed_batch_resilient(batch[mid:])


def ollama_embed_batch(texts: list) -> list:
    """Embed multiple texts in batches via /api/embed. Returns list of embedding vectors."""
    if not texts:
        return []
    all_embeddings = [None] * len(texts)
    batch: list[str] = []
    batch_indexes: list[int] = []

    def flush_batch():
        nonlocal batch, batch_indexes
        if not batch:
            return
        embeddings = _embed_batch_resilient(batch)
        for idx, emb in zip(batch_indexes, embeddings):
            all_embeddings[idx] = emb
        batch = []
        batch_indexes = []

    for idx, text in enumerate(texts):
        embed_text = _embedding_input(text)
        if embed_text is None:
            sample = re.sub(r"\s+", " ", text or "").strip()[:160]
            logger.warning("Skipping embedding for non-text/gibberish chunk: %s", sample)
            continue
        batch.append(embed_text)
        batch_indexes.append(idx)
        if len(batch) >= EMBED_BATCH_SIZE:
            flush_batch()

    flush_batch()
    return all_embeddings


def ollama_caption_image(image_bytes: bytes, lang: str = "de") -> str:
    prompt = CAPTION_PROMPTS.get(lang, CAPTION_PROMPTS["de"])
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        ],
        "stream": False,
        "options": {"num_ctx": 8192},
    }
    try:
        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=CAPTION_TIMEOUT)
        resp.raise_for_status()
        return (resp.json().get("message", {}) or {}).get("content", "").strip()
    except requests.Timeout:
        logger.warning("Caption timed out after %ds — skipping image", CAPTION_TIMEOUT)
        return ""


# ---------------------------------------------------------------------------
# Caption worker (consumer thread for caption_q)
# ---------------------------------------------------------------------------
# Queue items: (doc_id, page, im_i, img_bytes, lang, asset_name, meta_extra, cancel_event, result_q)


def _caption_worker():
    """Consume images from caption_q, caption + embed, put result in per-doc queue."""
    while not shutdown_event.is_set():
        try:
            item = caption_q.get(timeout=2)
        except queue.Empty:
            continue

        doc_id, page, im_i, img_bytes, lang, asset_name, meta_extra, cancel_event, result_q = item
        try:
            if cancel_event.is_set():
                caption_q.task_done()
                continue

            caption = _retry(lambda ib=img_bytes, la=lang: ollama_caption_image(ib, la))
            emb = ollama_embed_batch([caption])[0] if caption else None
            result_q.put((page, im_i, caption, asset_name, emb, meta_extra))
            _inc("completed_images")
        except Exception:
            logger.exception("Caption failed for %s page %d", doc_id, page)
            result_q.put((page, im_i, "", asset_name, None, meta_extra))
        finally:
            caption_q.task_done()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


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


def get_or_create_doc_id(filename: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mmrag:{filename}")


def should_process(cur, doc_id: uuid.UUID, sha: str) -> Tuple[bool, Optional[str]]:
    cur.execute("SELECT sha256 FROM rag_docs WHERE doc_id=%s", (doc_id,))
    row = cur.fetchone()
    if not row:
        return True, None
    existing = row[0]
    return existing != sha, existing


# ---------------------------------------------------------------------------
# Core ingestion
# ---------------------------------------------------------------------------


def _queue_legacy_pymupdf(
    cur,
    pdf_path: str,
    doc_id: uuid.UUID,
    lang: str,
    total_pages: int,
    cancel_event: threading.Event,
    result_q: queue.Queue,
    written_assets: List[str],
    stats: Dict[str, Any],
) -> int:
    """Legacy PyMuPDF path used as a fallback when opendataloader fails."""
    images_queued = 0
    seen_xrefs: set = set()
    with fitz.open(pdf_path) as doc:
        for pno in range(total_pages):
            page = doc.load_page(pno)
            text = page.get_text("text") or ""
            text_chunks = split_text(text, CHUNK_CHARS, CHUNK_OVERLAP)

            if text_chunks:
                text_embeddings = ollama_embed_batch(text_chunks)
                for idx, (chunk, emb) in enumerate(zip(text_chunks, text_embeddings)):
                    meta = {
                        "source": "pdf_text",
                        "page": pno + 1,
                        "chunk_index": idx,
                        "extractor": "pymupdf-fallback",
                    }
                    if emb is None:
                        meta["embedding_error"] = "ollama_embed_failed"
                    insert_chunk(
                        cur, doc_id, "text", pno + 1, chunk, None, None, emb,
                        meta,
                    )
                stats["text_chunks"] += len(text_chunks)
                _inc("completed_text_chunks", len(text_chunks))

            images = page.get_images(full=True) or []
            img_count = 0
            for im_i, img in enumerate(images[:MAX_IMAGES_PER_PAGE]):
                xref = img[0]
                base = doc.extract_image(xref)
                if _should_skip_image(base, xref, seen_xrefs):
                    stats["skipped_images"] += 1
                    _inc("skipped_images")
                    continue
                seen_xrefs.add(xref)

                img_bytes, ext = downscale_image(base["image"])
                asset_name = f"{doc_id}_p{pno + 1}_i{im_i}.{ext}"
                asset_path = os.path.join(ASSETS_DIR, asset_name)
                with open(asset_path, "wb") as f:
                    f.write(img_bytes)
                written_assets.append(asset_path)

                caption_q.put(
                    (
                        doc_id, pno + 1, im_i, img_bytes, lang, asset_name,
                        {"extractor": "pymupdf-fallback"},
                        cancel_event, result_q,
                    ),
                    block=True,
                )
                images_queued += 1
                img_count += 1

            logger.info("Page %d/%d fallback: %d text chunks, %d images queued",
                        pno + 1, total_pages, len(text_chunks), img_count)
    return images_queued


def _queue_opendataloader_chunks(
    cur,
    chunks: list,
    doc_id: uuid.UUID,
    lang: str,
    total_pages: int,
    cancel_event: threading.Event,
    result_q: queue.Queue,
    written_assets: List[str],
    stats: Dict[str, Any],
) -> int:
    text_chunks = [
        c for c in chunks
        if c.chunk_type == "text" and c.content_text and c.page <= total_pages
    ]
    if text_chunks:
        embeddings = ollama_embed_batch([c.content_text for c in text_chunks])
        for idx, (chunk, emb) in enumerate(zip(text_chunks, embeddings)):
            meta = dict(chunk.meta)
            meta.setdefault("chunk_index", idx)
            if emb is None:
                meta["embedding_error"] = "ollama_embed_failed"
            insert_chunk(
                cur,
                doc_id,
                "text",
                chunk.page,
                chunk.content_text,
                None,
                None,
                emb,
                meta,
            )
        stats["text_chunks"] += len(text_chunks)
        _inc("completed_text_chunks", len(text_chunks))

    images_queued = 0
    seen_hashes: set[str] = set()
    page_image_counts: Dict[int, int] = {}
    for chunk in chunks:
        if chunk.chunk_type != "image" or chunk.page > total_pages:
            continue
        im_i = page_image_counts.get(chunk.page, 0)
        page_image_counts[chunk.page] = im_i + 1
        if im_i >= MAX_IMAGES_PER_PAGE:
            stats["skipped_images"] += 1
            _inc("skipped_images")
            continue

        skip, image_sha = _should_skip_external_image(chunk.image_path, seen_hashes)
        if skip:
            stats["skipped_images"] += 1
            _inc("skipped_images")
            continue
        if image_sha:
            seen_hashes.add(image_sha)

        with open(chunk.image_path, "rb") as f:
            raw_img = f.read()
        img_bytes, ext = downscale_image(raw_img)
        asset_name = f"{doc_id}_p{chunk.page}_i{im_i}.{ext}"
        asset_path = os.path.join(ASSETS_DIR, asset_name)
        with open(asset_path, "wb") as f:
            f.write(img_bytes)
        written_assets.append(asset_path)

        meta_extra = dict(chunk.meta)
        if image_sha:
            meta_extra["image_sha256"] = image_sha
        caption_q.put(
            (
                doc_id, chunk.page, im_i, img_bytes, lang, asset_name,
                meta_extra, cancel_event, result_q,
            ),
            block=True,
        )
        images_queued += 1

    logger.info("Structured extraction queued: %d text chunks, %d images",
                len(text_chunks), images_queued)
    return images_queued


def extract_and_store(pdf_path: str, doc_id: uuid.UUID, lang: str) -> Dict[str, Any]:
    ensure_dirs()
    filename = os.path.basename(pdf_path)
    sha = sha256_file(pdf_path)
    t0 = _time.monotonic()

    stats = {"filename": filename, "doc_id": str(doc_id), "sha256": sha,
             "pages": 0, "text_chunks": 0, "images": 0, "skipped_images": 0}

    with pool.connection() as conn:
        with conn.cursor() as cur:
            process, _prev = should_process(cur, doc_id, sha)
            if not process:
                return {"status": "skipped", "reason": "already_ingested", **stats}

            delete_doc_chunks(cur, doc_id)

            with fitz.open(pdf_path) as doc:
                total_pages = doc.page_count
                if MAX_PAGES > 0:
                    total_pages = min(total_pages, MAX_PAGES)

            stats["pages"] = total_pages
            upsert_doc(cur, doc_id, filename, sha, lang, total_pages)
            logger.info("Ingestion started: %s (%d pages)", filename, total_pages)

            written_assets: List[str] = []
            cancel_event = threading.Event()
            result_q: queue.Queue = queue.Queue()
            images_queued = 0
            out_dir = None

            try:
                # --- Phase 1: Structured extraction ---
                try:
                    elements, out_dir = parse_layout(pdf_path, str(doc_id))
                    elements = [e for e in elements if e.page <= total_pages]
                    chunks = layout_to_chunks(elements, CHUNK_CHARS, CHUNK_OVERLAP)
                    if not chunks:
                        raise RuntimeError("opendataloader produced zero chunks")
                except Exception:
                    if out_dir:
                        shutil.rmtree(out_dir, ignore_errors=True)
                        out_dir = None
                    logger.exception(
                        "opendataloader failed for %s; falling back to PyMuPDF",
                        filename,
                    )
                    images_queued = _queue_legacy_pymupdf(
                        cur, pdf_path, doc_id, lang, total_pages,
                        cancel_event, result_q, written_assets, stats,
                    )
                else:
                    images_queued = _queue_opendataloader_chunks(
                        cur, chunks, doc_id, lang, total_pages,
                        cancel_event, result_q, written_assets, stats,
                    )

                # --- Phase 2: Wait for caption results ---
                caption_results = []
                deadline = _time.monotonic() + DOC_TIMEOUT
                while len(caption_results) < images_queued:
                    remaining = deadline - _time.monotonic()
                    if remaining <= 0:
                        logger.error("Document timeout (%ds) for %s — %d/%d images done",
                                     DOC_TIMEOUT, filename, len(caption_results), images_queued)
                        cancel_event.set()  # Purge remaining queued images for this doc
                        break
                    try:
                        result = result_q.get(timeout=min(remaining, 5))
                        caption_results.append(result)
                    except queue.Empty:
                        continue

                # --- Phase 3: Insert caption chunks into DB ---
                for page_no, im_i, caption, asset_name, emb, meta_extra in caption_results:
                    meta = {"source": "pdf_image", "page": page_no, "image_index": im_i}
                    meta.update(meta_extra or {})
                    insert_chunk(
                        cur, doc_id, "image", page_no, None, caption, asset_name, emb,
                        meta,
                    )
                stats["images"] = len(caption_results)

                conn.commit()

            except Exception:
                cancel_event.set()  # Tell caption workers to skip remaining images
                conn.rollback()
                for path in written_assets:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                logger.warning("Ingestion failed for %s, rolled back %d chunks and %d assets",
                               filename, stats["text_chunks"] + stats["images"], len(written_assets))
                raise
            finally:
                if out_dir:
                    shutil.rmtree(out_dir, ignore_errors=True)

    elapsed = _time.monotonic() - t0
    logger.info("Ingestion complete: %s — %d text chunks, %d images in %.1fs",
                filename, stats["text_chunks"], stats["images"], elapsed)
    return {"status": "ingested", **stats}


def move_to_processed(pdf_path: str):
    dst = os.path.join(PROCESSED_DIR, os.path.basename(pdf_path))
    # shutil.move uses os.rename first, which fails across Docker bind mounts
    # (different filesystems → EXDEV). Copy + remove works reliably.
    shutil.copy2(pdf_path, dst)
    os.remove(pdf_path)


def move_to_error(pdf_path: str) -> bool:
    if not os.path.exists(pdf_path):
        return False
    dst = os.path.join(ERROR_DIR, os.path.basename(pdf_path))
    shutil.copy2(pdf_path, dst)
    os.remove(pdf_path)
    return True


def list_pdfs(folder: str) -> List[str]:
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, fn) for fn in sorted(os.listdir(folder)) if fn.lower().endswith(".pdf")]


def _submit_pdf(pdf_path: str, lang: str = "de") -> bool:
    """Submit a PDF once while it remains in inbox."""
    norm_path = os.path.abspath(pdf_path)
    with _submit_lock:
        if norm_path in _submitted_paths:
            return False
        if not os.path.exists(norm_path):
            return False
        _submitted_paths.add(norm_path)
    try:
        doc_executor.submit(_process_one, norm_path, lang)
    except Exception:
        with _submit_lock:
            _submitted_paths.discard(norm_path)
        raise
    return True


def _process_one(pdf_path: str, lang: str = "de"):
    """Process a single PDF with error handling. Called by executor threads."""
    pdf_path = os.path.abspath(pdf_path)
    filename = os.path.basename(pdf_path)
    _inc("active_docs")
    try:
        if not os.path.exists(pdf_path):
            logger.warning("Skipping missing PDF already moved by another worker: %s", filename)
            return
        doc_id = get_or_create_doc_id(filename)
        result = extract_and_store(pdf_path, doc_id, lang)
        if result.get("status") in ("ingested", "skipped"):
            move_to_processed(pdf_path)
        if result.get("status") == "ingested":
            _inc("completed_docs")
        logger.info("Result for %s: %s", filename, result.get("status"))
    except Exception:
        logger.exception("Fatal error processing %s — moving to error dir", filename)
        os.makedirs(ERROR_DIR, exist_ok=True)
        if not move_to_error(pdf_path):
            logger.warning("Could not move %s to error dir because it no longer exists", filename)
        _inc("failed_docs")
    finally:
        with _submit_lock:
            _submitted_paths.discard(pdf_path)
        _dec("active_docs")


def _inbox_watcher():
    """Poll inbox for new PDFs. Submit stable files (size unchanged for 2 polls) to executor."""
    known: Dict[str, int] = {}  # path → file size at last poll
    stable: set = set()         # paths already submitted to executor

    logger.info("File watcher started (poll every %ds)", WATCHER_POLL_INTERVAL)

    while not shutdown_event.is_set():
        try:
            ensure_dirs()
            current: Dict[str, int] = {}
            for p in list_pdfs(INBOX_DIR):
                try:
                    current[p] = os.path.getsize(p)
                except OSError:
                    continue

            for path, size in current.items():
                if path in stable:
                    continue
                prev_size = known.get(path)
                if prev_size is not None and prev_size == size:
                    # Size stable for 2 consecutive polls → submit
                    stable.add(path)
                    if _submit_pdf(path):
                        logger.info("New PDF detected (stable): %s", os.path.basename(path))

            # Clean up: remove entries for files no longer in inbox (moved to processed/error)
            known = {p: s for p, s in current.items() if p not in stable}
            stable = {p for p in stable if p in current}
        except Exception:
            logger.exception("Watcher error")

        shutdown_event.wait(WATCHER_POLL_INTERVAL)

    logger.info("File watcher stopped")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat()}


@app.get("/health/ready")
def health_ready():
    checks = {}
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = str(e)
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        checks["ollama"] = "ok" if r.ok else f"status {r.status_code}"
    except Exception as e:
        checks["ollama"] = str(e)
    ok = all(v == "ok" for v in checks.values())
    return {"ok": ok, "checks": checks}


@app.post("/ingest/upload", status_code=202)
async def ingest_upload(file: UploadFile = File(...), lang: str = "de"):
    """Accept PDF upload, save to inbox for background processing."""
    ensure_dirs()

    if file.size and file.size > MAX_UPLOAD_BYTES:
        return {"status": "error", "reason": f"file too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)"}

    safe_name = sanitize_filename(file.filename)
    dst = os.path.join(INBOX_DIR, safe_name)
    total = 0
    try:
        with open(dst, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise ValueError("file too large")
                f.write(chunk)
    except ValueError:
        if os.path.exists(dst):
            os.remove(dst)
        return {"status": "error", "reason": f"file too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)"}

    logger.info("Upload accepted: %s (%d bytes) — queued in inbox", safe_name, total)
    return {"status": "accepted", "filename": safe_name,
            "message": "File saved to inbox, processing will start automatically"}


@app.post("/ingest/scan")
def ingest_scan(max_docs: int = 10, lang: str = "de"):
    """Submit inbox PDFs to the processing queue. Returns immediately.

    Note: If the file watcher already submitted a file that is still processing
    (file remains in inbox until move_to_processed), this will submit it again.
    The SHA256 dedup in should_process will return "skipped" — benign but logged.
    """
    ensure_dirs()
    pdfs = list_pdfs(INBOX_DIR)[:max_docs]
    submitted = 0
    for pdf_path in pdfs:
        if _submit_pdf(pdf_path, lang):
            submitted += 1
    return {"status": "ok", "submitted": submitted, "inbox_total": len(list_pdfs(INBOX_DIR))}


@app.get("/ingest/status")
def ingest_status():
    """Return current ingestion status for monitoring/dashboard."""
    with _status_lock:
        s = dict(_status)
    return {
        **s,
        "caption_queue_size": caption_q.qsize(),
        "caption_queue_max": CAPTION_QUEUE_SIZE,
        "inbox_files": len(list_pdfs(INBOX_DIR)),
        "error_files": len([f for f in os.listdir(ERROR_DIR) if f.lower().endswith(".pdf")]) if os.path.isdir(ERROR_DIR) else 0,
    }
