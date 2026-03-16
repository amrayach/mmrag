# MMRAG Demo Guide

This guide provides step-by-step instructions for presenting the MMRAG (Multimodal Retrieval-Augmented Generation) demo. It is written so that anyone — even someone who didn't build the system — can run the demo.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Pre-Demo Checklist](#2-pre-demo-checklist)
3. [Demo Part 1: Upload a PDF Document](#3-demo-part-1-upload-a-pdf-document)
4. [Demo Part 2: Chat Q&A with Documents](#4-demo-part-2-chat-qa-with-documents)
5. [Demo Part 3: RSS Feeds & Multi-Source](#5-demo-part-3-rss-feeds--multi-source)
6. [Demo Part 4: Under the Hood (Architecture)](#6-demo-part-4-under-the-hood-architecture)
7. [Troubleshooting](#7-troubleshooting)
8. [Resetting the Demo](#8-resetting-the-demo)

---

## 1. System Overview

### What is MMRAG?

MMRAG is a **locally hosted AI system** that understands documents (PDFs, RSS feeds) and can answer questions about them — including images and source citations. All data stays on the server; nothing goes to the cloud.

### Core Capabilities

- **PDF Analysis**: Upload PDFs — text and images are automatically extracted and understood
- **RSS Integration**: News articles are automatically ingested and become searchable
- **Multimodal Answers**: Responses include text, source citations, and relevant images
- **German Language**: The system is optimized for German text processing
- **Vector Search**: Semantic search — finds content by meaning, not just keywords

### Architecture (Simplified)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  OpenWebUI   │     │ FileBrowser  │     │   Adminer    │
│  (Chat UI)   │     │ (Upload UI)  │     │  (Database)  │
└──────┬───────┘     └──────┬───────┘     └──────────────┘
       │                    │
       ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ RAG-Gateway  │     │  PDF-Ingest  │     │  RSS-Ingest  │
│ (Streaming)  │     │ (Processing) │     │  (Feeds)     │
└──┬───────┬───┘     └──────┬───────┘     └──────┬───────┘
   │       │                │                    │
   ▼       ▼                ▼                    ▼
┌──────┐ ┌──────┐    ┌──────────────┐     ┌──────────────┐
│ n8n  │ │Ollama│    │  PostgreSQL  │◄───►│   Ollama     │
│(Ctx) │ │(LLM) │    │  (pgvector)  │     │  (GPU)       │
└──────┘ └──────┘    └──────────────┘     └──────────────┘
```

> **Note:** RAG-Gateway retrieves context from n8n and then streams directly from Ollama — token by token in real-time.

### Data Flow: From Document to Answer

```
Upload PDF ──► Extract text + images ──► Split into chunks
                                                │
                                                ▼
                                      Compute vectors (embeddings)
                                                │
                                                ▼
                                        Store in database
                                                │
                                                ▼
Ask a question ──► Vectorize question ──► Find similar chunks ──► Generate answer
                                                                       │
                                                                       ▼
                                                          Answer + images + sources
```

### Access URLs (Tailscale)

| Service | URL | Purpose |
|---------|-----|---------|
| OpenWebUI | https://spark-e010.tail907fce.ts.net:8451 | Chat interface |
| FileBrowser | https://spark-e010.tail907fce.ts.net:8452 | File uploads |
| n8n | https://spark-e010.tail907fce.ts.net:8450 | Workflow editor |
| Adminer | https://spark-e010.tail907fce.ts.net:8453 | Database viewer |
| Assets | https://spark-e010.tail907fce.ts.net:8454 | Extracted images |

> **Note:** All URLs are only accessible via Tailscale (no public access).

---

## 2. Pre-Demo Checklist

Complete these steps **15 minutes before the demo**.

### 2.1 Run the Automated Check

SSH into the server and run the readiness script:

```bash
cd /srv/projects/ammer/mmrag-n8n-demo-v2
bash scripts/demo_readiness_check.sh
```

The script checks 15 points:
- All 10 containers are running
- Ollama models are loaded
- n8n webhooks are reachable
- n8n context pipeline works
- SSE streaming from RAG gateway
- Demo mode active (rss-ingest stopped)
- Tailscale Serve rules active
- Tailnet URLs are accessible

**Expected result:** `DEMO READY` at the end of the output.

### 2.2 If the Check Fails

| Problem | Solution |
|---------|----------|
| Containers not started | `cd /srv/projects/ammer/mmrag-n8n-demo-v2 && docker compose up -d` |
| Ollama models missing | `bash scripts/setup_models.sh` (takes ~5-10 min) |
| Webhooks not reachable | Log into n8n, check and activate workflows |
| Tailscale URLs not reachable | Check `tailscale serve status`, re-set rules if needed |

### 2.3 Activate Demo Mode (Recommended)

Demo mode stops the RSS ingest (prevents GPU contention), warms up all models, and shows a status dashboard:

```bash
make demo-start
```

After the demo, restore normal operation:

```bash
make demo-stop
```

### 2.4 Prepare a Demo Document

Have a suitable PDF ready (e.g., a user manual, report, or datasheet). Ideal properties:
- **2-10 pages** (short processing time)
- **Contains text and images** (showcases multimodal capabilities)
- **German language** (optimized processing)
- **Specific content** (enables targeted questions)

### 2.5 Want a Fresh Demo?

If you don't want pre-existing data in the demo:

```bash
bash reset_demo.sh
```

> **Warning:** Deletes all ingested documents and chunks. Cannot be undone.

---

## 3. Demo Part 1: Upload a PDF Document

> **Presenter note:** *"We'll now show how a document is ingested into the system. From upload to availability in the chat typically takes 1-2 minutes."*

### Step 1: Open FileBrowser

1. Open in browser: **https://spark-e010.tail907fce.ts.net:8452**
2. Log in (ask the administrator for credentials)
3. Navigate to the `inbox/` folder

### Step 2: Upload the PDF

1. Click **Upload** (top right)
2. Select the prepared PDF
3. Wait for the upload to complete
4. The file appears in the `inbox/` folder

> **Presenter note:** *"The system automatically checks for new files in the inbox every 2 minutes. But we can also trigger processing immediately."*

### Step 3: Trigger Processing Immediately

**Option A — Via n8n (visual, recommended for the demo):**

1. Open n8n: **https://spark-e010.tail907fce.ts.net:8450**
2. Log in (see CREDENTIALS.md — not tracked in git)
3. Open the **"Ingestion Factory"** workflow
4. Click **"Test Workflow"** at the top
5. Watch the execution — each node turns green when successful

**Option B — Via command line (faster):**

```bash
make ingest
```

### Step 4: Verify Processing

The output shows:

```json
{
  "status": "ok",
  "processed_count": 1,
  "processed": [
    {
      "filename": "example.pdf",
      "pages": 5,
      "text_chunks": 12,
      "image_chunks": 3
    }
  ]
}
```

> **Presenter note:** *"The system analyzed the PDF page by page: 12 text segments and 3 images were extracted, converted into vectors, and stored in the database. The document is now searchable."*

### Step 5 (Optional): Show in the Database

1. Open Adminer: **https://spark-e010.tail907fce.ts.net:8453**
2. Log in: System `PostgreSQL`, Server `postgres`, username and password from `.env`
3. Database `rag` → Table `rag_chunks` → **Select data**
4. Show the new entries with `doc_id`, `chunk_type`, `content_text`, and `embedding`

> **Presenter note:** *"Here we see the raw data: each text segment received a 768-dimensional vector. Images were described by the vision model and also stored as vectors."*

---

## 4. Demo Part 2: Chat Q&A with Documents

> **Presenter note:** *"Now we'll show the heart of the system: we ask questions and get answers based on the ingested documents."*

### Step 1: Open OpenWebUI

1. Open in browser: **https://spark-e010.tail907fce.ts.net:8451**
2. Log in or create a new account
3. Start a new chat

### Step 2: Ask a Simple Text Question

Enter a question that relates directly to the uploaded PDF. Examples:

- *"What are the key points in the document?"*
- *"Summarize the document in 3 sentences."*
- *"What technical specifications are mentioned?"*

**Expected result:**
- A German-language answer
- Source citations at the end (filename, page number)

> **Presenter note:** *"The system encoded the question as a vector, found the most similar text segments in the database, and generated an answer from them. Note the source citations — you can trace where the information comes from."*

### Step 3: Ask a Question About Image Content

Ask a question that relates to images in the document:

- *"What figures does the document contain?"*
- *"What does the diagram on page 2 show?"*
- *"Describe the graphics in the document."*

**Expected result:**
- Answer referencing image content
- Embedded images displayed directly in the chat (as previews)
- Image descriptions generated by the vision model

> **Presenter note:** *"The system shows not only text but also relevant images from the document. These were analyzed by the vision model during ingestion and described, making them semantically searchable."*

### Step 4: Ask a Follow-Up Question

Without providing new context, ask a follow-up:

- *"Can you explain that in more detail?"*
- *"What does that mean specifically?"*

> **Presenter note:** *"The system recognizes follow-up questions and automatically includes the previous context. It internally rewrites the question so that the vector search still returns relevant results."*

### Step 5 (Optional): Use the Document Filter

Search within a specific document using the `@` prefix:

- *"@example.pdf What's on page 3?"*

> **Presenter note:** *"With the @ prefix, you can restrict the search to a specific document. Useful when many documents are in the system."*

---

## 5. Demo Part 3: RSS Feeds & Multi-Source

> **Presenter note:** *"The system can process not only PDFs but also news articles from RSS feeds automatically. We'll show how different sources are combined in a single answer."*

### Step 1: Check RSS Status

If RSS feeds have already been ingested, skip to Step 3.

Otherwise, trigger RSS ingestion:

**Option A — Via n8n:**
1. Open n8n
2. Open the **"RSS Ingestion"** workflow
3. Click **"Test Workflow"**
4. Wait (can take 1-5 minutes depending on the number of articles)

**Option B — Via command line:**

```bash
make rss-ingest
```

### Step 2: Verify the Result

```json
{
  "status": "ok",
  "feeds_processed": 2,
  "articles_ingested": 15,
  "chunks_created": 90
}
```

> **Presenter note:** *"15 news articles from 2 RSS feeds were automatically downloaded, split into text segments, and stored as vectors."*

### Step 3: RSS Text + Image Query

In OpenWebUI, ask a question about a recent news topic:

- *"Was berichten die Nachrichten über KI-Infrastruktur?"*
- *"Zeige mir aktuelle Technologie-Nachrichten mit Bildern"*
- *"Was sind die neuesten Nachrichten von heise online?"*

**Expected result:**
- German-language answer citing RSS feed sources
- Inline images from the articles (displayed as previews)
- Source links at the end (clickable markdown links to original articles)

> **Presenter note:** *"The system retrieves both text and images from news articles. Images were analyzed by the vision model and are semantically searchable — asking about a topic can surface relevant photos from news articles."*

### Step 4: Multi-Source Query

In OpenWebUI, ask a question that could involve both PDF and RSS content:

- *"What's new on the topic of [topic from the PDF or feeds]?"*
- *"Compare the information from different sources."*

**Expected result:**
- Answer combines information from PDFs and RSS articles
- Source citations show different origins (filename vs. feed name/URL)

> **Presenter note:** *"Here we see how the system merges different sources — an uploaded PDF and news articles — into a single answer. The source citations show exactly where each piece of information comes from."*

---

## 6. Demo Part 4: Under the Hood (Architecture)

> **Presenter note:** *"For those interested in the technical details, let's look behind the scenes: how does the system work internally?"*

### 6.1 Show n8n Workflows

1. Open n8n: **https://spark-e010.tail907fce.ts.net:8450**
2. Log in (see CREDENTIALS.md — not tracked in git)

**Show the Chat Brain workflow:**
1. Open the **"Chat Brain"** workflow
2. Explain the data flow: `Webhook → Extract query → Embedding → Vector literal → Vector search → Build context`
3. Explain: "n8n delivers the context — the actual answer is streamed by the RAG gateway directly from Ollama, token by token."

> **Presenter note:** *"The workflow has 6 nodes: it receives the question, computes the search vector, finds the relevant text segments, and builds the context. The answer generation then happens directly — tokens are streamed to the browser in real-time."*

**Show the Ingestion Factory:**
1. Open the **"Ingestion Factory"** workflow
2. Explain: Scheduled (every 2 min) + manually triggerable, processes 1 PDF at a time

> **Presenter note:** *"Ingestion runs automatically in the background. New PDFs in the inbox folder are detected and processed. The workflow calls our Python service, which handles the actual text extraction and AI processing."*

### 6.2 Show Database Structure

1. Open Adminer: **https://spark-e010.tail907fce.ts.net:8453**
2. Select database `rag`

**Explain the tables:**

| Table | Contents |
|-------|----------|
| `rag_docs` | Document metadata (filename, SHA256 hash, language, page count) |
| `rag_chunks` | Individual text segments + images with 768-dim vectors |

3. Run a SQL query (in Adminer's SQL field):

```sql
SELECT chunk_type, COUNT(*),
       AVG(LENGTH(content_text)) AS avg_text_length
FROM rag_chunks
GROUP BY chunk_type;
```

> **Presenter note:** *"In the database, we can see how many text and image chunks are stored. Each chunk has a 768-dimensional vector representing its semantic content. The database uses pgvector for similarity search."*

### 6.3 Show Local AI Models

Three models run locally on the GPU:

| Model | Task | Size |
|-------|------|------|
| `qwen2.5:7b-instruct` | Text generation (answers) | ~4.7 GB |
| `nomic-embed-text` | Vectorization (embeddings) | ~274 MB |
| `qwen2.5vl:7b` | Image recognition (vision) | ~4.7 GB |

> **Presenter note:** *"All three AI models run locally on the GPU — no API calls to OpenAI or other cloud services. The data never leaves the server."*

### 6.4 Show Asset Gallery (Optional)

1. Open the asset gallery: **https://spark-e010.tail907fce.ts.net:8454**
2. Browse extracted images — the gallery shows all images as tiles with folder filtering
3. Click an image for full-size view (lightbox)

> **Presenter note:** *"Here you can see all extracted images from PDFs and RSS feeds in a browsable gallery. You can filter by folder and view images at full size. These are the same images that appear as previews in the chat answers."*

---

## 7. Troubleshooting

### Chat Not Responding or Very Slow

| Symptom | Cause | Solution |
|---------|-------|----------|
| No response | Ollama is not running | Check `docker compose ps ollama`, start with `docker compose start ollama` |
| Timeout (504) | Model is loading | Wait 30 sec, try again. Pre-warm with: `bash scripts/prewarm.sh` |
| Empty response | No documents ingested | Upload and process a PDF first |
| Error 503 | n8n not reachable | Check `docker compose ps n8n`, are workflows activated? |

### PDF Not Being Processed

| Symptom | Cause | Solution |
|---------|-------|----------|
| Status `busy` | Another processing job is running | Wait 2 minutes, try again |
| Status `skipped` | PDF already processed | Use a different PDF or reset the demo |
| Status `error` | File corrupted or too large | Maximum size: 100 MB. Check the file. |

### Images Not Displaying

| Symptom | Cause | Solution |
|---------|-------|----------|
| Broken image icon | Assets server not reachable | Check `docker compose ps assets` |
| No images in response | PDF contains no images | Use a different PDF with images |
| No RSS images | Articles ingested before captioning | Run `docker exec ammer_mmragv2_rss_ingest curl -s -X POST "http://localhost:8002/ingest/backfill-images?limit=50"` |

### General Diagnostics

```bash
# Status of all containers
docker compose ps

# Logs of a specific service (e.g., rag-gateway)
docker compose logs --tail=20 rag-gateway

# Full health check
bash scripts/health_check.sh

# Demo readiness check
bash scripts/demo_readiness_check.sh
```

---

## 8. Resetting the Demo

### Full Reset (Delete All Documents)

```bash
cd /srv/projects/ammer/mmrag-n8n-demo-v2
bash reset_demo.sh
```

This script:
- Truncates the `rag_docs` and `rag_chunks` tables
- Deletes processed PDFs from `data/processed/`
- Deletes extracted images from `data/assets/`

### Reset RSS Data Only (Keep PDFs)

```bash
bash reset_demo.sh --rss-only
```

### After the Reset

1. Copy the demo PDF back into `data/inbox/` if needed
2. Trigger processing: `make ingest`
3. Verify that the chat responds again

---

## Appendix: Credentials

See **CREDENTIALS.md** (not tracked in git) for all service logins and passwords.

---

## Appendix: Useful Commands

```bash
# Start the stack
make up

# Stop the stack
make down

# Follow logs
make logs

# Health check
make health

# Warm up Ollama
make prewarm

# Activate demo mode (stops RSS, warms up)
make demo-start

# Deactivate demo mode
make demo-stop

# Trigger PDF processing
make ingest

# Ingest RSS feeds
make rss-ingest

# Send a test query
make test-rag

# Full demo reset
make reset
```
