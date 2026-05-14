"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const http = require("node:http");
const https = require("node:https");
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

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade"
]);

const LOCAL_STATIC_PATHS = new Set([
  "/app.js",
  "/styles.css",
  "/favicon.ico",
  "/index.html"
]);

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

function floatFromEnv(name, fallback, min, max) {
  const raw = process.env[name];
  const parsed = Number.parseFloat(raw || "");
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

function stripTrailingSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function envString(overrides, key, envName, fallback = "") {
  if (Object.prototype.hasOwnProperty.call(overrides, key)) {
    return String(overrides[key] || "");
  }
  return String(process.env[envName] || fallback);
}

function hoursToMs(hours) {
  return Math.max(0.000001, Number(hours) || 1) * 60 * 60 * 1000;
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
    codeTtlHours:
      overrides.codeTtlHours || floatFromEnv("DEMO_SITE_CODE_TTL_HOURS", 24, 0.01, 24 * 31),
    sessionTtlHours:
      overrides.sessionTtlHours || floatFromEnv("DEMO_SITE_SESSION_TTL_HOURS", 24, 0.01, 24 * 31),
    adminToken: Object.prototype.hasOwnProperty.call(overrides, "adminToken")
      ? overrides.adminToken
      : process.env.DEMO_SITE_ADMIN_TOKEN || "",
    authStorePath:
      overrides.authStorePath ||
      process.env.DEMO_SITE_AUTH_STORE_PATH ||
      path.join("/app", "data", "auth.json"),
    maxQueriesPerHour:
      overrides.maxQueriesPerHour || intFromEnv("DEMO_SITE_MAX_QUERIES_PER_HOUR", 10, 1, 100),
    maxTokensCap: overrides.maxTokensCap || 800,
    chatTimeoutMs: overrides.chatTimeoutMs || intFromEnv("DEMO_SITE_CHAT_TIMEOUT_MS", 60_000, 1_000, 300_000),
    openWebuiEnabled:
      typeof overrides.openWebuiEnabled === "boolean"
        ? overrides.openWebuiEnabled
        : envFlag(process.env.DEMO_SITE_OPENWEBUI_ENABLED),
    openWebuiUrl:
      stripTrailingSlash(envString(overrides, "openWebuiUrl", "OPENWEBUI_URL", "http://openwebui:8080")) ||
      "http://openwebui:8080",
    openWebuiAdminEmail: envString(overrides, "openWebuiAdminEmail", "OPENWEBUI_ADMIN_EMAIL", ""),
    openWebuiAdminPassword: envString(overrides, "openWebuiAdminPassword", "OPENWEBUI_ADMIN_PASSWORD", ""),
    openWebuiTrustedEmailHeader:
      envString(overrides, "openWebuiTrustedEmailHeader", "OPENWEBUI_TRUSTED_EMAIL_HEADER", "X-Demo-Email") ||
      "X-Demo-Email",
    openWebuiTrustedNameHeader:
      envString(overrides, "openWebuiTrustedNameHeader", "OPENWEBUI_TRUSTED_NAME_HEADER", "X-Demo-Name") ||
      "X-Demo-Name",
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

function nowIso() {
  return new Date().toISOString();
}

function tokenPrefix(token) {
  return String(token || "").slice(0, 8);
}

function reviewerIdentity(session) {
  const prefix = tokenPrefix(session?.token);
  return {
    token_prefix: prefix,
    email: `demo-${prefix}@mmrag.invalid`,
    name: `Demo Reviewer ${prefix}`
  };
}

function remoteAddress(req) {
  const forwarded = req.headers["x-forwarded-for"];
  if (typeof forwarded === "string" && forwarded.trim()) {
    return forwarded.split(",")[0].trim();
  }
  return req.socket?.remoteAddress || "";
}

function optionalString(value, maxLength = 500) {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim().slice(0, maxLength);
}

function parsePositiveNumber(value, fallback, min, max) {
  const parsed = Number.parseFloat(String(value ?? ""));
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

function initialAuthData() {
  return {
    version: 1,
    access_codes: [],
    sessions: [],
    audit_events: []
  };
}

function normalizeAuthData(raw) {
  const data = raw && typeof raw === "object" ? raw : {};
  return {
    version: 1,
    access_codes: Array.isArray(data.access_codes) ? data.access_codes : [],
    sessions: Array.isArray(data.sessions) ? data.sessions : [],
    audit_events: Array.isArray(data.audit_events) ? data.audit_events : []
  };
}

function codeState(code, now = Date.now()) {
  if (code.revoked_at) {
    return "revoked";
  }
  if (Date.parse(code.expires_at) <= now) {
    return "expired";
  }
  if ((Number(code.redemption_count) || 0) >= (Number(code.max_redemptions) || 1)) {
    return "exhausted";
  }
  return "active";
}

function authError(statusCode, error, message) {
  return { ok: false, statusCode, error, message };
}

function tokenHash(value) {
  return crypto.createHash("sha256").update(String(value || "")).digest("hex");
}

class AuthStore {
  constructor(filePath) {
    this.filePath = path.resolve(filePath);
    this.data = initialAuthData();
    this.error = null;
    this.writeQueue = Promise.resolve();
    this.ready = this.load();
  }

  async load() {
    try {
      await fs.mkdir(path.dirname(this.filePath), { recursive: true });
      const raw = await fs.readFile(this.filePath, "utf8");
      this.data = normalizeAuthData(JSON.parse(raw));
      this.error = null;
    } catch (error) {
      if (error.code === "ENOENT") {
        this.data = initialAuthData();
        try {
          await this.persist();
          this.error = null;
        } catch (writeError) {
          this.error = writeError;
        }
        return;
      }
      this.error = error;
    }
  }

  async ensureAvailable() {
    await this.ready;
    if (this.error) {
      const err = new Error("auth_store_unavailable");
      err.statusCode = 503;
      err.detail = this.error.message;
      throw err;
    }
  }

  health() {
    if (this.error) {
      return { auth_store: "error", auth_store_error: this.error.message };
    }
    return { auth_store: "ok" };
  }

  async persist() {
    const write = async () => {
      await fs.mkdir(path.dirname(this.filePath), { recursive: true });
      const tmpPath = `${this.filePath}.${process.pid}.${Date.now()}.tmp`;
      const body = `${JSON.stringify(this.data, null, 2)}\n`;
      await fs.writeFile(tmpPath, body, { mode: 0o600 });
      await fs.rename(tmpPath, this.filePath);
    };
    this.writeQueue = this.writeQueue.then(write, write);
    await this.writeQueue;
  }

  audit(event, req) {
    this.data.audit_events.push({
      timestamp: nowIso(),
      event: event.event,
      code: event.code || undefined,
      token_prefix: event.token ? tokenPrefix(event.token) : event.token_prefix || undefined,
      status: event.status || "ok",
      remote_address: req ? remoteAddress(req) : undefined
    });
    this.data.audit_events = this.data.audit_events.slice(-1000);
  }

  async createCode(body, req, config) {
    await this.ensureAvailable();
    const now = Date.now();
    const ttlHours = parsePositiveNumber(body.ttl_hours, config.codeTtlHours, 0.000001, 24 * 31);
    const maxRedemptions = Math.floor(
      parsePositiveNumber(body.max_redemptions, 1, 1, 1000)
    );
    const code = `demo-${crypto.randomBytes(18).toString("base64url")}`;
    const record = {
      code,
      created_at: new Date(now).toISOString(),
      expires_at: new Date(now + hoursToMs(ttlHours)).toISOString(),
      revoked_at: null,
      max_redemptions: maxRedemptions,
      redemption_count: 0,
      label: optionalString(body.label, 120) || null,
      created_by: optionalString(body.created_by, 120) || "admin",
      notes: optionalString(body.notes, 1000) || null
    };
    this.data.access_codes.push(record);
    this.audit({ event: "code_created", code, status: "ok" }, req);
    await this.persist();
    return record;
  }

  async listCodes() {
    await this.ensureAvailable();
    const now = Date.now();
    return this.data.access_codes.map((code) => ({
      code: code.code,
      created_at: code.created_at,
      expires_at: code.expires_at,
      revoked_at: code.revoked_at || null,
      redemption_count: Number(code.redemption_count) || 0,
      max_redemptions: Number(code.max_redemptions) || 1,
      label: code.label || null,
      notes: code.notes || null,
      created_by: code.created_by || null,
      status: codeState(code, now),
      active: codeState(code, now) === "active"
    }));
  }

  findCode(codeValue) {
    return this.data.access_codes.find((record) => record.code === codeValue);
  }

  async revokeCode(codeValue, req) {
    await this.ensureAvailable();
    const code = this.findCode(codeValue);
    if (!code) {
      this.audit({ event: "code_revoke", code: codeValue, status: "not_found" }, req);
      await this.persist();
      return authError(404, "code_not_found", "Der Demo-Code wurde nicht gefunden.");
    }
    if (!code.revoked_at) {
      code.revoked_at = nowIso();
    }
    this.audit({ event: "code_revoke", code: codeValue, status: "ok" }, req);
    await this.persist();
    return { ok: true, code };
  }

  async redeemCode(codeValue, req, config) {
    await this.ensureAvailable();
    const now = Date.now();
    const code = this.findCode(codeValue);
    if (!code) {
      this.audit({ event: "code_redeem", code: codeValue, status: "invalid" }, req);
      await this.persist();
      return authError(401, "code_invalid", "Der Demo-Code ist ungueltig.");
    }

    const state = codeState(code, now);
    if (state === "revoked") {
      this.audit({ event: "code_redeem", code: codeValue, status: "revoked" }, req);
      await this.persist();
      return authError(403, "code_revoked", "Der Demo-Code wurde widerrufen.");
    }
    if (state === "expired") {
      this.audit({ event: "code_redeem", code: codeValue, status: "expired" }, req);
      await this.persist();
      return authError(410, "code_expired", "Der Demo-Code ist abgelaufen.");
    }
    if (state === "exhausted") {
      this.audit({ event: "code_redeem", code: codeValue, status: "exhausted" }, req);
      await this.persist();
      return authError(429, "code_exhausted", "Der Demo-Code wurde bereits verwendet.");
    }

    const token = crypto.randomBytes(32).toString("base64url");
    const codeExpiresAt = Date.parse(code.expires_at);
    const sessionExpiresAt = Math.min(now + hoursToMs(config.sessionTtlHours), codeExpiresAt);
    const session = {
      token,
      code: code.code,
      created_at: new Date(now).toISOString(),
      expires_at: new Date(sessionExpiresAt).toISOString(),
      revoked_at: null,
      last_seen_at: new Date(now).toISOString(),
      query_times: []
    };
    code.redemption_count = (Number(code.redemption_count) || 0) + 1;
    this.data.sessions.push(session);
    this.audit({ event: "code_redeem", code: codeValue, token, status: "ok" }, req);
    await this.persist();

    return {
      ok: true,
      token,
      expires_at: session.expires_at,
      code_expires_at: code.expires_at,
      session
    };
  }

  async validateSession(token, req) {
    await this.ensureAvailable();
    if (!token) {
      return { status: "missing" };
    }
    const session = this.data.sessions.find((record) => record.token === token);
    if (!session) {
      return { status: "invalid", token };
    }
    if (session.revoked_at) {
      return { status: "revoked", token };
    }
    if (Date.parse(session.expires_at) <= Date.now()) {
      return { status: "expired", token };
    }
    session.last_seen_at = nowIso();
    session.queryTimes = Array.isArray(session.queryTimes)
      ? session.queryTimes
      : Array.isArray(session.query_times)
        ? session.query_times
        : [];
    this.audit({ event: "session_seen", token, status: "ok" }, req);
    await this.persist();
    return { status: "ok", token, session };
  }

  async validateOpenWebuiToken(token, req) {
    await this.ensureAvailable();
    if (!token) {
      return { status: "missing" };
    }
    const hash = tokenHash(token);
    const session = this.data.sessions.find((record) => record.openwebui_token_hash === hash);
    if (!session) {
      return { status: "invalid" };
    }
    if (session.revoked_at) {
      return { status: "revoked" };
    }
    if (Date.parse(session.expires_at) <= Date.now()) {
      return { status: "expired" };
    }
    session.last_seen_at = nowIso();
    session.queryTimes = Array.isArray(session.queryTimes)
      ? session.queryTimes
      : Array.isArray(session.query_times)
        ? session.query_times
        : [];
    this.audit({ event: "session_seen", token: session.token, status: "ok" }, req);
    await this.persist();
    return { status: "ok", token: session.token, session };
  }

  async saveSession(session) {
    session.query_times = Array.isArray(session.queryTimes) ? session.queryTimes : session.query_times || [];
    await this.persist();
  }

  async revokeSessionByPrefix(prefix, req) {
    await this.ensureAvailable();
    if (prefix.length < 8) {
      return authError(400, "token_prefix_too_short", "Der Token-Praefix muss mindestens 8 Zeichen haben.");
    }
    const matches = this.data.sessions.filter((session) => session.token.startsWith(prefix));
    if (matches.length === 0) {
      return authError(404, "session_not_found", "Die Demo-Sitzung wurde nicht gefunden.");
    }
    if (matches.length > 1) {
      return authError(409, "token_prefix_ambiguous", "Der Token-Praefix ist nicht eindeutig.");
    }
    matches[0].revoked_at = matches[0].revoked_at || nowIso();
    this.audit({ event: "session_revoke", token: matches[0].token, status: "ok" }, req);
    await this.persist();
    return { ok: true, token_prefix: tokenPrefix(matches[0].token), revoked_at: matches[0].revoked_at };
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

function cookieValue(value, cookieName) {
  const raw = Array.isArray(value) ? value.join("; ") : String(value || "");
  for (const part of raw.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === cookieName) {
      return rest.join("=");
    }
  }
  return "";
}

function tokenFromRequest(req) {
  const authorization = req.headers.authorization || "";
  const bearer = authorization.match(/^Bearer\s+(.+)$/i);
  if (bearer) {
    return bearer[1].trim();
  }

  const token = cookieValue(req.headers.cookie, "demo_session");
  return token ? decodeURIComponent(token) : "";
}

function openWebuiTokenFromRequest(req) {
  return cookieValue(req.headers.cookie, "token");
}

function openWebuiTokenFromSetCookies(cookies) {
  for (const cookie of cookies) {
    const token = cookieValue(String(cookie).split(";")[0], "token");
    if (token) {
      return token;
    }
  }
  return "";
}

async function getSession(req, authStore) {
  const token = tokenFromRequest(req);
  return authStore.validateSession(token, req);
}

async function getOpenWebuiMuxSession(req, authStore) {
  const auth = await getSession(req, authStore);
  if (auth.status === "ok") {
    return auth;
  }
  const openWebuiToken = openWebuiTokenFromRequest(req);
  if (!openWebuiToken) {
    return auth;
  }
  return authStore.validateOpenWebuiToken(openWebuiToken, req);
}

function trustedHeaders(config, identity) {
  return {
    [config.openWebuiTrustedEmailHeader]: identity.email,
    [config.openWebuiTrustedNameHeader]: identity.name
  };
}

async function openWebuiResponseBody(response) {
  const text = await response.text().catch(() => "");
  if (!text.trim()) {
    return { text, json: null };
  }
  try {
    return { text, json: JSON.parse(text) };
  } catch {
    return { text, json: null };
  }
}

function responseSetCookies(response) {
  if (typeof response.headers.getSetCookie === "function") {
    return response.headers.getSetCookie();
  }
  const cookie = response.headers.get("set-cookie");
  return cookie ? [cookie] : [];
}

function openWebuiError(message, statusCode = 502) {
  const err = new Error(message);
  err.statusCode = statusCode;
  return err;
}

function isOpenWebuiDuplicateUser(response, body) {
  const detail = String(body.json?.detail || body.json?.message || body.text || "");
  return response.status === 400 && detail.includes("This email is already registered");
}

async function openWebuiAdminSignin(config, fetchImpl) {
  const adminIdentity = {
    email: config.openWebuiAdminEmail,
    name: "Demo Admin"
  };
  const response = await fetchImpl(`${config.openWebuiUrl}/api/v1/auths/signin`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...trustedHeaders(config, adminIdentity)
    },
    body: JSON.stringify({
      email: config.openWebuiAdminEmail,
      password: config.openWebuiAdminPassword
    })
  });
  const body = await openWebuiResponseBody(response);
  if (!response.ok) {
    throw openWebuiError(`openwebui_admin_signin_${response.status}`);
  }
  const token = body.json?.token || body.json?.access_token;
  if (!token) {
    throw openWebuiError("openwebui_admin_token_missing");
  }
  return token;
}

async function openWebuiEnsureReviewer(config, fetchImpl, identity) {
  if (!config.openWebuiAdminEmail || !config.openWebuiAdminPassword) {
    return { skipped: true };
  }

  const adminToken = await openWebuiAdminSignin(config, fetchImpl);
  const throwawayPassword = crypto.randomBytes(24).toString("base64url");
  const response = await fetchImpl(`${config.openWebuiUrl}/api/v1/auths/add`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${adminToken}`
    },
    body: JSON.stringify({
      name: identity.name,
      email: identity.email,
      password: throwawayPassword,
      role: "user"
    })
  });
  const body = await openWebuiResponseBody(response);
  if (response.ok || isOpenWebuiDuplicateUser(response, body)) {
    return { skipped: false };
  }
  throw openWebuiError(`openwebui_add_user_${response.status}`);
}

async function openWebuiReviewerSignin(config, fetchImpl, identity) {
  const response = await fetchImpl(`${config.openWebuiUrl}/api/v1/auths/signin`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...trustedHeaders(config, identity)
    },
    body: JSON.stringify({
      email: identity.email,
      password: ""
    })
  });
  await openWebuiResponseBody(response);
  if (!response.ok) {
    throw openWebuiError(`openwebui_reviewer_signin_${response.status}`);
  }
  return { cookies: responseSetCookies(response) };
}

async function handleOpenWebuiStart(req, res, app) {
  if (req.method !== "POST") {
    sendJson(res, 405, { error: "method_not_allowed" });
    return true;
  }

  const auth = await getSession(req, app.authStore);
  if (auth.status !== "ok") {
    sendJson(res, 401, { error: "invalid_or_expired_session" });
    return true;
  }

  if (!app.config.openWebuiEnabled) {
    sendJson(res, 503, {
      error: "openwebui_disabled",
      message: "OpenWebUI ist fuer diese Demo nicht aktiviert."
    });
    return true;
  }

  const identity = reviewerIdentity(auth.session);
  try {
    await openWebuiEnsureReviewer(app.config, app.fetchImpl, identity);
    const signin = await openWebuiReviewerSignin(app.config, app.fetchImpl, identity);
    const openWebuiToken = openWebuiTokenFromSetCookies(signin.cookies);
    if (openWebuiToken) {
      auth.session.openwebui_token_hash = tokenHash(openWebuiToken);
      await app.authStore.saveSession(auth.session);
    }
    const maxAgeSeconds = Math.max(1, (Date.parse(auth.session.expires_at) - Date.now()) / 1000);
    const cookies = [...signin.cookies, cookieHeader(auth.session.token, maxAgeSeconds)];
    const headers = { "set-cookie": cookies };
    sendJson(res, 200, { ok: true, redirect: "/" }, headers);
  } catch {
    sendJson(res, 502, {
      error: "openwebui_bootstrap_failed",
      message: "OpenWebUI konnte nicht gestartet werden."
    });
  }
  return true;
}

function isReservedLocalPath(pathname) {
  return (
    pathname === "/health" ||
    pathname === "/api/chat" ||
    pathname.startsWith("/api/auth/") ||
    pathname === "/api/admin" ||
    pathname.startsWith("/api/admin/") ||
    pathname === "/api/openwebui" ||
    pathname.startsWith("/api/openwebui/") ||
    pathname === "/classic" ||
    pathname.startsWith("/classic/") ||
    LOCAL_STATIC_PATHS.has(pathname)
  );
}

function connectionHeaderNames(headers) {
  return String(headers.connection || "")
    .split(",")
    .map((name) => name.trim().toLowerCase())
    .filter(Boolean);
}

function openWebuiRequestPath(targetUrl, reqUrl) {
  const basePath = targetUrl.pathname === "/" ? "" : targetUrl.pathname.replace(/\/+$/, "");
  const requestPath = String(reqUrl || "/").startsWith("/") ? String(reqUrl || "/") : `/${reqUrl || ""}`;
  return `${basePath}${requestPath}`;
}

function openWebuiCookieHeader(value) {
  const raw = Array.isArray(value) ? value.join("; ") : String(value || "");
  return raw
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean)
    .filter((part) => part.split("=")[0].trim() !== "demo_session")
    .join("; ");
}

function openWebuiRequestHeaders(req, config, identity, targetUrl) {
  const headers = {};
  const connectionScoped = new Set(connectionHeaderNames(req.headers));
  const trustedEmailHeader = config.openWebuiTrustedEmailHeader.toLowerCase();
  const trustedNameHeader = config.openWebuiTrustedNameHeader.toLowerCase();

  for (const [name, value] of Object.entries(req.headers)) {
    const lowerName = name.toLowerCase();
    if (
      lowerName === "host" ||
      lowerName === "authorization" ||
      HOP_BY_HOP_HEADERS.has(lowerName) ||
      connectionScoped.has(lowerName) ||
      lowerName === trustedEmailHeader ||
      lowerName === trustedNameHeader ||
      lowerName.startsWith("x-demo-")
    ) {
      continue;
    }
    if (lowerName === "cookie") {
      const cookie = openWebuiCookieHeader(value);
      if (cookie) {
        headers[name] = cookie;
      }
      continue;
    }
    headers[name] = value;
  }

  headers.host = targetUrl.host;
  Object.assign(headers, trustedHeaders(config, identity));
  return headers;
}

function openWebuiResponseHeaders(upstreamHeaders) {
  const connectionScoped = new Set(connectionHeaderNames(upstreamHeaders));
  const headers = {};
  for (const [name, value] of Object.entries(upstreamHeaders)) {
    const lowerName = name.toLowerCase();
    if (HOP_BY_HOP_HEADERS.has(lowerName) || connectionScoped.has(lowerName)) {
      continue;
    }
    headers[name] = value;
  }
  return headers;
}

function sendOpenWebuiProxyError(req, res) {
  if (res.headersSent) {
    res.destroy();
    return;
  }

  const wantsJson =
    String(req.headers.accept || "").includes("application/json") ||
    String(req.url || "").startsWith("/api/");
  if (wantsJson) {
    sendJson(res, 502, {
      error: "openwebui_upstream_unavailable",
      message: "OpenWebUI upstream is unavailable."
    });
    return;
  }

  const body = "OpenWebUI upstream is unavailable.";
  res.writeHead(502, {
    "content-type": "text/plain; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store"
  });
  res.end(body);
}

function writeSocketHttpError(socket, statusCode, statusMessage) {
  if (socket.destroyed) {
    return;
  }
  const reason = statusMessage || "Error";
  socket.end(
    [
      `HTTP/1.1 ${statusCode} ${reason}`,
      "Connection: close",
      "Content-Length: 0",
      "",
      ""
    ].join("\r\n")
  );
}

function proxyOpenWebuiRequest(req, res, app, identity) {
  return new Promise((resolve) => {
    let settled = false;
    const settle = () => {
      if (!settled) {
        settled = true;
        resolve();
      }
    };

    let targetUrl;
    try {
      targetUrl = new URL(app.config.openWebuiUrl);
    } catch {
      sendOpenWebuiProxyError(req, res);
      settle();
      return;
    }

    const transport = targetUrl.protocol === "https:" ? https : http;
    const upstreamReq = transport.request(
      {
        protocol: targetUrl.protocol,
        hostname: targetUrl.hostname,
        port: targetUrl.port,
        method: req.method,
        path: openWebuiRequestPath(targetUrl, req.url),
        headers: openWebuiRequestHeaders(req, app.config, identity, targetUrl)
      },
      (upstreamRes) => {
        const responseHeaders = openWebuiResponseHeaders(upstreamRes.headers);
        if (upstreamRes.statusMessage) {
          res.writeHead(upstreamRes.statusCode || 502, upstreamRes.statusMessage, responseHeaders);
        } else {
          res.writeHead(upstreamRes.statusCode || 502, responseHeaders);
        }
        upstreamRes.pipe(res);
        upstreamRes.on("end", settle);
        upstreamRes.on("error", () => {
          if (!res.destroyed) {
            res.destroy();
          }
          settle();
        });
      }
    );

    upstreamReq.on("error", () => {
      sendOpenWebuiProxyError(req, res);
      settle();
    });
    req.on("aborted", () => {
      upstreamReq.destroy();
      settle();
    });
    req.pipe(upstreamReq);
  });
}

function openWebuiUpgradeHeaders(req, config, identity, targetUrl) {
  const headers = openWebuiRequestHeaders(req, config, identity, targetUrl);
  headers.connection = "Upgrade";
  headers.upgrade = String(req.headers.upgrade || "websocket");
  return headers;
}

function proxyOpenWebuiUpgrade(req, socket, head, app, identity) {
  let upstreamSocket = null;
  let settled = false;
  const destroyBoth = () => {
    if (settled) {
      return;
    }
    settled = true;
    if (!socket.destroyed) {
      socket.destroy();
    }
    if (upstreamSocket && !upstreamSocket.destroyed) {
      upstreamSocket.destroy();
    }
  };

  let targetUrl;
  try {
    targetUrl = new URL(app.config.openWebuiUrl);
  } catch {
    writeSocketHttpError(socket, 502, "Bad Gateway");
    return;
  }

  const transport = targetUrl.protocol === "https:" ? https : http;
  const upstreamReq = transport.request({
    protocol: targetUrl.protocol,
    hostname: targetUrl.hostname,
    port: targetUrl.port,
    method: req.method,
    path: openWebuiRequestPath(targetUrl, req.url),
    headers: openWebuiUpgradeHeaders(req, app.config, identity, targetUrl)
  });

  upstreamReq.on("upgrade", (upstreamRes, nextUpstreamSocket, upstreamHead) => {
    upstreamSocket = nextUpstreamSocket;
    const statusCode = upstreamRes.statusCode || 101;
    const statusMessage = upstreamRes.statusMessage || "Switching Protocols";
    socket.write(`HTTP/1.1 ${statusCode} ${statusMessage}\r\n`);
    for (let i = 0; i < upstreamRes.rawHeaders.length; i += 2) {
      socket.write(`${upstreamRes.rawHeaders[i]}: ${upstreamRes.rawHeaders[i + 1]}\r\n`);
    }
    socket.write("\r\n");

    if (upstreamHead?.length) {
      socket.write(upstreamHead);
    }
    if (head?.length) {
      upstreamSocket.write(head);
    }

    socket.on("error", destroyBoth);
    upstreamSocket.on("error", destroyBoth);
    socket.pipe(upstreamSocket);
    upstreamSocket.pipe(socket);
  });

  upstreamReq.on("response", (upstreamRes) => {
    const statusCode = upstreamRes.statusCode || 502;
    const statusMessage = upstreamRes.statusMessage || "Bad Gateway";
    socket.write(`HTTP/1.1 ${statusCode} ${statusMessage}\r\n`);
    for (let i = 0; i < upstreamRes.rawHeaders.length; i += 2) {
      socket.write(`${upstreamRes.rawHeaders[i]}: ${upstreamRes.rawHeaders[i + 1]}\r\n`);
    }
    socket.write("\r\n");
    upstreamRes.pipe(socket);
    upstreamRes.on("end", () => socket.end());
    upstreamRes.on("error", destroyBoth);
  });

  upstreamReq.on("error", () => {
    writeSocketHttpError(socket, 502, "Bad Gateway");
  });
  socket.on("error", () => upstreamReq.destroy());
  socket.on("close", () => {
    upstreamReq.destroy();
    if (upstreamSocket && !upstreamSocket.destroyed) {
      upstreamSocket.destroy();
    }
  });
  upstreamReq.end();
}

async function handleOpenWebuiUpgrade(req, socket, head, app) {
  let url;
  try {
    url = new URL(req.url || "/", "http://127.0.0.1");
  } catch {
    writeSocketHttpError(socket, 400, "Bad Request");
    return;
  }

  if (!app.config.openWebuiEnabled || isReservedLocalPath(url.pathname)) {
    writeSocketHttpError(socket, 404, "Not Found");
    return;
  }

  const auth = await getOpenWebuiMuxSession(req, app.authStore);
  if (auth.status !== "ok") {
    writeSocketHttpError(socket, 401, "Unauthorized");
    return;
  }

  proxyOpenWebuiUpgrade(req, socket, head, app, reviewerIdentity(auth.session));
}

function checkRateLimit(session, config, now = Date.now()) {
  const windowStart = now - 60 * 60 * 1000;
  session.queryTimes = (Array.isArray(session.queryTimes) ? session.queryTimes : session.query_times || []).filter(
    (timestamp) => timestamp > windowStart
  );
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

function safeEqual(value, expected) {
  const left = Buffer.from(String(value || ""));
  const right = Buffer.from(String(expected || ""));
  if (left.length !== right.length) {
    return false;
  }
  return crypto.timingSafeEqual(left, right);
}

function requireAdmin(req, config) {
  if (!config.adminToken) {
    return authError(
      503,
      "admin_disabled",
      "Admin-Endpunkte sind deaktiviert, weil DEMO_SITE_ADMIN_TOKEN nicht gesetzt ist."
    );
  }
  const authorization = req.headers.authorization || "";
  const bearer = authorization.match(/^Bearer\s+(.+)$/i);
  if (!bearer || !safeEqual(bearer[1].trim(), config.adminToken)) {
    return authError(401, "admin_unauthorized", "Admin-Token fehlt oder ist ungueltig.");
  }
  return { ok: true };
}

function codeFromRevokePath(pathname) {
  const match = pathname.match(/^\/api\/admin\/codes\/(.+)\/revoke$/);
  if (!match) {
    return "";
  }
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return "";
  }
}

function tokenPrefixFromRevokePath(pathname) {
  const match = pathname.match(/^\/api\/admin\/sessions\/([^/]+)\/revoke$/);
  if (!match) {
    return "";
  }
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return "";
  }
}

async function handleAdminRequest(req, res, app, url) {
  const admin = requireAdmin(req, app.config);
  if (!admin.ok) {
    sendJson(res, admin.statusCode, { error: admin.error, message: admin.message });
    return true;
  }

  if (url.pathname === "/api/admin/codes" && req.method === "POST") {
    const body = await readJson(req);
    const code = await app.authStore.createCode(body, req, app.config);
    sendJson(res, 200, {
      code: code.code,
      expires_at: code.expires_at,
      max_redemptions: code.max_redemptions
    });
    return true;
  }

  if (url.pathname === "/api/admin/codes" && req.method === "GET") {
    sendJson(res, 200, { codes: await app.authStore.listCodes() });
    return true;
  }

  const codeValue = codeFromRevokePath(url.pathname);
  if (codeValue && req.method === "POST") {
    const result = await app.authStore.revokeCode(codeValue, req);
    if (!result.ok) {
      sendJson(res, result.statusCode, { error: result.error, message: result.message });
      return true;
    }
    sendJson(res, 200, {
      code: result.code.code,
      revoked_at: result.code.revoked_at,
      status: codeState(result.code)
    });
    return true;
  }

  const prefix = tokenPrefixFromRevokePath(url.pathname);
  if (prefix && req.method === "POST") {
    const result = await app.authStore.revokeSessionByPrefix(prefix, req);
    if (!result.ok) {
      sendJson(res, result.statusCode, { error: result.error, message: result.message });
      return true;
    }
    sendJson(res, 200, result);
    return true;
  }

  return false;
}

async function handleRequest(req, res, app) {
  const url = new URL(req.url, "http://127.0.0.1");

  if (req.method === "OPTIONS") {
    sendNoContent(res);
    return;
  }

  if (req.method === "GET" && url.pathname === "/health") {
    await app.authStore.ready;
    const health = app.authStore.health();
    sendJson(res, health.auth_store === "ok" ? 200 : 503, { ok: health.auth_store === "ok", ...health });
    return;
  }

  if (url.pathname.startsWith("/api/admin/")) {
    const handled = await handleAdminRequest(req, res, app, url);
    if (handled) {
      return;
    }
  }

  if (req.method === "POST" && url.pathname === "/api/auth/redeem") {
    const body = await readJson(req);
    const code = typeof body.code === "string" ? body.code.trim() : "";
    if (!code) {
      sendJson(res, 400, { error: "code_required", message: "Bitte einen Demo-Code eingeben." });
      return;
    }

    const result = await app.authStore.redeemCode(code, req, app.config);
    if (!result.ok) {
      sendJson(res, result.statusCode, { error: result.error, message: result.message });
      return;
    }

    const maxAgeSeconds = Math.max(1, (Date.parse(result.expires_at) - Date.now()) / 1000);
    sendJson(
      res,
      200,
      { token: result.token, expires_at: result.expires_at, code_expires_at: result.code_expires_at },
      { "set-cookie": cookieHeader(result.token, maxAgeSeconds) }
    );
    return;
  }

  if (url.pathname === "/api/openwebui/start") {
    const handled = await handleOpenWebuiStart(req, res, app);
    if (handled) {
      return;
    }
  }

  if (req.method === "POST" && url.pathname === "/api/chat") {
    const auth = await getSession(req, app.authStore);
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
    await app.authStore.saveSession(auth.session);

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

  if (app.config.openWebuiEnabled && !isReservedLocalPath(url.pathname)) {
    const auth = await getOpenWebuiMuxSession(req, app.authStore);
    if (auth.status === "ok") {
      await proxyOpenWebuiRequest(req, res, app, reviewerIdentity(auth.session));
      return;
    }
    if (url.pathname.startsWith("/api/")) {
      sendJson(res, 401, { error: "invalid_or_expired_session" });
      return;
    }
  }

  if (req.method === "GET" || req.method === "HEAD") {
    await serveStatic(req, res);
    return;
  }

  sendJson(res, 405, { error: "method_not_allowed" });
}

function createApp(options = {}) {
  const config = createConfig(options.config || {});
  const app = {
    config,
    authStore: options.authStore || new AuthStore(config.authStorePath),
    fetchImpl: options.fetchImpl || fetch
  };

  const server = http.createServer((req, res) => {
    handleRequest(req, res, app).catch((error) => {
      const statusCode = error.statusCode || 500;
      const message = statusCode >= 500 && error.message !== "auth_store_unavailable" ? "server_error" : error.message;
      sendJson(res, statusCode, {
        error: message,
        message: error.detail || undefined
      });
    });
  });
  server.on("upgrade", (req, socket, head) => {
    handleOpenWebuiUpgrade(req, socket, head, app).catch(() => {
      writeSocketHttpError(socket, 502, "Bad Gateway");
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
  AuthStore,
  createApp,
  parseAssistantContent,
  sanitizeMessages,
  checkRateLimit
};
