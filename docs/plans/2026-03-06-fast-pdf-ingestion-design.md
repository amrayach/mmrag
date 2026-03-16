# Fast Parallel PDF Ingestion — Design Document

**Date:** 2026-03-06
**Status:** Approved (v4 — final, all review feedback incorporated)
**Goal:** Speed up PDF ingestion ~8-9x for bulk prep-time processing (5-10 PDFs, 100-200 pages each)

## Problem

Current PDF ingestion is fully serial: one document at a time, one Ollama call per chunk/image, one image per page sequentially. A moderate batch (500 pages) takes ~4.6 hours. This is too slow for demo prep.

### Current bottleneck breakdown (500 pages)

| Phase | Time | % of total |
|---|---|---|
| Image captioning (500 images × ~20s) | ~2.8h | 60% |
| Text embedding (4,000 chunks × 1s each) | ~1.1h | 24% |
| Junk image captioning (wasted) | ~0.5h | 11% |
| Text extraction (CPU) | ~0.1h | 2% |

## Solution: Pipeline Architecture with 6 Optimizations

### Architecture Overview

```
data/inbox/          pdf-ingest service
  ├── doc1.pdf  ──→  ┌──────────────────────────────────────────────┐
  ├── doc2.pdf  ──→  │  File Watcher (10s poll thread)              │
  └── doc3.pdf  ──→  │         │                                    │
                     │  ┌──────▼───────────────────────────┐        │
                     │  │ ThreadPoolExecutor(max_workers=2) │        │
                     │  │ (limits concurrency, queues rest) │        │
                     │  │                                   │        │
                     │  │  Doc Worker: per document          │        │
                     │  │  ├── Extract pages (CPU)           │        │
                     │  │  ├── Filter + downscale images     │        │
                     │  │  ├── Document-scoped XREF dedup    │        │
                     │  │  ├── Batch embed text (/api/embed) │        │
                     │  │  └── Enqueue images for captioning │        │
                     │  └──────────────────┬────────────────┘        │
                     │                     │                         │
                     │           caption_q (bounded, maxsize=50)     │
                     │           backpressure: blocks when full      │
                     │                     │                         │
                     │  ┌──────────────────▼────────────────────┐   │
                     │  │ 3 Caption Worker Threads               │   │
                     │  │ → Ollama vision (60s timeout each)     │   │
                     │  │ → Results via Queue per doc             │   │
                     │  │ → Checks cancelled flag on doc failure  │   │
                     │  └──────────────────┬────────────────────┘   │
                     │                     │                         │
                     │  ┌──────────────────▼────────────────────┐   │
                     │  │ DB commit (per doc, own pool connection) │  │
                     │  └──────────────────────────────────────┘   │
                     │                                               │
                     │  GET /ingest/status → queue depth, progress   │
                     └──────────────────────────────────────────────┘
```

---

## Optimization 1: Batch Embeddings

**Current:** Each text chunk → separate HTTP call to `/api/embeddings` (one at a time).
**New:** Collect all text chunks per page, send in batches of 10 to `/api/embed`.

```python
EMBED_BATCH_SIZE = 10  # Conservative: 10 chunks × ~400 tokens = ~4000 tokens
                       # Well under nomic-embed-text's 8192 token context limit

def ollama_embed_batch(texts: list) -> list:
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

**Why batch_size=10, not 20:** With `CHUNK_CHARS=1500`, each chunk is ~300-400 tokens. A batch of 20 could reach ~8,000 tokens, dangerously close to `nomic-embed-text`'s 8,192 token context limit. Batch size 10 (~4,000 tokens) provides safety margin while still eliminating ~90% of HTTP round-trips.

**Ollama compatibility:** `/api/embed` with array input available since Ollama 0.4.0. We run 0.13.0. Response format: `{"embeddings": [[...], [...]]}`.

**Impact:** 5-8x fewer HTTP calls for embedding. ~1.1h → ~0.15h.

---

## Optimization 2: Image Filtering

**Current:** All images extracted from PDF pages are captioned, including logos, icons, spacers.
**New:** Skip junk images before sending to Ollama.

Filters (matching RSS ingest approach):
- **Dimensions:** Skip images smaller than 150×150 pixels
- **File size:** Skip images smaller than 5 KB
- **Duplicates:** Track XREFs at **document scope** (not page scope), catching cross-page duplicates like headers, watermarks, and logos

```python
MIN_IMAGE_WIDTH = 150
MIN_IMAGE_HEIGHT = 150
MIN_IMAGE_BYTES = 5120  # 5 KB

