# Fast Parallel PDF Ingestion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Speed up PDF ingestion ~8-9x with parallel processing, batch embeddings, image filtering, and auto file watcher.

**Architecture:** Pipeline with background file watcher, ThreadPoolExecutor(2) for docs, bounded caption queue with 3 workers, batch embeddings via `/api/embed`, and image filtering/downscaling via PyMuPDF shrink API.

**Tech Stack:** Python 3.11, FastAPI, PyMuPDF 1.24.14 (fitz), requests, psycopg_pool, threading, queue.Queue

**Design doc:** `docs/plans/2026-03-06-fast-pdf-ingestion-design.md`

**Verified in-container:**
- `pix.shrink(n)` — works (2^n divisor scaling)
- `fitz.Pixmap(fitz.csRGB, pix)` — works (CMYK→RGB)
- `fitz.Pixmap(pix, 0)` — works (drop alpha)
- `pix.tobytes(output="jpeg", jpg_quality=85)` — works
- `fitz.Pixmap(pix, new_w, new_h)` — **does NOT work** (constructor error)
- Pillow — **not available**, not needed
- `queue.SimpleQueue.get(timeout=...)` — **does NOT work** (no timeout param). Use `queue.Queue` instead.

---

### Task 1: docker-compose.yml — OLLAMA_NUM_PARALLEL + error dir

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Change OLLAMA_NUM_PARALLEL from 1 to 3**

In the `ollama` service environment section, change:
```yaml
OLLAMA_NUM_PARALLEL: "3"
```

**Step 2: Add error dir volume to pdf-ingest**

In the `pdf-ingest` service volumes, add:
```yaml
- ./data/error:/kb/error
```

**Step 3: Verify compose config**

Run: `docker compose -p ammer-mmragv2 config --quiet`
Expected: no output (valid config)

**Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "perf: OLLAMA_NUM_PARALLEL=3, add error dir volume for pdf-ingest"
```

---

### Task 2: Image filtering — skip junk images

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

**Step 1: Add image filtering constants after existing config (around line 53)**

```python
MIN_IMAGE_WIDTH = 150   # pixels — skip icons, logos
MIN_IMAGE_HEIGHT = 150
MIN_IMAGE_BYTES = 5120  # 5 KB — skip spacers, lines, tracking pixels
```

**Step 2: Add filter function after the constants**

```python
def _should_skip_image(base: dict, xref: int, seen_xrefs: set) -> bool:
    """Return True if image should be skipped (junk, duplicate, too small)."""
    if xref in seen_xrefs:
        return True
    if base["width"] < MIN_IMAGE_WIDTH or base["height"] < MIN_IMAGE_HEIGHT:
        return True
    if len(base["image"]) < MIN_IMAGE_BYTES:
        return True
    return False
```

**Step 3: Apply filtering in `extract_and_store`**

Move `seen_xrefs` to document scope — add before the `for pno in range(total_pages):` loop:
```python
seen_xrefs: set = set()
```

Replace the image iteration block inside the page loop. Change:
```python
images = (page.get_images(full=True) or [])[:MAX_IMAGES_PER_PAGE]
for im_i, img in enumerate(images):
    xref = img[0]
    base = doc.extract_image(xref)
    img_bytes = base["image"]
```

To:
```python
images = page.get_images(full=True) or []
img_count = 0
for im_i, img in enumerate(images[:MAX_IMAGES_PER_PAGE]):
    xref = img[0]
    base = doc.extract_image(xref)
    if _should_skip_image(base, xref, seen_xrefs):
        continue
    seen_xrefs.add(xref)
    img_bytes = base["image"]
    img_count += 1
```

Update the page log line at the end of the page loop to use the tracked counter instead of re-extracting:
```python
logger.info("Page %d/%d: %d text chunks, %d images", pno + 1, total_pages, len(text_chunks), img_count)
```

**Step 4: Commit**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "perf: add image filtering to skip junk images (<150px, <5KB, doc-scoped dedup)"
```

---

### Task 3: Image downscaling via PyMuPDF shrink

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

**Step 1: Add downscale constant and function after the filter function**

```python
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
```

**Why `>> n` not `// (2 ** (n + 1))`:** The previous loop had an off-by-one for images just over a power-of-two boundary (e.g., 4097px would stay at n=1, giving 2048px — still over 1024). The `>> n` loop checks the actual result: `4097 >> 1 = 2048 > 1024` → n=2. `4097 >> 2 = 1024` → stop. Correct.

**Step 2: Apply downscaling in the image processing block**

In `extract_and_store`, after the filter check and `seen_xrefs.add(xref)`, replace:
```python
img_bytes = base["image"]
ext = base.get("ext", "png")
```
with:
```python
img_bytes, ext = downscale_image(base["image"])
```

