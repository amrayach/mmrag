````text
ROLE: You are a Senior DevOps Engineer + Backend Engineer.
GOAL: Deploy the mmrag-n8n-demo-v2 project exactly according to the Frozen Specification below.

AVAILABLE TOOLS — USE THEM
===========================
You have several MCP servers connected. Use them proactively throughout implementation:

1) `postgres` (read-only Postgres MCP)
   - USE to verify: database creation, schema correctness, extension presence, table structure
   - USE after Phase 1 DB init to confirm rag_docs/rag_chunks tables exist with correct columns
   - USE after ingestion to confirm rows were written correctly
   - Connection: host=127.0.0.1, port=56154, user/pass from .env, databases: rag, n8n

2) `docker` (Docker MCP)
   - USE to inspect running containers, images, volumes, networks at every validation gate
   - USE to verify container names match ammer_mmragv2_* prefix
   - USE to check container health status, restart counts, port bindings
   - USE to confirm GPU allocation on ollama container
   - USE instead of blind `docker ps` — query structured data

3) `n8n-mcp` (n8n MCP)
   - USE to list, inspect, create, update, and activate workflows directly via API
   - USE to import the two workflow JSONs (01_chat_brain.json, 02_ingestion_factory.json)
   - USE to activate workflows programmatically (avoids manual UI step)
   - USE to verify webhook endpoints are registered and responding
   - USE to create the Postgres credential inside n8n and wire it to the Vector Search node
   - This can automate most of MANUAL_STEPS.md §5 (credentials + import + activate)

4) `context7` (library documentation lookup)
   - USE to look up correct API usage for: FastAPI, PyMuPDF (fitz), psycopg3, pgvector-python,
     python-multipart, docker compose v2 syntax, n8n webhook node config, nginx config
   - USE BEFORE writing any code to verify current API signatures and avoid deprecated patterns
   - USE when troubleshooting errors to check if API has changed

5) `sequential-thinking` (structured reasoning)
   - USE for complex multi-step decisions: debugging compose dependency chains,
     diagnosing why a container won't start, planning rollback sequences
   - USE when a validation gate fails to reason through root cause systematically
   - USE when deciding whether to proceed or stop at a checkpoint

INSTALLED SKILL:
- `czlonkowski/n8n-skills` — USE for n8n workflow creation patterns, node configuration,
  credential setup, and workflow JSON structure. Consult this skill BEFORE writing or modifying
  any n8n workflow JSON. It contains best practices for webhook nodes, function nodes,
  HTTP request nodes, and Postgres nodes that will prevent common mistakes.

CONSTRAINTS:
  - DO NOT deviate from ports, paths, names, or file contents.
  - DO NOT stop, modify, or interact with any existing stacks/containers except this new project.
  - DO NOT bind services to 0.0.0.0; bind ONLY to 127.0.0.1 host ports specified below.
  - DO NOT enable public exposure. Tailnet-only access is required. (No new Funnel rules.)
  - MUST: First produce a detailed Implementation Plan with phases and checkpoints.
  - MUST: STOP and wait for my approval after the plan (do not create files or run commands until approved).
  - MUST: Document everything done in README.md and create docs/ markdown for each component.
  - MUST: Flag all manual steps explicitly in MANUAL_STEPS.md.
  - MUST: When running any command that could change system state, ask for confirmation first.
  - MUST: The agent runs on the server; be extremely cautious and "do no harm."

TOOL USAGE STRATEGY (follow at each phase)
===========================================
Before writing code:
  → Use `context7` to verify library APIs you're about to use
  → Consult `n8n-skills` before touching workflow JSON

After creating files:
  → Use `sequential-thinking` to verify the compose dependency graph is correct
  → Use `docker` MCP to confirm no naming/volume conflicts exist

After `docker compose up`:
  → Use `docker` MCP to verify all containers are running, healthy, correct names
  → Use `postgres` MCP to verify databases exist, schemas applied, extensions loaded
  → Use `n8n-mcp` to verify n8n is accessible and ready for workflow import

After workflow import:
  → Use `n8n-mcp` to list workflows and confirm both are present
  → Use `n8n-mcp` to activate both workflows
  → Use `n8n-mcp` to verify webhook paths are registered

After model pull:
  → Use `docker` MCP to confirm ollama container is still healthy
  → Verify models via `docker compose exec ollama ollama list`


FROZEN SPECIFICATION (mmrag-n8n-demo-v2) — v2.4 (FULLY INLINED)
===============================================================

1) Host & Base Path
- Project root (MUST): /srv/projects/ammer/mmrag-n8n-demo-v2
- All work must happen inside this root.

2) Isolation / Safety Rules
- docker compose project name: ammer-mmragv2
- unique container names prefix: ammer_mmragv2_
- host binds: localhost only, ports 56150–56157
- no default ports bound directly to host
- GPU usage: Only the ollama container uses GPU. Concurrency=1. No background GPU-heavy jobs.
- Ingestion must be strictly single-worker (enforced by a lock inside pdf-ingest).

3) Services (Docker Compose)
- postgres: supabase/postgres (pgvector), persistent volume, init scripts create DBs and schema
- n8n: n8nio/n8n:latest-arm64, uses postgres DB "n8n"
- ollama: ollama/ollama:latest, persistent model cache volume, concurrency=1
- openwebui: ghcr.io/open-webui/open-webui:main, UI only (provider configured to rag-gateway)
- filebrowser: filebrowser/filebrowser:latest, corpus manager for /data (inbox/processed/assets)
- adminer: adminer:latest, visual DB UI
- assets: nginx:alpine serving ./data/assets (read-only) so browsers can load images
- pdf-ingest: FastAPI service, internal only; scans inbox, processes 1 pdf max per call
- rag-gateway: FastAPI OpenAI-compatible gateway, internal only; OpenWebUI points to it

