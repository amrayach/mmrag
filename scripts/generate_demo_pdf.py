#!/usr/bin/env python3
"""Generate TechVision AG Jahresbericht 2025 — synthetic demo PDF.

Run inside a temporary venv with matplotlib + reportlab:
    python3 -m venv /tmp/pdf_gen_venv
    /tmp/pdf_gen_venv/bin/pip install matplotlib reportlab
    /tmp/pdf_gen_venv/bin/python scripts/generate_demo_pdf.py
"""

import os
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Wedge, Circle
import numpy as np

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak,
    Table, TableStyle, KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = SCRIPT_DIR / "demo_assets"
OUTPUT_PDF = SCRIPT_DIR / "TechVision_AG_Jahresbericht_2025.pdf"
ASSETS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Corporate design
# ---------------------------------------------------------------------------
BLUE = "#1a5276"
GREEN = "#27ae60"
DARK = "#2c3e50"
LIGHT = "#ecf0f1"
ORANGE = "#e67e22"
RED = "#c0392b"
PURPLE = "#8e44ad"

CHART_DPI = 150
CHART_W, CHART_H = 10, 7.5  # inches → 1500x1125 px at 150 dpi

# ---------------------------------------------------------------------------
# Font setup
# ---------------------------------------------------------------------------
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

pdfmetrics.registerFont(TTFont("DejaVuSans", FONT_PATH))
pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", FONT_BOLD_PATH))

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False


def _save_chart(fig, name: str) -> str:
    """Save matplotlib figure as JPEG in demo_assets/. Returns path."""
    path = str(ASSETS_DIR / name)
    fig.savefig(path, format="jpeg", dpi=CHART_DPI,
                pil_kwargs={"quality": 95},
                bbox_inches="tight", facecolor="white", edgecolor="none")
    plt.close(fig)
    size = os.path.getsize(path)
    print(f"  Chart: {name} ({size:,} bytes)")
    return path


# ---------------------------------------------------------------------------
# Chart 1: Megatrend strategy diagram (circular)
# ---------------------------------------------------------------------------
def chart_strategy_diagram() -> str:
    fig, ax = plt.subplots(figsize=(CHART_W, CHART_H))
    ax.set_xlim(-1.6, 1.6)
    ax.set_ylim(-1.6, 1.6)
    ax.set_aspect("equal")
    ax.axis("off")

    # Central circle
    center = Circle((0, 0), 0.45, fc=BLUE, ec="white", lw=3, zorder=5)
    ax.add_patch(center)
    ax.text(0, 0.08, "TechVision", ha="center", va="center",
            fontsize=14, fontweight="bold", color="white", zorder=6)
    ax.text(0, -0.12, "Strategie", ha="center", va="center",
            fontsize=12, color="white", zorder=6)

    # 5 segments around center
    labels = [
        ("KI & Maschinelles\nLernen", BLUE),
        ("Industrie 4.0 &\nSmart Factory", DARK),
        ("Nachhaltigkeit &\nDekarbonisierung", GREEN),
        ("Fachkräftemangel &\nDemografie", ORANGE),
        ("Globalisierung\n& Resilienz", PURPLE),
    ]

    for i, (label, color) in enumerate(labels):
        angle = 90 + i * 72  # degrees, starting at top
        rad = math.radians(angle)
        x = 1.05 * math.cos(rad)
        y = 1.05 * math.sin(rad)

        hex_patch = mpatches.RegularPolygon(
            (x, y), numVertices=6, radius=0.42, orientation=0,
            fc=color, ec="white", lw=2, alpha=0.9, zorder=3,
        )
        ax.add_patch(hex_patch)
        ax.text(x, y, label, ha="center", va="center",
                fontsize=9, fontweight="bold", color="white", zorder=4)

        # Connection line to center
        cx = 0.48 * math.cos(rad)
        cy = 0.48 * math.sin(rad)
        ix = 0.63 * math.cos(rad)
        iy = 0.63 * math.sin(rad)
        ax.plot([cx, ix], [cy, iy], color=color, lw=2.5, zorder=2)

    ax.set_title("Strategische Megatrends 2025", fontsize=18,
                 fontweight="bold", color=DARK, pad=20)
    return _save_chart(fig, "strategy_diagram.jpg")


# ---------------------------------------------------------------------------
# Chart 2: Robot arm technical diagram
# ---------------------------------------------------------------------------
def chart_robot_diagram() -> str:
    fig, ax = plt.subplots(figsize=(CHART_W, CHART_H))
    ax.set_xlim(-1, 11)
    ax.set_ylim(-1, 9)
    ax.axis("off")

    # Base platform
    base = FancyBboxPatch((3.5, 0), 3, 1.2, boxstyle="round,pad=0.1",
                          fc=DARK, ec="white", lw=2)
    ax.add_patch(base)
    ax.text(5, 0.6, "Basis & Steuerung", ha="center", va="center",
            fontsize=10, color="white", fontweight="bold")

    # Joint 1
    j1 = Circle((5, 1.8), 0.35, fc=BLUE, ec="white", lw=2, zorder=3)
    ax.add_patch(j1)
    ax.text(5, 1.8, "J1", ha="center", va="center", color="white",
            fontsize=9, fontweight="bold", zorder=4)

    # Arm segment 1
    arm1 = FancyBboxPatch((4.6, 2.2), 0.8, 2.0, boxstyle="round,pad=0.05",
                          fc=BLUE, ec="white", lw=2, alpha=0.8)
    ax.add_patch(arm1)

    # Joint 2
    j2 = Circle((5, 4.5), 0.35, fc=BLUE, ec="white", lw=2, zorder=3)
    ax.add_patch(j2)
    ax.text(5, 4.5, "J2", ha="center", va="center", color="white",
            fontsize=9, fontweight="bold", zorder=4)

    # Arm segment 2 (angled)
    ax.plot([5, 7], [4.8, 6.5], color=BLUE, lw=18, solid_capstyle="round", alpha=0.8)

    # Joint 3
    j3 = Circle((7, 6.5), 0.35, fc=BLUE, ec="white", lw=2, zorder=3)
    ax.add_patch(j3)
    ax.text(7, 6.5, "J3", ha="center", va="center", color="white",
            fontsize=9, fontweight="bold", zorder=4)

    # Forearm
    ax.plot([7, 9], [6.5, 7.5], color=BLUE, lw=14, solid_capstyle="round", alpha=0.8)

    # Gripper
    ax.plot([9, 9.5], [7.5, 8.2], color=GREEN, lw=6, solid_capstyle="round")
    ax.plot([9, 9.5], [7.5, 6.8], color=GREEN, lw=6, solid_capstyle="round")
    ax.plot([9.5, 10], [8.2, 8.0], color=GREEN, lw=4, solid_capstyle="round")
    ax.plot([9.5, 10], [6.8, 7.0], color=GREEN, lw=4, solid_capstyle="round")

    # Labels with arrows
    labels = [
        (1.5, 0.6, "Basis", 3.4, 0.6),
        (1.0, 3.0, "6-Achs-Gelenke", 4.6, 2.5),
        (1.5, 5.5, "Sensoren", 4.7, 4.5),
        (8.5, 5.0, "Präzision:\n0,02 mm", 7.3, 6.2),
        (9.5, 5.5, "Greifer", 9.2, 7.0),
    ]
    for lx, ly, text, ax_, ay_ in labels:
        ax.annotate(text, xy=(ax_, ay_), xytext=(lx, ly),
                    fontsize=10, fontweight="bold", color=DARK,
                    arrowprops=dict(arrowstyle="->", color=DARK, lw=1.5),
                    bbox=dict(boxstyle="round,pad=0.3", fc=LIGHT, ec=DARK, lw=1))

    ax.set_title("RoboAssist Pro — 6-Achs-Industrieroboter",
                 fontsize=18, fontweight="bold", color=DARK, pad=20)
    ax.text(5, -0.7, "Tragkraft: 15 kg  |  340 Einheiten ausgeliefert 2025",
            ha="center", fontsize=11, color=DARK)
    return _save_chart(fig, "robot_diagram.jpg")


# ---------------------------------------------------------------------------
# Chart 3: VisionAI architecture flow
# ---------------------------------------------------------------------------
def chart_visionai_flow() -> str:
    fig, ax = plt.subplots(figsize=(CHART_W, CHART_H))
    ax.set_xlim(-0.5, 10.5)
    ax.set_ylim(-1, 6)
    ax.axis("off")

    boxes = [
        (0.5, 2, "Kamera\n(Hochgeschw.)", DARK),
        (3, 2, "Edge-KI\n(NVIDIA Jetson)", BLUE),
        (5.5, 2, "Analyse &\nKlassifikation", GREEN),
        (8, 2, "Dashboard\n& Alerts", ORANGE),
    ]

    for x, y, label, color in boxes:
        rect = FancyBboxPatch((x, y), 2.0, 1.8, boxstyle="round,pad=0.15",
                              fc=color, ec="white", lw=2)
        ax.add_patch(rect)
        ax.text(x + 1.0, y + 0.9, label, ha="center", va="center",
                fontsize=11, fontweight="bold", color="white")

    # Arrows between boxes
    for i in range(3):
        x_start = boxes[i][0] + 2.1
        x_end = boxes[i + 1][0] - 0.1
        y_mid = 2.9
        ax.annotate("", xy=(x_end, y_mid), xytext=(x_start, y_mid),
                    arrowprops=dict(arrowstyle="-|>", color=DARK, lw=2.5))

    # Speed labels below arrows
    speeds = ["500 Bilder/s", "< 2 ms Latenz", "Echtzeit"]
    for i, spd in enumerate(speeds):
        x_mid = (boxes[i][0] + 2.0 + boxes[i + 1][0]) / 2
        ax.text(x_mid, 1.5, spd, ha="center", fontsize=9, color=DARK,
                style="italic")

    # Bottom stats
    stats = "Erkennungsgenauigkeit: 99,7%  |  HERMES Award 2025  |  Edge-Inferenz ohne Cloud"
    ax.text(5, 0.3, stats, ha="center", fontsize=11, color=DARK, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc=LIGHT, ec=DARK, lw=1))

    ax.set_title("VisionAI Platform — Architektur", fontsize=18,
                 fontweight="bold", color=DARK, pad=20)
    return _save_chart(fig, "visionai_flow.jpg")


# ---------------------------------------------------------------------------
# Chart 4: Warehouse layout (top-down AMR paths)
# ---------------------------------------------------------------------------
def chart_warehouse_layout() -> str:
    fig, ax = plt.subplots(figsize=(CHART_W, CHART_H))
    ax.set_xlim(-0.5, 12)
    ax.set_ylim(-0.5, 9)
    ax.axis("off")

    # Warehouse walls
    wall = FancyBboxPatch((0, 0), 11.5, 8.5, boxstyle="round,pad=0.1",
                          fc="#f8f9fa", ec=DARK, lw=3, fill=True)
    ax.add_patch(wall)

    # Shelf rows
    for row in range(4):
        y = 1.5 + row * 1.8
        for col in range(4):
            x = 1.0 + col * 2.5
            shelf = FancyBboxPatch((x, y), 1.8, 0.8, boxstyle="round,pad=0.05",
                                  fc=DARK, ec="white", lw=1, alpha=0.6)
            ax.add_patch(shelf)

    # AMR paths (dashed lines)
    # Horizontal lanes
    for y in [1.0, 2.8, 4.6, 6.4, 8.0]:
        ax.plot([0.3, 11.2], [y, y], color=BLUE, lw=1.5, ls="--", alpha=0.4)
    # Vertical lanes
    for x in [0.6, 3.1, 5.6, 8.1, 10.6]:
        ax.plot([x, x], [0.3, 8.2], color=BLUE, lw=1.5, ls="--", alpha=0.4)

    # AMR robots (circles with direction arrows)
    amrs = [(0.6, 1.0, "→"), (3.1, 4.6, "↑"), (8.1, 2.8, "←"),
            (5.6, 8.0, "↓"), (10.6, 6.4, "→")]
    for x, y, arrow in amrs:
        bot = Circle((x, y), 0.25, fc=GREEN, ec="white", lw=2, zorder=5)
        ax.add_patch(bot)
        ax.text(x, y, arrow, ha="center", va="center", fontsize=10,
                color="white", fontweight="bold", zorder=6)

    # Loading dock
    dock = FancyBboxPatch((10, 3.5), 1.3, 1.5, boxstyle="round,pad=0.1",
                          fc=ORANGE, ec="white", lw=2, alpha=0.8)
    ax.add_patch(dock)
    ax.text(10.65, 4.25, "Lade-\nstation", ha="center", va="center",
            fontsize=8, color="white", fontweight="bold")

    # Legend
    legend_items = [
        (GREEN, "AMR-Roboter (5 aktiv)"),
        (DARK, "Regalsysteme"),
        (ORANGE, "Ladestation"),
    ]
    for i, (color, label) in enumerate(legend_items):
        ax.add_patch(FancyBboxPatch((0.5, -0.1 - i * 0.01), 0.3, 0.15,
                                    fc=color, ec="none"))
        # Simple colored dot + text in bottom margin
    ax.text(5.75, -0.3, "■ AMR-Roboter    ■ Regale    ■ Ladestation",
            ha="center", fontsize=10, color=DARK)

    ax.set_title("LogiFlow Autonomous — Lagerlayout mit AMR-Pfaden",
                 fontsize=18, fontweight="bold", color=DARK, pad=20)
    ax.text(5.75, 8.8, "Flottenmanagement: bis zu 200 Roboter  |  45% Effizienzsteigerung",
            ha="center", fontsize=10, color=DARK, style="italic")
    return _save_chart(fig, "warehouse_layout.jpg")


