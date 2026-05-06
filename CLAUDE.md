# CLAUDE.md — mmrag-n8n-demo-v2 Project Context

## Who and Where

- You are operating as Linux user `ammer` on a shared NVIDIA DGX Spark.
- Other users and services run on this machine. **Do not touch anything outside this project.**
- Project root: `/srv/projects/ammer/mmrag-n8n-demo-v2`
- All work must happen inside this root. No files elsewhere.

## Critical Safety Rules (Never Violate)

- **DO NOT** stop, modify, restart, or inspect containers/stacks/volumes that don't belong to this project.
- **DO NOT** bind any port to `0.0.0.0`. All host port bindings must use `127.0.0.1` only.
- **DO NOT** expose anything publicly. Tailscale Serve only (not Funnel).
- **DO NOT** install system packages with `apt` or modify anything outside the project directory.
- **DO NOT** run `docker system prune`, `docker volume prune`, or any broad cleanup commands.
- **ASK before executing** any command that changes system state (docker compose up, docker compose down, tailscale serve, chown, etc.). Show me the command and wait for confirmation.
- If something fails unexpectedly, **STOP and report** rather than attempting creative fixes.

## Project Identity (Isolation)

- Docker Compose project name: `ammer-mmragv2`
- All container names start with: `ammer_mmragv2_`
- Named volumes start with: `ammer-mmragv2_`
- Host port range: `56150–56157` (localhost only)
- These names and ports are frozen. Do not change them.

## Frozen Port Map

| Port  | Service      | Notes                    |
|-------|-------------|--------------------------|
| 56150 | n8n         | -> container port 5678   |
| 56151 | OpenWebUI   | -> container port 8080   |
| 56152 | FileBrowser | -> container port 80     |
| 56153 | Adminer     | -> container port 8080   |
| 56154 | Postgres    | -> container port 5432   |
| 56157 | Assets      | -> container port 80     |

No host port binding for: ollama, pdf-ingest, rag-gateway (internal only).

## GPU Rules

- Only the `ollama` container gets GPU access (`gpus: all` in compose).
- Concurrency: `OLLAMA_NUM_PARALLEL=3`, `OLLAMA_MAX_LOADED_MODELS=3` (all 3 production models stay loaded, ~28 GB total: `gemma4:26b` ≈ 21 GB, `qwen2.5vl:7b` ≈ 6 GB, `bge-m3` ≈ 1.3 GB).
- Do not run any GPU-heavy commands outside the ollama container.

## DGX Spark Server Guidelines (from admin)

- Use Docker without sudo for everyday work. Sudo only for system packages or service management.
- All Docker projects live under `/srv/projects/ammer`.
- Each stack must have a unique project name — never reuse existing container/network/volume names.
- Use the 55xxx–56xxx port range. Never bind default ports (5432, 8080, etc.) directly.
- Remove unused containers/images when done. Don't leave experiments running.

## Implementation Approach

- Follow the frozen specification file (mmrag-spec-v2.4.md) exactly. Do not improvise file contents.
- Work in phases: Foundation → Services → Logic → Launch.
- After completing each phase, run the corresponding validation gate before moving on.
- Document manual steps in MANUAL_STEPS.md. Flag anything that can't be automated.

## Technical Gotchas (Hard-Won Lessons)

### pgvector: VECTOR_DISTANCE_THRESHOLD is cosine DISTANCE, not similarity
The SQL `embedding <=> emb < threshold` compares cosine **distance** (0=identical, 2=opposite).
`score = 1 - distance`. So `threshold=0.5` means `score > 0.5`, and `threshold=0.6` means `score > 0.4`.
**Lowering the threshold TIGHTENS the filter (fewer results). To be more permissive, RAISE it.**

### pgvector: Image score thresholds must exceed SQL cutoff
Any `image_score_min <= (1 - VECTOR_DISTANCE_THRESHOLD)` is silently useless — the SQL
pre-filter already guarantees all returned rows score above that level. For example, with
`VECTOR_DISTANCE_THRESHOLD=0.6` (score > 0.4), setting `image_score_min=0.40` filters nothing.
Always verify: `image_score_min > (1 - VECTOR_DISTANCE_THRESHOLD)`.

### pgvector: HNSW indexes are dimension-bound
`ALTER TABLE ... ALTER COLUMN embedding TYPE vector(N)` will fail if an HNSW index exists
on that column. Must `DROP INDEX` first, then ALTER, then recreate. For bulk re-embedding,
defer index creation until after all UPDATEs complete (one bulk build is much faster than
incremental rebuilds during 6,000 UPDATEs).

### psycopg3: Server-side cursors are transaction-bound
Calling `conn.commit()` inside a loop that reads from a named (server-side) cursor destroys
the cursor — `InvalidCursorName` error. For small datasets (<10k rows), fetch all into memory
first. For large datasets, use a separate connection for reads vs writes.

### Postgres auth in supabase/postgres container
`rag_user` cannot connect via Unix socket (peer auth fails). Always use `-h 127.0.0.1` for
TCP connection: `psql -U rag_user -d rag -h 127.0.0.1`

### Bash arithmetic with set -e
`((VAR++))` exits the script when VAR=0 (evaluates falsy). Use `VAR=$((VAR + 1))` instead.

## Key File Locations (Reference)

- Frozen spec: `/srv/projects/ammer/mmrag-spec-v2.4.md`
- DGX guidelines: `/srv/projects/ammer/DGX_Docker_Guidelines_for_Ammer_EN.pdf`
- Environment config: `.env` (created from `.env.example`, never committed)
- SQL init scripts: `db/init/001_init.sql`, `db/init/010_rag_schema.sql`
- Python services: `services/pdf-ingest/`, `services/rag-gateway/`
- n8n workflows (for manual import): `n8n/workflows/`
- Shell scripts: `scripts/` and `reset_demo.sh`