**Step 3: Commit**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "perf: downscale images via PyMuPDF shrink, normalize CMYK/alpha to RGB JPEG"
```

---

### Task 4: Batch embeddings via /api/embed

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

**Step 1: Add batch embedding constant and function**

Add after (or alongside) the existing `ollama_embeddings` function:

```python
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
```

**Step 2: Refactor text chunk embedding in extract_and_store**

Replace the per-chunk embedding loop:
```python
for idx, chunk in enumerate(text_chunks):
    emb = _retry(lambda c=chunk: ollama_embeddings(c))
    insert_chunk(cur, doc_id, "text", pno + 1, chunk, None, None, emb,
                 {"source": "pdf_text", "page": pno + 1, "chunk_index": idx})
```

With batched version:
```python
if text_chunks:
    text_embeddings = ollama_embed_batch(text_chunks)
    for idx, (chunk, emb) in enumerate(zip(text_chunks, text_embeddings)):
        insert_chunk(cur, doc_id, "text", pno + 1, chunk, None, None, emb,
                     {"source": "pdf_text", "page": pno + 1, "chunk_index": idx})
```

**Step 3: Commit**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "perf: batch text embeddings via /api/embed (10 per batch)"
```

---

### Task 5: Caption timeout + error directory + poison pill handling

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

**Step 1: Add constants**

```python
CAPTION_TIMEOUT = 60  # seconds — skip image if vision model hangs
ERROR_DIR = os.getenv("ERROR_DIR", "/kb/error")
```

**Step 2: Update ensure_dirs**

```python
def ensure_dirs():
    for d in [INBOX_DIR, PROCESSED_DIR, ASSETS_DIR, ERROR_DIR]:
        os.makedirs(d, exist_ok=True)
```

**Step 3: Update ollama_caption_image timeout and add timeout handling**

Change the timeout from 180 to `CAPTION_TIMEOUT` and add explicit timeout catch:
```python
def ollama_caption_image(image_bytes: bytes, lang: str = "de") -> str:
    prompt = CAPTION_PROMPTS.get(lang, CAPTION_PROMPTS["de"])
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        "stream": False,
    }
    try:
        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=CAPTION_TIMEOUT)
        resp.raise_for_status()
        return (resp.json().get("message", {}) or {}).get("content", "").strip()
    except requests.Timeout:
        logger.warning("Caption timed out after %ds — skipping image", CAPTION_TIMEOUT)
        return ""
```

**IMPORTANT — _retry interaction:** The existing `_retry` wrapper catches `requests.RequestException` (which includes `requests.Timeout`). Because `ollama_caption_image` now catches `Timeout` internally and returns `""`, the timeout **never propagates** to `_retry`. This means:
- **Timeouts** → fail fast (60s, no retry) — correct, avoids wasting 3×60s on pathological images
- **Connection errors** (Ollama model swapping, brief unavailability) → retried 3× with backoff — correct

Do NOT change `_retry` to exclude `Timeout` — the current interaction is correct by design.

**Step 4: Commit**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "fix: 60s caption timeout, error directory, poison pill handling prep"
```

---

### Task 6: Upload endpoint → 202 Accepted

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

**Step 1: Replace the ingest_upload function**

```python
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
```

**Step 2: Commit**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "feat: upload endpoint returns 202 Accepted, defers to file watcher"
```

---

### Task 7a: Concurrency config + status counters + caption worker

This task adds pure new code — no existing functions are modified. This makes it safe to commit independently before the risky extract_and_store refactor in Task 7b.

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

**Step 1: Add imports at the top of the file**

```python
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
```

**Step 2: Add concurrency config and status tracking after existing config section**

```python
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
```

**Step 3: Add caption worker function**

```python
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
```

**Step 4: Commit**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "feat: concurrency config, status counters, caption worker function"
```

---

### Task 7b: extract_and_store refactor to use caption queue

This is the core refactor. It rewrites `extract_and_store` to use the caption queue and concurrent workers from Task 7a.

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

**Step 1: Replace the entire `extract_and_store` function with:**

```python
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
```

**Key design notes for this function:**
- `result_q` is `queue.Queue()` (not `SimpleQueue`) because `SimpleQueue.get()` does not accept a `timeout` parameter. The queue is unbounded but naturally limited by `images_queued`.
- `cancel_event.set()` is called in **two** places: the `except` block (on failure) and the timeout break (on DOC_TIMEOUT). Both prevent wasted GPU cycles on abandoned images.
- Phase 3 catches `queue.Empty` specifically (not bare `Exception`) to avoid swallowing real errors.

**Step 2: Commit**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "feat: refactor extract_and_store for caption queue with backpressure and cancellation"
```

---

### Task 8: File watcher + _process_one + lifespan + scan/status endpoints

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

**Step 1: Add _process_one function (no semaphore)**

```python
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
```

**Step 2: Add file watcher function**

```python
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
```

**Step 3: Replace the lifespan function**

```python
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
```

**Step 4: Replace the ingest_scan endpoint**

```python
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
```

**Step 5: Add status endpoint**

```python
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
```

**Step 6: Delete the old `ingestion_lock` context manager**

Remove the entire `ingestion_lock` function (the `@contextmanager` block around lines 112-125). The LOCK_FILE cleanup in lifespan stays for backward compat.

**Step 7: Update MAX_DOCS_PER_SCAN default**

Change:
```python
MAX_DOCS_PER_SCAN = int(os.getenv("MAX_DOCS_PER_SCAN", "10"))
```

**Step 8: Commit**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "feat: file watcher, concurrent doc processing, status endpoint, async scan"
```

---

### Task 9: Rebuild and smoke test

**Step 1: Rebuild pdf-ingest container (ASK BEFORE EXECUTING)**

```bash
docker compose -p ammer-mmragv2 up -d --build pdf-ingest
```

**Step 2: Restart Ollama for new PARALLEL setting (ASK BEFORE EXECUTING)**

```bash
docker compose -p ammer-mmragv2 restart ollama
```

**Step 3: Verify both services are up**

```bash
docker compose -p ammer-mmragv2 ps pdf-ingest ollama
```

**Step 4: Test status endpoint**

```bash
docker compose -p ammer-mmragv2 exec pdf-ingest curl -s http://localhost:8001/ingest/status | python3 -m json.tool
```

Expected: JSON with all zero counters, 0 inbox files, 0 errors.

**Step 5: Test health endpoint**

```bash
docker compose -p ammer-mmragv2 exec pdf-ingest curl -s http://localhost:8001/health/ready | python3 -m json.tool
```

Expected: `{"ok": true, "checks": {"db": "ok", "ollama": "ok"}}`

**Step 6: Check logs for startup messages**

```bash
docker compose -p ammer-mmragv2 logs --tail=20 pdf-ingest
```

Expected: Log lines showing "pdf-ingest v0.5.0 starting", caption workers started, watcher started.

**Step 7: Commit any hotfixes**

---

### Task 10: End-to-end watcher test

**Step 1: Drop a test PDF into inbox**

Find a small existing PDF or use one from backup:
```bash
ls data/processed/  # see what's available
```

If empty, any small PDF will do. Copy it into inbox:
```bash
cp /path/to/test.pdf data/inbox/watcher_test.pdf
```

**Step 2: Wait 25 seconds (2 watcher polls + processing start)**

```bash
sleep 25
```

**Step 3: Check status shows active processing**

```bash
docker compose -p ammer-mmragv2 exec pdf-ingest curl -s http://localhost:8001/ingest/status | python3 -m json.tool
```

Expected: `active_docs: 1` or `completed_docs: 1`

**Step 4: Wait for completion and verify DB**

```bash
docker compose -p ammer-mmragv2 exec -e PGPASSWORD='ckq7Laso/xGIIiKYPjXivtiqaxD6V/rG' postgres \
  psql -U rag_user -h localhost -d rag \
  -c "SELECT doc_id, filename, pages, created_at FROM rag_docs ORDER BY created_at DESC LIMIT 5;"
```

**Step 5: Verify file moved to processed**

```bash
ls data/inbox/        # should be empty
ls data/processed/    # should have watcher_test.pdf
ls data/error/        # should be empty
```

**Step 6: Test upload endpoint returns 202**

```bash
docker compose -p ammer-mmragv2 exec pdf-ingest curl -s -w "\nHTTP %{http_code}\n" -X POST http://localhost:8001/ingest/upload -F "file=@/kb/processed/watcher_test.pdf"
```

Expected: HTTP 202 with `{"status": "accepted", ...}`. **Note:** The watcher will pick up this file and re-process it; since it was just ingested in Steps 1-5, `should_process` will return "skipped" (SHA256 dedup match). This confirms both the upload-to-inbox flow and the dedup safety net work correctly.

---

### Task 11: Update docs and final commit

**Step 1: Update MANUAL_STEPS.md with D18 spec deviations**

Add to the deviations table:
```
D18: PDF ingestion parallelism — OLLAMA_NUM_PARALLEL=3, ThreadPoolExecutor(2) for concurrent docs,
     3 caption workers with bounded queue, batch embeddings (/api/embed, 10/batch),
     image filtering (<150px, <5KB, doc-scoped dedup), PyMuPDF shrink downscaling, auto file watcher.
D18a: /ingest/upload returns 202 Accepted and defers to file watcher (was synchronous).
D18b: /ingest/scan returns immediately after submitting to thread pool (was synchronous).
```

**Step 2: Commit**

```bash
git add MANUAL_STEPS.md
git commit -m "docs: D18 spec deviations for parallel PDF ingestion"
```
