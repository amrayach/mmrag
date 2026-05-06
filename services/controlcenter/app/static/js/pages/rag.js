/* ---------------------------------------------------------------------------
   rag.js — RAG Playground: chat + streaming response + debug tabs
   --------------------------------------------------------------------------- */

Pages.rag = function(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>RAG Playground</h2>
      <p class="subtitle">Query the knowledge base with streaming responses</p>
    </div>

    <div class="rag-layout">
      <!-- Chat Panel -->
      <div class="card rag-chat-panel">
        <div class="card-header">
          <span class="card-title">Chat</span>
          <div style="display:flex;gap:0.4rem;align-items:center">
            <button class="btn btn-sm" id="rag-clear" title="New conversation">New Chat</button>
            <button class="btn btn-sm" id="rag-history-btn" title="Query history">History</button>
          </div>
        </div>

        <div class="rag-messages" id="rag-messages"></div>

        <div class="rag-input-row">
          <div class="rag-settings-row" style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.4rem;font-size:0.78rem">
            <label style="color:var(--text-secondary)">Model:</label>
            <select id="rag-model" style="flex:1;max-width:250px;font-size:0.78rem;background:var(--bg-tertiary);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;padding:0.2rem 0.4rem"></select>
          </div>
          <textarea id="rag-input" class="rag-textarea" placeholder="Ask a question about the documents..." rows="2"></textarea>
          <div style="display:flex;gap:0.4rem">
            <button class="btn btn-accent" id="rag-send">Send</button>
            <button class="btn btn-danger btn-sm" id="rag-cancel" style="display:none">Stop</button>
          </div>
        </div>
      </div>

      <!-- Debug Panel -->
      <div class="card rag-debug-panel">
        <div class="card-header">
          <span class="card-title">Debug</span>
          <button class="btn btn-sm" id="rag-curl-btn" title="Copy as cURL" style="display:none">{ } cURL</button>
        </div>
        ${Components.tabs([
          {id: 'context', label: 'Context'},
          {id: 'chunks', label: 'Chunks'},
          {id: 'images', label: 'Images'},
          {id: 'sources', label: 'Sources'},
        ], 'context')}
        <div class="tab-content active" id="tab-context">
          <pre class="rag-debug-pre" id="rag-ctx-pre"><code>No query yet</code></pre>
        </div>
        <div class="tab-content" id="tab-chunks">
          <div id="rag-chunks-list" style="font-size:0.82rem;color:var(--text-secondary)">No chunks yet</div>
        </div>
        <div class="tab-content" id="tab-images">
          <div id="rag-images-list" style="font-size:0.82rem;color:var(--text-secondary)">No images yet</div>
        </div>
        <div class="tab-content" id="tab-sources">
          <div id="rag-sources-list" style="font-size:0.82rem;color:var(--text-secondary)">No sources yet</div>
        </div>
      </div>
    </div>

    <!-- History Modal -->
    <div class="modal-overlay" id="rag-history-modal">
      <div class="modal" style="max-width:550px">
        <h3>Query History</h3>
        <div id="rag-history-list" style="max-height:400px;overflow-y:auto;margin-bottom:1rem"></div>
        <div class="modal-actions">
          <button class="btn btn-sm btn-danger" id="rag-history-clear">Clear All</button>
          <button class="btn" id="rag-history-close">Close</button>
        </div>
      </div>
    </div>
  `;

  // --- State ---
  let controller = null;
  let lastQuery = null;
  let lastContext = null;
  let messages = [];  // Multi-turn conversation (session-scoped)
  let selectedModel = null;

  // --- Model selector ---
  async function loadModels() {
    const select = document.getElementById('rag-model');
    try {
      const data = await API.get('/api/rag/models');
      const models = data.data || data.models || [];
      const defaultModel = data.default_model || 'gemma4:26b';
      select.innerHTML = models.map(m => {
        const name = m.id || m.name || m;
        const isDefault = name === defaultModel || name.includes(defaultModel);
        return `<option value="${name}"${isDefault ? ' selected' : ''}>${name}</option>`;
      }).join('');
      selectedModel = select.value;
    } catch {
      const fallback = 'gemma4:26b';
      select.innerHTML = `<option value="${fallback}">${fallback}</option>`;
      selectedModel = fallback;
      Components.toast('Could not load models — using default', 'warning');
    }
    select.addEventListener('change', () => { selectedModel = select.value; });
  }
  loadModels();

  // --- Tab switching ---
  container.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      container.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      container.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    });
  });

  // --- Send query ---
  const input = document.getElementById('rag-input');
  const sendBtn = document.getElementById('rag-send');
  const cancelBtn = document.getElementById('rag-cancel');
  const messagesEl = document.getElementById('rag-messages');

  function sendQuery() {
    const text = input.value.trim();
    if (!text || controller) return;

    // Multi-turn: add user message to conversation
    messages.push({role: 'user', content: text});
    const recentMessages = messages.slice(-6); // Last 3 turns
    lastQuery = {messages: recentMessages, model: selectedModel};
    input.value = '';
    input.style.height = 'auto';

    // Add user message
    _addMessage('user', text);

    // Add assistant placeholder
    const assistantEl = _addMessage('assistant', '');
    const contentEl = assistantEl.querySelector('.rag-msg-content');
    contentEl.innerHTML = '<span class="rag-typing">Thinking...</span>';

    // Show cancel, hide send
    sendBtn.style.display = 'none';
    cancelBtn.style.display = '';

    // Reset debug
    document.getElementById('rag-ctx-pre').querySelector('code').textContent = 'Loading context...';
    document.getElementById('rag-chunks-list').textContent = 'Loading...';
    document.getElementById('rag-images-list').textContent = 'Loading...';
    document.getElementById('rag-sources-list').textContent = 'Loading...';

    let tokens = '';
    let queryFailed = false;
    let t0 = performance.now();

    controller = API.streamPost('/api/rag/query', lastQuery, {
      onEvent(eventType, data) {
        if (eventType === 'context') {
          lastContext = data;
          _renderContextDebug(data);
          document.getElementById('rag-curl-btn').style.display = '';
        } else if (eventType === 'images') {
          _renderImagesDebug(data);
        } else if (eventType === 'sources') {
          _renderSourcesDebug(data);
        } else if (eventType === 'token') {
          if (contentEl.querySelector('.rag-typing')) contentEl.innerHTML = '';
          tokens += data.content;
          contentEl.textContent = tokens;
        } else if (eventType === 'error') {
          queryFailed = true;
          contentEl.innerHTML += `<span style="color:var(--error);display:block;margin-top:0.5rem">${_ragEsc(data.message || 'Unknown error')}</span>`;
        } else if (eventType === 'done') {
          const elapsed = data.elapsed_ms || Math.round(performance.now() - t0);
          const statsEl = assistantEl.querySelector('.rag-msg-stats');
          if (statsEl) statsEl.textContent = `${data.total_tokens || 0} tokens | ${(elapsed / 1000).toFixed(1)}s`;
          // Only commit assistant response on success
          if (!queryFailed && tokens) {
            messages.push({role: 'assistant', content: tokens});
          } else if (queryFailed) {
            messages.pop(); // Remove the failed user message
          }
          _saveHistory(text, tokens, elapsed);
        }
      },
      onError(err) {
        queryFailed = true;
        contentEl.innerHTML = `<span style="color:var(--error)">${_ragEsc(err.message)}</span>`;
        messages.pop(); // Remove failed user message
      },
      onDone() {
        controller = null;
        sendBtn.style.display = '';
        cancelBtn.style.display = 'none';
      },
    });
  }

  sendBtn.addEventListener('click', sendQuery);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendQuery(); }
  });

  // Auto-resize textarea
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });

  // --- Cancel ---
  cancelBtn.addEventListener('click', () => {
    if (controller) { controller.abort(); controller = null; }
    sendBtn.style.display = '';
    cancelBtn.style.display = 'none';
  });

  // --- New Chat ---
  document.getElementById('rag-clear').addEventListener('click', () => {
    messagesEl.innerHTML = '';
    messages = [];
    lastContext = null;
    document.getElementById('rag-ctx-pre').querySelector('code').textContent = 'No query yet';
    document.getElementById('rag-chunks-list').textContent = 'No chunks yet';
    document.getElementById('rag-images-list').textContent = 'No images yet';
    document.getElementById('rag-sources-list').textContent = 'No sources yet';
    document.getElementById('rag-curl-btn').style.display = 'none';
  });

  // --- Copy as cURL ---
  document.getElementById('rag-curl-btn').addEventListener('click', () => {
    if (!lastQuery) return;
    const curl = `curl -N -X POST http://127.0.0.1:56156/api/rag/query \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify(lastQuery)}'`;
    Components.copyToClipboard(curl, document.getElementById('rag-curl-btn'));
  });

  // --- History ---
  document.getElementById('rag-history-btn').addEventListener('click', () => {
    _renderHistoryModal();
    document.getElementById('rag-history-modal').classList.add('active');
  });
  document.getElementById('rag-history-close').addEventListener('click', () => {
    document.getElementById('rag-history-modal').classList.remove('active');
  });
  document.getElementById('rag-history-modal').addEventListener('click', (e) => {
    if (e.target.id === 'rag-history-modal') e.target.classList.remove('active');
  });
  document.getElementById('rag-history-clear').addEventListener('click', () => {
    localStorage.removeItem('rag_history');
    _renderHistoryModal();
    Components.toast('History cleared', 'info');
  });

  // --- Helpers ---

  function _addMessage(role, content) {
    const el = document.createElement('div');
    el.className = `rag-msg rag-msg-${role}`;
    el.innerHTML = `
      <div class="rag-msg-role">${role === 'user' ? 'You' : 'Assistant'}</div>
      <div class="rag-msg-content">${_ragEsc(content)}</div>
      ${role === 'assistant' ? '<div class="rag-msg-stats"></div>' : ''}
    `;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function _renderContextDebug(ctx) {
    // Context tab: show assembled prompt
    const body = ctx.chatRequestBody || {};
    const msgs = body.messages || [];
    let text = '';
    for (const m of msgs) {
      text += `--- ${m.role} ---\n${m.content}\n\n`;
    }
    if (!text) text = JSON.stringify(ctx, null, 2);
    document.getElementById('rag-ctx-pre').querySelector('code').textContent = text;

    // Chunks tab: extract chunks with cosine scores from context messages
    const chunks = [];
    const systemMsg = msgs.find(m => m.role === 'system');
    if (systemMsg && systemMsg.content) {
      const lines = systemMsg.content.split('\n');
      let currentChunk = null;
      for (const line of lines) {
        // Look for chunk markers like "[Quelle: filename.pdf | Score: 0.85]"
        const scoreMatch = line.match(/\[(?:Quelle|Source):\s*(.+?)\s*(?:\|\s*Score:\s*([\d.]+))?\]/i);
        if (scoreMatch) {
          if (currentChunk) chunks.push(currentChunk);
          currentChunk = { source: scoreMatch[1], score: scoreMatch[2] || null, text: '' };
        } else if (currentChunk) {
          currentChunk.text += line + '\n';
        }
      }
      if (currentChunk) chunks.push(currentChunk);
    }

    const chunksEl = document.getElementById('rag-chunks-list');
    if (chunks.length > 0) {
      chunksEl.innerHTML = chunks.map((c, i) => `
        <div style="border-bottom:1px solid var(--border);padding:0.5rem 0">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.3rem">
            <span style="font-weight:600;font-size:0.78rem">#${i + 1} ${_ragEsc(c.source)}</span>
            ${c.score ? `<span class="badge badge-info">${c.score}</span>` : ''}
          </div>
          <div style="font-size:0.78rem;color:var(--text-secondary);max-height:80px;overflow:hidden;text-overflow:ellipsis">${_ragEsc(c.text.trim().slice(0, 300))}</div>
        </div>
      `).join('');
    } else {
      chunksEl.textContent = 'No chunk markers found in context';
    }
  }

  function _renderImagesDebug(images) {
    const el = document.getElementById('rag-images-list');
    if (!images || images.length === 0) {
      el.textContent = 'No images in response';
      return;
    }
    el.innerHTML = `<div class="rag-images-grid">${images.map(img => `
      <div class="rag-image-card">
        <img src="${_ragEsc(img.url || '')}" alt="${_ragEsc(img.caption || '')}" loading="lazy"
             onerror="this.style.display='none'">
        <div class="rag-image-caption">${_ragEsc(img.caption || 'No caption')}</div>
      </div>
    `).join('')}</div>`;
  }

  function _renderSourcesDebug(sources) {
    const el = document.getElementById('rag-sources-list');
    if (!sources || sources.length === 0) {
      el.textContent = 'No sources in response';
      return;
    }
    el.innerHTML = sources.map(s => {
      // Sources can be strings (markdown links) or objects
      if (typeof s === 'string') {
        const linkMatch = s.match(/\[(.+?)\]\((.+?)\)/);
        if (linkMatch) {
          return `<div style="padding:0.3rem 0;border-bottom:1px solid var(--border)">
            <a href="${_ragEsc(linkMatch[2])}" target="_blank" rel="noopener"
               style="color:var(--accent);font-size:0.82rem;text-decoration:none">${_ragEsc(linkMatch[1])}</a>
            <div style="font-size:0.7rem;color:var(--text-muted);word-break:break-all">${_ragEsc(linkMatch[2])}</div>
          </div>`;
        }
        return `<div style="padding:0.3rem 0;border-bottom:1px solid var(--border);font-size:0.82rem">${_ragEsc(s)}</div>`;
      }
      return `<div style="padding:0.3rem 0;border-bottom:1px solid var(--border)">
        <a href="${_ragEsc(s.url || '#')}" target="_blank" rel="noopener"
           style="color:var(--accent);font-size:0.82rem;text-decoration:none">${_ragEsc(s.title || s.url || 'Source')}</a>
      </div>`;
    }).join('');
  }

  function _saveHistory(query, answer, elapsedMs) {
    try {
      const history = JSON.parse(localStorage.getItem('rag_history') || '[]');
      history.unshift({
        query,
        answer: answer.slice(0, 200),
        elapsed_ms: elapsedMs,
        ts: Date.now(),
      });
      // Keep last 50
      if (history.length > 50) history.length = 50;
      localStorage.setItem('rag_history', JSON.stringify(history));
    } catch { /* localStorage may be full */ }
  }

  function _renderHistoryModal() {
    const el = document.getElementById('rag-history-list');
    let history;
    try {
      history = JSON.parse(localStorage.getItem('rag_history') || '[]');
    } catch { history = []; }

    if (history.length === 0) {
      el.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem">No history yet</p>';
      return;
    }

    el.innerHTML = history.map((h, i) => {
      const date = new Date(h.ts);
      const timeStr = date.toLocaleTimeString('de-DE', {hour: '2-digit', minute: '2-digit'});
      const dateStr = date.toLocaleDateString('de-DE');
      return `<div class="rag-history-item" data-idx="${i}">
        <div style="display:flex;justify-content:space-between;margin-bottom:0.2rem">
          <span style="font-weight:600;font-size:0.82rem;color:var(--text-primary)">${_ragEsc(h.query)}</span>
          <span style="font-size:0.7rem;color:var(--text-muted)">${dateStr} ${timeStr}</span>
        </div>
        <div style="font-size:0.78rem;color:var(--text-secondary);max-height:40px;overflow:hidden">${_ragEsc(h.answer)}</div>
        <div style="font-size:0.7rem;color:var(--text-muted);margin-top:0.2rem">${((h.elapsed_ms || 0) / 1000).toFixed(1)}s</div>
      </div>`;
    }).join('');

    // Click to re-use query
    el.querySelectorAll('.rag-history-item').forEach(item => {
      item.addEventListener('click', () => {
        const idx = parseInt(item.dataset.idx);
        const h = history[idx];
        if (h) {
          input.value = h.query;
          document.getElementById('rag-history-modal').classList.remove('active');
          input.focus();
        }
      });
    });
  }

  // Cleanup
  return () => {
    if (controller) { controller.abort(); controller = null; }
  };
};

function _ragEsc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
