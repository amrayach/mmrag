# Phase 0.4 — BMW p04 targeted diagnostic

- **Captured at:** 2026-05-06T12:44:58+00:00
- **Resolved expected doc:** `BMWGroup_Bericht2023.pdf`
- **All candidates from prompts.json:** ['BMWGroup_Bericht2023.pdf']
- **doc_id:** `955cd062-4e76-59c4-a28c-c210d70c19df`
- **Search terms:** `['MINI', 'Rolls', 'Rolls-Royce', 'Motorrad', 'Marken', 'Konzernmarken', 'BMW Group brands']`
- **Matching chunks:** 17
- **Retrieval attempted:** True
- **Retrieval evidence available:** True

## Classification

**`generation`**

1 brand-list chunk(s) reached final context for p04. The list-completeness failure is downstream of retrieval — likely a prompt or generator concern. Out of scope for retrieval upgrades.

## Matching brand-list chunks

| chunk_id | page | type | has_emb | embedding_error | heading_path | element_type | chars | in_cand | rank | score | in_ctx | order |
|---:|---:|---|:---:|---|---|---|---:|:---:|---:|---:|:---:|---:|
| 36806 | 16 | text | Y |  | [] | section | 533 | N | — | — | N | — |
| 36846 | 27 | text | Y |  | [] | section | 205 | N | — | — | N | — |
| 36854 | 31 | text | Y |  | [] | section | 1486 | N | — | — | N | — |
| 36880 | 37 | text | Y |  | [] | section | 1474 | Y | 6 | 0.6926 | Y | 6 |
| 36980 | 55 | text | Y |  | [] | section | 1488 | N | — | — | N | — |
| 37032 | 69 | text | Y |  | [] | section | 1494 | N | — | — | N | — |
| 37033 | 69 | text | Y |  | [] | section | 1169 | N | — | — | N | — |
| 37039 | 71 | text | N | ollama_embed_failed | [] | section | 1263 | N | — | — | N | — |
| 37040 | 71 | text | Y |  | [] | section | 1488 | N | — | — | N | — |
| 37041 | 71 | text | Y |  | [] | section | 216 | N | — | — | N | — |
| 37047 | 71 | text | Y |  | [] | section | 1341 | N | — | — | N | — |
| 37106 | 82 | text | Y |  | [] | section | 1499 | N | — | — | N | — |
| 37291 | 123 | text | Y |  | [] | section | 1279 | N | — | — | N | — |
| 37300 | 126 | text | Y |  | [] | section | 1460 | N | — | — | N | — |
| 37418 | 146 | text | Y |  | [] | section | 1256 | N | — | — | N | — |
| 37998 | 321 | text | Y |  | [] | section | 1020 | N | — | — | N | — |
| 38050 | 338 | text | Y |  | [] | section | 915 | N | — | — | N | — |

### Content previews

- **chunk 36806** (page 16):
  > ����Nominierungsausschuss �������������������������������������������������������������� ��������������������������������������������������������������������������������������� �������������������������������������������������������������������������������������� ������������������������������������
- **chunk 36846** (page 27):
  > Von links nach rechts: Walter Mertl Mitglied des Vorstands der BMW AG,  Finanzen Oliver Zipse Vorsitzender des Vorstands der BMW AG Jochen Goller Mitglied des Vorstands der BMW AG,  Kunde, Marken, Vertrieb
- **chunk 36854** (page 31):
  > � ANDRÉ MANDL1 �������� �������������������������������������������������� ���������������������� ��������������������������������������������������� ����������������������� � � DR. DOMINIQUE MOHABEER1 �������� ������������������������������������������������� ���������������������� ����������������
- **chunk 36880** (page 37):
  > 37 ����������������������� ���������������������� Zusammengefasster Lagebericht ����������������� ����������������������������������� ������������������ ���������������������� 38 Die BMW Group im Überblick 78 EU­Taxonomie 123 Prognose 126 Angemessenheit und Wirksamkeit des Internen Kontrollsystems 9
- **chunk 36980** (page 55):
  > Internationale Automobilmärkte solide im Plus  �������������������������������������������������������������� ������������������������������������������������������������� �������������������������������������������������������������� ��������������������  Internationale Automobilmärkte  Veränderung
- **chunk 37032** (page 69):
  > MINI setzt Fahrspaß unter Strom ������������������������������������������������������������ ��������������������������������������������������������� ������������� ������ ������ ������������������� ���� ����������� �������������������������������������������������������������� ������������ ��������
- **chunk 37033** (page 69):
  > ���������������������� ���������������������������� �������� �������� ����� ����� ������������ ������� ������� ����� ����� ������������� ������� ������� ������ ���� ���������������� ������� ������� ���� ����� MINI gesamt  295.358  292.922  0,8  100,0  ������������������������������������������������
- **chunk 37039** (page 71):
  > SEGMENT MOTORRÄDER  BMW Motorrad mit Absatzbestwert im Jubiläumsjahr ���������������������������������������������������������� �������������������������������������������������������������� �������������������������������������������������������������� ����������������������������������������������
- **chunk 37040** (page 71):
  > ��������������������������������������������������������������� ������ ���� ������ �������� ������������� ������������������ ��� ���������������������������������������������� ������������� ������������������������������������ Markteinführungen im Berichtsjahr ���������������������������������������
- **chunk 37041** (page 71):
  > ������������������������ �������������������������� Auslieferungen von BMW Motorrädern ����������������� 175,2 169,3 194,3 202,9 209,1 � ���� ���� ���� ���� ���� BMW Group – Größte Motorradmärkte 2023 ���������������
- **chunk 37047** (page 71):
  > ����� ���  ������� ���  Neuvorstellungen bei BMW Motorrad Das Berichtsjahr 2023 war für BMW Motorrad von den Feierlichkeiten zum Jubiläumsjahr geprägt. Es wurden gleich vier neue  Modelle und vier Modellüberarbeitungen für die Markteinführungen im Jahr 2024 vorgestellt. Im Rahmen der BMW Motorrad  D
- **chunk 37106** (page 82):
  > ���� ������������������� ���� ����������� �� ������� ���� ���� ��������������������� ���� ���� ��������� ��� ������ ���� ���� ����� ������������������������������������������������������������� ��������������������������������������������������������������� ������� Mindestschutzverfahren („Minimum S
- **chunk 37291** (page 123):
  > ���������������������������������������������������������������� �������������������������������������������������������������� ������������������������������������������������������������� ������������������������������������������������������������ ������������  Internationale Automobilmärkte  ���
- **chunk 37300** (page 126):
  > ������������������������������������������������������������������������������������������  ANGEMESSENHEIT UND WIRKSAMKEIT  DES INTERNEN KONTROLLSYSTEMS UND  RISIKOMANAGEMENTSYSTEMS*  ���������������������������������������������������������� ���������������������������������������������������������
- **chunk 37418** (page 146):
  > � � � � �������������������������� � � � � � � � �  INTERNES KONTROLLSYSTEM  ���� �������� ���������������� ������ ���� ������������ ���� ��������� �������������������������������������������������������������� ������������������������������������������������������������ ����������������������������
- **chunk 37998** (page 321):
  > TCFD­INDEX  [[  Governance  Offenlegung der Governance des Unternehmens im Hinblick auf klimabedingte Risiken und Chancen.  Erforderliche TCFD­Informationen  BMW Group Bericht 2023  CDP­Fragebogen 2023  ↗ Die BMW Group Strategie  ���������������������������������������������������� �����������������
- **chunk 38050** (page 338):
  > 338  ����������������������� ���������������������� ������������������������������ ����������������� ����������������������������������� ������������������ Weitere Informationen  ����������  KONTAKT  WIRTSCHAFTSPRESSE  �������� � ����������������� � �����������������  �������� � �����������������  �

## Production retrieval summary

- text candidates returned: 6, image candidates returned: 2
- final context chunks: 8 (chars≈6675)
- sources emitted: ['[BMWGroup Bericht2023 — Seite 4](https://spark-e010.tail907fce.ts.net:8454/pdf/BMWGroup_Bericht2023.pdf#page=4)', '[BMWGroup Bericht2023 — Seite 325](https://spark-e010.tail907fce.ts.net:8454/pdf/BMWGroup_Bericht2023.pdf#page=325)', '[BMWGroup Bericht2023 — Seite 307](https://spark-e010.tail907fce.ts.net:8454/pdf/BMWGroup_Bericht2023.pdf#page=307)', '[BMWGroup Bericht2023 — Seite 1](https://spark-e010.tail907fce.ts.net:8454/pdf/BMWGroup_Bericht2023.pdf#page=1)', '[BMWGroup Bericht2023 — Seite 8](https://spark-e010.tail907fce.ts.net:8454/pdf/BMWGroup_Bericht2023.pdf#page=8)', '[BMWGroup Bericht2023 — Seite 37](https://spark-e010.tail907fce.ts.net:8454/pdf/BMWGroup_Bericht2023.pdf#page=37)']

### Top text candidates

| rank | chunk_id | page | filename | score | preview |
|---:|---:|---:|---|---:|---|
| 0 | 36761 | 4 | BMWGroup_Bericht2023.pdf | 0.7123 | 4  BMW Group Bericht 2023  ���������������������� ������������������������������ |
| 1 | 38005 | 325 | BMWGroup_Bericht2023.pdf | 0.7101 | ������������  NFE­INDEX  Pflichtangabe gemäß § 289 c­e HGB  BMW Group Bericht 20 |
| 2 | 37968 | 307 | BMWGroup_Bericht2023.pdf | 0.6941 | 307  ����������������������� ���������������������� ���������������������������� |
| 3 | 36755 | 1 | BMWGroup_Bericht2023.pdf | 0.6933 | DRIVING THE NEXT ERA  BMW GROUP BERICHT 2023  Auf dem Weg zur elektrischen und d |
| 4 | 36774 | 8 | BMWGroup_Bericht2023.pdf | 0.6926 | 8  ����������������������� An unsere Stakeholder  ������������������������������ |
| 5 | 36880 | 37 | BMWGroup_Bericht2023.pdf | 0.6926 | 37 ����������������������� ���������������������� Zusammengefasster Lagebericht  |
