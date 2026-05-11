"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const test = require("node:test");
const { createApp, parseAssistantContent } = require("../server/index.js");

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
