# Multimodal Generation (Phase 1 Hybrid) — Design Document

**Date:** 2026-05-13
**Status:** Draft — pending Phase 0 verification
**Goal:** Have `gemma4:26b` reason over actual image pixels at answer time, while leaving retrieval caption-based. Track 0 of a three-track hybrid roadmap. No re-ingestion, no schema change, no retrieval path change.

---

## Context: Why This Plan Exists Now

Two facts that were never written down together until this design:

1. **The original caption-only rationale no longer holds.** The February note to Sven framed the system as *"caption-based multi-modal RAG, not native"*, with the explicit justification that ≤7B vision models put too much pressure on GPU memory at generation time. That constraint was real then. It is not real now.
2. **The May 2026 model upgrade quietly removed the constraint.** The A/B harness promoted `gemma4:26b` post-ODL integration (Ollama pinned to `0.23.1` for Gemma 4 manifest support). Gemma 4 is natively multimodal — Ollama publishes `text+image` capability on all variants from `e2b` (7.2 GB) through `31b` (20 GB), with configurable visual token budgets `{70, 140, 280, 560, 1120}` per image and 256K context on `26b`/`31b`.

The architectural premise that drove the caption-only choice — that we couldn't afford a multimodal answering model — no longer applies at generation time. This spec leverages that opening.

### Three-track hybrid framing

This spec is **Track 0** of a three-track roadmap. The other two tracks exist on paper and are explicitly out of scope here:

| Track | What it changes | Effort | Addresses |
|---|---|---|---|
| **0 — this spec** | rag-gateway feeds image bytes to `gemma4:26b` at answer time; retrieval unchanged | ~3 days | LLM reasons over pixels, not captioner-paraphrase |
| 1 — GLM-OCR (deferred) | Add OCR/structure extractor as ODL fallback for scanned/poorly-tagged PDFs | ~1 week | Extraction quality on hard PDFs. Does **not** move retrieval-side eval. |
| 2 — Visual embedder (v3) | `rag_pages` table, multimodal embedder (ColPali / BGE-VL / JinaCLIP-v2), retrieval fusion | Weeks | Retrieval-side multimodality. The real v3. |

Track 0 stacks independently of Tracks 1 and 2 and is the cheapest visible upgrade available. None of the other tracks are blocked by it, and it does not block them.

---

## Problem

`rag-gateway` builds a single user message that combines retrieved text chunks **and a textual paraphrase of every retrieved image**, then sends that text-only message to Ollama. The currently running answering model (`gemma4:26b`) never sees image bytes — only the captioner's description of them.

The exact line where image bytes turn into text, today, is `services/rag-gateway/app/context.py:312`:

```python
ctx_lines.append(f"{src}: {h.get('caption') or ''} {url}".strip())
```

This produces context lines like:

> `Bild (Seite 4): Ein Balkendiagramm zeigt CO₂-Emissionen pro Geschäftsbereich https://.../doc_p4_i1.jpeg`

Downstream consequences:

- Answer quality is bounded by **caption quality**, not by what the model could actually read from the chart/diagram/photo.
- Numerical content, axis labels, legend entries, embedded text, and visual relationships present in the image but absent from the 1-2 sentence caption are unrecoverable at answer time.
- The system prompt at `context.py:34-42` instructs the model to *"refer to image descriptions (captions)"* — wording that is now an obstacle to upgrading.

The fix is small and structural: load the JPEG, base64-encode it, attach it as an image to the Ollama `/api/chat` message, and tell the model in prose that it can look at the image directly.

---

## What This Plan Does **Not** Change

Explicit non-scope, to keep review focused:

- **Retrieval path.** `_preprocess_query`, `_embed_query`, `_vector_search`, dual-retrieval slot allocation, `image_score_min`, `cross_doc_id_guard`, follow-up rewriting, `@rss`/`@pdf`/`@doc` filters — all unchanged.
- **Schema.** `rag_docs` / `rag_chunks` unchanged. No new tables, no new columns, no new indexes.
- **Re-ingestion.** No PDF or RSS reprocessing required. Existing captions and asset files are used as-is.
- **Vision/embedding models.** `bge-m3` (embeddings) and `qwen2.5vl:7b` (captioning at ingest time) continue to do their existing jobs.
- **OpenWebUI display.** `_build_suffix` in `main.py:395-408` still appends post-answer markdown images and source links — that is the user-facing rendering, not LLM input.
- **n8n fallback path.** `CONTEXT_MODE=n8n` remains caption-only. n8n is a rollback path; extending it is risk-for-no-reward.
- **Captioning at ingest time.** Captions stay in `rag_chunks` and remain the substrate for retrieval. At generation time captions become a grounding hint alongside the pixels, not the model's only signal.
- **Tracks 1 and 2.** GLM-OCR and the visual-embedding column are separate roadmap items.

---

## Architecture (Phase 1)

```
                          rag-gateway (services/rag-gateway/app/)
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  /v1/chat/completions                                                       │
│        │                                                                    │
│        ▼                                                                    │
│  _get_context() ──→ context.get_context_direct()  (UNCHANGED)               │
│        │                ├── _preprocess_query                               │
│        │                ├── _embed_query (bge-m3)                           │
│        │                ├── _vector_search (text + image, dual retrieval)   │
│        │                └── _build_context  ◄─── ONLY FUNCTION THAT CHANGES │
│        │                       │                                            │
│        │                       │  if MULTIMODAL_GENERATION_ENABLED:         │
│        │                       │    - load JPEG bytes from /kb/assets       │
│        │                       │    - base64-encode (capped MAX_IMAGE_BYTES)│
│        │                       │    - cap to MAX_GEN_IMAGES (= 3)           │
│        │                       │    - attach to messages[1].images          │
│        │                       │    - keep terse caption hints in prose     │
│        │                       │  else:                                     │
│        │                       │    - byte-identical to today's behavior    │
│        ▼                                                                    │
│  chat_body = {model, stream:true, options:{num_ctx: 8192, ...},            │
│               messages: [system, {role:"user", content:"…", images:[…]}]}   │
│        │                                                                    │
│        ▼                                                                    │
│  _stream_from_ollama() → POST /api/chat → SSE   (UNCHANGED)                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                       ammer_mmragv2_ollama
                       gemma4:26b (already resident, multimodal-capable)
                              ▲
                              │ base64 image payload (per-message images[])
                              │
                      /kb/assets bind-mount (NEW, read-only)
                       data/assets/{doc_id}_pN_iI.jpeg
                       data/assets/rss/_shared/{sha16}.{ext}
```

**What's new on the wire:** the `messages[user].images` field on the Ollama call gains an array of base64 strings. The NDJSON streaming response shape from Ollama is identical (image tokens are consumed silently inside the vision encoder; output is still text deltas). The SSE translator at `main.py:439-456` requires no change.

---

## Phased Delivery with Hard Gates

Each phase ends at a **hard gate**. A failed gate stops work; do not skip ahead. The cost of finding a problem at gate N is much lower than finding it at gate N+2.

---

### Phase 0 — Pre-flight verification (~5 minutes)

**Goal:** Confirm that `gemma4:26b` running under our pinned Ollama `0.23.1` actually accepts the `images` field and returns a coherent vision-grounded answer.

**Why this is the cheapest possible test:** every downstream phase assumes this works. If it doesn't, the entire effort stops here, before any bind mount, any helper, any eval harness change.

**Procedure:**

1. Pick one already-ingested PDF image from `data/assets/` (a chart from `BMWGroup`, `Siemens`, or `Nachhaltigkeit` — something with embedded text the captioner would have struggled with).
2. Base64-encode it.
3. **Warm `gemma4:26b` first.** A cold-load of the 26b takes 5-15 s on the DGX and would invalidate the wall-clock pass criterion below. Send one text-only request and discard the response:

   ```bash
   docker compose exec -T ollama curl -sS http://localhost:11434/api/chat -d '{
     "model": "gemma4:26b",
     "messages": [{"role":"user","content":"ping"}],
     "stream": false
   }' >/dev/null
   ```

   `OLLAMA_KEEP_ALIVE=1h` should keep it resident afterwards. Verify with `docker compose exec ollama ollama ps` — `gemma4:26b` should appear with a non-zero `UNTIL`.

4. Make the measured call to Ollama with the image, bypassing the gateway entirely:

```bash
B64=$(base64 -w 0 data/assets/<some_chart>.jpeg)
docker compose exec -T ollama curl -sS http://localhost:11434/api/chat -d @- <<EOF
{
  "model": "gemma4:26b",
  "messages": [
    {"role": "user",
     "content": "Was zeigt dieses Diagramm? Liste alle erkennbaren Achsenbeschriftungen und Werte auf.",
     "images": ["${B64}"]}
  ],
  "stream": false,
  "options": {"num_ctx": 8192}
}
EOF
```

5. Measure wall-clock time and inspect `message.content` and `eval_duration` / `prompt_eval_duration` fields.

**Pass criteria (ALL must hold):**

- HTTP 200, valid JSON response.
- `message.content` references **specific visual elements that are NOT in the existing caption** for that asset (axis labels, legend, numeric values, chart shape, etc.). Spot-check by comparing to `SELECT caption FROM rag_chunks WHERE asset_path = '…';`.
- `prompt_eval_duration` is reported (confirms the vision encoder ran).
- Total wall-clock ≤ 5 s for a single 1024 px image (sanity check; expected 1-3 s on warm `gemma4:26b`).

**Fail criteria (any one stops the plan):**

