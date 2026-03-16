/* ---------------------------------------------------------------------------
   dashboard.js — Metrics, topology, quick actions, activity feed
   --------------------------------------------------------------------------- */

const Pages = window.Pages || {};

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
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:1rem;">
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
          <span class="card-title">Recent Activity</span>
          <span class="time-ago" id="dash-activity-ts">--</span>
        </div>
        <div id="dash-activity" style="font-size:0.82rem;">
          ${Components.skeleton('100%', '200px')}
        </div>
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

  function refresh() {
    loadMetrics();
    loadTopology();
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