# Document-scoped — catches repeated header/footer/watermark images
seen_xrefs: set[int] = set()

for pno in range(total_pages):
    page = doc.load_page(pno)
    for img in page.get_images(full=True)[:MAX_IMAGES_PER_PAGE]:
        xref = img[0]
        if xref in seen_xrefs:
            continue
        seen_xrefs.add(xref)

        base = doc.extract_image(xref)
        if base["width"] < MIN_IMAGE_WIDTH or base["height"] < MIN_IMAGE_HEIGHT:
            continue
        if len(base["image"]) < MIN_IMAGE_BYTES:
            continue
```

**Impact:** Skip 30-50% of images. ~2.8h captioning → ~1.6h.

---

## Optimization 3: Image Downscaling

**Current:** Full-resolution images (often 2000×3000px+) sent to vision model.
**New:** Downscale using PyMuPDF's `pix.shrink(n)` method (divides dimensions by 2^n).

**API verified in-container** (PyMuPDF 1.24.14):
- `fitz.Pixmap(pix, new_w, new_h)` — **does NOT work** (constructor doesn't support resize)
- `pix.shrink(n)` — **works**, in-place, divides by 2^n
- `fitz.Pixmap(fitz.csRGB, pix)` — **works** for CMYK→RGB
- `fitz.Pixmap(pix, 0)` — **works** for dropping alpha

```python
MAX_IMAGE_DIM = 1024

def downscale_image(img_bytes: bytes) -> tuple:
    """Downscale image, convert CMYK→RGB, drop alpha. Returns (jpeg_bytes, 'jpeg')."""
    pix = fitz.Pixmap(img_bytes)

    # CMYK or other non-RGB colorspace → convert to RGB
    if pix.colorspace and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)

    # Drop alpha channel
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)

    # Shrink: find smallest n where max(w,h) >> n <= MAX_IMAGE_DIM
    w, h = pix.width, pix.height
    if max(w, h) > MAX_IMAGE_DIM:
        n = 1
        while max(w, h) >> n > MAX_IMAGE_DIM and n < 4:
            n += 1
        pix.shrink(n)  # in-place, divides by 2^n

    return pix.tobytes(output="jpeg", jpg_quality=85), "jpeg"
```

**Shrink behavior for common PDF image sizes:**

| Original | shrink(n) | Result | Notes |
|---|---|---|---|
| 2000px | n=1 | 1000px | ≤ 1024, good |
| 3000px | n=2 | 750px | Below 1024, fine for captioning |
| 4000px | n=2 | 1000px | ≤ 1024, good |
| 4097px | n=2 | 1024px | Exactly at limit |
| 1500px | n=1 | 750px | Fine |
| 800px | none | 800px | No shrink needed |

**Why `>> n` not `// (2 ** (n + 1))`:** The v3 loop `while max(w,h) // (2 ** (n + 1)) > MAX_IMAGE_DIM` had an off-by-one: for 4097px it checked whether `n=2` was needed by computing `4097 // 4 = 1024 ≤ 1024` and stayed at `n=1`, giving `shrink(1) → 2048px` — still over 1024. The correct loop checks `max(w,h) >> n > MAX_IMAGE_DIM` directly: `4097 >> 1 = 2048 > 1024` → increment to `n=2`. `4097 >> 2 = 1024 ≤ 1024` → stop. `shrink(2) → 1024px`. Correct.

**Why not Pillow?** PyMuPDF's shrink + colorspace conversion handles the full chain (verified). Adding Pillow would be another dependency for marginal benefit. The approximate scaling (2^n divisor) is sufficient for generating 1-2 sentence captions.

**Impact:** 15-30% faster per image caption (fewer input tokens). ~1.6h → ~1.2h.

---

## Optimization 4: OLLAMA_NUM_PARALLEL=3

**Current:** `OLLAMA_NUM_PARALLEL=1` — one inference at a time.
**New:** `OLLAMA_NUM_PARALLEL=3` — three concurrent inferences.

Change in `docker-compose.yml`:
```yaml
OLLAMA_NUM_PARALLEL: "3"
```

