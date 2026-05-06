# Phase 1.0 Gate Plan

Status: plan only. No files were staged, no commit was made, no Docker state
was changed, and no embedding backfill was executed.

## Gate A — Curated Checkpoint Commit Plan

The worktree contains Phase 0 / Phase 1.0 diagnostic work mixed with unrelated
demo/runtime changes. Do not make a broad commit.

### Current Dirty Summary

Read-only checks run:

```bash
git status --short
git diff --stat
```

`git diff --stat` currently reports modified tracked files:

```text
.gitignore
CLAUDE.md
MANUAL_STEPS.md
docker-compose.yml
docs/DEMO_REVIEW_AGENDA.md
scripts/demo_mode.sh
scripts/demo_readiness_check.sh
scripts/eval_run.py
scripts/prewarm.sh
services/controlcenter/app/static/js/pages/overview.js
services/rag-gateway/app/context.py
services/rag-gateway/app/main.py
```

There are also untracked Phase 0 outputs, untracked eval-run directories, and
one untracked `scripts/TechVision_AG_Jahresbericht_2025.pdf`.

### Proposed Include List

Whole-file stage these files if the checkpoint commit is approved:

```text
services/rag-gateway/app/trace.py
services/rag-gateway/app/context.py
services/rag-gateway/app/main.py
scripts/_phase0_utils.py
scripts/report_rag_index_integrity.py
scripts/diagnose_bmw_p04.py
scripts/audit_bmw_p04_evidence_quality.py
scripts/backfill_missing_embeddings.py
scripts/eval_retrieval_metrics.py
data/eval/gold_chunks.template.json
data/eval/gold_chunks.phase0.json
data/eval/phase0_baseline/baseline_state.md
data/eval/phase0_baseline/baseline_state.json
data/eval/phase0_baseline/index_integrity_report.md
data/eval/phase0_baseline/index_integrity_report.json
data/eval/phase0_baseline/bmw_p04_diagnostic.md
data/eval/phase0_baseline/bmw_p04_diagnostic.json
data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.md
data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.json
data/eval/phase0_baseline/embedding_backfill_dryrun.md
data/eval/phase0_baseline/embedding_backfill_dryrun.json
data/rag-traces/.gitkeep
docs/plans/retrieval_phase1_metadata_prefix_plan.md
docs/phase0_summary.md
docs/phase0_external_review_report.md
docs/phase1_0_preliminary_report.md
docs/phase1_0_gate_plan.md
```

Stage these files hunk-by-hunk, not as whole files:

```text
.gitignore
docker-compose.yml
scripts/eval_run.py
```

Hunks to include:

- `.gitignore`
  - include `.venv-phase0/`
  - include `data/rag-traces/*`
  - include `!data/rag-traces/.gitkeep`
  - exclude `backups/` unless the user explicitly wants it in this checkpoint
- `docker-compose.yml`
  - include only the `rag-gateway` `RAG_TRACE` / `RAG_TRACE_PATH` env vars
  - include only the `./data/rag-traces:/data/rag-traces` mount
  - exclude Ollama demo-performance env changes
  - exclude OpenWebUI image / secret changes
- `scripts/eval_run.py`
  - include `DEFAULT_TRACE_PATH`
  - include `--rag-trace-path`
  - include `--no-rag-trace-capture`
  - include trace offset/capture/run metadata and `summary.json` fields
  - exclude unrelated prewarm/GPU-residency behavior changes

### Proposed Exclude List

Do not include these in the Phase 0 / Phase 1.0 checkpoint:

```text
CLAUDE.md
MANUAL_STEPS.md
docs/DEMO_REVIEW_AGENDA.md
scripts/demo_mode.sh
scripts/demo_readiness_check.sh
scripts/prewarm.sh
services/controlcenter/app/static/js/pages/overview.js
scripts/TechVision_AG_Jahresbericht_2025.pdf
data/eval/runs/
data/rag-traces/retrieval.jsonl
```

Also exclude the non-Phase-0 hunks listed above in `.gitignore`,
`docker-compose.yml`, and `scripts/eval_run.py`.

### Proposed Staging Commands

Use explicit file staging for whole-file includes:

```bash
git add \
  services/rag-gateway/app/trace.py \
  services/rag-gateway/app/context.py \
  services/rag-gateway/app/main.py \
  scripts/_phase0_utils.py \
  scripts/report_rag_index_integrity.py \
  scripts/diagnose_bmw_p04.py \
  scripts/audit_bmw_p04_evidence_quality.py \
  scripts/backfill_missing_embeddings.py \
  scripts/eval_retrieval_metrics.py \
  data/eval/gold_chunks.template.json \
  data/eval/gold_chunks.phase0.json \
  data/eval/phase0_baseline/baseline_state.md \
  data/eval/phase0_baseline/baseline_state.json \
  data/eval/phase0_baseline/index_integrity_report.md \
  data/eval/phase0_baseline/index_integrity_report.json \
  data/eval/phase0_baseline/bmw_p04_diagnostic.md \
  data/eval/phase0_baseline/bmw_p04_diagnostic.json \
  data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.md \
  data/eval/phase0_baseline/bmw_p04_evidence_quality_audit.json \
  data/eval/phase0_baseline/embedding_backfill_dryrun.md \
  data/eval/phase0_baseline/embedding_backfill_dryrun.json \
  data/rag-traces/.gitkeep \
  docs/plans/retrieval_phase1_metadata_prefix_plan.md \
  docs/phase0_summary.md \
  docs/phase0_external_review_report.md \
  docs/phase1_0_preliminary_report.md \
  docs/phase1_0_gate_plan.md
```

Use interactive/hunk staging for mixed files:

```bash
git add -p .gitignore
git add -p docker-compose.yml
git add -p scripts/eval_run.py
```

Then review before committing:

```bash
git diff --cached --stat
git diff --cached --name-status
```

Suggested commit message, if approved later:

```text
chore: add phase0 rag diagnostics and p04 evidence audit
```

## Gate B — Project-Safe BMW Backfill Execution Path

Backfill must use:

```text
DB:      project Postgres
Ollama:  project Compose Ollama with bge-m3
```

It must not use the unrelated host Ollama at `127.0.0.1:11434`, which was
confirmed to lack `bge-m3`.

### Current Constraint

The Phase 0 database helper intentionally connects to host TCP
`127.0.0.1:56154` to avoid Unix socket / peer auth. That means the current
backfill script is safe from the host, but it is not directly runnable inside
`pdf-ingest` or a sidecar container against `postgres:5432` unless a DB-host
override is added.

### Recommended No-Port Execution Path

Run the script on the host for DB access, but point `--ollama-host` at the
project Ollama container IP. This uses the project Compose Ollama service
without exposing a port.

Read-only verification already showed:

```text
project_ollama_ip=172.23.0.5
bge_matches=['bge-m3:latest']
has_bge_m3=True
```

Because container IPs can change after recreation, compute it immediately
before each command:

```bash
OLLAMA_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ammer_mmragv2_ollama)"
```

Verify it is the project Ollama and has `bge-m3`:

```bash
OLLAMA_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ammer_mmragv2_ollama)"
OLLAMA_IP="$OLLAMA_IP" python3 - <<'PY'
import json
import os
import urllib.request

url = f"http://{os.environ['OLLAMA_IP']}:11434/api/tags"
with urllib.request.urlopen(url, timeout=5) as resp:
    models = [m.get("name") for m in json.load(resp).get("models", [])]
print([m for m in models if "bge" in (m or "").lower()])
assert any((m or "").split(":")[0] == "bge-m3" for m in models), models
PY
```

Dry-run inside the safe environment:

```bash
OLLAMA_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ammer_mmragv2_ollama)"
python3 scripts/backfill_missing_embeddings.py --dry-run \
  --doc-filter BMWGroup_Bericht2023.pdf \
  --only-error ollama_embed_failed \
  --ollama-host "http://${OLLAMA_IP}:11434"
```

Execute command, only after explicit approval:

```bash
OLLAMA_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ammer_mmragv2_ollama)"
python3 scripts/backfill_missing_embeddings.py --execute \
  --doc-filter BMWGroup_Bericht2023.pdf \
  --only-error ollama_embed_failed \
  --ollama-host "http://${OLLAMA_IP}:11434"
```

This command still preserves:

- `embedding IS NULL` selection
- `meta.embedding_error = "ollama_embed_failed"`
- BMW filename filter
- no overwrite of non-NULL embeddings without `--force`
- no raw `content_text` mutation
- no new ports
- no `0.0.0.0` exposure

### Optional Strict In-Network Path

If the user requires the Python process itself to run inside the Compose
network, make a small pre-execution patch first: add an explicit DB connection
override to the backfill script, such as `--db-host postgres --db-port 5432`.
Do not change the diagnostic scripts' default `127.0.0.1` behavior.

After that patch, a one-off tool container or `pdf-ingest` exec path could run
against `postgres:5432` and `ollama:11434` with no published ports. Without
that patch, the script would try `127.0.0.1` from inside the container and fail
to reach Postgres.

## Pre-Execution Verification Commands

Verify chunk `37039` is selected before execution:

```bash
.venv-phase0/bin/python - <<'PY'
import sys
sys.path.insert(0, "scripts")
from _phase0_utils import open_db_connection

with open_db_connection() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT c.id, d.filename, c.page, c.embedding IS NULL AS missing_embedding,
               c.meta->>'embedding_error' AS embedding_error
        FROM rag_chunks c
        JOIN rag_docs d ON d.doc_id = c.doc_id
        WHERE c.id = 37039;
    """)
    print(cur.fetchone())
PY
```

Verify before/after BMW missing-embedding counts:

```bash
.venv-phase0/bin/python - <<'PY'
import sys
sys.path.insert(0, "scripts")
from _phase0_utils import open_db_connection

with open_db_connection() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT
          count(*) FILTER (WHERE c.embedding IS NULL) AS null_embeddings,
          count(*) FILTER (
            WHERE c.embedding IS NULL
              AND c.meta->>'embedding_error' = 'ollama_embed_failed'
          ) AS null_ollama_embed_failed
        FROM rag_chunks c
        JOIN rag_docs d ON d.doc_id = c.doc_id
        WHERE d.filename = 'BMWGroup_Bericht2023.pdf';
    """)
    print(cur.fetchone())
PY
```

Sanity-check three random chunks through the project Ollama before mutation:

```bash
OLLAMA_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ammer_mmragv2_ollama)"
OLLAMA_IP="$OLLAMA_IP" .venv-phase0/bin/python - <<'PY'
import json
import math
import os
import random
import sys
import urllib.request

sys.path.insert(0, "scripts")
from _phase0_utils import open_db_connection

with open_db_connection() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT c.id, c.content_text
        FROM rag_chunks c
        JOIN rag_docs d ON d.doc_id = c.doc_id
        WHERE d.filename = 'BMWGroup_Bericht2023.pdf'
          AND c.embedding IS NULL
          AND c.meta->>'embedding_error' = 'ollama_embed_failed'
          AND length(coalesce(c.content_text, '')) >= 50
        ORDER BY random()
        LIMIT 3;
    """)
    rows = cur.fetchall()

payload = {
    "model": "bge-m3",
    "input": [text for _, text in rows],
}
req = urllib.request.Request(
    f"http://{os.environ['OLLAMA_IP']}:11434/api/embed",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=60) as resp:
    embeddings = json.load(resp).get("embeddings") or []

assert len(embeddings) == len(rows), (len(embeddings), len(rows))
for (chunk_id, _), vec in zip(rows, embeddings):
    assert len(vec) == 1024, (chunk_id, len(vec))
    assert any(abs(float(x)) > 0 for x in vec), chunk_id
    assert not any(math.isnan(float(x)) for x in vec), chunk_id
    print(chunk_id, len(vec), "ok")
PY
```

## Rollback Expectations

Git cannot roll back embedding updates in Postgres. Before any `--execute`
backfill, take a DB snapshot or targeted `rag_chunks` backup. If backfill
produces unexpected results, rollback requires restoring those DB rows or
restoring from the snapshot.

The backfill script itself preserves failure history under
`meta.embedding_error_history` and removes `meta.embedding_error` only on
successful embedding writes. It does not delete chunks and does not overwrite
non-NULL embeddings unless `--force` is explicitly passed.

## Stop Point

Stop here until the user approves:

1. hunk-staged curated checkpoint commit, and/or
2. the project-Ollama-IP BMW backfill path, including the three-chunk sanity
   check and a DB snapshot before mutation.
