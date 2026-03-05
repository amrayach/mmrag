# MMRAG Demo — Dress Rehearsal Checklist

Use this checklist to prepare and run the demo. Choose the track that matches your audience.

---

## Pre-Demo Setup (All Tracks)

- [ ] Run `make demo-start` (stops rss-ingest, pre-warms models)
- [ ] Verify dashboard shows all services healthy
- [ ] Open OpenWebUI in browser, confirm model is selectable
- [ ] Open Asset Gallery in a second tab (https://spark-e010.tail907fce.ts.net:8454)
- [ ] Clear any previous chat history in OpenWebUI
- [ ] Have a PDF ready in `data/inbox/` (if showing live ingestion)
- [ ] Run `bash scripts/demo_readiness_check.sh` — all checks must PASS

---

## Track 1: Executive (15 min)

**Audience:** Leadership, non-technical stakeholders
**Focus:** What it does, why it matters

| Time | Step | What to Show |
|------|------|-------------|
| 0:00 | **Intro** | "This system answers questions using your internal documents and live news feeds." |
| 1:00 | **PDF Query** | Ask: "Was steht im Handbuch zur Wartung?" — show answer with page references |
| 3:00 | **RSS Query** | Ask: "Was sind die neuesten Technologie-Nachrichten?" — show live news answers with source links |
| 5:00 | **Image Query** | Ask: "Zeige mir Bilder aus dem Handbuch" — show inline image display |
| 7:00 | **Cross-source** | Ask: "Vergleiche die Handbuch-Informationen mit aktuellen Nachrichten" — show multi-source synthesis |
| 10:00 | **Architecture** | Show the n8n workflow (1 slide/screen) — "Embedding, vector search, LLM — all orchestrated visually" |
| 12:00 | **Gallery** | Show Asset Gallery — "Every image extracted is browsable" |
| 14:00 | **Q&A** | Answer questions |

- [ ] Rehearsed intro pitch (under 60 seconds)
- [ ] Tested all 4 demo queries and confirmed they produce good answers
- [ ] Verified streaming works (tokens appear progressively)

---

## Track 2: Mixed Audience (30 min)

**Audience:** Product managers, tech leads, mixed roles
**Focus:** Capabilities + architecture overview

| Time | Step | What to Show |
|------|------|-------------|
| 0:00 | **Intro** | System overview, architecture diagram |
| 3:00 | **PDF Query** | Ask a question about uploaded PDF content |
| 6:00 | **RSS Query** | Ask about recent news, show source links |
| 9:00 | **Multimodal** | Ask about images, show captions and inline images |
| 12:00 | **Cross-source** | Query combining PDF and RSS knowledge |
| 15:00 | **n8n Workflow** | Walk through Chat Brain workflow nodes |
| 19:00 | **Live Ingestion** | Upload a new PDF via FileBrowser, trigger ingestion, query it |
| 24:00 | **Asset Gallery** | Browse extracted images |
| 26:00 | **Architecture** | Docker Compose stack, services overview |
| 28:00 | **Q&A** | Answer questions |

- [ ] Rehearsed all queries and verified good answers
- [ ] Tested live PDF upload + ingestion cycle (< 3 min for a short PDF)
- [ ] Prepared architecture slide or `docs/architecture.md` on screen
- [ ] Verified n8n UI loads with workflow visible

---

## Track 3: Technical Deep Dive (45 min)

**Audience:** Engineers, data scientists, DevOps
**Focus:** How it works, how to extend it

| Time | Step | What to Show |
|------|------|-------------|
| 0:00 | **Architecture** | docker-compose.yml, service diagram, port map |
| 5:00 | **PDF Query** | Live query with streaming, explain SSE translation |
| 8:00 | **n8n Chat Brain** | Walk through each node: webhook, extract, embed, vector search, context build |
| 14:00 | **RAG Gateway** | Show `main.py` — Ollama NDJSON to OpenAI SSE translation |
| 18:00 | **Vector Search** | Show Postgres pgvector query, cosine distance, explain thresholds |
| 22:00 | **PDF Ingestion** | Upload PDF, show `pdf-ingest` service processing, Adminer for DB inspection |
| 28:00 | **RSS Ingestion** | Show RSS feed config, scraper, image captioning pipeline |
| 33:00 | **Multimodal** | Image extraction, captioning with vision model, gallery |
| 37:00 | **Infrastructure** | Ollama GPU config, model management, health checks |
| 40:00 | **Extensibility** | How to add new feeds, new document types, swap models |
| 43:00 | **Q&A** | Technical questions |

- [ ] Rehearsed all queries including edge cases (empty results, @filename filter)
- [ ] Tested PDF upload + full ingestion cycle end-to-end
- [ ] Opened Adminer and verified rag_chunks table is visible
- [ ] Tested `@filename` filter query syntax
- [ ] Prepared code editor/terminal for showing source files
- [ ] Verified `make test-rag` returns valid response

---

## Post-Demo

- [ ] Run `make demo-stop` to restart rss-ingest
- [ ] Note any issues encountered during demo
- [ ] Save interesting queries that worked well for future demos