**Memory analysis:** `OLLAMA_NUM_PARALLEL` applies per-model. With `OLLAMA_MAX_LOADED_MODELS=3`, this goes from 3 total KV cache slots (1 per model) to 9 total (3 per model):

| Model | Params | KV cache per slot | Slots (1→3) | Delta |
|---|---|---|---|---|
| qwen2.5vl:7b | 7B | ~0.5-0.8 GB | 1→3 | +1.0-1.6 GB |
| qwen2.5:7b-instruct | 7B | ~0.5-0.8 GB | 1→3 | +1.0-1.6 GB |
| nomic-embed-text | 137M | ~50 MB | 1→3 | +100 MB |
| **Total delta** | | | | **+2.1-3.3 GB** |

Total Ollama memory: ~11 GB (models) + ~3.3 GB (KV caches) = **~14.3 GB**. With 84 GB available → ~70 GB remaining. Safe.

**Note:** During ingestion, `qwen2.5:7b-instruct` is idle — its KV slots are wasted but acceptable.

**Impact:** 3 concurrent caption workers keep the GPU saturated. ~1.2h → ~0.5h.

---

## Optimization 5: File Watcher (Auto-Processing)

**Current:** PDFs in inbox only processed when `/ingest/scan` is triggered by n8n Ingestion Factory workflow.
**New:** Background thread polls inbox every 10 seconds, auto-submits new PDFs.

```python
def _inbox_watcher(shutdown_event, executor, process_fn):
    known: dict[str, int] = {}  # path → size at last poll
    stable: set[str] = set()    # paths already submitted

    while not shutdown_event.is_set():
        current = {p: os.path.getsize(p) for p in list_pdfs(INBOX_DIR)}

        for path, size in current.items():
            if path in stable:
                continue
            prev_size = known.get(path)
            if prev_size is not None and prev_size == size:
                stable.add(path)
                executor.submit(process_fn, path)  # queues in executor

        known = {p: s for p, s in current.items() if p not in stable}
        stable = {p for p in stable if p in current}  # clean up moved files
        shutdown_event.wait(10)
```

**File stability:** A PDF is only submitted when its size is unchanged between two consecutive polls (20s). This avoids processing partially-copied files.

**Stable set cleanup:** `stable = {p for p in stable if p in current}` removes entries for files that have been moved to `processed/` or `error/`, preventing unbounded set growth.

### Compatibility with n8n Ingestion Factory

The n8n Ingestion Factory cron (every 2 min) calls `/ingest/scan`. With the watcher active, the cron typically finds an empty inbox (watcher already picked up files). The two mechanisms are compatible — the cron acts as a fallback if the watcher misses something.

**Known limitation:** `/ingest/scan` bypasses the watcher's 20-second stability check. If a file is still being uploaded when the cron fires, it could process a partial PDF. This is unlikely in practice (FileBrowser writes are fast, cron is every 2 min) and is documented as a known limitation.

**Benign double-submit race:** If the watcher has already submitted a file but processing hasn't finished yet (file still in inbox), a concurrent `/ingest/scan` call will submit the same file to the executor again. The SHA256 dedup in `should_process` will return "skipped" for the second execution — no data corruption, just a wasted dedup check and a confusing log line. This is accepted as benign.

---

## Optimization 6: Concurrent Document Processing

**Current:** Lock file prevents any concurrent ingestion. `MAX_DOCS_PER_SCAN=1`.
**New:** `ThreadPoolExecutor(max_workers=2)` allows 2 documents to process concurrently. `MAX_DOCS_PER_SCAN=10`.

### Why no semaphore

The `ThreadPoolExecutor(max_workers=2)` already limits concurrency to 2 concurrent tasks. Any additional submissions queue in the executor's internal work queue. A separate semaphore is redundant and creates a starvation bug: if `semaphore.acquire(timeout=0)` fails, the file is already in the watcher's `stable` set and won't be resubmitted. The executor's built-in backpressure is simpler and correct.

### Upload endpoint change (prevents starvation)

The upload endpoint saves to inbox and returns `202 Accepted` immediately. The watcher picks it up within 20 seconds. No lock contention, no "busy" responses.

```python
@app.post("/ingest/upload", status_code=202)
async def ingest_upload(file: UploadFile = File(...), lang: str = "de"):
    # ... size validation, sanitize filename, write to inbox ...
    return {"status": "accepted", "filename": safe_name,
            "message": "File saved to inbox, processing will start automatically"}
```