# ---------------------------------------------------------------------------
# Chart 5: Revenue bar chart 2021–2025
# ---------------------------------------------------------------------------
def chart_revenue_bars() -> str:
    fig, ax = plt.subplots(figsize=(CHART_W, CHART_H))

    years = ["2021", "2022", "2023", "2024", "2025"]
    revenue = [320, 410, 520, 689, 847]
    colors = [BLUE] * 4 + [GREEN]

    bars = ax.bar(years, revenue, color=colors, width=0.6, edgecolor="white", lw=2)

    for bar, val in zip(bars, revenue):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 15,
                f"{val}", ha="center", va="bottom", fontsize=14,
                fontweight="bold", color=DARK)

    ax.set_ylabel("Mio. €", fontsize=14, color=DARK)
    ax.set_ylim(0, 1000)
    ax.set_title("Umsatzentwicklung 2021–2025", fontsize=18,
                 fontweight="bold", color=DARK, pad=20)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=12)

    # Growth annotation
    ax.annotate("+23% YoY", xy=(4, 847), xytext=(3.2, 920),
                fontsize=13, fontweight="bold", color=GREEN,
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=2))

    fig.tight_layout()
    return _save_chart(fig, "revenue_bars.jpg")


# ---------------------------------------------------------------------------
# Chart 6: Revenue by segment pie chart
# ---------------------------------------------------------------------------
def chart_revenue_pie() -> str:
    fig, ax = plt.subplots(figsize=(CHART_W, CHART_H))

    segments = ["Robotik\n382 Mio. €", "KI-Software\n296 Mio. €", "Logistik\n169 Mio. €"]
    sizes = [45, 35, 20]
    colors = [BLUE, GREEN, ORANGE]
    explode = (0.03, 0.03, 0.03)

    wedges, texts, autotexts = ax.pie(
        sizes, labels=segments, colors=colors, explode=explode,
        autopct="%1.0f%%", startangle=90, textprops={"fontsize": 13},
        pctdistance=0.6, labeldistance=1.15,
    )
    for at in autotexts:
        at.set_fontsize(15)
        at.set_fontweight("bold")
        at.set_color("white")

    ax.set_title("Umsatz nach Geschäftsbereichen 2025\nGesamt: 847 Mio. €",
                 fontsize=18, fontweight="bold", color=DARK, pad=20)
    return _save_chart(fig, "revenue_pie.jpg")


