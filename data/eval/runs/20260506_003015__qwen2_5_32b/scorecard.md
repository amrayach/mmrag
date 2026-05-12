# Eval scorecard — qwen2_5_32b

- **Run dir:** `data/eval/runs/20260506_003015__qwen2_5_32b`
- **Started:** 2026-05-05T22:30:15+00:00
- **Model:** `qwen2.5:32b-instruct-q4_K_M`
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
| p01_bmw_kennzahlen | pdf_factual_de | 4702 | 32204 | 662 | 8 | 2 |  |  |  |  |  |  |  |
| p02_siemens_nachhaltigkeit_ziele | pdf_factual_de | 2424 | 73167 | 1863 | 9 | 1 |  |  |  |  |  |  |  |
| p03_techvision_bereiche | pdf_factual_de | 2642 | 33870 | 1000 | 6 | 2 |  |  |  |  |  |  |  |
| p04_bmw_list_completeness | pdf_list_completeness | 3701 | 40878 | 1138 | 6 | 2 |  |  |  |  |  |  |  |
| p05_bmw_table_numbers | pdf_table_extraction | 4656 | 52846 | 885 | 8 | 2 |  |  |  |  |  |  |  |
| p06_pdf_image_relevance | pdf_image_caption | 2735 | 68514 | 1320 | 7 | 3 |  |  |  |  |  |  |  |
| p07_no_filter_german | no_filter_de | 3935 | 43210 | 1200 | 6 | 0 |  |  |  |  |  |  |  |
| p08_rss_summary_de | rss_summary_de | 4083 | 39692 | 1048 | 6 | 0 |  |  |  |  |  |  |  |
| p09_rss_entity_de | rss_entity_de | 4358 | 52539 | 1455 | 3 | 0 |  |  |  |  |  |  |  |
| p10_siemens_english | pdf_factual_en | 1953 | 27843 | 1310 | 4 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t1 | followup_de | 1953 | 48657 | 1472 | 5 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t2 | followup_de | 2158 | 42129 | 1281 | 5 | 1 |  |  |  |  |  |  |  |
| p12_repeat_for_stability | stability | 4502 | 28248 | 586 | 8 | 2 |  |  |  |  |  |  |  |

## Free-form observations

- Repetition patterns:
- List truncation:
- Wrong-language outputs:
- Wrong-source citations:
- BMW unembedded-chunk symptoms:
