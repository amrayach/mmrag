# Eval scorecard — gemma4_26b

- **Run dir:** `data/eval/runs/20260506_015332__gemma4_26b`
- **Started:** 2026-05-05T23:53:32+00:00
- **Model:** `gemma4:26b`
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
| p01_bmw_kennzahlen | pdf_factual_de | 1377 | 6119 | 625 | 8 | 2 |  |  |  |  |  |  |  |
| p02_siemens_nachhaltigkeit_ziele | pdf_factual_de | 904 | 12466 | 2375 | 6 | 1 |  |  |  |  |  |  |  |
| p03_techvision_bereiche | pdf_factual_de | 908 | 3162 | 440 | 6 | 2 |  |  |  |  |  |  |  |
| p04_bmw_list_completeness | pdf_list_completeness | 1225 | 6831 | 1137 | 6 | 2 |  |  |  |  |  |  |  |
| p05_bmw_table_numbers | pdf_table_extraction | 1361 | 6890 | 839 | 8 | 2 |  |  |  |  |  |  |  |
| p06_pdf_image_relevance | pdf_image_caption | 961 | 6486 | 838 | 7 | 3 |  |  |  |  |  |  |  |
| p07_no_filter_german | no_filter_de | 1179 | 9358 | 1879 | 6 | 0 |  |  |  |  |  |  |  |
| p08_rss_summary_de | rss_summary_de | 1124 | 7305 | 1208 | 6 | 0 |  |  |  |  |  |  |  |
| p09_rss_entity_de | rss_entity_de | 1268 | 10850 | 1913 | 3 | 0 |  |  |  |  |  |  |  |
| p10_siemens_english | pdf_factual_en | 790 | 5113 | 1147 | 4 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t1 | followup_de | 805 | 4532 | 850 | 5 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t2 | followup_de | 833 | 5437 | 1050 | 5 | 1 |  |  |  |  |  |  |  |
| p12_repeat_for_stability | stability | 1362 | 6075 | 625 | 8 | 2 |  |  |  |  |  |  |  |

## Free-form observations

- Repetition patterns:
- List truncation:
- Wrong-language outputs:
- Wrong-source citations:
- BMW unembedded-chunk symptoms:
