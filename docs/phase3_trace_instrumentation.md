# Phase 3.0 — Retrieval-trace evidence instrumentation

Stage 3.0 extends the per-request retrieval trace with diagnostic-only
structural and document-level metadata, and adds a standalone inspector
script that turns the JSONL records into a Markdown + JSON report. No
retrieval behavior, ranking, candidate selection, image guard, or context
packing changed.

## What was added

### New trace fields on every candidate and final-context chunk

All fields are pulled from ``rag_chunks.meta`` JSONB or from ``rag_docs``
via the JOIN that already produced ``doc_filename``. Each list — text
candidates, image candidates, and final-context entries — carries them.

| Field | Source | Notes |
|---|---|---|
| `heading_path` | `meta.heading_path` | Breadcrumb string; populated on ~1,648 OpenDataLoader PDF chunks |
| `element_type` | `meta.element_type` | One of `paragraph`, `table`, `heading`, etc. |
| `split_strategy` | `meta.split_strategy` | Chunking strategy that produced the chunk |
| `bbox_present` | `meta.bbox is not null` | Boolean — PDF coordinate availability |
| `page_size_present` | `meta.page_size is not null` | Boolean — page dimensions availability |
| `meta_source` | `meta.source` | `pdf_text` / `pdf_image` / `rss_article` / `rss_image` |
| `content_type` | `meta.content_type` | RSS chunks carry `rss_article` here |
| `content_length` | `len(content_text)` | Text candidates only |
| `caption_length` | `len(caption)` | Image candidates only |
| `is_pdf` | derived | filename does not start with `http` and ends in `.pdf` |
| `is_rss` | derived | filename starts with `http` |
| `meta_embedding_error` | `meta.embedding_error` | Backfill-recovery audit (e.g. `ollama_embed_failed`) |
| `doc_pages` | `rag_docs.pages` | Used by `back_matter_like` |
| `doc_lang` | `rag_docs.lang` | Document language |

Image-candidate records also surface `heading_path` and `element_type`
for parity with text candidates.

### Diagnostic flags

| Flag | Rule | Reason emitted |
|---|---|---|
| `front_matter_like` | `page <= 10` OR `heading_path` contains `inhaltsverzeichnis` | `page_in_first_10` / `heading_path_contains_toc` |
| `back_matter_like` | `page >= doc_pages - 10` when `doc_pages` known; falls back to `page >= 320` only when `doc_pages` is NULL; OR `heading_path` contains `stichwortverzeichnis` / `impressum` / `index` | `page_in_last_10` / `page_fallback_gte_320` / `heading_path_contains_toc` |
| `front_or_back_matter_reason` | List of all rules that fired | (see above) |

The flags are **diagnostic only**. They do not influence retrieval
ranking, candidate selection, the image-score-min filter, the cross-doc-id
guard, image-score boosting, context packing, or any other production
decision. They exist solely to be read back by the inspector.

### Trace shapes the enrichment applies to

Stage 3.0 only writes the dense-retrieval shape. The serialization helpers
were written generically so the same enrichment also lands on future
hybrid-retrieval shapes:

- `candidates_text_before_selection` (dense — current)
- `candidates_image_before_selection` (dense — current)
- `final_context_chunks` (current)
- `candidates_text_dense_before_fusion` (hybrid — future)
- `candidates_text_lexical_before_fusion` (hybrid — future)
- `candidates_text_after_fusion` (hybrid — future)

When a hybrid trace is detected, the inspector additionally surfaces
`dense_rank`, `lexical_rank`, `rrf_score`, and `lexical_query_mode`
columns for each candidate.

## Why diagnostic-only

Mixing observation and behavior is exactly how Stage 2B hybrid V1 went
wrong: rule-driven ranking that looked sensible in the trace did not
translate to better answer quality on p04. Stage 3.0 separates these
concerns rigidly. Future ranking experiments are free to **read** these
diagnostics as evidence in their post-mortems, but the decision to
prefer or penalize a chunk has to live behind its own gate. That gate
will be wired explicitly in Stage 3.1+ once we know which signals
actually move recall@k for the gold chunks of p04.

