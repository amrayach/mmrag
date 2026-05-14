# Internal Tailnet Access

This project has two internal access modes for Ammer/Sven. The default stack
continues to publish host ports on `127.0.0.1` only.

## Canonical HTTPS Serve URLs

Use Tailscale Serve as the canonical internal access path for admin surfaces.
Serve terminates HTTPS on the tailnet hostname and proxies to localhost-bound
project ports, so no Docker port binding changes are needed.

| Service | HTTPS URL |
|---|---|
| n8n | `https://spark-e010.tail907fce.ts.net:8450` |
| FileBrowser | `https://spark-e010.tail907fce.ts.net:8452` |
| Adminer | `https://spark-e010.tail907fce.ts.net:8453` |
| Assets | `https://spark-e010.tail907fce.ts.net:8454` |
| Control Center | `https://spark-e010.tail907fce.ts.net:8455` |

OpenWebUI direct Serve access is not part of the reviewer path in hybrid mode.
Reviewers should enter through demo-site so the access-code gate and session
bootstrap remain in control.

The demo-site reviewer URL is the approved `:8443` demo Funnel slot:
`https://spark-e010.tail907fce.ts.net:8443`. That slot is separate from the
admin Serve URLs above.

## Raw 100.x Fallback URLs

Raw `http://100.77.150.62:<port>` URLs are fallback convenience URLs only. They
exist for internal troubleshooting when Serve, browser DNS, or certificate
handling gets in the way for a tailnet user.

Raw mode is opt-in and requires both of these:

1. Explicit operator approval before changing runtime state.
2. The override file `docker-compose.tailnet-raw.yml`.

The override binds only to `${TAILSCALE_HOST_IP}`. It must never bind to
`0.0.0.0`.

| Service | Raw fallback URL |
|---|---|
| n8n | `http://100.77.150.62:56150` |
| FileBrowser | `http://100.77.150.62:56152` |
| Adminer | `http://100.77.150.62:56153` |
| Assets | `http://100.77.150.62:56157` |
| Control Center | `http://100.77.150.62:56156` |
| Demo site | `http://100.77.150.62:56158` |

OpenWebUI raw access is intentionally omitted by default because it bypasses the
demo-site code gate. If a direct OpenWebUI admin fallback is ever needed, treat
it as a separate explicit admin-only approval.

## Operator Commands

Do not run these without approval.

Apply the raw fallback bindings for selected UI services:

```bash
TAILSCALE_HOST_IP=100.77.150.62 docker compose -f docker-compose.yml -f docker-compose.tailnet-raw.yml -p ammer-mmragv2 up -d n8n filebrowser adminer controlcenter demo-site assets
```

Return selected UI services to localhost-only bindings:

```bash
docker compose -f docker-compose.yml -p ammer-mmragv2 up -d n8n filebrowser adminer controlcenter demo-site assets
```

## Cookie Caveat

The earlier Sven access issue was browser/session-layer behavior, not basic
tailnet reachability: raw HTTP n8n access may depend on `N8N_SECURE_COOKIE=false`.
HTTPS Serve avoids that class of cookie problem because the browser sees an
HTTPS origin.

## Funnel Ownership

Only the `:8443` Funnel slot is approved for this project's demo-site. Existing
Sven-owned Funnel slots `:443` and `:10000` are intentionally left untouched.
Do not use broad Tailscale reset commands.
