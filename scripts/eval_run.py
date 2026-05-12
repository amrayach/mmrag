#!/usr/bin/env python3
"""Run a fixed eval prompt set against rag-gateway and persist per-prompt outputs.

Usage:
  scripts/eval_run.py [--prompts data/eval/prompts.json]
                      [--gateway http://127.0.0.1:56155]
                      [--model qwen2.5:7b-instruct]
                      [--label baseline_post_odl]
                      [--only p01_bmw_kennzahlen,p11_followup_deictic]
                      [--repeat 1]
                      [--no-stream]
                      [--prewarm]

Outputs land under data/eval/runs/<timestamp>__<label>/:
  <prompt_id>.json           — full per-prompt record (or <prompt_id>__r<n>.json with --repeat)
  <prompt_id>__turn<k>.json  — per-turn record for multi-turn prompts
  summary.json               — aggregate stats and per-prompt timings
  scorecard.md               — manual rubric template, ready to fill in
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit(
        "FATAL: this script needs the 'requests' library. Install with:\n"
        "  pip install --user requests"
    )

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPTS = ROOT / "data" / "eval" / "prompts.json"
RUNS_DIR = ROOT / "data" / "eval" / "runs"
DEFAULT_TRACE_PATH = ROOT / "data" / "rag-traces" / "retrieval.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_id(label: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)[:60] or "run"
    return f"{ts}__{safe_label}"


# Suffix from rag-gateway looks like:
#   ...answer text...
#
#   ![caption](url)
#   ![caption2](url2)
#
#   Quellen:
#   - markdown-formatted source 1
#   - markdown-formatted source 2
IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
SOURCES_BLOCK_RE = re.compile(r"(?ms)^Quellen:\s*\n((?:- .+\n?)+)")


def parse_suffix(text: str) -> tuple[list[dict], list[str], str]:
    """Extract image_objects and sources from the gateway-appended suffix.

    Returns (image_objects, sources, body_text_with_suffix_stripped).
    """
    images = [{"caption": m.group(1), "url": m.group(2)} for m in IMG_RE.finditer(text)]

    sources: list[str] = []
    sm = SOURCES_BLOCK_RE.search(text)
    if sm:
        for line in sm.group(1).splitlines():
            line = line.strip()
            if line.startswith("- "):
                sources.append(line[2:].strip())

    body = text
    if sm:
        body = body[: sm.start()].rstrip()
    body = IMG_RE.sub("", body).rstrip()
    return images, sources, body


def stream_chat(
    gateway: str, model: str, messages: list[dict], temperature: float, max_tokens: int
) -> dict:
    """Send a streaming chat request, capture TTFT and full content."""
    url = f"{gateway.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    started = time.monotonic()
    ttft_ms = None
    content_parts: list[str] = []
    sse_events = 0
    error = None

    try:
        with requests.post(url, json=payload, stream=True, timeout=(10, 600)) as r:
            r.raise_for_status()
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                if not raw.startswith("data:"):
                    continue
                data = raw[len("data:") :].strip()
                if data == "[DONE]":
                    continue
                sse_events += 1
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                chunk = delta.get("content")
                if chunk:
                    if ttft_ms is None:
                        ttft_ms = int((time.monotonic() - started) * 1000)
                    content_parts.append(chunk)
    except requests.RequestException as exc:
        error = f"{type(exc).__name__}: {exc}"

    total_ms = int((time.monotonic() - started) * 1000)
    full = "".join(content_parts)
    images, sources, body = parse_suffix(full)
    return {
        "ttft_ms": ttft_ms,
        "total_latency_ms": total_ms,
        "sse_events": sse_events,
        "answer_full": full,
        "answer_body": body,
        "answer_chars": len(body),
        "answer_lines": body.count("\n") + 1 if body else 0,
        "image_objects": images,
        "sources": sources,
        "error": error,
    }


def nonstream_chat(
    gateway: str, model: str, messages: list[dict], temperature: float, max_tokens: int
) -> dict:
    url = f"{gateway.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    started = time.monotonic()
    error = None
    answer = ""
    try:
        r = requests.post(url, json=payload, timeout=(10, 600))
        r.raise_for_status()
        body = r.json()
        answer = body["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    total_ms = int((time.monotonic() - started) * 1000)
    images, sources, clean = parse_suffix(answer)
    return {
        "ttft_ms": None,
        "total_latency_ms": total_ms,
        "sse_events": 0,
        "answer_full": answer,
        "answer_body": clean,
        "answer_chars": len(clean),
        "answer_lines": clean.count("\n") + 1 if clean else 0,
        "image_objects": images,
        "sources": sources,
        "error": error,
    }


def run_prompt(
    prompt: dict, gateway: str, model: str, temperature: float, max_tokens: int, stream: bool
) -> dict:
    """Run all turns of a prompt, threading the conversation."""
    turns_out = []
    messages: list[dict] = []
    for idx, turn in enumerate(prompt["turns"], start=1):
        user_text = turn["user"]
        messages.append({"role": "user", "content": user_text})
        chat_fn = stream_chat if stream else nonstream_chat
        result = chat_fn(gateway, model, messages, temperature, max_tokens)
        result.update(
            {
                "prompt_id": prompt["id"],
                "turn": idx,
                "user_text": user_text,
                "started_at": now_iso(),
                "model": model,
                "temperature": temperature,
                "stream": stream,
            }
        )
        turns_out.append(result)
        if result.get("error"):
            break
        # Thread the assistant reply (without the appended suffix) into the next turn.
        messages.append({"role": "assistant", "content": result["answer_body"]})
    return {
        "prompt_id": prompt["id"],
        "category": prompt.get("category"),
        "intent": prompt.get("intent"),
        "expects_filter": prompt.get("expects_filter"),
        "expects_sources_from": prompt.get("expects_sources_from"),
        "rubric_focus": prompt.get("rubric_focus", []),
        "turns": turns_out,
    }


def write_run_files(out_dir: Path, prompt_id: str, repeat: int | None, record: dict) -> None:
    suffix = f"__r{repeat}" if repeat is not None else ""
    if len(record["turns"]) == 1:
        path = out_dir / f"{prompt_id}{suffix}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        for t in record["turns"]:
            path = out_dir / f"{prompt_id}{suffix}__turn{t['turn']}.json"
            path.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
        # Always write a combined view too.
        combined = out_dir / f"{prompt_id}{suffix}.json"
        combined.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def write_summary(out_dir: Path, run_meta: dict, records: list[dict]) -> None:
    rows = []
    for rec in records:
        for t in rec["turns"]:
            rows.append(
                {
                    "prompt_id": rec["prompt_id"],
                    "turn": t["turn"],
                    "category": rec["category"],
                    "ttft_ms": t["ttft_ms"],
                    "total_latency_ms": t["total_latency_ms"],
                    "answer_chars": t["answer_chars"],
                    "answer_lines": t["answer_lines"],
                    "sse_events": t["sse_events"],
                    "n_images": len(t["image_objects"]),
                    "n_sources": len(t["sources"]),
                    "error": t["error"],
                }
            )

    def avg(key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    summary = {
        "run": run_meta,
        "num_prompts": len(records),
        "num_turns": len(rows),
        "num_errors": sum(1 for r in rows if r["error"]),
        # Phase 0.7 surfaces RAG_TRACE state at the summary top level too,
        # mirroring the spec wording (rag_trace_enabled / rag_trace_path /
        # trace_record_count) so downstream metric scripts and reviewers can
        # find them without descending into run_meta.
        "rag_trace_enabled": bool(run_meta.get("rag_trace_enabled")),
        "rag_trace_path": run_meta.get("rag_trace_path"),
        "rag_trace_captured_path": run_meta.get("rag_trace_run_path"),
        "trace_record_count": int(run_meta.get("rag_trace_record_count") or 0),
        "averages": {
            "ttft_ms": avg("ttft_ms"),
            "total_latency_ms": avg("total_latency_ms"),
            "answer_chars": avg("answer_chars"),
            "answer_lines": avg("answer_lines"),
            "n_sources": avg("n_sources"),
            "n_images": avg("n_images"),
        },
        "rows": rows,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


SCORECARD_HEADER = """# Eval scorecard — {run_label}

- **Run dir:** `{run_dir}`
- **Started:** {started_at}
- **Model:** `{model}`
- **Gateway:** `{gateway}`
- **Stream:** `{stream}`
- **Prompts file:** `{prompts_file}`

## Rubric

Score each axis 1–5 (1 = unusable, 3 = acceptable, 5 = excellent).

| Axis | Meaning |
|---|---|
| faith. | Faithfulness — every claim is supported by retrieved context |
| compl. | Completeness — covers everything the context contains |
| cite | Citation — sources/images are correct and useful |
| lang | Language — output language matches user; German is fluent |
| rep | Repetition — no looping or duplicate bullets |
| struct | Structure — sensible structure, lists where lists belong |

## Per-prompt scores (fill in manually)

| ID | Category | TTFT ms | Total ms | Chars | #src | #img | faith. | compl. | cite | lang | rep | struct | Notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"""


def write_scorecard(
    out_dir: Path, run_meta: dict, records: list[dict], prompts_file: Path
) -> None:
    lines = [
        SCORECARD_HEADER.format(
            run_label=run_meta["label"],
            run_dir=str(out_dir.relative_to(ROOT)),
            started_at=run_meta["started_at"],
            model=run_meta["model"],
            gateway=run_meta["gateway"],
            stream=run_meta["stream"],
            prompts_file=str(Path(prompts_file).relative_to(ROOT)),
        )
    ]
    for rec in records:
        for t in rec["turns"]:
            label = rec["prompt_id"] if len(rec["turns"]) == 1 else f"{rec['prompt_id']}/t{t['turn']}"
            lines.append(
                "| {label} | {cat} | {ttft} | {tot} | {chars} | {nsrc} | {nimg} |  |  |  |  |  |  |  |".format(
                    label=label,
                    cat=rec.get("category", ""),
                    ttft=t["ttft_ms"] if t["ttft_ms"] is not None else "—",
                    tot=t["total_latency_ms"],
                    chars=t["answer_chars"],
                    nsrc=len(t["sources"]),
                    nimg=len(t["image_objects"]),
                )
            )
    lines.append("")
    lines.append("## Free-form observations")
    lines.append("")
    lines.append("- Repetition patterns:")
    lines.append("- List truncation:")
    lines.append("- Wrong-language outputs:")
    lines.append("- Wrong-source citations:")
    lines.append("- BMW unembedded-chunk symptoms:")
    lines.append("")
    (out_dir / "scorecard.md").write_text("\n".join(lines), encoding="utf-8")


