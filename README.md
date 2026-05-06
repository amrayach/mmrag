# MMRAG — Multimodal RAG Demo

A self-hosted, GPU-accelerated **Retrieval-Augmented Generation** pipeline that ingests PDFs and RSS feeds (text + images), stores vector embeddings in PostgreSQL/pgvector, and serves streaming answers through a chat UI. Retrieval and generation run through the RAG Gateway for direct pgvector context assembly and Ollama token streaming; n8n remains the workflow layer for ingestion triggers and fallback context workflows.

## Architecture

```
Chat flow (streaming):
  OpenWebUI → rag-gateway (OpenAI SSE)
    → PostgreSQL/pgvector (direct vector search)
    → Ollama (streaming LLM)
    → OpenWebUI (token-by-token)

Ingestion flows:
  FileBrowser upload → data/inbox/ → pdf-ingest watcher
    → OpenDataLoader PDF + qwen2.5vl captions + bge-m3 embeddings
    → PostgreSQL/pgvector + assets/ (nginx)

  RSS feeds → rss-ingest (scheduled) → PostgreSQL/pgvector + assets/ (nginx)
```

### Services (11 containers)

| Service | Description |
|---------|-------------|
| **postgres** | PostgreSQL 15 with pgvector for document storage and vector search |
| **n8n** | Workflow automation — Chat Brain (context), Ingestion Factory, RSS Ingestion |
| **ollama** | Local LLM inference (GPU-accelerated) |
| **rag-gateway** | OpenAI-compatible API with true SSE streaming (Ollama NDJSON → OpenAI SSE) |
| **pdf-ingest** | PDF processing: OpenDataLoader layout extraction, image captioning, embedding generation |
| **rss-ingest** | RSS feed ingestion: article scraping, image captioning, embedding generation |
| **openwebui** | Chat UI frontend |
| **filebrowser** | Web-based file manager for PDF uploads |
| **adminer** | Database admin UI |
| **controlcenter** | Project dashboard, readiness checks, ingestion controls, docs browser |
| **assets** | Nginx serving extracted images + browsable gallery |

### Models (Ollama)

| Model | Purpose |
|-------|---------|
| `gemma4:26b` | Text generation (chat answers) — MoE, 4B active params per token |
| `qwen2.5vl:7b` | Vision model (image captioning during ingestion) |
| `bge-m3` | Multilingual embedding generation (1024-dim vectors) |

All three active models are kept loaded in GPU memory simultaneously (`OLLAMA_MAX_LOADED_MODELS=3`, ~28 GB total) to reduce model swap latency. Requires Ollama ≥ 0.21.0 for the `gemma4` manifest; this project pins `ollama/ollama:0.23.1`.

### PDF Ingestion

PDF text extraction now uses `opendataloader-pdf==2.4.1` in local mode with OpenJDK 17 inside the `pdf-ingest` container. It produces structure-aware chunks with reading order, heading breadcrumbs, tables, image bounding boxes, page sizes, element IDs, and extractor provenance stored in `rag_chunks.meta`.

PyMuPDF remains in the service for image post-processing, external-image dimension checks, and fallback handling. Embeddings still use `bge-m3`; PDF image captions still use `qwen2.5vl:7b`.

The May 5, 2026 reprocess snapshot is `data/demo_snapshot_pre_opendataloader_20260505_172446.sql`; old PDF assets were preserved under `data/assets/_pre_opendataloader_20260505_172446/`. Current PDF corpus: 5 PDFs, 1,648 chunks, all 1,648 with `meta.bbox`. Known caveat: BMW Group text extraction produced 486 noisy text chunks that are stored without embeddings and flagged with `meta.embedding_error`; image chunks and structured metadata are present.

## Prerequisites

- Docker and Docker Compose
- NVIDIA GPU with driver + NVIDIA Container Toolkit (for Ollama)
- ~20 GB disk for models + container images

## Quick Start

1. **Clone and configure:**

```bash
git clone https://github.com/amrayach/mmrag.git
cd mmrag
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, N8N_ENCRYPTION_KEY, PUID/PGID
```

2. **Initialize directories:**

```bash
chmod +x scripts/*.sh reset_demo.sh
./scripts/init_dirs.sh
```

3. **Launch the stack:**

```bash
docker compose up -d --build
./scripts/health_check.sh
```

4. **Pull Ollama models** (first run only, ~15 GB):

```bash
./scripts/setup_models.sh
```

5. **Set up n8n** (see [MANUAL_STEPS.md](MANUAL_STEPS.md)):
   - Create owner account
   - Add PostgreSQL credential
   - Import and activate workflows from `n8n/workflows/`

6. **Configure OpenWebUI:**
   - Add OpenAI-compatible provider pointing to `http://rag-gateway:8000/v1`
   - Set up welcome banner and starter questions (see MANUAL_STEPS.md)

## Usage

1. Upload PDFs via FileBrowser into `data/inbox/`
2. Ingestion starts automatically when the `pdf-ingest` watcher sees a stable file; the n8n `/webhook/ingest-now` endpoint remains available as a manual scan trigger
3. Chat in OpenWebUI — answers stream token-by-token with relevant text chunks, inline images, and source citations

### Demo Mode

For live demos, stop background GPU consumers and pre-warm models:

```bash
make demo-start   # Stops rss-ingest, pre-warms models, shows dashboard
make demo-stop    # Restarts rss-ingest
```

### Reset demo data

```bash
./reset_demo.sh
```

This truncates the RAG tables and clears `data/processed/` and `data/assets/`.

## Port Map

All ports bind to `127.0.0.1` only (not publicly exposed).

| Port | Service |
|------|---------|
| 56150 | n8n |
| 56151 | OpenWebUI |
| 56152 | FileBrowser |
| 56153 | Adminer |
| 56154 | PostgreSQL |
| 56155 | RAG Gateway |
| 56156 | Control Center |
| 56157 | Assets (nginx + gallery) |

Use a reverse proxy or Tailscale Serve to expose services on your network.

## Project Structure

```
.
├── db/init/              # SQL init scripts (schema + pgvector setup)
├── services/
│   ├── pdf-ingest/       # PDF processing microservice (FastAPI)
│   ├── rss-ingest/       # RSS feed ingestion microservice (FastAPI)
│   ├── rag-gateway/      # OpenAI-compatible streaming proxy (FastAPI)
│   └── controlcenter/    # Unified dashboard, readiness, docs, ingestion controls
├── n8n/workflows/        # Exportable n8n workflow JSONs
├── nginx/                # Custom nginx config (assets gallery)
├── scripts/              # Setup, health check, demo mode, prewarm scripts
├── data/                 # Runtime data (inbox, processed, assets)
├── docs/                 # Demo guides, architecture, dress rehearsal
│   ├── DEMO_GUIDE.md     # German demo guide
│   ├── DEMO_GUIDE_EN.md  # English demo guide
│   ├── DRESS_REHEARSAL.md # 3-track rehearsal checklist
│   └── architecture.md   # Architecture overview
├── docker-compose.yml
├── Makefile              # Common tasks (up, down, demo-start, test-rag, etc.)
├── .env.example
└── MANUAL_STEPS.md       # Post-deploy manual configuration steps
```

## License

MIT
