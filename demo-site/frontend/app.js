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
  launch: document.getElementById("launchView"),
  classic: document.getElementById("chatView")
};

const loginForm = document.getElementById("loginForm");
const codeInput = document.getElementById("codeInput");
const loginStatus = document.getElementById("loginStatus");
const openWebuiButton = document.getElementById("openWebuiButton");
const launchStatus = document.getElementById("launchStatus");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const messageList = document.getElementById("messageList");
const sendButton = document.getElementById("sendButton");

function hasValidLocalToken() {
  return Boolean(state.token && state.expiresAt && Date.parse(state.expiresAt) > Date.now());
}

function normalizeRoute(route) {
  return route === "chat" ? "classic" : route;
}

function routePath(route) {
  if (route === "login") {
    return "/login";
  }
  if (route === "classic") {
    return "/classic";
  }
  return "/";
}

function setRoute(route) {
  const requestedRoute = normalizeRoute(route);
  const requiresToken = requestedRoute === "launch" || requestedRoute === "classic";
  const nextRoute = requiresToken && !hasValidLocalToken() ? "login" : requestedRoute;
  for (const [name, element] of Object.entries(views)) {
    element.hidden = name !== nextRoute;
  }
  history.replaceState(null, "", routePath(nextRoute));
  if (nextRoute === "login") {
    codeInput.focus();
  }
  if (nextRoute === "launch") {
    launchStatus.textContent = "";
    openWebuiButton.focus();
  }
  if (nextRoute === "classic") {
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

function clearSessionState() {
  clearToken();
  state.messages = [];
  state.pending = false;
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
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code })
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.message || data.error || "Code konnte nicht eingeloest werden.");
  }
  saveToken(data.token, data.expires_at);
}

function openWebuiErrorMessage(response, data) {
  if (response.status === 503 && data.error === "openwebui_disabled") {
    return "OpenWebUI ist fuer diese Demo derzeit nicht aktiviert. Der klassische Chat bleibt verfuegbar.";
  }
  if (response.status === 502 && data.error === "openwebui_bootstrap_failed") {
    return "OpenWebUI konnte nicht gestartet werden. Der klassische Chat bleibt verfuegbar.";
  }
  return data.message || data.error || "OpenWebUI konnte nicht gestartet werden. Der klassische Chat bleibt verfuegbar.";
}

async function startOpenWebui() {
  if (!hasValidLocalToken()) {
    clearSessionState();
    loginStatus.textContent = "Die Demo-Sitzung ist abgelaufen. Bitte erneut anmelden.";
    setRoute("login");
    return;
  }

  launchStatus.textContent = "";
  openWebuiButton.disabled = true;

  try {
    const response = await fetch("/api/openwebui/start", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Authorization: `Bearer ${state.token}`
      }
    });
    const data = await response.json().catch(() => ({}));

    if (response.status === 401) {
      clearSessionState();
      loginStatus.textContent = "Die Demo-Sitzung ist abgelaufen. Bitte erneut anmelden.";
      openWebuiButton.disabled = false;
      setRoute("login");
      return;
    }
    if (!response.ok) {
      throw new Error(openWebuiErrorMessage(response, data));
    }

    const redirect = typeof data.redirect === "string" && data.redirect ? data.redirect : "/";
    if (typeof data.openwebui_token === "string" && data.openwebui_token) {
      try {
        localStorage.setItem("token", data.openwebui_token);
      } catch (_err) {
        // localStorage unavailable (private mode etc.) — cookie auth still works for proxied requests.
      }
    }
    window.location.assign(redirect);
  } catch (error) {
    launchStatus.textContent = error.message;
    openWebuiButton.disabled = false;
  }
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
    setRoute("launch");
  } catch (error) {
    loginStatus.textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
});

openWebuiButton.addEventListener("click", startOpenWebui);

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text || state.pending) {
    return;
  }
  messageInput.value = "";
  await sendChatMessage(text);
});

const initialPath = window.location.pathname.replace(/^\/+/, "");
const initialRoute = {
  "": hasValidLocalToken() ? "launch" : "landing",
  landing: "landing",
  login: "login",
  chat: "classic",
  classic: "classic"
}[initialPath] || "landing";
setRoute(initialRoute);
