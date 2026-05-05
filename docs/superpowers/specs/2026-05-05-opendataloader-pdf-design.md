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
│  Step 1 — extractor.parse(pdf_path, doc_id)   │
│   • out_dir = mkdtemp(prefix=doc_id+"_",     │
│                       dir=OPENDATALOADER_TMP)│
│   • Open pdf_path with fitz to harvest       │
│     per-page sizes (PyMuPDF Rect.width/.height)│
│   • Acquire OPENDATALOADER semaphore         │
│   • subprocess.run(["java","-jar",JAR_PATH,  │
│       *cli_args], timeout=...)               │
│   • Read out_dir/<stem>.json                 │
│   • DFS the kids tree; for tables walk        │
│     rows→cells; for lists walk list items;   │
│     normalize types; resolve image source    │
│     paths via os.path.join(out_dir, source)  │
│   • Return (List[ParsedElement], out_dir)    │
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

### 3.1 `parse(pdf_path, doc_id) -> tuple[list[ParsedElement], str]`

Returns the flattened element list AND the temp `out_dir` (caller is responsible for cleanup once images have been copied to `ASSETS_DIR`).

```python
@dataclass
class ParsedElement:
    element_type: str          # "heading" | "text" | "table" | "list" | "image" | "caption"
    page: int                  # 1-indexed
    bbox: tuple[float, float, float, float]  # (left, bottom, right, top), pdf points
    page_size: tuple[float, float]            # (width, height), pdf points (from PyMuPDF)
    content: str | None        # Markdown text for text/table/list/heading; None for image
    image_path: str | None     # absolute path on disk for image elements
    heading_level: int | None  # 1..6 for headings, else None
    raw_id: int | None         # opendataloader element id, for traceability
```

#### Pseudocode

