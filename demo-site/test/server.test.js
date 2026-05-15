"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const test = require("node:test");
const { createApp, parseAssistantContent, reviewerPassword } = require("../server/index.js");

const ADMIN_TOKEN = "admin-test-token";

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolve(`http://127.0.0.1:${address.port}`);
    });
  });
}

async function close(server) {
  await new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

function readStubBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

async function startOpenWebuiStub(handler) {
  const calls = [];
  const server = http.createServer((req, res) => {
    Promise.resolve()
      .then(async () => {
        const call = {
          method: req.method,
          url: req.url,
          headers: req.headers,
          body: await readStubBody(req)
        };
        calls.push(call);
        await handler(req, res, calls, call);
      })
      .catch((error) => {
        if (!res.headersSent) {
          res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
        }
        res.end(error.message);
      });
  });
  const baseUrl = await listen(server);
  return {
    baseUrl,
    calls,
    cleanup: () => close(server)
  };
}

async function startOpenWebuiUpgradeStub(handler) {
  const calls = [];
  const server = http.createServer((_req, res) => {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end("unexpected http request");
  });
  server.on("upgrade", (req, socket, head) => {
    Promise.resolve()
      .then(async () => {
        const call = {
          method: req.method,
          url: req.url,
          headers: req.headers,
          headLength: head.length
        };
        calls.push(call);
        await handler(req, socket, head, calls, call);
      })
      .catch((error) => {
        socket.end(
          [
            "HTTP/1.1 500 Internal Server Error",
            "Content-Type: text/plain; charset=utf-8",
            `Content-Length: ${Buffer.byteLength(error.message)}`,
            "",
            error.message
          ].join("\r\n")
        );
      });
  });
  const baseUrl = await listen(server);
  return {
    baseUrl,
    calls,
    cleanup: () => close(server)
  };
}

async function tempStorePath() {
  const dir = await fs.mkdtemp(path.join(process.cwd(), ".tmp-auth-test-"));
  return {
    dir,
    authStorePath: path.join(dir, "auth.json"),
    cleanup: () => fs.rm(dir, { recursive: true, force: true })
  };
}

async function startApp(config = {}, options = {}) {
  const temp = await tempStorePath();
  const app = createApp({
    ...options,
    config: {
      mockGateway: true,
      adminToken: ADMIN_TOKEN,
      authStorePath: temp.authStorePath,
      ...config
    }
  });
  const baseUrl = await listen(app.server);
  return {
    app,
    baseUrl,
    authStorePath: temp.authStorePath,
    cleanup: async () => {
      await close(app.server);
      await app.authStore.ready.catch(() => {});
      await app.authStore.writeQueue.catch(() => {});
      await temp.cleanup();
    }
  };
}

async function adminCreateCode(baseUrl, body = {}, adminToken = ADMIN_TOKEN) {
  const response = await fetch(`${baseUrl}/api/admin/codes`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${adminToken}`
    },
    body: JSON.stringify(body)
  });
  const data = await response.json();
  assert.equal(response.status, 200);
  return data;
}

async function redeem(baseUrl, code) {
  const response = await fetch(`${baseUrl}/api/auth/redeem`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code })
  });
  const data = await response.json();
  return { response, data };
}

async function assertRedeemOk(baseUrl, code) {
  const result = await redeem(baseUrl, code);
  assert.equal(result.response.status, 200);
  return result.data;
}

async function createSession(baseUrl) {
  const created = await adminCreateCode(baseUrl);
  return assertRedeemOk(baseUrl, created.code);
}

function sessionCookie(token) {
  return `demo_session=${encodeURIComponent(token)}`;
}

function jsonResponse(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json",
      ...headers
    }
  });
}

function parseFetchBody(options) {
  return options.body ? JSON.parse(options.body) : null;
}

function openWebuiSigninFetch(openWebuiToken = "openwebui-cookie") {
  return async () =>
    jsonResponse(
      { token: "reviewer-jwt" },
      200,
      { "set-cookie": `token=${openWebuiToken}; Path=/; HttpOnly; SameSite=Lax` }
    );
}

function websocketUpgrade(baseUrl, requestPath = "/ws/socket.io/?EIO=4&transport=websocket", headers = {}) {
  const target = new URL(baseUrl);
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(
      {
        host: target.hostname,
        port: Number(target.port)
      },
      () => {
        const headerLines = [
          `GET ${requestPath} HTTP/1.1`,
          `Host: ${target.host}`,
          "Upgrade: websocket",
          "Connection: Upgrade",
          "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==",
          "Sec-WebSocket-Version: 13"
        ];
        for (const [name, value] of Object.entries(headers)) {
          headerLines.push(`${name}: ${value}`);
        }
        socket.write(`${headerLines.join("\r\n")}\r\n\r\n`);
      }
    );

    let raw = "";
    const timeout = setTimeout(() => {
      socket.destroy();
      reject(new Error("upgrade_timeout"));
    }, 2000);

    socket.setEncoding("utf8");
    socket.on("data", (chunk) => {
      raw += chunk;
      if (raw.includes("\r\n\r\n")) {
        clearTimeout(timeout);
        socket.destroy();
        const [head] = raw.split("\r\n\r\n");
        const lines = head.split("\r\n");
        const statusCode = Number.parseInt(lines[0].split(" ")[1] || "0", 10);
        const responseHeaders = {};
        for (const line of lines.slice(1)) {
          const index = line.indexOf(":");
          if (index > -1) {
            responseHeaders[line.slice(0, index).toLowerCase()] = line.slice(index + 1).trim();
          }
        }
        resolve({ raw, statusCode, headers: responseHeaders });
      }
    });
    socket.on("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    socket.on("close", () => clearTimeout(timeout));
  });
}

test("parseAssistantContent separates Quellen links", () => {
  const parsed = parseAssistantContent(
    "Antwort\n\nQuellen:\n- [RSS: Titel](https://example.test/a)\n- Seite 3"
  );
  assert.equal(parsed.answer, "Antwort");
  assert.deepEqual(parsed.sources, [
    { label: "RSS: Titel", url: "https://example.test/a" },
    { label: "Seite 3", url: "" }
  ]);
});

test("reviewerPassword is deterministic for the same token and secret", () => {
  const a = reviewerPassword("session-token-abcd1234", "secret-1");
  const b = reviewerPassword("session-token-abcd1234", "secret-1");
  const c = reviewerPassword("session-token-abcd1234", "secret-2");
  const d = reviewerPassword("different-token", "secret-1");
  assert.equal(typeof a, "string");
  assert.equal(a.length, 32);
  assert.match(a, /^[A-Za-z0-9_-]{32}$/);
  assert.equal(a, b);
  assert.notEqual(a, c);
  assert.notEqual(a, d);
  assert.equal(a.includes("session-token-abcd1234"), false);
  assert.equal(a.includes("abcd1234"), false);
});

test("reviewerPassword throws when secret is missing", () => {
  assert.throws(() => reviewerPassword("session-token", ""), /secret/i);
  assert.throws(() => reviewerPassword("session-token", null), /secret/i);
  assert.throws(() => reviewerPassword("session-token", undefined), /secret/i);
});

test("admin token missing disables code creation", async () => {
  const appContext = await startApp({ adminToken: "" });
  try {
    const response = await fetch(`${appContext.baseUrl}/api/admin/codes`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({})
    });
    const data = await response.json();
    assert.equal(response.status, 503);
    assert.equal(data.error, "admin_disabled");
  } finally {
    await appContext.cleanup();
  }
});

test("wrong admin token is rejected", async () => {
  const appContext = await startApp();
  try {
    const response = await fetch(`${appContext.baseUrl}/api/admin/codes`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer wrong"
      },
      body: JSON.stringify({})
    });
    const data = await response.json();
    assert.equal(response.status, 401);
    assert.equal(data.error, "admin_unauthorized");
  } finally {
    await appContext.cleanup();
  }
});

test("admin creates a random persistent access code", async () => {
  const appContext = await startApp();
  try {
    const created = await adminCreateCode(appContext.baseUrl, {
      ttl_hours: 24,
      max_redemptions: 2,
      label: "Sven",
      notes: "Demo"
    });
    assert.match(created.code, /^demo-[A-Za-z0-9_-]{20,}$/);
    assert.equal(created.max_redemptions, 2);
    assert.ok(Date.parse(created.expires_at) > Date.now());

    const stored = JSON.parse(await fs.readFile(appContext.authStorePath, "utf8"));
    assert.equal(stored.access_codes.length, 1);
    assert.equal(stored.access_codes[0].code, created.code);
    assert.equal(stored.access_codes[0].label, "Sven");
  } finally {
    await appContext.cleanup();
  }
});

test("redeeming a valid code creates a session and increments redemption_count", async () => {
  const appContext = await startApp();
  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const session = await assertRedeemOk(appContext.baseUrl, created.code);
    assert.match(session.token, /^[A-Za-z0-9_-]+$/);
    assert.ok(Date.parse(session.expires_at) > Date.now());
    assert.equal(session.code_expires_at, created.expires_at);

    const stored = JSON.parse(await fs.readFile(appContext.authStorePath, "utf8"));
    assert.equal(stored.access_codes[0].redemption_count, 1);
    assert.equal(stored.sessions.length, 1);
    assert.equal(stored.sessions[0].code, created.code);
  } finally {
    await appContext.cleanup();
  }
});

test("single-use code cannot be redeemed twice", async () => {
  const appContext = await startApp();
  try {
    const created = await adminCreateCode(appContext.baseUrl, { max_redemptions: 1 });
    await assertRedeemOk(appContext.baseUrl, created.code);
    const second = await redeem(appContext.baseUrl, created.code);
    assert.equal(second.response.status, 429);
    assert.equal(second.data.error, "code_exhausted");
  } finally {
    await appContext.cleanup();
  }
});

test("expired code is rejected", async () => {
  const appContext = await startApp();
  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const record = appContext.app.authStore.findCode(created.code);
    record.expires_at = new Date(Date.now() - 1000).toISOString();
    await appContext.app.authStore.persist();

    const result = await redeem(appContext.baseUrl, created.code);
    assert.equal(result.response.status, 410);
    assert.equal(result.data.error, "code_expired");
  } finally {
    await appContext.cleanup();
  }
});

test("revoked code is rejected", async () => {
  const appContext = await startApp();
  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const revoke = await fetch(
      `${appContext.baseUrl}/api/admin/codes/${encodeURIComponent(created.code)}/revoke`,
      {
        method: "POST",
        headers: { authorization: `Bearer ${ADMIN_TOKEN}` }
      }
    );
    assert.equal(revoke.status, 200);

    const result = await redeem(appContext.baseUrl, created.code);
    assert.equal(result.response.status, 403);
    assert.equal(result.data.error, "code_revoked");
  } finally {
    await appContext.cleanup();
  }
});

test("chat without a token returns 401", async () => {
  const appContext = await startApp();
  try {
    const response = await fetch(`${appContext.baseUrl}/api/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: "Hallo" })
    });
    assert.equal(response.status, 401);
  } finally {
    await appContext.cleanup();
  }
});

test("OpenWebUI start returns 503 when hybrid mode is disabled", async () => {
  let openWebuiCalls = 0;
  const appContext = await startApp({}, {
    fetchImpl: async () => {
      openWebuiCalls += 1;
      return jsonResponse({});
    }
  });
  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const session = await assertRedeemOk(appContext.baseUrl, created.code);
    const response = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${session.token}` }
    });
    const data = await response.json();
    assert.equal(response.status, 503);
    assert.equal(data.error, "openwebui_disabled");
    assert.equal(openWebuiCalls, 0);
  } finally {
    await appContext.cleanup();
  }
});

test("OpenWebUI start without a demo session returns 401", async () => {
  let openWebuiCalls = 0;
  const appContext = await startApp(
    { openWebuiEnabled: true },
    {
      fetchImpl: async () => {
        openWebuiCalls += 1;
        return jsonResponse({});
      }
    }
  );
  try {
    const response = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST"
    });
    const data = await response.json();
    assert.equal(response.status, 401);
    assert.equal(data.error, "invalid_or_expired_session");
    assert.equal(response.headers.get("set-cookie"), null);
    assert.equal(openWebuiCalls, 0);
  } finally {
    await appContext.cleanup();
  }
});

test("OpenWebUI start pre-creates reviewer and relays signin cookie", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({
      url: String(url),
      method: options.method,
      headers: options.headers,
      body: parseFetchBody(options)
    });
    if (String(url).endsWith("/api/v1/auths/signin") && calls.length === 1) {
      return jsonResponse({ token: "admin-jwt" });
    }
    if (String(url).endsWith("/api/v1/auths/add")) {
      return jsonResponse({ id: "reviewer-id" });
    }
    return jsonResponse(
      { token: "reviewer-jwt" },
      200,
      { "set-cookie": "token=reviewer-cookie; Path=/; HttpOnly; SameSite=Lax" }
    );
  };
  const appContext = await startApp(
    {
      openWebuiEnabled: true,
      openWebuiUrl: "http://openwebui.test/",
      openWebuiAdminEmail: "admin@mmrag.invalid",
      openWebuiAdminPassword: "admin-pass",
      openWebuiPasswordSecret: "test-secret"
    },
    { fetchImpl }
  );

  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const session = await assertRedeemOk(appContext.baseUrl, created.code);
    const prefix = session.token.slice(0, 8);
    const reviewerEmail = `demo2-${prefix}@mmrag.invalid`;
    const reviewerName = `Demo Reviewer ${prefix}`;

    const response = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${session.token}` }
    });
    const data = await response.json();

    assert.equal(response.status, 200);
    assert.deepEqual(data, { ok: true, redirect: "/" });
    const setCookie = response.headers.get("set-cookie") || "";
    assert.match(setCookie, /token=reviewer-cookie/);
    assert.match(setCookie, /demo_session=/);
    assert.match(setCookie, /Path=\//);
    assert.match(setCookie, /HttpOnly/);
    const storedText = await fs.readFile(appContext.authStorePath, "utf8");
    const stored = JSON.parse(storedText);
    const storedSession = stored.sessions.find((item) => item.token === session.token);
    assert.match(storedSession.openwebui_token_hash, /^[a-f0-9]{64}$/);
    assert.equal(storedText.includes("reviewer-cookie"), false);
    assert.equal(calls.length, 3);

    assert.equal(calls[0].url, "http://openwebui.test/api/v1/auths/signin");
    assert.equal(calls[0].method, "POST");
    assert.equal(calls[0].headers["X-Demo-Email"], undefined);
    assert.equal(calls[0].headers["x-demo-email"], undefined);
    assert.equal(calls[0].headers["X-Demo-Name"], undefined);
    assert.equal(calls[0].headers["x-demo-name"], undefined);
    assert.deepEqual(calls[0].body, {
      email: "admin@mmrag.invalid",
      password: "admin-pass"
    });

    assert.equal(calls[1].url, "http://openwebui.test/api/v1/auths/add");
    assert.equal(calls[1].headers.authorization, "Bearer admin-jwt");
    assert.equal(calls[1].body.name, reviewerName);
    assert.equal(calls[1].body.email, reviewerEmail);
    assert.equal(calls[1].body.role, "user");
    assert.equal(typeof calls[1].body.password, "string");
    assert.equal(calls[1].body.password.length, 32);
    assert.match(calls[1].body.password, /^[A-Za-z0-9_-]{32}$/);
    assert.equal(calls[1].body.password.includes(prefix), false);
    assert.equal(calls[1].body.password.includes(session.token), false);

    assert.equal(calls[2].url, "http://openwebui.test/api/v1/auths/signin");
    assert.equal(calls[2].headers["X-Demo-Email"], undefined);
    assert.equal(calls[2].headers["x-demo-email"], undefined);
    assert.equal(calls[2].headers["X-Demo-Name"], undefined);
    assert.equal(calls[2].headers["x-demo-name"], undefined);
    assert.deepEqual(calls[2].body, {
      email: reviewerEmail,
      password: calls[1].body.password
    });
    assert.equal(JSON.stringify(calls).includes(session.token), false);
    assert.equal(JSON.stringify(calls).includes(session.token.slice(8)), false);
  } finally {
    await appContext.cleanup();
  }
});

test("OpenWebUI duplicate reviewer creation still bootstraps session", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({
      url: String(url),
      method: options.method,
      headers: options.headers,
      body: parseFetchBody(options)
    });
    if (String(url).endsWith("/api/v1/auths/signin") && calls.length === 1) {
      return jsonResponse({ token: "admin-jwt" });
    }
    if (String(url).endsWith("/api/v1/auths/add")) {
      return jsonResponse(
        {
          detail:
            "Uh-oh! This email is already registered. Sign in with your existing account or choose another email to start anew."
        },
        400
      );
    }
    return jsonResponse(
      { token: "reviewer-jwt" },
      200,
      { "set-cookie": "token=reviewer-cookie; Path=/; HttpOnly" }
    );
  };
  const appContext = await startApp(
    {
      openWebuiEnabled: true,
      openWebuiUrl: "http://openwebui.test",
      openWebuiAdminEmail: "admin@mmrag.invalid",
      openWebuiAdminPassword: "admin-pass",
      openWebuiPasswordSecret: "test-secret"
    },
    { fetchImpl }
  );

  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const session = await assertRedeemOk(appContext.baseUrl, created.code);
    const response = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${session.token}` }
    });
    const data = await response.json();
    assert.equal(response.status, 200);
    assert.deepEqual(data, { ok: true, redirect: "/" });
    assert.equal(calls.length, 3);
    assert.equal(calls[0].headers["X-Demo-Email"], undefined);
    assert.equal(calls[0].headers["X-Demo-Name"], undefined);
    assert.equal(calls[2].headers["X-Demo-Email"], undefined);
    assert.equal(calls[2].headers["X-Demo-Name"], undefined);
    assert.equal(calls[1].body.password, calls[2].body.password);
    assert.match(calls[2].body.password, /^[A-Za-z0-9_-]{32}$/);
  } finally {
    await appContext.cleanup();
  }
});

test("OpenWebUI start fails with 503 when password secret is missing", async () => {
  let fetchCount = 0;
  const fetchImpl = async () => {
    fetchCount += 1;
    return jsonResponse({});
  };
  const appContext = await startApp(
    {
      openWebuiEnabled: true,
      openWebuiUrl: "http://openwebui.test/",
      openWebuiAdminEmail: "admin@mmrag.invalid",
      openWebuiAdminPassword: "admin-pass"
    },
    { fetchImpl }
  );

  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const session = await assertRedeemOk(appContext.baseUrl, created.code);
    const response = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${session.token}` }
    });
    const data = await response.json();
    assert.equal(response.status, 503);
    assert.equal(data.error, "openwebui_password_secret_missing");
    assert.equal(fetchCount, 0);
  } finally {
    await appContext.cleanup();
  }
});

test("hybrid proxy accepts mapped OpenWebUI token cookie without demo_session", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ data: [{ id: "gemma4:26b" }] }));
  });
  const appContext = await startApp(
    {
      openWebuiEnabled: true,
      openWebuiUrl: upstream.baseUrl,
      openWebuiPasswordSecret: "test-secret"
    },
    { fetchImpl: openWebuiSigninFetch("mapped-openwebui-cookie") }
  );

  try {
    const session = await createSession(appContext.baseUrl);
    const prefix = session.token.slice(0, 8);
    const start = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${session.token}` }
    });
    assert.equal(start.status, 200);

    const response = await fetch(`${appContext.baseUrl}/api/models`, {
      headers: {
        authorization: "Bearer stale-browser-token",
        cookie: "token=mapped-openwebui-cookie; demo_session=must-not-forward; theme=dark"
      }
    });
    const data = await response.json();

    assert.equal(response.status, 200);
    assert.deepEqual(data, { data: [{ id: "gemma4:26b" }] });
    assert.equal(upstream.calls.length, 1);
    assert.equal(upstream.calls[0].url, "/api/models");
    assert.equal(upstream.calls[0].headers["x-demo-email"], undefined);
    assert.equal(upstream.calls[0].headers.authorization, undefined);
    assert.equal(upstream.calls[0].headers.cookie, "token=mapped-openwebui-cookie; theme=dark");
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid proxy ignores stale OpenWebUI bearer when demo_session cookie is valid", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ data: [{ id: "gemma4:26b" }] }));
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const session = await createSession(appContext.baseUrl);
    const prefix = session.token.slice(0, 8);

    const response = await fetch(`${appContext.baseUrl}/api/models`, {
      headers: {
        authorization: "Bearer eyJhbGciOiJIUzI1NiJ9.openwebui-spa-localstorage.jwt",
        cookie: sessionCookie(session.token)
      }
    });
    const data = await response.json();

    assert.equal(response.status, 200);
    assert.deepEqual(data, { data: [{ id: "gemma4:26b" }] });
    assert.equal(upstream.calls.length, 1);
    assert.equal(upstream.calls[0].url, "/api/models");
    assert.equal(upstream.calls[0].headers["x-demo-email"], undefined);
    assert.equal(upstream.calls[0].headers.authorization, undefined);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid proxy ignores stale OpenWebUI bearer after the SPA rotates the token cookie", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ data: [{ id: "gemma4:26b" }] }));
  });
  const appContext = await startApp(
    {
      openWebuiEnabled: true,
      openWebuiUrl: upstream.baseUrl,
      openWebuiPasswordSecret: "test-secret"
    },
    { fetchImpl: openWebuiSigninFetch("first-openwebui-cookie") }
  );

  try {
    const session = await createSession(appContext.baseUrl);
    const prefix = session.token.slice(0, 8);
    const start = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${session.token}` }
    });
    assert.equal(start.status, 200);

    // Browser SPA rotated the OpenWebUI token via /auth re-signin; the cookie
    // value no longer matches the hash stored during /api/openwebui/start, and
    // the SPA also sends its new JWT as Authorization. The demo_session cookie
    // is still valid and must keep the proxy authenticated.
    const response = await fetch(`${appContext.baseUrl}/api/models`, {
      headers: {
        authorization: "Bearer eyJhbGciOiJIUzI1NiJ9.rotated-spa-jwt.sig",
        cookie: `${sessionCookie(session.token)}; token=rotated-openwebui-cookie`
      }
    });
    const data = await response.json();

    assert.equal(response.status, 200);
    assert.deepEqual(data, { data: [{ id: "gemma4:26b" }] });
    assert.equal(upstream.calls.length, 1);
    assert.equal(upstream.calls[0].headers["x-demo-email"], undefined);
    assert.equal(upstream.calls[0].headers.authorization, undefined);
    assert.equal(upstream.calls[0].headers.cookie, "token=rotated-openwebui-cookie");
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid proxy rejects unknown OpenWebUI token cookie with JSON 401", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end("unexpected proxy call");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const response = await fetch(`${appContext.baseUrl}/api/models`, {
      headers: { cookie: "token=unknown-openwebui-cookie" }
    });
    const data = await response.json();

    assert.equal(response.status, 401);
    assert.equal(data.error, "invalid_or_expired_session");
    assert.equal(upstream.calls.length, 0);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid proxy rejects expired and revoked mapped OpenWebUI sessions", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end("unexpected proxy call");
  });
  let openWebuiCookie = "expired-openwebui-cookie";
  const appContext = await startApp(
    {
      openWebuiEnabled: true,
      openWebuiUrl: upstream.baseUrl,
      openWebuiPasswordSecret: "test-secret"
    },
    { fetchImpl: async () => openWebuiSigninFetch(openWebuiCookie)() }
  );

  try {
    const expiredSession = await createSession(appContext.baseUrl);
    const expiredStart = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${expiredSession.token}` }
    });
    assert.equal(expiredStart.status, 200);
    const expiredRecord = appContext.app.authStore.data.sessions.find(
      (item) => item.token === expiredSession.token
    );
    expiredRecord.expires_at = new Date(Date.now() - 1000).toISOString();
    await appContext.app.authStore.persist();

    const expiredResponse = await fetch(`${appContext.baseUrl}/api/models`, {
      headers: { cookie: "token=expired-openwebui-cookie" }
    });
    assert.equal(expiredResponse.status, 401);

    openWebuiCookie = "revoked-openwebui-cookie";
    const revokedSession = await createSession(appContext.baseUrl);
    const revokedStart = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${revokedSession.token}` }
    });
    assert.equal(revokedStart.status, 200);
    const revokedRecord = appContext.app.authStore.data.sessions.find(
      (item) => item.token === revokedSession.token
    );
    revokedRecord.revoked_at = new Date().toISOString();
    await appContext.app.authStore.persist();

    const revokedResponse = await fetch(`${appContext.baseUrl}/api/models`, {
      headers: { cookie: "token=revoked-openwebui-cookie" }
    });
    assert.equal(revokedResponse.status, 401);
    assert.equal(upstream.calls.length, 0);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid disabled root serves demo-site UI without proxying", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end("unexpected proxy call");
  });
  const appContext = await startApp({
    openWebuiEnabled: false,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const response = await fetch(`${appContext.baseUrl}/`);
    const text = await response.text();
    assert.equal(response.status, 200);
    assert.match(text, /MMRAG Demo/);
    assert.equal(upstream.calls.length, 0);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid enabled root without a session serves demo-site UI without proxying", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end("unexpected proxy call");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const response = await fetch(`${appContext.baseUrl}/`);
    const text = await response.text();
    assert.equal(response.status, 200);
    assert.match(text, /MMRAG Demo/);
    assert.equal(upstream.calls.length, 0);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid stale OpenWebUI navigation without a session redirects to demo root", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end("unexpected proxy call");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const response = await fetch(`${appContext.baseUrl}/error`, { redirect: "manual" });
    assert.equal(response.status, 302);
    assert.equal(response.headers.get("location"), "/");
    assert.equal(upstream.calls.length, 0);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid stale OpenWebUI assets without a session do not serve demo HTML", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end("unexpected proxy call");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    for (const path of ["/manifest.json", "/loader.js", "/_app/immutable/nodes/51.test.js"]) {
      const response = await fetch(`${appContext.baseUrl}${path}`);
      const text = await response.text();
      assert.equal(response.status, 401);
      assert.match(response.headers.get("content-type") || "", /text\/plain/);
      assert.doesNotMatch(text, /<!doctype html>/i);
    }
    assert.equal(upstream.calls.length, 0);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid enabled root with a valid session proxies to OpenWebUI without trusted headers", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(201, {
      "content-type": "text/plain; charset=utf-8",
      "x-openwebui-stub": "root"
    });
    res.end("proxied root");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const session = await createSession(appContext.baseUrl);
    const prefix = session.token.slice(0, 8);
    const response = await fetch(`${appContext.baseUrl}/`, {
      headers: { cookie: sessionCookie(session.token) }
    });
    const text = await response.text();

    assert.equal(response.status, 201);
    assert.equal(response.headers.get("x-openwebui-stub"), "root");
    assert.equal(text, "proxied root");
    assert.equal(upstream.calls.length, 1);
    assert.equal(upstream.calls[0].method, "GET");
    assert.equal(upstream.calls[0].url, "/");
    assert.equal(upstream.calls[0].headers["x-demo-email"], undefined);
    assert.equal(upstream.calls[0].headers["x-demo-name"], undefined);
    assert.equal(upstream.calls[0].headers.cookie, undefined);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid proxy strips incoming X-Demo spoof headers and preserves request details", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(202, { "content-type": "text/plain; charset=utf-8" });
    res.end("accepted");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const session = await createSession(appContext.baseUrl);
    const prefix = session.token.slice(0, 8);
    const response = await fetch(`${appContext.baseUrl}/owui/api/test?x=1`, {
      method: "POST",
      headers: {
        cookie: `${sessionCookie(session.token)}; token=openwebui-cookie`,
        "content-type": "text/plain; charset=utf-8",
        "x-demo-email": "attacker@example.test",
        "x-demo-name": "Spoofed User",
        "x-demo-extra": "strip-me",
        "x-regular-header": "keep-me"
      },
      body: "request-body"
    });

    assert.equal(response.status, 202);
    assert.equal(await response.text(), "accepted");
    assert.equal(upstream.calls.length, 1);
    assert.equal(upstream.calls[0].method, "POST");
    assert.equal(upstream.calls[0].url, "/owui/api/test?x=1");
    assert.equal(upstream.calls[0].body, "request-body");
    assert.equal(upstream.calls[0].headers["x-demo-email"], undefined);
    assert.equal(upstream.calls[0].headers["x-demo-name"], undefined);
    assert.equal(upstream.calls[0].headers["x-demo-extra"], undefined);
    assert.equal(upstream.calls[0].headers["x-regular-header"], "keep-me");
    assert.equal(upstream.calls[0].headers.cookie, "token=openwebui-cookie");
    assert.equal(JSON.stringify(upstream.calls[0]).includes(session.token), false);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("reserved api chat path stays local in hybrid mode", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end("unexpected proxy call");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const session = await createSession(appContext.baseUrl);
    const response = await fetch(`${appContext.baseUrl}/api/chat`, {
      method: "POST",
      headers: {
        cookie: sessionCookie(session.token),
        "content-type": "application/json"
      },
      body: JSON.stringify({ message: "Was steht im Siemens-Bericht?" })
    });
    const data = await response.json();
    assert.equal(response.status, 200);
    assert.match(data.message.content, /Mock-Antwort/);
    assert.equal(upstream.calls.length, 0);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("expired and revoked hybrid sessions do not proxy", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    res.end("unexpected proxy call");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const expiredSession = await createSession(appContext.baseUrl);
    const expiredRecord = appContext.app.authStore.data.sessions.find(
      (item) => item.token === expiredSession.token
    );
    expiredRecord.expires_at = new Date(Date.now() - 1000).toISOString();
    await appContext.app.authStore.persist();

    const expiredResponse = await fetch(`${appContext.baseUrl}/`, {
      headers: { cookie: sessionCookie(expiredSession.token) }
    });
    assert.equal(expiredResponse.status, 200);
    assert.match(await expiredResponse.text(), /MMRAG Demo/);

    const revokedSession = await createSession(appContext.baseUrl);
    const revokedRecord = appContext.app.authStore.data.sessions.find(
      (item) => item.token === revokedSession.token
    );
    revokedRecord.revoked_at = new Date().toISOString();
    await appContext.app.authStore.persist();

    const revokedResponse = await fetch(`${appContext.baseUrl}/`, {
      headers: { cookie: sessionCookie(revokedSession.token) }
    });
    assert.equal(revokedResponse.status, 200);
    assert.match(await revokedResponse.text(), /MMRAG Demo/);
    assert.equal(upstream.calls.length, 0);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid proxy relays OpenWebUI Set-Cookie headers", async () => {
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(200, {
      "content-type": "text/plain; charset=utf-8",
      "set-cookie": [
        "token=openwebui-cookie; Path=/; HttpOnly; SameSite=Lax",
        "theme=dark; Path=/; SameSite=Lax"
      ]
    });
    res.end("cookie response");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const session = await createSession(appContext.baseUrl);
    const response = await fetch(`${appContext.baseUrl}/cookie-check`, {
      headers: { cookie: sessionCookie(session.token) }
    });
    const setCookie = response.headers.get("set-cookie") || "";
    assert.equal(response.status, 200);
    assert.match(setCookie, /token=openwebui-cookie/);
    assert.match(setCookie, /theme=dark/);
    assert.equal(await response.text(), "cookie response");
    assert.equal(upstream.calls.length, 1);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid proxy streams SSE chunks without buffering the upstream response", async () => {
  let secondChunkSent = false;
  const upstream = await startOpenWebuiStub((_req, res) => {
    res.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-cache"
    });
    res.write("data: first\n\n");
    setTimeout(() => {
      secondChunkSent = true;
      res.write("data: second\n\n");
      res.end();
    }, 300);
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const session = await createSession(appContext.baseUrl);
    const response = await fetch(`${appContext.baseUrl}/api/sse-stream`, {
      headers: {
        accept: "text/event-stream",
        cookie: sessionCookie(session.token)
      }
    });
    assert.equal(response.status, 200);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const first = await reader.read();
    assert.equal(first.done, false);
    const firstText = decoder.decode(first.value);
    assert.match(firstText, /data: first/);
    assert.equal(firstText.includes("data: second"), false);
    assert.equal(secondChunkSent, false);

    let rest = "";
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) {
        break;
      }
      rest += decoder.decode(chunk.value, { stream: true });
    }
    rest += decoder.decode();
    assert.match(rest, /data: second/);
    assert.equal(secondChunkSent, true);
    assert.equal(upstream.calls.length, 1);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid upgrade with a valid session proxies to OpenWebUI", async () => {
  const upstream = await startOpenWebuiUpgradeStub((_req, socket) => {
    socket.end(
      [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        "X-Upstream-Upgrade: ok",
        "",
        ""
      ].join("\r\n")
    );
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const session = await createSession(appContext.baseUrl);
    const response = await websocketUpgrade(appContext.baseUrl, "/ws/socket.io/?EIO=4&transport=websocket", {
      cookie: sessionCookie(session.token)
    });

    assert.equal(response.statusCode, 101);
    assert.equal(response.headers["x-upstream-upgrade"], "ok");
    assert.equal(upstream.calls.length, 1);
    assert.equal(upstream.calls[0].method, "GET");
    assert.equal(upstream.calls[0].url, "/ws/socket.io/?EIO=4&transport=websocket");
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid upgrade without a valid session returns 401 without upstream call", async () => {
  const upstream = await startOpenWebuiUpgradeStub((_req, socket) => {
    socket.end("HTTP/1.1 101 Switching Protocols\r\n\r\n");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const response = await websocketUpgrade(appContext.baseUrl);

    assert.equal(response.statusCode, 401);
    assert.equal(upstream.calls.length, 0);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid upgrade strips spoofed X-Demo headers without injecting trusted headers", async () => {
  const upstream = await startOpenWebuiUpgradeStub((_req, socket) => {
    socket.end("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const session = await createSession(appContext.baseUrl);
    const prefix = session.token.slice(0, 8);
    const response = await websocketUpgrade(appContext.baseUrl, "/ws/socket.io/?EIO=4&transport=websocket", {
      cookie: sessionCookie(session.token),
      "X-Demo-Email": "attacker@example.test",
      "X-Demo-Name": "Spoofed User",
      "X-Demo-Extra": "strip-me",
      "X-Regular-Header": "keep-me"
    });

    assert.equal(response.statusCode, 101);
    assert.equal(upstream.calls.length, 1);
    assert.equal(upstream.calls[0].headers["x-demo-email"], undefined);
    assert.equal(upstream.calls[0].headers["x-demo-name"], undefined);
    assert.equal(upstream.calls[0].headers["x-demo-extra"], undefined);
    assert.equal(upstream.calls[0].headers["x-regular-header"], "keep-me");
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid upgrade preserves OpenWebUI cookies and strips demo session", async () => {
  const upstream = await startOpenWebuiUpgradeStub((_req, socket) => {
    socket.end("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n");
  });
  const appContext = await startApp({
    openWebuiEnabled: true,
    openWebuiUrl: upstream.baseUrl
  });

  try {
    const session = await createSession(appContext.baseUrl);
    const response = await websocketUpgrade(appContext.baseUrl, "/ws/socket.io/?EIO=4&transport=websocket", {
      cookie: `${sessionCookie(session.token)}; token=openwebui-cookie; theme=dark`
    });

    assert.equal(response.statusCode, 101);
    assert.equal(upstream.calls.length, 1);
    assert.equal(upstream.calls[0].headers.cookie, "token=openwebui-cookie; theme=dark");
    assert.equal(JSON.stringify(upstream.calls[0]).includes(session.token), false);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("hybrid upgrade accepts mapped OpenWebUI token cookie", async () => {
  const upstream = await startOpenWebuiUpgradeStub((_req, socket) => {
    socket.end(
      [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        "X-Upstream-Upgrade: mapped",
        "",
        ""
      ].join("\r\n")
    );
  });
  const appContext = await startApp(
    {
      openWebuiEnabled: true,
      openWebuiUrl: upstream.baseUrl,
      openWebuiPasswordSecret: "test-secret"
    },
    { fetchImpl: openWebuiSigninFetch("mapped-upgrade-cookie") }
  );

  try {
    const session = await createSession(appContext.baseUrl);
    const start = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${session.token}` }
    });
    assert.equal(start.status, 200);

    const response = await websocketUpgrade(appContext.baseUrl, "/ws/socket.io/?EIO=4&transport=websocket", {
      authorization: "Bearer stale-browser-token",
      cookie: "token=mapped-upgrade-cookie"
    });

    assert.equal(response.statusCode, 101);
    assert.equal(response.headers["x-upstream-upgrade"], "mapped");
    assert.equal(upstream.calls.length, 1);
    assert.equal(upstream.calls[0].headers.authorization, undefined);
  } finally {
    await appContext.cleanup();
    await upstream.cleanup();
  }
});

test("classic chat does not accept mapped OpenWebUI token cookie", async () => {
  const appContext = await startApp(
    { openWebuiEnabled: true, openWebuiPasswordSecret: "test-secret" },
    { fetchImpl: openWebuiSigninFetch("chat-openwebui-cookie") }
  );

  try {
    const session = await createSession(appContext.baseUrl);
    const start = await fetch(`${appContext.baseUrl}/api/openwebui/start`, {
      method: "POST",
      headers: { authorization: `Bearer ${session.token}` }
    });
    assert.equal(start.status, 200);

    const response = await fetch(`${appContext.baseUrl}/api/chat`, {
      method: "POST",
      headers: {
        cookie: "token=chat-openwebui-cookie",
        "content-type": "application/json"
      },
      body: JSON.stringify({ message: "Hallo" })
    });
    const data = await response.json();

    assert.equal(response.status, 401);
    assert.equal(data.error, "invalid_or_expired_session");
  } finally {
    await appContext.cleanup();
  }
});

test("chat with a valid session returns an assistant message with sources", async () => {
  const appContext = await startApp();
  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const session = await assertRedeemOk(appContext.baseUrl, created.code);
    const response = await fetch(`${appContext.baseUrl}/api/chat`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${session.token}`
      },
      body: JSON.stringify({ message: "Was steht im Siemens-Bericht?" })
    });
    const data = await response.json();
    assert.equal(response.status, 200);
    assert.match(data.message.content, /Mock-Antwort/);
    assert.equal(data.sources.length, 2);
  } finally {
    await appContext.cleanup();
  }
});

test("the 11th request is rejected before proxying", async () => {
  let gatewayCalls = 0;
  const fetchImpl = async () => {
    gatewayCalls += 1;
    return new Response(
      JSON.stringify({
        model: "test-model",
        choices: [
          {
            message: {
              role: "assistant",
              content: "Antwort\n\nQuellen:\n- [Quelle](https://example.test)"
            }
          }
        ]
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    );
  };

  const appContext = await startApp(
    {
      mockGateway: false,
      ragGatewayUrl: "http://127.0.0.1:9",
      maxQueriesPerHour: 10
    },
    { fetchImpl }
  );

  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const session = await assertRedeemOk(appContext.baseUrl, created.code);
    let lastStatus = 0;
    for (let i = 0; i < 11; i += 1) {
      const response = await fetch(`${appContext.baseUrl}/api/chat`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${session.token}`
        },
        body: JSON.stringify({ message: `Ping ${i}` })
      });
      lastStatus = response.status;
    }
    assert.equal(lastStatus, 429);
    assert.equal(gatewayCalls, 10);
  } finally {
    await appContext.cleanup();
  }
});

test("expired sessions return 401", async () => {
  const appContext = await startApp({ sessionTtlHours: 0.01 });
  try {
    const created = await adminCreateCode(appContext.baseUrl);
    const session = await assertRedeemOk(appContext.baseUrl, created.code);
    const record = appContext.app.authStore.data.sessions.find((item) => item.token === session.token);
    record.expires_at = new Date(Date.now() - 1000).toISOString();
    await appContext.app.authStore.persist();

    const response = await fetch(`${appContext.baseUrl}/api/chat`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${session.token}`
      },
      body: JSON.stringify({ message: "Noch da?" })
    });
    assert.equal(response.status, 401);
  } finally {
    await appContext.cleanup();
  }
});

test("sessions persist across process restart with the same auth store", async () => {
  const temp = await tempStorePath();
  const app1 = createApp({
    config: {
      mockGateway: true,
      adminToken: ADMIN_TOKEN,
      authStorePath: temp.authStorePath
    }
  });
  const baseUrl1 = await listen(app1.server);
  let token;

  try {
    const created = await adminCreateCode(baseUrl1);
    const session = await assertRedeemOk(baseUrl1, created.code);
    token = session.token;
  } finally {
    await close(app1.server);
    await app1.authStore.ready.catch(() => {});
    await app1.authStore.writeQueue.catch(() => {});
  }

  const app2 = createApp({
    config: {
      mockGateway: true,
      adminToken: ADMIN_TOKEN,
      authStorePath: temp.authStorePath
    }
  });
  const baseUrl2 = await listen(app2.server);

  try {
    const response = await fetch(`${baseUrl2}/api/chat`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${token}`
      },
      body: JSON.stringify({ message: "Persistiert?" })
    });
    assert.equal(response.status, 200);
    const stored = JSON.parse(await fs.readFile(temp.authStorePath, "utf8"));
    assert.equal(stored.sessions.length, 1);
  } finally {
    await close(app2.server);
    await app2.authStore.ready.catch(() => {});
    await app2.authStore.writeQueue.catch(() => {});
    await temp.cleanup();
  }
});
