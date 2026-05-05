# OpenDataLoader PDF Integration — Design

**Status:** Draft — pending user approval before implementation plan
**Date:** 2026-05-05
**Scope:** Replace PyMuPDF-based text extraction in `services/pdf-ingest` with `opendataloader-pdf` (local mode); keep PyMuPDF for image post-processing and the existing `qwen2.5vl:7b` captioning flow; introduce structure-aware chunking with bounding boxes and heading paths.

## 1. Goals & Non-Goals

### Goals
- **G1.** Improve PDF retrieval quality by feeding the chunker correct reading order (XY-Cut++) and structural element types instead of PyMuPDF's flat per-page text dump. Multi-column German annual/sustainability reports are the target.
- **G2.** Capture per-chunk bounding boxes, page sizes, and heading paths in `rag_chunks.meta` so a future "click-to-source" UI in the Control Center can render PDF highlights without re-parsing.

### Non-goals
- Building the click-to-source UI itself (data only, this round).
- Enabling opendataloader's hybrid mode (docling/AI backend on a separate port). Local mode only; hybrid is a future upgrade gated behind one env flag.
- Replacing the embedding model (`bge-m3`, 1024d) or vision model (`qwen2.5vl:7b`). Both stay.
- Replacing the text-generation model. That is `rag-gateway`'s concern, not `pdf-ingest`'s.
- Building OCR support. Demo PDFs are digital, not scanned.
- Tagging PDFs (the accessibility/PDF-UA pipeline). We extract from existing PDFs only.

## 2. Architecture & Data Flow

```
inbox/foo.pdf
    │
    ▼
[pdf-ingest container]
    │
    ▼
┌──────────────────────────────────────────────┐
│  Step 1 — extractor.parse(pdf_path)           │
│   • Acquire OPENDATALOADER semaphore         │
│   • opendataloader_pdf.convert(...)          │
│       output_dir = /tmp/odl/<doc_id>/        │
│       format    = "json"                     │
│       image_output = "external"              │
│       reading_order = "xycut"                │
│       use_struct_tree = True                 │
│   • Read /tmp/odl/<doc_id>/<stem>.json       │
│   • Recursively flatten `kids` tree          │
│   • Normalize element types via map          │
│   • Return List[ParsedElement]               │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│  Step 2 — layout_to_chunks(elements)          │
│   • Group consecutive text elements under    │
│     the active heading path → SectionChunk   │
│   • Each section is bound to ONE page        │
│     (split at page boundary)                 │
│   • Tables → TableChunk (markdown rendered)  │
│   • Pictures → ImageChunk (path + bbox)      │
│   • Soft cap CHUNK_CHARS (1500); fallback to │
│     row_groups for tables, sentence_fallback │
│     for huge paragraphs                      │
│   • Prefix every text/table chunk with a     │
│     heading-path breadcrumb in the embedded  │
│     content                                  │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│  Step 3 — embed + persist (existing pipeline)│
│   • ollama_embed_batch(text+table chunks)    │
│   • Enqueue ImageChunks for caption workers  │
│     (queue tuple now carries meta_extra)     │
│   • _caption_worker captions + embeds        │
│   • insert_chunk(...) for all chunk types    │
│     meta merges meta_extra                    │
└──────────────────────────────────────────────┘
    │
    ▼
move /kb/inbox/foo.pdf → /kb/processed/foo.pdf
```

### Files Touched
| File | Change |
|---|---|
| `services/pdf-ingest/app/extractor.py` | NEW — `parse(pdf_path) -> list[ParsedElement]` and `layout_to_chunks(elements) -> list[Chunk]` |
| `services/pdf-ingest/app/main.py` | `extract_and_store()` calls extractor instead of iterating fitz pages; caption queue tuple extended; `_should_skip_external_image()` added; Java-version startup check |
| `services/pdf-ingest/requirements.txt` | Add `opendataloader-pdf==2.4.1`, `Pillow==10.4.0` (already an indirect dep but pin explicitly for our hash dedup) |
| `services/pdf-ingest/Dockerfile` | Add `openjdk-17-jre-headless=<pinned>` install; digest-pin base `python:3.11-slim-bookworm` |
| `docker-compose.yml` | Add `OPENDATALOADER_MAX_PARALLEL`, `OPENDATALOADER_TIMEOUT`, `OPENDATALOADER_TMP_DIR` env vars (with safe defaults); healthcheck stays on `/health` |
| `scripts/reprocess_pdfs.sh` | NEW — gated reprocess flow (snapshot, status check, chunk delete, asset cleanup, move-to-inbox) |
| `scripts/demo_readiness_check.sh` | Extended check #16 (Java present + `meta ? 'bbox'` chunks exist) |
| `MANUAL_STEPS.md` | New deviation D24 |
| `tests/fixtures/sample_layout.json` | NEW — adapter unit-test fixture |
| `services/pdf-ingest/tests/test_extractor.py` | NEW — adapter unit tests |

PyMuPDF (`fitz`) stays as a dependency: still used for `downscale_image()` (CMYK→RGB conversion, alpha drop, pixmap shrink), and for reading external image dimensions in the new size filter.

## 3. Adapter Contract — `extractor.py`

### 3.1 `parse(pdf_path) -> list[ParsedElement]`

```python
@dataclass
class ParsedElement:
    element_type: str          # "heading" | "text" | "table" | "list" | "image" | "caption"
    page: int                  # 1-indexed
    bbox: tuple[float, float, float, float]  # (left, bottom, right, top), pdf points
    page_size: tuple[float, float]            # (width, height), pdf points
    content: str | None        # Markdown text for text/table/list/heading; None for image
    image_path: str | None     # absolute path on disk for image elements
    heading_level: int | None  # 1..6 for headings, else None
    raw_id: int | None         # opendataloader element id, for traceability
```

#### Pseudocode

```python
import json, os, subprocess, tempfile, threading
from pathlib import Path
import opendataloader_pdf

OPENDATALOADER_SEMAPHORE = threading.Semaphore(
    int(os.getenv("OPENDATALOADER_MAX_PARALLEL", "1"))
)
OPENDATALOADER_TIMEOUT = int(os.getenv("OPENDATALOADER_TIMEOUT", "300"))
OPENDATALOADER_TMP = os.getenv("OPENDATALOADER_TMP_DIR", "/tmp/odl")

ELEMENT_TYPE_MAP = {
    # images (handle both observed and documented variants)
    "image": "image", "picture": "image",
    "png": "image", "jpeg": "image", "jpg": "image",
    # tables
    "table": "table",
    # headings
    "heading": "heading", "title": "heading", "h": "heading",
    "h1": "heading", "h2": "heading", "h3": "heading",
    "h4": "heading", "h5": "heading", "h6": "heading",
    # text-like
    "paragraph": "text", "text": "text", "p": "text", "textbox": "text",
    # lists
    "list": "list", "ul": "list", "ol": "list", "li": "text",
    # structural noise
    "header": "_skip", "footer": "_skip",
    "caption": "caption",
    # page wrapper — used to harvest page_size, then descended
    "page": "_page",
}

def _normalize_type(raw: str) -> str:
    return ELEMENT_TYPE_MAP.get((raw or "").lower(), "text")

def _bbox(node) -> tuple[float, float, float, float] | None:
    bb = node.get("bounding box")
    if not bb or len(bb) != 4:
        return None
    return tuple(float(x) for x in bb)

def parse(pdf_path: str) -> list[ParsedElement]:
    stem = Path(pdf_path).stem
    out_dir = Path(OPENDATALOADER_TMP) / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    with OPENDATALOADER_SEMAPHORE:
        # convert() returns None; output goes to <out_dir>/<stem>.json + <out_dir>/images/...
        opendataloader_pdf.convert(
            input_path=pdf_path,
            output_dir=str(out_dir),
            format="json",
            image_output="external",
            image_format="png",
            reading_order="xycut",
            use_struct_tree=True,
            sanitize=False,            # do NOT redact emails/phones/URLs — we want full content
            content_safety_off=None,   # leave hidden/off-page/tiny filters ON (prompt-injection defense)
            quiet=True,
        )

    json_path = out_dir / f"{stem}.json"
    if not json_path.exists():
        raise FileNotFoundError(f"opendataloader produced no JSON at {json_path}")
    doc = json.loads(json_path.read_text(encoding="utf-8"))

    # Walk the recursive `kids` tree depth-first, preserving reading order
    elements: list[ParsedElement] = []
    current_page = 1
    current_page_size = (612.0, 792.0)  # US Letter fallback

    def walk(node):
        nonlocal current_page, current_page_size
        norm = _normalize_type(node.get("type", ""))
        page = int(node.get("page number") or current_page)

        if norm == "_page":
            current_page = page
            bb = _bbox(node)
            if bb:
                current_page_size = (bb[2] - bb[0], bb[3] - bb[1])
            for kid in node.get("kids") or []:
                walk(kid)
            return

        if norm == "_skip":
            return  # opendataloader filters these by default; double-guard

        bbox = _bbox(node) or (0.0, 0.0, 0.0, 0.0)

        if norm == "image":
            elements.append(ParsedElement(
                element_type="image",
                page=page,
                bbox=bbox,
                page_size=current_page_size,
                content=None,
                image_path=node.get("source") or node.get("path"),
                heading_level=None,
                raw_id=node.get("id"),
            ))
            return

        if norm == "table":
            content = _render_table_markdown(node)  # walk kids recursively
            elements.append(ParsedElement(
                element_type="table",
                page=page,
                bbox=bbox,
                page_size=current_page_size,
                content=content,
                image_path=None,
                heading_level=None,
                raw_id=node.get("id"),
            ))
            return

        if norm == "heading":
            # `heading level` field, then `level`, then trailing digit on type ("h2" → 2)
            raw_type = (node.get("type") or "").lower()
            digit_suffix = next((c for c in raw_type if c.isdigit()), None)
            level = (node.get("heading level")
                     or node.get("level")
                     or (int(digit_suffix) if digit_suffix else 1))
            elements.append(ParsedElement(
                element_type="heading",
                page=page,
                bbox=bbox,
                page_size=current_page_size,
                content=(node.get("content") or "").strip(),
                image_path=None,
                heading_level=int(level),
                raw_id=node.get("id"),
            ))
            for kid in node.get("kids") or []:
                walk(kid)
            return

        # text / list / caption — collect content if present, then descend
        text = (node.get("content") or "").strip()
        if text:
            elements.append(ParsedElement(
                element_type=norm if norm != "caption" else "text",
                page=page,
                bbox=bbox,
                page_size=current_page_size,
                content=text,
                image_path=None,
                heading_level=None,
                raw_id=node.get("id"),
            ))
        for kid in node.get("kids") or []:
            walk(kid)

    for kid in doc.get("kids") or []:
        walk(kid)

    return elements
```