## Current Project Truth (Post-Spec)

The frozen spec is the baseline, but the running demo intentionally diverges in several places. Treat these as current project truth unless the code and `MANUAL_STEPS.md` prove otherwise.

### Current Architecture

- Deployment is complete and demo-hardened. The expected stack is the `ammer-mmragv2` Docker Compose project on localhost ports `56150-56157`.
- `rag-gateway` runs in `CONTEXT_MODE=direct`: it embeds queries, searches Postgres/pgvector, builds context, and streams Ollama output as OpenAI-compatible SSE.
- n8n Chat Brain is context-only now: Webhook -> Extract Query -> Embed -> Vector Literal -> Vector Search -> Build Context. Do not move LLM generation back into n8n.
- Demo readiness lives at `scripts/demo_readiness_check.sh`. Run it before demos or after changes that affect containers, models, webhooks, context retrieval, streaming, demo mode, Tailscale Serve, or tailnet URLs.

### Retrieval And Embeddings

- Embeddings use `bge-m3` with 1024-dimensional vectors. `nomic-embed-text` is obsolete for this project and should not be reintroduced.
- `VECTOR_DISTANCE_THRESHOLD=0.6`. This is cosine distance, so the SQL pre-filter keeps rows with score `1 - distance > 0.4`.
- Image relevance thresholds are deliberately above that SQL floor: `image_score_min=0.45` for image-focused queries and `0.55` for non-image queries.
- Direct retrieval reserves slots for both text and images: image queries use 4 text + 4 image hits; other queries use 6 text + 2 image hits.
- Query prefixes matter: `@rss` restricts to RSS docs, `@pdf` restricts to PDFs, and any other `@token` is treated as a filename filter.
- Follow-up rewriting is deictic/anaphoric: short follow-ups or phrases such as `dabei`, `dazu`, `davon`, `hierzu`, `diesem` are rewritten with the previous user query.
- PDF retrieval is improved by OpenDataLoader structure-aware chunks, but source filters are still preferred for demos because the RSS corpus is much larger. For PDF-focused prompts, use filename filters such as `@Nachhaltigkeit`, `@BMWGroup`, `@Siemens`, or `@TechVision`.

### PDF Ingestion

- PDF text/layout extraction uses `opendataloader-pdf==2.4.1` local mode with OpenJDK 17 inside `pdf-ingest`.
- `rag_chunks.meta` now carries PDF structure metadata: `bbox`, `bbox_units`, `bbox_order`, `page_size`, `heading_path`, `element_ids`, `element_type`, `split_strategy`, and `extractor`.
- Chunking is section-aware and page-boundary-safe: headings and paragraphs are grouped under heading breadcrumbs, tables are preserved as table chunks, and every chunk keeps a meaningful `page`.
- PyMuPDF remains for image post-processing, image dimension checks, and fallback ingestion.
- Embeddings remain `bge-m3` (1024d); PDF image captioning remains `qwen2.5vl:7b`.
- All PDFs in `data/processed/` were reprocessed on May 5, 2026. Snapshot: `data/demo_snapshot_pre_opendataloader_20260505_172446.sql`; rollback asset quarantine: `data/assets/_pre_opendataloader_20260505_172446/`.
- Current PDF corpus after reprocess: 5 PDFs, 1,648 chunks, 1,648 chunks with `meta.bbox`. BMW Group has a controlled degradation: 486 noisy text chunks are stored without embeddings and flagged with `meta.embedding_error = "ollama_embed_failed"`.

### RSS And Images

- RSS ingestion uses Scrapling first with BeautifulSoup fallback.
- Enabled RSS sources are 7 feeds: `spiegel`, `tagesschau`, `heise`, `spektrum`, `zdf`, `dw`, and `faz`.
- RSS image handling uses a 5-layer dedup pipeline: URL normalization, within-article visual dedup, global visual dedup, SHA-256, and file existence.
- Shared RSS images live under `data/assets/rss/_shared/{sha256[:16]}.{ext}`; avoid reintroducing per-article duplicate image directories.
- The `/ingest/backfill-images` endpoint exists for retroactive RSS image captioning. It filters SVGs, tracking pixels, and images under 5 KB.

### Important Deviations From Spec

- D14: LLM generation moved from n8n to `rag-gateway` for true streaming.
- D15: assets nginx uses custom `nginx/assets.conf` with JSON autoindex and gallery UI.
- D16: `OLLAMA_MAX_LOADED_MODELS=3` keeps the text, vision, and embedding models loaded.
- D17: RSS image backfill endpoint added.
- D18/D18a/D18b: PDF ingestion is parallel and non-blocking, with file watcher handoff and batch embeddings.
- D19: Control Center exists as the project UI on localhost port `56156`.
- D20: Direct dual retrieval reserves text/image result slots.
- D21: Follow-up rewriting uses deictic/anaphoric detection.
- D22: RSS source set was reduced to the current 7 feeds.
- D23: `bge-m3` replaced `nomic-embed-text`; vector schema is 1024d.
- D24: PDF extraction switched from PyMuPDF flat text chunks to OpenDataLoader structured layout extraction with bounding boxes and heading paths. Reprocess snapshot/quarantine were created before regenerating all PDF chunks.

### Local Agent Config

- `.mcp.json`, `.claude/`, and `.codex/` are gitignored because they contain local agent wiring and credentials. A fresh clone will not be fully MCP-ready without recreating those local files.
- `AGENTS.md` is a symlink to this file, so edits here are shared by Claude Code and Codex.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
