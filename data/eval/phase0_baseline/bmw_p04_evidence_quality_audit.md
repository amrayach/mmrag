# Phase 0 — BMW p04 Evidence-Quality Audit

- **Captured at:** 2026-05-07T16:46:29+00:00
- **Source diagnostic:** `data/eval/phase0_baseline/bmw_p04_diagnostic.json`
- **Mechanical classification:** `generation`
- **Corrected classification:** `mixed_failure`

## Conclusion

The live trace's mechanical classification was generation, but the only original brand-term match in final context was chunk 36880, a table-of-contents chunk. True answer-bearing partial evidence exists in chunks 37032, 37033, 37039, 37040, 37041, and 37047, all of which are now embedded, but none of those reached retrieval candidates or final context. The corrected substantive classification is therefore mixed: ranking/evidence-quality failure for p04 plus a broader BMW extraction/noise problem shown by the remaining NULL-embedding cohort.

- **Chunk 36880 answer-bearing?** No. It is table-of-contents style evidence.
- **Chunk 37039 matters?** Yes. It is BMW Motorrad evidence; current state: embedded.
- **Any true answer-bearing original brand-term chunk reached final context?** No.

## Original 17 Matching Chunks

| chunk | page | emb | label | in_cand | rank | score | in_ctx | note |
|---:|---:|:---:|---|:---:|---:|---:|:---:|---|
| 36806 | 16 | Y | `garbled_or_extraction_noise` | N | — | — | N | Supervisory-board/navigation fragment; not BMW portfolio evidence. |
| 36846 | 27 | Y | `weak_keyword_match` | N | — | — | N | Board photo caption; 'Kunde, Marken, Vertrieb' is an executive remit, not the requested list. |
| 36854 | 31 | Y | `garbled_or_extraction_noise` | N | — | — | N | Supervisory-board/mandate text with extraction noise; no answer-bearing portfolio content. |
| 36880 | 37 | Y | `toc_or_index_only` | Y | 6 | 0.6926 | Y | Table-of-contents page. It reached final context but only points to report sections. |
| 36980 | 55 | Y | `weak_keyword_match` | N | — | — | N | Market overview for international automobile/motorcycle markets, not BMW Group brands/business units. |
| 37032 | 69 | Y | `answer_bearing` | N | — | — | N | Substantive MINI and Rolls-Royce section text; partial evidence for the brand list. |
| 37033 | 69 | Y | `answer_bearing` | N | — | — | N | MINI and Rolls-Royce delivery table; partial evidence for the brand list. |
| 37039 | 71 | Y | `answer_bearing` | N | — | — | N | BMW Motorrad segment introduction; partial evidence, but embedding is NULL. |
| 37040 | 71 | Y | `answer_bearing` | N | — | — | N | BMW Motorrad market launches/deliveries text; partial evidence for business/brand coverage. |
| 37041 | 71 | Y | `answer_bearing` | N | — | — | N | BMW motorcycle deliveries / markets table; partial evidence for the Motorrad business. |
| 37047 | 71 | Y | `answer_bearing` | N | — | — | N | BMW Motorrad new-model discussion; partial evidence for the Motorrad business. |
| 37106 | 82 | Y | `weak_keyword_match` | N | — | — | N | False positive from 'Minimum Safeguards' matching the loose '%MINI%' term. |
| 37291 | 123 | Y | `weak_keyword_match` | N | — | — | N | Automobile/motorcycle market forecast context, not BMW Group portfolio evidence. |
| 37300 | 126 | Y | `weak_keyword_match` | N | — | — | N | Internal-control/risk-management section, not portfolio evidence. |
| 37418 | 146 | Y | `weak_keyword_match` | N | — | — | N | Internal-control section, not portfolio evidence. |
| 37998 | 321 | Y | `toc_or_index_only` | N | — | — | N | TCFD/NFE index link list, not substantive portfolio evidence. |
| 38050 | 338 | Y | `weak_keyword_match` | N | — | — | N | Contact/web-link page lists brand websites but does not answer the full p04 request. |

## Answer-Bearing Summary

- answer-bearing original matches: 6
- embedded answer-bearing matches: 6
- answer-bearing matches in retrieval candidates: 0
- answer-bearing matches in final context: 0
- answer-bearing NULL-embedding chunk IDs: none

## Expanded Matcher

The expanded terms include `Konzernmarken`, `Markenportfolio`, `Marken des BMW Group`, `BMW Group im Überblick`, segment headings, and BMW Motorrad / MINI / Rolls-Royce table phrases.

- expanded matches: 35
- expanded matches in retrieval candidates: 36880, 38005
- expanded matches in final context: 36880, 38005

| chunk | page | emb | in_cand | rank | in_ctx | preview |
|---:|---:|:---:|:---:|---:|:---:|---|
| 36756 | 2 | Y | N | — | N | 2 BMW Group Bericht 2023 ��������������������� ����������������������������� ���������������� ���������������������������������� ����������������� ��������������������� ����� ����� BMW GROUP BERICHT 2023 �������������������������������������������������������� |
| 36757 | 2 | Y | N | — | N | AUSLIEFERUNGEN IM SEGMENT AUTOMOBILE ������������ 2.554.183 |
| 36758 | 2 | Y | N | — | N | ���������������������������� AUSLIEFERUNGEN IM SEGMENT MOTORRÄDER ������������ 209.066 ���������������������������� |
| 36778 | 10 | Y | N | — | N | WEITERE FINANZIELLE KENNZAHLEN ���������� ����� ����� ����� ����� 2023 ����������������� Gesamtinvestitionen1 ������ ������ ������ ������� ������� ���� Abschreibungen ������ ������ ������ ������ ������ ���� Free Cashflow Segment Automobile ������ ������ ������ |
| 36880 | 37 | Y | Y | 6 | Y | 37 ����������������������� ���������������������� Zusammengefasster Lagebericht ����������������� ����������������������������������� ������������������ ���������������������� 38 Die BMW Group im Überblick 78 EU­Taxonomie 123 Prognose 126 Angemessenheit und Wi |
| 36883 | 38 | Y | N | — | N | DIE BMW GROUP IM ÜBERBLICK ORGANISATION UND GESCHÄFTSMODELL SEGMENTE ���������������������������������������������������������� ���� ������������� ����� ������� ����� ������ ������������ ���� ���������������������������������������������������������� ��������� |
| 36885 | 38 | Y | N | — | N | Segment Automobile ������������������������������������������������������������ ���������������������������������������������������������� ���������������������������������������������������������� ����������������������������������������������������������� �� |
| 36887 | 39 | Y | N | — | N | ���������������������������������������������������������� ���������������������������� ����������������� ���������������� ������������������������������������������������������������ ������������������������������������������������������������� �������������� |
| 36888 | 39 | Y | N | — | N | ����� ��� ����������������� ��������� ���� ���� ������ ����� ������������������������������������������������������������� �������������� ���� ������������� ��������� ������� ���� ������ ����������������������������������������������������������� ���� �������� |
| 36937 | 47 | Y | N | — | N | — ������������������������������������������ Segment Automobile — �������������������������������������������� �������������������������������� — ���������������������������������������� — ������������������������������ — �������������������������������������� |
| 36956 | 49 | Y | N | — | N | Operative Steuerung auf Segmentebene ������������������������������������������������������������ �������������������������������������������������������������� ������������������������������������������������������������� ������������������������������������� |
| 36959 | 49 | Y | N | — | N | RoCE Automobile bzw. Motorräder = |
| 36961 | 49 | Y | N | — | N | Durchschnittlich eingesetztes Kapital Return on Capital Employed (Segment Automobile) ��������������������������� ��������� ������������������������������������� ��������� �������������������������� ���� 2023 ���� 2023 ���� 2023 ���� ���������� ������ ������ � |
| 36962 | 50 | Y | N | — | N | Segment Motorräder ����������������������������������������������������������� ������������������������������������������������������������ ������������������������������������������������������������� ����������������������������������������������� ���������� |
| 36997 | 60 | Y | N | — | N | BMW Group Überblick Zahlungsströme ���������� 2023 ����� ������������ ��������������������������������������������������������������� ������� ������� ������� ������������������������������������������������������������� ������� ������� ������� ���������������� |
| 36998 | 61 | Y | N | — | N | ���������������������������������������������������������� ���������������������������� ������������� �������� ���� ���� ��������� ��� ������������������� ������������������������������������������������������������������� ������������������������������������� |
| 36999 | 61 | Y | N | — | N | ���������� 2023 ����� ������������ ��������������������������������������������� ������� ������� ���� ���������������������������������� ������ ������ ������� �������������������������������������� ������ ������� ������� Finanzvermögen 19.778 27.337 – 7.559 �� |
| 37015 | 66 | Y | N | — | N | � SEGMENT AUTOMOBILE BMW Group schließt Berichtsjahr mit neuem Absatzhöchstwert ab ��������������������������������������������������������������� ������������������������������������������������������������� ��������������������������������������������������� |
| 37032 | 69 | Y | N | — | N | MINI setzt Fahrspaß unter Strom ������������������������������������������������������������ ��������������������������������������������������������� ������������� ������ ������ ������������������� ���� ����������� �������������������������������������������� |
| 37033 | 69 | Y | N | — | N | ���������������������� ���������������������������� �������� �������� ����� ����� ������������ ������� ������� ����� ����� ������������� ������� ������� ������ ���� ���������������� ������� ������� ���� ����� MINI gesamt 295.358 292.922 0,8 100,0 ������������� |
| 37035 | 70 | Y | N | — | N | Ertragslage Segment Automobile entspricht Erwartungen ������������������������������������������������������������� ��� ������������������� ��� ���������� ����� ���� ����������� ����� ������������������������������������������������������������� �������������� |
| 37039 | 71 | Y | N | — | N | SEGMENT MOTORRÄDER BMW Motorrad mit Absatzbestwert im Jubiläumsjahr ���������������������������������������������������������� �������������������������������������������������������������� �������������������������������������������������������������� ������� |
| 37040 | 71 | Y | N | — | N | ��������������������������������������������������������������� ������ ���� ������ �������� ������������� ������������������ ��� ���������������������������������������������� ������������� ������������������������������������ Markteinführungen im Berichtsjahr |
| 37041 | 71 | Y | N | — | N | ������������������������ �������������������������� Auslieferungen von BMW Motorrädern ����������������� 175,2 169,3 194,3 202,9 209,1 � ���� ���� ���� ���� ���� BMW Group – Größte Motorradmärkte 2023 ��������������� |
| 37047 | 71 | Y | N | — | N | ����� ��� ������� ��� Neuvorstellungen bei BMW Motorrad Das Berichtsjahr 2023 war für BMW Motorrad von den Feierlichkeiten zum Jubiläumsjahr geprägt. Es wurden gleich vier neue Modelle und vier Modellüberarbeitungen für die Markteinführungen im Jahr 2024 vorge |
| 37048 | 72 | Y | N | — | N | Ertragslage Segment Motorräder erfüllt Prognoseziel ����������������������������������������������������������� ����������������������������������������������������������� ����������������������������������� ���������������������������������������������������� |
| 37049 | 72 | Y | N | — | N | Ergebnis im Finanzdienstleistungsgeschäft unter Vorjahr ����������������������������������������������������������� �������������������������������������������������������������� ������������������������������������������������������������ �������������������� |
| 37050 | 72 | Y | N | — | N | Neugeschäft mit Endkunden auf Vorjahresniveau ������������������������������������������������������������ ����������������� ���� ���������� ���������� ���������������� ����������������������������������������������������������� ����������������� ������������� |
| 37052 | 73 | Y | N | — | N | Vertragsbestand mit Endkunden im Segment Finanzdienstleistungen 2023 ����������������� 5.486 5.592 5.577 5.210 4.952 � ���� ���� ���� ���� ���� Vertragsbestand mit Endkunden im Segment Finanzdienstleistungen 2023 ������������������ |
| 37114 | 83 | Y | N | — | N | — Wirtschaftstätigkeit CCM 6.5 „Beförderung mit Motorrädern, Personenkraftwagen und leichten Nutzfahrzeugen“ ���������������������������������������������������������� ��������������������������������������������������������� ���������������������������������� |
| 37437 | 152 | Y | N | — | N | � � � � � � ������������������������������������������������������������� � � � GEWINN­UND­VERLUST­RECHNUNG DES KONZERNS UND DER SEGMENTE � Automobile Motorräder Finanzdienstleistungen Sonstige Gesellschaften Konsolidierungen � � � � �������������������������� |
| 37441 | 154 | Y | N | — | N | BILANZ DES KONZERNS UND DER SEGMENTE ZUM 31. DEZEMBER 2023 � Automobile Motorräder Finanzdienstleistungen Sonstige Gesellschaften Konsolidierungen � � � ������������������������������� � ������������������������������� � ������������������������������� � ����� |
| 37444 | 155 | Y | N | — | N | BILANZ DES KONZERNS UND DER SEGMENTE ZUM 31. DEZEMBER 2023 � Automobile Motorräder Finanzdienstleistungen Sonstige Gesellschaften Konsolidierungen � � � ������������������������������� � ������������������������������� � ������������������������������� � ����� |
| 38005 | 325 | Y | Y | 2 | Y | ������������ NFE­INDEX Pflichtangabe gemäß § 289 c­e HGB BMW Group Bericht 2023 ���������������� ↗ Organisation und Geschäftsmodell ↗ Die BMW Group Strategie ����������������������������������� ↗ Die BMW Group Strategie — ↗ Eckpfeiler der Strategie — ↗ Leistun |
| 38040 | 334 | Y | N | — | N | Free Cashflow (Segment Automobile) ������������������������������������������������������������� ����������������������������������������������������������������� ����� ���� ���� ���������������������� ������������ ��������������� ����������������������������� |

