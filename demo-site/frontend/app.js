"use strict";

const state = {
  token: localStorage.getItem("demoToken") || "",
  expiresAt: localStorage.getItem("demoTokenExpiresAt") || "",
  messages: [],
  pending: false
};

const views = {
  landing: document.getElementById("landingView"),
  login: document.getElementById("loginView"),
  chat: document.getElementById("chatView")
};

const loginForm = document.getElementById("loginForm");
const codeInput = document.getElementById("codeInput");
const loginStatus = document.getElementById("loginStatus");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const messageList = document.getElementById("messageList");
const sendButton = document.getElementById("sendButton");

function hasValidLocalToken() {
  return Boolean(state.token && state.expiresAt && Date.parse(state.expiresAt) > Date.now());
}

function setRoute(route) {
  const nextRoute = route === "chat" && !hasValidLocalToken() ? "login" : route;
  for (const [name, element] of Object.entries(views)) {
    element.hidden = name !== nextRoute;
  }
  history.replaceState(null, "", nextRoute === "landing" ? "/" : `/${nextRoute}`);
  if (nextRoute === "login") {
    codeInput.focus();
  }
  if (nextRoute === "chat") {
    messageInput.focus();
    renderMessages();
  }
}

function saveToken(token, expiresAt) {
  state.token = token;
  state.expiresAt = expiresAt;
  localStorage.setItem("demoToken", token);
  localStorage.setItem("demoTokenExpiresAt", expiresAt);
}

function clearToken() {
  state.token = "";
  state.expiresAt = "";
  localStorage.removeItem("demoToken");
  localStorage.removeItem("demoTokenExpiresAt");
}

function messageLabel(role) {
  if (role === "user") {
    return "Du";
  }
  if (role === "error") {
    return "Hinweis";
  }
  return "Antwort";
}

function createTypingIndicator() {
  const wrapper = document.createElement("span");
  wrapper.className = "typing";
  wrapper.setAttribute("aria-label", "Antwort wird erzeugt");
  for (let i = 0; i < 3; i += 1) {
    wrapper.appendChild(document.createElement("span"));
  }
  return wrapper;
}

function appendSources(container, sources) {
  if (!Array.isArray(sources) || sources.length === 0) {
    return;
  }
  const sourceList = document.createElement("div");
  sourceList.className = "sources";

  for (const source of sources) {
    if (source.url) {
      const link = document.createElement("a");
      link.className = "source-link";
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = source.label || source.url;
      sourceList.appendChild(link);
    } else {
      const label = document.createElement("span");
      label.className = "source-label";
      label.textContent = source.label;
      sourceList.appendChild(label);
    }
  }

  container.appendChild(sourceList);
}

function renderMessages() {
  messageList.replaceChildren();

  if (state.messages.length === 0) {
    const empty = document.createElement("article");
    empty.className = "message assistant";
    empty.innerHTML =
      '<span class="message-role">Antwort</span><div class="message-content">Wähle ein Beispiel oder stelle eine eigene Frage.</div>';
    messageList.appendChild(empty);
    return;
  }

  for (const message of state.messages) {
    const item = document.createElement("article");
    item.className = `message ${message.role === "user" ? "user" : message.role === "error" ? "error" : "assistant"}`;

    const role = document.createElement("span");
    role.className = "message-role";
    role.textContent = messageLabel(message.role);
    item.appendChild(role);

    const content = document.createElement("div");
    content.className = "message-content";
    if (message.pending) {
      content.appendChild(createTypingIndicator());
    } else {
      content.textContent = message.content;
    }
    item.appendChild(content);
    appendSources(item, message.sources);
    messageList.appendChild(item);
  }

  messageList.scrollTop = messageList.scrollHeight;
}

async function redeemCode(code) {
  const response = await fetch("/api/auth/redeem", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code })
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Code konnte nicht eingeloest werden.");
  }
  saveToken(data.token, data.expires_at);
}

async function sendChatMessage(text) {
  state.messages.push({ role: "user", content: text });
  const pendingMessage = { role: "assistant", content: "", pending: true, sources: [] };
  state.messages.push(pendingMessage);
  state.pending = true;
  sendButton.disabled = true;
  renderMessages();

  const conversation = state.messages
    .filter((message) => !message.pending && message.role !== "error")
    .map((message) => ({
      role: message.role === "assistant" ? "assistant" : "user",
      content: message.content
    }));

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${state.token}`
      },
      body: JSON.stringify({ messages: conversation, max_tokens: 800 })
    });
    const data = await response.json().catch(() => ({}));

    if (response.status === 401) {
      clearToken();
      throw new Error("Die Demo-Sitzung ist abgelaufen. Bitte erneut anmelden.");
    }
    if (response.status === 429) {
      throw new Error("Das Stundenlimit für diese Demo-Sitzung ist erreicht.");
    }
    if (!response.ok) {
      throw new Error(data.error || "Die Antwort konnte nicht erzeugt werden.");
    }

    pendingMessage.pending = false;
    pendingMessage.content = data.message?.content || "";
    pendingMessage.sources = data.sources || [];
  } catch (error) {
    pendingMessage.role = "error";
    pendingMessage.pending = false;
    pendingMessage.content = error.message;
    pendingMessage.sources = [];
    if (!hasValidLocalToken()) {
      setRoute("login");
    }
  } finally {
    state.pending = false;
    sendButton.disabled = false;
    renderMessages();
  }
}

document.addEventListener("click", (event) => {
  const routeTarget = event.target.closest("[data-route]");
  if (routeTarget) {
    event.preventDefault();
    setRoute(routeTarget.dataset.route);
    return;
  }

  const example = event.target.closest(".example-button");
  if (example) {
    messageInput.value = example.textContent.trim();
    messageInput.focus();
  }
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginStatus.textContent = "";
  const submitButton = loginForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  try {
    await redeemCode(codeInput.value);
    codeInput.value = "";
    setRoute("chat");
  } catch (error) {
    loginStatus.textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text || state.pending) {
    return;
  }
  messageInput.value = "";
  await sendChatMessage(text);
});

const initialPath = window.location.pathname.replace(/^\/+/, "") || "landing";
setRoute(["landing", "login", "chat"].includes(initialPath) ? initialPath : "landing");
