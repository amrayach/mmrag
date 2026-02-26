import base64
import hashlib
import json
import logging
import os
import re
import shutil
import time as _time
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import psycopg
import requests
from fastapi import FastAPI, File, UploadFile
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

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
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

INBOX_DIR = os.getenv("INBOX_DIR", "/kb/inbox")
PROCESSED_DIR = os.getenv("PROCESSED_DIR", "/kb/processed")
ASSETS_DIR = os.getenv("ASSETS_DIR", "/kb/assets")

MAX_DOCS_PER_SCAN = int(os.getenv("MAX_DOCS_PER_SCAN", "1"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "0"))
MAX_IMAGES_PER_PAGE = int(os.getenv("MAX_IMAGES_PER_PAGE", "5"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))

LOCK_FILE = os.getenv("LOCK_FILE", "/tmp/pdf_ingest.lock")

# ---------------------------------------------------------------------------
# Connection pool (initialized in lifespan)
# ---------------------------------------------------------------------------
pool: Optional[ConnectionPool] = None

# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app):
    global pool
    # Startup: clean stale lock (container restart = previous worker is dead)
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
        logger.info("Stale lock removed on startup")

    # Init connection pool
    conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS}"
    pool = ConnectionPool(
        conninfo, min_size=2, max_size=3, open=True,
        configure=lambda conn: register_vector(conn),
    )
    logger.info("Connection pool initialized (min=2, max=3)")
    logger.info("pdf-ingest starting")
    yield
    pool.close()
    logger.info("pdf-ingest shutting down")


app = FastAPI(title="pdf-ingest", version="0.4.0", lifespan=lifespan)

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
    for d in [INBOX_DIR, PROCESSED_DIR, ASSETS_DIR]:
        os.makedirs(d, exist_ok=True)


@contextmanager
def ingestion_lock():
    ensure_dirs()
    if os.path.exists(LOCK_FILE):
        raise RuntimeError("busy")
    try:
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        yield
    finally:
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass


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
    }
    resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=180)
    resp.raise_for_status()
    return (resp.json().get("message", {}) or {}).get("content", "").strip()


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

    stats = {"filename": filename, "doc_id": str(doc_id), "sha256": sha, "pages": 0, "text_chunks": 0, "images": 0}

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

            try:
                for pno in range(total_pages):
                    page = doc.load_page(pno)
                    text = page.get_text("text") or ""
                    text_chunks = split_text(text, CHUNK_CHARS, CHUNK_OVERLAP)

                    for idx, chunk in enumerate(text_chunks):
                        emb = _retry(lambda c=chunk: ollama_embeddings(c))
                        insert_chunk(
                            cur, doc_id, "text", pno + 1, chunk, None, None, emb,
                            {"source": "pdf_text", "page": pno + 1, "chunk_index": idx},
                        )
                    stats["text_chunks"] += len(text_chunks)

                    images = (page.get_images(full=True) or [])[:MAX_IMAGES_PER_PAGE]
                    for im_i, img in enumerate(images):
                        xref = img[0]
                        base = doc.extract_image(xref)
                        img_bytes = base["image"]
                        ext = base.get("ext", "png")

                        asset_name = f"{doc_id}_p{pno+1}_i{im_i}.{ext}"
                        asset_path = os.path.join(ASSETS_DIR, asset_name)
                        with open(asset_path, "wb") as f:
                            f.write(img_bytes)
                        written_assets.append(asset_path)

                        caption = _retry(lambda ib=img_bytes, la=lang: ollama_caption_image(ib, la))
                        emb = _retry(lambda c=caption: ollama_embeddings(c)) if caption else None

                        insert_chunk(
                            cur, doc_id, "image", pno + 1, None, caption, asset_name, emb,
                            {"source": "pdf_image", "page": pno + 1, "image_index": im_i},
                        )
                        stats["images"] += 1

                    img_count = len(images)
                    logger.info("Page %d/%d: %d text chunks, %d images", pno + 1, total_pages, len(text_chunks), img_count)

                conn.commit()
            except Exception:
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
    logger.info("Ingestion complete: %s — %d chunks, %d images in %.1fs",
                filename, stats["text_chunks"], stats["images"], elapsed)
    return {"status": "ingested", **stats}


def move_to_processed(pdf_path: str):
    dst = os.path.join(PROCESSED_DIR, os.path.basename(pdf_path))
    shutil.move(pdf_path, dst)


def list_pdfs(folder: str) -> List[str]:
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, fn) for fn in sorted(os.listdir(folder)) if fn.lower().endswith(".pdf")]


class ScanResponse(BaseModel):
    status: str
    processed_count: int
    processed: List[Dict[str, Any]]


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


@app.post("/ingest/upload")
async def ingest_upload(file: UploadFile = File(...), lang: str = "de"):
    ensure_dirs()

    # Fast pre-check from Content-Length
    if file.size and file.size > MAX_UPLOAD_BYTES:
        return {"status": "error", "reason": f"file too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)"}

    safe_name = sanitize_filename(file.filename)

    try:
        with ingestion_lock():
            tmp_path = os.path.join(INBOX_DIR, safe_name)
            total = 0
            try:
                with open(tmp_path, "wb") as f:
                    while chunk := await file.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_UPLOAD_BYTES:
                            raise ValueError("file too large")
                        f.write(chunk)
            except ValueError:
                os.remove(tmp_path)
                return {"status": "error", "reason": f"file too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)"}

            doc_id = get_or_create_doc_id(safe_name)
            res = extract_and_store(tmp_path, doc_id, lang)
            if res.get("status") == "ingested":
                move_to_processed(tmp_path)
            return res
    except RuntimeError as e:
        if str(e) == "busy":
            logger.info("Lock busy, returning busy status")
            return {"status": "busy", "reason": "ingestion_in_progress"}
        raise


@app.post("/ingest/scan", response_model=ScanResponse)
def ingest_scan(max_docs: int = 1, lang: str = "de"):
    ensure_dirs()
    try:
        with ingestion_lock():
            max_docs = min(max_docs, MAX_DOCS_PER_SCAN)
            pdfs = list_pdfs(INBOX_DIR)

            processed: List[Dict[str, Any]] = []
            for pdf_path in pdfs[:max_docs]:
                doc_id = get_or_create_doc_id(os.path.basename(pdf_path))
                res = extract_and_store(pdf_path, doc_id, lang)
                processed.append(res)
                if res.get("status") == "ingested":
                    move_to_processed(pdf_path)

            return ScanResponse(status="ok", processed_count=len(processed), processed=processed)
    except RuntimeError as e:
        if str(e) == "busy":
            logger.info("Lock busy, returning busy status")
            return ScanResponse(status="busy", processed_count=0, processed=[])
        raise
