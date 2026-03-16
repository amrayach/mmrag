import logging
import pathlib

from fastapi import APIRouter, HTTPException, Query

from .. import config

logger = logging.getLogger("controlcenter.routes.docs")

router = APIRouter(prefix="/api/docs", tags=["docs"])

BASE = pathlib.Path(config.PROJECT_DOCS_DIR)


def _safe_path(requested: str) -> pathlib.Path:
    """Resolve a path safely, preventing traversal attacks."""
    if ".." in requested:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    resolved = (BASE / requested).resolve()
    if not resolved.is_relative_to(BASE.resolve()):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    return resolved


@router.get("/tree")
async def docs_tree():
    """Walk project-docs for .md files, return tree structure."""
    base = BASE.resolve()
    if not base.exists():
        return {"files": []}

    files = []
    for p in sorted(base.rglob("*.md")):
        rel = p.relative_to(base)
        files.append({
            "path": str(rel),
            "name": p.name,
            "dir": str(rel.parent) if str(rel.parent) != "." else "",
            "size": p.stat().st_size,
        })
    return {"files": files}


@router.get("/content")
async def docs_content(path: str = Query(..., description="Relative path to .md file")):
    """Read a markdown file and extract TOC from headers."""
    resolved = _safe_path(path)

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if not resolved.suffix.lower() == ".md":
        raise HTTPException(status_code=400, detail="Only .md files supported")

    content = resolved.read_text(encoding="utf-8", errors="replace")

    # Extract TOC from markdown headers
    toc = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            if title:
                slug = title.lower().replace(" ", "-")
                slug = "".join(c for c in slug if c.isalnum() or c == "-")
                toc.append({"level": hashes, "title": title, "slug": slug})

    return {"path": path, "content": content, "toc": toc}