```python
import json, os, subprocess, tempfile, threading
from importlib.resources import files
from pathlib import Path
import fitz  # PyMuPDF, already a dep

OPENDATALOADER_SEMAPHORE = threading.Semaphore(
    int(os.getenv("OPENDATALOADER_MAX_PARALLEL", "1"))
)
OPENDATALOADER_TIMEOUT = int(os.getenv("OPENDATALOADER_TIMEOUT", "300"))
OPENDATALOADER_TMP = os.getenv("OPENDATALOADER_TMP_DIR", "/tmp/odl")
JAR_PATH = str(files("opendataloader_pdf").joinpath("jar", "opendataloader-pdf-cli.jar"))
JAVA_OPTS = os.getenv("OPENDATALOADER_JAVA_OPTS", "-Xmx2g").split()

ELEMENT_TYPE_MAP = {
    # images — schema canonically uses "image"; png/jpeg/picture handled defensively
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
    # lists — schema fields below ("list items", "items") drive traversal, type just classifies
    "list": "list", "ul": "list", "ol": "list",
    "list item": "text", "li": "text",
    # structural noise (opendataloader filters by default; double-guard)
    "header": "_skip", "footer": "_skip", "table row": "_skip", "table cell": "_skip",
    "caption": "caption",
}

def _normalize_type(raw: str) -> str:
    return ELEMENT_TYPE_MAP.get((raw or "").lower(), "text")

def _bbox(node) -> tuple[float, float, float, float] | None:
    bb = node.get("bounding box")
    if not bb or len(bb) != 4:
        return None
    return tuple(float(x) for x in bb)

def _harvest_page_sizes(pdf_path: str) -> dict[int, tuple[float, float]]:
    """Read page dimensions from PyMuPDF — schema does not expose them."""
    sizes: dict[int, tuple[float, float]] = {}
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            r = doc.load_page(i).rect
            sizes[i + 1] = (float(r.width), float(r.height))
    return sizes

def _run_opendataloader(pdf_path: str, out_dir: str) -> None:
    """Invoke the bundled JAR directly so we get a real subprocess timeout."""
    args = [
        "java", *JAVA_OPTS, "-jar", JAR_PATH,
        pdf_path,
        "--output-dir", out_dir,
        "--format", "json",
        "--image-output", "external",
        "--image-format", "png",
        "--reading-order", "xycut",
        "--use-struct-tree",
        "--quiet",
        # sanitize=False (default) — keep emails/phones/URLs in content
        # content-safety-off=None (default) — keep hidden/off-page filtering ON
    ]
    subprocess.run(args, check=True, timeout=OPENDATALOADER_TIMEOUT,
                   capture_output=True, text=True)

def parse(pdf_path: str, doc_id: str) -> tuple[list[ParsedElement], str]:
    os.makedirs(OPENDATALOADER_TMP, exist_ok=True)
    out_dir = tempfile.mkdtemp(prefix=f"{doc_id}_", dir=OPENDATALOADER_TMP)
    page_sizes = _harvest_page_sizes(pdf_path)

    with OPENDATALOADER_SEMAPHORE:
        _run_opendataloader(pdf_path, out_dir)

    stem = Path(pdf_path).stem
    json_path = Path(out_dir) / f"{stem}.json"
    if not json_path.exists():
        raise FileNotFoundError(f"opendataloader produced no JSON at {json_path}")
    doc = json.loads(json_path.read_text(encoding="utf-8"))

    elements: list[ParsedElement] = []

    def page_size_for(p: int) -> tuple[float, float]:
        return page_sizes.get(p, (612.0, 792.0))

    def walk(node):
        norm = _normalize_type(node.get("type", ""))
        if norm == "_skip":
            return
        page = int(node.get("page number") or 1)
        bbox = _bbox(node) or (0.0, 0.0, 0.0, 0.0)

        if norm == "image":
            rel = node.get("source")
            img_path = os.path.join(out_dir, rel) if rel else None
            elements.append(ParsedElement(
                element_type="image", page=page, bbox=bbox,
                page_size=page_size_for(page),
                content=None, image_path=img_path,
                heading_level=None, raw_id=node.get("id"),
            ))
            return

        if norm == "table":
            content = _render_table_markdown(node)  # walks rows→cells, NOT kids
            elements.append(ParsedElement(
                element_type="table", page=page, bbox=bbox,
                page_size=page_size_for(page),
                content=content, image_path=None,
                heading_level=None, raw_id=node.get("id"),
            ))
            return

        if norm == "list":
            content = _render_list_markdown(node)  # walks "list items" / "items"
            elements.append(ParsedElement(
                element_type="list", page=page, bbox=bbox,
                page_size=page_size_for(page),
                content=content, image_path=None,
                heading_level=None, raw_id=node.get("id"),
            ))
            return

        if norm == "heading":
            raw_type = (node.get("type") or "").lower()
            digit_suffix = next((c for c in raw_type if c.isdigit()), None)
            level = (node.get("heading level")
                     or node.get("level")
                     or (int(digit_suffix) if digit_suffix else 1))
            elements.append(ParsedElement(
                element_type="heading", page=page, bbox=bbox,
                page_size=page_size_for(page),
                content=(node.get("content") or "").strip(),
                image_path=None, heading_level=int(level),
                raw_id=node.get("id"),
            ))
            for kid in node.get("kids") or []:
                walk(kid)
            return

        # text / caption / unknown — emit content if present, then descend
        text = (node.get("content") or "").strip()
        if text:
            elements.append(ParsedElement(
                element_type="text", page=page, bbox=bbox,
                page_size=page_size_for(page),
                content=text, image_path=None,
                heading_level=None, raw_id=node.get("id"),
            ))
        for kid in node.get("kids") or []:
            walk(kid)

    for kid in doc.get("kids") or []:
        walk(kid)

    return elements, out_dir
```

#### Text-collection helper (`_collect_text`)

Schema (`$defs/tableCell`, `$defs/listItem`) makes `kids` required and does **not** define a direct `content` field on cells or list items. Cell/item text lives in nested `kids` (paragraphs, runs, sometimes nested lists). `_collect_text` walks the subtree DFS and concatenates whatever leaf-level `content` strings it finds:

```python
def _collect_text(node) -> str:
    """Recursively gather visible text from a node's content + descendants."""
    if not isinstance(node, dict):
        return ""
    parts: list[str] = []
    if isinstance(node.get("content"), str) and node["content"].strip():
        parts.append(node["content"].strip())
    for kid in node.get("kids") or []:
        sub = _collect_text(kid)
        if sub:
            parts.append(sub)
    return " ".join(parts).strip()
```

#### Table renderer (`_render_table_markdown`)

Per schema (`$defs/table.rows[].cells[]`), tables expose `rows` (array of `tableRow`), each with `cells` (array of `tableCell` whose text is in nested `kids`).

`column span > 1` is handled by emitting empty padding cells so column counts stay rectangular. **`row span > 1` is intentionally not modeled** — implementing vertical occupancy would mean tracking a 2-D grid and skipping positions filled by spans from earlier rows. Demo-corpus tables (annual-report financial summaries) are dominated by horizontal category spans; vertical merges are rare. The fallback behavior is acceptable: a row-spanning cell appears in its first row only, and subsequent rows have an empty cell in that column. Splitting this into a follow-up if the demo surfaces a problem table.

```python
def _render_table_markdown(node) -> str:
    rows = node.get("rows") or []
    if not rows:
        return ""
    grid: list[list[str]] = []
    max_cols = 0
    for row in rows:
        line: list[str] = []
        for cell in row.get("cells") or []:
            text = _collect_text(cell).replace("|", r"\|").replace("\n", " ").strip()
            line.append(text)
            cspan = int(cell.get("column span") or 1)
            for _ in range(cspan - 1):
                line.append("")
        grid.append(line)
        max_cols = max(max_cols, len(line))
    # Pad short rows so the table is rectangular
    for line in grid:
        line.extend([""] * (max_cols - len(line)))
    md = ["| " + " | ".join(grid[0]) + " |",
          "| " + " | ".join(["---"] * max_cols) + " |"]
    for line in grid[1:]:
        md.append("| " + " | ".join(line) + " |")
    return "\n".join(md)
```

#### List renderer (`_render_list_markdown`)

Per schema (`$defs/list."list items"[]`), lists expose `list items` (array of `listItem` whose text is also in nested `kids`). Some emitters use the camelCase `items` synonym; handle both:

```python
def _render_list_markdown(node) -> str:
    items = node.get("list items") or node.get("items") or []
    lines = []
    for it in items:
        text = _collect_text(it)
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)
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

`_render_table_markdown(node)` is defined in §3.1 — it walks `rows`/`cells` from the schema. `_parse_md_table(md)` is its inverse for the row-group split path: it splits on `\n` and treats lines `2..N` as rows (line 1 = header, line 2 = `--|--|...` separator). `_table_chunk(...)` is a small constructor mirroring the section-flush logic with `element_type="table"` and the appropriate `split_strategy` value. Implementation details live in `extractor.py`.


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

1. opendataloader writes images into the per-run temp dir (`out_dir/...`); each `ParsedElement.image_path` is already an absolute path (joined with `out_dir`).
2. For each `ParsedElement(element_type="image")`:
   a. Run `_should_skip_external_image(image_path, seen_hashes)` filter (returns `(skip, sha256)`).
   b. Read the file bytes; run existing `downscale_image()` on them.
   c. Save to `ASSETS_DIR/<doc_id>_p<page>_i<idx>.<ext>` (existing naming preserved).
   d. Enqueue tuple onto `caption_q` with `meta_extra` carrying the SHA-256 + bbox + heading_path.
3. Caption worker captions + embeds; result tuple flows back with `meta_extra`.
4. Main thread inserts the image chunk, merging `meta_extra` into the meta dict.
5. After all images are persisted to ASSETS_DIR (i.e., after Phase 4 of `extract_and_store`), `shutil.rmtree(out_dir, ignore_errors=True)` in a `finally` block.

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
OPENDATALOADER_TIMEOUT: "300"          # subprocess.run timeout — kills JVM on hang
OPENDATALOADER_TMP_DIR: "/tmp/odl"     # parent of per-run tempfile.mkdtemp() dirs
OPENDATALOADER_JAVA_OPTS: "-Xmx2g"     # heap cap so JVM doesn't OOM the host
```

