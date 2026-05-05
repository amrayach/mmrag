import json
import logging
import os
import shutil
import shlex
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Optional

import fitz

from .splitter import split_text

logger = logging.getLogger("pdf-ingest.extractor")

OPENDATALOADER_SEMAPHORE = threading.Semaphore(
    int(os.getenv("OPENDATALOADER_MAX_PARALLEL", "1"))
)
OPENDATALOADER_TIMEOUT = int(os.getenv("OPENDATALOADER_TIMEOUT", "300"))
OPENDATALOADER_TMP = os.getenv(
    "OPENDATALOADER_TMP_DIR",
    os.getenv("OPENDATALOADER_TMP", "/tmp/odl"),
)
OPENDATALOADER_VERSION = os.getenv("OPENDATALOADER_VERSION", "2.4.1")
JAVA_OPTS = shlex.split(os.getenv("OPENDATALOADER_JAVA_OPTS", "-Xmx2g"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))
TABLE_HARD_LIMIT = 4 * CHUNK_CHARS

EXTRACTOR_NAME = f"opendataloader-pdf@{OPENDATALOADER_VERSION}"

ELEMENT_TYPE_MAP = {
    "image": "image",
    "picture": "image",
    "png": "image",
    "jpeg": "image",
    "jpg": "image",
    "table": "table",
    "heading": "heading",
    "title": "heading",
    "h": "heading",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
    "paragraph": "text",
    "text": "text",
    "p": "text",
    "textbox": "text",
    "list": "list",
    "ul": "list",
    "ol": "list",
    "list item": "text",
    "li": "text",
    "header": "_skip",
    "footer": "_skip",
    "table row": "_skip",
    "table cell": "_skip",
    "caption": "_skip",
}


@dataclass
class ParsedElement:
    element_type: str
    page: int
    bbox: tuple[float, float, float, float]
    page_size: tuple[float, float]
    content: Optional[str]
    image_path: Optional[str]
    heading_level: Optional[int]
    raw_id: Optional[int]


@dataclass
class Chunk:
    chunk_type: str
    page: int
    content_text: Optional[str]
    caption: Optional[str]
    asset_path: Optional[str]
    image_bytes: Optional[bytes]
    meta: dict
    image_path: Optional[str] = None


def _normalize_type(raw: str) -> str:
    return ELEMENT_TYPE_MAP.get((raw or "").lower(), "text")


def _bbox(node) -> tuple[float, float, float, float] | None:
    bb = node.get("bounding box")
    if not bb or len(bb) != 4:
        return None
    try:
        return tuple(float(x) for x in bb)
    except (TypeError, ValueError):
        return None


def _collect_text(node) -> str:
    if not isinstance(node, dict):
        return ""
    parts: list[str] = []
    content = node.get("content")
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    for kid in node.get("kids") or []:
        sub = _collect_text(kid)
        if sub:
            parts.append(sub)
    return " ".join(parts).strip()


def _render_table_markdown(node) -> str:
    rows = node.get("rows") or []
    if not rows:
        return ""
    grid: list[list[str]] = []
    max_cols = 0
    for row in rows:
        line: list[str] = []
        for cell in row.get("cells") or []:
            text = _collect_text(cell).replace("|", r"\|").replace("\n", " ").strip()
            line.append(text)
            cspan = int(cell.get("column span") or cell.get("columnSpan") or 1)
            for _ in range(max(cspan - 1, 0)):
                line.append("")
        grid.append(line)
        max_cols = max(max_cols, len(line))
    if not grid or max_cols == 0:
        return ""
    for line in grid:
        line.extend([""] * (max_cols - len(line)))
    md = [
        "| " + " | ".join(grid[0]) + " |",
        "| " + " | ".join(["---"] * max_cols) + " |",
    ]
    for line in grid[1:]:
        md.append("| " + " | ".join(line) + " |")
    return "\n".join(md)


def _render_list_markdown(node) -> str:
    items = node.get("list items") or node.get("items") or []
    lines = []
    for item in items:
        text = _collect_text(item)
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)


def _jar_path() -> str:
    override = os.getenv("OPENDATALOADER_JAR_PATH")
    if override:
        return override
    return str(files("opendataloader_pdf").joinpath("jar", "opendataloader-pdf-cli.jar"))


def _harvest_page_sizes(pdf_path: str) -> dict[int, tuple[float, float]]:
    sizes: dict[int, tuple[float, float]] = {}
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            rect = doc.load_page(i).rect
            sizes[i + 1] = (float(rect.width), float(rect.height))
    return sizes


def _run_opendataloader(pdf_path: str, out_dir: str) -> None:
    args = [
        "java",
        *JAVA_OPTS,
        "-jar",
        _jar_path(),
        pdf_path,
        "--output-dir",
        out_dir,
        "--format",
        "json",
        "--image-output",
        "external",
        "--image-format",
        "png",
        "--reading-order",
        "xycut",
        "--use-struct-tree",
        "--quiet",
    ]
    subprocess.run(
        args,
        check=True,
        timeout=OPENDATALOADER_TIMEOUT,
        capture_output=True,
        text=True,
    )


