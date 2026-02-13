# CLAUDE.md — mmrag-n8n-demo-v2 Project Context

## Who and Where

- You are operating as Linux user `ammer` on a shared NVIDIA DGX Spark.
- Other users and services run on this machine. **Do not touch anything outside this project.**
- Project root: `/srv/projects/ammer/mmrag-n8n-demo-v2`
- All work must happen inside this root. No files elsewhere.

## Critical Safety Rules (Never Violate)

- **DO NOT** stop, modify, restart, or inspect containers/stacks/volumes that don't belong to this project.
- **DO NOT** bind any port to `0.0.0.0`. All host port bindings must use `127.0.0.1` only.
- **DO NOT** expose anything publicly. Tailscale Serve only (not Funnel).
- **DO NOT** install system packages with `apt` or modify anything outside the project directory.
- **DO NOT** run `docker system prune`, `docker volume prune`, or any broad cleanup commands.
- **ASK before executing** any command that changes system state (docker compose up, docker compose down, tailscale serve, chown, etc.). Show me the command and wait for confirmation.
- If something fails unexpectedly, **STOP and report** rather than attempting creative fixes.

## Project Identity (Isolation)

- Docker Compose project name: `ammer-mmragv2`
- All container names start with: `ammer_mmragv2_`
- Named volumes start with: `ammer-mmragv2_`
- Host port range: `56150–56157` (localhost only)
- These names and ports are frozen. Do not change them.

## Frozen Port Map

| Port  | Service      | Notes                    |
|-------|-------------|--------------------------|
| 56150 | n8n         | -> container port 5678   |
| 56151 | OpenWebUI   | -> container port 8080   |
| 56152 | FileBrowser | -> container port 80     |
| 56153 | Adminer     | -> container port 8080   |
| 56154 | Postgres    | -> container port 5432   |
| 56157 | Assets      | -> container port 80     |

No host port binding for: ollama, pdf-ingest, rag-gateway (internal only).

## GPU Rules

- Only the `ollama` container gets GPU access (`gpus: all` in compose).
- Concurrency is locked: `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`.
- Do not run any GPU-heavy commands outside the ollama container.

## DGX Spark Server Guidelines (from admin)

- Use Docker without sudo for everyday work. Sudo only for system packages or service management.
- All Docker projects live under `/srv/projects/ammer`.
- Each stack must have a unique project name — never reuse existing container/network/volume names.
- Use the 55xxx–56xxx port range. Never bind default ports (5432, 8080, etc.) directly.
- Remove unused containers/images when done. Don't leave experiments running.

## Implementation Approach

- Follow the frozen specification file (mmrag-spec-v2.4.md) exactly. Do not improvise file contents.
- Work in phases: Foundation → Services → Logic → Launch.
- After completing each phase, run the corresponding validation gate before moving on.
- Document manual steps in MANUAL_STEPS.md. Flag anything that can't be automated.

## Key File Locations (Reference)

- Frozen spec: `/srv/projects/ammer/mmrag-spec-v2.4.md`
- DGX guidelines: `/srv/projects/ammer/DGX_Docker_Guidelines_for_Ammer_EN.pdf`
- Environment config: `.env` (created from `.env.example`, never committed)
- SQL init scripts: `db/init/001_init.sql`, `db/init/010_rag_schema.sql`
- Python services: `services/pdf-ingest/`, `services/rag-gateway/`
- n8n workflows (for manual import): `n8n/workflows/`
- Shell scripts: `scripts/` and `reset_demo.sh`
