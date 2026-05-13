# Live Demo Access — Feasibility Report

**Status:** DRAFT — pending boss approval. Do not start implementation until cleared.
**Date:** 2026-05-06
**Authors:** drafted in collaboration with Claude Code

> **Superseded access note:** Option 3C hybrid demo access replaces the direct-OpenWebUI public exposure described in this early feasibility report. Funnel, when explicitly approved for the hybrid demo, must expose demo-site only. Direct OpenWebUI Tailscale Serve/Funnel exposure must be removed in hybrid mode. See `docs/option3c_hybrid_architecture.md`.

---

## Context

Boss requested three features for an upcoming live demo where 5–10 participants try the RAG system on their own devices:

1. **Temporary user accounts** in OpenWebUI for the demo participants
2. **Public access** for participants who are not on our tailnet — boss has explicitly granted an exception to the project's "Tailscale Serve only, no Funnel" rule (CLAUDE.md) **for this demo only**
3. **OpenAI cloud model** (e.g. GPT-5) as an alternative to local `gemma4:26b`, primarily to handle concurrency

Confirmed during initial discussion:
- Demo audience: max 5–10 people
- Demo data (current PDFs + RSS) is non-confidential / synthetic → OK to send to OpenAI
- Per-user routing should balance Gemma vs GPT and users must always know which model is answering them
- Boss interested in both Tailscale Funnel and Cloudflare Tunnel as routes; Cloudflare to be raised as alternative in the report

## Open decisions awaiting boss

| # | Decision | Note |
|---|---|---|
| 1 | Public access route | Funnel (simpler) vs Cloudflare Tunnel + Access (better access control) |
| 2 | OpenAI model | GPT-5 (best quality) vs GPT-5-mini (~5–10× cheaper, plenty for a demo) |
| 3 | Monthly OpenAI cap | Suggest $50 hard cap |
| 4 | Demo date | Need ~4 working days + rehearsal before the demo |

---

## Report drafted for boss

> **Verdict:** all three asks (public access for participants, temporary user accounts, OpenAI as alternative to local Gemma) are feasible for a 5–10 person live demo. Estimated effort: **~4 working days** including a rehearsal pass. No blockers.

### 1. Public access for non-tailnet participants

Two viable paths:

**A. Tailscale Funnel** *(historical recommendation; superseded by Option 3C)*
- The original idea was to expose OpenWebUI directly. Option 3C changes this: expose demo-site only and keep OpenWebUI private behind demo-site's root-mux proxy.
- Public URL: `https://<dgx-host>.<tailnet>.ts.net`, port 443, Tailscale-managed Let's Encrypt cert (auto-renewing)
- **Only demo-site is exposed in Option 3C.** OpenWebUI, n8n, Postgres, Adminer, FileBrowser, and internal services remain private.
- Reversible (`tailscale funnel reset`); Tailscale logs every connection (source IP + timestamp) for audit.

**B. Cloudflare Tunnel + Cloudflare Access** *(more setup, better access control)*
- Custom hostname (e.g. `demo.<our-domain>`)
- Email-based magic-link auth in front of OpenWebUI — no shared passwords needed, per-user audit log, expiring grants.

**Recommendation:** Funnel for this demo. Move to Cloudflare later if we want to keep public access running between demos.

**Risk surface either way:** demo-site's access-code gate and OpenWebUI's session are the barriers between the public URL and the demo data. Mitigations for Option 3C:
- Keep OpenWebUI private and reachable only through demo-site's authenticated root-mux proxy.
- Pre-create per-session OpenWebUI users via the admin API.
- Funnel disabled immediately after the session.

### 2. Temporary user accounts

Native OpenWebUI feature, no code changes:
- Pre-create 10 admin-managed accounts (`demo01`–`demo10`) before the demo.
- Random per-account passwords on a single handout.
- Cleanup script deletes users + chat history + uploads post-demo.

Effort: ~½ day including the cleanup script.

### 3. Dual-model routing — local Gemma + cloud GPT

Our chat backend (`rag-gateway`) already speaks OpenAI-compatible streaming, so this is mostly configuration:

- Two models exposed in OpenWebUI's chat dropdown:
  - **`Local — Gemma 4 26B`** (DGX, no data leaves the box)
  - **`Cloud — GPT-5`** *(or whichever OpenAI model boss picks)*
- Same RAG document retrieval for both; only the generation step differs.
- The active model is **always visible in the chat UI** — users always know who is answering them.
- Each demo account ships with a default (split ~50/50 across the two models); users can switch at any time.

Why this design:
- **Concurrency:** load naturally spreads across local GPU + cloud, avoiding queue buildup.
- **Demo value:** "swap models, re-ask the same question, compare the answers" is a built-in talking point.
- **Resilience:** if OpenAI is slow/unreachable, requests fall through to local Gemma rather than failing.

Effort: ~1.5–2 days.

### 4. Concurrency outlook

The DGX is sized for one heavy local generation at a time (~5–30s per Gemma response). Splitting traffic across the two models keeps latencies acceptable for 5–10 concurrent users without further hardware changes. If we want to push beyond ~10 concurrent users in future, we have follow-on options (more local parallelism, smaller local fallback model) — not needed for this demo.

### 5. Data and cost

- **Data:** confirmed the current demo corpus (PDFs, RSS) is non-confidential / synthetic — safe to send to OpenAI.
- **OpenAI budget cap:** set a hard monthly cap on the API key in the OpenAI dashboard before issuing it. ~**$50/month** comfortably covers a multi-hour demo plus margin and prevents runaway costs from any stuck request loop.

### 6. Decisions needed from you

| # | Decision | Note |
|---|---|---|
| 1 | Public access route | Funnel (simpler) vs Cloudflare Tunnel (better access control) |
| 2 | OpenAI model | GPT-5 (best quality) vs GPT-5-mini (~5–10× cheaper, plenty for a demo) |
| 3 | Monthly OpenAI cap | Suggest $50 |
| 4 | Demo date | Need ~4 working days + rehearsal before the demo |

### 7. Effort breakdown

| Task | Effort |
|---|---|
| Public access (Funnel + signup off + password handout) | 0.5 d |
| Temp accounts + cleanup script | 0.5 d |
| Dual-model routing in `rag-gateway` (incl. timeout fallback) | 1.5 d |
| OpenWebUI model registration + per-account defaults | 0.5 d |
| Demo rehearsal + smoke test | 1.0 d |
| **Total** | **~4 days** |

---

## Internal notes (not in the boss-facing report)

- The CLAUDE.md hard rule "Tailscale Serve only (not Funnel)" — boss's exception is **demo-specific**. Funnel must be disabled immediately after the demo, and the rule remains in force for any non-demo work.
- Once Funnel is enabled, the Tailscale hostname enters the public TLS cert log (crt.sh) — assume it's discoverable by scrapers within hours of going live.
- DGX is shared infrastructure: any public exposure also sits next to other tenants' services. Option 3C exposes demo-site only; still ping the DGX admin before flipping the switch.
- `rag-gateway` already speaks OpenAI-compatible streaming SSE, so adding an OpenAI upstream is routing config, not protocol work. Look at `services/rag-gateway/app/main.py` and `context.py` for the existing Ollama call paths.
- OpenAI key: store in `.env` (already gitignored), never in `docker-compose.yml`. Set the budget cap on the OpenAI dashboard side as a **hard** limit (not a soft alert).
- Cleanup script for demo accounts should also wipe uploaded files in OpenWebUI's data volume — they persist across login sessions otherwise.
- "GPT-5.5" was mentioned by boss but is not a real model name — confirm intended model with him (likely `gpt-5` or `gpt-5-mini`).

## Next steps (when boss greenlights)

1. Capture boss's four decisions in this doc.
2. Run `superpowers:brainstorming` to convert this into an approved design spec under `docs/superpowers/specs/YYYY-MM-DD-live-demo-access-design.md`.
3. Run `superpowers:writing-plans` to produce a phased implementation plan.
4. Implementation order: **temp accounts** (lowest risk) → **dual-model routing** → **public access flip** last, immediately before the demo.
