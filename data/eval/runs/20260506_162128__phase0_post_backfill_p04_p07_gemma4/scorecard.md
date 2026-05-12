# Eval scorecard — phase0_post_backfill_p04_p07_gemma4

- **Run dir:** `data/eval/runs/20260506_162128__phase0_post_backfill_p04_p07_gemma4`
- **Started:** 2026-05-06T14:21:28+00:00
- **Model:** `gemma4:26b`
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
| p04_bmw_list_completeness | pdf_list_completeness | — | 10825 | 1252 | 6 | 2 |  |  |  |  |  |  |  |
| p07_no_filter_german | no_filter_de | — | 8713 | 1815 | 6 | 0 |  |  |  |  |  |  |  |

## Free-form observations

- Repetition patterns:
- List truncation:
- Wrong-language outputs:
- Wrong-source citations:
- BMW unembedded-chunk symptoms:
