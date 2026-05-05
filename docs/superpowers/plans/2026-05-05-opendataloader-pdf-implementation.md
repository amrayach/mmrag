# OpenDataLoader PDF Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Execution status:** implemented, tested, and rolled out on May 5, 2026. `pdf-ingest` was rebuilt with OpenJDK 17 and `opendataloader-pdf==2.4.1`; all five PDFs were reprocessed. Current result: 1,648 PDF chunks, 1,648 chunks with `meta.bbox`, and 486 BMW text chunks intentionally stored without embeddings and flagged with `meta.embedding_error` after Ollama rejected noisy extracted text.

**Verification:** container tests passed (`15 passed, 5 warnings`), `pdf-ingest` finished idle with `failed_docs=0`, and the final DB spot-check showed all PDF chunks carry bounding boxes. Rollback artifacts remain: `data/demo_snapshot_pre_opendataloader_20260505_172446.sql` and `data/assets/_pre_opendataloader_20260505_172446/`.

**Goal:** Replace PyMuPDF-based PDF text extraction in `services/pdf-ingest` with `opendataloader-pdf` 2.4.1 (local mode), adding section-based chunking with heading-path breadcrumbs, bounding boxes, and per-chunk structural metadata, then re-process all 5 PDFs in `data/processed/`.

**Architecture:** A new `extractor.py` module wraps the bundled JAR via `subprocess.run(..., timeout=...)`, walks the JSON layout tree, and produces (a) a flat element list and (b) section-grouped `Chunk` objects whose embedded text is prefixed with a `›`-separated heading breadcrumb. `main.py::extract_and_store` swaps its fitz-page loop for `extractor.parse(...)` + `extractor.layout_to_chunks(...)`; PyMuPDF is retained for image downscaling and external-image dimension reads. New JSONB `meta` keys (`bbox`, `bbox_units`, `bbox_order`, `page_size`, `heading_path`, `element_ids`, `split_strategy`, `extractor`, `image_sha256`) are additive — no schema migration.

**Tech Stack:** Python 3.11 (slim-bookworm, digest-pinned) · OpenJDK 17 JRE headless (apt-pinned) · `opendataloader-pdf==2.4.1` (PyPI wheel bundles the JAR) · `PyMuPDF==1.24.14` (kept) · `Pillow==10.4.0` (explicit pin) · `pytest==8.3.4` (new test dep) · Postgres 15 / pgvector / `bge-m3` (1024d, unchanged) · `qwen2.5vl:7b` captioning (unchanged).

**Spec source:** `docs/superpowers/specs/2026-05-05-opendataloader-pdf-design.md` @ `8b2d368` (4 rounds of Codex review).

---

## Reference Files (read once before starting)

- Spec: `docs/superpowers/specs/2026-05-05-opendataloader-pdf-design.md`
- Current extract loop: `services/pdf-ingest/app/main.py:436-560` (`extract_and_store`)
- Current splitter: `services/pdf-ingest/app/main.py:244-285` (`split_text`)
- Current caption queue tuple: `services/pdf-ingest/app/main.py:345` and `_caption_worker` 348-370
- Current insert helper: `services/pdf-ingest/app/main.py:398-415` (`insert_chunk`)
- Snapshot pattern: `scripts/snapshot.sh`
- Restore pattern: `scripts/restore_snapshot.sh` (TRUNCATE-then-restore)
- Demo readiness pattern: `scripts/demo_readiness_check.sh` (`pass`/`fail` helpers, `-p ammer-mmragv2 exec -T -e PGPASSWORD=...` Postgres pattern)
- Project rules: `CLAUDE.md` (compose project name, port range, no `0.0.0.0` bindings, ask before stack-changing commands)

## Project Rules to Enforce Throughout

