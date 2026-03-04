# Image Relevance Improvement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make RSS images in search results relevant to the query by using context-aware captioning, enriched embeddings, and score-based filtering.

**Architecture:** The vision model receives article title + feed name alongside the image, producing topic-anchored captions. Embeddings are computed on `"[feed] title — caption"` to place images in the article's semantic space. The n8n workflow filters images by a score threshold relative to the best text hit.

**Tech Stack:** Python/FastAPI (rss-ingest service), Ollama (qwen2.5vl:7b vision, nomic-embed-text embedding), PostgreSQL/pgvector, n8n workflow JSON

---

### Task 1: Add contextual captioning function to ollama.py

**Files:**
- Modify: `services/rss-ingest/app/ollama.py:12-16` (CAPTION_PROMPTS) and append new function after line 61

**Step 1: Add context-aware prompt templates**

In `services/rss-ingest/app/ollama.py`, add new prompt dict after `CAPTION_PROMPTS` (after line 16):

```python
CONTEXTUAL_CAPTION_PROMPTS = {
    "de": (
        'Dieses Bild stammt aus dem Artikel "{title}" ({feed}).'
        " Beschreibe was das Bild zeigt und wie es zum Artikelthema passt (2-3 Sätze)."
    ),
    "en": (
        'This image is from the article "{title}" ({feed}).'
        " Describe what the image shows and how it relates to the article topic (2-3 sentences)."
    ),
}
```

**Step 2: Add `ollama_caption_image_contextual` function**

Append after the existing `ollama_caption_image` function (after line 60):

```python
def ollama_caption_image_contextual(
    image_bytes: bytes, title: str, feed_name: str, lang: str = "de",
) -> str:
    """Caption an image with article context for better semantic relevance."""
    template = CONTEXTUAL_CAPTION_PROMPTS.get(lang, CONTEXTUAL_CAPTION_PROMPTS["de"])
    prompt = template.format(title=title[:120], feed=feed_name[:30])
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        ],
        "stream": False,
    }
    resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=180)
    resp.raise_for_status()
    return (resp.json().get("message", {}) or {}).get("content", "").strip()
```

**Step 3: Add enriched embedding helper**

Append after the new function:

```python
def enriched_image_embedding_text(caption: str, title: str, feed_name: str) -> str:
    """Build enriched text for image embedding: [feed] title — caption."""
    return f"[{feed_name}] {title} — {caption}"
```

**Step 4: Commit**

```bash
git add services/rss-ingest/app/ollama.py
git commit -m "feat(rss-ingest): add context-aware image captioning and enriched embedding"
```

---

### Task 2: Update ingest_article to use contextual captioning

**Files:**
- Modify: `services/rss-ingest/app/ingest.py:19` (imports) and lines 239-240 (captioning + embedding)

**Step 1: Update import**

In `services/rss-ingest/app/ingest.py` line 19, change:

```python
from app.ollama import _retry, ollama_caption_image, ollama_embeddings
```
to:
```python
from app.ollama import (
    _retry, ollama_caption_image, ollama_caption_image_contextual,
    ollama_embeddings, enriched_image_embedding_text,
)
```

**Step 2: Replace captioning call in ingest_article**

In `ingest_article()`, replace lines 239-240:

```python
                            caption = _retry(lambda ib=img_bytes, la=lang: ollama_caption_image(ib, la))
                            emb = _retry(lambda c=caption: ollama_embeddings(c)) if caption else None
```

with:

```python
                            caption = _retry(
                                lambda ib=img_bytes, t=title, fn=feed_config.name, la=lang:
                                    ollama_caption_image_contextual(ib, t, fn, la)
                            )
                            emb_text = enriched_image_embedding_text(caption, title, feed_config.name)
                            emb = _retry(lambda et=emb_text: ollama_embeddings(et)) if caption else None
```

**Step 3: Replace captioning call in backfill_images_for_doc**

In `backfill_images_for_doc()`, replace lines 338-339:

```python
                        caption = _retry(lambda ib=img_bytes, la=lang: ollama_caption_image(ib, la))
                        emb = _retry(lambda c=caption: ollama_embeddings(c)) if caption else None
```

with:

```python
                        caption = _retry(
                            lambda ib=img_bytes, t=title, fn=feed_config.name, la=lang:
                                ollama_caption_image_contextual(ib, t, fn, la)
                        )
                        emb_text = enriched_image_embedding_text(caption, title, feed_config.name)
                        emb = _retry(lambda et=emb_text: ollama_embeddings(et)) if caption else None
```

**Step 4: Commit**

```bash
git add services/rss-ingest/app/ingest.py
git commit -m "feat(rss-ingest): use contextual captioning and enriched embedding in ingestion"
```

---

### Task 3: Add DB functions for recaption backfill

**Files:**
- Modify: `services/rss-ingest/app/db.py` — append two new functions

**Step 1: Add `get_all_image_chunks` function**

Append to `services/rss-ingest/app/db.py`:

```python
def get_all_image_chunks(cur, limit: int = 0) -> list:
    """Get all RSS image chunks for re-captioning."""
    sql = """
        SELECT id, doc_id, caption, asset_path, meta
        FROM rag_chunks
        WHERE chunk_type = 'image'
          AND asset_path IS NOT NULL
        ORDER BY id
    """
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    cur.execute(sql)
    return [
        {
            "id": row[0],
            "doc_id": row[1],
            "caption": row[2],
            "asset_path": row[3],
            "meta": row[4] if isinstance(row[4], dict) else {},
        }
        for row in cur.fetchall()
    ]
```

**Step 2: Add `update_chunk_caption_embedding` function**

Append to `services/rss-ingest/app/db.py`:

```python
def update_chunk_caption_embedding(cur, chunk_id: int, caption: str, embedding: list):
    """Update an existing chunk's caption and embedding in-place."""
    cur.execute(
        "UPDATE rag_chunks SET caption = %s, embedding = %s WHERE id = %s",
        (caption, embedding, chunk_id),
    )
```

**Step 3: Commit**

```bash
git add services/rss-ingest/app/db.py
git commit -m "feat(rss-ingest): add DB functions for image recaption backfill"
```

---

### Task 4: Add /ingest/recaption-images endpoint

**Files:**
- Modify: `services/rss-ingest/app/ingest.py` — add `recaption_image_chunk` function at end
- Modify: `services/rss-ingest/app/main.py` — add endpoint after `/ingest/backfill-images`

**Step 1: Add recaption function to ingest.py**

Append to `services/rss-ingest/app/ingest.py`:

```python
def recaption_image_chunk(pool, chunk: dict, lang: str = "de") -> dict:
    """
    Re-caption a single image chunk using contextual prompt and update in-place.
    Reads saved image from disk (no re-download).
    """
    from app.db import update_chunk_caption_embedding

    asset_path = os.path.join(ASSETS_DIR, chunk["asset_path"])
    if not os.path.exists(asset_path):
        return {"status": "skipped", "reason": "asset file missing"}

    with open(asset_path, "rb") as f:
        img_bytes = f.read()

    if len(img_bytes) < MIN_IMAGE_BYTES:
        return {"status": "skipped", "reason": "image too small"}

    meta = chunk.get("meta", {})
    title = meta.get("title", "")
    feed_name = meta.get("feed_name", "RSS")

    caption = _retry(
        lambda ib=img_bytes, t=title, fn=feed_name, la=lang:
            ollama_caption_image_contextual(ib, t, fn, la)
    )
    emb_text = enriched_image_embedding_text(caption, title, feed_name)
    emb = _retry(lambda et=emb_text: ollama_embeddings(et)) if caption else None

    with pool.connection() as conn:
        with conn.cursor() as cur:
            update_chunk_caption_embedding(cur, chunk["id"], caption, emb)
        conn.commit()

    return {"status": "ok", "caption": caption[:80]}
```

**Step 2: Add endpoint to main.py**

In `services/rss-ingest/app/main.py`, add after the `/ingest/backfill-images` endpoint (after line 153):

```python
@app.post("/ingest/recaption-images")
def recaption_images(limit: int = 0, lang: str = "de"):
    """Re-caption all image chunks with context-aware prompts and re-embed."""
    from app.db import get_all_image_chunks
    from app.ingest import recaption_image_chunk

    try:
        with ingestion_lock():
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    chunks = get_all_image_chunks(cur, limit=limit)

            results = {
                "total_chunks": len(chunks),
                "recaptioned": 0,
                "skipped": 0,
                "errors": 0,
            }
            for i, chunk in enumerate(chunks):
                try:
                    r = recaption_image_chunk(pool, chunk, lang)
                    if r.get("status") == "ok":
                        results["recaptioned"] += 1
                    else:
                        results["skipped"] += 1
                except Exception as e:
                    logger.warning(
                        "Recaption error for chunk %s: %s", chunk["id"], e
                    )
                    results["errors"] += 1

                if (i + 1) % 50 == 0:
                    logger.info(
                        "Recaption progress: %d/%d done", i + 1, len(chunks)
                    )

            return results
    except RuntimeError:
        logger.info("Lock busy, returning busy status")
        return {"status": "busy", "reason": "ingestion_in_progress"}
```

**Step 3: Commit**

```bash
git add services/rss-ingest/app/ingest.py services/rss-ingest/app/main.py
git commit -m "feat(rss-ingest): add /ingest/recaption-images endpoint for contextual re-captioning"
```

---

### Task 5: Update n8n workflow with score-based image filtering

**Files:**
- Modify: `n8n/workflows/01_chat_brain.json` — update Build Context node jsCode (line 68)

**Step 1: Update the Build Context JavaScript**

In `n8n/workflows/01_chat_brain.json`, replace the `jsCode` value in the Build Context node with updated image filtering logic. The key change is replacing the `showImage` function:

Old logic (around middle of jsCode):
```javascript
const showImage = (h) => {
  if (h.chunk_type !== 'image' || !h.asset_path) return false;
  if (imageDominant) return true;
  return textDocIds.has(h.doc_id);
};
```

New logic:
```javascript
// Score-based image filtering: only show images scoring >= 60% of best text hit
const bestTextScore = Math.max(...textHits.map(h => h.score), 0);
const imageScoreThreshold = bestTextScore * 0.6;

const showImage = (h) => {
  if (h.chunk_type !== 'image' || !h.asset_path) return false;
  if (h.score < imageScoreThreshold) return false;
  if (imageDominant) return true;
  return textDocIds.has(h.doc_id);
};
```

The full updated jsCode for the Build Context node (replace the entire `jsCode` string value at line 68):

```javascript
const hits = ($('Vector Search (Postgres)').all() || []).map(it => it.json);
const base = $env.PUBLIC_ASSETS_BASE_URL || '';

// Determine dominant result type by majority vote
const textHits = hits.filter(h => h.chunk_type === 'text');
const imageHits = hits.filter(h => h.chunk_type === 'image');
const imageDominant = imageHits.length > textHits.length;

// Collect doc_ids from text hits for cross-referencing
const textDocIds = new Set(textHits.map(h => h.doc_id));

// Score-based image filtering: only show images scoring >= 60% of best text hit
const bestTextScore = Math.max(...textHits.map(h => h.score), 0);
const imageScoreThreshold = bestTextScore * 0.6;

// Image inclusion rules:
// 1. Must pass score threshold (>= 60% of best text score)
// 2. If images are the majority → show all passing image hits
// 3. If text is the majority → only show passing images from same documents
const showImage = (h) => {
  if (h.chunk_type !== 'image' || !h.asset_path) return false;
  if (h.score < imageScoreThreshold) return false;
  if (imageDominant) return true;
  return textDocIds.has(h.doc_id);
};

const images = hits.filter(showImage).map(h => `${base}/${h.asset_path}`);

// Structured image objects with caption for rag-gateway
const imageObjects = hits.filter(h => h.chunk_type === 'image' && showImage(h) && h.asset_path)
  .map(h => ({ url: `${base}/${h.asset_path}`, caption: h.caption || 'Bild' }));

const ctxLines = hits.map(h => {
  const meta = h.meta || {};
  const isRss = meta.content_type === 'rss_article';
  if (h.chunk_type === 'image') {
    if (!showImage(h)) return null;
    const url = h.asset_path ? `${base}/${h.asset_path}` : '';
    const src = isRss ? `Bild (${meta.feed_name || 'RSS'})` : `Bild (Seite ${h.page})`;
    return `${src}: ${h.caption || ''} ${url}`.trim();
  }
  if (isRss) {
    return `Quelle ${meta.feed_name || 'RSS'} - "${meta.title || ''}": ${h.content_text || ''}`;
  }
  return `Text (Seite ${h.page}): ${h.content_text || ''}`;
}).filter(l => l !== null);

// Sources with markdown links for RSS items
const sources = hits.filter(h => {
  if (h.chunk_type === 'image' && !showImage(h)) return false;
  return true;
}).map(h => {
  const meta = h.meta || {};
  if (meta.content_type === 'rss_article') {
    const title = (meta.title || '').substring(0, 60);
    if (meta.url) return `[${meta.feed_name || 'RSS'}: ${title}](${meta.url})`;
    return `${meta.feed_name || 'RSS'}: ${title}`;
  }
  return `Seite ${h.page} (${h.chunk_type})`;
}).slice(0, 8);

const query = $('Extract Query').first().json.query;
const context = ctxLines.join('\n\n');
const chatRequestBody = {
  model: $env.OLLAMA_TEXT_MODEL || 'llama3.1:8b',
  stream: false,
  options: { num_predict: 400 },
  messages: [
    {role: 'system', content: 'Du bist ein intelligenter Multimodal-Assistent. Antworte auf Deutsch und beziehe dich auf den bereitgestellten Kontext. Wenn der Kontext Bildbeschreibungen (Captions) enthält, weise den Nutzer aktiv darauf hin, was auf den Bildern zu sehen ist. Zitiere immer deine Quellen (z.B. \'Laut Seite 4...\' oder \'Wie im Bild auf Seite 2 zu sehen ist...\').'},
    {role: 'user', content: 'Frage: ' + query + '\n\nKontext aus Dokumenten und Nachrichten:\n' + context + '\n\nAntworte kurz, korrekt und mit Quellenhinweisen.'}
  ]
};
return [{ json: { query, context, images, imageObjects, sources, chatRequestBody } }];
```

