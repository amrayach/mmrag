# BMW Backfill Execution Anomaly

- **Captured at:** 2026-05-06T13:58:00+00:00
- **Status:** `stopped_after_backfill_anomaly`
- **Target chunks before execution:** 486
- **Backfill results:** {'ok': 12, 'failed': 474, 'skipped': 0}
- **BMW NULL embeddings after:** 476
- **BMW NULL + ollama_embed_failed after:** 0
- **BMW NULL + gibberish cleanup error after:** 474
- **BMW NULL + no embedding_error after:** 2
- **Chunk 37039 embedded:** yes
- **Chunk 37039 dim:** 1024
- **Chunk 37039 error_state:** None

## Stop Reason

474 of 486 target chunks failed ingest-cleanup validation; live traced p04/p07 diagnostics were not run.

## Interpretation

Original ollama_embed_failed was replaced for 474 chunks by ValueError: empty or gibberish embedding input after ingest cleanup, indicating extraction/noise quality rather than transient Ollama availability for most failed BMW chunks.

## Successful Target Chunks

| chunk_id | page | dim | error_state | chars |
|---:|---:|---:|---|---:|
| 37019 | 67 | 1024 |  | 1498 |
| 37039 | 71 | 1024 |  | 1263 |
| 37211 | 106 | 1024 |  | 1316 |
| 37276 | 120 | 1024 |  | 1494 |
| 37277 | 120 | 1024 |  | 211 |
| 37328 | 131 | 1024 |  | 1438 |
| 37562 | 189 | 1024 |  | 1438 |
| 37596 | 202 | 1024 |  | 814 |
| 37721 | 247 | 1024 |  | 841 |
| 37990 | 317 | 1024 |  | 1077 |
| 37991 | 318 | 1024 |  | 1473 |
| 38045 | 336 | 1024 |  | 1351 |

## Diagnostics

Live traced p04/p07 diagnostics were intentionally not run after this anomaly.