4) Frozen Host Port Bindings (LOCALHOST ONLY)
- 127.0.0.1:56150 -> n8n:5678
- 127.0.0.1:56151 -> openwebui:8080
- 127.0.0.1:56152 -> filebrowser:80
- 127.0.0.1:56153 -> adminer:8080
- 127.0.0.1:56154 -> postgres:5432
- 127.0.0.1:56157 -> assets:80
(No host bind for: ollama, pdf-ingest, rag-gateway)

5) Tailnet-Only URLs (Tailscale Serve)
- https://YOUR_TAILSCALE_HOSTNAME:8450 -> http://127.0.0.1:56150 (n8n UI)
- https://YOUR_TAILSCALE_HOSTNAME:8451 -> http://127.0.0.1:56151 (OpenWebUI UI)
- https://YOUR_TAILSCALE_HOSTNAME:8452 -> http://127.0.0.1:56152 (FileBrowser UI)
- https://YOUR_TAILSCALE_HOSTNAME:8453 -> http://127.0.0.1:56153 (Adminer UI)
- https://YOUR_TAILSCALE_HOSTNAME:8454 -> http://127.0.0.1:56157 (Assets static files)
NOTE: Do not change existing Funnel mappings. Add Serve rules only. If Serve conflicts, report and STOP.

6) Data Folders
- ./data/inbox       : PDFs uploaded here (via FileBrowser)
- ./data/processed   : PDFs moved here after ingest
- ./data/assets      : extracted images stored here, served via assets service

7) Database & Schema
- Postgres databases:
  - n8n   (for n8n internal)
  - rag   (for RAG)
- rag schema:
  - rag_docs(doc_id UUID PK, filename TEXT, sha256 TEXT, lang TEXT, pages INT, created_at, updated_at)
  - rag_chunks(id BIGSERIAL PK, doc_id UUID FK, chunk_type TEXT, page INT,
              content_text TEXT, caption TEXT, asset_path TEXT,
              embedding VECTOR(768), meta JSONB)
- Extension: vector
- Re-ingest: if sha256 differs, delete existing chunks for doc_id and reprocess.

8) Models (Ollama) — pulled ONCE, cached in volume
- Text: qwen2.5:7b-instruct
- Vision: qwen2.5vl:7b
- Embeddings: nomic-embed-text
Constraints: <=7B. Concurrency=1. Do not repeatedly pull.

9) Workflow Architecture (n8n) — exactly TWO workflows
A) Chat Brain (Synchronous)
- Trigger: Webhook POST /webhook/rag-chat
- Steps: embed -> vector search -> build context (+ image URLs computed at runtime) -> generate answer -> respond
B) Ingestion Factory (Asynchronous)
- Trigger: Cron every 2 minutes AND Webhook POST /webhook/ingest-now
- Steps: call pdf-ingest /ingest/scan?max_docs=1 -> summarize result -> done
- Must process sequentially (enforced via lock inside pdf-ingest; if locked, returns status=busy)

10) Demo Utilities
- reset_demo.sh: truncates rag tables + clears processed/assets
- setup_models.sh: pull 3 models into ollama cache once (waits for Ollama readiness)
- prewarm.sh: keeps text model loaded via keep_alive before demo (curl executed from rag-gateway container)
- GPU proof: run watch -n 1 nvidia-smi during demo

EXECUTION STRATEGY (MUST FOLLOW)
================================
1) Read entire spec and files below.
2) Produce an Implementation Plan with phases and validation gates:

   - Phase 1: Foundation
     * create directories
     * create .env.example, scripts, docs, sql init
     * Gate: scripts/preflight_check.sh passes (ports free, docker ok, no conflicting volumes, serve status printed)
     * TOOL GATE: Use `docker` MCP to confirm no ammer-mmragv2 volumes/containers exist
     * TOOL GATE: Use `sequential-thinking` to verify the full dependency graph before proceeding

   - Phase 2: Services
     * BEFORE writing code: use `context7` to verify FastAPI, psycopg3, pgvector, PyMuPDF APIs
     * BEFORE writing workflow JSON: consult `n8n-skills` for node configuration best practices
     * create compose + python services
     * chmod +x scripts
     * docker compose up -d --build
     * Gate: scripts/health_check.sh passes
     * TOOL GATE: Use `docker` MCP to verify all 9 containers running with correct names
     * TOOL GATE: Use `postgres` MCP to verify:
       - databases `rag` and `n8n` exist
       - `vector` extension is installed in `rag`
       - tables `rag_docs` and `rag_chunks` exist with correct columns
       - HNSW index exists on `rag_chunks.embedding`

   - Phase 3: Logic (n8n workflows + wiring)
     * Use `n8n-mcp` to:
       a) Create a Postgres credential (host=postgres, port=5432, db=rag, user/pass from .env)
       b) Import 01_chat_brain.json workflow
       c) Import 02_ingestion_factory.json workflow
       d) Wire the Postgres credential to the "Vector Search (Postgres)" node in Chat Brain
       e) Activate BOTH workflows
       f) Verify webhook endpoints /webhook/rag-chat and /webhook/ingest-now are registered
     * Update MANUAL_STEPS.md to reflect which steps were automated vs still manual
     * Gate: docs complete and manual steps clearly flagged
     * TOOL GATE: Use `n8n-mcp` to list active workflows and confirm both are active
     * TOOL GATE: Test webhook endpoint existence (POST to /webhook/rag-chat with test payload)

   - Phase 4: Launch
     * scripts/setup_models.sh
     * scripts/prewarm.sh
     * provide tailscale serve commands (DO NOT EXECUTE unless explicitly approved)
     * TOOL GATE: Use `docker` MCP to confirm ollama container still healthy after model pull
     * TOOL GATE: Use `postgres` MCP to do a final schema sanity check
     * TOOL GATE: End-to-end test: upload a small test PDF, trigger ingest, verify chunks in DB via `postgres` MCP

3) STOP after the plan and wait for approval.

