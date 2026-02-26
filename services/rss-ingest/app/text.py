import re
from typing import List


def split_text(text: str, chunk_chars: int, overlap: int) -> List[str]:
    """German-optimized sentence-aware text chunking (copied from pdf-ingest)."""
    if not text or not text.strip():
        return []

    # Collapse horizontal whitespace but PRESERVE newlines for paragraph detection
    text = re.sub(r'[^\S\n]+', ' ', text)

    # Split on paragraph breaks first, then on sentence boundaries
    # (period/!/? followed by space + capital letter — avoids breaking "z.B." or "Nr.")
    paragraphs = re.split(r'\n\s*\n+', text)
    sentences: List[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        parts = re.split(r'(?<=[.!?])\s+(?=[A-ZÄÖÜ])', para)
        sentences.extend(p.strip() for p in parts if p.strip())

    # Merge sentences into chunks up to chunk_chars
    chunks: List[str] = []
    current = ""
    for sent in sentences:
        if current and len(current) + len(sent) + 1 > chunk_chars:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = (tail + " " + sent).strip() if tail else sent
        else:
            current = (current + " " + sent).strip() if current else sent
    if current:
        chunks.append(current)

    # Fallback: hard-split any oversized chunks (single huge sentence)
    result: List[str] = []
    for c in chunks:
        if len(c) <= chunk_chars:
            result.append(c)
        else:
            start = 0
            while start < len(c):
                result.append(c[start:start + chunk_chars])
                start += chunk_chars - overlap
    return result
