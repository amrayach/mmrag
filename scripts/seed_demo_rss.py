#!/usr/bin/env python3
"""Seed 6 synthetic German RSS articles into the RAG database.

Run INSIDE rag-gateway container:
    docker compose cp scripts/seed_demo_rss.py ammer_mmragv2_rag_gateway:/tmp/
    docker compose exec -T rag-gateway python3 /tmp/seed_demo_rss.py
"""

import hashlib
import json
import os
import uuid

import httpx
import psycopg
from psycopg.rows import dict_row

# ---------------------------------------------------------------------------
# Config (reads from container env vars set by docker-compose)
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DATABASE_HOST", "postgres")
DB_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DB_NAME = os.getenv("DATABASE_NAME", "rag")
DB_USER = os.getenv("DATABASE_USER", "rag_user")
DB_PASS = os.getenv("DATABASE_PASSWORD", "")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = "bge-m3"


def get_rss_doc_id(url: str) -> uuid.UUID:
    """Match services/rss-ingest/app/db.py:get_rss_doc_id exactly."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mmrag:rss:{url}")


def embed_text(client: httpx.Client, text: str) -> list[float]:
    """Get bge-m3 embedding (1024d) via Ollama."""
    resp = client.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": [text]},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


# ---------------------------------------------------------------------------
# Article data (verbatim from spec)
# ---------------------------------------------------------------------------
ARTICLES = [
    {
        "url": "https://www.spiegel.de/wirtschaft/ki-boom-deutsche-industrie-robotik-2025",
        "feed_name": "spiegel",
        "feed_url": "https://www.spiegel.de/schlagzeilen/index.rss",
        "title": "KI-Boom: Deutsche Industrie investiert Rekordsummen in Robotik und Automatisierung",
        "published_at": "2025-03-10",
        "text": (
            "Die deutsche KI- und Robotikbranche verzeichnet ein Rekordjahr. Laut dem Branchenverband "
            "VDMA stiegen die Investitionen in industrielle KI-Lösungen im vergangenen Jahr um 35 Prozent "
            "auf 4,2 Milliarden Euro. Besonders gefragt sind Lösungen für die visuelle Qualitätskontrolle, "
            "vorausschauende Wartung und autonome Logistik.\n\n"
            "\"Deutschland hat die Chance, zum weltweit führenden Standort für industrielle KI zu werden\", "
            "sagte VDMA-Präsident Karl Haeusgen auf der Hannover Messe. Treiber des Wachstums sind vor "
            "allem mittelständische Unternehmen, die zunehmend auf KI-gestützte Automatisierung setzen, "
            "um dem Fachkräftemangel entgegenzuwirken. Allein im Bereich kollaborativer Robotik wuchs "
            "der Markt um 28 Prozent.\n\n"
            "Experten erwarten, dass der deutsche KI-Markt bis 2028 ein Volumen von 12 Milliarden Euro "
            "erreichen wird. Die Bundesregierung unterstützt den Trend mit dem erweiterten KI-Aktionsplan, "
            "der zusätzliche Forschungsmittel von 800 Millionen Euro vorsieht. Auch die EU fördert "
            "industrielle KI-Projekte im Rahmen von Horizon Europe mit Schwerpunkt auf vertrauenswürdige "
            "und nachhaltige Anwendungen."
        ),
    },
    {
        "url": "https://www.heise.de/news/eu-ki-verordnung-ai-act-compliance-industrie-2025",
        "feed_name": "heise",
        "feed_url": "https://www.heise.de/rss/heise-atom.xml",
        "title": "AI Act in Kraft: Was die EU-KI-Verordnung für Industrieunternehmen bedeutet",
        "published_at": "2025-03-12",
        "text": (
            "Mit dem vollständigen Inkrafttreten der EU-KI-Verordnung (AI Act) stehen deutsche "
            "Unternehmen vor neuen Compliance-Anforderungen. Hochrisiko-KI-Systeme in der industriellen "
            "Fertigung, medizinischen Diagnostik und Personalauswahl müssen bis Mitte 2025 zertifiziert "
            "werden. Der Verband Bitkom schätzt die Implementierungskosten für mittelständische Unternehmen "
            "auf durchschnittlich 250.000 bis 500.000 Euro.\n\n"
            "Besonders betroffen sind Hersteller von KI-gestützten Qualitätsprüfungssystemen und autonomen "
            "Robotern, die unter die Kategorie \"Hochrisiko\" fallen. Gleichzeitig sehen Experten den AI Act "
            "als Wettbewerbsvorteil: \"Europäische KI-Produkte mit CE-Zertifizierung werden international "
            "als Qualitätssiegel anerkannt\", erklärte Prof. Dr. Sandra Wachter von der Universität Oxford.\n\n"
            "Deutsche Unternehmen, die frühzeitig in verantwortungsvolle KI investiert haben, seien gut "
            "positioniert. Der TÜV Rheinland hat bereits über 200 Zertifizierungsanträge erhalten. Die "
            "Industrie- und Handelskammern bieten bundesweit Informationsveranstaltungen zum AI Act an."
        ),
    },
    {
        "url": "https://www.tagesschau.de/wirtschaft/fachkraeftemangel-tech-ki-branche-2025",
        "feed_name": "tagesschau",
        "feed_url": "https://www.tagesschau.de/xml/rss2",
        "title": "148.000 offene IT-Stellen: Fachkräftemangel erreicht neuen Höchststand",
        "published_at": "2025-03-14",
        "text": (
            "Der Fachkräftemangel in der deutschen IT- und Technologiebranche hat einen neuen Höchststand "
            "erreicht. Nach Angaben des Instituts der deutschen Wirtschaft (IW) fehlen aktuell rund "
            "148.000 IT-Fachkräfte — ein Anstieg von 12 Prozent gegenüber dem Vorjahr. Besonders "
            "betroffen sind die Bereiche KI-Entwicklung, Robotik-Programmierung und Cybersicherheit.\n\n"
            "Die durchschnittliche Vakanzzeit für IT-Stellen liegt mittlerweile bei 7,3 Monaten. "
            "Unternehmen reagieren zunehmend mit Automatisierung: \"Wo wir keine Fachkräfte finden, "
            "setzen wir auf Mensch-Roboter-Kollaboration und KI-gestützte Prozesse\", berichtet ein "
            "Sprecher eines Münchner Automatisierungsspezialisten. Auch Weiterbildungsprogramme werden "
            "massiv ausgebaut — die Branche investierte 2024 insgesamt 3,8 Milliarden Euro in die "
            "Qualifizierung bestehender Mitarbeiter.\n\n"
            "Die Bundesagentur für Arbeit hat die Einwanderungsregeln für IT-Fachkräfte aus Drittstaaten "
            "gelockert, was zu einem Anstieg der Visa-Anträge um 45 Prozent führte."
        ),
    },
    {
        "url": "https://www.faz.net/aktuell/wirtschaft/nachhaltigkeit-tech-csrd-berichtspflicht-2025",
        "feed_name": "faz",
        "feed_url": "https://www.faz.net/rss/aktuell",
        "title": "CSRD-Berichtspflicht: Tech-Unternehmen müssen Nachhaltigkeit offenlegen",
        "published_at": "2025-03-08",
        "text": (
            "Die Tech-Industrie steht unter wachsendem Druck, ihre CO₂-Bilanz transparent offenzulegen. "
            "Der neue EU-Standard CSRD (Corporate Sustainability Reporting Directive) verpflichtet ab "
            "2025 alle großen Technologieunternehmen zur detaillierten Nachhaltigkeitsberichterstattung. "
            "\"Die Zeiten des Greenwashings sind vorbei\", sagt Dr. Elena Fischer vom Wuppertal Institut.\n\n"
            "Vorreiter in der Branche setzen bereits auf Science Based Targets (SBTi) und streben "
            "Klimaneutralität bis 2030 an. Der Energieverbrauch von Rechenzentren und KI-Training "
            "bleibt jedoch ein Kernproblem. Deutsche Tech-Unternehmen begegnen dem mit "
            "energieeffizienter Edge-KI, die Berechnungen lokal statt in der Cloud durchführt, sowie "
            "langfristigen Ökostrom-Verträgen.\n\n"
            "Die Kreislaufwirtschaft gewinnt ebenfalls an Bedeutung — mehrere Robotik-Hersteller "
            "berichten Recyclingquoten von über 75 Prozent bei Produktionsabfällen. Der "
            "Branchendurchschnitt liegt allerdings erst bei 52 Prozent. Analysten erwarten, dass "
            "nachhaltige Unternehmen mittelfristig besseren Zugang zu Kapital und Fördermitteln erhalten."
        ),
    },
    {
        "url": "https://www.zdfheute.de/wirtschaft/techvision-ag-hermes-award-hannover-messe-2025",
        "feed_name": "zdf",
        "feed_url": "https://www.zdf.de/rss/zdf/nachrichten",
        "title": "Hannover Messe: TechVision AG erhält HERMES Award für VisionAI-Plattform",
        "published_at": "2025-03-15",
        "text": (
            "Das Münchner KI-Unternehmen TechVision AG hat auf der Hannover Messe 2025 den renommierten "
            "HERMES Award für industrielle Innovation gewonnen. Ausgezeichnet wurde das Unternehmen für "
            "seine VisionAI-Plattform, die mittels fortschrittlicher Bildverarbeitung und Edge Computing "
            "Qualitätsprüfungen in Echtzeit durchführt.\n\n"
            "Die Jury lobte besonders die Kombination aus hoher Erkennungsgenauigkeit von 99,7 Prozent "
            "und dem energieeffizienten Betrieb auf lokaler Hardware. \"TechVision zeigt, wie industrielle "
            "KI gleichzeitig leistungsstark und nachhaltig sein kann\", begründete Jury-Vorsitzende "
            "Prof. Dr. Claudia Eckert die Entscheidung.\n\n"
            "CEO Dr. Markus Weber nahm den Preis entgegen und kündigte die Eröffnung eines neuen "
            "KI-Forschungszentrums in München-Garching für das zweite Quartal 2026 an. Das Zentrum "
            "soll in Kooperation mit dem Fraunhofer IPA betrieben werden und rund 150 Forschungsstellen "
            "schaffen. TechVision beschäftigt aktuell 3.200 Mitarbeiter und erzielte im Geschäftsjahr "
            "2025 einen Umsatz von 847 Millionen Euro."
        ),
    },
    {
        "url": "https://www.dw.com/de/industrieautomatisierung-cobots-amr-robotik-wachstum-2025",
        "feed_name": "dw",
        "feed_url": "https://rss.dw.com/xml/rss-de-all",
        "title": "Deutsche Robotik-Branche wächst zweistellig — Cobots erobern den Mittelstand",
        "published_at": "2025-03-11",
        "text": (
            "Die deutsche Robotik- und Automatisierungsbranche hat 2024 erneut zweistellig zugelegt. "
            "Nach vorläufigen Zahlen des Branchenverbands IFR stieg der Absatz von Industrierobotern "
            "in Deutschland um 18 Prozent auf 28.300 Einheiten. Damit bleibt Deutschland der größte "
            "Robotermarkt in Europa und weltweit auf Platz fünf.\n\n"
            "Besonders stark wuchs das Segment der kollaborativen Roboter (Cobots), die ohne Schutzzaun "
            "direkt neben menschlichen Arbeitern eingesetzt werden. Ihr Marktanteil stieg von 11 auf "
            "17 Prozent. \"Cobots demokratisieren die Automatisierung — auch kleine und mittlere "
            "Unternehmen können jetzt profitieren\", sagte IFR-Generalsekretärin Marina Bill.\n\n"
            "Treiber der Nachfrage sind neben dem Fachkräftemangel auch steigende Qualitätsanforderungen "
            "und der Druck zur Rückverlagerung von Produktion nach Europa (Reshoring). Die "
            "Logistikbranche holt mit einem Wachstum von 42 Prozent bei autonomen mobilen Robotern (AMR) "
            "für Lagerhaltung und innerbetrieblichen Transport stark auf."
        ),
    },
]


def main():
    print("=" * 60)
    print("Seeding 6 synthetic RSS articles into RAG database")
    print("=" * 60)
    print(f"DB: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"Ollama: {OLLAMA_URL}")
    print()

    # Warm up bge-m3
    print("Warming up bge-m3...")
    http = httpx.Client()
    embed_text(http, "Warmup test.")
    print("Model ready.\n")

    conn = psycopg.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
        row_factory=dict_row,
    )

    seeded = 0
    skipped = 0

    for i, article in enumerate(ARTICLES, 1):
        url = article["url"]
        title = article["title"]
        text = article["text"]
        doc_id = get_rss_doc_id(url)
        sha = hashlib.sha256(text.encode()).hexdigest()

        print(f"[{i}/6] {article['feed_name']}: {title[:60]}...")

        with conn.cursor() as cur:
            # Check if already seeded
            cur.execute("SELECT 1 FROM rag_docs WHERE doc_id = %s", (doc_id,))
            if cur.fetchone():
                print(f"  -> Skipped (already exists)")
                skipped += 1
                continue

            # Embed the article text
            emb = embed_text(http, text)
            print(f"  -> Embedded ({len(emb)}d)")

            # Insert doc
            cur.execute(
                """INSERT INTO rag_docs (doc_id, filename, sha256, lang, pages, created_at, updated_at)
                   VALUES (%s, %s, %s, 'de', 1, now(), now())
                   ON CONFLICT (doc_id) DO UPDATE
                   SET sha256 = EXCLUDED.sha256, updated_at = now()""",
                (doc_id, url, sha),
            )

            # Insert text chunk with metadata
            meta = {
                "source": "rss_article",
                "content_type": "rss_article",
                "feed_name": article["feed_name"],
                "feed_url": article["feed_url"],
                "title": title,
                "author": "",
                "published_at": article["published_at"],
                "url": url,
                "chunk_index": 0,
            }
            cur.execute(
                """INSERT INTO rag_chunks (doc_id, chunk_type, page, content_text, embedding, meta)
                   VALUES (%s, 'text', 1, %s, %s::vector, %s)""",
                (doc_id, text, str(emb), json.dumps(meta)),
            )

        conn.commit()
        seeded += 1
        print(f"  -> Committed")

    http.close()
    conn.close()

    print(f"\n{'=' * 60}")
    print(f"Done: {seeded} seeded, {skipped} skipped")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