ROLLBACK PLAN (if any phase fails)
===================================
- Phase 2 fail: `docker compose down -v` to remove all containers and volumes, fix issue, retry
- Phase 3 fail: Use `n8n-mcp` to deactivate/delete workflows, re-import
- Phase 4 fail: Models can be re-pulled safely (idempotent). Prewarm is safe to retry.
- Nuclear: `docker compose down -v && rm -rf data/processed/* data/assets/*` then restart from Phase 2


FILES TO CREATE (EXACT CONTENTS)
================================

[1] /srv/projects/ammer/mmrag-n8n-demo-v2/.env.example
----------------------------------------------------
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=CHANGE_ME_STRONG_PASSWORD

RAG_DB=rag
N8N_DB=n8n

# Host-bound localhost ports (frozen)
PORT_N8N=56150
PORT_OPENWEBUI=56151
PORT_FILEBROWSER=56152
PORT_ADMINER=56153
PORT_PG=56154
PORT_ASSETS=56157

# Tailnet assets base URL used in answers (computed at runtime)
PUBLIC_ASSETS_BASE_URL=https://YOUR_TAILSCALE_HOSTNAME:8454

# Ollama internal URL
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_TEXT_MODEL=qwen2.5:7b-instruct
OLLAMA_VISION_MODEL=qwen2.5vl:7b
OLLAMA_EMBED_MODEL=nomic-embed-text

# n8n internal webhook used by rag-gateway
N8N_CHAT_WEBHOOK_URL=http://n8n:5678/webhook/rag-chat

# n8n requires a 64 hex char encryption key. Generate: openssl rand -hex 32
N8N_ENCRYPTION_KEY=CHANGE_ME_64_HEX_CHARS

# Linux user/group for file permissions (ammer typically 1000:1000)
PUID=1000
PGID=1000