def maybe_prewarm() -> None:
    script = ROOT / "scripts" / "prewarm.sh"
    if not script.exists():
        raise RuntimeError("scripts/prewarm.sh not found")
    print("[prewarm] running scripts/prewarm.sh", file=sys.stderr)
    try:
        subprocess.run(["bash", str(script)], check=True, timeout=300)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"prewarm failed: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("prewarm timed out after 300s") from e


def collect_ollama_ps() -> dict:
    """Return Ollama /api/ps for run evidence; never raises."""
    try:
        ip = subprocess.check_output(
            [
                "docker", "inspect", "-f",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                "ammer_mmragv2_ollama",
            ],
            cwd=ROOT,
            text=True,
            timeout=5,
        ).strip()
        if not ip:
            return {"error": "ammer_mmragv2_ollama has no container IP"}
        r = requests.get(f"http://{ip}:11434/api/ps", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def assert_resident_model_on_gpu(model: str, ps: dict) -> None:
    """Fail evals when the target model is known to be resident on CPU."""
    if ps.get("error"):
        raise RuntimeError(f"could not collect Ollama GPU residency: {ps['error']}")

    wanted = {model}
    if ":" not in model:
        wanted.add(f"{model}:latest")

    for item in ps.get("models", []):
        names = {item.get("name", ""), item.get("model", "")}
        if names & wanted:
            if int(item.get("size_vram") or 0) <= 0:
                raise RuntimeError(
                    f"{model} is resident but size_vram=0; refusing CPU-fallback eval"
                )
            return

    raise RuntimeError(f"{model} is not resident after prewarm; refusing cold/ambiguous eval")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prompts", default=str(DEFAULT_PROMPTS))
    p.add_argument("--gateway", default="http://127.0.0.1:56155")
    p.add_argument("--model", default=None, help="overrides default_model in prompts.json")
    p.add_argument("--label", default="baseline_post_odl")
    p.add_argument("--only", default=None, help="comma-separated list of prompt IDs")
    p.add_argument("--repeat", type=int, default=1, help="repeat each selected prompt N times")
    p.add_argument("--no-stream", action="store_true", help="use non-streaming endpoint")
    p.add_argument("--prewarm", action="store_true", help="run scripts/prewarm.sh first")
    p.add_argument(
        "--rag-trace-path",
        default=str(DEFAULT_TRACE_PATH),
        help=(
            "Host path to the rag-gateway RAG_TRACE JSONL file. When set, the "
            "harness snapshots the file size before the run and copies records "
            "appended during the run into <run_dir>/traces/retrieval.jsonl. "
            "Has no effect when RAG_TRACE is disabled in the gateway."
        ),
    )
    p.add_argument(
        "--no-rag-trace-capture",
        action="store_true",
        help="Disable trace capture even if RAG_TRACE is enabled on the gateway.",
    )
    args = p.parse_args()

    prompts_path = Path(args.prompts)
    spec = json.loads(prompts_path.read_text(encoding="utf-8"))
    model = args.model or spec.get("default_model", "qwen2.5:7b-instruct")
    temperature = spec.get("default_temperature", 0.2)
    max_tokens = spec.get("default_max_tokens", 800)
    stream = not args.no_stream and spec.get("default_stream", True)

    selected = spec["prompts"]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        selected = [p_ for p_ in selected if p_["id"] in wanted]
        missing = wanted - {p_["id"] for p_ in selected}
        if missing:
            print(f"WARN: unknown prompt IDs: {sorted(missing)}", file=sys.stderr)
    if not selected:
        print("ERROR: no prompts selected", file=sys.stderr)
        return 2

    if args.prewarm:
        try:
            maybe_prewarm()
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

    ollama_ps_at_start = collect_ollama_ps()
    if args.prewarm:
        try:
            assert_resident_model_on_gpu(model, ollama_ps_at_start)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

    run_dir = RUNS_DIR / run_id(args.label)
    run_dir.mkdir(parents=True, exist_ok=True)

    # RAG_TRACE capture: snapshot the existing trace file size before the run
    # so we can later copy only the lines appended during this run.
    trace_path = (
        Path(args.rag_trace_path) if args.rag_trace_path else None
    )
    trace_capture_enabled = bool(trace_path) and not args.no_rag_trace_capture
    trace_offset_at_start = 0
    if trace_capture_enabled and trace_path and trace_path.exists():
        trace_offset_at_start = trace_path.stat().st_size

    run_meta = {
        "label": args.label,
        "started_at": now_iso(),
        "model": model,
        "gateway": args.gateway,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "repeat": args.repeat,
        "prompts_file": str(prompts_path.relative_to(ROOT)) if prompts_path.is_relative_to(ROOT) else str(prompts_path),
        "prewarm": args.prewarm,
        "ollama_ps_at_start": ollama_ps_at_start,
        "rag_trace_path": (
            str(trace_path.relative_to(ROOT))
            if trace_path and trace_path.is_relative_to(ROOT)
            else (str(trace_path) if trace_path else None)
        ),
        "rag_trace_capture_enabled": trace_capture_enabled,
        "rag_trace_offset_at_start": trace_offset_at_start,
    }
    (run_dir / "run.json").write_text(
        json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[run] {run_dir.relative_to(ROOT)}", file=sys.stderr)
    print(
        f"[run] model={model} stream={stream} prompts={len(selected)} repeat={args.repeat}",
        file=sys.stderr,
    )

    all_records: list[dict] = []
    for prompt in selected:
        for r in range(1, args.repeat + 1):
            tag = f"r{r}/{args.repeat}" if args.repeat > 1 else ""
            print(f"[run] {prompt['id']} {tag}".rstrip(), file=sys.stderr, flush=True)
            record = run_prompt(prompt, args.gateway, model, temperature, max_tokens, stream)
            write_run_files(run_dir, prompt["id"], r if args.repeat > 1 else None, record)
            all_records.append(record)
            for t in record["turns"]:
                if t["error"]:
                    print(
                        f"  ! turn{t['turn']} ERROR: {t['error']}", file=sys.stderr, flush=True
                    )
                else:
                    print(
                        "  turn{turn}: ttft={ttft}ms total={tot}ms chars={c} src={s} img={i}".format(
                            turn=t["turn"],
                            ttft=t["ttft_ms"] if t["ttft_ms"] is not None else "—",
                            tot=t["total_latency_ms"],
                            c=t["answer_chars"],
                            s=len(t["sources"]),
                            i=len(t["image_objects"]),
                        ),
                        file=sys.stderr,
                        flush=True,
                    )

    # Capture the slice of trace records appended during this run.
    rag_trace_enabled = False
    rag_trace_record_count = 0
    rag_trace_run_path: str | None = None
    if trace_capture_enabled and trace_path and trace_path.exists():
        try:
            new_size = trace_path.stat().st_size
            if new_size > trace_offset_at_start:
                with trace_path.open("rb") as src:
                    src.seek(trace_offset_at_start)
                    payload = src.read(new_size - trace_offset_at_start)
                traces_dir = run_dir / "traces"
                traces_dir.mkdir(parents=True, exist_ok=True)
                out_file = traces_dir / "retrieval.jsonl"
                out_file.write_bytes(payload)
                rag_trace_record_count = sum(
                    1 for line in payload.splitlines() if line.strip()
                )
                rag_trace_enabled = rag_trace_record_count > 0
                rag_trace_run_path = str(out_file.relative_to(ROOT))
        except OSError as exc:
            print(f"[run] WARN: failed to capture trace records: {exc}", file=sys.stderr)

    run_meta["rag_trace_enabled"] = rag_trace_enabled
    run_meta["rag_trace_record_count"] = rag_trace_record_count
    run_meta["rag_trace_run_path"] = rag_trace_run_path
    (run_dir / "run.json").write_text(
        json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_summary(run_dir, run_meta, all_records)
    write_scorecard(run_dir, run_meta, all_records, prompts_path)
    print(f"[run] done. summary: {run_dir.relative_to(ROOT)}/summary.json", file=sys.stderr)
    print(f"[run] scorecard: {run_dir.relative_to(ROOT)}/scorecard.md", file=sys.stderr)
    if rag_trace_enabled:
        print(
            f"[run] traces:    {rag_trace_run_path} "
            f"({rag_trace_record_count} record(s))",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