### `/ingest/scan` endpoint semantics

Changes to async submission: submits PDFs to the executor and returns immediately with the count. No longer blocks the HTTP response.

---

## Backpressure: Bounded Caption Queue

**Problem:** CPU extraction is orders of magnitude faster than GPU captioning. Without backpressure, extracting 1,200 images queues them all in memory.

**Fix:** `queue.Queue(maxsize=50)` between extraction and captioning. When full, extraction blocks until a caption worker finishes.

**Memory cap:** 50 items × ~200 KB (downscaled JPEG) = ~10 MB max in queue.

### Caption Results via Per-Document Queue

Caption workers write results to a per-document `queue.Queue()` (unbounded). `queue.Queue` is used instead of `queue.SimpleQueue` because the doc worker needs `get(timeout=...)` for deadline-based draining during the result collection phase. `SimpleQueue.get()` does not accept a timeout parameter. The per-doc queue is naturally bounded by `images_queued` — it can never hold more results than the number of images enqueued for that document.

### Cancellation on Document Failure or Timeout

Each document carries a `threading.Event` (`cancel_event`). This event is set in two cases:

1. **Exception in extract_and_store** (e.g., during text embedding) — the `except` block sets `cancel_event`.
2. **Per-document timeout** (30 min ceiling) — set immediately before breaking out of the result collection loop.

Caption workers check this flag before processing each image, skipping work for the cancelled document to avoid wasting GPU time.

```python
# Queue item includes a cancel event
caption_q.put((doc_id, page, img_bytes, lang, asset_name, cancel_event, result_queue))

# Caption worker checks before processing:
if cancel_event.is_set():
    caption_q.task_done()
    continue
```

---

## Poison Pill PDF Handling

