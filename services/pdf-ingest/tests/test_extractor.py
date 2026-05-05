import json

from app import extractor
from app.extractor import ParsedElement


def pe(kind, page=1, content="", level=None, raw_id=1, bbox=None):
    return ParsedElement(
        element_type=kind,
        page=page,
        bbox=bbox or (10.0, 20.0, 100.0, 120.0),
        page_size=(612.0, 792.0),
        content=content,
        image_path="/tmp/image.png" if kind == "image" else None,
        heading_level=level,
        raw_id=raw_id,
    )


def test_normalize_type_image_variants():
    for raw in ["image", "picture", "png", "jpeg", "jpg"]:
        assert extractor._normalize_type(raw) == "image"


def test_normalize_type_skip_structural_noise():
    assert extractor._normalize_type("header") == "_skip"
    assert extractor._normalize_type("footer") == "_skip"


def test_bbox_reads_field_with_space():
    assert extractor._bbox({"bounding box": [1, "2", 3.5, 4]}) == (1.0, 2.0, 3.5, 4.0)


def test_collect_text_walks_nested_kids():
    node = {
        "kids": [
            {"content": "Umsatz"},
            {"kids": [{"content": "2025"}, {"content": "Mio. EUR"}]},
        ]
    }
    assert extractor._collect_text(node) == "Umsatz 2025 Mio. EUR"


def test_render_table_markdown_with_column_span():
    table = {
        "type": "table",
        "rows": [
            {"cells": [
                {"kids": [{"content": "Bereich"}], "column span": 2},
                {"kids": [{"content": "Wert"}]},
            ]},
            {"cells": [
                {"kids": [{"content": "A"}]},
                {"kids": [{"content": "B"}]},
                {"kids": [{"content": "10"}]},
            ]},
        ],
    }
    md = extractor._render_table_markdown(table)
    assert "| Bereich |  | Wert |" in md
    assert "| A | B | 10 |" in md


def test_render_list_markdown_handles_both_keys():
    node = {"list items": [{"kids": [{"content": "Erstens"}]}, {"kids": [{"content": "Zweitens"}]}]}
    assert extractor._render_list_markdown(node) == "- Erstens\n- Zweitens"
    node = {"items": [{"kids": [{"content": "Alternative"}]}]}
    assert extractor._render_list_markdown(node) == "- Alternative"


def test_parse_walks_kids_and_resolves_image_path(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    def fake_run(pdf_path, out_dir):
        doc = {
            "kids": [
                {"type": "heading", "page number": 1, "content": "Strategie", "heading level": 1,
                 "bounding box": [1, 2, 3, 4], "id": 1},
                {"type": "paragraph", "page number": 1, "content": "Absatz",
                 "bounding box": [5, 6, 7, 8], "id": 2},
                {"type": "image", "page number": 1, "source": "images/a.png",
                 "bounding box": [9, 10, 11, 12], "id": 3},
            ]
        }
        (tmp_path / "out").mkdir(exist_ok=True)
        target = tmp_path / "out" / "sample.json"
        target.write_text(json.dumps(doc), encoding="utf-8")
        return None

    monkeypatch.setattr(extractor, "OPENDATALOADER_TMP", str(tmp_path))
    monkeypatch.setattr(extractor.tempfile, "mkdtemp", lambda prefix, dir: str(tmp_path / "out"))
    monkeypatch.setattr(extractor, "_run_opendataloader", fake_run)
    monkeypatch.setattr(extractor, "_harvest_page_sizes", lambda _: {1: (100.0, 200.0)})

    elements, out_dir = extractor.parse(str(pdf), "doc")
    assert out_dir == str(tmp_path / "out")
    assert [e.element_type for e in elements] == ["heading", "text", "image"]
    assert elements[-1].image_path == str(tmp_path / "out" / "images/a.png")
    assert elements[0].page_size == (100.0, 200.0)


def test_section_chunk_has_breadcrumb_prefix():
    chunks = extractor.layout_to_chunks([
        pe("heading", content="1. Strategie", level=1, raw_id=10),
        pe("text", content="Der Bericht nennt Wachstum.", raw_id=11),
    ])
    assert len(chunks) == 1
    assert chunks[0].content_text.startswith("1. Strategie\n\n")
    assert chunks[0].meta["heading_path"] == ["1. Strategie"]
    assert chunks[0].meta["bbox"]


def test_page_continuation_marks_forts():
    chunks = extractor.layout_to_chunks([
        pe("heading", page=1, content="Kapitel", level=1),
        pe("text", page=1, content="Seite eins."),
        pe("text", page=2, content="Seite zwei."),
    ])
    assert len(chunks) == 2
    assert chunks[1].content_text.startswith("Kapitel (Forts.)")


def test_table_row_groups_split_for_large_table(monkeypatch):
    monkeypatch.setattr(extractor, "TABLE_HARD_LIMIT", 120)
    rows = [{"cells": [{"kids": [{"content": "Name"}]}, {"kids": [{"content": "Wert"}]}]}]
    for i in range(20):
        rows.append({"cells": [{"kids": [{"content": f"Zeile {i}"}]}, {"kids": [{"content": "x" * 20}]}]})
    table = pe("table", content=extractor._render_table_markdown({"rows": rows}))
    chunks = extractor.layout_to_chunks([table])
    assert len(chunks) > 1
    assert all(c.meta["split_strategy"] == "row_groups" for c in chunks)
    assert all("| Name | Wert |" in c.content_text for c in chunks)


def test_image_chunk_carries_bbox_and_heading_path():
    chunks = extractor.layout_to_chunks([
        pe("heading", content="Bilder", level=1),
        pe("image", raw_id=99),
    ])
    image = chunks[0]
    assert image.chunk_type == "image"
    assert image.meta["heading_path"] == ["Bilder"]
    assert image.meta["element_id"] == 99
