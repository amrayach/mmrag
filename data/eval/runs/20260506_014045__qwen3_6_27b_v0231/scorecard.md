# Eval scorecard — qwen3_6_27b_v0231

- **Run dir:** `data/eval/runs/20260506_014045__qwen3_6_27b_v0231`
- **Started:** 2026-05-05T23:40:45+00:00
- **Model:** `qwen3.6:27b`
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
| p01_bmw_kennzahlen | pdf_factual_de | 7996 | 55090 | 1461 | 8 | 2 |  |  |  |  |  |  |  |
| p02_siemens_nachhaltigkeit_ziele | pdf_factual_de | 2880 | 71504 | 2487 | 6 | 1 |  |  |  |  |  |  |  |
| p03_techvision_bereiche | pdf_factual_de | 3031 | 9299 | 201 | 6 | 2 |  |  |  |  |  |  |  |
| p04_bmw_list_completeness | pdf_list_completeness | 4832 | 30654 | 936 | 6 | 2 |  |  |  |  |  |  |  |
| p05_bmw_table_numbers | pdf_table_extraction | 5794 | 44721 | 1135 | 8 | 2 |  |  |  |  |  |  |  |
| p06_pdf_image_relevance | pdf_image_caption | 4032 | 22703 | 741 | 7 | 3 |  |  |  |  |  |  |  |
| p07_no_filter_german | no_filter_de | 4404 | 57783 | 2187 | 6 | 0 |  |  |  |  |  |  |  |
| p08_rss_summary_de | rss_summary_de | 3964 | 40651 | 1365 | 6 | 0 |  |  |  |  |  |  |  |
| p09_rss_entity_de | rss_entity_de | 4871 | 58151 | 2077 | 3 | 0 |  |  |  |  |  |  |  |
| p10_siemens_english | pdf_factual_en | 2466 | 48234 | 2138 | 4 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t1 | followup_de | 2598 | 27976 | 1021 | 5 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t2 | followup_de | 2719 | 39911 | 1580 | 5 | 1 |  |  |  |  |  |  |  |
| p12_repeat_for_stability | stability | 6117 | 73532 | 1996 | 8 | 2 |  |  |  |  |  |  |  |

## Free-form observations

- Repetition patterns:
- List truncation:
- Wrong-language outputs:
- Wrong-source citations:
- BMW unembedded-chunk symptoms:
