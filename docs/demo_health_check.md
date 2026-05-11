# Demo End-to-End Health Check

This check is a host-side smoke test for the local `ammer-mmragv2` demo stack.
It proves the RAG path is usable, not just that containers exist.

## What This Checks

Required checks fail the run and return a non-zero exit code:

| ID | Check | Required | Purpose |
|---|---|:---:|---|
| R1 | Disk space | Y | Verifies the filesystem hosting `/srv` has more than `DEMO_HEALTH_MIN_DISK_GB` free, default 5 GB. |
| R2 | Compose services | Y | Reads `docker compose ps --format json` and verifies `rag-gateway`, `postgres`, and `ollama` are running and healthy when a health state exists. Optional services are reported only. |
| R3 | Health endpoints | Y | Probes `rag-gateway /health` and runs `SELECT 1` against Postgres through `docker compose exec -T postgres psql`. OpenWebUI `/` is optional and reported separately. |
| R4 | Ollama models | Y | Uses the project Ollama container, not host `127.0.0.1:11434`, and verifies `bge-m3` plus the active generation model are available. Loaded/resident state is not required. |
| R5 | Embedding spot-check | Y | Calls project Ollama `/api/embed` for `bge-m3` and verifies one non-zero 1024-dimensional vector. |
| R6 | Trace directory writable | Y | Writes and removes `data/rag-traces/.health_write_test`, needed for later retrieval trace comparisons. |
| R7 | RAG query | Y | Sends the golden query through `/v1/chat/completions` with `stream=false`, `temperature=0`, and `max_tokens=180`; requires an answer, source links, and latency under budget. |
| R8 | Ollama text-model GPU placement | Y | Runs after the RAG query, reads `docker compose exec -T ollama ollama ps`, and verifies the active generation model is mostly on GPU. `>=90% GPU` passes, `50-89% GPU` warns, and `<50% GPU` fails by default. |
| R9 | Recent ingest activity | N | Reads `MAX(created_at)` from `rag_chunks` when that column exists; warns if newest content is older than seven days and reports SKIP if the current schema has no `created_at` column. |

## What This Does Not Check

- Multi-turn answer quality.
- Semantic correctness of the answer.
- Hybrid retrieval, reranking, metadata prefixing, or contextual retrieval.
- RSS feed freshness or external RSS availability.
- Tailscale Serve/Funnel reachability.
- Public demo website status.
- GPU throughput benchmarking. The check does verify active text-model placement in Ollama after the RAG query loads the model.
- Any ingestion, DB mutation, schema state, or document freshness beyond the warning-only newest chunk timestamp.

## Manual Run

From the repository root:

```bash
python3 scripts/demo_e2e_check.py
```

Expected stdout shape:

```text
DEMO_E2E_STATUS=PASS
duration_ms=...
latest_json=data/eval/demo_health/latest.json
latest_md=data/eval/demo_health/latest.md
selected_query_id=p01
selected_model=gemma4:26b
disk_space=PASS latency_ms=...
...
```

The script writes:

```text
data/eval/demo_health/latest.json
data/eval/demo_health/latest.md
data/eval/demo_health/history/<YYYYMMDDTHHMMSS>_health.json
data/eval/demo_health/history/<YYYYMMDDTHHMMSS>_health.md
```

Generated runtime reports are ignored by git.

## Reading latest.json

Important fields:

- `status`: `PASS` or `FAIL`.
- `duration_ms`: total runtime.
- `last_pass_ts`: timestamp of the most recent successful check.
- `selected_query_id`: the golden query ID.
- `selected_model`: active model used for the RAG query.
- `checks`: per-check status, latency, and details.
- `failed_check`: first required check that failed.
- `failure_reason`: concise reason for the first required failure.
- `warnings`: warning-only findings such as stale ingest activity.

A regression usually appears as a changed `failed_check`, a rising `rag_query`
latency, fewer detected sources, CPU placement for the active text model, or a
stale `last_pass_ts`.

## Reading latest.md

`latest.md` is a short operator-facing summary suitable to forward internally.
It includes overall status, timestamp, last successful pass, a per-check table,
RAG query latency/source detection, warnings, and the suggested next action
when failed.

## last_pass_ts

On a successful run, `last_pass_ts` is set to the current timestamp. On a failed
run, the script keeps the previous successful timestamp. This answers the
operator question: "when was the demo last known good?"

