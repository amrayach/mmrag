# MMRAG Architecture

## Chat Flow (Streaming)

```
OpenWebUI
  │  POST /v1/chat/completions (stream=true)
  ▼
rag-gateway (FastAPI, OpenAI-compatible)
  │  1. POST /webhook/rag-chat → n8n
  ▼
n8n Chat Brain (6 nodes):
  Webhook → Extract Query → Embed (Ollama) → Vector Literal → Vector Search (Postgres) → Build Context
  │  Returns: chatRequestBody, imageObjects, sources
  ▼
rag-gateway
  │  2. POST /api/chat (stream=true) → Ollama
  │  3. Translates Ollama NDJSON → OpenAI SSE chunks
  │  4. Appends images (![caption](url)) and sources as final chunk
  ▼
OpenWebUI (token-by-token streaming)
```

## Ingestion Flows

```
PDF Ingestion:
  FileBrowser upload → data/inbox/
    → n8n Ingestion Factory (every 2 min or manual webhook)
    → pdf-ingest service (text extraction, image captioning, embedding)
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
| 56157 | Assets       |

### Tailnet (Tailscale Serve)

| Port | Service      |
|------|-------------|
| 8450 | n8n          |
| 8451 | OpenWebUI    |
| 8452 | FileBrowser  |
| 8453 | Adminer      |
| 8454 | Assets       |

## Key Components

| Component | Tech | Role |
|-----------|------|------|
| rag-gateway | FastAPI | OpenAI API proxy + Ollama SSE translator |
| n8n | Node.js | Workflow orchestration (embedding, vector search, context assembly) |
| Ollama | Go | Local GPU inference (text, vision, embeddings) |
| PostgreSQL | pgvector | Vector storage + similarity search |
| pdf-ingest | FastAPI | PDF text/image extraction + captioning |
| rss-ingest | FastAPI | RSS feed scraping + image captioning |
| Assets (nginx) | Nginx | Static image serving + gallery UI |