### 3.2 `layout_to_chunks(elements) -> list[Chunk]`

```python
@dataclass
class Chunk:
    chunk_type: str              # "text" | "image"
    page: int
    content_text: str | None     # text/table content (with heading breadcrumb prefix)
    caption: str | None          # set by caption worker for images, None at chunk-time
    asset_path: str | None       # filename relative to ASSETS_DIR
    image_bytes: bytes | None    # only for image chunks, consumed by caption queue
    meta: dict                   # {bbox, bbox_units, bbox_order, page_size, element_type,
                                  #  element_ids, heading_path, split_strategy, extractor}
```

Algorithm:

```python
def layout_to_chunks(elements: list[ParsedElement]) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []  # (level, text)
    section: list[ParsedElement] = []          # accumulating text-like elements
    section_page: int | None = None

    def flush_section(reason: str = "size"):
        nonlocal section, section_page
        if not section:
            return
        breadcrumb = " › ".join(t for _, t in heading_stack)
        body = "\n\n".join(e.content for e in section if e.content)
        prefix = f"{breadcrumb}\n\n" if breadcrumb else ""
        # If reason == "page_continuation", append (Forts.) marker
        if reason == "page_continuation" and breadcrumb:
            prefix = f"{breadcrumb} (Forts.)\n\n"
        text = prefix + body
        union_bbox = _union_bbox([e.bbox for e in section])
        chunks.append(Chunk(
            chunk_type="text",
            page=section_page,
            content_text=text,
            caption=None,
            asset_path=None,
            image_bytes=None,
            meta={
                "source": "pdf_text",
                "page": section_page,
                "element_type": "section",
                "element_ids": [e.raw_id for e in section if e.raw_id is not None],
                "heading_path": [t for _, t in heading_stack],
                "bbox": list(union_bbox),
                "bbox_units": "pdf_points",
                "bbox_order": "left,bottom,right,top",
                "page_size": list(section[0].page_size),
                "split_strategy": reason,
                "extractor": "opendataloader-pdf@2.4.1",
            },
        ))
        section = []
        section_page = None

    for el in elements:
        # Page change → flush before continuing on the new page
        if section and el.page != section_page:
            flush_section(reason="page_continuation")

        if el.element_type == "heading":
            flush_section()
            level = el.heading_level or 1
            # Pop deeper-or-equal-level entries before pushing
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, el.content))
            # Heading itself is folded into the next section's breadcrumb;
            # we do NOT emit a heading-only chunk.
            continue

        if el.element_type == "image":
            flush_section()
            chunks.append(_make_image_chunk(el, heading_stack))
            continue

        if el.element_type == "table":
            flush_section()
            chunks.extend(_make_table_chunks(el, heading_stack))
            continue

        # text / list
        if not el.content:
            continue
        prospective = sum(len(e.content or "") for e in section) + len(el.content)
        if prospective > CHUNK_CHARS and section:
            flush_section()
        section.append(el)
        section_page = el.page

    flush_section()
    return chunks
```

