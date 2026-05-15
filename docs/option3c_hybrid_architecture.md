# Option 3C Hybrid OpenWebUI Access

**Status:** configuration and documentation stage. Application implementation is split across S1a/S1b/S2/S4/S5. Hybrid mode is disabled by default.

## Goal

Option 3C keeps demo-site as the reviewer gate while using OpenWebUI as the chat interface. Reviewers redeem an access code in demo-site, then start OpenWebUI through `/api/openwebui/start`. demo-site validates the `demo_session`, bootstraps the OpenWebUI session, and root-mux proxies authenticated OpenWebUI traffic.

The classic demo-site chat remains available as the rollback path through `/classic` and the existing `/api/chat` endpoint.

## Root-Mux Model

demo-site is the only public/root entrypoint in hybrid mode:

```text
reviewer browser
  -> demo-site public root
  -> /api/openwebui/start validates demo_session and signs in to OpenWebUI
  -> authenticated non-reserved paths proxy to OpenWebUI at http://openwebui:8080
  -> OpenWebUI sends chat requests to rag-gateway
  -> rag-gateway streams OpenAI-compatible SSE from local Ollama/RAG context
```

Reserved demo-site paths stay local, including `/health`, `/api/auth/*`, `/api/admin/*`, `/api/chat`, `/api/openwebui/*`, `/classic`, and static demo-site assets. Authenticated non-reserved paths proxy to OpenWebUI root. This avoids `/webui` subpath rewriting because OpenWebUI uses root-relative assets and API routes.

## OpenWebUI Bootstrap

OpenWebUI is configured for plain email/password auth (`WEBUI_AUTH=true`, no trusted-header SSO). `/api/openwebui/start` bootstraps a reviewer account on demand and signs it in using a deterministic password.

Bootstrap contract preserved from the S0 spike:

- `POST /api/v1/auths/signin` requires a real email/password pair.
- The OpenWebUI session cookie is required after signin; header-only requests do not authenticate.
- Duplicate `POST /api/v1/auths/add` for the same email returns HTTP 400 with an already-registered detail and is treated as success.
- SSE-through-Funnel has not yet been tested.

Reviewer identities use the format `demo2-<8-char-token-prefix>@mmrag.invalid` and `Demo Reviewer <token_prefix>`. The reviewer password is derived as `HMAC-SHA256(DEMO_SITE_OPENWEBUI_PASSWORD_SECRET, "reviewer:" + session.token)`, base64url-encoded, sliced to 32 characters. The full token, access code, and derived password must never be exposed to the browser or logs. Old `demo-<prefix>@mmrag.invalid` users from the trusted-header era stay in OpenWebUI as harmless orphans.

`DEMO_SITE_OPENWEBUI_PASSWORD_SECRET` defaults to `WEBUI_SECRET_KEY` when unset. `/api/openwebui/start` fails closed with `503 openwebui_password_secret_missing` when neither value is configured.

## Configuration

OpenWebUI:

```env
WEBUI_AUTH=true
WEBUI_SECRET_KEY=...                  # stable across restarts; also seeds the reviewer-password HMAC by default
ENABLE_FORWARD_USER_INFO_HEADERS=true  # forwards X-OpenWebUI-User-* to rag-gateway for rate-limit identity
JWT_EXPIRES_IN=24h
```

demo-site:

```env
DEMO_SITE_OPENWEBUI_ENABLED=false
OPENWEBUI_URL=http://openwebui:8080
OPENWEBUI_ADMIN_EMAIL=               # required for reviewer pre-creation
OPENWEBUI_ADMIN_PASSWORD=            # required for reviewer pre-creation
DEMO_SITE_OPENWEBUI_PASSWORD_SECRET= # optional override; falls back to WEBUI_SECRET_KEY
```

rag-gateway:

```env
RAG_DEMO_RATE_LIMIT_ENABLED=false
RAG_DEMO_MAX_QUERIES_PER_HOUR=10
```

`DEMO_SITE_OPENWEBUI_ENABLED=false` is the kill switch. With it disabled, the system should behave like the classic Option 1 demo-site flow.

## S5 Local Health Check

`scripts/demo_e2e_check.py` includes an optional hybrid/demo-site flow. It is off
by default and runs only when `DEMO_HEALTH_HYBRID_CHECK=true` is set:

```bash
DEMO_HEALTH_HYBRID_CHECK=true python3 scripts/demo_e2e_check.py
```

Discovery order for demo-site is:

1. `DEMO_HEALTH_DEMO_SITE_URL`
2. `docker compose port demo-site 3000`
3. `PORT_DEMO_SITE`, falling back to `http://127.0.0.1:56158`

When `DEMO_SITE_ADMIN_TOKEN` is configured, the local check creates one
short-lived access code, redeems it, uses the resulting `demo_session` cookie,
calls `/api/openwebui/start`, exercises classic `/api/chat`, verifies direct
local rag-gateway SSE with `stream:true`, revokes the new session by token
prefix, and verifies a later `/api/openwebui/start` is denied with `401`.

The health report stores only prefixes, cookie names, status codes, JSON error
keys, header names, and latency. It must not store full access codes, session
tokens, admin credentials, demo cookies, or OpenWebUI cookies.

Expected local outcomes:

- `DEMO_SITE_OPENWEBUI_ENABLED=true`: `/api/openwebui/start` must return `200`,
  `{ "ok": true }`, a redirect, and at least one OpenWebUI `Set-Cookie` header.
- `DEMO_SITE_OPENWEBUI_ENABLED=false`: `/api/openwebui/start` must return
  `503 openwebui_disabled`; classic `/api/chat` still works with the redeemed
  demo session.
- no `DEMO_SITE_ADMIN_TOKEN`: only `/health` is checked and the session flow is
  recorded as skipped.

Running the check writes the usual `data/eval/demo_health` output and, when the
admin token is present, short-lived demo-site auth-store records. It does not
change containers, ports, models, volumes, Tailscale state, or public exposure.

The check gates Ollama text-model GPU residency before `rag_query`. If
`gemma4:26b` is loaded on CPU, it fails fast with a recovery hint instead of
waiting for the p01 RAG query to time out. Before S6, warm the demo models and
confirm `docker compose -p ammer-mmragv2 exec -T ollama ollama ps` reports
`gemma4:26b` as `100% GPU`.

## Public Exposure Rules

The default project rule remains Tailscale Serve only, no Funnel.

The approved exception is narrow:

- Funnel may be used only for Option 3C hybrid demo mode.
- The operator must approve the exact Tailscale command before it runs.
- Funnel must expose demo-site only.
- OpenWebUI must never be exposed directly through Serve or Funnel in hybrid mode.
- Any existing direct OpenWebUI Serve/Funnel rule must be removed before hybrid exposure.
- S6 must verify the public URL from off-tailnet and prove SSE chunks arrive incrementally with `curl -N`.

SSE-through-Funnel remains unvalidated until S6. Do not treat the hybrid public path as demo-ready until that check passes.

The S5 health check intentionally skips Funnel and off-tailnet validation. S6
must still expose demo-site only after explicit operator approval, test the
public root from off-tailnet, and prove incremental SSE through Funnel with
`curl -N`.

## Rollback

1. Set `DEMO_SITE_OPENWEBUI_ENABLED=false`.
2. Restart the affected service only after explicit operator approval.
3. Use the classic demo-site chat at `/classic`, backed by `/api/chat`.
4. Remove any hybrid Funnel exposure after explicit operator approval.

This rollback does not require direct public OpenWebUI exposure.
