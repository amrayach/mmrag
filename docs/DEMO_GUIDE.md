# MMRAG Demo-Leitfaden

Dieser Leitfaden beschreibt Schritt für Schritt, wie die MMRAG-Demo (Multimodal Retrieval-Augmented Generation) vorgeführt wird. Er ist so geschrieben, dass auch Personen, die das System nicht selbst aufgebaut haben, die Demo durchführen können.

---

## Inhaltsverzeichnis

1. [Systemübersicht](#1-systemübersicht)
2. [Vor der Demo: Checkliste](#2-vor-der-demo-checkliste)
3. [Demo Teil 1: PDF-Dokument hochladen](#3-demo-teil-1-pdf-dokument-hochladen)
4. [Demo Teil 2: Chat-Abfrage mit Dokumenten](#4-demo-teil-2-chat-abfrage-mit-dokumenten)
5. [Demo Teil 3: RSS-Feeds & Multi-Source](#5-demo-teil-3-rss-feeds--multi-source)
6. [Demo Teil 4: Unter der Haube (Architektur)](#6-demo-teil-4-unter-der-haube-architektur)
7. [Troubleshooting](#7-troubleshooting)
8. [Demo zurücksetzen](#8-demo-zurücksetzen)

---

## 1. Systemübersicht

### Was ist MMRAG?

MMRAG ist ein **lokal gehostetes KI-System**, das Dokumente (PDFs, RSS-Feeds) versteht und Fragen dazu beantworten kann — inklusive Bilder und Quellenangaben. Alle Daten bleiben auf dem eigenen Server, nichts geht in die Cloud.

### Kernfähigkeiten

- **PDF-Analyse**: PDFs hochladen, Text und Bilder werden automatisch extrahiert und verstanden
- **RSS-Integration**: Nachrichtenartikel werden automatisch eingelesen und durchsuchbar
- **Multimodale Antworten**: Antworten enthalten Text, Quellenangaben und relevante Bilder
- **Deutsche Sprache**: Das System ist für deutsche Texte optimiert
- **Vektorsuche**: Semantische Suche — findet Inhalte nach Bedeutung, nicht nur nach Stichwörtern

### Architektur (vereinfacht)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  OpenWebUI   │     │ FileBrowser  │     │   Adminer    │
│  (Chat-UI)   │     │ (Upload-UI)  │     │  (Datenbank) │
└──────┬───────┘     └──────┬───────┘     └──────────────┘
       │                    │
       ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ RAG-Gateway  │     │  PDF-Ingest  │     │  RSS-Ingest  │
│ (Streaming)  │     │ (Verarbeitung)│     │  (Feeds)     │
└──┬───────┬───┘     └──────┬───────┘     └──────┬───────┘
   │       │                │                    │
   ▼       ▼                ▼                    ▼
┌──────┐ ┌──────┐    ┌──────────────┐     ┌──────────────┐
│ n8n  │ │Ollama│    │  PostgreSQL  │◄───►│   Ollama     │
│(Ctx) │ │(LLM) │    │  (pgvector)  │     │  (GPU)       │
└──────┘ └──────┘    └──────────────┘     └──────────────┘
```

> **Hinweis:** RAG-Gateway holt Kontext von n8n und streamt dann direkt von Ollama — Token für Token in Echtzeit.

### Datenfluss: Vom Dokument zur Antwort

```
PDF hochladen ──► Text + Bilder extrahieren ──► In Stücke teilen (Chunks)
                                                        │
                                                        ▼
                                              Vektoren berechnen (Embeddings)
                                                        │
                                                        ▼
                                              In Datenbank speichern
                                                        │
                                                        ▼
Frage stellen ──► Frage als Vektor ──► Ähnlichste Chunks finden ──► Antwort generieren
                                                                         │
                                                                         ▼
                                                              Antwort + Bilder + Quellen
```

### Zugangs-URLs (Tailscale)

| Dienst | URL | Zweck |
|--------|-----|-------|
| OpenWebUI | https://spark-e010.tail907fce.ts.net:8451 | Chat-Oberfläche |
| FileBrowser | https://spark-e010.tail907fce.ts.net:8452 | Dateien hochladen |
| n8n | https://spark-e010.tail907fce.ts.net:8450 | Workflow-Editor |
| Adminer | https://spark-e010.tail907fce.ts.net:8453 | Datenbank-Ansicht |
| Assets | https://spark-e010.tail907fce.ts.net:8454 | Extrahierte Bilder |

> **Hinweis:** Alle URLs sind nur über Tailscale erreichbar (kein öffentlicher Zugang).

---

## 2. Vor der Demo: Checkliste

Diese Schritte **15 Minuten vor der Demo** durchführen.

### 2.1 Automatischen Check ausführen

Am Server per SSH einloggen und das Readiness-Skript starten:

```bash
cd /srv/projects/ammer/mmrag-n8n-demo-v2
bash scripts/demo_readiness_check.sh
```

Das Skript prüft 15 Punkte:
- Alle 10 Container laufen
- Ollama-Modelle geladen
- n8n-Webhooks erreichbar
- n8n-Kontext-Pipeline funktioniert
- SSE-Streaming vom RAG-Gateway
- Demo-Modus aktiv (rss-ingest gestoppt)
- Tailscale-Serve-Regeln aktiv
- Tailnet-URLs erreichbar

**Erwartetes Ergebnis:** `DEMO READY` am Ende der Ausgabe.

### 2.2 Falls der Check fehlschlägt

| Problem | Lösung |
|---------|--------|
| Container nicht gestartet | `cd /srv/projects/ammer/mmrag-n8n-demo-v2 && docker compose up -d` |
| Ollama-Modelle fehlen | `bash scripts/setup_models.sh` (dauert ca. 5-10 Min.) |
| Webhooks nicht erreichbar | In n8n einloggen, Workflows prüfen und aktivieren |
| Tailscale-URLs nicht erreichbar | `tailscale serve status` prüfen, ggf. Regeln neu setzen |

### 2.3 Demo-Modus aktivieren (empfohlen)

Der Demo-Modus stoppt den RSS-Ingest (verhindert GPU-Konkurrenz), wärmt alle Modelle auf und zeigt ein Status-Dashboard:

```bash
make demo-start
```

Nach der Demo den normalen Betrieb wiederherstellen:

```bash
make demo-stop
```

### 2.4 Demo-Dokument vorbereiten

Ein passendes PDF bereitlegen (z.B. eine Bedienungsanleitung, einen Bericht oder ein Datenblatt). Ideal:
- **2-10 Seiten** (kurze Verarbeitungszeit)
- **Enthält Text und Bilder** (zeigt multimodale Fähigkeiten)
- **Deutschsprachig** (optimierte Verarbeitung)
- **Konkreter Inhalt** (ermöglicht gezielte Fragen)

### 2.5 Frische Demo gewünscht?

Falls keine Altdaten in der Demo gezeigt werden sollen:

```bash
bash reset_demo.sh
```

> **Achtung:** Löscht alle eingelesenen Dokumente und Chunks. Nicht rückgängig zu machen.

---

## 3. Demo Teil 1: PDF-Dokument hochladen

> **Moderationshinweis:** *„Wir zeigen jetzt, wie ein Dokument in das System aufgenommen wird. Vom Upload bis zur Verfügbarkeit im Chat dauert es typischerweise 1-2 Minuten."*

### Schritt 1: FileBrowser öffnen

1. Im Browser öffnen: **https://spark-e010.tail907fce.ts.net:8452**
2. Einloggen (Zugangsdaten beim Administrator erfragen)
3. In den Ordner `inbox/` navigieren

### Schritt 2: PDF hochladen

1. Auf **Upload** klicken (oben rechts)
2. Das vorbereitete PDF auswählen
3. Warten, bis der Upload abgeschlossen ist
4. Die Datei erscheint im `inbox/`-Ordner

> **Moderationshinweis:** *„Das System prüft alle 2 Minuten automatisch, ob neue Dateien im Eingangsordner liegen. Wir können die Verarbeitung aber auch sofort auslösen."*

### Schritt 3: Verarbeitung sofort auslösen

**Option A — Über n8n (visuell, für die Demo empfohlen):**

1. n8n öffnen: **https://spark-e010.tail907fce.ts.net:8450**
2. Einloggen (siehe CREDENTIALS.md — nicht in Git verfolgt)
3. Workflow **„Ingestion Factory"** öffnen
4. Oben auf **„Test Workflow"** klicken
5. Die Ausführung verfolgen — jeder Knoten wird grün, wenn erfolgreich

**Option B — Per Kommandozeile (schneller):**

```bash
make ingest
```

### Schritt 4: Verarbeitung prüfen

Die Ausgabe zeigt:

```json
{
  "status": "ok",
  "processed_count": 1,
  "processed": [
    {
      "filename": "beispiel.pdf",
      "pages": 5,
      "text_chunks": 12,
      "image_chunks": 3
    }
  ]
}
```

> **Moderationshinweis:** *„Das System hat das PDF Seite für Seite analysiert: 12 Textabschnitte und 3 Bilder wurden extrahiert, in Vektoren umgewandelt und in der Datenbank gespeichert. Das Dokument ist jetzt durchsuchbar."*

### Schritt 5 (optional): In der Datenbank zeigen

1. Adminer öffnen: **https://spark-e010.tail907fce.ts.net:8453**
2. Einloggen: System `PostgreSQL`, Server `postgres`, Benutzer und Passwort aus `.env`
3. Datenbank `rag` → Tabelle `rag_chunks` → **Daten anzeigen**
4. Die neuen Einträge mit `doc_id`, `chunk_type`, `content_text` und `embedding` zeigen

> **Moderationshinweis:** *„Hier sehen wir die Rohdaten: Jeder Textabschnitt hat einen 768-dimensionalen Vektor bekommen. Bilder wurden vom Vision-Modell beschrieben und ebenfalls als Vektoren gespeichert."*

---

## 4. Demo Teil 2: Chat-Abfrage mit Dokumenten

> **Moderationshinweis:** *„Jetzt zeigen wir das Herzstück: Wir stellen Fragen an das System und bekommen Antworten basierend auf den eingelesenen Dokumenten."*

### Schritt 1: OpenWebUI öffnen

1. Im Browser öffnen: **https://spark-e010.tail907fce.ts.net:8451**
2. Einloggen oder neuen Account erstellen
3. Einen neuen Chat starten

### Schritt 2: Einfache Textfrage stellen

Eine Frage eingeben, die sich direkt auf das hochgeladene PDF bezieht. Beispiele:

- *„Was sind die wichtigsten Punkte in dem Dokument?"*
- *„Fasse das Dokument in 3 Sätzen zusammen."*
- *„Welche technischen Spezifikationen werden genannt?"*

**Erwartetes Ergebnis:**
- Eine deutschsprachige Antwort
- Quellenangaben am Ende (Dateiname, Seitenzahl)

> **Moderationshinweis:** *„Das System hat die Frage als Vektor kodiert, die ähnlichsten Textabschnitte in der Datenbank gefunden und daraus eine Antwort generiert. Beachten Sie die Quellenangaben — man kann nachvollziehen, woher die Information stammt."*

### Schritt 3: Frage mit Bildinhalt stellen

Eine Frage stellen, die sich auf Bilder im Dokument bezieht:

- *„Welche Abbildungen enthält das Dokument?"*
- *„Was zeigt das Schaubild auf Seite 2?"*
- *„Beschreibe die Grafiken im Dokument."*

**Erwartetes Ergebnis:**
- Antwort mit Bezug auf Bildinhalte
- Eingebettete Bilder direkt im Chat (als Vorschau)
- Bildbeschreibungen, die vom Vision-Modell generiert wurden

> **Moderationshinweis:** *„Das System zeigt nicht nur Text, sondern auch die relevanten Bilder aus dem Dokument. Diese wurden beim Einlesen vom Vision-Modell analysiert und beschrieben, sodass sie jetzt semantisch durchsuchbar sind."*

### Schritt 4: Folgefrage stellen

Ohne neuen Kontext eine Folgefrage stellen:

- *„Kannst du das genauer erklären?"*
- *„Was bedeutet das konkret?"*

> **Moderationshinweis:** *„Das System erkennt Folgefragen und bezieht den vorherigen Kontext automatisch ein. Es schreibt die Frage intern um, damit die Vektorsuche weiterhin relevante Ergebnisse liefert."*

### Schritt 5 (optional): Dokumentfilter verwenden

Mit dem `@`-Prefix gezielt in einem Dokument suchen:

- *„@beispiel.pdf Was steht auf Seite 3?"*

> **Moderationshinweis:** *„Mit dem @-Prefix kann man die Suche auf ein bestimmtes Dokument einschränken. Praktisch, wenn viele Dokumente im System sind."*

---

## 5. Demo Teil 3: RSS-Feeds & Multi-Source

> **Moderationshinweis:** *„Das System kann nicht nur PDFs verarbeiten, sondern auch Nachrichtenartikel aus RSS-Feeds automatisch einlesen. Wir zeigen, wie verschiedene Quellen in einer Antwort kombiniert werden."*

### Schritt 1: RSS-Status prüfen

Falls bereits RSS-Feeds eingelesen wurden, direkt zu Schritt 3 springen.

Andernfalls RSS-Ingestion auslösen:

**Option A — Über n8n:**
1. n8n öffnen
2. Workflow **„RSS Ingestion"** öffnen
3. **„Test Workflow"** klicken
4. Warten (kann je nach Anzahl der Artikel 1-5 Minuten dauern)

**Option B — Per Kommandozeile:**

```bash
make rss-ingest
```

### Schritt 2: Ergebnis prüfen

```json
{
  "status": "ok",
  "feeds_processed": 2,
  "articles_ingested": 15,
  "chunks_created": 90
}
```

> **Moderationshinweis:** *„15 Nachrichtenartikel aus 2 RSS-Feeds wurden automatisch heruntergeladen, in Textabschnitte zerlegt und als Vektoren gespeichert."*

### Schritt 3: Multi-Source-Abfrage

In OpenWebUI eine Frage stellen, die sowohl PDF- als auch RSS-Inhalte betreffen könnte:

- *„Was gibt es Neues zum Thema [Thema aus dem PDF oder den Feeds]?"*
- *„Vergleiche die Informationen aus verschiedenen Quellen."*

**Erwartetes Ergebnis:**
- Antwort kombiniert Informationen aus PDFs und RSS-Artikeln
- Quellenangaben zeigen verschiedene Herkunft (Dateiname vs. Feed-Name/URL)

> **Moderationshinweis:** *„Hier sehen wir, wie das System verschiedene Quellen — ein hochgeladenes PDF und Nachrichtenartikel — in einer einzigen Antwort zusammenführt. Die Quellenangaben zeigen genau, welche Information woher stammt."*

---

## 6. Demo Teil 4: Unter der Haube (Architektur)

> **Moderationshinweis:** *„Für die technisch Interessierten schauen wir jetzt hinter die Kulissen: Wie funktioniert das System intern?"*

### 6.1 n8n-Workflows zeigen

1. n8n öffnen: **https://spark-e010.tail907fce.ts.net:8450**
2. Einloggen (siehe CREDENTIALS.md — nicht in Git verfolgt)

**Chat Brain Workflow zeigen:**
1. Workflow **„Chat Brain"** öffnen
2. Den Datenfluss erklären: `Webhook → Abfrage extrahieren → Embedding → Vektor-Literal → Vektorsuche → Kontext aufbauen`
3. Erklären: „n8n liefert den Kontext — die eigentliche Antwort wird vom RAG-Gateway direkt von Ollama gestreamt, Token für Token."

> **Moderationshinweis:** *„Der Workflow hat 6 Knoten: Er empfängt die Frage, berechnet den Suchvektor, findet die relevanten Textabschnitte und baut den Kontext auf. Die Antwortgenerierung erfolgt dann direkt — Token werden in Echtzeit an den Browser gestreamt."*

**Ingestion Factory zeigen:**
1. Workflow **„Ingestion Factory"** öffnen
2. Erklären: Zeitgesteuert (alle 2 Min.) + manuell auslösbar, verarbeitet je 1 PDF

> **Moderationshinweis:** *„Die Ingestion läuft automatisch im Hintergrund. Neue PDFs im Eingangsordner werden erkannt und verarbeitet. Der Workflow ruft unseren Python-Dienst auf, der die eigentliche Textextraktion und KI-Verarbeitung übernimmt."*

### 6.2 Datenbank-Struktur zeigen

1. Adminer öffnen: **https://spark-e010.tail907fce.ts.net:8453**
2. Datenbank `rag` auswählen

**Tabellen erklären:**

| Tabelle | Inhalt |
|---------|--------|
| `rag_docs` | Dokumenten-Metadaten (Dateiname, SHA256-Hash, Sprache, Seitenzahl) |
| `rag_chunks` | Einzelne Textabschnitte + Bilder mit 768-dim. Vektoren |

3. Eine SQL-Abfrage ausführen (im SQL-Feld von Adminer):

```sql
SELECT chunk_type, COUNT(*),
       AVG(LENGTH(content_text)) AS avg_text_length
FROM rag_chunks
GROUP BY chunk_type;
```

> **Moderationshinweis:** *„In der Datenbank sehen wir, wie viele Text- und Bild-Chunks gespeichert sind. Jeder Chunk hat einen 768-dimensionalen Vektor, der seinen semantischen Inhalt repräsentiert. Die Datenbank nutzt pgvector für die Ähnlichkeitssuche."*

### 6.3 Lokale KI-Modelle zeigen

Drei Modelle laufen lokal auf der GPU:

| Modell | Aufgabe | Größe |
|--------|---------|-------|
| `qwen2.5:7b-instruct` | Textgenerierung (Antworten) | ~4.7 GB |
| `nomic-embed-text` | Vektorisierung (Embeddings) | ~274 MB |
| `qwen2.5vl:7b` | Bilderkennung (Vision) | ~4.7 GB |

> **Moderationshinweis:** *„Alle drei KI-Modelle laufen lokal auf der GPU — kein API-Call an OpenAI oder andere Cloud-Dienste. Die Daten verlassen den Server nicht."*

### 6.4 Asset-Galerie zeigen (optional)

1. Asset-Galerie öffnen: **https://spark-e010.tail907fce.ts.net:8454**
2. Die extrahierten Bilder durchstöbern — die Galerie zeigt alle Bilder als Kacheln mit Ordner-Filter
3. Auf ein Bild klicken für die Vollansicht (Lightbox)

> **Moderationshinweis:** *„Hier sieht man alle extrahierten Bilder aus PDFs und RSS-Feeds in einer übersichtlichen Galerie. Man kann nach Ordner filtern und Bilder in der Vollansicht betrachten. Diese werden in den Chat-Antworten als Vorschau angezeigt."*

---

## 7. Troubleshooting

### Chat antwortet nicht oder sehr langsam

| Symptom | Ursache | Lösung |
|---------|---------|--------|
| Keine Antwort | Ollama läuft nicht | `docker compose ps ollama` prüfen, ggf. `docker compose start ollama` |
| Timeout (504) | Modell wird geladen | 30 Sek. warten, erneut versuchen. Vorher aufwärmen: `bash scripts/prewarm.sh` |
| Leere Antwort | Keine Dokumente eingelesen | Zuerst ein PDF hochladen und verarbeiten |
| Fehler 503 | n8n nicht erreichbar | `docker compose ps n8n` prüfen, Workflows aktiviert? |

### PDF wird nicht verarbeitet

| Symptom | Ursache | Lösung |
|---------|---------|--------|
| Status `busy` | Andere Verarbeitung läuft | 2 Minuten warten, erneut versuchen |
| Status `skipped` | PDF bereits verarbeitet | Anderes PDF verwenden oder Demo zurücksetzen |
| Status `error` | Datei beschädigt oder zu groß | Maximale Größe: 100 MB. Datei prüfen. |

### Bilder werden nicht angezeigt

| Symptom | Ursache | Lösung |
|---------|---------|--------|
| Defektes Bild-Icon | Assets-Server nicht erreichbar | `docker compose ps assets` prüfen |
| Keine Bilder in Antwort | PDF enthält keine Bilder | Anderes PDF mit Bildern verwenden |

### Allgemeine Diagnose

```bash
# Status aller Container
docker compose ps

# Logs eines bestimmten Dienstes (z.B. rag-gateway)
docker compose logs --tail=20 rag-gateway

# Vollständiger Health-Check
bash scripts/health_check.sh

# Demo-Readiness prüfen
bash scripts/demo_readiness_check.sh
```

---

## 8. Demo zurücksetzen

### Kompletter Reset (alle Dokumente löschen)

```bash
cd /srv/projects/ammer/mmrag-n8n-demo-v2
bash reset_demo.sh
```

Dieses Skript:
- Leert die Tabellen `rag_docs` und `rag_chunks`
- Löscht verarbeitete PDFs aus `data/processed/`
- Löscht extrahierte Bilder aus `data/assets/`

### Nur RSS-Daten zurücksetzen (PDFs behalten)

```bash
bash reset_demo.sh --rss-only
```

### Nach dem Reset

1. Ggf. Demo-PDF erneut in `data/inbox/` kopieren
2. Verarbeitung auslösen: `make ingest`
3. Prüfen, ob Chat wieder antwortet

---

## Anhang: Zugangsdaten

Siehe **CREDENTIALS.md** (nicht in Git verfolgt) für alle Service-Logins und Passwörter.

---

## Anhang: Nützliche Befehle

```bash
# Stack starten
make up

# Stack stoppen
make down

# Logs verfolgen
make logs

# Health-Check
make health

# Ollama aufwärmen
make prewarm

# Demo-Modus aktivieren (stoppt RSS, wärmt auf)
make demo-start

# Demo-Modus deaktivieren
make demo-stop

# PDF-Verarbeitung auslösen
make ingest

# RSS-Feeds einlesen
make rss-ingest

# Test-Abfrage senden
make test-rag

# Demo komplett zurücksetzen
make reset
```