def parse(pdf_path: str, doc_id: str) -> tuple[list[ParsedElement], str]:
    os.makedirs(OPENDATALOADER_TMP, exist_ok=True)
    out_dir = tempfile.mkdtemp(prefix=f"{doc_id}_", dir=OPENDATALOADER_TMP)
    try:
        page_sizes = _harvest_page_sizes(pdf_path)

        with OPENDATALOADER_SEMAPHORE:
            _run_opendataloader(pdf_path, out_dir)

        stem = Path(pdf_path).stem
        json_path = Path(out_dir) / f"{stem}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"opendataloader produced no JSON at {json_path}")

        doc = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    elements: list[ParsedElement] = []
    unknown_types: set[str] = set()

    def page_size_for(page: int) -> tuple[float, float]:
        return page_sizes.get(page, (612.0, 792.0))

    def node_text(node) -> str:
        return (node.get("content") or _collect_text(node) or "").strip()

    def heading_level(node) -> int:
        raw_type = (node.get("type") or "").lower()
        digit_suffix = next((c for c in raw_type if c.isdigit()), None)
        level = (
            node.get("heading level")
            or node.get("headingLevel")
            or node.get("level")
            or (int(digit_suffix) if digit_suffix else 1)
        )
        return int(level)

    def walk(node):
        raw_type = node.get("type", "")
        norm = _normalize_type(raw_type)
        if norm == "text" and raw_type and raw_type.lower() not in ELEMENT_TYPE_MAP:
            unknown_types.add(raw_type)
        if norm == "_skip":
            return

        page = int(node.get("page number") or node.get("pageNumber") or 1)
        bbox = _bbox(node) or (0.0, 0.0, 0.0, 0.0)

        if norm == "image":
            rel = node.get("source") or node.get("path")
            img_path = os.path.join(out_dir, rel) if rel and not os.path.isabs(rel) else rel
            elements.append(ParsedElement(
                element_type="image",
                page=page,
                bbox=bbox,
                page_size=page_size_for(page),
                content=None,
                image_path=img_path,
                heading_level=None,
                raw_id=node.get("id"),
            ))
            return

        if norm == "table":
            elements.append(ParsedElement(
                element_type="table",
                page=page,
                bbox=bbox,
                page_size=page_size_for(page),
                content=_render_table_markdown(node),
                image_path=None,
                heading_level=None,
                raw_id=node.get("id"),
            ))
            return

        if norm == "list":
            elements.append(ParsedElement(
                element_type="list",
                page=page,
                bbox=bbox,
                page_size=page_size_for(page),
                content=_render_list_markdown(node),
                image_path=None,
                heading_level=None,
                raw_id=node.get("id"),
            ))
            return

        if norm == "heading":
            elements.append(ParsedElement(
                element_type="heading",
                page=page,
                bbox=bbox,
                page_size=page_size_for(page),
                content=node_text(node),
                image_path=None,
                heading_level=heading_level(node),
                raw_id=node.get("id"),
            ))
            for kid in node.get("kids") or []:
                walk(kid)
            return

        text = node_text(node)
        if text:
            elements.append(ParsedElement(
                element_type="text",
                page=page,
                bbox=bbox,
                page_size=page_size_for(page),
                content=text,
                image_path=None,
                heading_level=None,
                raw_id=node.get("id"),
            ))
        for kid in node.get("kids") or []:
            walk(kid)

    for kid in doc.get("kids") or []:
        walk(kid)

    for raw in sorted(unknown_types):
        logger.warning("Unknown opendataloader element type %r mapped to text", raw)

    return elements, out_dir


def _union_bbox(bboxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    real = [b for b in bboxes if b and any(v != 0.0 for v in b)]
    if not real:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(b[0] for b in real),
        min(b[1] for b in real),
        max(b[2] for b in real),
        max(b[3] for b in real),
    )


def _heading_path(heading_stack: list[tuple[int, str]]) -> list[str]:
    return [text for _, text in heading_stack if text]


def _element_ids(elements: list[ParsedElement]) -> list[int]:
    return [int(e.raw_id) for e in elements if e.raw_id is not None]


def _section_meta(section: list[ParsedElement], heading_stack, strategy: str) -> dict:
    return {
        "source": "pdf_text",
        "page": section[0].page,
        "element_type": "section",
        "element_ids": _element_ids(section),
        "heading_path": _heading_path(heading_stack),
        "bbox": list(_union_bbox([e.bbox for e in section])),
        "bbox_units": "pdf_points",
        "bbox_order": "left,bottom,right,top",
        "page_size": list(section[0].page_size),
        "split_strategy": strategy,
        "extractor": EXTRACTOR_NAME,
    }


