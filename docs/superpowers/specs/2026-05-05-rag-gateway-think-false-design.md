# rag-gateway: explicit `think: false` for Qwen3 / Qwen3.6 — Design

**Status:** Spec only. No code change planned in this phase.
**Date:** 2026-05-05
**Scope:** Surface the Ollama `think` field at the top level of the request body that `rag-gateway` sends to `/api/chat`, default it to `false`, and make it overridable. Required before benchmarking thinking-capable Ollama models against the post-ODL baseline; not required to ship the current 7B demo.

## 1. Why this exists

Ollama added a top-level `think` field to `/api/chat` and `/api/generate`. For thinking-capable models (Qwen3 / Qwen3.5 / Qwen3.6, gpt-oss, etc.), thinking is **on by default** — the model emits a chain of reasoning before any user-visible content. The reasoning trace lands in `message.thinking`, and only the final answer in `message.content`.

`rag-gateway` currently:
- POSTs to `{OLLAMA_BASE_URL}/api/chat` with `chat_body` (model, messages, options.num_ctx, etc.) plus `stream: True`.
- Reads `message.content` from each NDJSON line and ignores `message.thinking`.

If we benchmark `qwen3.6:27b` or `qwen3:30b` without sending `think: false`, two things happen:
1. **TTFT is artificially inflated** — the user-visible first token only appears after the full reasoning trace, which can run hundreds of tokens.
2. **Streamed content is silently empty for the first N seconds** — looks like a stall to demo viewers and to the eval harness.

This is a benchmark-fairness issue, not a model-quality issue. The fix is a one-field addition.

## 2. Scope

### In
- Add `think` to the JSON payload sent by `_stream_from_ollama` and `_call_ollama_sync` (`services/rag-gateway/app/main.py`).
- Add an `OLLAMA_THINK` env var (default `"false"`) read at module load time.
- Pass `think` at the **top level** of the request body — sibling of `model`, `messages`, `stream`. **Not** inside `options`. Ollama's chat API treats `think` as a request-level flag; nesting it under `options` is silently ignored.
- Continue to read only `message.content` for streaming output. `message.thinking` is dropped on the floor for now.

### Out
- Surfacing the reasoning trace to OpenWebUI / Control Center / SSE consumers.
- Per-request override via the OpenAI-compat request body (no `think` field in `ChatRequest`). The env-driven default is enough for the benchmark.
- Auto-detecting whether the model is thinking-capable. Always send `think: false` by default; harmless on non-thinking models.
- Long-context tuning. `OLLAMA_NUM_CTX` is a separate later concern (the gateway currently builds requests with `num_ctx: 4096`, which underuses Qwen3.6's 256K).

## 3. Behavior

| `OLLAMA_THINK` env | Sent to Ollama        | Effect on thinking-capable models |
| ------------------ | --------------------- | --------------------------------- |
| unset / `"false"`  | `"think": false`      | reasoning suppressed, content streams immediately |
| `"true"`           | `"think": true`       | reasoning runs, then content streams |
| `"low"` / `"medium"` / `"high"` | `"think": "<level>"` | per Ollama gpt-oss-style reasoning levels |

For the benchmark phase we only need `false` and `true`. The string-level support is a "nice to have" we can add later without a breaking change.

## 4. Implementation sketch (one place to read)

In `services/rag-gateway/app/main.py`, near the other `os.getenv(...)` config lines:

```python
def _parse_think_env() -> bool | str:
    raw = os.getenv("OLLAMA_THINK", "false").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no", ""):
        return False
    return raw  # "low" / "medium" / "high" or any future Ollama-supported string
```

In both `_stream_from_ollama` and `_call_ollama_sync`, when building the body sent to `/api/chat`, add the field once, top-level:

```python
body = {**chat_body, "stream": True, "think": OLLAMA_THINK_VALUE}
```

(Or set `"think"` in `chat_body` upstream once it's built — same effect; the point is the field is sibling of `messages`, not a child of `options`.)

In `docker-compose.yml`, leave `OLLAMA_THINK` unset by default. The env var is read at gateway startup; no per-request plumbing.

## 5. Validation plan (small, model-phase only)

When this lands and the candidate text models are pulled:

1. `OLLAMA_TEXT_MODEL=qwen3.6:27b`, `OLLAMA_THINK=false`, restart `rag-gateway`.
2. Re-run `scripts/eval_run.py --label qwen3_6_27b_nothink --prewarm`.
3. Compare to `data/eval/runs/20260505_190437__baseline_post_odl/`:
   - TTFT should remain in the same order of magnitude as the 7B baseline (~1 s warm).
   - Total latency will grow with the model size, but not because of thinking overhead.
4. Optionally `OLLAMA_THINK=true` for the same model + same harness → expect TTFT to spike by seconds.
5. Promote the winner only after both the non-thinking baseline run AND the standard run are scored.

## 6. Rollback

The default behavior sends `"think": false` — `OLLAMA_THINK` unset, empty, or `false` all map to `False` in the parser. To enable thinking on a thinking-capable model, set `OLLAMA_THINK=true` (or `low`/`medium`/`high` for gpt-oss-style reasoning levels). Reverting to the pre-patch wire format — no `think` field at all — requires reverting the patch itself, not just unsetting the env var. Older Ollama servers ignore unknown top-level fields, so this rollback path is only relevant if a regression is observed against a specific Ollama build.

## 7. Out-of-scope follow-ups (for a separate spec when needed)

- **Long context for Qwen3.6:** add `OLLAMA_NUM_CTX` and surface it via env. The current hard-coded `4096` in `chat_body` will cap Qwen3.6's value-add for long PDFs.
- **Reasoning trace exposure:** capture `message.thinking` and surface it in a debug-only Control Center panel for prompt-engineering work.
- **Per-request override:** add `think` to the OpenAI-compat `ChatRequest` for OpenWebUI to pass through if a user wants to experiment.

## 8. References

- Ollama thinking docs: `https://ollama.com/blog/thinking` and `https://docs.ollama.com/capabilities/thinking`
- Project baseline this benchmark will compare against: `data/eval/runs/20260505_190437__baseline_post_odl/`
- Eval harness: `scripts/eval_run.py` + `data/eval/prompts.json`
- Project memory: `project_post_odl_baseline_eval.md` (three findings that shape A/B priorities)
