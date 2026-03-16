/* ---------------------------------------------------------------------------
   timeline.js — Event feed with filters, auto-scroll, SSE stream
   --------------------------------------------------------------------------- */

Pages.timeline = function(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>Timeline</h2>
      <p class="subtitle">Real-time event stream with filters</p>
    </div>
    <div class="card" style="margin-bottom:1rem">
      <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center">
        <input type="search" id="tl-search" placeholder="Search events..." style="flex:1;min-width:150px">
        <select id="tl-service" style="min-width:120px">
          <option value="">All services</option>
        </select>
        <select id="tl-severity" style="min-width:100px">
          <option value="">All levels</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
        </select>
        <label style="font-size:0.8rem;display:flex;align-items:center;gap:0.3rem;color:var(--text-secondary)">
          <input type="checkbox" id="tl-autoscroll" checked> Auto-scroll
        </label>
      </div>
    </div>
    <div class="card">
      <div class="card-header">
        <span class="card-title">Events</span>
        <span class="connection-status" id="tl-conn">
          <span class="status-dot status-unknown"></span>
          <span class="status-text">Connecting...</span>
        </span>
      </div>
      <div id="tl-events" style="max-height:600px;overflow-y:auto;font-size:0.82rem"></div>
    </div>
  `;

  const eventsEl = document.getElementById('tl-events');
  const searchEl = document.getElementById('tl-search');
  const serviceEl = document.getElementById('tl-service');
  const severityEl = document.getElementById('tl-severity');
  const autoscrollEl = document.getElementById('tl-autoscroll');
  const connEl = document.getElementById('tl-conn');

  let allEvents = [];
  let knownServices = new Set();
  let sse = null;

  function renderEvents() {
    const search = searchEl.value.toLowerCase();
    const svcFilter = serviceEl.value;
    const sevFilter = severityEl.value;

    const filtered = allEvents.filter(e => {
      if (svcFilter && e.service !== svcFilter) return false;
      if (sevFilter && e.severity !== sevFilter) return false;
      if (search && !e.message.toLowerCase().includes(search)) return false;
      return true;
    });

    eventsEl.innerHTML = filtered.length ? filtered.map(e => `
      <div style="display:flex;gap:0.5rem;padding:0.4rem 0;border-bottom:1px solid var(--border);align-items:flex-start">
        <span class="status-dot status-${_tlSevClass(e.severity)}" style="margin-top:5px;flex-shrink:0"></span>
        <span style="font-family:var(--font-mono);font-size:0.7rem;color:var(--text-muted);white-space:nowrap;min-width:70px">${_tlTime(e.ts)}</span>
        <span class="badge badge-info" style="flex-shrink:0;font-size:0.65rem">${_tlEsc(e.service || '--')}</span>
        <span style="flex:1;min-width:0;overflow-wrap:break-word">${_tlEsc(e.message)}</span>
        <span style="font-size:0.65rem;color:var(--text-muted);flex-shrink:0">${e.type}</span>
      </div>
    `).join('') : '<p style="color:var(--text-muted);padding:1rem;text-align:center">No events match filters</p>';

    if (autoscrollEl.checked) {
      eventsEl.scrollTop = eventsEl.scrollHeight;
    }
  }

  function updateServiceFilter() {
    const current = serviceEl.value;
    const sorted = [...knownServices].sort();
    serviceEl.innerHTML = '<option value="">All services</option>' +
      sorted.map(s => `<option value="${s}"${s === current ? ' selected' : ''}>${s}</option>`).join('');
  }

  function addEvent(e) {
    allEvents.push(e);
    if (allEvents.length > 500) allEvents.shift();
    if (e.service && !knownServices.has(e.service)) {
      knownServices.add(e.service);
      updateServiceFilter();
    }
    renderEvents();
  }

  function setConnStatus(connected) {
    const dot = connEl.querySelector('.status-dot');
    const text = connEl.querySelector('.status-text');
    dot.className = `status-dot ${connected ? 'status-healthy' : 'status-unknown'}`;
    text.textContent = connected ? 'Connected' : 'Reconnecting...';
  }

  // Load initial events
  async function loadInitial() {
    try {
      const events = await API.get('/api/events?limit=100');
      allEvents = events;
      events.forEach(e => { if (e.service) knownServices.add(e.service); });
      updateServiceFilter();
      renderEvents();
    } catch {}
  }

  // Connect SSE stream
  function connectSSE() {
    sse = new JsonSSE('/api/events/stream', {
      onEvent(e) {
        addEvent(e);
      },
      onConnect() {
        setConnStatus(true);
      },
      onDisconnect() {
        setConnStatus(false);
      },
    });
  }

  // Filter change handlers
  searchEl.addEventListener('input', renderEvents);
  serviceEl.addEventListener('change', renderEvents);
  severityEl.addEventListener('change', renderEvents);

  loadInitial();
  connectSSE();

  return () => {
    if (sse) sse.close();
  };
};

function _tlSevClass(sev) {
  if (sev === 'error') return 'error';
  if (sev === 'warning') return 'unhealthy';
  return 'healthy';
}

function _tlTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

function _tlEsc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}