## Scheduling Hourly With Cron

Do not enable this until the check has been observed stable for several days.
Paste-ready crontab line:

```cron
17 * * * * cd /srv/projects/ammer/mmrag-n8n-demo-v2 && /usr/bin/python3 scripts/demo_e2e_check.py >> data/eval/demo_health/notifications.log 2>&1
```

## Scheduling Hourly With systemd User Timer

Do not install this in the current session. If approved later, create:

`~/.config/systemd/user/mmrag-demo-health.service`

```ini
[Unit]
Description=MMRAG demo end-to-end health check

[Service]
Type=oneshot
WorkingDirectory=/srv/projects/ammer/mmrag-n8n-demo-v2
ExecStart=/usr/bin/python3 /srv/projects/ammer/mmrag-n8n-demo-v2/scripts/demo_e2e_check.py
```

`~/.config/systemd/user/mmrag-demo-health.timer`

```ini
[Unit]
Description=Run MMRAG demo health check hourly

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

Manual enable command, only after approval:

```bash
systemctl --user daemon-reload
systemctl --user enable --now mmrag-demo-health.timer
```

## Adding Alerting Later

Real alerting is deferred until the check is stable for several days. The
current `scripts/demo_e2e_check_notify.sh` stub only appends to
`data/eval/demo_health/notifications.log` and exits 0.

Later options:

1. `mail`: send a local email when `latest.json.status == FAIL`.
2. `ntfy.sh`: send a push notification to an approved topic.
3. Generic webhook: POST a small redacted payload to `DEMO_HEALTH_ALERT_WEBHOOK`.

Do not enable external alerting until false positives are understood.

## History Retention

No automatic rotation is installed. Manual cleanup pattern:

```bash
find /srv/projects/ammer/mmrag-n8n-demo-v2/data/eval/demo_health/history \
  -type f -name '*_health.*' -mtime +30 -delete
```

Adjust `+30` to the desired retention window.

## Environment Variables

- `DEMO_HEALTH_TIMEOUT_SECS`: default `60`.
- `DEMO_HEALTH_MODEL`: override the generation model.
- `DEMO_HEALTH_QUERY`: override the golden query text.
- `DEMO_HEALTH_GATEWAY_URL`: override the inferred local gateway URL.
- `DEMO_HEALTH_MIN_DISK_GB`: default `5`.
- `DEMO_HEALTH_REQUIRE_TEXT_GPU`: default `true`. When `false`, CPU-only or
  partial-CPU text-model placement is reported as WARN instead of FAIL. This is
  intended for CPU-only development environments, not demo readiness.
- `DEMO_HEALTH_ALERT_WEBHOOK`: documented for later; real webhook calls are not implemented in this session.

## Recovery Procedures

### Ollama Text Model Falls Back To CPU

Symptom:

```text
docker compose exec ollama ollama ps
gemma4:26b  ...  100% CPU
bge-m3      ...  100% GPU
```

Related logs can include `offloaded 0/31 layers to GPU`. In the observed
incident, host CUDA and the embedding model were healthy; the problem was
Ollama scheduler state corruption rather than actual VRAM shortage.

Recovery:

```bash
docker compose restart ollama
sleep 20

# Send one warm-up request through rag-gateway so the text model loads.
curl -sS -H "Content-Type: application/json" \
  -d '{"model":"gemma4:26b","messages":[{"role":"user","content":"Kurz antworten."}],"max_tokens":1}' \
  http://127.0.0.1:56155/v1/chat/completions >/dev/null

docker compose exec ollama ollama ps
```

Verify that the active text-generation model shows `100% GPU` or at least
`>=90% GPU`. Then rerun:

```bash
python3 scripts/demo_e2e_check.py
```

## Known Limitations

- The RAG check validates answer shape, source links, and latency, not semantic correctness.
- Optional services can be down without failing the RAG-path health check.
- Model availability is checked via `/api/tags`; loaded placement is checked separately after `rag_query`.
- The script uses Docker CLI read-only inspection and exec calls, so it requires local Docker permissions.
- The current `rag_chunks` schema has no `created_at` column, so the optional recent-ingest check reports SKIP rather than PASS/WARN.
- The golden query is p01 because it is historically stable; it is not intended to exercise known weak retrieval cases such as p04.