- HTTP 4xx/5xx from Ollama.
- Response ignores the image and asks "Bitte stellen Sie eine Frage" or similar.
- Response is hallucinated (describes content that isn't in the image — confirm by eyeballing the asset).
- Wall-clock > 30 s (suggests CPU fallback; would make demo-time UX unacceptable).

**Artifacts:**

- Save the request/response pair under `data/eval/runs/2026-05-13_phase0_multimodal_curl_probe/` as `request.json` and `response.json`.
- Record observed first-token-ish numbers (Ollama gives `prompt_eval_duration` / `eval_duration`) into `phase0_notes.md`.

**Gate decision:** If pass — proceed to Phase 1. If fail — write up the failure mode, close this spec, escalate. The plan does not continue with a workaround at this stage; the premise of Phase 1 is that Phase 0 passed.

---

### Phase 1 — Compose mount + flag skeleton (~30 minutes)

**Goal:** Make assets reachable from `rag-gateway` and ship the feature flag with `default = false`. **Zero observable behavior change.**

**Changes:**

1. **`docker-compose.yml`** — add a read-only bind mount to the `rag-gateway` service:

   ```yaml
   rag-gateway:
     # ... existing ...
     volumes:
       - ./data/assets:/kb/assets:ro
     environment:
       # ... existing ...

       # --- Multimodal generation (Track 0, flag-gated) ---
       MULTIMODAL_GENERATION_ENABLED: "${MULTIMODAL_GENERATION_ENABLED:-false}"
       ASSETS_LOCAL_DIR: "/kb/assets"
       MAX_GEN_IMAGES: "3"
       MAX_IMAGE_BYTES: "2097152"   # 2 MiB hard cap, defence in depth
       MULTIMODAL_NUM_CTX: "8192"
       MULTIMODAL_IMAGE_PLACEMENT: "after"   # "before" | "after" (Phase 3 A/B)
       # --- end multimodal generation ---
   ```

   The grouping comment is load-bearing for human readers, not for compose. Mirror the same comment band in `services/rag-gateway/app/context.py` when adding the corresponding `os.getenv(...)` calls — six knobs read as one feature surface, not six independent settings.

2. **`services/rag-gateway/app/context.py`** — add config parsing at module top, but keep all branches dead until Phase 2:

   ```python
   MULTIMODAL_GENERATION_ENABLED = os.getenv("MULTIMODAL_GENERATION_ENABLED", "false").lower() in ("1", "true", "yes")
   ASSETS_LOCAL_DIR = os.getenv("ASSETS_LOCAL_DIR", "/kb/assets")
   MAX_GEN_IMAGES = int(os.getenv("MAX_GEN_IMAGES", "3"))
   MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(2 * 1024 * 1024)))
   MULTIMODAL_NUM_CTX = int(os.getenv("MULTIMODAL_NUM_CTX", "8192"))
   MULTIMODAL_IMAGE_PLACEMENT = os.getenv("MULTIMODAL_IMAGE_PLACEMENT", "after").lower()
   ```

3. **Health check addition** — extend `/health/ready` to verify the mount exists when the flag is on (no-op otherwise):

   ```python
   if MULTIMODAL_GENERATION_ENABLED:
       checks["assets_mount"] = "ok" if os.path.isdir(ASSETS_LOCAL_DIR) else f"missing {ASSETS_LOCAL_DIR}"
   ```

**Pass criteria:**

- `docker compose config` validates.
- `docker compose up -d rag-gateway` succeeds; container has `/kb/assets` populated read-only (verify with `docker compose exec rag-gateway ls /kb/assets | head`).
- With `MULTIMODAL_GENERATION_ENABLED=false` (default), the existing eval baseline (`data/eval/runs/20260505_190437__baseline_post_odl/`) reproduces **byte-identical** answers for the 12-prompt set. Any diff fails the gate.
- `/health/ready` returns 200; new `assets_mount` key absent (flag off).
- `scripts/demo_readiness_check.sh` passes unchanged.

**Fail criteria:** any diff in the byte-identical replay, or any pre-existing container failing to start.

**Backout command (Phase 1 fail):** remove the `volumes:` block from the `rag-gateway` service in `docker-compose.yml`, then:

```bash
docker compose up -d --no-deps rag-gateway
```

Re-investigate before retry. The bind mount is the only structural change in this phase and is fully reversible.

**Gate decision:** If pass — proceed to Phase 2. If fail — back out the compose change; the bind mount is the only structural change in this phase and is fully reversible.

---

### Phase 2 — `_build_context` image-passthrough branch (~3-4 hours)

**Goal:** Behind the flag, route approved retrieved images into `messages[user].images` instead of into the text body. Flag still defaults to `false`.

**Files touched:** `services/rag-gateway/app/context.py` only. (Tests in the parallel `tests/` subtree.)

**New helper** (in `context.py`):

```python
def _load_image_b64(asset_path: str) -> tuple[str | None, str | None]:
    """Resolve asset_path relative to ASSETS_LOCAL_DIR, validate, base64-encode.

    Returns (b64, reason_skipped). reason_skipped is None on success, otherwise
    a short tag for tracing: "missing" | "oversize" | "unreadable".
    """
    p = Path(ASSETS_LOCAL_DIR) / asset_path
    try:
        st = p.stat()
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    if not p.is_file():
        return None, "missing"
    if st.st_size > MAX_IMAGE_BYTES:
        return None, "oversize"
    return base64.b64encode(p.read_bytes()).decode("ascii"), None
```

**Changes to `_build_context()`** (function at `context.py:238-458`):

1. After the `_approved_images` set is computed (existing logic at lines 261-273, **unchanged**), build a **bounded ordered list** of approved image hits — capped at `MAX_GEN_IMAGES`, preserving the existing score-desc order:

   ```python
   approved_image_hits = [h for h in hits
                          if h["chunk_type"] == "image" and id(h) in _approved_images][:MAX_GEN_IMAGES]
   ```

   The existing `max_images = 3 if query_wants_images else 2` already produces ≤ 3, so this cap is redundant for the current routing — but it makes the generation-time invariant explicit and survives future retrieval changes.

2. **Branch on the flag.** In the existing context-line build loop, the image branch (lines 303-325) splits into two paths:

   - **Flag off (default):** byte-identical to current behavior. Emit the `Bild (Seite N): <caption> <url>` line. **Do not change this branch.**
   - **Flag on:** suppress the `Bild: …` text line for hits in `approved_image_hits` (others still produce text lines, but they're filtered out of the message by `show_image()`). Instead, collect base64 payloads:

     ```python
     image_payloads = []      # list of base64 strings, ordered
     image_hint_lines = []    # list of "Bild 1 (Seite 4): <caption>" — caption is GROUNDING HINT, not the answer
     skipped = []             # for tracing
     for idx, h in enumerate(approved_image_hits, start=1):
         b64, reason = _load_image_b64(h["asset_path"])
         if b64 is None:
             skipped.append({"chunk_id": h.get("id"), "asset_path": h["asset_path"], "reason": reason})
             continue
         image_payloads.append(b64)
         is_rss = (h.get("meta") or {}).get("content_type") == "rss_article"
         src = (f"Bild {idx} ({(h['meta'] or {}).get('feed_name') or 'RSS'})"
                if is_rss else f"Bild {idx} (Seite {h['page']})")
         image_hint_lines.append(f"{src}: {h.get('caption') or ''}".rstrip(": ").rstrip())
     ```

   When `_load_image_b64` returns `None` for an approved hit (file missing from the mount, oversize, unreadable), the hit silently falls back to its text-line representation in the existing branch — guaranteeing graceful degradation to the caption-only behavior on a per-image basis.

3. **Compose the user message** based on flag + placement:

   ```python
   user_content_body = (
       f"Frage: {query}\n\n"
       f"Kontext aus Dokumenten und Nachrichten:\n{context_text}\n\n"
       "Antworte kurz, korrekt und mit Quellenhinweisen."
   )

   if MULTIMODAL_GENERATION_ENABLED and image_payloads:
       hint_block = ("\n\nBeigefügte Bilder (siehe Bildanhang):\n"
                     + "\n".join(f"- {ln}" for ln in image_hint_lines))
       if MULTIMODAL_IMAGE_PLACEMENT == "before":
           user_msg = {
               "role": "user",
               "content": hint_block.strip() + "\n\n" + user_content_body,
               "images": image_payloads,
           }
       else:
           user_msg = {
               "role": "user",
               "content": user_content_body + hint_block,
               "images": image_payloads,
           }
   else:
       user_msg = {"role": "user", "content": user_content_body}
   ```

   The `MULTIMODAL_IMAGE_PLACEMENT` env var ("before" vs "after") is wired in Phase 2 but not exercised until Phase 3 picks a winner.

4. **System prompt** must change when the flag is on. We swap the two-line vision clause but keep everything else:

   - Caption-only (current, unchanged):
     > "Wenn der Kontext Bildbeschreibungen (Captions) enthält, weise den Nutzer aktiv darauf hin, was auf den Bildern zu sehen ist."
   - Multimodal:
     > "Der Kontext enthält Text aus Dokumenten und kann zusätzlich Bilder enthalten, die der Frage als Bildanhang beigefügt sind. Wenn Bilder beigefügt sind, beschreibe und nutze, was du tatsächlich auf ihnen siehst — verlasse dich nicht nur auf die Bildunterschriften. Falls ein Bild eingebetteten Text, Achsenbeschriftungen oder Zahlenwerte enthält, lies sie direkt ab und zitiere sie wörtlich."

   Implemented as a constant pair (`SYSTEM_PROMPT_CAPTION_ONLY`, `SYSTEM_PROMPT_MULTIMODAL`) selected at message-build time.

5. **`num_ctx` bump.** Set `chat_body.options.num_ctx = MULTIMODAL_NUM_CTX` when the flag is on; otherwise keep `4096` to preserve byte-identical baseline.

6. **Trace enrichment.** Extend `_trace.RetrievalTrace` records with a new top-level key when populated:

   ```python
   trace.set("multimodal_generation", {
       "enabled": MULTIMODAL_GENERATION_ENABLED,
       "image_payloads_attached": len(image_payloads),
       "image_hint_lines": image_hint_lines,
       "skipped_assets": skipped,        # missing/oversize/unreadable
       "image_placement": MULTIMODAL_IMAGE_PLACEMENT,
       "num_ctx_used": chat_body["options"]["num_ctx"],
   })
   ```

   This makes A/B analysis in Phase 3 cheap — every trace says exactly which mode produced it.

**Tests** (`services/rag-gateway/tests/`):

- `test_context_image_passthrough.py` — new file. Uses a fixture image bundled under `tests/fixtures/`. Asserts:
  - Flag off: `chat_body` has no `images` key on any message; behavior matches existing snapshot.
  - Flag on, asset resolvable: `messages[1].images` is a list of exactly the expected length, capped at `MAX_GEN_IMAGES`; corresponding `Bild: …` text lines suppressed; hint block appended in `content`.
  - Flag on, asset missing: hit falls back to caption-text-line; trace `skipped_assets` records `reason="missing"`.
  - Flag on, asset oversize (mock a 3 MiB file): same fallback path, `reason="oversize"`.
  - Both placement modes (`before`, `after`) produce expected `content` layouts.
- `test_context_byte_identical_baseline.py` — replays the 12-prompt baseline through `_build_context()` with `MULTIMODAL_GENERATION_ENABLED=false` and asserts the produced `chat_body` is byte-identical to a stored golden snapshot. This is a regression guard against accidentally leaking multimodal behavior into the flag-off path.

**Pass criteria:**

- All new tests green.
- Existing `services/rag-gateway/tests/` green.
- Manual smoke (flag on): start a chat in OpenWebUI with a prompt that hits an image. Inspect the rag-gateway log; trace record shows `multimodal_generation.image_payloads_attached >= 1`. Answer references something the caption doesn't.
- Manual smoke (flag off): same prompt produces the existing answer byte-for-byte.

**Fail criteria:**

- Byte-identical baseline test fails (= flag-off path leaked multimodal behavior — must be fixed before proceeding).
- Image payload missing despite asset existing on disk (= mount path mismatch — debug `ASSETS_LOCAL_DIR` resolution).
- Ollama returns 400 / refuses the request with images (= contradicts Phase 0; reopens Phase 0 verification).

**Gate decision:** If pass — proceed to Phase 3. The flag is in production, default off; no users see any change yet.

---

### Phase 3 — Eval harness extension + chart-comprehension prompts (~1.5-2 days)

**Goal:** Produce defensible A/B numbers between caption-only and multimodal generation on a prompt set that actually discriminates the two. **This is the long pole of the plan.** Optimistic timing assumes existing harness is in good shape and the discriminating prompts come together quickly; pessimistic assumes the chart prompts need iteration.

**Why the eval is the long pole, not the implementation:** the implementation is two lines of logic in one branch of one function. The hard work is designing prompts where the answer differs *in a way a reviewer can read off the page*, and scoring the results consistently. Without that, flag-on is just a feeling.

**Changes:**

1. **`scripts/eval_run.py`** — add `--mode=caption|multimodal` flag. Internally this sets `MULTIMODAL_GENERATION_ENABLED` on the request path (either by injecting an env var into the gateway pre-run or — preferable — by adding an explicit per-request override header `X-Internal-Multimodal-Generation: on|off` that the gateway reads in Phase 2's parsing block, so the harness can flip per request without restarting the container).

   Decision: implement the per-request header override; it makes A/B faster and keeps the gateway state stable across runs. The header is a simple wrapper around the env-default; the env stays the source of truth for production.

2. **`scripts/eval_run.py`** — add `--image-placement=before|after` to drive the placement A/B inside the multimodal mode. Same header pattern (`X-Internal-Multimodal-Image-Placement`).

3. **Prompt set additions.** Under `data/eval/prompts/`, add three chart/diagram comprehension prompts whose answers should be **measurably** better when the model sees pixels:

   - `chart_bmw_p04_list_completeness.json` — the known BMW p04 failure case. Document any caption-only baseline answer, then measure whether pixel access closes any of the gap. Hypothesis: closes some, not all, because the case is also retrieval-side (memory) — useful as a control.
   - `chart_siemens_diagram_legend.json` — a Siemens diagram with a legend the captioner is known to abbreviate. Prompt asks for the legend entries verbatim.
   - `chart_nachhaltigkeit_axis_values.json` — a Nachhaltigkeit chart with embedded numeric values on bars/segments. Prompt asks for specific values.

   Each prompt fixture stores: prompt text, expected key facts (the axis labels / legend entries / numbers that *should* appear in a correct answer), the relevant `asset_path(s)` for sanity, and a scoring rubric (recall of key facts; tolerated paraphrase; allowed wrong values = 0).

4. **Scoring.** Reuse the existing scorecard pattern from the post-ODL baseline (`data/eval/runs/20260505_190437__baseline_post_odl/`). Add a "vision-grounded facts recovered" column: integer 0..K where K is the number of expected key facts in the rubric.

5. **Runs to produce:**

   | Run | Mode | Placement | Prompt set | Purpose |
   |---|---|---|---|---|
   | `2026-05-13_phase3_caption_baseline` | caption | n/a | 12 baseline + 3 chart | Re-baseline (current behavior; should match `20260505_190437`) |
   | `2026-05-13_phase3_multimodal_after` | multimodal | after | 12 baseline + 3 chart | Headline A/B |
   | `2026-05-13_phase3_multimodal_before` | multimodal | before | 12 baseline + 3 chart | Placement A/B |
   | `2026-05-13_phase3_multimodal_after_capped3` | multimodal | after | 3 chart | Sanity: triple-image budget probe |

6. **Corpus pinning.** All Phase 3 runs target a **pinned DB snapshot**, not the live database. For the current state of the project, the candidate baseline is `data/demo_snapshot_pre_opendataloader_20260505_172446.sql` (or its successor if the corpus is reprocessed before Phase 3 begins). Live DB is *not* acceptable: between Phase 3 measurement and Phase 4 dress rehearsal, any background ingestion (`rss-ingest` cron, new PDFs in `data/inbox/`) would invalidate the A/B numbers. Operator action before the four runs begin:

   - Either restore the snapshot to a side database used only for evaluation, or
   - Stop `rss-ingest`, drain `data/inbox/`, and confirm `SELECT COUNT(*) FROM rag_chunks` is stable across two reads 5 minutes apart.

   The same DB state must persist through Phase 4 dress rehearsal. A separate Phase 3 artifact records the pinned snapshot identifier and the chunk count so Phase 4 can verify before flipping the flag.

6. **Latency tracking.** Eval harness already records `prompt_eval_duration` and `eval_duration` when Ollama emits them. Surface them in the comparison table — multimodal mode is expected to add 200-800 ms of `prompt_eval_duration` per image, ~600-2400 ms total at 3 images. This is the "additive vision-encoder cost" risk made visible.

**Pass criteria:**

- All four runs complete; no errors, no timeouts.
- Caption baseline run matches `20260505_190437` within scoring tolerance (drift here is its own bug).
- On the 3 chart prompts, multimodal-after recovers strictly more vision-grounded facts than caption-only on at least 2 of 3. (Equality on the BMW p04 case is acceptable; it's the retrieval-bound control.)
- On the 12 baseline prompts, multimodal-after is not measurably worse than caption-only (no regressions in scorecard score; latency increase ≤ 3 s per prompt).
- Placement A/B yields a clear winner — or, if not, document the indifference and pick `after` as default.

**Fail criteria:**

- Multimodal-after regresses on the 12 baseline (= we made things worse on the demo prompts). Investigate before flipping.
- Latency makes first-token feel sluggish under typical demo conditions (> 5 s wall-clock). Investigate image budget / num_ctx / placement before flipping.
- Vision-grounded facts not recovered on any of the 3 chart prompts (= Phase 0 may have been optimistic; revisit prompt construction OR escalate as a model capability limit).

**Artifacts:**

- `data/eval/runs/2026-05-13_phase3_*/` directories with raw responses, scorecards, latency tables.
- `docs/plans/2026-05-13-multimodal-generation-eval-summary.md` — a brief sibling doc presenting the A/B in a form attachable to a future Sven review.

**Gate decision:** If pass — proceed to Phase 4. If fail — do not flip the flag. Either iterate (placement, num_ctx, image budget, prompt construction) or document the negative result and close the spec.

---

### Phase 4 — Flag flip on feature branch + dress rehearsal (~half day)

**Goal:** Turn the flag on under controlled conditions, validate end-to-end, then merge.

**Steps:**

1. Feature branch `option3d-multimodal-generation` off current `option3c-hybrid`. Push `MULTIMODAL_GENERATION_ENABLED=true` to `.env` on the branch only (uncommitted, matching the existing `.env` workflow per project memory).
2. Restart `rag-gateway` (`make` target or `docker compose up -d --no-deps rag-gateway`). `/health/ready` should now report `assets_mount: ok`.
3. Run `scripts/demo_readiness_check.sh`. All checks must pass; add a new check for the multimodal mount and capability if convenient (optional).
4. Run `docs/DRESS_REHEARSAL.md` Track 30-min (Mixed). Note any visible UX regressions: first-token latency, image hallucination, captioner-vs-pixel disagreement edge cases.
5. Decision point:
   - **Promote:** merge to `main`, leave `.env` unflipped on `main` so production default stays off until a separate release decision. Update `MANUAL_STEPS.md` Deployment Deviations with D26 (see below).
   - **Hold:** if rehearsal surfaces a defect, file an issue, revert the `.env` flip on the branch, and decide whether to fix-and-retry or close.

**Pass criteria (all rows must hold):**

| Criterion | Threshold | How measured |
|---|---|---|
| Browser console errors during rehearsal | 0 | DevTools Console panel (the Chrome-DevTools-MCP suite or manual) |
| Network 5xx during rehearsal | 0 | DevTools Network panel filtered by status |
| SSE stalls / partial answers | 0 | Visual: cursor moves continuously until `[DONE]`; no truncated responses |
| First-token latency, 3-image prompt | ≤ 5 s wall-clock | Stopwatch: submit → first visible token |
| Full-answer latency, 3-image prompt | ≤ 15 s wall-clock | Stopwatch: submit → SSE `[DONE]` |
| OpenWebUI post-answer image suffix render | Present, matches retrieved assets | Visual |
| Answer-quality win on at least one chart/diagram prompt | ≥ 1 prompt outperforms caption-only on Phase 3 rubric | Cross-reference Phase 3 scorecards |
| No regression vs caption-only on the 12 baseline prompts | Score delta ≥ 0 across the 12 | Cross-reference Phase 3 scorecards |

**Fail criteria:** any row fails. Specifically, latency exceeding 5 s to first token or 15 s total on a typical multimodal prompt is a hold — *not* a "ship and tune later" — because the demo experience visibly degrades. User-visible behavior unexpectedly diverging from Phase 3 measurements (suggests env or container drift between phases) is also a hold; reconcile before flipping.

**Gate decision:** Promote vs hold per above. Production rollout (flipping `.env` on `main`) is a separate, smaller decision made off this spec — call it Phase 5 if/when it becomes a question.

---

## Open Questions / Risks

Captured for the review, not for the implementation:

1. **Image placement order.** Gemma 3/4 inject `<start_of_image>` markers when `images[]` is set. Where those markers land relative to the caption hint text affects grounding quality. Phase 3 A/B settles this empirically. Pre-decision: default to `after` (caption text first, image next) on the theory that the hint primes the visual grounding question; revisit if A/B disagrees.

2. **Per-image vision-encoder cost is additive.** At 280 visual tokens/image × 3 images = 840 vision tokens of encoder work, not 280 — and the encoder runs once per image, not once per request. Phase 3 latency tracking will surface this. Hard cap `MAX_GEN_IMAGES=3` is the policy lever; raising it should be a deliberate, latency-justified call.

3. **First-token latency under SSE-through-Funnel.** Project memory: SSE-through-Funnel is an unresolved validation item for the Option 3C hybrid demo mode. Adding multimodal generation increases the gap between request and first byte (vision encode is upfront). Local-network validation is sufficient for Phase 4; off-tailnet validation belongs in the Option 3C hybrid validation track, not here.

4. **Capability check / graceful fallback.** Future models we might add (smaller text-only Gemma, a hypothetical OpenAI fallback) won't accept `images[]`. Phase 2's per-asset fallback (missing/oversize/unreadable → caption text line) already handles a fully-blank multimodal path, but the cleaner solution is a one-time capability probe at gateway startup against the configured `DEFAULT_MODEL`. **Decision:** out of scope for this spec; the flag default of `false` is the explicit kill switch. If a non-multimodal model is ever promoted to `DEFAULT_MODEL`, the operator must flip the flag off before the swap. Documented in the rollback section.

5. **Caption-vs-pixel disagreement.** If the captioner said one thing and the model now sees something different on the pixels, the model may surface a contradiction in the answer. Practically: the system prompt instructs the model to trust pixels over captions. Phase 3 chart prompts will catch any pathological case; expected outcome is *improvement on numerics/labels, no regression on shape/topic*.

6. **n8n fallback drift.** `CONTEXT_MODE=n8n` does not change. If the demo ever rolls back to n8n mode under load, answer quality drops to caption-only — accepted, since n8n is a rollback path. The system prompt in n8n's Build Context node is independent and stays as-is.

7. **OpenWebUI display unchanged.** The suffix at `main.py:395-408` still appends `![caption](url)` images and the sources block. The model now reasons over the same images it later displays — visually consistent UX.

8. **Re-timing vs first estimate.** Initial gut estimate was "1 day implementation + 1 day eval." Honest re-timing: Phase 0 ≤ 5 min, Phase 1 ≤ 30 min, Phase 2 ~3-4 hours, Phase 3 ~1.5-2 days, Phase 4 ~half day. End-to-end **~3 days** with defensible numbers. The eval is the long pole.

---

## Files Changed

| File | Phase | Change |
|---|---|---|
| `docker-compose.yml` | 1 | Add `./data/assets:/kb/assets:ro` mount + 5 env vars on `rag-gateway` |
| `services/rag-gateway/app/context.py` | 1 | Config parsing for new env vars (no behavior) |
| `services/rag-gateway/app/context.py` | 2 | `_load_image_b64()` helper; flag-gated branch in `_build_context()`; system-prompt pair; `num_ctx` bump under flag; trace enrichment |
| `services/rag-gateway/app/main.py` | 2 | Parse `X-Internal-Multimodal-Generation` / `X-Internal-Multimodal-Image-Placement` request headers (eval-harness override) |
| `services/rag-gateway/tests/test_context_image_passthrough.py` | 2 | New test file (image-passthrough, both placements, fallback paths) |
| `services/rag-gateway/tests/test_context_byte_identical_baseline.py` | 2 | New regression test (flag-off must stay byte-identical) |
| `services/rag-gateway/tests/fixtures/` | 2 | Bundled fixture JPEG (small chart-like image) |
| `scripts/eval_run.py` | 3 | `--mode=caption|multimodal`, `--image-placement=before|after`; emit per-request override headers; surface `prompt_eval_duration` in scorecard |
| `data/eval/prompts/chart_bmw_p04_list_completeness.json` | 3 | New prompt fixture |
| `data/eval/prompts/chart_siemens_diagram_legend.json` | 3 | New prompt fixture |
| `data/eval/prompts/chart_nachhaltigkeit_axis_values.json` | 3 | New prompt fixture |
| `docs/plans/2026-05-13-multimodal-generation-eval-summary.md` | 3 | Eval write-up (sibling to this doc) |
| `MANUAL_STEPS.md` | 4 | Add D26 to Deployment Deviations table |

**No new Python dependencies.** `base64`, `pathlib`, `os` are stdlib.
**No DB migrations.**
**No re-ingestion.**
**No new host ports.**
**No new public exposure.**

---

## Rollback Safety

- **Flag default is `false`.** Production behavior is unchanged until a deliberate operator action (`.env` flip + restart).
- **Per-asset fallback.** If an approved hit's asset is missing/oversize/unreadable, that hit falls back to its existing caption text line. A single bad file cannot wedge a multimodal request.
- **Byte-identical baseline test** (Phase 2) is a permanent regression guard: any future PR that accidentally leaks multimodal behavior into the flag-off path fails that test.
- **No data is rewritten.** Captions, embeddings, asset files are all read-only inputs. Rolling back is `MULTIMODAL_GENERATION_ENABLED=false` + restart, no DB action required.
- **Compose mount is read-only.** No risk of the gateway corrupting the assets dir.
- **n8n fallback path unchanged.** Setting `CONTEXT_MODE=n8n` immediately routes around all of this code.
- **Capability mismatch (text-only model swap).** If `DEFAULT_MODEL` is changed to a non-multimodal model while the flag is on, Ollama returns 400. The SSE error path at `main.py:466-473` must return a **specifically informative German error chunk** for this case — not a generic 4xx forwarding. Required wording (literal): `"[Das aktive Modell unterstützt keine Bildeingabe. Das Multimodal-Flag (MULTIMODAL_GENERATION_ENABLED) muss vor einem Modellwechsel deaktiviert werden.]"`. This preserves observability without adding a startup capability probe. Implementation: when the SSE error path catches an Ollama 400 from a request that carried `images[]`, swap in this specific chunk before continuing the existing error-translation logic. Documented; the operating policy remains "operator flips flag off before swapping to a text-only model."

---

## Spec Deviation Candidate

**D26** *(placeholder — number to verify at promotion time)***:** Multimodal generation behind feature flag — `rag-gateway` loads retrieved image bytes from `data/assets/` (read-only bind mount) and attaches them as `images[]` on the user message in `/api/chat`, allowing `gemma4:26b` to reason over pixels at answer time. Retrieval remains caption-based. Flag-gated (`MULTIMODAL_GENERATION_ENABLED`, default `false`). Captioning at ingest time, schema, n8n fallback path, and OpenWebUI display are unchanged. This is Track 0 of a three-track hybrid roadmap; Tracks 1 (GLM-OCR extraction fallback) and 2 (visual-embedding retrieval column / ColPali-class) remain separate roadmap items.

*Numbering note:* project memory says "Spec Deviations (19 total)" but the enumerated list (`D14`–`D24`, with sub-letters on `D18`) suggests a different count. Reconcile against `MANUAL_STEPS.md` "Deployment Deviations" table at promotion time; the literal next available integer may be `D25`, `D26`, or higher. This spec uses `D26` as a placeholder; the value is non-load-bearing.

---

## Cross-References

- `docs/plans/2026-03-04-image-relevance-design.md` — caption quality and image-relevance thresholds at retrieval time. Complementary, not overlapping.
- `docs/plans/2026-03-06-fast-pdf-ingestion-design.md` — ingest-time pipeline and captioning concurrency model. The captions consumed here are produced by that pipeline.
- `docs/superpowers/specs/2026-05-05-opendataloader-pdf-design.md` — current PDF extraction architecture. Track 1 (GLM-OCR) would amend or supplement that; this spec does not.
- `docs/superpowers/specs/2026-05-05-rag-gateway-think-false-design.md` — most recent gateway-side spec; same shape as this one.
- Project memory entries: caption-only rationale (Feb email to Sven), `gemma4:26b` promotion (May 2026 A/B), Ollama `0.23.1` pin (Gemma 4 manifest support), BMW p04 retrieval-side classification.
