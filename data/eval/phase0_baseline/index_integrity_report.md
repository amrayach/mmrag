# Phase 0.3 — RAG index integrity report

- **Captured at:** 2026-05-06T14:17:57+00:00
- **Connection:** TCP host=127.0.0.1

## Totals

- **Documents:** 4,098
- **Chunks:** 15,845
- **Chunks with NULL embedding:** 481 (3.04% — production silently excludes these via `WHERE embedding IS NOT NULL`)
- **Chunks with `meta.embedding_error`:** see breakdown below

## Chunks by chunk_type

| chunk_type | n |
|---|---|
| text | 14736 |
| image | 1109 |

## Chunks by meta.source

| source | n |
|---|---|
| rss_article | 13182 |
| pdf_text | 1554 |
| rss_image | 1015 |
| pdf_image | 94 |

## Chunks tagged with meta.embedding_error

| embedding_error | n |
|---|---|
| ValueError: empty or gibberish embedding input after ingest cleanup | 474 |

## Cohort: PDF text chunks, content_text non-empty, embedding NULL

- **Count:** 474

## Cohort: image chunks with asset_path but empty caption

- **Count:** 5

## Content-length cohorts

- **Very short (`len(content_text) < 50`):** 207
- **Very long  (`len(content_text) > 8000`):** 0 (likely contributors to ollama_embed_failed)

### Very-long text chunks per filename

_(no rows)_

### Very-short text chunks per filename

| filename | n |
|---|---|
| BMWGroup_Bericht2023.pdf | 192 |
| Siemens-Annual-Report-2024.pdf | 14 |
| https://www.zdfheute.de/politik/ausland/libanon-angriff-un-blauhelmsoldat-getoetet-nahost-100.html | 1 |

## Metadata coverage

- **chunks with `meta.heading_path`:** 1,648 (10.4%)
- **chunks with `meta.element_type`:** 1,648 (10.4%)

## Top 10 filenames by missing-embedding count

| filename | n_missing |
|---|---|
| BMWGroup_Bericht2023.pdf | 476 |
| Nachhaltigkeit-bei-Siemens.pdf | 4 |
| Siemens-Annual-Report-2024.pdf | 1 |

## Production-visibility gap

rag-gateway's vector search uses `WHERE embedding IS NOT NULL` so any chunk with a NULL embedding is silently excluded from retrieval. The table above reports those by filename, and the count is mirrored here:
- **Chunks excluded from retrieval (NULL embedding):** 481