def _table_chunk(el: ParsedElement, heading_stack, content: str, strategy: str) -> Chunk:
    ids = _element_ids([el])
    meta = {
        "source": "pdf_text",
        "page": el.page,
        "element_type": "table",
        "element_ids": ids,
        "heading_path": _heading_path(heading_stack),
        "bbox": list(el.bbox),
        "bbox_units": "pdf_points",
        "bbox_order": "left,bottom,right,top",
        "page_size": list(el.page_size),
        "split_strategy": strategy,
        "extractor": EXTRACTOR_NAME,
    }
    return Chunk("text", el.page, content, None, None, None, meta)


def _parse_md_table(md: str) -> tuple[str, list[str]]:
    lines = [line for line in md.splitlines() if line.strip()]
    if not lines:
        return "", []
    if len(lines) == 1:
        return lines[0], []
    return "\n".join(lines[:2]), lines[2:]


def _make_table_chunks(el: ParsedElement, heading_stack) -> list[Chunk]:
    md = el.content or ""
    if not md.strip():
        return []
    breadcrumb = " › ".join(_heading_path(heading_stack))
    prefix = f"{breadcrumb}\n\n" if breadcrumb else ""
    if len(prefix + md) <= TABLE_HARD_LIMIT:
        return [_table_chunk(el, heading_stack, prefix + md, "intact")]

    header, rows = _parse_md_table(md)
    if not rows:
        parts = split_text(md, CHUNK_CHARS, CHUNK_OVERLAP)
        return [_table_chunk(el, heading_stack, prefix + p, "sentence_fallback") for p in parts]

    chunks: list[Chunk] = []
    bucket = [header]
    bucket_len = len(prefix) + len(header)
    for row in rows:
        if bucket_len + len(row) > TABLE_HARD_LIMIT and len(bucket) > 1:
            chunks.append(_table_chunk(el, heading_stack, prefix + "\n".join(bucket), "row_groups"))
            bucket = [header, row]
            bucket_len = len(prefix) + len(header) + len(row)
        else:
            bucket.append(row)
            bucket_len += len(row)
    if len(bucket) > 1:
        chunks.append(_table_chunk(el, heading_stack, prefix + "\n".join(bucket), "row_groups"))
    return chunks


def _make_image_chunk(el: ParsedElement, heading_stack) -> Chunk:
    ids = _element_ids([el])
    element_id = ids[0] if ids else None
    meta = {
        "source": "pdf_image",
        "page": el.page,
        "element_type": "image",
        "element_ids": ids,
        "element_id": element_id,
        "heading_path": _heading_path(heading_stack),
        "bbox": list(el.bbox),
        "bbox_units": "pdf_points",
        "bbox_order": "left,bottom,right,top",
        "page_size": list(el.page_size),
        "split_strategy": "image",
        "extractor": EXTRACTOR_NAME,
    }
    return Chunk("image", el.page, None, None, None, None, meta, image_path=el.image_path)


def layout_to_chunks(
    elements: list[ParsedElement],
    chunk_chars: int = CHUNK_CHARS,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []
    section: list[ParsedElement] = []
    section_page: int | None = None
    section_continuation = False
    pending_page_continuation = False

    def flush_section(strategy: str = "size"):
        nonlocal section, section_page, section_continuation
        if not section:
            return
        effective_strategy = "page_continuation" if section_continuation else strategy
        breadcrumb = " › ".join(_heading_path(heading_stack))
        body = "\n\n".join(e.content for e in section if e.content)
        prefix = f"{breadcrumb}\n\n" if breadcrumb else ""
        if effective_strategy == "page_continuation" and breadcrumb:
            prefix = f"{breadcrumb} (Forts.)\n\n"
        text = prefix + body
        if len(text) > chunk_chars:
            parts = split_text(text, chunk_chars, chunk_overlap)
            for part in parts:
                chunks.append(Chunk(
                    "text",
                    section_page or section[0].page,
                    part,
                    None,
                    None,
                    None,
                    _section_meta(section, heading_stack, "sentence_fallback"),
                ))
        else:
            chunks.append(Chunk(
                "text",
                section_page or section[0].page,
                text,
                None,
                None,
                None,
                _section_meta(section, heading_stack, effective_strategy),
            ))
        section = []
        section_page = None
        section_continuation = False

    for el in elements:
        if section and el.page != section_page:
            flush_section()
            pending_page_continuation = True

        if el.element_type == "heading":
            flush_section()
            pending_page_continuation = False
            level = el.heading_level or 1
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            if el.content:
                heading_stack.append((level, el.content))
            continue

        if el.element_type == "image":
            flush_section()
            pending_page_continuation = False
            chunks.append(_make_image_chunk(el, heading_stack))
            continue

        if el.element_type == "table":
            flush_section()
            pending_page_continuation = False
            chunks.extend(_make_table_chunks(el, heading_stack))
            continue

        if not el.content:
            continue
        prospective = sum(len(e.content or "") for e in section) + len(el.content)
        if prospective > chunk_chars and section:
            flush_section()
        if not section:
            section_continuation = pending_page_continuation
            pending_page_continuation = False
        section.append(el)
        section_page = el.page

    flush_section()
    return chunks
