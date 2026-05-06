#!/usr/bin/env python3
"""Phase 0.3 — RAG index integrity report.

Scans rag_docs / rag_chunks via TCP host=127.0.0.1 (NEVER Unix socket peer
auth) and writes Markdown + JSON snapshots of the corpus state, including:

- doc / chunk totals
- chunks broken down by chunk_type, meta.source
- chunks with NULL embedding (the silent-exclusion cohort)
- chunks tagged meta.embedding_error (grouped by error value)
- PDF text chunks with non-empty content_text but NULL embedding
- image chunks with asset_path but empty/null caption
- very-short / very-long content cohorts (likely embed-failure contributors)
- meta.heading_path / meta.element_type coverage
- top filenames by missing-embedding count

Outputs:
    data/eval/phase0_baseline/index_integrity_report.md
    data/eval/phase0_baseline/index_integrity_report.json

Usage:
    python scripts/report_rag_index_integrity.py
    # or, if psycopg is missing on the host interpreter:
    .venv-phase0/bin/python scripts/report_rag_index_integrity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Re-exec under the project venv if psycopg is missing in the active interp.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _phase0_utils import (  # noqa: E402
    ensure_venv,
    open_db_connection,
    phase0_baseline_dir,
    now_iso,
)

ensure_venv()


SQL_STATS = {
    "total_docs": "SELECT COUNT(*) FROM rag_docs;",
    "total_chunks": "SELECT COUNT(*) FROM rag_chunks;",
    "chunks_by_chunk_type": (
        "SELECT chunk_type, COUNT(*) AS n FROM rag_chunks "
        "GROUP BY chunk_type ORDER BY n DESC;"
    ),
    "chunks_by_meta_source": (
        "SELECT COALESCE(meta->>'source', '<null>') AS source, COUNT(*) AS n "
        "FROM rag_chunks GROUP BY source ORDER BY n DESC;"
    ),
    "chunks_null_embedding_total": (
        "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL;"
    ),
    "chunks_with_embedding_error": (
        "SELECT COALESCE(meta->>'embedding_error', '<null>') AS err, "
        "COUNT(*) AS n FROM rag_chunks "
        "WHERE meta ? 'embedding_error' "
        "GROUP BY err ORDER BY n DESC;"
    ),
    "pdf_text_with_content_but_null_embedding": (
        "SELECT COUNT(*) FROM rag_chunks c "
        "JOIN rag_docs d ON c.doc_id = d.doc_id "
        "WHERE c.chunk_type = 'text' AND c.embedding IS NULL "
        "  AND COALESCE(c.content_text, '') <> '' "
        "  AND d.filename NOT LIKE 'http%';"
    ),
    "image_chunks_with_asset_no_caption": (
        "SELECT COUNT(*) FROM rag_chunks "
        "WHERE chunk_type = 'image' "
        "  AND COALESCE(asset_path, '') <> '' "
        "  AND COALESCE(NULLIF(caption, ''), '') = '';"
    ),
    "very_short_content_total": (
        "SELECT COUNT(*) FROM rag_chunks "
        "WHERE chunk_type = 'text' "
        "  AND char_length(COALESCE(content_text, '')) < 50;"
    ),
    "very_long_content_total": (
        "SELECT COUNT(*) FROM rag_chunks "
        "WHERE chunk_type = 'text' "
        "  AND char_length(COALESCE(content_text, '')) > 8000;"
    ),
    "chunks_with_heading_path": (
        "SELECT COUNT(*) FROM rag_chunks WHERE meta ? 'heading_path';"
    ),
    "chunks_with_element_type": (
        "SELECT COUNT(*) FROM rag_chunks WHERE meta ? 'element_type';"
    ),
    "top_filenames_missing_embedding": (
        "SELECT d.filename, COUNT(*) AS n_missing "
        "FROM rag_chunks c "
        "JOIN rag_docs d ON c.doc_id = d.doc_id "
        "WHERE c.embedding IS NULL "
        "GROUP BY d.filename ORDER BY n_missing DESC LIMIT 10;"
    ),
    "production_excluded_by_null_embedding": (
        # The same WHERE clause used by services/rag-gateway/app/context.py
        "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL;"
    ),
    "very_short_text_per_filename": (
        "SELECT d.filename, COUNT(*) AS n FROM rag_chunks c "
        "JOIN rag_docs d ON c.doc_id = d.doc_id "
        "WHERE c.chunk_type = 'text' "
        "  AND char_length(COALESCE(c.content_text, '')) < 50 "
        "GROUP BY d.filename ORDER BY n DESC LIMIT 10;"
    ),
    "very_long_text_per_filename": (
        "SELECT d.filename, COUNT(*) AS n FROM rag_chunks c "
        "JOIN rag_docs d ON c.doc_id = d.doc_id "
        "WHERE c.chunk_type = 'text' "
        "  AND char_length(COALESCE(c.content_text, '')) > 8000 "
        "GROUP BY d.filename ORDER BY n DESC LIMIT 10;"
    ),
}


def fetch(cur, sql: str):
    cur.execute(sql)
    rows = cur.fetchall()
    return rows


def main() -> int:
    out_dir = phase0_baseline_dir()
    md_path = out_dir / "index_integrity_report.md"
    json_path = out_dir / "index_integrity_report.json"

    with open_db_connection() as conn, conn.cursor() as cur:
        results: dict[str, object] = {}
        for key, sql in SQL_STATS.items():
            rows = fetch(cur, sql)
            if len(rows) == 1 and len(rows[0]) == 1:
                results[key] = rows[0][0]
            else:
                # Convert to list of dicts using cursor.description
                cols = [d.name for d in cur.description] if cur.description else []
                results[key] = [dict(zip(cols, r)) for r in rows]

        # Coverage percentages
        total_raw = results.get("total_chunks", 0) or 0
        total = int(total_raw) if isinstance(total_raw, int) else 0
        if total > 0:
            hp = int(results.get("chunks_with_heading_path", 0) or 0)  # type: ignore[arg-type]
            et = int(results.get("chunks_with_element_type", 0) or 0)  # type: ignore[arg-type]
            results["heading_path_coverage_pct"] = round(100.0 * hp / total, 2)
            results["element_type_coverage_pct"] = round(100.0 * et / total, 2)
            null_emb = int(
                results.get("chunks_null_embedding_total", 0) or 0  # type: ignore[arg-type]
            )
            results["null_embedding_pct"] = round(100.0 * null_emb / total, 2)

    payload = {
        "captured_at": now_iso(),
        "phase": "0.3",
        "host": "127.0.0.1",
        "results": results,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # ---- Markdown ----
    lines: list[str] = []
    lines.append("# Phase 0.3 — RAG index integrity report")
    lines.append("")
    lines.append(f"- **Captured at:** {payload['captured_at']}")
    lines.append("- **Connection:** TCP host=127.0.0.1")
    lines.append("")

    def fmt_int(x):
        return f"{int(x):,}" if isinstance(x, int) else str(x)

    lines.append("## Totals")
    lines.append("")
    lines.append(f"- **Documents:** {fmt_int(results.get('total_docs', 0))}")
    lines.append(f"- **Chunks:** {fmt_int(results.get('total_chunks', 0))}")
    lines.append(
        f"- **Chunks with NULL embedding:** "
        f"{fmt_int(results.get('chunks_null_embedding_total', 0))} "
        f"({results.get('null_embedding_pct', '?')}% — "
        "production silently excludes these via "
        "`WHERE embedding IS NOT NULL`)"
    )
    lines.append(
        f"- **Chunks with `meta.embedding_error`:** see breakdown below"
    )
    lines.append("")

    def md_kv_table(rows, header):
        if not rows:
            return ["_(no rows)_", ""]
        out = [header, "|" + "|".join(["---"] * len(rows[0])) + "|"]
        for r in rows:
            out.append("| " + " | ".join(str(v) for v in r.values()) + " |")
        return out + [""]

    lines.append("## Chunks by chunk_type")
    lines.append("")
    lines.extend(
        md_kv_table(
            results.get("chunks_by_chunk_type", []),
            "| chunk_type | n |",
        )
    )

    lines.append("## Chunks by meta.source")
    lines.append("")
    lines.extend(
        md_kv_table(
            results.get("chunks_by_meta_source", []),
            "| source | n |",
        )
    )

    lines.append("## Chunks tagged with meta.embedding_error")
    lines.append("")
    lines.extend(
        md_kv_table(
            results.get("chunks_with_embedding_error", []),
            "| embedding_error | n |",
        )
    )

    lines.append("## Cohort: PDF text chunks, content_text non-empty, embedding NULL")
    lines.append("")
    lines.append(
        f"- **Count:** "
        f"{fmt_int(results.get('pdf_text_with_content_but_null_embedding', 0))}"
    )
    lines.append("")

    lines.append("## Cohort: image chunks with asset_path but empty caption")
    lines.append("")
    lines.append(
        f"- **Count:** "
        f"{fmt_int(results.get('image_chunks_with_asset_no_caption', 0))}"
    )
    lines.append("")

    lines.append("## Content-length cohorts")
    lines.append("")
    lines.append(
        f"- **Very short (`len(content_text) < 50`):** "
        f"{fmt_int(results.get('very_short_content_total', 0))}"
    )
    lines.append(
        f"- **Very long  (`len(content_text) > 8000`):** "
        f"{fmt_int(results.get('very_long_content_total', 0))} "
        "(likely contributors to ollama_embed_failed)"
    )
    lines.append("")
    lines.append("### Very-long text chunks per filename")
    lines.append("")
    lines.extend(
        md_kv_table(
            results.get("very_long_text_per_filename", []),
            "| filename | n |",
        )
    )
    lines.append("### Very-short text chunks per filename")
    lines.append("")
    lines.extend(
        md_kv_table(
            results.get("very_short_text_per_filename", []),
            "| filename | n |",
        )
    )

    lines.append("## Metadata coverage")
    lines.append("")
    lines.append(
        f"- **chunks with `meta.heading_path`:** "
        f"{fmt_int(results.get('chunks_with_heading_path', 0))} "
        f"({results.get('heading_path_coverage_pct', '?')}%)"
    )
    lines.append(
        f"- **chunks with `meta.element_type`:** "
        f"{fmt_int(results.get('chunks_with_element_type', 0))} "
        f"({results.get('element_type_coverage_pct', '?')}%)"
    )
    lines.append("")

    lines.append("## Top 10 filenames by missing-embedding count")
    lines.append("")
    lines.extend(
        md_kv_table(
            results.get("top_filenames_missing_embedding", []),
            "| filename | n_missing |",
        )
    )

    lines.append("## Production-visibility gap")
    lines.append("")
    lines.append(
        "rag-gateway's vector search uses `WHERE embedding IS NOT NULL` so any "
        "chunk with a NULL embedding is silently excluded from retrieval. The "
        "table above reports those by filename, and the count is mirrored here:"
    )
    lines.append(
        f"- **Chunks excluded from retrieval (NULL embedding):** "
        f"{fmt_int(results.get('production_excluded_by_null_embedding', 0))}"
    )
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"[report] wrote {md_path.relative_to(Path.cwd())}", file=sys.stderr)
    print(f"[report] wrote {json_path.relative_to(Path.cwd())}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