## 7. Re-processing the 4 Demo PDFs

### 7.1 Why

Existing chunks were produced by 1500-char sliding window over PyMuPDF text. New chunks are section-based with breadcrumbs and bounding boxes. Mixing both for the same `doc_id` confuses retrieval (duplicate near-identical text, conflicting metadata semantics). One-time, controlled re-processing brings the demo corpus onto the new pipeline.

Scope: **all PDFs in `data/processed/`** (five at time of writing — `BMWGroup_Bericht2023.pdf`, `Nachhaltigkeit-bei-Siemens.pdf`, `Siemens-Annual-Report-2024.pdf`, `TechVision_AG_Jahresbericht_2025.pdf`, `watcher_test.pdf`). The small `watcher_test.pdf` doubles as a fast canary that the new pipeline is end-to-end working before the four production demo PDFs run.

### 7.2 `scripts/reprocess_pdfs.sh`

Follows the existing `scripts/snapshot.sh` patterns: sources `.env`, uses `docker compose -p ammer-mmragv2 exec -T -e PGPASSWORD=... postgres psql -h 127.0.0.1`, calls pdf-ingest's status endpoint via container exec (no host port), and uses `python3 -c` for JSON parsing (no `jq` host dep — `python3` is already required for the uuid5 lookup below).

doc_ids are computed deterministically from `data/processed/*.pdf` filenames using the same `uuid5(NAMESPACE_URL, "mmrag:" + filename)` scheme as `services/pdf-ingest/app/main.py::get_or_create_doc_id` — exactly the PDFs being re-processed, no broad WHERE clause.

**Asset handling.** Old asset files are *moved into a timestamped quarantine directory* (`data/assets/_pre_opendataloader_${ts}/`), not deleted. The original bytes are preserved for rollback: rag_chunks rows reference flat names like `<doc_id>_p<page>_i<idx>.png` which only resolve at `data/assets/<name>`, so the rollback procedure (§10) explicitly moves files back out of the quarantine before assets are reachable again. New ingestion writes fresh files into `data/assets/` directly using the same deterministic naming — the quarantine subdirectory is sibling-nested, so no name collisions with new ingestion.

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" != "--confirm" ]]; then
  echo "Refusing to run without --confirm. Quarantines assets + deletes chunks/docs for all PDFs in data/processed/."
  exit 1
fi

[[ -f .env ]] || { echo "ERROR: .env not found"; exit 1; }
set -a; source .env; set +a

