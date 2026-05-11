# MMRAG Demo Site

Local-only demo website for the existing `rag-gateway` OpenAI-compatible chat API.
It provides a branded German landing page, a temporary-code auth stub, and a small
chat UI that renders gateway sources below each assistant answer.

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
gateway.

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
docker compose up -d demo-site
curl -s http://127.0.0.1:56158/health
```

The compose service binds `127.0.0.1:${PORT_DEMO_SITE:-56158}:3000` and uses
`RAG_GATEWAY_URL=http://rag-gateway:8000` by default. `rag-gateway` already has a
healthcheck, so the demo service depends on `rag-gateway` with
`condition: service_healthy`.

## Auth Stub

This is intentionally in-memory only. `POST /api/auth/redeem` accepts any
non-empty code and returns:

```json
{"token":"<random>","expires_at":"<ISO 8601 24h hence>"}
```

The token is stored in memory and also returned as an HttpOnly localhost cookie.
`POST /api/chat` accepts either `Authorization: Bearer <token>` or the cookie.
Invalid or expired tokens return `401`. Tokens are lost on restart, which is
expected for Session 4.

For expiry testing, set `DEMO_SITE_TOKEN_TTL_SECONDS=1` and retry a chat request
after the token expires.

## Chat Limits

- Rate limit: 10 chat requests per session per rolling hour.
- Rate limiting is checked before proxying to `rag-gateway`; the 11th request
  returns `429` without a gateway call.
- `max_tokens` is capped at 800.
- Gateway timeout is 60 seconds.
- Streaming is not implemented in the demo UI; the UI shows a typing indicator
  until the full non-streaming response arrives.

## Session 4.1 Queue

- Persistent auth backend.
- Admin endpoint for code generation.
- Code rotation and expiry management.
- Optional analytics/audit logging.
- Tailscale Funnel exposure after local validation.

## Known Limitations

- No public deployment or Funnel configuration.
- No persistent temp-account storage.
- No OpenAI/cloud LLM integration.
- Example questions are provisional until live gateway walkthrough validation is
  approved and completed.
