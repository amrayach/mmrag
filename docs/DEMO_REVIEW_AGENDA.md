# MMRAG Demo System — Review Session

**Date:** Tuesday, May 5, 2026
**Participants:** Amay, Sven
**Duration:** ~60 minutes
**Access:** https://spark-e010.tail907fce.ts.net:8451 (OpenWebUI), https://spark-e010.tail907fce.ts.net:8455 (Control Center)

---

## System Overview

### What It Is

A self-hosted multimodal RAG (Retrieval-Augmented Generation) system that:
- Ingests PDFs and RSS news feeds (text + images)
- Embeds content with bge-m3 (multilingual, 1024-dim)
- Stores vectors in PostgreSQL/pgvector
- Answers questions via streaming chat UI (OpenWebUI)
- Uses qwen2.5:7b-instruct for generation, qwen2.5vl:7b for image captioning
- Uses OpenDataLoader PDF for structured PDF extraction, heading breadcrumbs, tables, images, and bounding boxes
- Runs entirely on the DGX Spark — no external API calls, no data leaves the server

### Architecture (simplified)

```
User → OpenWebUI → rag-gateway → pgvector (direct retrieve) + Ollama (generate) → streaming response
Ingestion: PDF/RSS → extract structured text + images → caption images → embed → store
```

### What's In the Knowledge Base

- **TechVision AG Jahresbericht 2025** — synthetic German company report (32 chunks: 24 text + 8 image)
- **Siemens Nachhaltigkeitsbericht** — real corporate sustainability report (152 chunks: 113 text + 39 image)
- **Siemens Annual Report 2024** — real annual report (119 chunks: 117 text + 2 image)
- **BMW Geschäftsbericht 2023** — real report (1,342 chunks: 1,297 text + 45 image; 486 noisy text chunks are stored without embeddings and flagged)
- **watcher_test.pdf** — small canary document (3 text chunks)
- **~3,926 RSS/news documents** from spiegel.de, tagesschau.de, heise.de, zdf, dw, faz, spektrum
- **Total: 15,332 chunks** (14,223 text + 1,109 image) across 3,931 documents
- **PDF metadata:** all 1,648 PDF chunks carry `meta.bbox` after the May 5 OpenDataLoader reprocess

---

## Guided Demo (15-20 minutes)

### Prompt Sequence

Each prompt showcases a specific capability. Run them in order — prompts 1-4 are in one chat session (multi-turn), prompts 5-8 are separate chats.

| # | Prompt | Capability | Expected |
|---|--------|-----------|----------|
| 1 | "Welche fünf strategischen Megatrends nennt TechVision AG in ihrem Jahresbericht 2025? Liste alle fünf auf." | **Deep PDF retrieval** — structured answer with page citations | 5 megatrends listed, page refs, strategy diagram image |
| 2 | "Welche konkreten Umsatzzahlen und Wachstumsziele hat sich das Unternehmen dabei gesetzt?" | **Multi-turn intelligence** — "dabei" triggers follow-up context from P1 | 1.05-1.10 Mrd 2026, 1.5 Mrd 2028, EBIT targets |
| 3 | "@TechVision Welche Nachhaltigkeitsziele und CO₂-Reduktionszahlen werden im Bericht genannt?" | **Document scoping** — @filename restricts search | 42% CO₂ reduction, 78% recycling, EcoVadis 91/100 |
| 4 | "@TechVision Zeige mir die Produktbilder und Diagramme aus dem Bericht" | **Multimodal** — images retrieved and displayed alongside text | 3 chart images with captions (revenue, CO₂, tech stack) |
| 5 | "Was berichten aktuelle Nachrichten über KI und Robotik in Deutschland?" | **Live news** — real RSS content with source links | Mix of seeded + real articles from spiegel, heise, tagesschau |
| 6 | "Vergleiche TechVisions KI-Strategie aus ihrem Jahresbericht mit den aktuellen Branchentrends aus den Nachrichten. Nutze sowohl den PDF-Bericht als auch RSS-Nachrichtenquellen." | **Cross-source synthesis** — PDF + news combined | Side-by-side analysis: TechVision strategy vs. industry trends |
| 7 | "@Nachhaltigkeit Welche Megatrends nennt Siemens in ihrem Nachhaltigkeitsbericht?" | **Multi-document** — works across different companies | Siemens megatrends from real PDF with page refs |
| 8 | "@BMWGroup Zeige mir Bilder von BMW Fahrzeugen aus dem Geschäftsbericht" | **Real annual-report images** — image extraction from real documents | 2-3 BMW car photos with AI-generated captions |

**Timing note:** Prompts take 25-95 seconds depending on complexity. The 7B model is the bottleneck — a 14B+ model would be faster per token but needs more VRAM.

---

## Open Exploration (20-30 minutes)

Sven gets access to explore freely. Suggested areas to test:

### Things That Work Well
- German-language queries (bge-m3 multilingual embeddings)
- Document-scoped queries (`@filename` syntax)
- Follow-up questions with pronouns/deictic words (dabei, dazu, davon)
- Image retrieval with explicit requests ("Zeige mir...", "Bilder von...")
- Source attribution (page numbers for PDFs, links for RSS)
- Streaming — tokens appear progressively in the UI

### Known Limitations (be upfront about these)
- **7B model constraints**: Answers can be repetitive, miss nuance, or list fewer items than exist in context. The next text-model evaluation should start with `qwen3.6:27b`, then `qwen3:30b` and `mistral-small3.2:24b`.
- **Response time**: 25-95 seconds per query. First query after idle is slowest (model loading).
- **Image relevance in unfiltered queries**: Images only appear when their document also has text hits (by design — prevents noise). Use `@filename` + image keywords to force image retrieval.
- **RSS image quality**: Some RSS images have generic captions (logo, banner). Contextual re-captioning is planned.
- **Single-language generation**: Answers in German even when source is English (Siemens Annual Report).
- **No conversation memory across sessions**: Each chat is independent.
- **BMW text degradation**: BMW Group's report now has structured chunks and image captions, but 486 noisy text chunks failed embedding and are intentionally flagged in metadata. Use `@BMWGroup` image-focused prompts for the most reliable BMW demo path.

### Things to Try
- Ask about specific numbers ("Wie hoch war der F&E-Anteil von TechVision?")
- Ask a broad question, then follow up with specifics (tests multi-turn)
- Try `@rss` or `@pdf` source filters
- Ask about something NOT in the knowledge base (tests graceful handling)
- Compare two companies' sustainability approaches

---

## Discussion Points (10-15 minutes)

### What's Working
- **Full pipeline**: ingest → embed → retrieve → generate → stream
- **Direct context mode**: 78ms retrieval (was 5s through n8n)
- **bge-m3 migration**: Migrated from nomic-embed-text (768d, English-primary) to bge-m3 (1024d, multilingual). Average quality score: 2.8 → 4.3 (+54%). Siemens German queries went from 1/5 → 5/5. Required re-embedding all 6,088 chunks, HNSW index drop/recreate, and threshold recalibration.
- **OpenDataLoader PDF rollout**: Reprocessed all five PDFs with section-aware chunks, heading paths, tables, and bounding boxes; 1,648/1,648 PDF chunks now carry `meta.bbox`.
- **11 containers**, all self-hosted, no external dependencies
- **Ollama 0.18.0 vision bug found and fixed**: Auto-requested 262K context for vision model (exceeds 128K training limit). Fixed with explicit `num_ctx=8192` — captioning went from 100% failure to 100% success.

### What Needs Improvement Before Real Demo
- [ ] Benchmark larger LLM candidates in order: `qwen3.6:27b`, `qwen3:30b`, `mistral-small3.2:24b-instruct-2506-q4_K_M`, then `qwen2.5:32b-instruct-q4_K_M` as a stable fallback
- [ ] Add `think: false` to Qwen3/Qwen3.6 Ollama chat payloads before benchmarking so thinking latency does not distort results
- [ ] Clean or suppress BMW embedding-error text chunks if BMW text questions become a demo priority
- [ ] Add click-to-source PDF highlighting using stored page + bbox metadata
- [ ] Contextual image re-captioning (use surrounding text for better captions)
- [ ] More German PDFs in the knowledge base
- [ ] OpenWebUI customization (branding, starter prompts already configured)
- [ ] Response time optimization (currently 25-95s depending on query)
- [ ] Multi-language answer control (answer in source language when appropriate)

### Open Questions for Sven
1. Target audience for the real demo — technical or business stakeholders?
2. Should we add more document types (e.g., PowerPoints, Excel)?
3. Which corporate documents should we ingest for the real demo?
4. Is the current answer quality acceptable for the intended audience?
5. Timeline for the real demo — how many weeks to prepare?

---

## Technical Access (for Sven)

| Service | URL | Purpose |
|---------|-----|---------|
| OpenWebUI | https://spark-e010.tail907fce.ts.net:8451 | Chat interface |
| n8n | https://spark-e010.tail907fce.ts.net:8450 | Workflow automation (ingestion) |
| FileBrowser | https://spark-e010.tail907fce.ts.net:8452 | Upload PDFs |
| Adminer | https://spark-e010.tail907fce.ts.net:8453 | Database inspection |
| Assets Gallery | https://spark-e010.tail907fce.ts.net:8454 | Browse extracted images |

**Prerequisite:** Sven must be on the Tailscale network. Test access before Thursday.

---

## Pre-Demo Checklist

- [ ] Run `make demo-start` (stops rss-ingest, pre-warms models)
- [ ] Run `bash scripts/demo_readiness_check.sh` — all checks must PASS
- [ ] Verify OpenWebUI loads and model is selectable
- [ ] Run one warm-up query to load models into GPU
- [ ] Clear chat history in OpenWebUI
- [ ] Have this agenda document open for reference
