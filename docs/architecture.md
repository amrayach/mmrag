# MMRAG Architecture

## Chat Flow (Streaming)

```
OpenWebUI
  │  POST /v1/chat/completions (stream=true)
  ▼
rag-gateway (FastAPI, OpenAI-compatible)
  │  1. Embed query with Ollama bge-m3
  ▼
PostgreSQL/pgvector
  │  2. Direct vector search + source/image slot reservation
  ▼
rag-gateway
  │  3. Build context locally
  │  4. POST /api/chat (stream=true) → Ollama
  │  5. Translate Ollama NDJSON → OpenAI SSE chunks
  │  6. Append images (![caption](url)) and sources as final chunk
  ▼
OpenWebUI (token-by-token streaming)
```

n8n Chat Brain remains available as a context-only workflow/fallback path, but the running demo uses `CONTEXT_MODE=direct` in `rag-gateway`.

## Current Runtime Models

| Role | Model | Notes |
|------|-------|-------|
| Text generation | `gemma4:26b` | Production default after the May 6, 2026 A/B. MoE model with 4B active params per token; fixed eval averaged 7.0s total latency vs 9.8s for the prior 7B baseline. |
| Image captioning | `qwen2.5vl:7b` | Used during PDF/RSS ingestion only, not during query-time generation. |
| Embeddings | `bge-m3` | Multilingual 1024-dimensional embeddings for text chunks and image captions. |

The Ollama container is pinned to `ollama/ollama:0.23.1` so the Gemma 4 manifest loads correctly. The three active production models are kept warm with `OLLAMA_MAX_LOADED_MODELS=3`.

## Ingestion Flows

```
PDF Ingestion:
  FileBrowser upload → data/inbox/
    → pdf-ingest watcher or n8n manual scan trigger
    → OpenDataLoader PDF layout extraction (local mode, Java 17)
    → section/table/image chunks with bounding boxes in rag_chunks.meta
    → qwen2.5vl image captioning + bge-m3 embeddings
    → PostgreSQL/pgvector + data/assets/ (nginx)

RSS Ingestion:
  rss-ingest service (scheduled every 8h or manual webhook)
    → Fetch feeds → Scrape articles → Caption images (Ollama vision)
    → Chunk text → Generate embeddings → PostgreSQL/pgvector + data/assets/
```

## Port Map

### Localhost Binds

| Port  | Service      |
|-------|-------------|
| 56150 | n8n          |
| 56151 | OpenWebUI    |
| 56152 | FileBrowser  |
| 56153 | Adminer      |
| 56154 | PostgreSQL   |
| 56155 | RAG Gateway  |
| 56156 | Control Center |
| 56157 | Assets       |

### Tailnet (Tailscale Serve)

| Port | Service      |
|------|-------------|
| 8450 | n8n          |
| 8451 | OpenWebUI    |
| 8452 | FileBrowser  |
| 8453 | Adminer      |
| 8454 | Assets       |
| 8455 | Control Center |

## Key Components

| Component | Tech | Role |
|-----------|------|------|
| rag-gateway | FastAPI | OpenAI API proxy + Ollama SSE translator |
| n8n | Node.js | Workflow orchestration, ingestion triggers, and context-only fallback workflow |
| Ollama | Go | Local GPU inference (text, vision, embeddings) |
| PostgreSQL | pgvector | Vector storage + similarity search |
| pdf-ingest | FastAPI + OpenDataLoader PDF | Structured PDF text/image extraction + captioning |
| rss-ingest | FastAPI | RSS feed scraping + image captioning |
| Control Center | FastAPI + static JS | Dashboard, readiness, docs, ingestion controls |
| Assets (nginx) | Nginx | Static image serving + gallery UI |