- `docker compose` always uses `-p ammer-mmragv2`.
- `psql` / `pg_dump` always use `-h 127.0.0.1`, `-U "$POSTGRES_USER"`, and `-e PGPASSWORD="$POSTGRES_PASSWORD"`.
- pdf-ingest has no host port — call its endpoints via `docker compose -p ammer-mmragv2 exec -T pdf-ingest curl http://localhost:8001/...`.
- Never bind ports to `0.0.0.0`. Never run `apt` on the host. Never touch other users' state.
- After every step that changes container state, **stop and ask the user before proceeding**. The user runs container actions themselves.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `services/pdf-ingest/app/splitter.py` | NEW | Standalone `split_text()` extracted from `main.py` so `extractor.py` can import without circular dep |
| `services/pdf-ingest/app/extractor.py` | NEW | `parse(pdf_path, doc_id)` + `layout_to_chunks(elements)` |
| `services/pdf-ingest/app/main.py` | MODIFY | Replace fitz-page loop; add Java startup check; extend caption queue tuple; merge `meta_extra`; tempdir cleanup |
| `services/pdf-ingest/requirements.txt` | MODIFY | Add `opendataloader-pdf==2.4.1`, `Pillow==10.4.0`, `pytest==8.3.4` |
| `services/pdf-ingest/Dockerfile` | MODIFY | Digest-pin base; install `openjdk-17-jre-headless` (apt-pinned); `COPY tests ./tests` |
| `services/pdf-ingest/tests/__init__.py` | NEW | Empty marker |
| `services/pdf-ingest/tests/conftest.py` | NEW | Add `services/pdf-ingest/` to `sys.path` so `from app.extractor import ...` resolves |
| `services/pdf-ingest/tests/test_extractor.py` | NEW | Adapter unit tests (10 tests) |
| `services/pdf-ingest/tests/fixtures/sample_layout.json` | NEW | Hand-crafted opendataloader output covering all element types |
| `docker-compose.yml` | MODIFY | `OPENDATALOADER_*` env vars on `pdf-ingest` |
| `scripts/reprocess_pdfs.sh` | NEW | Gated reprocess flow with **interactive `read -r` prompt** (caution #2) |
| `scripts/demo_readiness_check.sh` | MODIFY | Append check #16 (Java present + `meta ? 'bbox'` chunks exist) |
| `MANUAL_STEPS.md` | MODIFY | Append deviation D24 |

---

## Phase Map

| # | Phase | Why this order |
|---|---|---|
| 0 | Resolve Dockerfile pins, add deps, build image | Need a built image to run Phase 1's smoke test |
| 1 | **JAR + CLI smoke test** (NO adapter code yet) | Caution #1: validate JAR path & flags before writing the adapter |
| 2 | Refactor `split_text` into `app/splitter.py` | Lets `extractor.py` import the splitter without pulling all of `main.py` |
| 3 | TDD `extractor.parse()` | Adapter contract — read JSON, walk kids, render tables/lists |
| 4 | TDD `extractor.layout_to_chunks()` | Section accumulation + breadcrumbs + page-boundary split + table chunking |
| 5 | Add external-image filter + Java startup check | Pre-requisites for the main.py wire-up |
| 6 | Wire `extractor` into `main.py::extract_and_store` | Replace fitz-page loop; extend caption queue tuple; tempdir cleanup |
| 7 | `docker-compose.yml` env vars + rebuild | Ship the runtime knobs (`OPENDATALOADER_*`) |
| 8 | `scripts/reprocess_pdfs.sh` with **interactive prompt** | Caution #2: explicit approval per run, not just `--confirm` |
| 9 | `scripts/demo_readiness_check.sh` check #16 | Smoke validates `meta.bbox` is being written |
| 10 | `MANUAL_STEPS.md` deviation D24 | Document the change |
| 11 | Full corpus reprocess + demo prompt eyeball | Real validation; canary order: `watcher_test.pdf` → BMW → Siemens × 2 → TechVision |

---

## Phase 0: Resolve Dockerfile Pins, Add Deps, Build Image

**Files:**
- Modify: `services/pdf-ingest/requirements.txt`
- Modify: `services/pdf-ingest/Dockerfile`

### Task 0.1 — Capture the python:3.11-slim-bookworm digest

- [ ] **Step 1: Pull the base image and capture its digest.**

Run:

```bash
docker pull python:3.11-slim-bookworm
docker inspect --format='{{index .RepoDigests 0}}' python:3.11-slim-bookworm
```

Expected output: `python:3.11-slim-bookworm@sha256:<64-hex-chars>`. Copy the full string (the part after the `@`).

- [ ] **Step 2: Capture the openjdk-17-jre-headless apt version available in that bookworm image.**

Run:

```bash
docker run --rm python:3.11-slim-bookworm sh -c "apt-get update -qq && apt-cache policy openjdk-17-jre-headless | head -5"
```

Expected output begins:
```
openjdk-17-jre-headless:
  Installed: (none)
  Candidate: 17.0.<minor>+<n>-<n>~deb12u<n>
  Version table:
     17.0.<minor>+<n>-<n>~deb12u<n> 500
```
Copy the `Candidate:` value (everything after the colon) — that is the version string we'll pin.

- [ ] **Step 3: Note both values for the next task.**

Record on a scratch line in your shell session:
```
PY_DIGEST=sha256:<64-hex-chars-from-step-1>
JRE_VERSION=17.0.<minor>+<n>-<n>~deb12u<n>
```

(You will paste them into the Dockerfile in Task 0.3. Do not commit them yet.)

### Task 0.2 — Update `requirements.txt`

- [ ] **Step 1: Replace the file contents.**

Read the current file first (`services/pdf-ingest/requirements.txt`). Then write:

```text
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
psycopg[binary]==3.2.3
PyMuPDF==1.24.14
python-multipart==0.0.12
requests==2.32.3
pgvector==0.3.6
psycopg_pool==3.2.4
opendataloader-pdf==2.4.1
Pillow==10.4.0
pytest==8.3.4
```

Lines 1-9 are unchanged. Lines 10-12 are new.

### Task 0.3 — Update `Dockerfile`

- [ ] **Step 1: Replace the file with the pinned version.**

Substitute the `<digest>` and `<jre-version>` you captured in Task 0.1:

```dockerfile
FROM python:3.11-slim-bookworm@sha256:<digest>

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    openjdk-17-jre-headless=<jre-version> \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

The two new bits are: the `@sha256:...` after the `FROM` line, the `openjdk-17-jre-headless=<jre-version>` apt entry, and `COPY tests ./tests`. The `--host 0.0.0.0` in the `CMD` is intentional: that is the **container-internal** bind, exposed only on the loopback `127.0.0.1:56xxx` host port range — it does not violate the project rule against host-side `0.0.0.0` bindings.

### Task 0.4 — Build & verify

- [ ] **Step 1: Ask the user to confirm before building.**

Print the command and wait. (Building rewrites the existing pdf-ingest image — it is reversible by rebuilding from a previous `git checkout`, but counts as a stack change.)

```text
About to run:
  docker compose -p ammer-mmragv2 build pdf-ingest
This will rebuild the pdf-ingest image with the new Dockerfile (digest-pinned base, JRE 17, opendataloader-pdf 2.4.1, Pillow, pytest). It does NOT restart the running container.
OK to proceed?
```

- [ ] **Step 2: After the user confirms, run the build.**

Run: `docker compose -p ammer-mmragv2 build pdf-ingest`
Expected: build completes successfully. Final line includes `naming to docker.io/library/ammer-mmragv2-pdf-ingest`.

- [ ] **Step 3: Verify the build by sanity-checking the new layers.**

Run: `docker run --rm --entrypoint sh ammer-mmragv2-pdf-ingest -c "java -version && python -c 'import opendataloader_pdf, PIL, pytest; print(\"ok\")'"`
Expected: prints the OpenJDK 17 version banner on stderr, then `ok` on stdout. (No errors; non-zero exit means a dep is missing.)

- [ ] **Step 4: Commit.**

```bash
git add services/pdf-ingest/requirements.txt services/pdf-ingest/Dockerfile
git commit -m "$(cat <<'EOF'
build(pdf-ingest): add JRE 17 + opendataloader-pdf 2.4.1, pin base digest

- Base: python:3.11-slim-bookworm@<digest>
- Apt: openjdk-17-jre-headless pinned to bookworm version
- New runtime deps: opendataloader-pdf==2.4.1, Pillow==10.4.0
- New test dep: pytest==8.3.4 (Dockerfile now COPY tests ./tests)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 1: JAR + CLI Smoke Test (MANDATORY before adapter code)

**Goal:** Validate, *inside the built container*, that the bundled JAR path is what we expect, that the CLI flags from the spec are accepted, and that the produced JSON has the field shape the adapter assumes (`type`, `kids`, `page number`, `bounding box`, `source`, `rows[].cells[]`, `list items[]`).

**Why this is its own phase:** Caution #1 from the user. Skipping this and writing the adapter first means debugging two unknowns (parser bugs vs. wrong JAR/flag assumptions) at once. We resolve the JAR/flag axis first by a dry run.

**No code is written in this phase. No commits. Output of this phase is a paste of the inspected JSON keys into the conversation, used as evidence the spec's adapter contract matches reality.**

### Task 1.1 — Run the JAR on the smallest demo PDF

- [ ] **Step 1: Ask the user to confirm a one-shot ephemeral container run.**

Print:
```text
About to run:
  docker compose -p ammer-mmragv2 run --rm --entrypoint sh pdf-ingest -c "..."
This spins up a one-off pdf-ingest container, runs the JAR on watcher_test.pdf, dumps JSON keys, then exits. No state changes, no other containers touched. OK?
```

- [ ] **Step 2: After confirmation, run the smoke test.**

Run:

```bash
docker compose -p ammer-mmragv2 run --rm --entrypoint sh pdf-ingest -c '
  set -e
  JAR=$(python3 -c "from importlib.resources import files; print(files(\"opendataloader_pdf\").joinpath(\"jar\", \"opendataloader-pdf-cli.jar\"))")
  echo "JAR_PATH=$JAR"
  test -f "$JAR" || { echo "ERROR: JAR not found"; exit 1; }
  mkdir -p /tmp/odl-smoke
  java -jar "$JAR" /kb/processed/watcher_test.pdf \
    --output-dir /tmp/odl-smoke \
    --format json \
    --image-output external \
    --image-format png \
    --reading-order xycut \
    --use-struct-tree \
    --quiet
  echo "---OUTPUT-FILES---"
  ls -1 /tmp/odl-smoke
  echo "---JSON-TOP-LEVEL-KEYS---"
  python3 -c "import json,glob; d=json.load(open(glob.glob(\"/tmp/odl-smoke/*.json\")[0])); print(sorted(d.keys()))"
  echo "---FIRST-FEW-NODE-TYPES---"
  python3 -c "
import json,glob
d=json.load(open(glob.glob(\"/tmp/odl-smoke/*.json\")[0]))
def walk(n, depth=0, c=[0]):
    if c[0] >= 30: return
    if isinstance(n, dict):
        c[0] += 1
        keys = [k for k in n.keys() if k != \"kids\"]
        print(\"  \"*depth, n.get(\"type\",\"?\"), keys)
        for k in n.get(\"kids\",[]) or []: walk(k, depth+1, c)
walk(d)
"
'
```

Expected output (paste into conversation as evidence):
- `JAR_PATH=/usr/local/lib/python3.11/site-packages/opendataloader_pdf/jar/opendataloader-pdf-cli.jar` (path may vary; key check is the JAR exists)
- `---OUTPUT-FILES---` lists at least `watcher_test.json` and possibly some `.png` files in subdirs
- `---JSON-TOP-LEVEL-KEYS---` includes `kids` (the spec assumes `doc.get("kids")` for the top-level walk)
- `---FIRST-FEW-NODE-TYPES---` shows nodes carrying field names like `page number`, `bounding box`, `content`, `type`, plus list-of-strings like `rows`, `cells`, `list items` (or `items`) where applicable

- [ ] **Step 3: Failure handling.**

If any of these are wrong, **stop the implementation here** and report:
- JAR path different from `importlib.resources.files("opendataloader_pdf").joinpath("jar", "opendataloader-pdf-cli.jar")` → adapter's `JAR_PATH` constant must change
- Top-level JSON has no `kids` field → spec's `for kid in doc.get("kids") or []` is wrong; investigate before continuing
- Field names use camelCase (`pageNumber`, `boundingBox`) instead of spaced names → spec's `_bbox` and `walk` reads must change
- A flag is rejected (`Unknown option: --use-struct-tree`) → JAR version is not 2.4.1 or flag was renamed

Do **not** patch the spec silently. Surface the discrepancy to the user before writing any adapter code.

- [ ] **Step 4: Success — record evidence in conversation, no commit.**

Reply to the user with:
```
Phase 1 smoke test passed:
- JAR path matches spec: <path>
- Top-level keys: <list>
- Sample node types: <comma list>
- Field names with spaces confirmed: <yes/no>
Proceeding to Phase 2.
```

---

## Phase 2: Refactor `split_text` into `app/splitter.py`

**Goal:** Move the existing `split_text` function out of `main.py` so `extractor.py` can import it without circular deps. No behavior change.

**Files:**
- Create: `services/pdf-ingest/app/splitter.py`
- Modify: `services/pdf-ingest/app/main.py:244-285` (delete `split_text` body, replace with `from .splitter import split_text`)

### Task 2.1 — Create `splitter.py`

- [ ] **Step 1: Write the new file.**

Create `services/pdf-ingest/app/splitter.py`:

```python
import re
from typing import List


def split_text(text: str, chunk_chars: int, overlap: int) -> List[str]:
    """German-aware sentence splitter — moved from main.py unchanged.

    Preserves paragraph breaks; splits on sentence boundaries followed by a
    capital letter so 'z.B.' or 'Nr.' do not break sentences. Falls back to
    hard-split for single sentences that exceed chunk_chars.
    """
    if not text or not text.strip():
        return []

    text = re.sub(r'[^\S\n]+', ' ', text)
    paragraphs = re.split(r'\n\s*\n+', text)
    sentences: List[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        parts = re.split(r'(?<=[.!?])\s+(?=[A-ZÄÖÜ])', para)
        sentences.extend(p.strip() for p in parts if p.strip())

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
```

### Task 2.2 — Delete `split_text` from `main.py` and re-import

- [ ] **Step 1: Delete lines 244-285 (the `split_text` function body) and replace with an import.**

Edit `services/pdf-ingest/app/main.py`:

Find the block starting at line 244 (`def split_text(text: str, chunk_chars: int, overlap: int) -> List[str]:`) and ending at line 285 (the function's last `return result`). Replace the entire block with:

```python
from .splitter import split_text  # noqa: E402  (kept near other helper imports; re-export shape preserved)
```

Place the import alongside the other top-level imports (move it up to the import block at the top of the file — same place where `from typing import ...` lives, around line 15). Then delete the deleted-function lines from line 244.

### Task 2.3 — Build & verify

- [ ] **Step 1: Run the build.**

Ask user, then run: `docker compose -p ammer-mmragv2 build pdf-ingest`

- [ ] **Step 2: Smoke-import the module to confirm no syntax errors.**

Run: `docker compose -p ammer-mmragv2 run --rm --entrypoint sh pdf-ingest -c "python -c 'from app.main import split_text; print(split_text(\"Hallo. Welt.\", 100, 10))'"`
Expected: `['Hallo. Welt.']` printed to stdout.

- [ ] **Step 3: Commit.**

```bash
git add services/pdf-ingest/app/splitter.py services/pdf-ingest/app/main.py
git commit -m "$(cat <<'EOF'
refactor(pdf-ingest): extract split_text into app/splitter.py

Lets extractor.py import the German-aware sentence splitter without
pulling main.py's heavy module-level state. Behavior unchanged; main.py
now re-imports it for the (now-temporary) fitz path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: TDD `extractor.parse()`

**Goal:** Implement `parse(pdf_path, doc_id) -> tuple[list[ParsedElement], str]` and its helpers (`_normalize_type`, `_bbox`, `_collect_text`, `_render_table_markdown`, `_render_list_markdown`, `_harvest_page_sizes`, `_run_opendataloader`). All TDD.

**Files:**
- Create: `services/pdf-ingest/tests/__init__.py`
- Create: `services/pdf-ingest/tests/conftest.py`
- Create: `services/pdf-ingest/tests/fixtures/sample_layout.json`
- Create: `services/pdf-ingest/tests/test_extractor.py`
- Create: `services/pdf-ingest/app/extractor.py`

### Task 3.1 — Test scaffolding

- [ ] **Step 1: Create `tests/__init__.py` (empty).**

Write the file with empty content.

- [ ] **Step 2: Create `tests/conftest.py`.**

```python
"""Make `app.*` importable when pytest runs from services/pdf-ingest/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

- [ ] **Step 3: Create the fixture `tests/fixtures/sample_layout.json`.**

Hand-crafted minimal opendataloader output covering all element types the spec maps. Field names match the spec's schema reads (`page number`, `bounding box`, `kids`, `rows`/`cells`, `list items`):

```json
{
  "kids": [
    {
      "type": "Heading",
      "page number": 1,
      "bounding box": [50, 720, 562, 750],
      "content": "1. Strategie",
      "heading level": 1,
      "id": 1,
      "kids": [
        {
          "type": "Heading",
          "page number": 1,
          "bounding box": [50, 690, 562, 715],
          "content": "1.2 Nachhaltigkeit",
          "heading level": 2,
          "id": 2,
          "kids": [
            {
              "type": "paragraph",
              "page number": 1,
              "bounding box": [50, 600, 562, 685],
              "content": "Die Gruppe verfolgt klare Klimaziele.",
              "id": 3,
              "kids": []
            },
            {
              "type": "paragraph",
              "page number": 2,
              "bounding box": [50, 700, 562, 720],
              "content": "Fortsetzung auf Seite 2.",
              "id": 4,
              "kids": []
            }
          ]
        }
      ]
    },
    {
      "type": "table",
      "page number": 3,
      "bounding box": [50, 500, 562, 650],
      "id": 10,
      "rows": [
        {
          "cells": [
            {"kids": [{"content": "Jahr", "kids": []}]},
            {"kids": [{"content": "Umsatz", "kids": []}], "column span": 2}
          ]
        },
        {
          "cells": [
            {"kids": [{"content": "2023", "kids": []}]},
            {"kids": [{"content": "100", "kids": []}]},
            {"kids": [{"content": "Mio EUR", "kids": []}]}
          ]
        }
      ]
    },
    {
      "type": "list",
      "page number": 4,
      "bounding box": [50, 400, 562, 500],
      "id": 20,
      "list items": [
        {"kids": [{"content": "Erstens", "kids": []}]},
        {"kids": [{"content": "Zweitens", "kids": []}]}
      ]
    },
    {
      "type": "picture",
      "page number": 5,
      "bounding box": [100, 200, 400, 500],
      "source": "images/p5_i0.png",
      "id": 30
    },
    {
      "type": "header",
      "page number": 1,
      "bounding box": [50, 770, 562, 790],
      "content": "skipped header",
      "id": 99,
      "kids": []
    }
  ]
}
```

- [ ] **Step 4: Create `tests/test_extractor.py` with the failing tests for the helpers.**

```python
"""Tests for extractor.py — adapter that wraps opendataloader-pdf JSON."""
import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_layout.json"


@pytest.fixture
def sample_doc():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---- helper-level ---------------------------------------------------------

def test_normalize_type_image_variants():
    from app.extractor import _normalize_type
    for raw in ("image", "Image", "picture", "PICTURE", "png", "jpeg", "jpg"):
        assert _normalize_type(raw) == "image", f"{raw} should normalize to image"


def test_normalize_type_skip_structural_noise():
    from app.extractor import _normalize_type
    for raw in ("header", "footer", "table row", "table cell"):
        assert _normalize_type(raw) == "_skip", f"{raw} should be skipped"


def test_normalize_type_unknown_falls_back_to_text():
    from app.extractor import _normalize_type
    assert _normalize_type("annotation") == "text"
    assert _normalize_type("") == "text"


def test_bbox_reads_field_with_space():
    from app.extractor import _bbox
    node = {"bounding box": [10.0, 20.0, 30.0, 40.0]}
    assert _bbox(node) == (10.0, 20.0, 30.0, 40.0)


def test_bbox_returns_none_for_malformed():
    from app.extractor import _bbox
    assert _bbox({}) is None
    assert _bbox({"bounding box": [1, 2, 3]}) is None  # only 3 values


def test_collect_text_walks_nested_kids():
    from app.extractor import _collect_text
    node = {
        "kids": [
            {"content": "Foo", "kids": []},
            {"kids": [{"content": "Bar", "kids": []}]},
        ]
    }
    assert _collect_text(node) == "Foo Bar"


def test_render_table_markdown_with_column_span():
    from app.extractor import _render_table_markdown
    node = {
        "rows": [
            {"cells": [
                {"kids": [{"content": "Jahr"}]},
                {"kids": [{"content": "Umsatz"}], "column span": 2},
            ]},
            {"cells": [
                {"kids": [{"content": "2023"}]},
                {"kids": [{"content": "100"}]},
                {"kids": [{"content": "Mio EUR"}]},
            ]},
        ]
    }
    md = _render_table_markdown(node)
    lines = md.split("\n")
    # header row, separator row, data row → padded to 3 columns
    assert lines[0] == "| Jahr | Umsatz |  |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| 2023 | 100 | Mio EUR |"


def test_render_list_markdown_handles_both_keys():
    from app.extractor import _render_list_markdown
    node1 = {"list items": [{"kids": [{"content": "A"}]}, {"kids": [{"content": "B"}]}]}
    node2 = {"items":      [{"kids": [{"content": "A"}]}, {"kids": [{"content": "B"}]}]}
    assert _render_list_markdown(node1) == "- A\n- B"
    assert _render_list_markdown(node2) == "- A\n- B"
```

- [ ] **Step 5: Run tests — expect ALL FAIL with import errors.**

Ask user, then run: `docker compose -p ammer-mmragv2 build pdf-ingest && docker compose -p ammer-mmragv2 run --rm --entrypoint pytest pdf-ingest tests/test_extractor.py -v`
Expected: every test fails with `ModuleNotFoundError: No module named 'app.extractor'`.

### Task 3.2 — Implement helpers

- [ ] **Step 1: Create `services/pdf-ingest/app/extractor.py` with the helpers.**

```python
"""opendataloader-pdf adapter: parse JSON layout into ParsedElement list,
group into Chunk list. See docs/superpowers/specs/2026-05-05-opendataloader-pdf-design.md."""
import hashlib
import json
import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF — used for page-size harvest only

from .splitter import split_text

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OPENDATALOADER_MAX_PARALLEL = int(os.getenv("OPENDATALOADER_MAX_PARALLEL", "1"))
OPENDATALOADER_TIMEOUT = int(os.getenv("OPENDATALOADER_TIMEOUT", "300"))
OPENDATALOADER_TMP = os.getenv("OPENDATALOADER_TMP_DIR", "/tmp/odl")
JAVA_OPTS = os.getenv("OPENDATALOADER_JAVA_OPTS", "-Xmx2g").split()

JAR_PATH = str(
    files("opendataloader_pdf").joinpath("jar", "opendataloader-pdf-cli.jar")
)

CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))
TABLE_HARD_LIMIT = 4 * CHUNK_CHARS  # 6000 chars

EXTRACTOR_VERSION = "opendataloader-pdf@2.4.1"

_OPENDATALOADER_SEMAPHORE = threading.Semaphore(OPENDATALOADER_MAX_PARALLEL)

# ---------------------------------------------------------------------------
# Type map
# ---------------------------------------------------------------------------
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
    # lists — schema fields ("list items"/"items") drive traversal; type just classifies
    "list": "list", "ul": "list", "ol": "list",
    "list item": "text", "li": "text",
    # structural noise (opendataloader filters by default; double-guard)
    "header": "_skip", "footer": "_skip", "table row": "_skip", "table cell": "_skip",
    "caption": "caption",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ParsedElement:
    element_type: str          # "heading" | "text" | "table" | "list" | "image" | "caption"
    page: int                  # 1-indexed
    bbox: tuple                # (left, bottom, right, top), pdf points
    page_size: tuple           # (width, height), pdf points (from PyMuPDF)
    content: Optional[str]     # Markdown for text/table/list/heading; None for image
    image_path: Optional[str]  # absolute path on disk for image elements
    heading_level: Optional[int] = None
    raw_id: Optional[int] = None


@dataclass
class Chunk:
    chunk_type: str                    # "text" | "image"
    page: int
    content_text: Optional[str]
    caption: Optional[str]
    asset_path: Optional[str]
    image_bytes: Optional[bytes]
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalize_type(raw: str) -> str:
    return ELEMENT_TYPE_MAP.get((raw or "").lower(), "text")


def _bbox(node):
    bb = node.get("bounding box")
    if not bb or len(bb) != 4:
        return None
    return tuple(float(x) for x in bb)


def _collect_text(node) -> str:
    """Recursively gather visible text from a node's content + descendants.
    Cell/list-item text lives in nested kids per schema."""
    if not isinstance(node, dict):
        return ""
    parts = []
    if isinstance(node.get("content"), str) and node["content"].strip():
        parts.append(node["content"].strip())
    for kid in node.get("kids") or []:
        sub = _collect_text(kid)
        if sub:
            parts.append(sub)
    return " ".join(parts).strip()


def _render_table_markdown(node) -> str:
    rows = node.get("rows") or []
    if not rows:
        return ""
    grid = []
    max_cols = 0
    for row in rows:
        line = []
        for cell in row.get("cells") or []:
            text = _collect_text(cell).replace("|", r"\|").replace("\n", " ").strip()
            line.append(text)
            cspan = int(cell.get("column span") or 1)
            for _ in range(cspan - 1):
                line.append("")
        grid.append(line)
        max_cols = max(max_cols, len(line))
    for line in grid:
        line.extend([""] * (max_cols - len(line)))
    md = ["| " + " | ".join(grid[0]) + " |",
          "| " + " | ".join(["---"] * max_cols) + " |"]
    for line in grid[1:]:
        md.append("| " + " | ".join(line) + " |")
    return "\n".join(md)


def _render_list_markdown(node) -> str:
    items = node.get("list items") or node.get("items") or []
    lines = []
    for it in items:
        text = _collect_text(it)
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)
```

- [ ] **Step 2: Run helper tests — expect ALL PASS.**

Ask user, then run: `docker compose -p ammer-mmragv2 build pdf-ingest && docker compose -p ammer-mmragv2 run --rm --entrypoint pytest pdf-ingest tests/test_extractor.py -v -k "normalize_type or bbox or collect_text or render_table or render_list"`
Expected: 8 passed.

- [ ] **Step 3: Commit.**

```bash
git add services/pdf-ingest/app/extractor.py services/pdf-ingest/tests/
git commit -m "$(cat <<'EOF'
feat(pdf-ingest): add extractor helpers + test fixture

Adds _normalize_type, _bbox, _collect_text, _render_table_markdown,
_render_list_markdown plus pytest scaffolding (conftest.py, fixture)
for the opendataloader-pdf adapter. parse() and layout_to_chunks()
land in subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3.3 — Implement `parse()` itself + tests

- [ ] **Step 1: Add the failing test for `parse()`.**

Append to `services/pdf-ingest/tests/test_extractor.py`:

```python
# ---- parse-level (mocks subprocess + fitz) --------------------------------

def test_parse_walks_kids_and_normalizes_types(tmp_path, monkeypatch, sample_doc):
    """parse() runs the JAR (mocked), reads the JSON, walks kids in document order."""
    out_dir_holder = {}

    def fake_run(args, **kw):
        out_dir = args[args.index("--output-dir") + 1]
        out_dir_holder["dir"] = out_dir
        # Drop our fixture as the JSON the JAR would have produced. The stem
        # must match the input pdf's stem so parse() reads it.
        pdf = args[args.index("-jar") + 2]
        stem = Path(pdf).stem
        Path(out_dir, f"{stem}.json").write_text(json.dumps(sample_doc))

        class CompletedProcess:
            returncode = 0
            stdout = ""
            stderr = ""
        return CompletedProcess()

    def fake_harvest(_pdf_path):
        return {1: (612.0, 792.0), 2: (612.0, 792.0), 3: (612.0, 792.0),
                4: (612.0, 792.0), 5: (612.0, 792.0)}

    from app import extractor as ex
    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    monkeypatch.setattr(ex, "_harvest_page_sizes", fake_harvest)

    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")  # minimal placeholder; not parsed

    elements, out_dir = ex.parse(str(pdf), "doc-1")

    types = [e.element_type for e in elements]
    # Headings emitted in tree order; "header" structural noise skipped
    assert types[0] == "heading" and elements[0].content == "1. Strategie"
    assert types[1] == "heading" and elements[1].content == "1.2 Nachhaltigkeit"
    assert "text" in types and "table" in types and "list" in types and "image" in types
    assert "_skip" not in types  # structural noise filtered
    # Image element resolves source via os.path.join(out_dir, source)
    img = next(e for e in elements if e.element_type == "image")
    assert img.image_path.endswith("images/p5_i0.png")
    assert img.image_path.startswith(out_dir)
    # Table content is markdown
    tbl = next(e for e in elements if e.element_type == "table")
    assert tbl.content.startswith("| Jahr | Umsatz |")
    # Page sizes come from the harvested map
    assert elements[0].page_size == (612.0, 792.0)
```

- [ ] **Step 2: Run — expect FAIL.**

Ask user, then run: `docker compose -p ammer-mmragv2 run --rm --entrypoint pytest pdf-ingest tests/test_extractor.py::test_parse_walks_kids_and_normalizes_types -v`
Expected: `AttributeError: module 'app.extractor' has no attribute '_harvest_page_sizes'` (or `AttributeError: parse`).

- [ ] **Step 3: Add `_harvest_page_sizes`, `_run_opendataloader`, and `parse()` to `extractor.py`.**

Append to `services/pdf-ingest/app/extractor.py`:

```python
# ---------------------------------------------------------------------------
# Subprocess + page-size harvest
# ---------------------------------------------------------------------------
def _harvest_page_sizes(pdf_path: str) -> dict:
    """Read page dimensions from PyMuPDF — the JSON schema does not expose them."""
    sizes = {}
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            r = doc.load_page(i).rect
            sizes[i + 1] = (float(r.width), float(r.height))
    return sizes


def _run_opendataloader(pdf_path: str, out_dir: str) -> None:
    """Invoke the bundled JAR. subprocess.run(timeout=) kills the JVM on hang."""
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
    ]
    subprocess.run(
        args,
        check=True,
        timeout=OPENDATALOADER_TIMEOUT,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------
def parse(pdf_path: str, doc_id: str):
    """Parse PDF via opendataloader-pdf. Returns (elements, out_dir).

    Caller owns out_dir cleanup once images have been copied to ASSETS_DIR.
    """
    os.makedirs(OPENDATALOADER_TMP, exist_ok=True)
    out_dir = tempfile.mkdtemp(prefix=f"{doc_id}_", dir=OPENDATALOADER_TMP)
    page_sizes = _harvest_page_sizes(pdf_path)

    with _OPENDATALOADER_SEMAPHORE:
        _run_opendataloader(pdf_path, out_dir)

    stem = Path(pdf_path).stem
    json_path = Path(out_dir) / f"{stem}.json"
    if not json_path.exists():
        raise FileNotFoundError(f"opendataloader produced no JSON at {json_path}")
    doc = json.loads(json_path.read_text(encoding="utf-8"))

    elements = []
    default_size = (612.0, 792.0)

    def page_size_for(p):
        return page_sizes.get(p, default_size)

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
            elements.append(ParsedElement(
                element_type="table", page=page, bbox=bbox,
                page_size=page_size_for(page),
                content=_render_table_markdown(node),
                image_path=None,
                heading_level=None, raw_id=node.get("id"),
            ))
            return

        if norm == "list":
            elements.append(ParsedElement(
                element_type="list", page=page, bbox=bbox,
                page_size=page_size_for(page),
                content=_render_list_markdown(node),
                image_path=None,
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

- [ ] **Step 4: Re-run the parse test — expect PASS.**

Run: `docker compose -p ammer-mmragv2 build pdf-ingest && docker compose -p ammer-mmragv2 run --rm --entrypoint pytest pdf-ingest tests/test_extractor.py::test_parse_walks_kids_and_normalizes_types -v`
Expected: 1 passed.

- [ ] **Step 5: Commit.**

```bash
git add services/pdf-ingest/app/extractor.py services/pdf-ingest/tests/test_extractor.py
git commit -m "$(cat <<'EOF'
feat(pdf-ingest): implement extractor.parse()

Walks opendataloader-pdf JSON kids tree DFS, normalizes types, renders
tables/lists to markdown, resolves image source paths via
os.path.join(out_dir, source). Mocked-subprocess unit test confirms
field-name-with-spaces reads, image type variants, structural-noise
skipping, and page-size lookup from the PyMuPDF harvest.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: TDD `extractor.layout_to_chunks()`

**Goal:** Group consecutive text/list elements under the active heading path into `SectionChunk`s, prefix the breadcrumb, split at page boundaries with `(Forts.)` markers, emit `TableChunk`s with row-group splitting, emit `ImageChunk`s. Sentence-fallback for huge paragraphs.

**Files:**
- Modify: `services/pdf-ingest/app/extractor.py`
- Modify: `services/pdf-ingest/tests/test_extractor.py`

### Task 4.1 — Section accumulation + breadcrumb prefix

- [ ] **Step 1: Append failing test.**

```python
# ---- layout_to_chunks ----------------------------------------------------

def _make_el(et, page, content=None, level=None, bbox=(10, 20, 30, 40), raw_id=None):
    from app.extractor import ParsedElement
    return ParsedElement(
        element_type=et, page=page, bbox=bbox,
        page_size=(612.0, 792.0),
        content=content, image_path=None,
        heading_level=level, raw_id=raw_id,
    )


def test_section_chunk_has_breadcrumb_prefix():
    from app.extractor import layout_to_chunks
    elements = [
        _make_el("heading", 1, "1. Strategie", level=1, raw_id=1),
        _make_el("heading", 1, "1.2 Nachhaltigkeit", level=2, raw_id=2),
        _make_el("text", 1, "Die Gruppe verfolgt klare Klimaziele.", raw_id=3),
    ]
    chunks = layout_to_chunks(elements)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.chunk_type == "text"
    assert c.content_text.startswith("1. Strategie › 1.2 Nachhaltigkeit\n\n")
    assert "Die Gruppe verfolgt klare Klimaziele." in c.content_text
    assert c.meta["heading_path"] == ["1. Strategie", "1.2 Nachhaltigkeit"]
    assert c.meta["element_type"] == "section"
    assert c.meta["element_ids"] == [3]
    assert c.meta["bbox_units"] == "pdf_points"
    assert c.meta["bbox_order"] == "left,bottom,right,top"
    assert c.meta["extractor"] == "opendataloader-pdf@2.4.1"
    assert c.meta["split_strategy"] == "size"
    assert c.meta["page_size"] == [612.0, 792.0]
```

- [ ] **Step 2: Run — expect FAIL (`layout_to_chunks` not defined).**

Run: `docker compose -p ammer-mmragv2 run --rm --entrypoint pytest pdf-ingest tests/test_extractor.py::test_section_chunk_has_breadcrumb_prefix -v`

- [ ] **Step 3: Implement `layout_to_chunks` with section accumulation, plus `_make_image_chunk` and `_make_table_chunks` stubs.**

Append to `services/pdf-ingest/app/extractor.py`:

```python
# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def _union_bbox(bboxes):
    if not bboxes:
        return (0.0, 0.0, 0.0, 0.0)
    lefts = [b[0] for b in bboxes]
    bottoms = [b[1] for b in bboxes]
    rights = [b[2] for b in bboxes]
    tops = [b[3] for b in bboxes]
    return (min(lefts), min(bottoms), max(rights), max(tops))


def _section_meta(section, heading_stack, reason):
    return {
        "source": "pdf_text",
        "page": section[0].page,
        "element_type": "section",
        "element_ids": [e.raw_id for e in section if e.raw_id is not None],
        "heading_path": [t for _, t in heading_stack],
        "bbox": list(_union_bbox([e.bbox for e in section])),
        "bbox_units": "pdf_points",
        "bbox_order": "left,bottom,right,top",
        "page_size": list(section[0].page_size),
        "split_strategy": reason,
        "extractor": EXTRACTOR_VERSION,
    }


def _make_image_chunk(el, heading_stack):
    return Chunk(
        chunk_type="image",
        page=el.page,
        content_text=None,
        caption=None,
        asset_path=None,
        image_bytes=None,
        meta={
            "source": "pdf_image",
            "page": el.page,
            "element_type": "image",
            "element_ids": [el.raw_id] if el.raw_id is not None else [],
            "heading_path": [t for _, t in heading_stack],
            "bbox": list(el.bbox),
            "bbox_units": "pdf_points",
            "bbox_order": "left,bottom,right,top",
            "page_size": list(el.page_size),
            "extractor": EXTRACTOR_VERSION,
            # caller adds: image_sha256, image_index, asset_path, caption, embedding
            "_image_path": el.image_path,
        },
    )


def _table_chunk(el, heading_stack, body, split_strategy):
    return Chunk(
        chunk_type="text",
        page=el.page,
        content_text=body,
        caption=None,
        asset_path=None,
        image_bytes=None,
        meta={
            "source": "pdf_text",
            "page": el.page,
            "element_type": "table",
            "element_ids": [el.raw_id] if el.raw_id is not None else [],
            "heading_path": [t for _, t in heading_stack],
            "bbox": list(el.bbox),
            "bbox_units": "pdf_points",
            "bbox_order": "left,bottom,right,top",
            "page_size": list(el.page_size),
            "split_strategy": split_strategy,
            "extractor": EXTRACTOR_VERSION,
        },
    )


def _parse_md_table(md):
    """Inverse of _render_table_markdown: returns (header_line, [data_rows])."""
    lines = md.split("\n")
    if len(lines) < 2:
        return None, []
    header = lines[0]
    # lines[1] is the |---|---| separator
    rows = [ln for ln in lines[2:] if ln.strip()]
    return header, rows


def _make_table_chunks(el, heading_stack):
    md = el.content or ""
    breadcrumb = " › ".join(t for _, t in heading_stack)
    prefix = f"{breadcrumb}\n\n" if breadcrumb else ""

    if len(prefix + md) <= TABLE_HARD_LIMIT:
        return [_table_chunk(el, heading_stack, prefix + md, "intact")]

    header, rows = _parse_md_table(md)
    if not rows:
        parts = split_text(md, CHUNK_CHARS, CHUNK_OVERLAP)
        return [
            _table_chunk(el, heading_stack, prefix + p, "sentence_fallback")
            for p in parts
        ]

    chunks = []
    bucket = [header, "| " + " | ".join(["---"] * (header.count("|") - 1)) + " |"]
    bucket_len = len(prefix) + sum(len(x) for x in bucket)
    for row in rows:
        if bucket_len + len(row) > TABLE_HARD_LIMIT and len(bucket) > 2:
            chunks.append(_table_chunk(el, heading_stack,
                                       prefix + "\n".join(bucket),
                                       "row_groups"))
            bucket = [header,
                      "| " + " | ".join(["---"] * (header.count("|") - 1)) + " |",
                      row]
            bucket_len = len(prefix) + sum(len(x) for x in bucket)
        else:
            bucket.append(row)
            bucket_len += len(row)
    if len(bucket) > 2:
        chunks.append(_table_chunk(el, heading_stack,
                                   prefix + "\n".join(bucket),
                                   "row_groups"))
    return chunks


def layout_to_chunks(elements):
    chunks = []
    heading_stack = []  # list[(level, text)]
    section = []        # accumulating ParsedElement (text/list)
    section_page = None

    def flush_section(reason="size"):
        nonlocal section, section_page
        if not section:
            return
        breadcrumb = " › ".join(t for _, t in heading_stack)
        body = "\n\n".join(e.content for e in section if e.content)
        if reason == "page_continuation" and breadcrumb:
            prefix = f"{breadcrumb} (Forts.)\n\n"
        elif breadcrumb:
            prefix = f"{breadcrumb}\n\n"
        else:
            prefix = ""
        text = prefix + body
        # If the body itself overflows even after group-flushing, sentence-split.
        actual_reason = reason
        if len(text) > TABLE_HARD_LIMIT and len(section) == 1:
            for part in split_text(body, CHUNK_CHARS, CHUNK_OVERLAP):
                chunks.append(Chunk(
                    chunk_type="text",
                    page=section_page,
                    content_text=prefix + part,
                    caption=None, asset_path=None, image_bytes=None,
                    meta={**_section_meta(section, heading_stack, "sentence_fallback")},
                ))
            section = []
            section_page = None
            return
        chunks.append(Chunk(
            chunk_type="text",
            page=section_page,
            content_text=text,
            caption=None, asset_path=None, image_bytes=None,
            meta=_section_meta(section, heading_stack, actual_reason),
        ))
        section = []
        section_page = None

    for el in elements:
        if section and el.page != section_page:
            flush_section(reason="page_continuation")

        if el.element_type == "heading":
            flush_section()
            level = el.heading_level or 1
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, el.content or ""))
            continue

        if el.element_type == "image":
            flush_section()
            chunks.append(_make_image_chunk(el, heading_stack))
            continue

        if el.element_type == "table":
            flush_section()
            chunks.extend(_make_table_chunks(el, heading_stack))
            continue

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

- [ ] **Step 4: Run — expect PASS.**

Build then test: `docker compose -p ammer-mmragv2 build pdf-ingest && docker compose -p ammer-mmragv2 run --rm --entrypoint pytest pdf-ingest tests/test_extractor.py::test_section_chunk_has_breadcrumb_prefix -v`
Expected: 1 passed.

### Task 4.2 — Page boundary, image, table, sentence-fallback tests

- [ ] **Step 1: Append remaining tests.**

```python
def test_page_continuation_marks_forts():
    from app.extractor import layout_to_chunks
    elements = [
        _make_el("heading", 1, "Kapitel 1", level=1, raw_id=1),
        _make_el("text", 1, "Erster Absatz auf Seite 1.", raw_id=2),
        _make_el("text", 2, "Fortsetzung auf Seite 2.", raw_id=3),
    ]
    chunks = layout_to_chunks(elements)
    assert len(chunks) == 2
    # Spec §3.2: the section being flushed at a page boundary is marked
    # "page_continuation" — its breadcrumb gets (Forts.) to signal "this
    # content is interrupted; more on the next page". The new-page chunk
    # reverts to the default "size" reason.
    assert chunks[0].page == 1
    assert chunks[0].content_text.startswith("Kapitel 1 (Forts.)\n\n")
    assert chunks[0].meta["split_strategy"] == "page_continuation"
    assert chunks[1].page == 2
    assert chunks[1].content_text.startswith("Kapitel 1\n\n")
    assert chunks[1].meta["split_strategy"] == "size"


def test_size_split_falls_back_to_sentence_splitter():
    from app.extractor import layout_to_chunks, TABLE_HARD_LIMIT
    huge = ("Ein langer deutscher Satz. " * 1000)[:TABLE_HARD_LIMIT + 500]
    elements = [
        _make_el("heading", 1, "T", level=1, raw_id=1),
        _make_el("text", 1, huge, raw_id=2),
    ]
    chunks = layout_to_chunks(elements)
    assert len(chunks) >= 2
    assert all(c.meta["split_strategy"] == "sentence_fallback" for c in chunks)


def test_table_intact_when_small():
    from app.extractor import layout_to_chunks
    el = _make_el("table", 3, "| a | b |\n| --- | --- |\n| 1 | 2 |", raw_id=10)
    chunks = layout_to_chunks([el])
    assert len(chunks) == 1
    assert chunks[0].meta["element_type"] == "table"
    assert chunks[0].meta["split_strategy"] == "intact"
    assert chunks[0].content_text.startswith("| a | b |")


def test_table_row_groups_split_for_large_table():
    from app.extractor import layout_to_chunks, TABLE_HARD_LIMIT
    rows = "\n".join(f"| {i} | data{i} |" for i in range(2000))
    big_md = f"| col | val |\n| --- | --- |\n{rows}"
    assert len(big_md) > TABLE_HARD_LIMIT
    el = _make_el("table", 1, big_md, raw_id=11)
    chunks = layout_to_chunks([el])
    assert len(chunks) >= 2
    assert all(c.meta["split_strategy"] == "row_groups" for c in chunks)
    # Header row repeats on every continuation chunk
    for c in chunks:
        assert "| col | val |" in c.content_text


def test_image_chunk_carries_bbox_and_heading_path():
    from app.extractor import ParsedElement, layout_to_chunks
    elements = [
        _make_el("heading", 5, "Abbildungen", level=1, raw_id=1),
        ParsedElement(
            element_type="image", page=5, bbox=(100, 200, 400, 500),
            page_size=(612.0, 792.0),
            content=None, image_path="/tmp/odl/x/images/p5_i0.png",
            heading_level=None, raw_id=30,
        ),
    ]
    chunks = layout_to_chunks(elements)
    img = [c for c in chunks if c.chunk_type == "image"]
    assert len(img) == 1
    assert img[0].meta["bbox"] == [100.0, 200.0, 400.0, 500.0]
    assert img[0].meta["heading_path"] == ["Abbildungen"]
    assert img[0].meta["_image_path"] == "/tmp/odl/x/images/p5_i0.png"
```

- [ ] **Step 2: Run — expect 5 PASS.**

Run: `docker compose -p ammer-mmragv2 run --rm --entrypoint pytest pdf-ingest tests/test_extractor.py -v`
Expected: 14 passed (8 helpers + 1 parse + 5 new chunking tests).

- [ ] **Step 3: Commit.**

```bash
git add services/pdf-ingest/app/extractor.py services/pdf-ingest/tests/test_extractor.py
git commit -m "$(cat <<'EOF'
feat(pdf-ingest): implement layout_to_chunks with breadcrumbs + table split

Section-based chunking accumulates consecutive text/list elements under
the active heading path; flushes at page boundaries with a (Forts.)
breadcrumb suffix; emits ImageChunk and TableChunk separately.
Tables split via row_groups (header repeats per continuation) once they
exceed TABLE_HARD_LIMIT (4× CHUNK_CHARS = 6000); paragraphs that
overflow fall through to the German sentence splitter.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5: External Image Filter + Java Startup Check

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

### Task 5.1 — Add `_should_skip_external_image` and Java startup check

- [ ] **Step 1: Add the helper near the existing `_should_skip_image` (around line 102 in main.py).**

In `services/pdf-ingest/app/main.py`, *immediately after* `_should_skip_image` (line 110), add:

```python
def _should_skip_external_image(path: str, seen_hashes: set) -> tuple[bool, str | None]:
    """For opendataloader's externalized images. Returns (skip, sha256_or_None).
    Mirrors _should_skip_image's intent (size + dedup) but reads the file from
    disk instead of an in-memory base dict.
    """
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

- [ ] **Step 2: Add the Java startup check inside `lifespan()`.**

In `services/pdf-ingest/app/main.py`, edit `lifespan()` (line 152). After `ensure_dirs()` (line 159) and before the connection-pool `conninfo = ...` line (currently line 162), insert:

```python
    # Fail fast if the JRE used by opendataloader-pdf is missing
    import subprocess as _sp
    try:
        _sp.run(["java", "-version"], check=True, capture_output=True, timeout=5)
        logger.info("Java runtime verified")
    except Exception as e:
        logger.error("Java runtime not available: %s", e)
        raise RuntimeError("Java 17+ required for opendataloader-pdf") from e
```

- [ ] **Step 3: Build & confirm container starts.**

Ask user, then run: `docker compose -p ammer-mmragv2 build pdf-ingest && docker compose -p ammer-mmragv2 up -d pdf-ingest`
Expected: container reaches `healthy` within ~15s. Run `docker compose -p ammer-mmragv2 logs --tail 30 pdf-ingest` and confirm a `"Java runtime verified"` log line appears before the `"Connection pool initialized"` line.

- [ ] **Step 4: Commit.**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "$(cat <<'EOF'
feat(pdf-ingest): java startup check + external-image skip helper

Lifespan now fails fast if 'java -version' isn't available (the
opendataloader JAR can't run without it). Adds
_should_skip_external_image() — disk-backed sibling of
_should_skip_image — ahead of the main.py wire-up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6: Wire `extractor` Into `extract_and_store`

**Goal:** Replace the per-page fitz loop in `extract_and_store` with `extractor.parse(...)` + `extractor.layout_to_chunks(...)`. Extend the caption queue tuple with `meta_extra`. Add a `finally` block that cleans up the temp dir.

**Files:**
- Modify: `services/pdf-ingest/app/main.py`

### Task 6.1 — Replace `extract_and_store` body

- [ ] **Step 1: Update the imports.**

In `services/pdf-ingest/app/main.py`, find the imports block (around line 15). Add:

```python
from . import extractor as _extractor
```

(Place it next to the other internal imports, e.g. right after `from .splitter import split_text`.)

- [ ] **Step 2: Update `_caption_worker` to pass `meta_extra` through.**

Currently the queue tuple is 8-wide (`doc_id, page, im_i, img_bytes, lang, asset_name, cancel_event, result_q`). Change it to 9-wide by inserting `meta_extra` before `cancel_event`. Edit the comment around line 345 to:

```python
# Queue items: (doc_id, page, im_i, img_bytes, lang, asset_name, meta_extra, cancel_event, result_q)
```

Then in `_caption_worker` (line 348), change the unpack at line 356 from:

```python
        doc_id, page, im_i, img_bytes, lang, asset_name, cancel_event, result_q = item
```

to:

```python
        doc_id, page, im_i, img_bytes, lang, asset_name, meta_extra, cancel_event, result_q = item
```

And change the `result_q.put` calls (lines 364 and 368) to include `meta_extra` at the end:

```python
            result_q.put((page, im_i, caption, asset_name, emb, meta_extra))
```

```python
            result_q.put((page, im_i, "", asset_name, None, meta_extra))
```

- [ ] **Step 3: Replace the fitz loop in `extract_and_store` with the extractor call.**

In `services/pdf-ingest/app/main.py`, replace the existing `extract_and_store` function (lines 436-560) with the following body. The sha256, status counters, and DB-write structure stay the same; only the extraction loop and caption-result handling change.

```python
def extract_and_store(pdf_path: str, doc_id: uuid.UUID, lang: str) -> Dict[str, Any]:
    ensure_dirs()
    filename = os.path.basename(pdf_path)
    sha = sha256_file(pdf_path)
    t0 = _time.monotonic()

    stats = {"filename": filename, "doc_id": str(doc_id), "sha256": sha,
             "pages": 0, "text_chunks": 0, "images": 0, "skipped_images": 0}

    out_dir = None  # set after parse(); cleaned up in finally
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                process, _prev = should_process(cur, doc_id, sha)
                if not process:
                    return {"status": "skipped", "reason": "already_ingested", **stats}

                delete_doc_chunks(cur, doc_id)

                # Parse PDF (subprocess JAR call) — also sets out_dir for image source paths
                elements, out_dir = _extractor.parse(pdf_path, str(doc_id))

                # Page count from PyMuPDF (used by upsert_doc) — extractor doesn't expose it
                with fitz.open(pdf_path) as fdoc:
                    total_pages = fdoc.page_count
                if MAX_PAGES > 0:
                    total_pages = min(total_pages, MAX_PAGES)
                stats["pages"] = total_pages
                upsert_doc(cur, doc_id, filename, sha, lang, total_pages)
                logger.info("Ingestion started: %s (%d pages)", filename, total_pages)

                chunks = _extractor.layout_to_chunks(elements)

                written_assets: List[str] = []
                cancel_event = threading.Event()
                result_q: queue.Queue = queue.Queue()
                seen_hashes: set = set()
                images_queued = 0

                # --- Phase 1: text/table chunks → embed + insert -----------
                text_chunks = [c for c in chunks if c.chunk_type == "text"]
                texts = [c.content_text for c in text_chunks]
                if texts:
                    text_embeddings = ollama_embed_batch(texts)
                    for c, emb in zip(text_chunks, text_embeddings):
                        insert_chunk(
                            cur, doc_id, "text", c.page,
                            c.content_text, None, None, emb,
                            c.meta,
                        )
                    stats["text_chunks"] = len(text_chunks)
                    _inc("completed_text_chunks", len(text_chunks))

                # --- Phase 2: image chunks → filter + downscale + queue ----
                image_chunks = [c for c in chunks if c.chunk_type == "image"]
                # Track per-page index for asset naming
                page_idx_counter: Dict[int, int] = {}
                for c in image_chunks:
                    src_path = c.meta.pop("_image_path", None)
                    if not src_path:
                        stats["skipped_images"] += 1
                        _inc("skipped_images")
                        continue

                    skip, sha_img = _should_skip_external_image(src_path, seen_hashes)
                    if skip:
                        stats["skipped_images"] += 1
                        _inc("skipped_images")
                        continue
                    seen_hashes.add(sha_img)

                    with open(src_path, "rb") as f:
                        raw = f.read()
                    img_bytes, ext = downscale_image(raw)

                    im_i = page_idx_counter.get(c.page, 0)
                    page_idx_counter[c.page] = im_i + 1
                    asset_name = f"{doc_id}_p{c.page}_i{im_i}.{ext}"
                    asset_path = os.path.join(ASSETS_DIR, asset_name)
                    with open(asset_path, "wb") as f:
                        f.write(img_bytes)
                    written_assets.append(asset_path)

                    meta_extra = {
                        **c.meta,
                        "image_index": im_i,
                        "image_sha256": sha_img,
                    }

                    caption_q.put(
                        (doc_id, c.page, im_i, img_bytes, lang, asset_name,
                         meta_extra, cancel_event, result_q),
                        block=True,
                    )
                    images_queued += 1

                # --- Phase 3: wait for caption results ---------------------
                caption_results = []
                deadline = _time.monotonic() + DOC_TIMEOUT
                while len(caption_results) < images_queued:
                    remaining = deadline - _time.monotonic()
                    if remaining <= 0:
                        logger.error("Document timeout (%ds) for %s — %d/%d images done",
                                     DOC_TIMEOUT, filename, len(caption_results), images_queued)
                        cancel_event.set()
                        break
                    try:
                        result = result_q.get(timeout=min(remaining, 5))
                        caption_results.append(result)
                    except queue.Empty:
                        continue

                # --- Phase 4: insert image chunks --------------------------
                for page_no, im_i, caption, asset_name, emb, meta_extra in caption_results:
                    insert_chunk(
                        cur, doc_id, "image", page_no, None, caption, asset_name, emb,
                        meta_extra,
                    )
                stats["images"] = len(caption_results)

                conn.commit()
    except Exception:
        # If we got far enough to enqueue images, signal workers to stop
        try:
            cancel_event.set()
        except UnboundLocalError:
            pass
        try:
            for path in written_assets:  # type: ignore[name-defined]
                try:
                    os.remove(path)
                except OSError:
                    pass
        except UnboundLocalError:
            pass
        logger.warning("Ingestion failed for %s — rolled back", filename)
        raise
    finally:
        if out_dir:
            shutil.rmtree(out_dir, ignore_errors=True)

    elapsed = _time.monotonic() - t0
    logger.info("Ingestion complete: %s — %d text chunks, %d images in %.1fs",
                filename, stats["text_chunks"], stats["images"], elapsed)
    return {"status": "ingested", **stats}
```

- [ ] **Step 4: Bump the FastAPI version label.**

Edit `services/pdf-ingest/app/main.py`, line 198:

```python
app = FastAPI(title="pdf-ingest", version="0.6.0", lifespan=lifespan)
```

And the matching log line (around line 184):

```python
    logger.info("pdf-ingest v0.6.0 starting (parallel: %d docs, %d caption workers, queue=%d)",
                MAX_CONCURRENT_DOCS, MAX_CAPTION_WORKERS, CAPTION_QUEUE_SIZE)
```

- [ ] **Step 5: Build & verify container starts and old tests still pass.**

Ask user, then run: `docker compose -p ammer-mmragv2 build pdf-ingest && docker compose -p ammer-mmragv2 up -d pdf-ingest`
Then: `docker compose -p ammer-mmragv2 run --rm --entrypoint pytest pdf-ingest tests/test_extractor.py -v`
Expected: 14 passed. Logs show "Java runtime verified" + "pdf-ingest v0.6.0 starting".

- [ ] **Step 6: Commit.**

```bash
git add services/pdf-ingest/app/main.py
git commit -m "$(cat <<'EOF'
feat(pdf-ingest): wire opendataloader extractor into extract_and_store

Replaces the per-page fitz loop with extractor.parse() +
layout_to_chunks(). Caption queue tuple grows from 8 to 9 fields
(meta_extra carries bbox/heading_path/sha256 through the worker).
Adds finally-block tempdir cleanup and bumps app version to 0.6.0.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 7: docker-compose.yml Env Vars

**Files:**
- Modify: `docker-compose.yml`

### Task 7.1 — Add OPENDATALOADER_* env vars

- [ ] **Step 1: Edit the `pdf-ingest.environment` block.**

In `docker-compose.yml`, find the `pdf-ingest:` service block (line 120). After line 152 (`CHUNK_OVERLAP_CHARS: "200"`), add:

```yaml
      OPENDATALOADER_MAX_PARALLEL: "1"
      OPENDATALOADER_TIMEOUT: "300"
      OPENDATALOADER_TMP_DIR: "/tmp/odl"
      OPENDATALOADER_JAVA_OPTS: "-Xmx2g"
```

- [ ] **Step 2: Validate the compose file parses.**

Run: `docker compose -p ammer-mmragv2 config --services`
Expected: 11 service names listed (postgres, ollama, n8n, pdf-ingest, ...). No YAML error.

- [ ] **Step 3: Ask user to restart pdf-ingest to pick up env vars, then verify.**

```text
About to run:
  docker compose -p ammer-mmragv2 up -d pdf-ingest
This recreates the pdf-ingest container with the new env vars. Existing volumes preserved. OK?
```

After confirmation: `docker compose -p ammer-mmragv2 up -d pdf-ingest`
Then: `docker compose -p ammer-mmragv2 exec -T pdf-ingest env | grep OPENDATALOADER`
Expected: 4 lines printed.

- [ ] **Step 4: Commit.**

```bash
git add docker-compose.yml
git commit -m "$(cat <<'EOF'
feat(compose): OPENDATALOADER_* env vars on pdf-ingest

MAX_PARALLEL=1 (semaphore caps concurrent JAR runs)
TIMEOUT=300s (subprocess.run timeout — kills hung JVM)
TMP_DIR=/tmp/odl (parent of per-run mkdtemp dirs)
JAVA_OPTS=-Xmx2g (heap cap so JVM can't OOM the host)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 8: scripts/reprocess_pdfs.sh (with INTERACTIVE PROMPT)

**Files:**
- Create: `scripts/reprocess_pdfs.sh`

**This is caution #2.** The script must require BOTH `--confirm` AND an interactive `read -r` confirmation typing literal `yes`. This prevents another script (or hook) from invoking it silently.

### Task 8.1 — Create the script

- [ ] **Step 1: Write the file.**

Create `scripts/reprocess_pdfs.sh`:

```bash
#!/usr/bin/env bash
# Reprocess all PDFs in data/processed/ through the new opendataloader pipeline.
# Snapshots DB, quarantines old assets (NOT deletes), removes old chunks/docs,
# moves PDFs to inbox; the file watcher takes them from there.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" != "--confirm" ]]; then
  echo "Refusing to run without --confirm."
  echo "Quarantines assets + deletes chunks/docs for all PDFs in data/processed/."
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
  echo "Refusing — active_docs=$active caption_queue_size=$qsize"
  exit 1
fi

# 2. Compute doc_ids deterministically from filenames in data/processed/
mapfile -t pdfs < <(find data/processed -maxdepth 1 -name '*.pdf' -printf '%f\n')
if [[ ${#pdfs[@]} -eq 0 ]]; then
  echo "No PDFs in data/processed/"; exit 1
fi

declare -a doc_ids
for fn in "${pdfs[@]}"; do
  did=$(python3 -c "import uuid,sys; print(uuid.uuid5(uuid.NAMESPACE_URL, 'mmrag:' + sys.argv[1]))" "$fn")
  doc_ids+=("$did")
done

# 3. EXPLICIT INTERACTIVE PROMPT — required even with --confirm.
ts=$(date +%Y%m%d_%H%M%S)
quarantine="_pre_opendataloader_${ts}"
echo ""
echo "=========================================================================="
echo "  REPROCESS PLAN — OpenDataLoader-PDF integration (PDF re-extraction)"
echo "=========================================================================="
echo "PDFs to reprocess (${#pdfs[@]}):"
for i in "${!pdfs[@]}"; do
  echo "  - ${pdfs[$i]}  (doc_id=${doc_ids[$i]})"
done
echo ""
echo "Will:"
echo "  1. pg_dump rag_docs + rag_chunks → data/demo_snapshot_pre_opendataloader_${ts}.sql"
echo "  2. Move asset files <doc_id>_p*_i*.* → data/assets/${quarantine}/"
echo "  3. DELETE FROM rag_chunks WHERE doc_id IN (the doc_ids above)"
echo "  4. DELETE FROM rag_docs   WHERE doc_id IN (the doc_ids above)"
echo "  5. mv data/processed/*.pdf → data/inbox/  (watcher picks up)"
echo ""
echo "Rollback path: restore the snapshot + move quarantined assets back."
echo "=========================================================================="
read -r -p 'Type "yes" to proceed (anything else aborts): ' answer
if [[ "$answer" != "yes" ]]; then
  echo "Aborted."
  exit 1
fi

# 4. Timestamped DB snapshot (rag_docs + rag_chunks)
snap="data/demo_snapshot_pre_opendataloader_${ts}.sql"
docker compose -p "$PROJECT" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" \
    --table=rag_docs --table=rag_chunks --no-owner --no-privileges \
  > "$snap"
[[ -s "$snap" ]] || { echo "Snapshot empty — abort"; exit 1; }
echo "Snapshot: $snap ($(du -h "$snap" | cut -f1))"

# 5. Quarantine assets (NOT delete) and remove DB rows for those doc_ids
docker compose -p "$PROJECT" exec -T pdf-ingest mkdir -p "/kb/assets/${quarantine}"
for did in "${doc_ids[@]}"; do
  docker compose -p "$PROJECT" exec -T pdf-ingest sh -c \
    "find /kb/assets -maxdepth 1 -name '${did}_p*_i*.*' -exec mv -t /kb/assets/${quarantine} {} +" \
    || true
  "${PSQL[@]}" -c "DELETE FROM rag_chunks WHERE doc_id='$did';" >/dev/null
  "${PSQL[@]}" -c "DELETE FROM rag_docs   WHERE doc_id='$did';" >/dev/null
done

# 6. Move PDFs back to inbox; watcher picks them up
mv data/processed/*.pdf data/inbox/
echo "Reprocess queued. Quarantine: data/assets/${quarantine}/"
echo "Watch:  docker compose -p $PROJECT logs -f pdf-ingest"
```

- [ ] **Step 2: Make it executable.**

Run: `chmod +x scripts/reprocess_pdfs.sh`

- [ ] **Step 3: Test the gating without running the destructive parts.**

Run (no args): `bash scripts/reprocess_pdfs.sh`
Expected: prints `Refusing to run without --confirm.` and exits non-zero.

Run: `echo "no" | bash scripts/reprocess_pdfs.sh --confirm`
Expected: prints the plan, prompt, then `Aborted.` and exits non-zero. **No snapshot file is created**, **no DELETEs run**, **no PDFs move**. Verify by:
- `ls data/demo_snapshot_pre_opendataloader_*.sql 2>/dev/null` → should output nothing (or only pre-existing ones from earlier runs)
- `ls data/inbox/` → empty (or only files that were already there)
- Asset count unchanged

- [ ] **Step 4: Commit.**

```bash
git add scripts/reprocess_pdfs.sh
git commit -m "$(cat <<'EOF'
feat(scripts): reprocess_pdfs.sh — gated reprocess for opendataloader rollout

Requires both --confirm flag AND an interactive 'yes' prompt printing
the doc_ids and quarantine target. Snapshots rag_docs + rag_chunks,
quarantines (does not delete) old asset files, removes affected DB
rows, and moves PDFs back to inbox so the file watcher re-ingests
them through the new opendataloader pipeline.

Refuses to run if active_docs > 0 or caption queue is non-empty.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 9: scripts/demo_readiness_check.sh — Append Check #16

**Files:**
- Modify: `scripts/demo_readiness_check.sh`

### Task 9.1 — Append the new check

- [ ] **Step 1: Insert the check before the final `# ── Summary ──` section.**

In `scripts/demo_readiness_check.sh`, find the line `# ── Summary ──────────────────────────────────────────────────────────────` (around line 145). Immediately *before* that line and the blank line above it, add:

```bash
# ── 16. opendataloader integration ───────────────────────────────────────
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
  fail "no chunks carry meta.bbox — opendataloader pipeline did not produce structure metadata"
fi

```

(Note: trailing blank line is intentional — separates from the summary block below.)

- [ ] **Step 2: Run the script as-is to confirm it parses and the new check fails (since no PDFs have been re-ingested yet).**

Run: `bash scripts/demo_readiness_check.sh || true`
Expected: prints all 15 existing checks plus a new `== 16. opendataloader integration ==` block. The Java check should pass (container has the JRE). The bbox check should fail (`no chunks carry meta.bbox`). **Total FAIL count is 1 (the bbox count).** This is expected; Phase 11 will fix it.

- [ ] **Step 3: Commit.**

```bash
git add scripts/demo_readiness_check.sh
git commit -m "$(cat <<'EOF'
test(demo-readiness): check #16 — Java + meta.bbox presence

Two-step check on the opendataloader rollout: (1) Java is installed
in the pdf-ingest container; (2) at least one rag_chunks row has
meta ? 'bbox'. Will fail until reprocess_pdfs.sh runs in Phase 11.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 10: MANUAL_STEPS.md — D24 Entry

**Files:**
- Modify: `MANUAL_STEPS.md`

### Task 10.1 — Append D24

- [ ] **Step 1: Append a new row at the bottom of the deviations table.**

In `MANUAL_STEPS.md`, find the existing table heading `## Deployment Deviations from Spec (v2.4) — 21 items` and update the count. Then append after the last `D19` row (the table is markdown — append a row before any trailing content):

Header line: change `21 items` to `22 items`.

Append at end of the table:

```markdown
| D24 | PyMuPDF text extraction in pdf-ingest | Replaced with opendataloader-pdf 2.4.1 (local mode); section-based chunking with heading-path breadcrumbs replaces the 1500-char sliding window | OpenJDK 17 JRE in pdf-ingest container. Bounding boxes, page sizes, heading paths, element ids, and split-strategy provenance stored in `rag_chunks.meta` (JSONB; no schema migration). PyMuPDF retained for `downscale_image()` and external-image dimension reads. Re-processing of all PDFs in `data/processed/` (5 at time of writing — 4 production + `watcher_test.pdf`) performed via `scripts/reprocess_pdfs.sh --confirm` after `data/demo_snapshot_pre_opendataloader_<ts>.sql` snapshot and `data/assets/_pre_opendataloader_<ts>/` asset quarantine. Embedding model (bge-m3, 1024d) and vision model (qwen2.5vl:7b) unchanged. |
```

- [ ] **Step 2: Commit.**

```bash
git add MANUAL_STEPS.md
git commit -m "$(cat <<'EOF'
docs: D24 — opendataloader-pdf replaces PyMuPDF text extraction

22nd deviation entry. Section-based chunking with heading-path
breadcrumbs; bounding boxes + page sizes + structural provenance in
rag_chunks.meta (no schema migration). bge-m3 and qwen2.5vl:7b
unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 11: Full Corpus Reprocess + Demo Prompt Eyeball

**Goal:** Run the reprocess script. Watch `watcher_test.pdf` as the canary. Verify `meta.bbox` and `meta.heading_path` get populated. Run the four production demo prompts and eyeball quality.

**Files:** None modified (this phase is verification only).

### Task 11.1 — Pre-flight

- [ ] **Step 1: Confirm the stack is healthy.**

Run: `bash scripts/demo_readiness_check.sh`
Expected: 15 PASSes, 1 FAIL (check #16's bbox count — expected at this point).

If anything else fails, stop and resolve before reprocessing.

- [ ] **Step 2: Confirm pdf-ingest is idle.**

Run: `docker compose -p ammer-mmragv2 exec -T pdf-ingest curl -sf http://localhost:8001/ingest/status | python3 -m json.tool`
Expected: `"active_docs": 0`, `"caption_queue_size": 0`.

### Task 11.2 — Run the reprocess

- [ ] **Step 1: Ask user before kicking off the reprocess.**

```text
About to run:
  bash scripts/reprocess_pdfs.sh --confirm
This will:
- Snapshot rag_docs + rag_chunks to data/demo_snapshot_pre_opendataloader_<ts>.sql
- Quarantine ~<count> existing PDF asset files to data/assets/_pre_opendataloader_<ts>/
- DELETE the 5 PDF doc_ids' chunks/docs
- Move all 5 PDFs from data/processed/ → data/inbox/

The watcher will then re-ingest them. watcher_test.pdf finishes first
(it's a tiny canary), then BMW Group, Siemens × 2, TechVision.
Expected total runtime: ~10-20 minutes depending on Ollama throughput.

You'll need to type "yes" at the script's interactive prompt.
OK to proceed?
```

- [ ] **Step 2: After confirmation, run the script.**

Run: `bash scripts/reprocess_pdfs.sh --confirm`
At the prompt, type `yes` and press enter.

Expected:
- Snapshot file created: `ls -lh data/demo_snapshot_pre_opendataloader_*.sql`
- 5 PDFs now in `data/inbox/`: `ls data/inbox/`
- Quarantine dir exists with old assets: `docker compose -p ammer-mmragv2 exec -T pdf-ingest ls /kb/assets/_pre_opendataloader_*/ | head`

- [ ] **Step 3: Watch logs and wait.**

Run (in a separate terminal or background): `docker compose -p ammer-mmragv2 logs -f pdf-ingest`

Watch for:
- `"Ingestion started: watcher_test.pdf"` (canary, fast)
- `"Ingestion complete: watcher_test.pdf"` followed by the others

Poll status every minute: `docker compose -p ammer-mmragv2 exec -T pdf-ingest curl -sf http://localhost:8001/ingest/status | python3 -m json.tool`
When `active_docs == 0` and inbox is empty, the reprocess is done.

### Task 11.3 — Verification

- [ ] **Step 1: Run the demo readiness check.**

Run: `bash scripts/demo_readiness_check.sh`
Expected: all 16 checks pass, including `== 16. opendataloader integration ==` reporting `<N> chunks carry meta.bbox` where N is in the hundreds.

- [ ] **Step 2: Spot-check a chunk's meta.**

Run:
```bash
docker compose -p ammer-mmragv2 exec -T \
  -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" -c \
  "SELECT chunk_type, page, jsonb_pretty(meta) FROM rag_chunks
   WHERE meta ? 'bbox' AND meta->>'extractor' = 'opendataloader-pdf@2.4.1'
   ORDER BY random() LIMIT 1;"
```

Expected: a row whose `meta` JSON contains all of: `bbox`, `bbox_units`="pdf_points", `bbox_order`="left,bottom,right,top", `page_size`, `heading_path` (list of strings), `element_ids`, `split_strategy`, `extractor`="opendataloader-pdf@2.4.1".

- [ ] **Step 3: Eyeball baseline retrieval quality.**

Run all four demo prompts (replace newlines with spaces in the actual curl):
```bash
for q in \
  "@TechVision Welche Risiken nennt der Bericht?" \
  "@BMWGroup Was sind die wichtigsten Nachhaltigkeitsziele?" \
  "@Nachhaltigkeit Welche Maßnahmen ergreift Siemens für Klimaneutralität?" \
  "@Siemens-Annual Report Welche Geschäftsbereiche zeigen Wachstum?"
do
  echo "--- Q: $q ---"
  curl -s -m 60 -X POST http://127.0.0.1:56155/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$q")}],\"stream\":false}" \
    | python3 -c "import json,sys; r=json.load(sys.stdin); print(r['choices'][0]['message']['content'][:800])"
  echo ""
done
```

Expected: each answer cites the correct PDF, mentions section/heading context, and image references resolve. Compare informally against the pre-reprocess answers (the team's existing demo notes).

- [ ] **Step 4: If quality is acceptable, ask the user about cleanup.**

```text
Reprocess complete and verified:
- 16/16 readiness checks pass
- <N> chunks have meta.bbox / heading_path
- Demo prompts return relevant content with structural metadata

Two artifacts kept for rollback:
- data/demo_snapshot_pre_opendataloader_<ts>.sql (~<size>)
- data/assets/_pre_opendataloader_<ts>/ in the pdf-ingest container

Recommend keeping both for one demo cycle. Cleanup commands when ready:
  rm data/demo_snapshot_pre_opendataloader_<ts>.sql
  docker compose -p ammer-mmragv2 exec -T pdf-ingest rm -rf /kb/assets/_pre_opendataloader_<ts>

Should I delete now, or leave for after Sven's session?
```

Default: leave both in place. Only delete on explicit user instruction.

- [ ] **Step 5: Final commit (only if any artifacts changed during verification — typically nothing to commit here).**

If logs/output revealed any small follow-ups (e.g. typo in MANUAL_STEPS.md, missed env var), commit them as a final cleanup commit. Otherwise skip.

---

## Rollback Procedure (Reference — only if Phase 11 fails)

If the reprocess produces broken chunks or the demo prompts regress badly, follow the spec's §10 rollback (mirrors `scripts/restore_snapshot.sh`):

```bash
# 1. Halt ingestion
docker compose -p ammer-mmragv2 stop pdf-ingest

# 2. Truncate
docker compose -p ammer-mmragv2 exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" \
  -c "TRUNCATE rag_chunks, rag_docs CASCADE;"

# 3. Restore from snapshot
docker compose -p ammer-mmragv2 exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$RAG_DB" \
  < data/demo_snapshot_pre_opendataloader_<ts>.sql

# 4. Restore quarantined assets
docker compose -p ammer-mmragv2 exec -T pdf-ingest sh -c \
  "mv /kb/assets/_pre_opendataloader_<ts>/* /kb/assets/ && rmdir /kb/assets/_pre_opendataloader_<ts>"

# 5. Move PDFs back to processed/ so the watcher doesn't re-trigger
#    (only PDFs the user does not want to re-ingest under the new pipeline)
# git revert the integration commits if you also want to roll back code.

# 6. Restart pdf-ingest
docker compose -p ammer-mmragv2 start pdf-ingest
```

---

## Spec Coverage Self-Review

| Spec section | Implemented in |
|---|---|
| §2 architecture / data flow | Phase 6 (extract_and_store wire-up) |
| §2 file table | All phases (each row has a target task) |
| §3.1 `parse()` adapter | Phase 3 |
| §3.1 `_collect_text` | Task 3.2 (helper test + impl) |
| §3.1 `_render_table_markdown` | Task 3.2 |
| §3.1 `_render_list_markdown` | Task 3.2 |
| §3.2 `layout_to_chunks` | Phase 4 |
| §3.3 table splitting | Task 4.2 (`_make_table_chunks`, row_groups + sentence_fallback) |
| §3.4 breadcrumb format ` › `, `(Forts.)` | Task 4.1 + 4.2 |
| §4.1 image flow | Phase 6 (Phase 2 of the rewritten extract_and_store) |
| §4.2 `_should_skip_external_image` | Phase 5 |
| §4.3 caption queue tuple change | Phase 6 (Task 6.1, _caption_worker unpack + insert_chunk meta merge) |
| §5 schema (no migration) | Implicit — `insert_chunk(... meta=...)` in Phase 6 |
| §5.2 new meta keys | Phase 4 (`_section_meta`, `_make_image_chunk`) + Phase 6 (image_index, image_sha256 added) |
| §6.1 Dockerfile | Phase 0 |
| §6.2 Java startup check | Phase 5 |
| §6.3 compose env vars | Phase 7 |
| §7 reprocess | Phase 8 + Phase 11 |
| §7.2 `reprocess_pdfs.sh` (with **interactive prompt** for caution #2) | Phase 8 |
| §7.3 order of operations | Phase 11 |
| §8 error handling fallback | Implemented in `extract_and_store`: OpenDataLoader/JAR/zero-chunk failure logs the error and falls back to the legacy PyMuPDF path with fallback metadata instead of losing the document. |
| §9.1 unit tests (10 listed) | Phase 3 + Phase 4 (8 helper + 1 parse + 5 chunking = 14 tests, covering all 10 requirements) |
| §9.2 integration smoke | Phase 11 (`watcher_test.pdf` is the canary in the natural reprocess order) |
| §9.3 readiness check #16 | Phase 9 |
| §10 rollout | Phase 11 |
| §10 rollback | Reference section above (TRUNCATE-then-restore + quarantine restore) |
| §12 deviation D24 | Phase 10 |

**Remaining caveat:** BMW Group text extraction contains 486 chunks that could not be embedded because the extracted text was too noisy for Ollama's embedding endpoint. They are preserved for auditability with `meta.embedding_error`; BMW image chunks and PDF bounding-box metadata are present.
