# MMRAG — Multimodal RAG Demo

A self-hosted, GPU-accelerated **Retrieval-Augmented Generation** pipeline that ingests PDFs (text + images), stores vector embeddings in PostgreSQL/pgvector, and serves answers through a chat UI — all orchestrated by n8n workflows running on a local Ollama instance.

## Architecture

```
Chat flow:
  OpenWebUI → rag-gateway (OpenAI-compatible API) → n8n (Chat Brain workflow)
    → PostgreSQL/pgvector (vector search) + Ollama (LLM)

Ingestion flow:
  FileBrowser upload → data/inbox/ → n8n (Ingestion Factory workflow)
    → pdf-ingest → PostgreSQL/pgvector + assets/ (nginx)
```

### Services (9 containers)

| Service | Description |
|---------|-------------|
| **postgres** | PostgreSQL 15 with pgvector for document storage and vector search |
| **n8n** | Workflow automation — runs Chat Brain and Ingestion Factory workflows |
| **ollama** | Local LLM inference (GPU-accelerated) |
| **rag-gateway** | OpenAI-compatible API proxy that routes chat requests through n8n |
| **pdf-ingest** | PDF processing: text extraction, image captioning, embedding generation |
| **openwebui** | Chat UI frontend |
| **filebrowser** | Web-based file manager for PDF uploads |
| **adminer** | Database admin UI |
| **assets** | Nginx serving extracted images for inline display in chat answers |

### Models (Ollama)

| Model | Purpose |
|-------|---------|
| `qwen2.5:7b-instruct` | Text generation (chat answers) |
| `qwen2.5vl:7b` | Vision model (image captioning during ingestion) |
| `nomic-embed-text` | Embedding generation (768-dim vectors) |

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

## Usage

1. Upload PDFs via FileBrowser into `data/inbox/`
2. Trigger ingestion: wait for the 2-minute cron, or call the `/webhook/ingest-now` endpoint in n8n
3. Chat in OpenWebUI — answers include relevant text chunks and inline images from your documents

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
| 56157 | Assets (nginx) |

Use a reverse proxy or Tailscale Serve to expose services on your network.

## Project Structure

```
.
├── db/init/              # SQL init scripts (schema + pgvector setup)
├── services/
│   ├── pdf-ingest/       # PDF processing microservice (FastAPI)
│   └── rag-gateway/      # OpenAI-compatible chat proxy (FastAPI)
├── n8n/workflows/        # Exportable n8n workflow JSONs
├── scripts/              # Setup, health check, model pull scripts
├── data/                 # Runtime data (inbox, processed, assets)
├── docs/                 # Architecture and port documentation
├── docker-compose.yml
├── .env.example
└── MANUAL_STEPS.md       # Post-deploy manual configuration steps
```

## License

MIT
