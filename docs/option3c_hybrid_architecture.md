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

S0 spike facts to preserve in implementation:

- Trusted-header signin works through `POST /api/v1/auths/signin`.
- Header-only requests do not authenticate.
- The OpenWebUI session cookie is required after signin.
- A stale reviewer1 cookie with reviewer2 trusted headers is rejected.
- Duplicate `POST /api/v1/auths/add` for the same email returns HTTP 400 with an already-registered detail and should be treated as success.
- SSE-through-Funnel has not yet been tested.

Because header-only auth is insufficient, `/api/openwebui/start` must sign in with trusted headers and relay OpenWebUI `Set-Cookie` headers to the browser. Reviewer identities use the deterministic format `demo-<8-char-token-prefix>@mmrag.invalid` and `Demo Reviewer <token_prefix>`; the full token or access code must never be exposed.

## Configuration

OpenWebUI:

```env
WEBUI_AUTH=true
WEBUI_AUTH_TRUSTED_EMAIL_HEADER=X-Demo-Email
WEBUI_AUTH_TRUSTED_NAME_HEADER=X-Demo-Name
ENABLE_FORWARD_USER_INFO_HEADERS=true
JWT_EXPIRES_IN=24h
```

demo-site:

```env
DEMO_SITE_OPENWEBUI_ENABLED=false
OPENWEBUI_URL=http://openwebui:8080
OPENWEBUI_ADMIN_EMAIL=
OPENWEBUI_ADMIN_PASSWORD=
OPENWEBUI_TRUSTED_EMAIL_HEADER=X-Demo-Email
OPENWEBUI_TRUSTED_NAME_HEADER=X-Demo-Name
```

rag-gateway:

```env
RAG_DEMO_RATE_LIMIT_ENABLED=false
RAG_DEMO_MAX_QUERIES_PER_HOUR=10
```

`DEMO_SITE_OPENWEBUI_ENABLED=false` is the kill switch. With it disabled, the system should behave like the classic Option 1 demo-site flow.

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

## Rollback

1. Set `DEMO_SITE_OPENWEBUI_ENABLED=false`.
2. Restart the affected service only after explicit operator approval.
3. Use the classic demo-site chat at `/classic`, backed by `/api/chat`.
4. Remove any hybrid Funnel exposure after explicit operator approval.

This rollback does not require direct public OpenWebUI exposure.
