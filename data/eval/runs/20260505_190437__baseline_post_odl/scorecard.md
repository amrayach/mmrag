# Eval scorecard — baseline_post_odl

- **Run dir:** `data/eval/runs/20260505_190437__baseline_post_odl`
- **Started:** 2026-05-05T17:04:37+00:00
- **Model:** `qwen2.5:7b-instruct`
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
| p01_bmw_kennzahlen | pdf_factual_de | 1155 | 9942 | 993 | 8 | 2 |  |  |  |  |  |  |  |
| p02_siemens_nachhaltigkeit_ziele | pdf_factual_de | 736 | 13880 | 1740 | 6 | 1 |  |  |  |  |  |  |  |
| p03_techvision_bereiche | pdf_factual_de | 758 | 5850 | 652 | 6 | 2 |  |  |  |  |  |  |  |
| p04_bmw_list_completeness | pdf_list_completeness | 977 | 6595 | 753 | 6 | 2 |  |  |  |  |  |  |  |
| p05_bmw_table_numbers | pdf_table_extraction | 1088 | 11089 | 693 | 8 | 2 |  |  |  |  |  |  |  |
| p06_pdf_image_relevance | pdf_image_caption | 743 | 3704 | 444 | 7 | 3 |  |  |  |  |  |  |  |
| p07_no_filter_german | no_filter_de | 964 | 12591 | 1622 | 5 | 0 |  |  |  |  |  |  |  |
| p08_rss_summary_de | rss_summary_de | 921 | 12055 | 1377 | 6 | 0 |  |  |  |  |  |  |  |
| p09_rss_entity_de | rss_entity_de | 1077 | 11863 | 1368 | 3 | 0 |  |  |  |  |  |  |  |
| p10_siemens_english | pdf_factual_en | 591 | 9635 | 1388 | 4 | 2 |  |  |  |  |  |  |  |
| p11_followup_deictic/t1 | followup_de | 633 | 8529 | 1059 | 5 | 1 |  |  |  |  |  |  |  |
| p11_followup_deictic/t2 | followup_de | 630 | 9727 | 1011 | 5 | 2 |  |  |  |  |  |  |  |
| p12_repeat_for_stability | stability | 1131 | 12565 | 923 | 8 | 3 |  |  |  |  |  |  |  |

## Free-form observations

- Repetition patterns:
- List truncation:
- Wrong-language outputs:
- Wrong-source citations:
- BMW unembedded-chunk symptoms:
