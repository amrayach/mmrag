# Eval scorecard — qwen3_30b_v0231

- **Run dir:** `data/eval/runs/20260506_013422__qwen3_30b_v0231`
- **Started:** 2026-05-05T23:34:22+00:00
- **Model:** `qwen3:30b`
- **Gateway:** `http://127.0.0.1:56155`
- **Stream:** `True`
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
| p01_bmw_kennzahlen | pdf_factual_de | 9763 | 22074 | 2599 | 8 | 2 |  |  |  |  |  |  |  |
| p02_siemens_nachhaltigkeit_ziele | pdf_factual_de | 4428 | 18340 | 2739 | 6 | 1 |  |  |  |  |  |  |  |
| p03_techvision_bereiche | pdf_factual_de | 913 | 14776 | 3364 | 6 | 2 |  |  |  |  |  |  |  |
| p04_bmw_list_completeness | pdf_list_completeness | 1269 | 15460 | 3223 | 6 | 2 |  |  |  |  |  |  |  |
| p05_bmw_table_numbers | pdf_table_extraction | 1456 | 15965 | 2010 | 8 | 2 |  |  |  |  |  |  |  |
| p06_pdf_image_relevance | pdf_image_caption | 1049 | 15847 | 3367 | 7 | 3 |  |  |  |  |  |  |  |
| p07_no_filter_german | no_filter_de | 11179 | 25436 | 3580 | 6 | 0 |  |  |  |  |  |  |  |
| p08_rss_summary_de | rss_summary_de | 1203 | 15240 | 3071 | 6 | 0 |  |  |  |  |  |  |  |
| p09_rss_entity_de | rss_entity_de | 1357 | 15581 | 2925 | 3 | 0 |  |  |  |  |  |  |  |
| p10_siemens_english | pdf_factual_en | 752 | 14668 | 3967 | 4 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t1 | followup_de | 2575 | 16430 | 3865 | 5 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t2 | followup_de | 746 | 14597 | 3949 | 5 | 1 |  |  |  |  |  |  |  |
| p12_repeat_for_stability | stability | 1708 | 16415 | 2616 | 8 | 2 |  |  |  |  |  |  |  |

## Free-form observations

- Repetition patterns:
- List truncation:
- Wrong-language outputs:
- Wrong-source citations:
- BMW unembedded-chunk symptoms:
