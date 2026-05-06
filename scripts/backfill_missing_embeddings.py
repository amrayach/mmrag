#!/usr/bin/env python3
"""Phase 0.5 — Missing-embedding backfill (DRY-RUN BY DEFAULT).

Selects ``rag_chunks`` rows where ``embedding IS NULL`` (optionally further
filtered by ``meta.embedding_error``, filename substring, or chunk_type) and
prints what *would* be re-embedded. To actually write embeddings, pass
``--execute`` explicitly. Defaults to dry-run; never overwrites a non-NULL
embedding without ``--force``; never deletes chunks; preserves
``meta.embedding_error`` history when an attempt fails.

Embedding pipeline:
    text chunks → POST /api/embed to Ollama with the configured
                  ``OLLAMA_EMBED_MODEL`` (bge-m3 by default), 1024-dim vector
    image chunks → only re-embeds if a non-empty caption is present (the
                   embedded text is the caption); skipped otherwise

Usage (dry-run is default — required to be reviewed before --execute):
    python scripts/backfill_missing_embeddings.py
    python scripts/backfill_missing_embeddings.py --doc-filter BMW
    python scripts/backfill_missing_embeddings.py --chunk-type text --limit 5
    python scripts/backfill_missing_embeddings.py --execute --doc-filter BMW

Output: data/eval/phase0_baseline/embedding_backfill_dryrun.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _phase0_utils import (  # noqa: E402
    ensure_venv,
    open_db_connection,
    phase0_baseline_dir,
    now_iso,
    load_env_file,
)

ensure_venv()


def select_chunks(
    cur,
    doc_filter: str | None,
    chunk_type: str | None,
    only_error: str | None,
    limit: int | None,
    force: bool,
):
    where = []
    params: list = []
    if force:
        where.append("(embedding IS NULL OR embedding IS NOT NULL)")
    else:
        where.append("c.embedding IS NULL")
    if only_error:
        where.append("c.meta->>'embedding_error' = %s")
        params.append(only_error)
    if doc_filter:
        where.append("d.filename ILIKE '%%' || %s || '%%'")
        params.append(doc_filter)
    if chunk_type:
        where.append("c.chunk_type = %s")
        params.append(chunk_type)

    sql = (
        "SELECT c.id, d.filename, c.chunk_type, c.page, "
        "       char_length(COALESCE(c.content_text, '')) AS content_chars, "
        "       char_length(COALESCE(c.caption, '')) AS caption_chars, "
        "       c.meta->>'embedding_error' AS embedding_error, "
        "       (c.embedding IS NOT NULL) AS has_embedding "
        "FROM rag_chunks c "
        "JOIN rag_docs d ON c.doc_id = d.doc_id "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY d.filename, c.page, c.id"
    )
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    cur.execute(sql, params)
    cols = [d.name for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_embed_payload(cur, chunk_id: int, chunk_type: str) -> str | None:
    if chunk_type == "image":
        cur.execute(
            "SELECT COALESCE(caption, '') FROM rag_chunks WHERE id = %s",
            (chunk_id,),
        )
    else:
        cur.execute(
            "SELECT COALESCE(content_text, '') FROM rag_chunks WHERE id = %s",
            (chunk_id,),
        )
    row = cur.fetchone()
    if not row:
        return None
    text = (row[0] or "").strip()
    return text or None


def embedding_input(text: str) -> str | None:
    """Mirror services/pdf-ingest/app/main.py::_embedding_input."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    cleaned = re.sub(r"\ufffd+", " ", stripped)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    cleaned_alnum = sum(1 for c in cleaned if c.isalnum())
    if len(cleaned) > 40 and cleaned_alnum / len(cleaned) < 0.20:
        return None
    return cleaned


def ollama_base_url(env: dict[str, str]) -> str:
    """Return a host-reachable Ollama URL or fail clearly."""
    explicit = env.get("OLLAMA_BASE_URL_HOST")
    if explicit:
        return explicit

    configured = env.get("OLLAMA_BASE_URL")
    if configured:
        host = (urlparse(configured).hostname or "").lower()
        if host and host not in {"ollama", "postgres", "n8n"}:
            return configured

    raise RuntimeError(
        "No host-reachable Ollama URL configured. This project does not expose "
        "Ollama on a host port; pass --ollama-host <url> or set "
        "OLLAMA_BASE_URL_HOST before using --execute."
    )