Failed PDFs are moved to `data/error/` and logged. This prevents crash loops on container restart (the watcher's `known` set resets, but the file is no longer in inbox).

---

## Caption Timeout / Circuit Breaker

60-second timeout per caption call. On timeout, `ollama_caption_image` catches `requests.Timeout` internally and returns `""` (empty caption). This prevents one bad image from blocking a caption worker indefinitely.

### _retry Interaction (Intentional)

The `_retry` wrapper catches `requests.RequestException` (which includes `requests.Timeout`). However, since `ollama_caption_image` handles `Timeout` internally by returning `""`, the timeout never propagates to `_retry`. This means timeouts fail fast (60s, no retry) while transient connection errors (Ollama model swapping, brief unavailability) are retried 3× with backoff. This is the correct behavior: retrying a timeout on a pathological image would waste 3 × 60s = 180s of GPU time per bad image.

### Per-Document Timeout Ceiling

In addition to per-image timeouts, a hard ceiling of **30 minutes per document**. For pathological cases (200 pages, 100 images, each taking close to 60s), the per-image deadline could exceed 100 minutes. The 30-minute ceiling catches these cases, sets `cancel_event` to purge remaining queued images, and moves on with whatever caption results were collected. Text chunks and partial image results are still committed.

---

## Status Endpoint

```python
@app.get("/ingest/status")
def ingest_status():
    return {
        "active_docs": ...,
        "completed_docs": ...,
        "failed_docs": ...,
        "completed_images": ...,
        "skipped_images": ...,
        "caption_queue_size": caption_q.qsize(),
        "caption_queue_max": CAPTION_QUEUE_SIZE,
        "inbox_files": len(list_pdfs(INBOX_DIR)),
        "error_files": ...,
    }
```

---

## Concurrency Model

```
File watcher thread ──→ ThreadPoolExecutor(max_workers=2)
                          │     (executor's internal queue handles overflow)
                          ├── Doc worker 1 ──→ extract pages
                          │     ├── batch-embed text (/api/embed, batches of 10)
                          │     └── put images → caption_q (bounded, maxsize=50)
                          └── Doc worker 2 ──→ extract pages
                                ├── batch-embed text (/api/embed, batches of 10)
                                └── put images → caption_q (bounded, maxsize=50)
                                                        │
                                          Caption workers (3 daemon threads)
                                          consume from shared caption_q
                                          60s timeout per image
                                          check cancel_event before processing
                                                        │
                                          Results via Queue per doc
                                                        │
                                          DB commit per doc (separate pool connections)
```

**Thread count:** 1 (watcher) + 2 (doc workers via executor) + 3 (caption workers) = 6 threads.

**Ollama request interleaving:** With 2 doc workers embedding + 3 caption workers captioning, up to 5 concurrent Ollama requests can occur. `OLLAMA_NUM_PARALLEL=3` means Ollama queues the excess. Embedding is fast (~100ms per batch) and rarely overlaps significantly with captioning.

**DB connection safety:** `psycopg_pool.ConnectionPool(min_size=2, max_size=4)` — each `with pool.connection()` provides an independent connection. 2 doc workers + 1 health check + 1 spare = 4 max.

---

## Graceful Shutdown

```python
shutdown_event.set()
doc_executor.shutdown(wait=False, cancel_futures=True)  # Don't block; cancel queued docs
watcher_thread.join(timeout=15)
for t in caption_threads:
    t.join(timeout=5)
pool.close()
```

**Why `wait=False, cancel_futures=True`:** With `wait=True`, shutdown blocks until the currently executing PDFs finish (potentially 15+ minutes for large docs). Docker/Uvicorn will SIGKILL the container. With `wait=False`, in-flight documents hit `extract_and_store`'s existing rollback logic — the DB transaction rolls back and orphan assets are cleaned up. `cancel_futures=True` prevents queued (not yet started) documents from beginning during shutdown, which is desirable.

---

## Memory Budget

| Component | Current | After | Delta |
|---|---|---|---|
| Ollama models (3 loaded) | ~11 GB | ~11 GB | 0 |
| KV caches (parallel 1→3, 9 total slots) | ~0.5 GB | ~3.8 GB | +3.3 GB |
| Caption queue (bounded, 50 items) | 0 | ~10 MB | +10 MB |
| pdf-ingest (2 workers + 3 caption threads) | 25 MB | ~80 MB | +55 MB |
| **Total** | **~11.5 GB** | **~14.9 GB** | **+3.4 GB** |

84 GB available → **~69 GB remaining**. Safe margin for DGX shared usage.

---

## Performance Estimates

### Moderate case: 5 PDFs × 100 pages (500 pages, ~300 images after filtering)

| Scenario | Time |
|---|---|
| Current (serial, no filtering) | ~4.6 hours |
| + batch embed (size 10) | ~3.7 hours |
| + image filter (40% skip) | ~2.3 hours |
| + image downscale | ~1.8 hours |
| + 3 concurrent captions (PARALLEL=3) | ~0.6 hours |
| + 2 concurrent docs + pipeline | **~30-35 min** |

### Worst case: 10 PDFs × 200 pages (2,000 pages, ~1,200 images after filtering)

| Scenario | Time |
|---|---|
| Current | ~18 hours |
| All optimizations | **~2-2.5 hours** |

### Speedup: ~8-9x

---

## Files Changed

| File | Change |
|---|---|
| `docker-compose.yml` | `OLLAMA_NUM_PARALLEL: "3"`, add error dir volume mount |
| `services/pdf-ingest/app/main.py` | All optimizations + concurrency refactor |

**No new Python dependencies.** PyMuPDF handles image resize + colorspace (verified in-container).

**New directory:** `data/error/` — created automatically for failed PDFs.

---

## Rollback Safety

- Deduplication (SHA256) still prevents re-ingesting unchanged documents
- Transaction rollback on failure still cleans up partial chunks + orphan asset files
- Poison pill PDFs moved to `data/error/` instead of crash-looping
- Cancel event prevents wasted GPU time on failed documents **and** timed-out documents
- File watcher gracefully shuts down via `shutdown_event`
- Upload endpoint returns 202 immediately — no processing lock
- `OLLAMA_NUM_PARALLEL` can be reverted to 1 with a compose restart
- n8n Ingestion Factory cron still works as fallback (benign double-submit handled by dedup)

---

## Spec Deviations

**D18:** PDF ingestion parallelism — `OLLAMA_NUM_PARALLEL=3`, 2 concurrent docs via ThreadPoolExecutor, 3 caption workers, batch embeddings, image filtering/downscaling, auto file watcher, bounded caption queue.

**D18a:** `/ingest/upload` returns `202 Accepted` and defers processing to watcher (was synchronous).

**D18b:** `/ingest/scan` returns immediately after submitting to thread pool (was synchronous, blocking until complete).
