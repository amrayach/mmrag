"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { createApp, parseAssistantContent } = require("../server/index.js");

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

async function redeem(baseUrl, code = "demo") {
  const response = await fetch(`${baseUrl}/api/auth/redeem`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code })
  });
  assert.equal(response.status, 200);
  return response.json();
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

test("auth redeem accepts non-empty codes and sets a cookie", async () => {
  const app = createApp({ config: { mockGateway: true } });
  const baseUrl = await listen(app.server);
  try {
    const response = await fetch(`${baseUrl}/api/auth/redeem`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code: "abc" })
    });
    const data = await response.json();
    assert.equal(response.status, 200);
    assert.match(data.token, /^[A-Za-z0-9_-]+$/);
    assert.ok(Date.parse(data.expires_at) > Date.now());
    assert.match(response.headers.get("set-cookie"), /demo_session=/);
  } finally {
    await close(app.server);
  }
});

test("chat without a token returns 401", async () => {
  const app = createApp({ config: { mockGateway: true } });
  const baseUrl = await listen(app.server);
  try {
    const response = await fetch(`${baseUrl}/api/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: "Hallo" })
    });
    assert.equal(response.status, 401);
  } finally {
    await close(app.server);
  }
});

test("mock chat returns an assistant message with sources", async () => {
  const app = createApp({ config: { mockGateway: true } });
  const baseUrl = await listen(app.server);
  try {
    const session = await redeem(baseUrl);
    const response = await fetch(`${baseUrl}/api/chat`, {
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
    await close(app.server);
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

  const app = createApp({
    fetchImpl,
    config: {
      mockGateway: false,
      ragGatewayUrl: "http://127.0.0.1:9",
      maxQueriesPerHour: 10
    }
  });
  const baseUrl = await listen(app.server);

  try {
    const session = await redeem(baseUrl);
    let lastStatus = 0;
    for (let i = 0; i < 11; i += 1) {
      const response = await fetch(`${baseUrl}/api/chat`, {
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
    await close(app.server);
  }
});

test("expired tokens return 401", async () => {
  const app = createApp({ config: { mockGateway: true, tokenTtlMs: 20 } });
  const baseUrl = await listen(app.server);
  try {
    const session = await redeem(baseUrl);
    await new Promise((resolve) => setTimeout(resolve, 40));
    const response = await fetch(`${baseUrl}/api/chat`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${session.token}`
      },
      body: JSON.stringify({ message: "Noch da?" })
    });
    assert.equal(response.status, 401);
  } finally {
    await close(app.server);
  }
});