def embed_via_ollama(text: str, env: dict[str, str], timeout: float) -> list[float]:
    import requests  # type: ignore[import-not-found]

    cleaned = embedding_input(text)
    if cleaned is None:
        raise ValueError("empty or gibberish embedding input after ingest cleanup")

    base_url = ollama_base_url(env)
    model = env.get("OLLAMA_EMBED_MODEL", "bge-m3")
    r = requests.post(
        f"{base_url.rstrip('/')}/api/embed",
        json={"model": model, "input": [cleaned]},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    embeddings = data.get("embeddings") or []
    emb = embeddings[0] if embeddings else None
    if not emb:
        raise RuntimeError(f"Ollama returned no embedding: {data}")
    return emb


def write_embedding(cur, chunk_id: int, embedding: list[float], force: bool) -> None:
    # The pgvector adapter accepts list[float] when registered; the script's
    # connection has no register_vector call so we build the literal directly.
    literal = "[" + ",".join(f"{x:.7g}" for x in embedding) + "]"
    guard = "" if force else " AND embedding IS NULL"
    cur.execute(
        "UPDATE rag_chunks "
        "SET embedding = %s::vector, "
        "    meta = (meta - 'embedding_error' - 'embedding_error_at') "
        f"WHERE id = %s{guard}",
        (literal, chunk_id),
    )
    if cur.rowcount != 1:
        raise RuntimeError(
            f"chunk {chunk_id} was not updated; embedding may already be "
            "non-NULL and --force was not provided"
        )


def append_error_history(
    cur, chunk_id: int, new_error: str, ts: str
) -> None:
    """Preserve the prior error in meta.embedding_error_history before
    overwriting meta.embedding_error with the new failure reason."""
    cur.execute(
        "UPDATE rag_chunks "
        "SET meta = jsonb_set("
        "  jsonb_set(meta, "
        "    '{embedding_error_history}', "
        "    COALESCE(meta->'embedding_error_history', '[]'::jsonb) "
        "      || jsonb_build_array(jsonb_build_object("
        "        'error', meta->>'embedding_error', "
        "        'previous_at', meta->>'embedding_error_at')) "
        "  ), "
        "  '{embedding_error}', to_jsonb(%s::text) "
        ") || jsonb_build_object('embedding_error_at', %s::text) "
        "WHERE id = %s "
        "  AND meta ? 'embedding_error'",
        (new_error, ts, chunk_id),
    )
    # If meta has no prior 'embedding_error', set it without history munging.
    cur.execute(
        "UPDATE rag_chunks "
        "SET meta = meta || jsonb_build_object("
        "  'embedding_error', %s::text, "
        "  'embedding_error_at', %s::text) "
        "WHERE id = %s "
        "  AND NOT (meta ? 'embedding_error')",
        (new_error, ts, chunk_id),
    )


def render_md(payload: dict) -> str:
    lines: list[str] = []
    lines.append("# Phase 0.5 — Missing-embedding backfill (dry-run summary)")
    lines.append("")
    lines.append(f"- **Captured at:** {payload['captured_at']}")
    lines.append(f"- **Mode:** {'EXECUTE' if payload['executed'] else 'dry-run'}")
    lines.append(f"- **Filters:** {payload['filters']}")
    lines.append(f"- **Selected chunks:** {len(payload['selected'])}")
    if payload.get("results"):
        lines.append(
            f"- **Re-embedded successfully:** {payload['results']['ok']}"
        )
        lines.append(
            f"- **Failed during re-embedding:** {payload['results']['failed']}"
        )
        lines.append(f"- **Skipped (empty payload):** {payload['results']['skipped']}")
    lines.append("")
    lines.append("## Selection breakdown by filename")
    lines.append("")
    if payload["by_filename"]:
        lines.append("| filename | n_selected | by_error |")
        lines.append("|---|---:|---|")
        for fn, info in payload["by_filename"].items():
            lines.append(f"| {fn} | {info['n']} | {info['by_error']} |")
    lines.append("")
    lines.append("## Selection breakdown by embedding_error value")
    lines.append("")
    if payload["by_error"]:
        lines.append("| embedding_error | n |")
        lines.append("|---|---:|")
        for err, n in payload["by_error"].items():
            lines.append(f"| {err or '<null>'} | {n} |")
    lines.append("")
    lines.append("## Length cohorts (informational only — not filtered out)")
    lines.append("")
    lines.append(
        f"- chunks with `len(content_text) > 8000`: "
        f"{payload['cohorts']['very_long']}"
    )
    lines.append(
        f"- chunks with `len(content_text) < 50`: "
        f"{payload['cohorts']['very_short']}"
    )
    lines.append("")
    lines.append("## First 30 selected chunks")
    lines.append("")
    lines.append(
        "| chunk_id | filename | type | page | chars(text) | chars(caption) | "
        "embedding_error |"
    )
    lines.append("|---:|---|---|---:|---:|---:|---|")
    for r in payload["selected"][:30]:
        lines.append(
            "| {id} | {fn} | {t} | {p} | {c} | {cap} | {e} |".format(
                id=r["id"],
                fn=r["filename"],
                t=r["chunk_type"],
                p=r["page"],
                c=r["content_chars"],
                cap=r["caption_chars"],
                e=r.get("embedding_error") or "",
            )
        )
    if len(payload["selected"]) > 30:
        lines.append(f"_... and {len(payload['selected']) - 30} more_")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument(
        "--execute",
        action="store_true",
        help="Actually write embeddings; otherwise dry-run only.",
    )
    p.add_argument("--doc-filter", default=None)
    p.add_argument("--chunk-type", choices=["text", "image"], default=None)
    p.add_argument("--only-error", default="ollama_embed_failed")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--force",
        action="store_true",
        help="REQUIRED to overwrite an existing non-NULL embedding.",
    )
    p.add_argument(
        "--ollama-host",
        default=None,
        help="Override Ollama host URL (default 127.0.0.1:11434).",
    )
    p.add_argument(
        "--timeout-secs",
        type=float,
        default=30.0,
        help="Per-chunk Ollama embed timeout.",
    )
    args = p.parse_args()

    executed = bool(args.execute)
    env = load_env_file()
    if args.ollama_host:
        env["OLLAMA_BASE_URL_HOST"] = args.ollama_host

    with open_db_connection() as conn, conn.cursor() as cur:
        selected = select_chunks(
            cur,
            doc_filter=args.doc_filter,
            chunk_type=args.chunk_type,
            only_error=args.only_error,
            limit=args.limit,
            force=args.force,
        )

        by_filename: dict[str, dict] = {}
        by_error: dict[str, int] = {}
        very_long = 0
        very_short = 0
        for r in selected:
            fn = r["filename"]
            err = r.get("embedding_error") or "<null>"
            slot = by_filename.setdefault(
                fn, {"n": 0, "by_error": {}}
            )
            slot["n"] += 1
            slot["by_error"][err] = slot["by_error"].get(err, 0) + 1
            by_error[err] = by_error.get(err, 0) + 1
            if (r.get("content_chars") or 0) > 8000:
                very_long += 1
            if (r.get("content_chars") or 0) < 50:
                very_short += 1

        results = None
        if executed:
            ok, failed, skipped = 0, 0, 0
            for r in selected:
                payload_text = fetch_embed_payload(cur, r["id"], r["chunk_type"])
                if not payload_text:
                    skipped += 1
                    continue
                ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
                try:
                    emb = embed_via_ollama(payload_text, env, args.timeout_secs)
                    write_embedding(cur, r["id"], emb, force=args.force)
                    ok += 1
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    try:
                        append_error_history(
                            cur,
                            r["id"],
                            f"{type(exc).__name__}: {exc}",
                            ts,
                        )
                        conn.commit()
                    except Exception:
                        conn.rollback()
                    failed += 1
                # Brief inter-call breather to avoid hammering Ollama.
                time.sleep(0.05)
            results = {"ok": ok, "failed": failed, "skipped": skipped}

    payload = {
        "captured_at": now_iso(),
        "phase": "0.5",
        "executed": executed,
        "filters": {
            "doc_filter": args.doc_filter,
            "chunk_type": args.chunk_type,
            "only_error": args.only_error,
            "limit": args.limit,
            "force": args.force,
        },
        "selected": selected,
        "by_filename": by_filename,
        "by_error": by_error,
        "cohorts": {"very_long": very_long, "very_short": very_short},
        "results": results,
    }

    out_dir = phase0_baseline_dir()
    md_path = out_dir / "embedding_backfill_dryrun.md"
    md_path.write_text(render_md(payload), encoding="utf-8")
    json_path = out_dir / "embedding_backfill_dryrun.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        f"[backfill] mode={'EXECUTE' if executed else 'dry-run'} "
        f"selected={len(selected)} long>8000={very_long} short<50={very_short}",
        file=sys.stderr,
    )
    print(f"[backfill] wrote {md_path.relative_to(Path.cwd())}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
