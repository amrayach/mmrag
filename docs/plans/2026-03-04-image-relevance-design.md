# Image Relevance Improvement Design

**Date:** 2026-03-04
**Status:** Approved

## Problem

When querying RSS-ingested data, images shown alongside answers are often irrelevant to the query. Root cause: image chunks are embedded using generic visual captions (e.g., "a man at a computer") rather than article-contextualized descriptions. Vector search finds relevant text chunks, and images tag along via `doc_id` matching — but the images themselves don't semantically relate to the query.

## Solution: Context-Aware Re-captioning + Enriched Embedding + Relevance Threshold

### 1. Contextual Captioning

Replace the generic vision prompt with one that includes article context:

**Old:** `"Beschreibe dieses Bild kurz und präzise auf Deutsch (1-2 Sätze)."`

**New:** `"Dieses Bild stammt aus dem Artikel '{title}' ({feed_name}). Beschreibe was das Bild zeigt und wie es zum Artikelthema passt (2-3 Sätze)."`

**File:** `services/rss-ingest/app/ollama.py` — add `ollama_caption_image_contextual()`.

### 2. Enriched Embedding

Embed `f"[{feed_name}] {title} — {caption}"` instead of just the caption. This anchors image embeddings in the article's topic space.

**File:** `services/rss-ingest/app/ingest.py` — modify embedding input for image chunks.

### 3. Relevance Threshold in n8n

Only show an image if its cosine similarity score >= 60% of the best text hit's score.

```javascript
const bestTextScore = Math.max(...textHits.map(h => h.score), 0);
const imageScoreThreshold = bestTextScore * 0.6;
const showImage = (h) => {
  if (h.chunk_type !== 'image' || !h.asset_path) return false;
  if (h.score < imageScoreThreshold) return false;
  if (imageDominant) return true;
  return textDocIds.has(h.doc_id);
};
```

**File:** `n8n/workflows/01_chat_brain.json` — Build Context node.

### 4. Backfill Endpoint

New `/ingest/recaption-images` endpoint to reprocess all 719 existing image chunks:
- Reads saved image files from disk (no re-download needed)
- Re-captions with contextual prompt using article title from chunk metadata
- Re-embeds with enriched text
- Updates chunks in-place

**Files:** `services/rss-ingest/app/db.py`, `services/rss-ingest/app/ingest.py`, `services/rss-ingest/app/main.py`

### 5. Forward-Compatible

All future ingestion uses contextual captioning + enriched embedding automatically.

## Files Changed

| File | Change |
|------|--------|
| `services/rss-ingest/app/ollama.py` | Add contextual caption function |
| `services/rss-ingest/app/ingest.py` | Use contextual captioning + enriched embedding |
| `services/rss-ingest/app/db.py` | Add `update_chunk_caption_embedding()`, `get_all_image_chunks()` |
| `services/rss-ingest/app/main.py` | Add `/ingest/recaption-images` endpoint |
| `n8n/workflows/01_chat_brain.json` | Add score-based image filtering |
| `services/rss-ingest/Dockerfile` | Rebuild needed |

## Estimated GPU Time

~2-3 hours for re-captioning 719 images through qwen2.5vl:7b.