[2] /srv/projects/ammer/mmrag-n8n-demo-v2/.gitignore
----------------------------------------------------
.env
data/inbox/*
data/processed/*
data/assets/*
!data/.gitkeep


[3] /srv/projects/ammer/mmrag-n8n-demo-v2/docker-compose.yml
-----------------------------------------------------------
version: "3.9"

name: ammer-mmragv2

services:
  postgres:
    image: supabase/postgres:latest
    container_name: ammer_mmragv2_postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: postgres
    ports:
      - "127.0.0.1:${PORT_PG}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d postgres"]
      interval: 5s
      timeout: 3s
      retries: 30
    restart: unless-stopped

  n8n:
    image: n8nio/n8n:latest-arm64
    container_name: ammer_mmragv2_n8n
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      N8N_HOST: "0.0.0.0"
      N8N_PORT: "5678"
      N8N_PROTOCOL: "http"
      N8N_DIAGNOSTICS_ENABLED: "false"
      N8N_PERSONALIZATION_ENABLED: "false"
      N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY}

      DB_TYPE: "postgresdb"
      DB_POSTGRESDB_HOST: "postgres"
      DB_POSTGRESDB_PORT: "5432"
      DB_POSTGRESDB_DATABASE: "${N8N_DB}"
      DB_POSTGRESDB_USER: "${POSTGRES_USER}"
      DB_POSTGRESDB_PASSWORD: "${POSTGRES_PASSWORD}"

      # REQUIRED for workflows that reference $env.*
      OLLAMA_BASE_URL: ${OLLAMA_BASE_URL}
      OLLAMA_TEXT_MODEL: ${OLLAMA_TEXT_MODEL}
      OLLAMA_VISION_MODEL: ${OLLAMA_VISION_MODEL}
      OLLAMA_EMBED_MODEL: ${OLLAMA_EMBED_MODEL}
      PUBLIC_ASSETS_BASE_URL: ${PUBLIC_ASSETS_BASE_URL}

    ports:
      - "127.0.0.1:${PORT_N8N}:5678"
    volumes:
      - n8n_data:/home/node/.n8n
      - ./n8n/workflows:/workflows:ro
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    container_name: ammer_mmragv2_ollama
    environment:
      OLLAMA_NUM_PARALLEL: "1"
      OLLAMA_MAX_LOADED_MODELS: "1"
    volumes:
      - ollama_data:/root/.ollama
    gpus: all
    restart: unless-stopped

  rag-gateway:
    build:
      context: ./services/rag-gateway
      dockerfile: Dockerfile
    container_name: ammer_mmragv2_rag_gateway
    depends_on:
      n8n:
        condition: service_started
    environment:
      N8N_CHAT_WEBHOOK_URL: ${N8N_CHAT_WEBHOOK_URL}
      REQUEST_TIMEOUT_SECS: "120"
      DEFAULT_MODEL: ${OLLAMA_TEXT_MODEL}
    restart: unless-stopped

  pdf-ingest:
    build:
      context: ./services/pdf-ingest
      dockerfile: Dockerfile
    container_name: ammer_mmragv2_pdf_ingest
    depends_on:
      postgres:
        condition: service_healthy
      ollama:
        condition: service_started
    environment:
      DATABASE_HOST: postgres
      DATABASE_PORT: 5432
      DATABASE_NAME: ${RAG_DB}
      DATABASE_USER: ${POSTGRES_USER}
      DATABASE_PASSWORD: ${POSTGRES_PASSWORD}

      OLLAMA_BASE_URL: ${OLLAMA_BASE_URL}
      OLLAMA_VISION_MODEL: ${OLLAMA_VISION_MODEL}
      OLLAMA_EMBED_MODEL: ${OLLAMA_EMBED_MODEL}

      INBOX_DIR: /kb/inbox
      PROCESSED_DIR: /kb/processed
      ASSETS_DIR: /kb/assets

      # strict single-worker ingestion (lock)
      LOCK_FILE: /tmp/pdf_ingest.lock

      MAX_DOCS_PER_SCAN: "1"
      MAX_PAGES: "0"
      MAX_IMAGES_PER_PAGE: "5"
      CHUNK_CHARS: "1500"
      CHUNK_OVERLAP_CHARS: "200"
    volumes:
      - ./data/inbox:/kb/inbox
      - ./data/processed:/kb/processed
      - ./data/assets:/kb/assets
    restart: unless-stopped

  openwebui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: ammer_mmragv2_openwebui
    depends_on:
      rag-gateway:
        condition: service_started
    environment:
      WEBUI_NAME: "MMRAG Demo (Tailnet Only)"
    ports:
      - "127.0.0.1:${PORT_OPENWEBUI}:8080"
    volumes:
      - openwebui_data:/app/backend/data
    restart: unless-stopped

  filebrowser:
    image: filebrowser/filebrowser:latest
    container_name: ammer_mmragv2_filebrowser
    user: "${PUID}:${PGID}"
    ports:
      - "127.0.0.1:${PORT_FILEBROWSER}:80"
    volumes:
      - ./data:/srv
      - filebrowser_db:/database
      - filebrowser_config:/config
    command: ["--database", "/database/filebrowser.db", "--root", "/srv", "--port", "80", "--address", "0.0.0.0"]
    restart: unless-stopped

  adminer:
    image: adminer:latest
    container_name: ammer_mmragv2_adminer
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      ADMINER_DEFAULT_SERVER: postgres
    ports:
      - "127.0.0.1:${PORT_ADMINER}:8080"
    restart: unless-stopped

  assets:
    image: nginx:alpine
    container_name: ammer_mmragv2_assets
    ports:
      - "127.0.0.1:${PORT_ASSETS}:80"
    volumes:
      - ./data/assets:/usr/share/nginx/html:ro
    restart: unless-stopped

volumes:
  postgres_data:
  n8n_data:
  ollama_data:
  openwebui_data:
  filebrowser_db:
  filebrowser_config:


[4] /srv/projects/ammer/mmrag-n8n-demo-v2/db/init/001_init.sql
--------------------------------------------------------------
-- Create databases safely (CREATE DATABASE cannot run inside a DO/transaction).
SELECT 'CREATE DATABASE n8n' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')\gexec
SELECT 'CREATE DATABASE rag' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag')\gexec


[5] /srv/projects/ammer/mmrag-n8n-demo-v2/db/init/010_rag_schema.sql
-------------------------------------------------------------------
\connect rag

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_docs (
  doc_id UUID PRIMARY KEY,
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT 'de',
  pages INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_chunks (
  id BIGSERIAL PRIMARY KEY,
  doc_id UUID NOT NULL REFERENCES rag_docs(doc_id) ON DELETE CASCADE,
  chunk_type TEXT NOT NULL,         -- 'text' | 'image'
  page INT NOT NULL DEFAULT 0,
  content_text TEXT,
  caption TEXT,
  asset_path TEXT,
  embedding VECTOR(768),
  meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_page ON rag_chunks(doc_id, page);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_type ON rag_chunks(chunk_type);

DO $$
BEGIN
  EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw ON rag_chunks USING hnsw (embedding vector_cosine_ops);';
EXCEPTION WHEN others THEN
END $$;


[6] /srv/projects/ammer/mmrag-n8n-demo-v2/services/pdf-ingest/Dockerfile
-----------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]


[7] /srv/projects/ammer/mmrag-n8n-demo-v2/services/pdf-ingest/requirements.txt
------------------------------------------------------------------------------
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
psycopg[binary]==3.2.3
PyMuPDF==1.24.14
python-multipart==0.0.12
requests==2.32.3
pgvector==0.3.6


[8] /srv/projects/ammer/mmrag-n8n-demo-v2/services/pdf-ingest/app/main.py
------------------------------------------------------------------------
import base64
import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import psycopg
import requests
from fastapi import FastAPI, File, UploadFile
from pydantic import BaseModel
from pgvector import Vector
from pgvector.psycopg import register_vector

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

LOCK_FILE = os.getenv("LOCK_FILE", "/tmp/pdf_ingest.lock")

app = FastAPI(title="pdf-ingest", version="0.3.0")


def ensure_dirs():
    for d in [INBOX_DIR, PROCESSED_DIR, ASSETS_DIR]:
        os.makedirs(d, exist_ok=True)


@contextmanager
def ingestion_lock():
    """
    Strict single-worker lock:
    - If lock file exists -> return busy.
    - Otherwise create it and remove on exit.
    """
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


def db_conn():
    conn = psycopg.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )
    register_vector(conn)
    return conn


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def split_text(text: str, chunk_chars: int, overlap: int) -> List[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def ollama_embeddings(text: str) -> List[float]:
    resp = requests.post(
        f"{OLLAMA_BASE}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def ollama_caption_image(image_bytes: bytes) -> str:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": "Beschreibe dieses Bild kurz und präzise auf Deutsch (1-2 Sätze).",
                "images": [b64],
            }
        ],
        "stream": False,
    }
    resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=180)
    resp.raise_for_status()
    return (resp.json().get("message", {}) or {}).get("content", "").strip()


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
    emb_val = Vector(embedding) if embedding is not None else None
    cur.execute(
        """
        INSERT INTO rag_chunks(doc_id, chunk_type, page, content_text, caption, asset_path, embedding, meta)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (doc_id, chunk_type, page, content_text, caption, asset_path, emb_val, json.dumps(meta)),
    )


def get_or_create_doc_id(filename: str) -> uuid.UUID:
    # stable id per filename (demo-grade)
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mmrag:{filename}")


def should_process(cur, doc_id: uuid.UUID, sha: str) -> Tuple[bool, Optional[str]]:
    cur.execute("SELECT sha256 FROM rag_docs WHERE doc_id=%s", (doc_id,))
    row = cur.fetchone()
    if not row:
        return True, None
    existing = row[0]
    return existing != sha, existing


def extract_and_store(pdf_path: str, doc_id: uuid.UUID, lang: str) -> Dict[str, Any]:
    ensure_dirs()

    filename = os.path.basename(pdf_path)
    sha = sha256_file(pdf_path)

    stats = {"filename": filename, "doc_id": str(doc_id), "sha256": sha, "pages": 0, "text_chunks": 0, "images": 0}

    with db_conn() as conn:
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

            for pno in range(total_pages):
                page = doc.load_page(pno)
                text = page.get_text("text") or ""
                text_chunks = split_text(text, CHUNK_CHARS, CHUNK_OVERLAP)

                for idx, chunk in enumerate(text_chunks):
                    emb = ollama_embeddings(chunk)
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

                    caption = ollama_caption_image(img_bytes)
                    emb = ollama_embeddings(caption) if caption else None

                    insert_chunk(
                        cur, doc_id, "image", pno + 1, None, caption, asset_name, emb,
                        {"source": "pdf_image", "page": pno + 1, "image_index": im_i},
                    )
                    stats["images"] += 1

            conn.commit()

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


@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat()}


@app.post("/ingest/upload")
async def ingest_upload(file: UploadFile = File(...), lang: str = "de"):
    ensure_dirs()
    try:
        with ingestion_lock():
            tmp_path = os.path.join(INBOX_DIR, file.filename)
            with open(tmp_path, "wb") as f:
                f.write(await file.read())

            doc_id = get_or_create_doc_id(file.filename)
            res = extract_and_store(tmp_path, doc_id, lang)
            if res.get("status") == "ingested":
                move_to_processed(tmp_path)
            return res
    except RuntimeError as e:
        if str(e) == "busy":
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
            return ScanResponse(status="busy", processed_count=0, processed=[])
        raise


[9] /srv/projects/ammer/mmrag-n8n-demo-v2/services/rag-gateway/Dockerfile
-----------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


[10] /srv/projects/ammer/mmrag-n8n-demo-v2/services/rag-gateway/requirements.txt
------------------------------------------------------------------------------
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
requests==2.32.3


[11] /srv/projects/ammer/mmrag-n8n-demo-v2/services/rag-gateway/app/main.py
-------------------------------------------------------------------------
import os
import time
import uuid
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

N8N_WEBHOOK = os.getenv("N8N_CHAT_WEBHOOK_URL", "http://n8n:5678/webhook/rag-chat")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECS", "120"))
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b-instruct")

app = FastAPI(title="rag-gateway", version="0.2.0")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = 800


def last_user_text(messages: List[ChatMessage]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return messages[-1].content if messages else ""


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    if req.stream:
        raise HTTPException(status_code=400, detail="streaming not supported in this demo gateway")

    query = last_user_text(req.messages)
    payload = {
        "query": query,
        "messages": [m.model_dump() for m in req.messages],
        "model": req.model or DEFAULT_MODEL,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
    }

    try:
        r = requests.post(N8N_WEBHOOK, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"n8n webhook failed: {e}")

    answer = (data.get("answer") or "").strip()
    images = data.get("images") or []
    sources = data.get("sources") or []

    if images:
        answer += "\n\n" + "\n".join([f"![image]({u})" for u in images])

    if sources:
        answer += "\n\nQuellen:\n" + "\n".join([f"- {s}" for s in sources])

    now = int(time.time())
    resp_id = f"chatcmpl-{uuid.uuid4().hex}"
    return {
        "id": resp_id,
        "object": "chat.completion",
        "created": now,
        "model": req.model or DEFAULT_MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
    }


[12] /srv/projects/ammer/mmrag-n8n-demo-v2/scripts/init_dirs.sh
--------------------------------------------------------------
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# init_dirs should work even before .env exists
PUID_DEFAULT=1000
PGID_DEFAULT=1000

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

PUID="${PUID:-$PUID_DEFAULT}"
PGID="${PGID:-$PGID_DEFAULT}"

mkdir -p data/inbox data/processed data/assets
mkdir -p n8n/workflows db/init docs scripts
mkdir -p services/pdf-ingest/app services/rag-gateway/app

touch data/.gitkeep

# Ensure FileBrowser user can write
chown -R "${PUID}:${PGID}" data

echo "✅ Directories created and permissions set (data owned by ${PUID}:${PGID})."


[13] /srv/projects/ammer/mmrag-n8n-demo-v2/scripts/preflight_check.sh
--------------------------------------------------------------------
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

ports=(56150 56151 56152 56153 56154 56157)
echo "== Preflight: checking ports =="
for p in "${ports[@]}"; do
  if ss -tuln | grep -q ":$p "; then
    echo "ERROR: Port $p is already in use."
    exit 1
  fi
done
echo "OK: ports are free."

echo "== Preflight: docker access =="
docker ps >/dev/null
echo "OK: docker works."

echo "== Preflight: volume collision (FAIL by default) =="
if docker volume ls | awk '{print $2}' | grep -qE '^ammer-mmragv2_'; then
  echo "ERROR: Volumes from previous deployment exist."
  echo "If you want a clean redeploy: run 'docker compose down -v' inside the project root (MANUAL)."
  exit 1
fi
echo "OK: no conflicting volumes."

echo "== Preflight: tailscale serve status (informational) =="
tailscale serve status || true

echo "✅ Preflight checks passed."


[14] /srv/projects/ammer/mmrag-n8n-demo-v2/scripts/health_check.sh
-----------------------------------------------------------------
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

echo "== Health: containers =="
docker compose ps

echo "== Health: postgres =="
docker compose exec -T postgres pg_isready -U "${POSTGRES_USER}" -d postgres

echo "== Health: n8n UI =="
if curl -fsS "http://127.0.0.1:${PORT_N8N}/" 2>/dev/null | grep -qi "n8n"; then
  echo "OK: n8n UI responding"
else
  echo "WARNING: n8n UI not responding as expected"
fi

echo "== Health: OpenWebUI =="
curl -fsS "http://127.0.0.1:${PORT_OPENWEBUI}/" >/dev/null && echo "OK: OpenWebUI responding"

echo "== Health: Adminer =="
curl -fsS "http://127.0.0.1:${PORT_ADMINER}/" >/dev/null && echo "OK: Adminer responding"

echo "== Health: Assets =="
curl -fsS "http://127.0.0.1:${PORT_ASSETS}/" >/dev/null 2>&1 && echo "OK: Assets server responding" || echo "NOTE: Assets empty is fine"

echo "== Health: rag-gateway container =="
docker compose exec -T rag-gateway curl -fsS http://127.0.0.1:8000/health >/dev/null && echo "OK: rag-gateway /health"

echo "== Health: pdf-ingest container =="
docker compose exec -T pdf-ingest python -c "import requests; print(requests.get('http://127.0.0.1:8001/health').json())" >/dev/null 2>&1 && echo "OK: pdf-ingest /health" || echo "WARNING: pdf-ingest health check failed"

echo "✅ Health checks complete."


[15] /srv/projects/ammer/mmrag-n8n-demo-v2/scripts/setup_models.sh
------------------------------------------------------------------
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

echo "Waiting for Ollama daemon to be ready..."
until docker compose exec -T ollama ollama list >/dev/null 2>&1; do
  sleep 2
done
echo "Ollama is ready."

echo "Pulling models once into persistent volume..."
docker compose exec -T ollama ollama pull "${OLLAMA_TEXT_MODEL}"
docker compose exec -T ollama ollama pull "${OLLAMA_VISION_MODEL}"
docker compose exec -T ollama ollama pull "${OLLAMA_EMBED_MODEL}"
echo "✅ Models pulled and cached."


[16] /srv/projects/ammer/mmrag-n8n-demo-v2/scripts/prewarm.sh
------------------------------------------------------------
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

echo "Pre-warming text model (keep_alive 1h)..."
docker compose exec -T rag-gateway curl -s http://ollama:11434/api/generate -d "{
  \"model\": \"${OLLAMA_TEXT_MODEL}\",
  \"prompt\": \"Sag kurz Hallo auf Deutsch.\",
  \"keep_alive\": \"1h\",
  \"stream\": false
}" >/dev/null
echo "✅ Prewarm complete."


[17] /srv/projects/ammer/mmrag-n8n-demo-v2/scripts/tailscale_preflight.sh
------------------------------------------------------------------------
#!/usr/bin/env bash
set -euo pipefail
echo "== Tailscale Serve status BEFORE changes =="
tailscale serve status || true
echo ""
echo "If 8450-8454 already appear above, STOP and resolve conflicts manually."


[18] /srv/projects/ammer/mmrag-n8n-demo-v2/reset_demo.sh
-------------------------------------------------------
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env first."
  exit 1
fi
set -a; source .env; set +a

if ! docker compose ps postgres | grep -q "Up"; then
  echo "ERROR: postgres container not running. Start stack first."
  exit 1
fi

echo "♻️  Resetting RAG tables and clearing processed/assets..."
docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d rag -c "
  TRUNCATE TABLE rag_chunks RESTART IDENTITY CASCADE;
  TRUNCATE TABLE rag_docs RESTART IDENTITY CASCADE;
"

rm -f data/processed/* || true
rm -f data/assets/* || true

echo "✅ Reset complete."


[19] /srv/projects/ammer/mmrag-n8n-demo-v2/n8n/workflows/01_chat_brain.json
--------------------------------------------------------------------------
{
  "name": "MMRAG Chat Brain (Webhook)",
  "nodes": [
    {
      "parameters": { "path": "rag-chat", "httpMethod": "POST", "responseMode": "lastNode" },
      "id": "Webhook_Chat",
      "name": "Webhook (rag-chat)",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [200, 200]
    },
    {
      "parameters": {
        "functionCode": "const body = $json;\nconst msgs = body.messages || [];\nlet q = body.query;\nif (!q && msgs.length) {\n  for (let i = msgs.length - 1; i >= 0; i--) {\n    if (msgs[i].role === 'user') { q = msgs[i].content; break; }\n  }\n}\nreturn [{ json: { ...body, query: q || '' } }];"
      },
      "id": "Fn_ExtractQuery",
      "name": "Extract Query",
      "type": "n8n-nodes-base.function",
      "typeVersion": 2,
      "position": [420, 200]
    },
    {
      "parameters": {
        "url": "http://ollama:11434/api/embeddings",
        "method": "POST",
        "jsonParameters": true,
        "options": { "timeout": 120000 },
        "bodyParametersJson": "{\n  \"model\": \"{{$env.OLLAMA_EMBED_MODEL}}\",\n  \"prompt\": \"{{$json.query}}\"\n}"
      },
      "id": "HTTP_Embed",
      "name": "Embed Query (Ollama)",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4,
      "position": [660, 200]
    },
    {
      "parameters": {
        "functionCode": "const emb = $json.embedding || [];\nconst embVec = '[' + emb.join(',') + ']';\nreturn [{ json: { query: $node['Extract Query'].json.query, embedding_vec: embVec } }];"
      },
      "id": "Fn_VectorLiteral",
      "name": "To Vector Literal",
      "type": "n8n-nodes-base.function",
      "typeVersion": 2,
      "position": [900, 200]
    },
    {
      "parameters": {
        "operation": "executeQuery",
        "query": "SELECT chunk_type, page, content_text, caption, asset_path,\n       1 - (embedding <=> '{{$json.embedding_vec}}'::vector) AS score\nFROM rag_chunks\nWHERE embedding IS NOT NULL\nORDER BY embedding <=> '{{$json.embedding_vec}}'::vector\nLIMIT 8;"
      },
      "id": "PG_VectorSearch",
      "name": "Vector Search (Postgres)",
      "type": "n8n-nodes-base.postgres",
      "typeVersion": 2,
      "position": [1140, 200]
    },
    {
      "parameters": {
        "functionCode": "const hits = ($items('Vector Search (Postgres)') || []).map(it => it.json);\nconst base = $env.PUBLIC_ASSETS_BASE_URL || '';\nconst images = hits\n  .filter(h => h.chunk_type === 'image' && h.asset_path)\n  .map(h => `${base}/${h.asset_path}`);\nconst ctxLines = hits.map(h => {\n  if (h.chunk_type === 'image') {\n    const url = h.asset_path ? `${base}/${h.asset_path}` : '';\n    return `Bild (Seite ${h.page}): ${h.caption || ''} ${url}`.trim();\n  }\n  return `Text (Seite ${h.page}): ${h.content_text || ''}`;\n});\nconst sources = hits.map(h => `Seite ${h.page} (${h.chunk_type})`).slice(0, 8);\nreturn [{ json: { query: $node['Extract Query'].json.query, context: ctxLines.join('\\n\\n'), images, sources } }];"
      },
      "id": "Fn_BuildContext",
      "name": "Build Context",
      "type": "n8n-nodes-base.function",
      "typeVersion": 2,
      "position": [1380, 200]
    },
    {
      "parameters": {
        "url": "http://ollama:11434/api/chat",
        "method": "POST",
        "jsonParameters": true,
        "options": { "timeout": 180000 },
        "bodyParametersJson": "{\n  \"model\": \"{{$env.OLLAMA_TEXT_MODEL}}\",\n  \"stream\": false,\n  \"messages\": [\n    {\"role\": \"system\", \"content\": \"Du bist ein präziser Assistent. Antworte auf Deutsch. Zitiere Seitenzahlen wenn möglich.\"},\n    {\"role\": \"user\", \"content\": \"Frage: {{$json.query}}\\n\\nKontext aus Dokumenten:\\n{{$json.context}}\\n\\nAntworte kurz, korrekt und mit Seitenhinweisen.\"}\n  ]\n}"
      },
      "id": "HTTP_Generate",
      "name": "Generate Answer (Ollama)",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4,
      "position": [1620, 200]
    },
    {
      "parameters": {
        "functionCode": "const msg = $json.message?.content || '';\nconst ctx = $node['Build Context'].json;\nreturn [{ json: { answer: msg, images: ctx.images || [], sources: ctx.sources || [] } }];"
      },
      "id": "Fn_FormatResponse",
      "name": "Format Response",
      "type": "n8n-nodes-base.function",
      "typeVersion": 2,
      "position": [1860, 200]
    }
  ],
  "connections": {
    "Webhook (rag-chat)": { "main": [[{ "node": "Extract Query", "type": "main", "index": 0 }]] },
    "Extract Query": { "main": [[{ "node": "Embed Query (Ollama)", "type": "main", "index": 0 }]] },
    "Embed Query (Ollama)": { "main": [[{ "node": "To Vector Literal", "type": "main", "index": 0 }]] },
    "To Vector Literal": { "main": [[{ "node": "Vector Search (Postgres)", "type": "main", "index": 0 }]] },
    "Vector Search (Postgres)": { "main": [[{ "node": "Build Context", "type": "main", "index": 0 }]] },
    "Build Context": { "main": [[{ "node": "Generate Answer (Ollama)", "type": "main", "index": 0 }]] },
    "Generate Answer (Ollama)": { "main": [[{ "node": "Format Response", "type": "main", "index": 0 }]] }
  },
  "active": false,
  "settings": {},
  "versionId": "frozen-v2.4"
}


[20] /srv/projects/ammer/mmrag-n8n-demo-v2/n8n/workflows/02_ingestion_factory.json
--------------------------------------------------------------------------------
{
  "name": "MMRAG Ingestion Factory (Cron + Webhook)",
  "nodes": [
    {
      "parameters": { "triggerTimes": { "item": [{ "mode": "everyX", "value": 2, "unit": "minutes" }] } },
      "id": "Cron_Ingest",
      "name": "Cron (every 2 min)",
      "type": "n8n-nodes-base.cron",
      "typeVersion": 1,
      "position": [200, 280]
    },
    {
      "parameters": { "path": "ingest-now", "httpMethod": "POST", "responseMode": "onReceived" },
      "id": "Webhook_IngestNow",
      "name": "Webhook (ingest-now)",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [200, 120]
    },
    {
      "parameters": {
        "url": "http://pdf-ingest:8001/ingest/scan?max_docs=1&lang=de",
        "method": "POST",
        "jsonParameters": true,
        "options": { "timeout": 300000 },
        "bodyParametersJson": "{}"
      },
      "id": "HTTP_Scan",
      "name": "Scan & Ingest 1 PDF",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4,
      "position": [520, 200]
    },
    {
      "parameters": {
        "functionCode": "return [{ json: { status: $json.status, processed_count: $json.processed_count, processed: $json.processed } }];"
      },
      "id": "Fn_Summarize",
      "name": "Summarize Result",
      "type": "n8n-nodes-base.function",
      "typeVersion": 2,
      "position": [760, 200]
    }
  ],
  "connections": {
    "Cron (every 2 min)": { "main": [[{ "node": "Scan & Ingest 1 PDF", "type": "main", "index": 0 }]] },
    "Webhook (ingest-now)": { "main": [[{ "node": "Scan & Ingest 1 PDF", "type": "main", "index": 0 }]] },
    "Scan & Ingest 1 PDF": { "main": [[{ "node": "Summarize Result", "type": "main", "index": 0 }]] }
  },
  "active": false,
  "settings": {},
  "versionId": "frozen-v2.4"
}


[21] /srv/projects/ammer/mmrag-n8n-demo-v2/MANUAL_STEPS.md
---------------------------------------------------------
# Manual Steps (Cannot be fully automated)

All commands assume:
cd /srv/projects/ammer/mmrag-n8n-demo-v2

## 1) Create .env
Copy `.env.example` -> `.env` and set:
- POSTGRES_PASSWORD (strong)
- N8N_ENCRYPTION_KEY (64 hex chars: `openssl rand -hex 32`)

## 2) Change FileBrowser Password IMMEDIATELY
- URL (tailnet): https://YOUR_TAILSCALE_HOSTNAME:8452
- Default login: admin / admin
- Settings → Users → Change password
- Do this immediately (default credentials are a risk even on tailnet)

## 3) Configure Tailscale Serve (tailnet-only)
Before adding rules:
- `tailscale serve status`
If 8450-8454 are unused:
- `tailscale serve --bg --https=8450 http://127.0.0.1:56150`
- `tailscale serve --bg --https=8451 http://127.0.0.1:56151`
- `tailscale serve --bg --https=8452 http://127.0.0.1:56152`
- `tailscale serve --bg --https=8453 http://127.0.0.1:56153`
- `tailscale serve --bg --https=8454 http://127.0.0.1:56157`

## 4) OpenWebUI Provider
In OpenWebUI Admin:
- Add an OpenAI-compatible provider:
  - Base URL: `http://rag-gateway:8000/v1`
  - API key: `sk-dummy-key-12345`

## 5) n8n Credentials -> Import -> Configure -> Activate (DO IN ORDER)
NOTE: Steps 5a-5d CAN be automated via n8n-mcp. If n8n-mcp was used during
deployment, verify the results rather than repeating manually.

a) Create Postgres credential first:
   - Host: postgres
   - Port: 5432
   - Database: rag
   - User/Pass: from .env
   - VERIFY via n8n-mcp: list credentials, confirm Postgres credential exists

b) Import workflows:
   - Settings → Workflows → Import from File
   - Import `n8n/workflows/01_chat_brain.json`
   - Import `n8n/workflows/02_ingestion_factory.json`
   - VERIFY via n8n-mcp: list workflows, confirm both present

c) Configure credential in workflow 01:
   - Open "MMRAG Chat Brain (Webhook)"
   - Click node "Vector Search (Postgres)"
   - In the credential dropdown, select your Postgres credential
   - Save

d) Activate BOTH workflows:
   - Toggle "Active" ON in each workflow
   - Verify green "Active" badge
   - If not active, webhooks will 404.
   - VERIFY via n8n-mcp: list workflows, confirm both show active=true

## 6) Optional: Adminer Login (visual DB)
- URL: https://YOUR_TAILSCALE_HOSTNAME:8453
- System: PostgreSQL
- Server: postgres
- Username: rag_user
- Password: from .env
- Database: rag


[22] /srv/projects/ammer/mmrag-n8n-demo-v2/README.md
---------------------------------------------------
# mmrag-n8n-demo-v2 (Tailnet Only, Isolated)

All commands assume:
```bash
cd /srv/projects/ammer/mmrag-n8n-demo-v2
```

## Safety Invariants

* Root: `/srv/projects/ammer/mmrag-n8n-demo-v2`
* Compose: `ammer-mmragv2`
* Host binds: **localhost only** (56150–56157)
* No new Funnel exposure; use **Tailscale Serve** only.
* Only `ollama` uses GPU; concurrency=1.
* Ingestion is single-worker (lock file inside `pdf-ingest`).

## Quick Start (after approval + implementation)

1. Preflight (ports free, volumes clean, docker ok):

```bash
./scripts/preflight_check.sh
```

2. Create `.env` from `.env.example` (see MANUAL_STEPS.md)

3. Init directories + permissions (requires sudo for chown):

```bash
sudo ./scripts/init_dirs.sh
```

4. Make scripts executable:

```bash
chmod +x scripts/*.sh reset_demo.sh
```

5. Launch stack:

```bash
docker compose up -d --build
./scripts/health_check.sh
```

6. Pull models once (cached in volume):

```bash
./scripts/setup_models.sh
```

7. Configure tailnet URLs + UI steps:
   See `MANUAL_STEPS.md`

## Demo Day Runbook

* Upload PDFs in FileBrowser -> `/inbox`
* Ingest:

  * wait for cron (2 min), or trigger webhook `/webhook/ingest-now` in n8n
  * If ingestion overlaps, pdf-ingest returns `status=busy` (this is expected safety behavior).
* Prewarm (avoid first-request model load latency):

```bash
./scripts/prewarm.sh
```

* GPU proof:

```bash
watch -n 1 nvidia-smi
```

* Reset between rehearsals:

```bash
./reset_demo.sh
```

## Troubleshooting

* Logs:

```bash
docker compose logs -f --tail=200
```

* Ports:

```bash
sudo ss -tulpen | egrep '5615[0-9]|56157'
```

* Tailscale:

```bash
tailscale serve status
```


## [23] /srv/projects/ammer/mmrag-n8n-demo-v2/docs/architecture.md

# Architecture (Scenario A)

Chat:
OpenWebUI (UI) -> rag-gateway (OpenAI-compatible) -> n8n (Chat Brain) -> Postgres(pgvector) + Ollama

Ingestion:
FileBrowser upload -> data/inbox -> n8n (Ingestion Factory) -> pdf-ingest -> Postgres(pgvector) + assets (nginx)

## [24] /srv/projects/ammer/mmrag-n8n-demo-v2/docs/ports.md

# Ports

Localhost binds:

* 56150 n8n
* 56151 OpenWebUI
* 56152 FileBrowser
* 56153 Adminer
* 56154 Postgres
* 56157 Assets

Tailnet-only (Tailscale Serve):

* 8450 n8n
* 8451 OpenWebUI
* 8452 FileBrowser
* 8453 Adminer
* 8454 Assets

NOW: Produce the Implementation Plan (Phase 1–4) with explicit commands, checks, validation gates, and rollback/safety notes.
Then STOP and wait for my approval.
````