## Neighbor Pages Checked

Same-page chunks were checked for the overview/segment pages and the strongest brand-evidence pages: 37, 38, 39, 66, 69, 70, 71, 72.

| chunk | page | emb | error | chars | preview |
|---:|---:|:---:|---|---:|---|
| 36880 | 37 | Y |  | 1474 | 37 ����������������������� ���������������������� Zusammengefasster Lagebericht ����������������� ����������������������������������� ������������������ ���������������������� 38 Die BMW Group im Überblick 78 EU­Taxonomie 123 Prognose 126 Angemessenheit und Wi |
| 36881 | 37 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 235 | ����������������� ��� ���������������������������������������������������������� ���� ���������������������������������������������������� ��� ����������������� ���� ���������������������������������� ��� ������������������������������ |
| 36882 | 37 | Y |  | 150 | ���� ������������������������������������������ ��� ������������������������� ���� ������������������������������ 02 ZUSAMMENGEFASSTER LAGEBERICHT |
| 38062 | 37 | Y |  | 0 |  |
| 36883 | 38 | Y |  | 884 | DIE BMW GROUP IM ÜBERBLICK ORGANISATION UND GESCHÄFTSMODELL SEGMENTE ���������������������������������������������������������� ���� ������������� ����� ������� ����� ������ ������������ ���� ���������������������������������������������������������� ��������� |
| 36884 | 38 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 739 | ������������������������������������������������������������� ����������������������������������������������������������� ����� �������� ���� ���� ������ �������� ������ ���� ���� ��� ���������������������������������������������������������������� ����������� |
| 36885 | 38 | Y |  | 784 | Segment Automobile ������������������������������������������������������������ ���������������������������������������������������������� ���������������������������������������������������������� ����������������������������������������������������������� �� |
| 36886 | 38 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 161 | � � � �������������������������������������������������������� ��������������������������������������������������������������� ��������������������������������� |
| 38064 | 38 | Y |  | 0 |  |
| 38065 | 38 | Y |  | 0 |  |
| 38068 | 38 | Y |  | 0 |  |
| 36887 | 39 | Y |  | 1053 | ���������������������������������������������������������� ���������������������������� ����������������� ���������������� ������������������������������������������������������������ ������������������������������������������������������������� �������������� |
| 36888 | 39 | Y |  | 1417 | ����� ��� ����������������� ��������� ���� ���� ������ ����� ������������������������������������������������������������� �������������� ���� ������������� ��������� ������� ���� ������ ����������������������������������������������������������� ���� �������� |
| 36889 | 39 | Y |  | 255 | STANDORTE Globaler Überblick ������������������������������������������������������������� ����������������������������������������������������������� ������������������������������������������������������������ ������� � ������������������������������ |
| 38067 | 39 | Y |  | 0 |  |
| 37013 | 66 | Y |  | 30 | GESCHÄFTSVERLAUF UND SEGMENTE |
| 37014 | 66 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 1 | � |
| 37015 | 66 | Y |  | 1380 | � SEGMENT AUTOMOBILE BMW Group schließt Berichtsjahr mit neuem Absatzhöchstwert ab ��������������������������������������������������������������� ������������������������������������������������������������� ��������������������������������������������������� |
| 37016 | 66 | Y |  | 1491 | Hohe Dynamik bei Elektromobilität ���� ������������ ����������������� ���� ���������������� ���� ���� ����������������������������������������������������������� ���������������������������������������������������������������� ���� ��������������� ������������ |
| 37017 | 66 | Y |  | 926 | BMW Group ­ Auslieferungen elektrifizierter Modelle ������������ ����� ������������� 2023 ����� ���� �������� �������� ����� ���� �������� �������� ����� ����� ������� ������� ���� ������������ ���� �� �� ����� �������� �������� ������ ���� �������� �������� � |
| 38070 | 66 | Y |  | 0 |  |
| 38072 | 66 | Y |  | 0 |  |
| 37032 | 69 | Y |  | 1494 | MINI setzt Fahrspaß unter Strom ������������������������������������������������������������ ��������������������������������������������������������� ������������� ������ ������ ������������������� ���� ����������� �������������������������������������������� |
| 37033 | 69 | Y |  | 1169 | ���������������������� ���������������������������� �������� �������� ����� ����� ������������ ������� ������� ����� ����� ������������� ������� ������� ������ ���� ���������������� ������� ������� ���� ����� MINI gesamt 295.358 292.922 0,8 100,0 ������������� |
| 37034 | 69 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 40 | � � � � ������������������������������� |
| 38077 | 69 | Y |  | 0 |  |
| 38078 | 69 | Y |  | 0 |  |
| 38079 | 69 | Y |  | 0 |  |
| 37035 | 70 | Y |  | 1142 | Ertragslage Segment Automobile entspricht Erwartungen ������������������������������������������������������������� ��� ������������������� ��� ���������� ����� ���� ����������� ����� ������������������������������������������������������������� �������������� |
| 37036 | 70 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 1413 | ���������������������������������������������������������� ������ ������ �������� ����� ������ ���� ���������� ������� ����������������������������������������������������������� �������������������������������������������������������������� ������������������ |
| 37037 | 70 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 1443 | ������������������������������������������������������������ ������������������������������������������������������������� �������������������������������������������������������������� ������������������������������������������ ������������������������������� |
| 37038 | 70 | Y |  | 1008 | ����������������������������������������������������������� �������������������������������������������������������������� ������������������������������������������������������������� ������������������������������������������������������������� ������������� |
| 37039 | 71 | Y |  | 1263 | SEGMENT MOTORRÄDER BMW Motorrad mit Absatzbestwert im Jubiläumsjahr ���������������������������������������������������������� �������������������������������������������������������������� �������������������������������������������������������������� ������� |
| 37040 | 71 | Y |  | 1488 | ��������������������������������������������������������������� ������ ���� ������ �������� ������������� ������������������ ��� ���������������������������������������������� ������������� ������������������������������������ Markteinführungen im Berichtsjahr |
| 37041 | 71 | Y |  | 216 | ������������������������ �������������������������� Auslieferungen von BMW Motorrädern ����������������� 175,2 169,3 194,3 202,9 209,1 � ���� ���� ���� ���� ���� BMW Group – Größte Motorradmärkte 2023 ��������������� |
| 37042 | 71 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 16 | ����������� ���� |
| 37043 | 71 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 15 | ���������� ���� |
| 37044 | 71 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 11 | ������� ��� |
| 37045 | 71 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 22 | �������� ���� ��� ��� |
| 37046 | 71 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 13 | ��������� ��� |
| 37047 | 71 | Y |  | 1341 | ����� ��� ������� ��� Neuvorstellungen bei BMW Motorrad Das Berichtsjahr 2023 war für BMW Motorrad von den Feierlichkeiten zum Jubiläumsjahr geprägt. Es wurden gleich vier neue Modelle und vier Modellüberarbeitungen für die Markteinführungen im Jahr 2024 vorge |
| 38080 | 71 | Y |  | 0 |  |
| 38081 | 71 | Y |  | 0 |  |
| 37048 | 72 | Y |  | 1244 | Ertragslage Segment Motorräder erfüllt Prognoseziel ����������������������������������������������������������� ����������������������������������������������������������� ����������������������������������� ���������������������������������������������������� |
| 37049 | 72 | Y |  | 1479 | Ergebnis im Finanzdienstleistungsgeschäft unter Vorjahr ����������������������������������������������������������� �������������������������������������������������������������� ������������������������������������������������������������ �������������������� |
| 37050 | 72 | Y |  | 1485 | Neugeschäft mit Endkunden auf Vorjahresniveau ������������������������������������������������������������ ����������������� ���� ���������� ���������� ���������������� ����������������������������������������������������������� ����������������� ������������� |
| 37051 | 72 | N | ValueError: empty or gibberish embedding input after ingest cleanup | 147 | ���������������������������������������������������������������������������������������������� ���������������������������������������������������� |

## Recommendation

Do not start Phase 1 from the mechanical generation label. The p04 answer-bearing chunks are embedded but still do not rank into retrieval candidates, while the wider BMW NULL-embedding cohort is mostly extraction/noise. After explicit approval, choose between retrieval/evidence-quality work and BMW extraction cleanup based on the post-backfill evidence and p07 trace.

Stop here for Phase 0. No backfill, retrieval change, metadata prefix, hybrid search, reranker, or generation prompt change was executed by this audit.
