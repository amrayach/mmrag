/* ---------------------------------------------------------------------------
   api.js — Fetch wrapper + SSE helpers with auto-reconnect + buffer parser
   --------------------------------------------------------------------------- */

const API = {
  /**
   * Fetch JSON from an API endpoint.
   */
  async get(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`GET ${url} failed: ${resp.status}`);
    return resp.json();
  },

  async post(url, body = null) {
    const opts = { method: 'POST' };
    if (body !== null) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(url, opts);
    if (!resp.ok) throw new Error(`POST ${url} failed: ${resp.status}`);
    return resp.json();
  },

  async postMultipart(url, formData) {
    const resp = await fetch(url, { method: 'POST', body: formData });
    if (!resp.ok) throw new Error(`POST ${url} failed: ${resp.status}`);
    return resp.json();
  },

  /**
   * POST with streaming SSE response via fetch + ReadableStream.
   * Handles the case where EventSource only supports GET.
   *
   * @param {string} url
   * @param {object} body - JSON body
   * @param {object} handlers - { onEvent(eventType, data), onError(err), onDone() }
   * @param {AbortController} [controller] - optional abort controller
   * @returns {AbortController}
   */
  streamPost(url, body, handlers, controller = null) {
    controller = controller || new AbortController();

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
      .then(resp => {
        if (!resp.ok) throw new Error(`POST ${url} failed: ${resp.status}`);
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        function pump() {
          return reader.read().then(({ done, value }) => {
            if (done) {
              // Process any remaining buffer
              if (buffer.trim()) _parseSSEBuffer(buffer, handlers);
              if (handlers.onDone) handlers.onDone();
              return;
            }
            buffer += decoder.decode(value, { stream: true });
            // Split on double newline — never assume one chunk = one SSE message
            const parts = buffer.split('\n\n');
            buffer = parts.pop(); // keep incomplete part
            for (const part of parts) {
              if (part.trim()) _parseSingleSSE(part, handlers);
            }
            return pump();
          });
        }

        return pump();
      })
      .catch(err => {
        if (err.name === 'AbortError') return;
        if (handlers.onError) handlers.onError(err);
      });

    return controller;
  },
};

/**
 * Parse a single SSE message block (lines between \n\n delimiters).
 */
function _parseSingleSSE(block, handlers) {
  let eventType = 'message';
  let dataLines = [];

  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      dataLines.push(line.slice(6));
    } else if (line.startsWith('id: ')) {
      // ignored for now
    }
  }

  if (dataLines.length > 0) {
    const raw = dataLines.join('\n');
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      data = raw;
    }
    if (handlers.onEvent) handlers.onEvent(eventType, data);
  }
}

function _parseSSEBuffer(buffer, handlers) {
  const blocks = buffer.split('\n\n');
  for (const block of blocks) {
    if (block.trim()) _parseSingleSSE(block, handlers);
  }
}

/* ---------------------------------------------------------------------------
   SSE auto-reconnect helper (GET-based EventSource)
   --------------------------------------------------------------------------- */

class JsonSSE {
  constructor(url, { onEvent, onError, onConnect, onDisconnect, reconnectMs = 3000 } = {}) {
    this.url = url;
    this.onEvent = onEvent;
    this.onError = onError;
    this.onConnect = onConnect;
    this.onDisconnect = onDisconnect;
    this.reconnectMs = reconnectMs;
    this._es = null;
    this._closed = false;
    this._reconnectTimer = null;
    this.connect();
  }

  connect() {
    if (this._closed) return;
    this._es = new EventSource(this.url);

    this._es.onopen = () => {
      if (this.onConnect) this.onConnect();
    };

    this._es.addEventListener('event', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (this.onEvent) this.onEvent(data);
      } catch (err) {
        if (this.onError) this.onError(err);
      }
    });

    this._es.onerror = () => {
      this._es.close();
      if (this.onDisconnect) this.onDisconnect();
      if (!this._closed) {
        this._reconnectTimer = setTimeout(() => this.connect(), this.reconnectMs);
      }
    };
  }

  close() {
    this._closed = true;
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer);
    if (this._es) this._es.close();
  }
}
