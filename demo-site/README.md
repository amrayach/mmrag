# MMRAG Demo Site

Local-only demo website for the existing `rag-gateway` OpenAI-compatible chat API.
It provides a branded German landing page, persistent temporary access-code auth,
and a small chat UI that renders gateway sources below each assistant answer.

## Stack Choice

The implementation uses dependency-free Node.js for the backend and static
HTML/CSS/JavaScript for the frontend. This keeps the demo small, works offline,
and avoids a package install step. The trade-off is that there is no frontend
build pipeline or component framework; for this narrow demo, the reduced
operational surface is more useful than Vite/Preact.

## Model Resolution

`/api/chat` sends `model: DEMO_SITE_MODEL` to `rag-gateway`.

Resolution order:

1. `DEMO_SITE_MODEL`
2. `OLLAMA_TEXT_MODEL`
3. `DEFAULT_MODEL`
4. `gemma4:26b`

The fallback was chosen after checking this worktree: `.env.example` sets
`OLLAMA_TEXT_MODEL=gemma4:26b`, and `docker-compose.yml` passes
`DEFAULT_MODEL: ${OLLAMA_TEXT_MODEL}` into `rag-gateway`. This session worktree
does not contain a real `.env`; if the deployed `.env` changes the text model,
set `DEMO_SITE_MODEL` to the same value.

## Local Dev Workflow

No dependencies are required beyond Node 20+.

```bash
cd demo-site
npm run check
npm test
npm run dev
```

`npm run dev` starts the backend and static frontend on
`http://127.0.0.1:56159` with `DEMO_SITE_MOCK_GATEWAY=true`. Mock mode verifies
the UI, auth flow, source rendering, and rate limiting without calling the real
gateway. Local dev writes auth state to `demo-site/data/auth.json`, which is
gitignored.

Admin endpoints are disabled unless `DEMO_SITE_ADMIN_TOKEN` is set:

```bash
cd demo-site
DEMO_SITE_ADMIN_TOKEN=local-admin-token npm run dev
```

For a local live-gateway run after Session 3.0 validation is complete:

```bash
cd demo-site
RAG_GATEWAY_URL=http://127.0.0.1:56155 DEMO_SITE_MOCK_GATEWAY=false npm start
```

## Compose Workflow

Only run these after Session 3.0 confirms gateway validation is complete:

```bash
docker compose config --quiet
docker compose build demo-site
DEMO_SITE_ADMIN_TOKEN=local-admin-token docker compose up -d --no-deps demo-site
curl -s http://127.0.0.1:56158/health
```

The compose service binds `127.0.0.1:${PORT_DEMO_SITE:-56158}:3000` and uses
`RAG_GATEWAY_URL=http://rag-gateway:8000` by default. `rag-gateway` already has a
healthcheck, so the demo service depends on `rag-gateway` with
`condition: service_healthy`. Auth data is stored in the demo-site-only
`demo_site_data` volume at `/app/data/auth.json`.

## Optional Hybrid Health Check

`scripts/demo_e2e_check.py` has an opt-in demo-site/OpenWebUI hybrid check. It is
disabled unless `DEMO_HEALTH_HYBRID_CHECK=true` is set.

```bash
DEMO_HEALTH_HYBRID_CHECK=true python3 scripts/demo_e2e_check.py
```

The checker discovers demo-site with `DEMO_HEALTH_DEMO_SITE_URL` first, then
`docker compose port demo-site 3000`, then `PORT_DEMO_SITE` or `56158`.

When `DEMO_SITE_ADMIN_TOKEN` is available, the check creates one short-lived
code, redeems it, captures only token prefixes and cookie names in the health
report, calls `/api/openwebui/start`, verifies classic `/api/chat`, verifies
local rag-gateway SSE at `/v1/chat/completions` with `stream:true`, revokes the
new session by token prefix, and confirms the revoked session is denied. Running
it writes normal demo health output and demo-site auth records.

With `DEMO_SITE_OPENWEBUI_ENABLED=true`, `/api/openwebui/start` must return
`200` with `{ "ok": true }`, a redirect, and at least one OpenWebUI
`Set-Cookie` header. With hybrid disabled, the expected result is
`503 openwebui_disabled`. If the admin token is absent, the checker only probes
`/health` and records the session flow as skipped.

