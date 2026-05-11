"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const http = require("node:http");
const path = require("node:path");
const { URL } = require("node:url");

const ROOT_DIR = path.resolve(__dirname, "..");
const FRONTEND_DIR = path.join(ROOT_DIR, "frontend");

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon"
};

function envFlag(value) {
  return String(value || "").toLowerCase() === "true";
}

function intFromEnv(name, fallback, min, max) {
  const raw = process.env[name];
  const parsed = Number.parseInt(raw || "", 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

function stripTrailingSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function createConfig(overrides = {}) {
  const defaultModel =
    process.env.DEMO_SITE_MODEL ||
    process.env.OLLAMA_TEXT_MODEL ||
    process.env.DEFAULT_MODEL ||
    "gemma4:26b";

  return {
    host: overrides.host || process.env.HOST || "127.0.0.1",
    port: overrides.port || intFromEnv("PORT", 3000, 1, 65535),
    ragGatewayUrl: stripTrailingSlash(
      overrides.ragGatewayUrl || process.env.RAG_GATEWAY_URL || "http://rag-gateway:8000"
    ),
    model: overrides.model || defaultModel,
    tokenTtlMs:
      overrides.tokenTtlMs ||
      intFromEnv("DEMO_SITE_TOKEN_TTL_SECONDS", 24 * 60 * 60, 1, 31 * 24 * 60 * 60) * 1000,
    maxQueriesPerHour:
      overrides.maxQueriesPerHour || intFromEnv("DEMO_SITE_MAX_QUERIES_PER_HOUR", 10, 1, 100),
    maxTokensCap: overrides.maxTokensCap || 800,
    chatTimeoutMs: overrides.chatTimeoutMs || 60_000,
    mockGateway:
      typeof overrides.mockGateway === "boolean"
        ? overrides.mockGateway
        : envFlag(process.env.DEMO_SITE_MOCK_GATEWAY)
  };
}

function sendJson(res, statusCode, data, extraHeaders = {}) {
  const body = JSON.stringify(data);
  res.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
    ...extraHeaders
  });
  res.end(body);
}

function sendNoContent(res) {
  res.writeHead(204, { "cache-control": "no-store" });
  res.end();
}