# ---------------------------------------------------------------------------
# Chart 7: CO₂ emissions line chart
# ---------------------------------------------------------------------------
def chart_co2_line() -> str:
    fig, ax = plt.subplots(figsize=(CHART_W, CHART_H))

    # Actual data
    years_actual = [2020, 2021, 2022, 2023, 2024, 2025]
    co2_actual = [21400, 19200, 17100, 15300, 13800, 12400]

    # Target projections
    years_target = [2025, 2026, 2027, 2028, 2029, 2030]
    co2_target = [12400, 10800, 9200, 7500, 4000, 0]

    ax.plot(years_actual, co2_actual, color=BLUE, lw=3, marker="o",
            markersize=8, label="Ist-Werte", zorder=3)
    ax.plot(years_target, co2_target, color=GREEN, lw=3, ls="--", marker="s",
            markersize=8, label="Zielpfad", zorder=3)

    # Fill areas
    ax.fill_between(years_actual, co2_actual, alpha=0.15, color=BLUE)
    ax.fill_between(years_target, co2_target, alpha=0.1, color=GREEN)

    # Annotations
    ax.annotate("−42% seit 2020", xy=(2025, 12400), xytext=(2022.5, 8000),
                fontsize=12, fontweight="bold", color=BLUE,
                arrowprops=dict(arrowstyle="->", color=BLUE, lw=1.5))
    ax.annotate("Klimaneutral\n2030", xy=(2030, 0), xytext=(2028.5, 4500),
                fontsize=12, fontweight="bold", color=GREEN,
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.5))

    # Format y-axis with dots for thousands
    ax.yaxis.set_major_formatter(plt.FuncFormatter(
        lambda x, p: f"{int(x):,}".replace(",", ".")))

    ax.set_ylabel("CO₂-Emissionen (Tonnen)", fontsize=14, color=DARK)
    ax.set_xlabel("Jahr", fontsize=14, color=DARK)
    ax.set_ylim(-500, 23000)
    ax.set_title("CO₂-Reduktionspfad 2020–2030", fontsize=18,
                 fontweight="bold", color=DARK, pad=20)
    ax.legend(fontsize=13, loc="upper right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=12)
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    return _save_chart(fig, "co2_line.jpg")


# ---------------------------------------------------------------------------
# Chart 8: Technology stack (5 layers)
# ---------------------------------------------------------------------------
def chart_tech_stack() -> str:
    fig, ax = plt.subplots(figsize=(CHART_W, CHART_H))
    ax.set_xlim(-0.5, 10.5)
    ax.set_ylim(-0.5, 9)
    ax.axis("off")

    layers = [
        ("Layer 5: Cloud Management & Analytics", PURPLE, "Monitoring, OTA-Updates, Fleet Management"),
        ("Layer 4: Application Suite", GREEN, "VisionAI  |  RoboAssist  |  LogiFlow"),
        ("Layer 3: AI Framework", BLUE, "PyTorch  |  ONNX Runtime  |  TensorRT"),
        ("Layer 2: TechVision OS", DARK, "Real-time Linux  |  Container Runtime"),
        ("Layer 1: Edge Hardware", "#7f8c8d", "NVIDIA Jetson  |  Custom FPGA"),
    ]

    for i, (label, color, detail) in enumerate(layers):
        y = 0.5 + i * 1.6
        width = 8.5 - i * 0.3
        x = (10 - width) / 2
        rect = FancyBboxPatch((x, y), width, 1.2, boxstyle="round,pad=0.1",
                              fc=color, ec="white", lw=2.5, alpha=0.9)
        ax.add_patch(rect)
        ax.text(5, y + 0.75, label, ha="center", va="center",
                fontsize=12, fontweight="bold", color="white")
        ax.text(5, y + 0.3, detail, ha="center", va="center",
                fontsize=9, color="white", alpha=0.9)

    ax.set_title("TechVision Technologie-Stack", fontsize=18,
                 fontweight="bold", color=DARK, pad=20)
    return _save_chart(fig, "tech_stack.jpg")


# ===========================================================================
# PDF Content (German business text)
# ===========================================================================

TEXT_VORWORT = """\
Sehr geehrte Aktionärinnen und Aktionäre, sehr geehrte Partner und Mitarbeiterinnen und \
Mitarbeiter,

das Geschäftsjahr 2025 markiert einen historischen Meilenstein für die TechVision AG. Mit \
einem Umsatz von 847 Millionen Euro und einem Wachstum von 23 Prozent gegenüber dem Vorjahr \
haben wir nicht nur unsere eigenen ambitionierten Ziele übertroffen, sondern uns auch als \
einer der führenden Innovatoren im Bereich industrieller Künstlicher Intelligenz etabliert.

Besonders stolz bin ich auf drei herausragende Erfolge dieses Jahres: Erstens die Verleihung \
des renommierten HERMES Award auf der Hannover Messe 2025 für unsere VisionAI-Plattform, \
die mit einer Erkennungsgenauigkeit von 99,7 Prozent neue Maßstäbe in der visuellen \
Qualitätsprüfung setzt. Zweitens die Eröffnung unseres Standorts in Shanghai im dritten \
Quartal 2025, mit dem wir unsere Präsenz im asiatischen Wachstumsmarkt nachhaltig stärken. \
Und drittens die Unterzeichnung unserer strategischen Forschungspartnerschaft mit dem \
Fraunhofer IPA, die unsere Position an der Spitze der multimodalen KI-Forschung festigt.

Unsere Belegschaft ist im vergangenen Jahr um 33 Prozent auf 3.200 Mitarbeiterinnen und \
Mitarbeiter gewachsen — ein Zeichen sowohl unserer wirtschaftlichen Dynamik als auch unserer \
Attraktivität als Arbeitgeber in einem von Fachkräftemangel geprägten Markt. Mit \
durchschnittlich 24 Stunden Weiterbildung pro Mitarbeiter pro Jahr investieren wir \
konsequent in die Zukunftsfähigkeit unseres Teams.

Mit Blick auf das Jahr 2026 freue ich mich besonders auf die Eröffnung unseres \
KI-Forschungszentrums in München-Garching im zweiten Quartal, das in enger Kooperation mit \
dem Fraunhofer IPA betrieben wird und rund 150 neue Forschungsstellen schaffen wird. Unsere \
Umsatzprognose für 2026 liegt bei 1,05 bis 1,10 Milliarden Euro — ein weiterer \
Meilenstein auf unserem Weg zum Umsatzziel von 1,5 Milliarden Euro bis 2028.

Ich danke Ihnen für Ihr Vertrauen und Ihre Unterstützung.

Dr. Markus Weber
Vorstandsvorsitzender der TechVision AG"""

TEXT_MEGATREND_1 = """\
<b>1. Künstliche Intelligenz & Maschinelles Lernen</b><br/><br/>\
Die rasante Entwicklung im Bereich Künstliche Intelligenz und Maschinelles Lernen bildet das \
Fundament unserer Unternehmensstrategie. Wir konzentrieren uns auf drei Kernbereiche: \
Edge AI ermöglicht die Verarbeitung komplexer KI-Modelle direkt an der Maschine, ohne \
Abhängigkeit von Cloud-Infrastruktur. Foundation Models für die Industrie adaptieren \
vortrainierte Großmodelle für spezifische Fertigungsaufgaben wie Anomalieerkennung und \
Prozessoptimierung. Predictive Maintenance nutzt multimodale Sensordaten zur Vorhersage \
von Maschinenausfällen mit einer Genauigkeit von über 94 Prozent. Unsere strategische \
Partnerschaft mit dem Fraunhofer IPA für multimodale KI-Forschung stärkt unsere \
Innovationskraft in diesem Bereich nachhaltig und verschafft uns Zugang zu neuesten \
Forschungsergebnissen im Bereich industrieller Bildverarbeitung und Robotersteuerung."""

TEXT_MEGATREND_2 = """\
<b>2. Industrie 4.0 & Smart Factory</b><br/><br/>\
Die vollständig vernetzte Fabrik der Zukunft ist keine Vision mehr, sondern Realität. \
TechVision treibt diese Transformation durch drei Technologiebereiche voran: Digitale \
Zwillinge ermöglichen die virtuelle Abbildung gesamter Produktionslinien in Echtzeit, \
wodurch Optimierungen risikofrei simuliert werden können, bevor sie in der physischen \
Umgebung umgesetzt werden. Unsere Lösungen für vernetzte Produktion integrieren \
Maschinensteuerung, Qualitätssicherung und Logistik in einem durchgängigen Datenstrom. \
Echtzeit-Optimierung durch unsere KI-Algorithmen hat bei einem führenden Automobilhersteller \
eine Effizienzsteigerung von 35 Prozent in der Endmontage erzielt — ein Referenzprojekt, \
das die transformative Kraft unserer Technologie eindrucksvoll demonstriert."""

TEXT_MEGATREND_3 = """\
<b>3. Nachhaltigkeit & Dekarbonisierung</b><br/><br/>\
Green AI ist ein zentraler Bestandteil unserer Nachhaltigkeitsstrategie. Durch den Einsatz \
energieeffizienter Edge-Inferenz statt cloudbasierter Verarbeitung reduzieren wir den \
Energieverbrauch unserer KI-Anwendungen um bis zu 80 Prozent pro Inferenzschritt. Unser \
Konzept der Circular Manufacturing zielt auf eine geschlossene Kreislaufwirtschaft in der \
industriellen Fertigung ab — unsere aktuelle Recyclingquote liegt bei 78 Prozent, mit dem \
ambitionierten Ziel von 90 Prozent bis 2027. Nachhaltigkeit und technologische Innovation \
sind für uns keine Gegensätze, sondern zwei Seiten derselben Medaille: Jede \
Effizienzsteigerung durch KI bedeutet gleichzeitig weniger Ressourcenverbrauch, weniger \
Ausschuss und einen geringeren ökologischen Fußabdruck."""

TEXT_MEGATREND_4 = """\
<b>4. Fachkräftemangel & Demografischer Wandel</b><br/><br/>\
Der anhaltende Fachkräftemangel in der deutschen Industrie — aktuell 148.000 offene \
IT-Stellen — erfordert innovative Lösungsansätze. TechVision begegnet dieser \
Herausforderung auf zwei Ebenen: Technologisch durch Mensch-Roboter-Kollaboration, bei der \
unsere RoboAssist-Systeme repetitive und ergonomisch belastende Tätigkeiten übernehmen und \
so die Produktivität bestehender Teams signifikant steigern. Organisatorisch durch umfassende \
Upskilling-Programme, die unseren Mitarbeiterinnen und Mitarbeitern den Umgang mit \
KI-gestützten Werkzeugen vermitteln. Mit durchschnittlich 24 Stunden Weiterbildung pro \
Mitarbeiter pro Jahr investieren wir deutlich über dem Branchendurchschnitt in die \
Qualifizierung unserer Belegschaft."""

TEXT_MEGATREND_5 = """\
<b>5. Globalisierung & Resilienz</b><br/><br/>\
Die geopolitischen Verwerfungen der letzten Jahre haben die Verletzlichkeit globaler \
Lieferketten offengelegt. TechVision bietet hierzu Lösungen auf mehreren Ebenen: Unsere \
Supply Chain AI analysiert Echtzeit-Daten aus über 200 Quellen, um Lieferkettenrisiken \
frühzeitig zu identifizieren und alternative Beschaffungswege vorzuschlagen. \
Nearshoring-Support durch unsere LogiFlow-Plattform unterstützt Unternehmen bei der \
Rückverlagerung von Produktionskapazitäten nach Europa. Unser geopolitisches Risikomodeling \
bewertet Standortentscheidungen anhand von über 50 makroökonomischen Indikatoren. Die \
Eröffnung unseres Shanghai-Büros folgt einer bewussten China+1-Strategie, die Marktzugang \
mit Risikostreuung verbindet."""

TEXT_PRODUCT_1 = """\
<b>RoboAssist Pro — Kollaborativer Industrieroboter</b><br/><br/>\
Der RoboAssist Pro ist unser Flaggschiff im Bereich der kollaborativen Robotik. Als \
6-Achs-System konzipiert, vereint er industrielle Leistungsfähigkeit mit der Sicherheit, \
die für den Einsatz direkt neben menschlichen Arbeitern erforderlich ist. Mit einer Tragkraft \
von 15 Kilogramm und einer Wiederholgenauigkeit von 0,02 Millimetern erfüllt er selbst \
anspruchsvollste Anforderungen in der Präzisionsmontage.<br/><br/>\
Im Geschäftsjahr 2025 haben wir 340 Einheiten des RoboAssist Pro ausgeliefert — ein Anstieg \
von 42 Prozent gegenüber dem Vorjahr. Die Haupteinsatzgebiete umfassen Montage, Verpackung \
und Qualitätskontrolle, wobei wir zunehmend Nachfrage aus dem Bereich der \
Elektronikfertigung verzeichnen. Durch die intuitive Programmierung mittels Handführung \
können auch Betriebe ohne spezifische Robotik-Expertise den RoboAssist Pro innerhalb \
weniger Stunden in Betrieb nehmen."""

TEXT_PRODUCT_2 = """\
<b>VisionAI Platform — KI-gestützte Qualitätsprüfung</b><br/><br/>\
Die VisionAI Platform ist unsere preisgekrönte Software-Suite für die visuelle \
Qualitätsprüfung in der industriellen Fertigung. Mit einer Erkennungsgenauigkeit von \
99,7 Prozent und einer Verarbeitungsgeschwindigkeit von 500 Bildern pro Sekunde setzt sie \
neue Branchenstandards — eine Leistung, die auf der Hannover Messe 2025 mit dem \
renommierten HERMES Award gewürdigt wurde.<br/><br/>\
Die Plattform basiert auf einer proprietären Kombination aus Deep Learning und klassischer \
Bildverarbeitung, die auf NVIDIA Jetson Edge-Hardware läuft und somit keine permanente \
Cloud-Verbindung erfordert. Dies garantiert nicht nur Datensouveränität, sondern auch \
Latenzzeiten unter 2 Millisekunden — entscheidend für Echtzeit-Qualitätskontrolle in \
Hochgeschwindigkeitsproduktionslinien. Aktuell ist die VisionAI Platform bei über 120 \
Kunden in 14 Ländern im Einsatz."""

TEXT_PRODUCT_3 = """\
<b>LogiFlow Autonomous — Autonome Lagerlogistik</b><br/><br/>\
LogiFlow Autonomous revolutioniert die innerbetriebliche Logistik durch den Einsatz \
autonomer mobiler Roboter (AMR). Unser System umfasst eine Flottenmanagement-Software, \
die bis zu 200 Roboter gleichzeitig koordiniert und dynamisch auf Veränderungen in der \
Lagertopologie reagiert. Im Vergleich zu manuellen Prozessen erzielen unsere Kunden \
eine durchschnittliche Effizienzsteigerung von 45 Prozent.<br/><br/>\
Die LogiFlow-AMRs navigieren mittels LiDAR und visueller SLAM-Technologie selbstständig \
durch komplexe Lagerumgebungen, erkennen Hindernisse in Echtzeit und optimieren ihre \
Fahrtwege kontinuierlich. Die Integration mit bestehenden Warehouse-Management-Systemen \
erfolgt über standardisierte Schnittstellen (REST API, VDA 5050), was eine schrittweise \
Automatisierung ohne Komplettumstellung ermöglicht."""

TEXT_FINANZEN = """\
Das Geschäftsjahr 2025 war das erfolgreichste in der Unternehmensgeschichte der TechVision AG. \
Der Konzernumsatz stieg um 23 Prozent auf 847 Millionen Euro (Vorjahr: 689 Millionen Euro). \
Das operative Ergebnis (EBIT) erreichte 127 Millionen Euro bei einer EBIT-Marge von \
15,0 Prozent. Besonders erfreulich entwickelte sich der Auftragseingang, der mit \
1,02 Milliarden Euro erstmals die Milliardengrenze überschritt — ein Plus von 31 Prozent \
gegenüber dem Vorjahr.<br/><br/>\
Die Investitionen in Forschung und Entwicklung beliefen sich auf 157 Millionen Euro, was \
einer F&E-Quote von 18,5 Prozent des Umsatzes entspricht. Damit liegt TechVision deutlich \
über dem Branchendurchschnitt von 12 Prozent und unterstreicht unser Bekenntnis zur \
technologischen Spitzenposition.<br/><br/>\
Die Mitarbeiterzahl stieg im Jahresverlauf von 2.400 auf 3.200 — ein Zuwachs von \
33 Prozent, der vorwiegend in den Bereichen F&E (60 Prozent der Neueinstellungen) und \
Vertrieb (25 Prozent) erfolgte."""

TEXT_FINANZEN_SEGMENTE = """\
<b>Umsatz nach Geschäftsbereichen:</b><br/><br/>\
<b>Robotik (382 Mio. €, 45%)</b>: Der größte Geschäftsbereich wuchs um 28 Prozent, \
getrieben durch die hohe Nachfrage nach dem RoboAssist Pro und dem Trend zur \
Mensch-Roboter-Kollaboration im Mittelstand.<br/><br/>\
<b>KI-Software (296 Mio. €, 35%)</b>: Wachstum von 19 Prozent, angeführt von der \
VisionAI Platform. Die SaaS-Erlöse stiegen überproportional um 34 Prozent auf \
89 Millionen Euro.<br/><br/>\
<b>Logistik (169 Mio. €, 20%)</b>: Mit einem Wachstum von 31 Prozent das am schnellsten \
wachsende Segment. LogiFlow Autonomous profitiert vom Boom im E-Commerce und der \
zunehmenden Automatisierung von Lagerprozessen."""

TEXT_FINANZEN_AUSBLICK = """\
<b>Finanzielle Ziele und Prognosen:</b><br/><br/>\
Für das Geschäftsjahr 2026 prognostiziert der Vorstand einen Konzernumsatz von 1,05 bis \
1,10 Milliarden Euro. Die EBIT-Marge soll auf 16 Prozent gesteigert werden. \
Mittelfristig strebt TechVision ein Umsatzziel von 1,5 Milliarden Euro bis 2028 an, \
bei einer Ziel-EBIT-Marge von 18 Prozent. Die F&E-Quote soll auch in Zukunft bei über \
17 Prozent des Umsatzes gehalten werden, um die technologische Führungsposition zu sichern."""

TEXT_ESG = """\
Nachhaltigkeit ist ein integraler Bestandteil der Unternehmensstrategie von TechVision. \
Im Geschäftsjahr 2025 haben wir unsere CO₂-Emissionen auf 12.400 Tonnen reduziert — eine \
Verringerung um 42 Prozent gegenüber dem Basisjahr 2020 (21.400 Tonnen). Damit liegen wir \
auf Kurs zur Erreichung unseres Zwischenziels von 65 Prozent Reduktion bis 2028 und der \
vollständigen Klimaneutralität bis 2030.<br/><br/>\
Seit 2024 beziehen alle Standorte der TechVision AG — München, Berlin, Hamburg und \
Shanghai — ausschließlich Ökostrom aus langfristigen Lieferverträgen. Im Bereich der \
Kreislaufwirtschaft erreichten wir eine Recyclingquote von 78 Prozent bei \
Produktionsabfällen (Ziel: 90 Prozent bis 2027). Der Wasserverbrauch konnte gegenüber \
2022 um 28 Prozent gesenkt werden.<br/><br/>\
Unsere Nachhaltigkeitsleistung wurde 2025 erneut extern bestätigt: Im EcoVadis-Rating \
erreichten wir die Platinstufe mit 91 von 100 Punkten. Unsere wissenschaftsbasierten \
Klimaziele sind durch die Science Based Targets initiative (SBTi) validiert. Jeder \
Mitarbeiter absolviert jährlich 24 Stunden Nachhaltigkeitsschulung — deutlich über dem \
Branchendurchschnitt von 8 Stunden."""

TEXT_TECHSTACK = """\
Die technologische Architektur von TechVision basiert auf einem fünfschichtigen Stack, \
der von der Edge-Hardware bis zur Cloud-Analytik reicht. Diese durchgängige Architektur \
ermöglicht es uns, KI-Anwendungen von der Entwicklung über die Bereitstellung bis zum \
Betrieb aus einer Hand zu liefern.<br/><br/>\
<b>Layer 1 — Edge Hardware:</b> NVIDIA Jetson Orin und custom FPGA-Designs bilden die \
Grundlage für leistungsfähige und energieeffiziente KI-Inferenz am Einsatzort. \
Unsere proprietären FPGA-Konfigurationen sind für spezifische Bildverarbeitungsaufgaben \
optimiert und erreichen bis zu 4x höhere Energieeffizienz als generische GPU-Lösungen.<br/><br/>\
<b>Layer 2 — TechVision OS:</b> Unser Real-time-Linux-basiertes Betriebssystem mit \
integrierter Container Runtime gewährleistet deterministische Ausführungszeiten unter \
1 Millisekunde — entscheidend für sicherheitskritische Roboteranwendungen.<br/><br/>\
<b>Layer 3 — AI Framework:</b> Die Integration von PyTorch für Training, ONNX Runtime für \
plattformübergreifende Inferenz und TensorRT für NVIDIA-optimierte Ausführung ermöglicht \
nahtlose Übergänge zwischen Entwicklung und Produktion.<br/><br/>\
<b>Layer 4 — Application Suite:</b> VisionAI, RoboAssist und LogiFlow nutzen gemeinsame \
Basisdienste für Datenmanagement, Modellverwaltung und Benutzeroberflächen.<br/><br/>\
<b>Layer 5 — Cloud Management:</b> Zentrales Monitoring, Over-the-Air-Updates und \
Flottenmanagement für verteilte Edge-Installationen weltweit."""

TEXT_AUSBLICK = """\
Das Jahr 2026 wird für TechVision ein Jahr der Expansion und Innovation. Wir planen \
die Eröffnung von Vertriebsbüros in Vietnam und Singapur, um unsere Präsenz im \
südostasiatischen Markt systematisch auszubauen. Der Logistik- und Fertigungssektor \
in der ASEAN-Region wächst jährlich um über 15 Prozent und bietet erhebliches Potenzial \
für unsere Automatisierungslösungen.<br/><br/>\
Im zweiten Quartal 2026 wird unser neues KI-Forschungszentrum in München-Garching den \
Betrieb aufnehmen. In enger Kooperation mit dem Fraunhofer IPA werden dort rund 150 \
Forscherinnen und Forscher an der nächsten Generation multimodaler KI-Systeme arbeiten. \
Schwerpunkte sind Foundation Models für die industrielle Bildverarbeitung, \
selbstlernende Robotersteuerungen und energieeffiziente KI-Architekturen.<br/><br/>\
Auf der Produktseite bereiten wir zwei bedeutende Launches vor: Der RoboAssist Pro 2.0 \
wird eine erhöhte Tragkraft von 20 Kilogramm und eine verbesserte Sensorik für noch \
engere Mensch-Roboter-Kollaboration bieten. Die VisionAI 4.0 wird erstmals generative \
KI-Funktionen integrieren, die automatisch Prüfpläne aus CAD-Daten ableiten.<br/><br/>\
Strategisch vertiefen wir unsere Partnerschaft mit Bosch im Bereich Automotive AI. \
Gemeinsam entwickeln wir KI-gestützte Qualitätssicherungssysteme für die \
Elektrofahrzeugproduktion — ein Markt, der bis 2028 auf ein Volumen von 3,2 Milliarden \
Euro anwachsen soll.<br/><br/>\
Für das Geschäftsjahr 2026 prognostizieren wir einen Konzernumsatz von 1,05 bis \
1,10 Milliarden Euro — und damit erstmals das Überschreiten der Milliarden-Euro-Marke. \
Die EBIT-Marge soll auf 16 Prozent gesteigert werden. Unser mittelfristiges Umsatzziel \
bleibt unverändert bei 1,5 Milliarden Euro bis 2028."""


# ===========================================================================
# PDF Builder
# ===========================================================================

def build_pdf(chart_paths: dict):
    """Build the full PDF from chart images and text content."""
    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )

    # Styles
    styles = getSampleStyleSheet()

    style_h1 = ParagraphStyle(
        "TVH1", parent=styles["Heading1"],
        fontName="DejaVuSans-Bold", fontSize=20,
        textColor=HexColor(BLUE), spaceAfter=12 * mm,
        spaceBefore=8 * mm,
    )
    style_h2 = ParagraphStyle(
        "TVH2", parent=styles["Heading2"],
        fontName="DejaVuSans-Bold", fontSize=14,
        textColor=HexColor(DARK), spaceAfter=6 * mm,
        spaceBefore=6 * mm,
    )
    style_body = ParagraphStyle(
        "TVBody", parent=styles["Normal"],
        fontName="DejaVuSans", fontSize=11,
        leading=16, alignment=TA_JUSTIFY,
        spaceAfter=4 * mm,
    )
    style_caption = ParagraphStyle(
        "TVCaption", parent=styles["Normal"],
        fontName="DejaVuSans", fontSize=9,
        textColor=HexColor("#666666"),
        alignment=TA_CENTER, spaceAfter=8 * mm,
        spaceBefore=2 * mm, leading=12,
    )
    style_cover_title = ParagraphStyle(
        "TVCoverTitle", parent=styles["Title"],
        fontName="DejaVuSans-Bold", fontSize=32,
        textColor=HexColor(BLUE), alignment=TA_CENTER,
        spaceAfter=10 * mm,
    )
    style_cover_sub = ParagraphStyle(
        "TVCoverSub", parent=styles["Normal"],
        fontName="DejaVuSans", fontSize=16,
        textColor=HexColor(DARK), alignment=TA_CENTER,
        spaceAfter=6 * mm,
    )

    # Page dimensions for image sizing
    pw = A4[0] - 40 * mm  # available width

    elements = []

    # --- Cover Page ---
    elements.append(Spacer(1, 60 * mm))
    elements.append(Paragraph("TechVision AG", style_cover_title))
    elements.append(Paragraph("Jahresbericht 2025", style_cover_sub))
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph("Industrielle KI. Robotik. Logistikautomatisierung.",
                              style_cover_sub))
    elements.append(Spacer(1, 30 * mm))

    # Cover info box
    cover_data = [
        ["Gründung:", "2015 in München"],
        ["CEO:", "Dr. Markus Weber"],
        ["Mitarbeiter:", "3.200 (2025)"],
        ["Umsatz 2025:", "847 Mio. €"],
        ["Standorte:", "München, Berlin, Hamburg, Shanghai"],
    ]
    cover_table = Table(cover_data, colWidths=[50 * mm, 100 * mm])
    cover_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
        ("FONTNAME", (0, 0), (0, -1), "DejaVuSans-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TEXTCOLOR", (0, 0), (-1, -1), HexColor(DARK)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("LEFTPADDING", (1, 0), (1, -1), 8),
    ]))
    elements.append(cover_table)
    elements.append(PageBreak())

    # --- Vorwort des CEO ---
    elements.append(Paragraph("Vorwort des Vorstandsvorsitzenden", style_h1))
    for para in TEXT_VORWORT.split("\n\n"):
        elements.append(Paragraph(para.replace("\n", " "), style_body))
    elements.append(PageBreak())

    # --- Strategie & Megatrends ---
    elements.append(Paragraph("Strategie & Megatrends", style_h1))
    elements.append(Paragraph(
        "Fünf Megatrends bestimmen die strategische Ausrichtung der TechVision AG "
        "und bilden den Rahmen für unsere Investitions- und Innovationsentscheidungen.",
        style_body))
    elements.append(Image(chart_paths["strategy"], width=pw, height=pw * 0.75))
    elements.append(Paragraph(
        "Abb. 1: Die fünf strategischen Megatrends der TechVision AG",
        style_caption))
    elements.append(Paragraph(TEXT_MEGATREND_1, style_body))
    elements.append(Paragraph(TEXT_MEGATREND_2, style_body))
    elements.append(Paragraph(TEXT_MEGATREND_3, style_body))
    elements.append(Paragraph(TEXT_MEGATREND_4, style_body))
    elements.append(Paragraph(TEXT_MEGATREND_5, style_body))
    elements.append(PageBreak())

    # --- Produkte & Innovation ---
    elements.append(Paragraph("Produkte & Innovation", style_h1))
    elements.append(Paragraph(TEXT_PRODUCT_1, style_body))
    elements.append(Image(chart_paths["robot"], width=pw, height=pw * 0.75))
    elements.append(Paragraph(
        "Abb. 2: RoboAssist Pro — 6-Achs-Industrieroboter mit kollaborativer Sicherheit",
        style_caption))
    elements.append(Paragraph(TEXT_PRODUCT_2, style_body))
    elements.append(Image(chart_paths["visionai"], width=pw, height=pw * 0.75))
    elements.append(Paragraph(
        "Abb. 3: VisionAI Platform — Architekturübersicht der Echtzeit-Qualitätsprüfung",
        style_caption))
    elements.append(Paragraph(TEXT_PRODUCT_3, style_body))
    elements.append(Image(chart_paths["warehouse"], width=pw, height=pw * 0.75))
    elements.append(Paragraph(
        "Abb. 4: LogiFlow Autonomous — Schematische Darstellung eines automatisierten Lagers",
        style_caption))
    elements.append(PageBreak())

    # --- Finanzkennzahlen ---
    elements.append(Paragraph("Finanzkennzahlen", style_h1))
    elements.append(Paragraph(TEXT_FINANZEN, style_body))
    elements.append(Image(chart_paths["revenue_bars"], width=pw, height=pw * 0.75))
    elements.append(Paragraph(
        "Abb. 5: Umsatzentwicklung der TechVision AG 2021–2025 (in Mio. €)",
        style_caption))

    # Key metrics table
    metrics_data = [
        ["Kennzahl", "2025", "2024", "Veränderung"],
        ["Umsatz (Mio. €)", "847", "689", "+23%"],
        ["EBIT (Mio. €)", "127", "99", "+28%"],
        ["EBIT-Marge", "15,0%", "14,4%", "+0,6 PP"],
        ["F&E-Ausgaben (Mio. €)", "157", "118", "+33%"],
        ["Auftragseingang (Mio. €)", "1.020", "779", "+31%"],
        ["Mitarbeiter", "3.200", "2.400", "+33%"],
    ]
    metrics_table = Table(metrics_data, colWidths=[55 * mm, 35 * mm, 35 * mm, 35 * mm])
    metrics_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "DejaVuSans"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor(BLUE)),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("TEXTCOLOR", (0, 1), (-1, -1), HexColor(DARK)),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor(LIGHT)]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(metrics_table)
    elements.append(Spacer(1, 8 * mm))

    elements.append(Paragraph(TEXT_FINANZEN_SEGMENTE, style_body))
    elements.append(Image(chart_paths["revenue_pie"], width=pw * 0.85, height=pw * 0.85 * 0.75))
    elements.append(Paragraph(
        "Abb. 6: Umsatzverteilung nach Geschäftsbereichen 2025",
        style_caption))
    elements.append(Paragraph(TEXT_FINANZEN_AUSBLICK, style_body))
    elements.append(PageBreak())

    # --- Nachhaltigkeit & ESG ---
    elements.append(Paragraph("Nachhaltigkeit & ESG", style_h1))
    elements.append(Paragraph(TEXT_ESG, style_body))

    # ESG metrics table
    esg_data = [
        ["ESG-Kennzahl", "2025", "Ziel"],
        ["CO₂-Emissionen (Tonnen)", "12.400", "0 (bis 2030)"],
        ["Reduktion vs. 2020", "−42%", "−65% (bis 2028)"],
        ["Ökostrom-Anteil", "100%", "100%"],
        ["Recyclingquote", "78%", "90% (bis 2027)"],
        ["Wasserreduktion vs. 2022", "−28%", "−40% (bis 2028)"],
        ["EcoVadis Score", "91/100 (Platin)", ">90"],
        ["SBTi-Status", "Validiert", "Validiert"],
        ["Schulungsstunden/MA/Jahr", "24h", ">20h"],
    ]
    esg_table = Table(esg_data, colWidths=[60 * mm, 50 * mm, 50 * mm])
    esg_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "DejaVuSans"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor(GREEN)),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("TEXTCOLOR", (0, 1), (-1, -1), HexColor(DARK)),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor(LIGHT)]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(esg_table)
    elements.append(Spacer(1, 8 * mm))
    elements.append(Image(chart_paths["co2"], width=pw, height=pw * 0.75))
    elements.append(Paragraph(
        "Abb. 7: CO₂-Reduktionspfad der TechVision AG 2020–2030",
        style_caption))
    elements.append(PageBreak())

    # --- Technologie-Stack ---
    elements.append(Paragraph("Technologie-Stack", style_h1))
    elements.append(Paragraph(TEXT_TECHSTACK, style_body))
    elements.append(Image(chart_paths["tech_stack"], width=pw, height=pw * 0.75))
    elements.append(Paragraph(
        "Abb. 8: Fünfschichtiger Technologie-Stack der TechVision AG",
        style_caption))
    elements.append(PageBreak())

    # --- Ausblick 2026 ---
    elements.append(Paragraph("Ausblick 2026", style_h1))
    elements.append(Paragraph(TEXT_AUSBLICK, style_body))

    # Build
    doc.build(elements)
    size = os.path.getsize(str(OUTPUT_PDF))
    print(f"\nPDF generated: {OUTPUT_PDF}")
    print(f"  Size: {size:,} bytes ({size / 1024 / 1024:.1f} MB)")


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 60)
    print("TechVision AG Jahresbericht 2025 — PDF Generator")
    print("=" * 60)

    # Step 1: Generate all charts
    print("\nGenerating charts...")
    charts = {}
    charts["strategy"] = chart_strategy_diagram()
    charts["robot"] = chart_robot_diagram()
    charts["visionai"] = chart_visionai_flow()
    charts["warehouse"] = chart_warehouse_layout()
    charts["revenue_bars"] = chart_revenue_bars()
    charts["revenue_pie"] = chart_revenue_pie()
    charts["co2"] = chart_co2_line()
    charts["tech_stack"] = chart_tech_stack()
    print(f"\n  {len(charts)} charts generated in {ASSETS_DIR}/")

    # Step 2: Build PDF
    print("\nBuilding PDF...")
    build_pdf(charts)

    # Step 3: Verify with PyMuPDF
    print("\n--- Verification ---")
    try:
        import fitz
        doc = fitz.open(str(OUTPUT_PDF))
        total_images = 0
        for page in doc:
            text = page.get_text()
            images = page.get_images()
            total_images += len(images)
            print(f"  Page {page.number + 1}: {len(text):,} chars, {len(images)} images")
            if page.number < 1:
                preview = text[:150].replace("\n", " ").strip()
                print(f"    Preview: {preview}...")
        print(f"\n  Total: {doc.page_count} pages, {total_images} images")
        doc.close()
    except ImportError:
        print("  (PyMuPDF not available for verification — install fitz)")


if __name__ == "__main__":
    main()