PROJECT="ammer-mmragv2"
PSQL=(docker compose -p "$PROJECT" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres
      psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" -At)

# 1. Active-work guard via the pdf-ingest container (no host port → use exec)
status=$(docker compose -p "$PROJECT" exec -T pdf-ingest \
           curl -sf http://localhost:8001/ingest/status)
active=$(echo "$status" | python3 -c "import json,sys;print(json.load(sys.stdin)['active_docs'])")
qsize=$(echo "$status"  | python3 -c "import json,sys;print(json.load(sys.stdin)['caption_queue_size'])")
if (( active > 0 || qsize > 0 )); then
  echo "Refusing — active_docs=$active caption_queue_size=$qsize"; exit 1
fi

# 2. Timestamped DB snapshot (rag_docs + rag_chunks)
ts=$(date +%Y%m%d_%H%M%S)
snap="data/demo_snapshot_pre_opendataloader_${ts}.sql"
docker compose -p "$PROJECT" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" \
    --table=rag_docs --table=rag_chunks --no-owner --no-privileges \
  > "$snap"
[[ -s "$snap" ]] || { echo "Snapshot empty — abort"; exit 1; }
echo "Snapshot: $snap ($(du -h "$snap" | cut -f1))"

# 3. Compute doc_ids deterministically from filenames in data/processed/
mapfile -t pdfs < <(find data/processed -maxdepth 1 -name '*.pdf' -printf '%f\n')
[[ ${#pdfs[@]} -gt 0 ]] || { echo "No PDFs in data/processed/"; exit 1; }
doc_ids=()
for fn in "${pdfs[@]}"; do
  did=$(python3 -c "import uuid,sys; print(uuid.uuid5(uuid.NAMESPACE_URL, 'mmrag:' + sys.argv[1]))" "$fn")
  doc_ids+=("$did")
  echo "  will reprocess: $fn  doc_id=$did"
done

# 4. Quarantine assets (NOT delete) and remove DB rows for those doc_ids
quarantine="_pre_opendataloader_${ts}"
docker compose -p "$PROJECT" exec -T pdf-ingest mkdir -p "/kb/assets/${quarantine}"
for did in "${doc_ids[@]}"; do
  docker compose -p "$PROJECT" exec -T pdf-ingest sh -c \
    "find /kb/assets -maxdepth 1 -name '${did}_p*_i*.*' -exec mv -t /kb/assets/${quarantine} {} +" \
    || true
  "${PSQL[@]}" -c "DELETE FROM rag_chunks WHERE doc_id='$did';" >/dev/null
  "${PSQL[@]}" -c "DELETE FROM rag_docs   WHERE doc_id='$did';" >/dev/null
done

# 5. Move PDFs back to inbox; watcher picks them up
mv data/processed/*.pdf data/inbox/
echo "Reprocess queued. Quarantine: data/assets/${quarantine}/"
echo "Watch: docker compose -p $PROJECT logs -f pdf-ingest"
```

### 7.3 Order of Operations on the Day

1. Ensure pdf-ingest is healthy and idle.
2. Build new pdf-ingest image.
3. `docker compose -p ammer-mmragv2 up -d pdf-ingest`.
4. Wait for `/health/ready` → `{"ok": true}`.
5. `bash scripts/reprocess_pdfs.sh --confirm`.
6. Watch logs; verify completion via `/ingest/status` — `active_docs=0` and `completed_docs` matches the count of PDFs queued (5 at time of writing).
7. Run `scripts/demo_readiness_check.sh`.

## 8. Error Handling

| Failure | Behavior |
|---|---|
| `java` missing at startup | `lifespan()` raises; container restart loop with clear log |
| `subprocess.run(["java","-jar",...])` returns non-zero | Catch in `extract_and_store`; log stderr; fall back to current PyMuPDF flow for this file; flag `meta.extractor = "pymupdf-fallback"` |
| `subprocess.TimeoutExpired` (JVM hangs past `OPENDATALOADER_TIMEOUT`) | Subprocess is killed automatically; same fallback path; release temp dir |
| Java not installed at runtime (subprocess raises `FileNotFoundError`) | Same fallback for the file; container is also caught at lifespan startup so this is rare |
| Convert produces no JSON file | Same fallback path; log warning with `out_dir` listing |
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

Append to `scripts/demo_readiness_check.sh`, using its existing `pass`/`fail` helpers and the same `-p ammer-mmragv2 exec -T -e PGPASSWORD` Postgres pattern as the other DB checks in the project:

```bash
echo "== 16. opendataloader integration =="
if docker compose -p ammer-mmragv2 exec -T pdf-ingest java -version >/dev/null 2>&1; then
  pass "Java runtime present in pdf-ingest"
else
  fail "Java runtime not available in pdf-ingest"
fi
BBOX_COUNT=$(docker compose -p ammer-mmragv2 exec -T \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  psql -h 127.0.0.1 -U "${POSTGRES_USER}" -d "${RAG_DB}" -At \
  -c "SELECT count(*) FROM rag_chunks WHERE meta ? 'bbox';" 2>/dev/null || echo "0")
if [ "${BBOX_COUNT:-0}" -gt 0 ]; then
  pass "$BBOX_COUNT chunks carry meta.bbox"
else
  fail "no chunks carry meta.bbox — pipeline did not produce structure metadata"
fi
```

## 10. Rollout & Rollback

### Rollout
1. PR with all changes (extractor, Dockerfile, compose env, scripts, tests).
2. Merge during a quiet window — mid-week, not before Sven's demo.
3. Build + restart pdf-ingest only (no other services touched):
   `docker compose -p ammer-mmragv2 build pdf-ingest && docker compose -p ammer-mmragv2 up -d pdf-ingest`
4. Run `scripts/reprocess_pdfs.sh --confirm`.
5. Run `scripts/demo_readiness_check.sh`.
6. Smoke test the four production demo prompts (BMW Group, Siemens × 2, TechVision).

### Rollback
Both DB and asset state are preserved by reprocess (`data/demo_snapshot_pre_opendataloader_<ts>.sql` + `data/assets/_pre_opendataloader_<ts>/`). Restore must mirror the existing `scripts/restore_snapshot.sh` pattern — TRUNCATE before psql-restore, otherwise post-merge rows collide with the snapshot's primary keys.

1. `git revert` the merge commit, rebuild pdf-ingest, `docker compose -p ammer-mmragv2 up -d pdf-ingest`.
2. Halt ingestion before restoring (avoid in-flight writes racing the truncate):
   ```bash
   docker compose -p ammer-mmragv2 stop pdf-ingest
   ```
3. Truncate, then restore — same pattern as `scripts/restore_snapshot.sh`:
   ```bash
   docker compose -p ammer-mmragv2 exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
     psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" \
     -c "TRUNCATE rag_chunks, rag_docs CASCADE;"

   docker compose -p ammer-mmragv2 exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
     psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" \
     < data/demo_snapshot_pre_opendataloader_<ts>.sql
   ```
4. Restore quarantined assets back to the live directory (asset_path values now resolve):
   ```bash
   docker compose -p ammer-mmragv2 exec -T pdf-ingest sh -c \
     "mv /kb/assets/_pre_opendataloader_<ts>/* /kb/assets/ && rmdir /kb/assets/_pre_opendataloader_<ts>"
   ```
5. Restart pdf-ingest:
   ```bash
   docker compose -p ammer-mmragv2 start pdf-ingest
   ```
6. Move any PDFs still sitting in `data/inbox/` back to `data/processed/` so the watcher doesn't re-trigger ingestion of the snapshot's documents.
7. Keep both the snapshot file and the quarantine dir for at least one demo cycle before final cleanup. (After cleanup: `rm data/demo_snapshot_pre_opendataloader_<ts>.sql` and `docker compose -p ammer-mmragv2 exec -T pdf-ingest rm -rf /kb/assets/_pre_opendataloader_<ts>`.)

## 11. Out of Scope (Future Work)

- Hybrid mode (`hybrid="docling-fast"`) for higher table accuracy on borderless / scanned tables. Adds a docling sidecar service. Defer until local-mode quality is judged insufficient on the demo prompts.
- Click-to-source UI in Control Center using the stored `bbox` + `page` + `page_size`. Data is now there; UI is a follow-up.
- Tagged-PDF generation (the accessibility add-on). Different problem.
- Replacing the qwen2.5vl:7b captioning step with opendataloader's hybrid SmolVLM picture descriptions. Would regress quality.

## 12. Deviation Record

Append to `MANUAL_STEPS.md`:

> **D24** — PDF text/image extraction switched from PyMuPDF to opendataloader-pdf 2.4.1 (local mode, OpenJDK 17 JRE in pdf-ingest container). Section-based chunking with heading-path breadcrumbs replaces the 1500-char sliding window. Bounding boxes, page sizes, heading paths, element ids, and split-strategy provenance are stored in `rag_chunks.meta` (JSONB; no schema migration). PyMuPDF retained for `downscale_image()` and external-image dimension reads. Re-processing of all PDFs in `data/processed/` (five at time of writing — four production demo PDFs plus `watcher_test.pdf`) performed via `scripts/reprocess_pdfs.sh --confirm` after `data/demo_snapshot_pre_opendataloader_<ts>.sql` snapshot and `data/assets/_pre_opendataloader_<ts>/` asset quarantine. Embedding model (`bge-m3`, 1024d) and vision model (`qwen2.5vl:7b`) unchanged.