**Step 2: Commit**

```bash
git add n8n/workflows/01_chat_brain.json
git commit -m "feat(n8n): add score-based image filtering to Build Context node"
```

---

### Task 6: Rebuild, deploy, and run recaption backfill

**Step 1: Rebuild rss-ingest Docker image**

```bash
cd /srv/projects/ammer/mmrag-n8n-demo-v2
docker compose build rss-ingest
```

Expected: successful build

**Step 2: Recreate rss-ingest container** (ASK USER FIRST)

```bash
docker compose up -d rss-ingest
```

Expected: container recreated with new image

**Step 3: Verify service is healthy**

```bash
curl -s http://127.0.0.1:56155/health/ready | python3 -m json.tool
```

Wait — rss-ingest doesn't have a host port. Use docker exec:

```bash
docker exec ammer_mmragv2_rss-ingest curl -s http://localhost:8000/health/ready
```

Expected: `{"ok": true, "checks": {"db": "ok", "ollama": "ok"}}`

**Step 4: Test recaption endpoint with limit=2**

```bash
docker exec ammer_mmragv2_rss-ingest curl -s -X POST 'http://localhost:8000/ingest/recaption-images?limit=2&lang=de'
```

Expected: `{"total_chunks": 2, "recaptioned": 2, "skipped": 0, "errors": 0}`

Verify new captions include article context:

```sql
SELECT caption FROM rag_chunks WHERE chunk_type='image' ORDER BY id LIMIT 2;
```

The captions should mention the article topic, not just describe visual elements.

**Step 5: Run full recaption backfill** (ASK USER FIRST — ~2-3 hours GPU time)

```bash
docker exec ammer_mmragv2_rss-ingest curl -s -X POST 'http://localhost:8000/ingest/recaption-images?lang=de'
```

Monitor progress in container logs:

```bash
docker logs -f ammer_mmragv2_rss-ingest
```

**Step 6: Re-import n8n workflow** (MANUAL — ASK USER)

Import the updated `n8n/workflows/01_chat_brain.json` into n8n via the UI or API:
1. Open n8n at `http://127.0.0.1:56150`
2. Open the "MMRAG Chat Brain (Webhook)" workflow
3. Replace the Build Context node's JavaScript with the updated code
4. Save and activate

**Step 7: Test end-to-end**

Query the system with a topic that has related images (e.g., "Was passiert mit KI in der Tech-Branche?") and verify:
- Images shown are relevant to the AI/tech topic
- Irrelevant stock photos are filtered out
- Text answers still work correctly

**Step 8: Commit any remaining changes**

```bash
git add -A
git commit -m "feat: deploy contextual image captioning with score-based filtering"
```