### 3.3 Table Splitting (`_make_table_chunks`)

`_render_table_markdown(node)`, `_parse_md_table(md)`, and `_table_chunk(...)` are private helpers in `extractor.py`. The first walks a `table` node's `kids` (rows → cells) and emits a GitHub-flavored Markdown table; the second is its inverse for re-splitting; the third is a small constructor mirroring the section-flush logic with `element_type="table"`. They are noted here for shape only — exact implementation lives in the file.


```python
TABLE_HARD_LIMIT = 4 * CHUNK_CHARS  # 6000 chars

def _make_table_chunks(el, heading_stack):
    md = el.content  # already markdown-rendered table
    breadcrumb = " › ".join(t for _, t in heading_stack)
    prefix = f"{breadcrumb}\n\n" if breadcrumb else ""

    if len(prefix + md) <= TABLE_HARD_LIMIT:
        return [_table_chunk(el, heading_stack, prefix + md, "intact")]

    # Row-group split: keep header row, group rows until each chunk fits
    header, rows = _parse_md_table(md)
    if not rows:
        # Single-row table that's still too big — fall back to sentence splitter
        from .splitter import split_text
        parts = split_text(md, CHUNK_CHARS, CHUNK_OVERLAP)
        return [
            _table_chunk(el, heading_stack, prefix + p, "sentence_fallback")
            for p in parts
        ]

    chunks = []
    bucket = [header]
    bucket_len = len(prefix) + len(header)
    for row in rows:
        if bucket_len + len(row) > TABLE_HARD_LIMIT and len(bucket) > 1:
            chunks.append(_table_chunk(el, heading_stack,
                                       prefix + "\n".join(bucket),
                                       "row_groups"))
            bucket = [header, row]  # repeat header on continuation
            bucket_len = len(prefix) + len(header) + len(row)
        else:
            bucket.append(row)
            bucket_len += len(row)
    if len(bucket) > 1:
        chunks.append(_table_chunk(el, heading_stack,
                                   prefix + "\n".join(bucket),
                                   "row_groups"))
    return chunks
```

### 3.4 Heading-Path Breadcrumb Format

- Single line, separator ` › ` (U+203A), e.g. `1. Strategie › 1.2 Nachhaltigkeit`.
- Followed by a blank line, then chunk body.
- Page continuations append ` (Forts.)` to the breadcrumb (German "Fortsetzung" — matches the project's German UX).
- The breadcrumb is part of `content_text` AND the embedded text, so retrieval can match on heading keywords.

## 4. Image Handling

### 4.1 Flow

1. opendataloader writes images to `/tmp/odl/<stem>/images/*.png`.
2. For each `ParsedElement(element_type="image")`:
   a. Run `_should_skip_external_image(image_path)` filter.
   b. Run existing `downscale_image()` on the file bytes.
   c. Save to `ASSETS_DIR/<doc_id>_p<page>_i<idx>.<ext>` (existing naming preserved).
   d. Hash file bytes (SHA-256); if hash already seen for this doc, skip captioning (dedup).
   e. Enqueue tuple onto `caption_q`.
3. Caption worker captions + embeds; result tuple flows back with `meta_extra`.
4. Main thread inserts the image chunk, merging `meta_extra` into the meta dict.

### 4.2 New External-Image Filter

```python
def _should_skip_external_image(path: str, seen_hashes: set[str]) -> tuple[bool, str | None]:
    """Returns (skip, sha256_or_None). When skip=True, sha256 may be None."""
    if not os.path.isfile(path):
        return True, None
    size = os.path.getsize(path)
    if size < MIN_IMAGE_BYTES:
        return True, None
    try:
        pix = fitz.Pixmap(path)
    except Exception:
        return True, None
    if pix.width < MIN_IMAGE_WIDTH or pix.height < MIN_IMAGE_HEIGHT:
        return True, None
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if sha in seen_hashes:
        return True, sha
    return False, sha
```

The `seen_hashes` set is per-document (lives on the call stack in `extract_and_store`), matching today's per-document `seen_xrefs` semantics.

### 4.3 Caption Queue Shape Change

Today:
```python
# queue:  (doc_id, page, im_i, img_bytes, lang, asset_name, cancel_event, result_q)
# result: (page, im_i, caption, asset_name, emb)
```

After:
```python
# queue:  (doc_id, page, im_i, img_bytes, lang, asset_name, meta_extra, cancel_event, result_q)
# result: (page, im_i, caption, asset_name, emb, meta_extra)
```

Where `meta_extra` is built once at enqueue time:
```python
{
  "bbox": [...], "bbox_units": "pdf_points", "bbox_order": "left,bottom,right,top",
  "page_size": [...], "heading_path": [...], "element_id": ...,
  "extractor": "opendataloader-pdf@2.4.1",
  "image_sha256": "...",
}
```

Insert at `extract_and_store()`:
```python
insert_chunk(cur, doc_id, "image", page_no, None, caption, asset_name, emb,
             {"source": "pdf_image", "page": page_no, "image_index": im_i, **meta_extra})
```

## 5. Database

### 5.1 Schema — No Migration

`db/init/010_rag_schema.sql` already declares `meta JSONB`. New keys are additive.

### 5.2 New `meta` Keys (per chunk)

| Key | Type | Notes |
|---|---|---|
| `source` | string | unchanged: `"pdf_text"` \| `"pdf_image"` |
| `page` | int | unchanged |
| `image_index` | int | image chunks only — order of image on the page |
| `element_type` | string | `"section"` \| `"table"` \| `"image"` |
| `element_ids` | list[int] | opendataloader source ids (multiple for merged sections) |
| `heading_path` | list[string] | e.g. `["1. Strategie", "1.2 Nachhaltigkeit"]` |
| `bbox` | list[float] | 4 floats |
| `bbox_units` | string | constant `"pdf_points"` |
| `bbox_order` | string | constant `"left,bottom,right,top"` |
| `page_size` | list[float] | `[width_pt, height_pt]` |
| `split_strategy` | string | `"size"` \| `"page_continuation"` \| `"intact"` \| `"row_groups"` \| `"sentence_fallback"` |
| `image_sha256` | string | image chunks only — for global dedup |
| `extractor` | string | `"opendataloader-pdf@2.4.1"` (or `"pymupdf-fallback"` on degraded path) |

Existing retrieval queries in `services/rag-gateway/app/context.py` are unaffected — they read `chunk_type`, `page`, `content_text`, `caption`, `asset_path`, `meta.feed_name`, `meta.url`, `meta.title`, `meta.content_type`. The new keys are extra.

## 6. Container & Java

### 6.1 Dockerfile

```dockerfile
FROM python:3.11-slim-bookworm@sha256:<digest-to-pin>

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    openjdk-17-jre-headless=<exact-bookworm-version> \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

The exact digest and JRE version are determined during the implementation step (run once locally, pin the result). Both pins land in the same commit.

### 6.2 Startup Java Check

In `lifespan()` before `yield`:
```python
try:
    subprocess.run(["java", "-version"], check=True, capture_output=True, timeout=5)
    logger.info("Java runtime verified")
except Exception as e:
    logger.error("Java runtime not available: %s", e)
    raise RuntimeError("Java 11+ required for opendataloader-pdf") from e
```

Fail-fast at container startup; the container won't reach ready state without Java. Compose's healthcheck on `/health` continues to mean "process is alive".

### 6.3 Docker Compose Env Vars

Added to `pdf-ingest` service in `docker-compose.yml`:
```yaml
OPENDATALOADER_MAX_PARALLEL: "1"
OPENDATALOADER_TIMEOUT: "300"
OPENDATALOADER_TMP_DIR: "/tmp/odl"
```

## 7. Re-processing the 4 Demo PDFs

### 7.1 Why

Existing chunks were produced by 1500-char sliding window over PyMuPDF text. New chunks are section-based with breadcrumbs and bounding boxes. Mixing both for the same `doc_id` confuses retrieval (duplicate near-identical text, conflicting metadata semantics). One-time, controlled re-processing brings the demo corpus onto the new pipeline.

### 7.2 `scripts/reprocess_pdfs.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--confirm" ]]; then
  echo "Refusing to run without --confirm. This deletes chunks + assets for all processed PDFs."
  exit 1
fi

# 1. Active-work guard
status=$(curl -sf http://127.0.0.1:8001/ingest/status)
active=$(echo "$status" | jq '.active_docs')
qsize=$(echo "$status" | jq '.caption_queue_size')
if [[ "$active" -gt 0 || "$qsize" -gt 0 ]]; then
  echo "Refusing — active_docs=$active caption_queue_size=$qsize"
  exit 1
fi

# 2. Timestamped snapshot
ts=$(date +%Y%m%d_%H%M%S)
snap="data/demo_snapshot_pre_opendataloader_${ts}.sql"
docker compose exec -T postgres pg_dump -U rag_user rag > "$snap"
test -s "$snap" || { echo "Snapshot empty — abort"; exit 1; }

# 3. Identify doc_ids to drop, then chunk + asset cleanup
doc_ids=$(docker compose exec -T postgres psql -U rag_user -d rag -At -c \
  "SELECT doc_id FROM rag_docs WHERE doc_id NOT IN (
     SELECT DISTINCT doc_id FROM rag_chunks
     WHERE meta->>'content_type' = 'rss_article'
   );")

for did in $doc_ids; do
  docker compose exec -T postgres psql -U rag_user -d rag -c \
    "DELETE FROM rag_chunks WHERE doc_id='$did';"
  docker compose exec -T pdf-ingest find /kb/assets -maxdepth 1 \
    -name "${did}_p*_i*.*" -delete || true
done
docker compose exec -T postgres psql -U rag_user -d rag -c \
  "DELETE FROM rag_docs WHERE doc_id NOT IN (
     SELECT DISTINCT doc_id FROM rag_chunks
   );"

# 4. Move processed PDFs back to inbox; watcher will pick them up
mv data/processed/*.pdf data/inbox/ 2>/dev/null || true
echo "Done. Watch logs: docker compose logs -f pdf-ingest"
```

### 7.3 Order of Operations on the Day

1. Ensure pdf-ingest is healthy and idle.
2. Build new pdf-ingest image.
3. `docker compose up -d pdf-ingest`.
4. Wait for `/health/ready` → `{"ok": true}`.
5. `bash scripts/reprocess_pdfs.sh --confirm`.
6. Watch logs; verify completion via `/ingest/status` (`active_docs=0`, `completed_docs=4`).
7. Run `scripts/demo_readiness_check.sh`.

## 8. Error Handling

| Failure | Behavior |
|---|---|
| `java` missing at startup | `lifespan()` raises; container restart loop with clear log |
| `opendataloader_pdf.convert` raises | Catch in `extract_and_store`; log; fall back to current PyMuPDF flow for this file; flag `meta.extractor = "pymupdf-fallback"` |
| `convert` produces no JSON file | Same fallback path; log warning |
| JSON has unexpected element types | Map to `"text"` and log unknown type once per ingest |
| Section chunking produces zero chunks | Fall back to per-page text + sentence splitter (current behavior) |
| Caption worker failure | Unchanged — empty caption, no embedding, image still inserted |
| Reprocess script: snapshot empty | Abort before any DELETE |
| Reprocess script: ingestion in progress | Abort before any DELETE |

The fallback path is the safety net: even if opendataloader breaks (a JVM crash, a malformed PDF, a parser regression), the file still ingests via the legacy code with `extractor: "pymupdf-fallback"` so we can grep for them.

## 9. Testing

### 9.1 Unit Tests (`services/pdf-ingest/tests/test_extractor.py`)

- `test_walks_kids_tree` — fixture JSON with nested `kids`, asserts flattening preserves reading order.
- `test_normalizes_image_types` — same element with `type="image"`, `"picture"`, `"png"`, `"jpeg"` all map to `element_type="image"`.
- `test_field_names_with_spaces` — fixture uses `"page number"` and `"bounding box"`; adapter reads them correctly.
- `test_section_breadcrumb_prefix` — heading path prepended to chunk text.
- `test_section_splits_at_page_boundary` — section spanning pages 1–2 produces 2 chunks, second has `(Forts.)`.
- `test_size_split_falls_back_to_sentence_splitter` — single huge paragraph triggers `split_strategy="sentence_fallback"`.
- `test_table_intact` — small table stays as one chunk, `split_strategy="intact"`.
- `test_table_row_groups` — large table splits, header repeats on each chunk.
- `test_skip_image_too_small` — external image below threshold is skipped.
- `test_skip_image_dedup` — same SHA-256 within a doc is skipped after the first.

Fixture: `tests/fixtures/sample_layout.json` — hand-crafted minimal opendataloader output covering all element types.

### 9.2 Integration

- Build the new image.
- Run on `data/processed/watcher_test.pdf` (the smallest demo file). Verify:
  - At least one chunk has `meta.bbox` set.
  - At least one chunk has non-empty `meta.heading_path`.
  - Image chunks still have valid captions and embeddings.
- Run a known demo prompt (`@TechVision Welche Risiken nennt der Bericht?`) and eyeball the answer quality vs the pre-snapshot baseline.

### 9.3 Demo Readiness Check #16

Append to `scripts/demo_readiness_check.sh`:
```bash
echo "Check #16 — opendataloader integration"
docker compose exec -T pdf-ingest java -version >/dev/null 2>&1 \
  && echo "  ✓ Java present" || echo "  ✗ Java missing"
bbox_count=$(docker compose exec -T postgres psql -U rag_user -d rag -At -c \
  "SELECT count(*) FROM rag_chunks WHERE meta ? 'bbox';")
[[ "$bbox_count" -gt 0 ]] \
  && echo "  ✓ $bbox_count chunks have meta.bbox" \
  || echo "  ✗ no chunks have meta.bbox"
```

## 10. Rollout & Rollback

### Rollout
1. PR with all changes (extractor, Dockerfile, compose env, scripts, tests).
2. Merge during a quiet window — mid-week, not before Sven's demo.
3. Build + restart pdf-ingest only (no other services touched).
4. Run reprocess script.
5. Run readiness check.
6. Smoke test the 4 known demo prompts.

### Rollback
- Keep `data/demo_snapshot_pre_opendataloader_<ts>.sql` for at least one demo cycle.
- To revert: `git revert`, rebuild pdf-ingest, restore snapshot via `psql < snapshot.sql`, move PDFs back to `processed/`.

## 11. Out of Scope (Future Work)

- Hybrid mode (`hybrid="docling-fast"`) for higher table accuracy on borderless / scanned tables. Adds a docling sidecar service. Defer until local-mode quality is judged insufficient on the demo prompts.
- Click-to-source UI in Control Center using the stored `bbox` + `page` + `page_size`. Data is now there; UI is a follow-up.
- Tagged-PDF generation (the accessibility add-on). Different problem.
- Replacing the qwen2.5vl:7b captioning step with opendataloader's hybrid SmolVLM picture descriptions. Would regress quality.

## 12. Deviation Record

Append to `MANUAL_STEPS.md`:

> **D24** — PDF text/image extraction switched from PyMuPDF to opendataloader-pdf 2.4.1 (local mode, OpenJDK 17 JRE in pdf-ingest container). Section-based chunking with heading-path breadcrumbs replaces the 1500-char sliding window. Bounding boxes, page sizes, heading paths, element ids, and split-strategy provenance are stored in `rag_chunks.meta` (JSONB; no schema migration). PyMuPDF retained for `downscale_image()` and external-image dimension reads. Re-processing of all four demo PDFs performed via `scripts/reprocess_pdfs.sh --confirm` after `data/demo_snapshot_pre_opendataloader_<ts>.sql` snapshot. Embedding model (`bge-m3`, 1024d) and vision model (`qwen2.5vl:7b`) unchanged.
