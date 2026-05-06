/* ---------------------------------------------------------------------------
   dashboard.js — Metrics, topology, quick actions, activity feed
   --------------------------------------------------------------------------- */

Pages.dashboard = function(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>Dashboard</h2>
      <p class="subtitle">System overview and quick actions</p>
    </div>
    <div class="metrics-grid" id="dash-metrics">
      ${Components.skeleton('100%', '80px')}
      ${Components.skeleton('100%', '80px')}
      ${Components.skeleton('100%', '80px')}
      ${Components.skeleton('100%', '80px')}
    </div>
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:1rem;">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Service Topology</span>
          <span class="time-ago" id="dash-topo-ts">--</span>
        </div>
        <div id="dash-topology" style="font-size:0.82rem;">
          ${Components.skeleton('100%', '200px')}
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <span class="card-title">Runtime Baseline</span>
          <span class="time-ago" id="dash-runtime-ts">--</span>
        </div>
        <div id="dash-runtime" style="font-size:0.82rem;">
          ${Components.skeleton('100%', '200px')}
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:1rem">
      <div class="card-header">
        <span class="card-title">Recent Activity</span>
        <span class="time-ago" id="dash-activity-ts">--</span>
      </div>
      <div id="dash-activity" style="font-size:0.82rem;">
        ${Components.skeleton('100%', '200px')}
      </div>
    </div>
  `;

  let refreshTimer = null;

  async function loadMetrics() {
    try {
      const m = await API.get('/api/dashboard/metrics');
      document.getElementById('dash-metrics').innerHTML = [
        Components.metricCard(`${m.containers_up}/${m.containers_total}`, 'Containers Up', 'var(--success)'),
        Components.metricCard(m.total_docs, 'Documents'),
        Components.metricCard(m.total_chunks, 'Chunks'),
        Components.metricCard(m.total_images, 'Images'),
      ].join('');
    } catch (e) {
      document.getElementById('dash-metrics').innerHTML =
        '<div class="card" style="grid-column:1/-1;text-align:center;color:var(--error)">Failed to load metrics</div>';
    }
  }

  async function loadTopology() {
    try {
      const data = await API.get('/api/dashboard/graph');
      const el = document.getElementById('dash-topology');
      if (!data.nodes || !data.nodes.length) {
        el.innerHTML = '<p style="color:var(--text-muted)">No services found</p>';
        return;
      }
      ServiceGraph.render(el, data, { colorMode: 'status' });
      document.getElementById('dash-topo-ts').textContent = _nowLabel();
    } catch {
      document.getElementById('dash-topology').innerHTML =
        '<p style="color:var(--error)">Failed to load topology</p>';
    }
  }

  async function loadActivity() {
    try {
      const events = await API.get('/api/dashboard/recent');
      const el = document.getElementById('dash-activity');
      if (!events.length) {
        el.innerHTML = '<p style="color:var(--text-muted)">No events yet</p>';
        return;
      }
      el.innerHTML = events.reverse().map(e => `
        <div style="display:flex;gap:0.5rem;align-items:flex-start;padding:0.35rem 0;border-bottom:1px solid var(--border)">
          <span class="status-dot status-${_severityClass(e.severity)}" style="margin-top:5px"></span>
          <div style="flex:1;min-width:0">
            <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${_escHtml(e.message)}</div>
            <div style="font-size:0.7rem;color:var(--text-muted)">${_timeStr(e.ts)}${e.service ? ' &middot; ' + e.service : ''}</div>
          </div>
        </div>
      `).join('');
      document.getElementById('dash-activity-ts').textContent = _nowLabel();
    } catch {
      document.getElementById('dash-activity').innerHTML =
        '<p style="color:var(--error)">Failed to load activity</p>';
    }
  }

  async function loadRuntime() {
    try {
      const data = await API.get('/api/dashboard/runtime');
      const el = document.getElementById('dash-runtime');
      const models = data.models || [];
      const delta = data.eval && data.eval.baseline_total_s
        ? Math.round((data.eval.avg_total_s - data.eval.baseline_total_s) / data.eval.baseline_total_s * 100)
        : null;

      el.innerHTML = `
        <div style="display:grid;gap:0.75rem">
          <div style="padding:0.75rem;border:1px solid var(--border);border-radius:var(--radius);background:rgba(0,212,170,0.06)">
            <div style="font-size:0.72rem;color:var(--text-secondary);margin-bottom:0.2rem">Production Text Model</div>
            <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap">
              <code style="font-size:1rem;color:var(--text-primary)">${_escHtml(_modelByRole(models, 'Text generation')?.name || 'unknown')}</code>
              ${_loadedBadge(_modelByRole(models, 'Text generation')?.loaded)}
            </div>
            <div style="font-size:0.72rem;color:var(--text-muted);margin-top:0.35rem">
              ${_escHtml(data.eval?.label || 'latest eval')}: ${data.eval?.avg_total_s || '--'}s avg total
              ${delta !== null ? `(${delta}% vs 7B baseline)` : ''}
            </div>
          </div>
          <div style="display:grid;gap:0.35rem">
            ${models.map(m => `
              <div style="display:grid;grid-template-columns:1fr auto;gap:0.5rem;align-items:center;padding:0.45rem 0;border-bottom:1px solid var(--border)">
                <div style="min-width:0">
                  <div style="font-weight:600;color:var(--text-primary)">${_escHtml(m.role)}</div>
                  <div style="font-family:var(--font-mono);font-size:0.74rem;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${_escHtml(m.name)}</div>
                  <div style="font-size:0.7rem;color:var(--text-muted)">${_escHtml(m.note)}</div>
                </div>
                ${_loadedBadge(m.loaded)}
              </div>
            `).join('')}
          </div>
          <div class="metrics-grid" style="grid-template-columns:repeat(4,minmax(0,1fr));gap:0.5rem">
            ${Components.metricCard(data.ollama_image?.replace('ollama/ollama:', '') || '--', 'Ollama')}
            ${Components.metricCard(`${data.readiness?.pass || 0}/${data.readiness?.fail || 0}/${data.readiness?.warn || 0}`, 'Ready P/F/W', 'var(--success)')}
            ${Components.metricCard(`${data.pdf?.bbox_chunks || 0}/${data.pdf?.chunks || 0}`, 'PDF bbox', 'var(--success)')}
            ${Components.metricCard(data.pdf?.bmw_unembedded || 0, 'BMW no-embed', 'var(--warning)')}
          </div>
        </div>
      `;
      document.getElementById('dash-runtime-ts').textContent = _nowLabel();
    } catch {
      document.getElementById('dash-runtime').innerHTML =
        '<p style="color:var(--error)">Failed to load runtime baseline</p>';
    }
  }

  function refresh() {
    loadMetrics();
    loadTopology();
    loadRuntime();
    loadActivity();
  }

  refresh();
  refreshTimer = setInterval(refresh, 15000);

  return () => {
    if (refreshTimer) clearInterval(refreshTimer);
  };
};

/* Dashboard helpers */
function _truncImage(img) {
  if (!img) return '';
  if (img.length > 35) return img.slice(0, 32) + '...';
  return img;
}

function _severityClass(sev) {
  if (sev === 'error') return 'error';
  if (sev === 'warning') return 'unhealthy';
  return 'healthy';
}

function _timeStr(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

function _nowLabel() {
  return 'updated ' + new Date().toLocaleTimeString();
}

function _escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function _modelByRole(models, role) {
  return (models || []).find(m => m.role === role);
}

function _loadedBadge(loaded) {
  if (loaded === true) return '<span class="badge badge-success">loaded</span>';
  if (loaded === false) return '<span class="badge badge-warning">cold</span>';
  return '<span class="badge">unknown</span>';
}