function readRequestBody(req, maxBytes = 256 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > maxBytes) {
        reject(Object.assign(new Error("request_body_too_large"), { statusCode: 413 }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

async function readJson(req) {
  const raw = await readRequestBody(req);
  if (!raw.trim()) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch {
    const err = new Error("invalid_json");
    err.statusCode = 400;
    throw err;
  }
}

function cookieHeader(token, maxAgeSeconds) {
  const safeToken = encodeURIComponent(token);
  return [
    `demo_session=${safeToken}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    `Max-Age=${Math.max(1, Math.floor(maxAgeSeconds))}`
  ].join("; ");
}

function tokenFromRequest(req) {
  const authorization = req.headers.authorization || "";
  const bearer = authorization.match(/^Bearer\s+(.+)$/i);
  if (bearer) {
    return bearer[1].trim();
  }

  const cookie = req.headers.cookie || "";
  for (const part of cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === "demo_session") {
      return decodeURIComponent(rest.join("="));
    }
  }
  return "";
}

function getSession(req, sessions, now = Date.now()) {
  const token = tokenFromRequest(req);
  if (!token) {
    return { status: "missing" };
  }
  const session = sessions.get(token);
  if (!session) {
    return { status: "invalid", token };
  }
  if (session.expiresAt <= now) {
    sessions.delete(token);
    return { status: "expired", token };
  }
  return { status: "ok", token, session };
}

function checkRateLimit(session, config, now = Date.now()) {
  const windowStart = now - 60 * 60 * 1000;
  session.queryTimes = session.queryTimes.filter((timestamp) => timestamp > windowStart);
  if (session.queryTimes.length >= config.maxQueriesPerHour) {
    const oldest = session.queryTimes[0] || now;
    const retryAfterSeconds = Math.max(1, Math.ceil((oldest + 60 * 60 * 1000 - now) / 1000));
    return {
      ok: false,
      retryAfterSeconds,
      remaining: 0
    };
  }
  session.queryTimes.push(now);
  return {
    ok: true,
    retryAfterSeconds: 0,
    remaining: Math.max(0, config.maxQueriesPerHour - session.queryTimes.length)
  };
}

function sanitizeMessages(body) {
  const rawMessages = Array.isArray(body.messages)
    ? body.messages
    : typeof body.message === "string"
      ? [{ role: "user", content: body.message }]
      : [];

  const messages = rawMessages
    .filter((message) => message && typeof message.content === "string")
    .map((message) => ({
      role: ["user", "assistant", "system"].includes(message.role) ? message.role : "user",
      content: message.content.trim().slice(0, 8000)
    }))
    .filter((message) => message.content.length > 0)
    .slice(-12);

  if (!messages.some((message) => message.role === "user")) {
    const err = new Error("missing_user_message");
    err.statusCode = 400;
    throw err;
  }
  return messages;
}

function requestedMaxTokens(body, config) {
  const requested = Number.parseInt(String(body.max_tokens || body.maxTokens || config.maxTokensCap), 10);
  if (!Number.isFinite(requested)) {
    return config.maxTokensCap;
  }
  return Math.min(config.maxTokensCap, Math.max(1, requested));
}

function parseMarkdownLink(value) {
  const markdown = value.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
  if (markdown) {
    return {
      label: markdown[1].trim(),
      url: markdown[2].trim()
    };
  }
  return { label: value.trim(), url: "" };
}

function parseAssistantContent(content) {
  const text = String(content || "").trim();
  const markerMatch = /\n?Quellen:\s*/i.exec(text);
  if (!markerMatch) {
    return { answer: text, sources: [] };
  }

  const answer = text.slice(0, markerMatch.index).trim();
  const sourceBlock = text.slice(markerMatch.index + markerMatch[0].length);
  const sources = sourceBlock
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.replace(/^[-*]\s*/, ""))
    .filter(Boolean)
    .map(parseMarkdownLink)
    .slice(0, 8);

  return { answer, sources };
}

function buildMockGatewayResponse(payload, config) {
  const lastUser = [...payload.messages].reverse().find((message) => message.role === "user");
  const question = lastUser ? lastUser.content : "Demo-Frage";
  const content = [
    `Mock-Antwort fuer: ${question}`,
    "",
    "Dies ist eine lokale Platzhalterantwort. Sie prueft UI, Authentifizierung und Rate-Limit ohne Gateway-Aufruf.",
    "",
    "Quellen:",
    "- [Siemens Nachhaltigkeitsbericht — Seite 12](https://example.local/siemens.pdf#page=12)",
    "- [RSS: Demo-Nachricht](https://example.local/rss/demo)"
  ].join("\n");

  return {
    id: `mock-${crypto.randomUUID()}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: config.model,
    choices: [
      {
        index: 0,
        message: { role: "assistant", content },
        finish_reason: "stop"
      }
    ]
  };
}

async function proxyChat(messages, body, config, fetchImpl) {
  const payload = {
    model: config.model,
    messages,
    stream: false,
    temperature: 0.2,
    max_tokens: requestedMaxTokens(body, config)
  };

  if (config.mockGateway) {
    return buildMockGatewayResponse(payload, config);
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.chatTimeoutMs);
  try {
    const response = await fetchImpl(`${config.ragGatewayUrl}/v1/chat/completions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      const err = new Error(text.slice(0, 500) || `gateway_status_${response.status}`);
      err.statusCode = response.status === 504 ? 504 : 502;
      throw err;
    }
    return response.json();
  } catch (error) {
    if (error.name === "AbortError") {
      const err = new Error("gateway_timeout");
      err.statusCode = 504;
      throw err;
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function serveStatic(req, res) {
  const url = new URL(req.url, "http://127.0.0.1");
  let pathname;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch {
    sendJson(res, 400, { error: "invalid_path" });
    return;
  }
  if (pathname === "/" || pathname === "/login" || pathname === "/chat") {
    pathname = "/index.html";
  }

  const requested = path.normalize(path.join(FRONTEND_DIR, pathname));
  if (requested !== FRONTEND_DIR && !requested.startsWith(`${FRONTEND_DIR}${path.sep}`)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }

  try {
    const data = await fs.readFile(requested);
    const ext = path.extname(requested).toLowerCase();
    res.writeHead(200, {
      "content-type": MIME_TYPES[ext] || "application/octet-stream",
      "cache-control": ext === ".html" ? "no-store" : "public, max-age=300"
    });
    res.end(data);
  } catch (error) {
    if (error.code === "ENOENT") {
      const index = await fs.readFile(path.join(FRONTEND_DIR, "index.html"));
      res.writeHead(200, {
        "content-type": MIME_TYPES[".html"],
        "cache-control": "no-store"
      });
      res.end(index);
      return;
    }
    throw error;
  }
}

async function handleRequest(req, res, app) {
  const url = new URL(req.url, "http://127.0.0.1");

  if (req.method === "OPTIONS") {
    sendNoContent(res);
    return;
  }

  if (req.method === "GET" && url.pathname === "/health") {
    sendJson(res, 200, { ok: true });
    return;
  }

  if (req.method === "POST" && url.pathname === "/api/auth/redeem") {
    const body = await readJson(req);
    const code = typeof body.code === "string" ? body.code.trim() : "";
    if (!code) {
      sendJson(res, 400, { error: "code_required" });
      return;
    }

    const token = crypto.randomBytes(32).toString("base64url");
    const expiresAt = Date.now() + app.config.tokenTtlMs;
    app.sessions.set(token, { expiresAt, queryTimes: [] });

    sendJson(
      res,
      200,
      { token, expires_at: new Date(expiresAt).toISOString() },
      { "set-cookie": cookieHeader(token, app.config.tokenTtlMs / 1000) }
    );
    return;
  }

  if (req.method === "POST" && url.pathname === "/api/chat") {
    const auth = getSession(req, app.sessions);
    if (auth.status !== "ok") {
      sendJson(res, 401, { error: "invalid_or_expired_session" });
      return;
    }

    const body = await readJson(req);
    const messages = sanitizeMessages(body);
    const rate = checkRateLimit(auth.session, app.config);
    if (!rate.ok) {
      sendJson(
        res,
        429,
        { error: "rate_limit_exceeded", retry_after_seconds: rate.retryAfterSeconds },
        { "retry-after": String(rate.retryAfterSeconds) }
      );
      return;
    }

    const gatewayResponse = await proxyChat(messages, body, app.config, app.fetchImpl);
    const content = gatewayResponse.choices?.[0]?.message?.content || "";
    const parsed = parseAssistantContent(content);
    sendJson(res, 200, {
      message: { role: "assistant", content: parsed.answer },
      sources: parsed.sources,
      model: gatewayResponse.model || app.config.model,
      rate_limit: {
        limit: app.config.maxQueriesPerHour,
        remaining: rate.remaining
      }
    });
    return;
  }

  if (req.method === "GET" || req.method === "HEAD") {
    await serveStatic(req, res);
    return;
  }

  sendJson(res, 405, { error: "method_not_allowed" });
}

function createApp(options = {}) {
  const app = {
    config: createConfig(options.config || {}),
    sessions: options.sessions || new Map(),
    fetchImpl: options.fetchImpl || fetch
  };

  const server = http.createServer((req, res) => {
    handleRequest(req, res, app).catch((error) => {
      const statusCode = error.statusCode || 500;
      const message = statusCode >= 500 ? "server_error" : error.message;
      sendJson(res, statusCode, { error: message });
    });
  });

  return { ...app, server };
}

if (require.main === module) {
  const app = createApp();
  app.server.listen(app.config.port, app.config.host, () => {
    process.stdout.write(
      `demo-site listening on ${app.config.host}:${app.config.port} ` +
        `(mock=${app.config.mockGateway}, model=${app.config.model})\n`
    );
  });
}

module.exports = {
  createApp,
  parseAssistantContent,
  sanitizeMessages,
  checkRateLimit
};
