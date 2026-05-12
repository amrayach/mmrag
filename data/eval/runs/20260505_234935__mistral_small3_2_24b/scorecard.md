# Eval scorecard — mistral_small3_2_24b

- **Run dir:** `data/eval/runs/20260505_234935__mistral_small3_2_24b`
- **Started:** 2026-05-05T21:49:35+00:00
- **Model:** `mistral-small3.2:24b-instruct-2506-q4_K_M`
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
| p01_bmw_kennzahlen | pdf_factual_de | 4679 | 23235 | 555 | 8 | 2 |  |  |  |  |  |  |  |
| p02_siemens_nachhaltigkeit_ziele | pdf_factual_de | 1827 | 40224 | 1702 | 6 | 1 |  |  |  |  |  |  |  |
| p03_techvision_bereiche | pdf_factual_de | 1707 | 5679 | 145 | 6 | 2 |  |  |  |  |  |  |  |
| p04_bmw_list_completeness | pdf_list_completeness | 3900 | 67841 | 2265 | 6 | 2 |  |  |  |  |  |  |  |
| p05_bmw_table_numbers | pdf_table_extraction | 4751 | 37268 | 1272 | 8 | 2 |  |  |  |  |  |  |  |
| p06_pdf_image_relevance | pdf_image_caption | 3409 | 16114 | 569 | 7 | 3 |  |  |  |  |  |  |  |
| p07_no_filter_german | no_filter_de | 2965 | 25663 | 1150 | 6 | 0 |  |  |  |  |  |  |  |
| p08_rss_summary_de | rss_summary_de | 2417 | 25911 | 973 | 6 | 0 |  |  |  |  |  |  |  |
| p09_rss_entity_de | rss_entity_de | 2879 | 33576 | 1386 | 3 | 0 |  |  |  |  |  |  |  |
| p10_siemens_english | pdf_factual_en | 1440 | 17146 | 1086 | 4 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t1 | followup_de | 1461 | 12631 | 504 | 5 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t2 | followup_de | 1627 | 16507 | 703 | 5 | 1 |  |  |  |  |  |  |  |
| p12_repeat_for_stability | stability | 4722 | 22488 | 517 | 8 | 2 |  |  |  |  |  |  |  |

## Free-form observations

- Repetition patterns:
- List truncation:
- Wrong-language outputs:
- Wrong-source citations:
- BMW unembedded-chunk symptoms:
