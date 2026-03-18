import base64
import hashlib
import json
import logging
import os
import queue
import re
import shutil
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


def split_text(text: str, chunk_chars: int, overlap: int) -> List[str]:
    if not text or not text.strip():
        return []

    # Collapse horizontal whitespace but PRESERVE newlines for paragraph detection
    text = re.sub(r'[^\S\n]+', ' ', text)

    # Split on paragraph breaks first, then on sentence boundaries
    # (period/!/? followed by space + capital letter — avoids breaking "z.B." or "Nr.")
    paragraphs = re.split(r'\n\s*\n+', text)
    sentences: List[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        parts = re.split(r'(?<=[.!?])\s+(?=[A-ZÄÖÜ])', para)
        sentences.extend(p.strip() for p in parts if p.strip())

    # Merge sentences into chunks up to chunk_chars
    chunks: List[str] = []
    current = ""
    for sent in sentences:
        if current and len(current) + len(sent) + 1 > chunk_chars:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = (tail + " " + sent).strip() if tail else sent
        else:
            current = (current + " " + sent).strip() if current else sent
    if current:
        chunks.append(current)

    # Fallback: hard-split any oversized chunks (single huge sentence)
    result: List[str] = []
    for c in chunks:
        if len(c) <= chunk_chars:
            result.append(c)
        else:
            start = 0
            while start < len(c):
                result.append(c[start:start + chunk_chars])
                start += chunk_chars - overlap
    return result


def ollama_embeddings(text: str) -> List[float]:
    resp = requests.post(
        f"{OLLAMA_BASE}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


EMBED_BATCH_SIZE = 10


def ollama_embed_batch(texts: list) -> list:
    """Embed multiple texts in batches via /api/embed. Returns list of embedding vectors."""
    if not texts:
        return []
    all_embeddings = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        resp = _retry(lambda b=batch: requests.post(
            f"{OLLAMA_BASE}/api/embed",
            json={"model": EMBED_MODEL, "input": b},
            timeout=120,
        ))
        resp.raise_for_status()
        all_embeddings.extend(resp.json()["embeddings"])
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
# Queue items: (doc_id, page, im_i, img_bytes, lang, asset_name, cancel_event, result_q)


def _caption_worker():
    """Consume images from caption_q, caption + embed, put result in per-doc queue."""
    while not shutdown_event.is_set():
        try:
            item = caption_q.get(timeout=2)
        except queue.Empty:
            continue

        doc_id, page, im_i, img_bytes, lang, asset_name, cancel_event, result_q = item
        try:
            if cancel_event.is_set():
                caption_q.task_done()
                continue

            caption = _retry(lambda ib=img_bytes, la=lang: ollama_caption_image(ib, la))
            emb = ollama_embed_batch([caption])[0] if caption else None
            result_q.put((page, im_i, caption, asset_name, emb))
            _inc("completed_images")
        except Exception:
            logger.exception("Caption failed for %s page %d", doc_id, page)
            result_q.put((page, im_i, "", asset_name, None))
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

            doc = fitz.open(pdf_path)
            total_pages = doc.page_count
            if MAX_PAGES > 0:
                total_pages = min(total_pages, MAX_PAGES)

            stats["pages"] = total_pages
            upsert_doc(cur, doc_id, filename, sha, lang, total_pages)
            logger.info("Ingestion started: %s (%d pages)", filename, total_pages)

            written_assets: List[str] = []
            cancel_event = threading.Event()
            result_q: queue.Queue = queue.Queue()
            seen_xrefs: set = set()
            images_queued = 0

            try:
                # --- Phase 1+2: Extract text + embed, queue images ---
                for pno in range(total_pages):
                    page = doc.load_page(pno)
                    text = page.get_text("text") or ""
                    text_chunks = split_text(text, CHUNK_CHARS, CHUNK_OVERLAP)

                    # Batch embed text
                    if text_chunks:
                        text_embeddings = ollama_embed_batch(text_chunks)
                        for idx, (chunk, emb) in enumerate(zip(text_chunks, text_embeddings)):
                            insert_chunk(
                                cur, doc_id, "text", pno + 1, chunk, None, None, emb,
                                {"source": "pdf_text", "page": pno + 1, "chunk_index": idx},
                            )
                        stats["text_chunks"] += len(text_chunks)
                        _inc("completed_text_chunks", len(text_chunks))

                    # Filter + downscale + queue images
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

                        asset_name = f"{doc_id}_p{pno+1}_i{im_i}.{ext}"
                        asset_path = os.path.join(ASSETS_DIR, asset_name)
                        with open(asset_path, "wb") as f:
                            f.write(img_bytes)
                        written_assets.append(asset_path)

                        # Enqueue for caption workers (blocks if queue full = backpressure)
                        caption_q.put(
                            (doc_id, pno + 1, im_i, img_bytes, lang, asset_name,
                             cancel_event, result_q),
                            block=True,
                        )
                        images_queued += 1
                        img_count += 1

                    logger.info("Page %d/%d: %d text chunks, %d images queued",
                                pno + 1, total_pages, len(text_chunks), img_count)

                # --- Phase 3: Wait for caption results ---
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

                # --- Phase 4: Insert caption chunks into DB ---
                for page_no, im_i, caption, asset_name, emb in caption_results:
                    insert_chunk(
                        cur, doc_id, "image", page_no, None, caption, asset_name, emb,
                        {"source": "pdf_image", "page": page_no, "image_index": im_i},
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


def list_pdfs(folder: str) -> List[str]:
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, fn) for fn in sorted(os.listdir(folder)) if fn.lower().endswith(".pdf")]


def _process_one(pdf_path: str, lang: str = "de"):
    """Process a single PDF with error handling. Called by executor threads."""
    filename = os.path.basename(pdf_path)
    _inc("active_docs")
    try:
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
        try:
            shutil.move(pdf_path, os.path.join(ERROR_DIR, filename))
        except Exception:
            logger.exception("Failed to move %s to error dir", filename)
        _inc("failed_docs")
    finally:
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
                    logger.info("New PDF detected (stable): %s", os.path.basename(path))
                    doc_executor.submit(_process_one, path)

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
        doc_executor.submit(_process_one, pdf_path, lang)
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