This is a local contract check. It does not expose anything publicly, does not
use Tailscale Funnel, and does not prove off-tailnet incremental SSE. That
boundary remains the S6 operator validation.

## Persistent Access-Code Auth

`POST /api/auth/redeem` validates a persistent temporary code and returns:

```json
{"token":"<random>","expires_at":"<ISO 8601>","code_expires_at":"<ISO 8601>"}
```

Codes are stored in a local JSON file with `code`, `created_at`, `expires_at`,
`revoked_at`, `max_redemptions`, `redemption_count`, `label`, `created_by`, and
`notes`. Sessions are stored in the same file with `token`, `code`, `created_at`,
`expires_at`, `revoked_at`, and `last_seen_at`. Audit events record event type,
status, remote address, code, and token prefix only. Full session tokens are not
written to audit events.

Generated codes and session tokens use `crypto.randomBytes`. Default code expiry
is 24 hours and default `max_redemptions` is 1. Session expiry is the earlier of
the code expiry and `DEMO_SITE_SESSION_TTL_HOURS` after redemption.

The token is returned as JSON and also as an HttpOnly localhost cookie.
`POST /api/chat` accepts either `Authorization: Bearer <token>` or the cookie.
Invalid, expired, or revoked tokens return `401`.

Session persistence uses Option A: sessions persist across container restart.
This avoids disrupting a live demo if `docker compose restart demo-site` is
needed. The trade-off is a broader persistent token surface than a hard-reset
restart model, so revocation is written to the same JSON store immediately and
the admin revoke endpoint never logs full token values.

## Admin API

All admin endpoints require `Authorization: Bearer $DEMO_SITE_ADMIN_TOKEN`. If
the token is unset, admin endpoints return `503 admin_disabled`.

Create a code:

```bash
curl -s -X POST http://127.0.0.1:56158/api/admin/codes \
  -H "Authorization: Bearer $DEMO_SITE_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ttl_hours":24,"max_redemptions":1,"label":"Sven"}'
```

List codes:

```bash
curl -s -H "Authorization: Bearer $DEMO_SITE_ADMIN_TOKEN" \
  http://127.0.0.1:56158/api/admin/codes
```

Revoke a code:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $DEMO_SITE_ADMIN_TOKEN" \
  http://127.0.0.1:56158/api/admin/codes/<code>/revoke
```

Optionally revoke a session by token prefix:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $DEMO_SITE_ADMIN_TOKEN" \
  http://127.0.0.1:56158/api/admin/sessions/<first-8-token-chars>/revoke
```

## Configuration

- `DEMO_SITE_ADMIN_TOKEN`: enables admin endpoints.
- `DEMO_SITE_CODE_TTL_HOURS`: default code TTL, default `24`.
- `DEMO_SITE_SESSION_TTL_HOURS`: default session TTL, default `24`.
- `DEMO_SITE_AUTH_STORE_PATH`: auth JSON path, default `/app/data/auth.json`.
- `DEMO_SITE_MAX_QUERIES_PER_HOUR`: per-session rate limit, default `10`.
- `DEMO_SITE_CHAT_TIMEOUT_MS`: gateway timeout in milliseconds, default `60000`.
- `DEMO_SITE_OPENWEBUI_ENABLED`: enables the hybrid OpenWebUI bootstrap path.
- `DEMO_HEALTH_HYBRID_CHECK`: opt-in local hybrid health/e2e check.
- `DEMO_HEALTH_DEMO_SITE_URL`: optional demo-site URL override for the checker.

## Chat Limits

- Rate limit: 10 chat requests per session per rolling hour.
- Rate limiting is checked before proxying to `rag-gateway`; the 11th request
  returns `429` without a gateway call.
- `max_tokens` is capped at 800.
- Gateway timeout is 60 seconds.
- Streaming is not implemented in the demo UI; the UI shows a typing indicator
  until the full non-streaming response arrives.

## Remaining Queue

- Optional admin UI.
- External delivery of demo codes.
- More detailed operational audit export.
- Tailscale Funnel exposure after local validation.

## Known Limitations

- No public deployment or Funnel configuration.
- No public signup, user accounts, passwords, OAuth, email delivery, analytics,
  or billing.
- No OpenAI/cloud LLM integration.
- Example questions are provisional until live gateway walkthrough validation is
  approved and completed.
