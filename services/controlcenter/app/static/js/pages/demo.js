/* ---------------------------------------------------------------------------
   demo.js — Toggle, readiness checklist, prewarm, model status, Tailscale URLs
   --------------------------------------------------------------------------- */

Pages.demo = function(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>Demo Mode</h2>
      <p class="subtitle">Toggle demo mode, readiness checks, and model prewarming</p>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
      <!-- Demo Toggle -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">Demo Toggle</span>
        </div>
        <div id="demo-status" style="margin-bottom:0.8rem">
          ${Components.skeleton('100%', '40px')}
        </div>
        <div style="display:flex;gap:0.5rem">
          <button class="btn btn-sm btn-success" id="demo-start">Start Demo Mode</button>
          <button class="btn btn-sm btn-danger" id="demo-stop">Stop Demo Mode</button>
        </div>
        <div id="demo-steps" style="margin-top:0.8rem;font-size:0.82rem"></div>
      </div>

      <!-- Models -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">Ollama Models</span>
          <button class="btn btn-sm" id="demo-prewarm">Prewarm All</button>
        </div>
        <div id="demo-models">
          ${Components.skeleton('100%', '100px')}
        </div>
      </div>
    </div>

    <!-- Readiness Check -->
    <div class="card" style="margin-bottom:1rem">
      <div class="card-header">
        <span class="card-title">Readiness Check</span>
        <button class="btn btn-sm btn-accent" id="demo-readiness-btn">Run Checks</button>
      </div>
      <div id="demo-readiness" style="font-size:0.82rem"></div>
    </div>

    <!-- Tailscale URLs -->
    <div class="card">
      <div class="card-header">
        <span class="card-title">Tailscale URLs</span>
      </div>
      <div id="demo-tailscale">
        ${Components.skeleton('100%', '80px')}
      </div>
    </div>
  `;

  let refreshTimer = null;

  // --- Demo Status ---
  async function loadStatus() {
    try {
      const s = await API.get('/api/demo/status');
      const el = document.getElementById('demo-status');
      el.innerHTML = `
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem">
          <span class="status-dot ${s.demo_active ? 'status-healthy' : 'status-stopped'}"></span>
          <span style="font-weight:600">${s.demo_active ? 'Demo Mode Active' : 'Demo Mode Inactive'}</span>
        </div>
        <div style="font-size:0.8rem;color:var(--text-secondary)">
          rss-ingest: <span class="badge ${s.rss_ingest_state === 'running' ? 'badge-success' : 'badge-warning'}">${s.rss_ingest_state}</span>
          &nbsp; Models: <span class="badge ${s.all_models_loaded ? 'badge-success' : 'badge-warning'}">${s.models_loaded.length}/3 loaded</span>
        </div>`;
    } catch {
      document.getElementById('demo-status').innerHTML = '<p style="color:var(--error)">Failed to load status</p>';
    }
  }

  // --- Demo Start/Stop ---
  document.getElementById('demo-start').addEventListener('click', async () => {
    const ok = await Components.confirm('Start Demo Mode',
      'This will stop rss-ingest and prewarm all models. Takes ~30-60 seconds.');
    if (!ok) return;
    const btn = document.getElementById('demo-start');
    const stepsEl = document.getElementById('demo-steps');
    btn.disabled = true;
    stepsEl.innerHTML = '<p style="color:var(--warning)">Starting demo mode...</p>';
    try {
      const result = await API.post('/api/demo/start');
      stepsEl.innerHTML = result.steps.map(s =>
        `<div style="display:flex;gap:0.5rem;padding:0.2rem 0">
          <span class="status-dot ${s.status === 'ok' ? 'status-healthy' : 'status-error'}" style="margin-top:4px"></span>
          <span>${_demoEsc(s.step)}</span>
          <span style="color:var(--text-muted);font-size:0.75rem">${_demoEsc(s.detail)}</span>
        </div>`
      ).join('');
      Components.toast(result.all_ok ? 'Demo mode activated' : 'Demo mode started with warnings', result.all_ok ? 'success' : 'warning');
      loadStatus();
      loadModels();
    } catch (e) {
      stepsEl.innerHTML = `<p style="color:var(--error)">${_demoEsc(e.message)}</p>`;
      Components.toast('Failed to start demo mode', 'error');
    }
    btn.disabled = false;
  });

  document.getElementById('demo-stop').addEventListener('click', async () => {
    try {
      await API.post('/api/demo/stop');
      Components.toast('Demo mode deactivated', 'info');
      document.getElementById('demo-steps').innerHTML = '';
      loadStatus();
    } catch (e) { Components.toast(e.message, 'error'); }
  });

  // --- Models ---
  async function loadModels() {
    try {
      const data = await API.get('/api/demo/models');
      const el = document.getElementById('demo-models');
      el.innerHTML = data.models.map(m => `
        <div style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0;border-bottom:1px solid var(--border)">
          <span class="status-dot ${m.loaded ? 'status-healthy' : 'status-stopped'}"></span>
          <span style="font-family:var(--font-mono);font-size:0.8rem;flex:1">${_demoEsc(m.name)}</span>
          <span class="badge ${m.loaded ? 'badge-success' : 'badge-error'}">${m.loaded ? 'loaded' : 'unloaded'}</span>
          ${m.loaded && m.size_vram ? `<span style="font-size:0.7rem;color:var(--text-muted)">${Components.formatBytes(m.size_vram)} VRAM</span>` : ''}
        </div>
      `).join('') +
        `<div style="margin-top:0.5rem;font-size:0.75rem;color:var(--text-secondary)">Total VRAM: ${Components.formatBytes(data.total_vram)}</div>`;
    } catch {
      document.getElementById('demo-models').innerHTML = '<p style="color:var(--text-muted)">Ollama unavailable</p>';
    }
  }

  // --- Prewarm ---
  document.getElementById('demo-prewarm').addEventListener('click', async () => {
    const btn = document.getElementById('demo-prewarm');
    btn.disabled = true;
    btn.textContent = 'Prewarming...';
    try {
      const data = await API.post('/api/demo/prewarm');
      const allOk = data.results.every(r => r.status === 'ok');
      Components.toast(allOk ? 'All models prewarmed' : 'Prewarm completed with errors',
        allOk ? 'success' : 'warning');
      loadModels();
    } catch (e) { Components.toast(e.message, 'error'); }
    btn.disabled = false;
    btn.textContent = 'Prewarm All';
  });

  // --- Readiness ---
  document.getElementById('demo-readiness-btn').addEventListener('click', () => {
    const el = document.getElementById('demo-readiness');
    const btn = document.getElementById('demo-readiness-btn');
    btn.disabled = true;
    el.innerHTML = '';
    let pass = 0, fail = 0, warn = 0;

    const es = new EventSource('/api/demo/readiness');
    es.addEventListener('check', (e) => {
      const c = JSON.parse(e.data);
      let icon, color;
      if (c.status === 'pass') { icon = 'PASS'; color = 'var(--success)'; pass++; }
      else if (c.status === 'warn') { icon = 'WARN'; color = 'var(--warning)'; warn++; }
      else { icon = 'FAIL'; color = 'var(--error)'; fail++; }

      el.innerHTML += `<div style="display:flex;gap:0.5rem;padding:0.3rem 0;border-bottom:1px solid var(--border)">
        <span style="font-family:var(--font-mono);font-size:0.7rem;color:${color};min-width:35px;font-weight:700">${icon}</span>
        <span style="min-width:40px;font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted)">${c.num}.</span>
        <span style="flex:1">${_demoEsc(c.name)}</span>
        <span style="color:var(--text-secondary);font-size:0.8rem">${_demoEsc(c.detail)}</span>
      </div>`;
    });
    es.addEventListener('done', () => {
      es.close();
      btn.disabled = false;
      el.innerHTML += `<div style="margin-top:0.8rem;padding:0.6rem;border-radius:var(--radius);background:var(--bg-tertiary);text-align:center;font-weight:600">
        <span style="color:var(--success)">PASS: ${pass}</span> &nbsp;|&nbsp;
        <span style="color:var(--error)">FAIL: ${fail}</span> &nbsp;|&nbsp;
        <span style="color:var(--warning)">WARN: ${warn}</span>
        &nbsp;&mdash;&nbsp; ${fail === 0 ? 'Demo is ready!' : 'Fix failures above.'}
      </div>`;
    });
    es.onerror = () => {
      es.close();
      btn.disabled = false;
      el.innerHTML += '<p style="color:var(--error);margin-top:0.5rem">Readiness check stream ended unexpectedly</p>';
    };
  });

  // --- Tailscale URLs ---
  async function loadTailscale() {
    try {
      const data = await API.get('/api/demo/tailscale-urls');
      const el = document.getElementById('demo-tailscale');
      if (!data.configured) {
        el.innerHTML = '<p style="color:var(--text-muted)">TAILNET_HOST not configured</p>';
        return;
      }
      el.innerHTML = data.urls.map(u => `
        <div style="display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0;border-bottom:1px solid var(--border)">
          <span style="min-width:140px;font-size:0.82rem">${_demoEsc(u.label)}</span>
          <code style="flex:1;font-size:0.78rem">${_demoEsc(u.url)}</code>
          <button class="btn btn-sm demo-copy-url" data-url="${u.url}">Copy</button>
        </div>
      `).join('');
      el.querySelectorAll('.demo-copy-url').forEach(btn => {
        btn.addEventListener('click', () => Components.copyToClipboard(btn.dataset.url, btn));
      });
    } catch {
      document.getElementById('demo-tailscale').innerHTML = '<p style="color:var(--error)">Failed to load Tailscale URLs</p>';
    }
  }

  loadStatus();
  loadModels();
  loadTailscale();
  refreshTimer = setInterval(() => { loadStatus(); loadModels(); }, 30000);

  return () => { if (refreshTimer) clearInterval(refreshTimer); };
};

function _demoEsc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