In short: this stage closes an instrumentation gap. It does not start
the experiment that the next stage will run.

## How to use the inspector

```bash
# Latest record in the trace file
python scripts/inspect_retrieval_trace.py \
    --trace data/rag-traces/retrieval.jsonl

# Targeted at one prompt-id with gold chunk analysis
python scripts/inspect_retrieval_trace.py \
    --trace data/rag-traces/retrieval.jsonl \
    --gold data/eval/gold_chunks.phase0.json \
    --prompt-id p04

# Inspect a per-run capture from scripts/eval_run.py
python scripts/inspect_retrieval_trace.py \
    --trace data/eval/runs/<run-dir>/traces/retrieval.jsonl \
    --gold data/eval/gold_chunks.phase0.json \
    --prompt-id p04
```

Output lands under `data/eval/trace_inspections/` and is keyed by UTC
timestamp + prompt-id, so multiple inspections do not collide:

```
data/eval/trace_inspections/20260511T180000Z_p04_inspection.md
data/eval/trace_inspections/20260511T180000Z_p04_inspection.json
```

The directory is gitignored (`.gitkeep` is kept). Reports are pure
artifacts; nothing else writes there.

### Inspector report sections

1. **Trace summary** — file path, record count, retrieval mode, selected
   timestamp + req_id, model, raw / rewritten query.
2. **Top 20 candidates (text)** — rank, chunk_id, page, filename, score,
   heading_path, element_type, front_matter_like flag, content_length.
   In hybrid traces the table also includes dense_rank, lexical_rank,
   rrf_score, and lexical_query_mode.
3. **Final context** — chunks that reached the LLM prompt, with their
   structural metadata and diagnostic flags.
4. **Front/back matter analysis** — counts of front_matter_like and
   back_matter_like chunks at top-6, top-10, top-20, and final-context
   slices.
5. **Gold chunk analysis** *(only when `--gold` and `--prompt-id` map to
   a populated gold entry)* — per gold-chunk presence, rank, final
   position, plus recall@1/5/10/20 and MRR.
6. **Structural-metadata coverage** — share of candidates that carry
   heading_path / element_type / bbox / page_size, and the share that
   are fully missing structural metadata (typically RSS chunks).

## How this unblocks future work

- **Reranker experiments** (Stage 3.1A or similar) need `element_type`,
  `heading_path`, and `content_length` as feature inputs. Stage 3.0
  guarantees they reach the trace whenever the chunk has them in meta.
- **Metadata-aware penalties** (Stage 3.1B) need `front_matter_like` and
  `back_matter_like` flags surfaced at every candidate position. The
  inspector lets us count exactly how often a weak chunk reached top-k
  in real traffic before deciding on a penalty weight.
- **Metadata prefixing** (Stage 3.1C) needs heading_path coverage stats
  and `split_strategy` per chunk to scope which document subset will get
  reprocessed.
- **Hybrid analysis** (rerun of Stage 2B or successor) — the serializer
  is shape-agnostic and the inspector already understands hybrid
  candidate lists, so future hybrid traces inherit the structural
  fields and RRF columns without further plumbing.

## Known limitations

- **heading_path coverage is roughly 10% of total chunks.** ~1,648 PDF
  chunks have it (the OpenDataLoader cohort). RSS chunks and pre-ODL
  PDF chunks do not, so retrieval that picks RSS-heavy candidate lists
  will see most cells empty.
- **bbox / page_size only on ODL-extracted PDFs.** Same cohort as above.
- **TOC heuristic is a substring match.** Body-text mentions of
  `Inhaltsverzeichnis`, `Index`, `Stichwortverzeichnis`, or `Impressum`
  will fire the heading_path_contains_toc reason without being TOC
  content. Treat the reason as evidence to inspect, not as proof.
- **`page >= 320` fallback is a heuristic** for documents whose
  `rag_docs.pages` is NULL. Once Phase 1 backfills page counts for the
  RSS-style rows, this branch should fall idle. It will never override
  the doc_pages-based rule when that rule is available.
- **Inspector is single-record per report.** When `--prompt-id` matches
  multiple records, the inspector picks the most recent timestamp and
  notes the rest in the summary's `matched_count`.
