# Eval scorecard — phase0_post_backfill_p04_p07

- **Run dir:** `data/eval/runs/20260506_162030__phase0_post_backfill_p04_p07`
- **Started:** 2026-05-06T14:20:30+00:00
- **Model:** `qwen2.5:7b-instruct`
- **Gateway:** `http://127.0.0.1:56155`
- **Stream:** `False`
- **Prompts file:** `data/eval/prompts.json`

## Rubric

Score each axis 1–5 (1 = unusable, 3 = acceptable, 5 = excellent).

| Axis | Meaning |
|---|---|
| faith. | Faithfulness — every claim is supported by retrieved context |
| compl. | Completeness — covers everything the context contains |
| cite | Citation — sources/images are correct and useful |
| lang | Language — output language matches user; German is fluent |
| rep | Repetition — no looping or duplicate bullets |
| struct | Structure — sensible structure, lists where lists belong |

## Per-prompt scores (fill in manually)

| ID | Category | TTFT ms | Total ms | Chars | #src | #img | faith. | compl. | cite | lang | rep | struct | Notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| p04_bmw_list_completeness | pdf_list_completeness | — | 15575 | 1611 | 6 | 2 |  |  |  |  |  |  |  |
| p07_no_filter_german | no_filter_de | — | 14854 | 1561 | 6 | 0 |  |  |  |  |  |  |  |

## Free-form observations

- Repetition patterns:
- List truncation:
- Wrong-language outputs:
- Wrong-source citations:
- BMW unembedded-chunk symptoms:
