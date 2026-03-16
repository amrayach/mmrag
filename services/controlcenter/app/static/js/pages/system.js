/* ---------------------------------------------------------------------------
   system.js — Config viewer, disk usage, service graph
   --------------------------------------------------------------------------- */

Pages.system = function(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>System</h2>
      <p class="subtitle">Configuration, disk usage, and service dependencies</p>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
      <!-- Disk Usage -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">Disk Usage</span>
        </div>
        <div id="sys-disk">
          ${Components.skeleton('100%', '120px')}
        </div>
      </div>

      <!-- Service Graph -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">Service Dependencies</span>
        </div>
        <div id="sys-graph">
          ${Components.skeleton('100%', '120px')}
        </div>
      </div>
    </div>

    <!-- Config -->
    <div class="card">
      <div class="card-header">
        <span class="card-title">Environment Configuration</span>
      </div>
      <div id="sys-config">
        ${Components.skeleton('100%', '200px')}
      </div>
    </div>
  `;

  async function loadDisk() {
    try {
      const data = await API.get('/api/system/disk-usage');
      const el = document.getElementById('sys-disk');
      let html = '';

      // Data directories
      const dirs = data.directories || {};
      for (const [name, info] of Object.entries(dirs)) {
        if (info.missing) continue;
        html += `<div style="display:flex;justify-content:space-between;padding:0.35rem 0;border-bottom:1px solid var(--border);font-size:0.82rem">
          <span>data/${_sysEsc(name)}</span>
          <span style="color:var(--text-secondary)">${Components.formatBytes(info.size)} (${info.files} files)</span>
        </div>`;
      }

      // Partition
      if (data.partition) {
        const p = data.partition;
        const pctColor = p.percent > 90 ? 'var(--error)' : p.percent > 70 ? 'var(--warning)' : 'var(--success)';
        html += `<div style="margin-top:0.8rem">
          <div style="display:flex;justify-content:space-between;font-size:0.78rem;margin-bottom:0.3rem">
            <span>Partition</span>
            <span style="color:${pctColor};font-weight:600">${p.percent}% used</span>
          </div>
          <div style="background:var(--bg-tertiary);border-radius:4px;height:8px;overflow:hidden">
            <div style="background:${pctColor};height:100%;width:${p.percent}%;transition:width 0.3s"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:0.7rem;color:var(--text-muted);margin-top:0.3rem">
            <span>${Components.formatBytes(p.used)} used</span>
            <span>${Components.formatBytes(p.free)} free</span>
          </div>
        </div>`;
      }

      el.innerHTML = html || '<p style="color:var(--text-muted);font-size:0.82rem">No data available</p>';
    } catch {
      document.getElementById('sys-disk').innerHTML = '<p style="color:var(--error);font-size:0.82rem">Failed to load disk usage</p>';
    }
  }

  async function loadConfig() {
    try {
      const data = await API.get('/api/system/config');
      const el = document.getElementById('sys-config');
      const env = data.env || {};
      const keys = Object.keys(env);

      if (keys.length === 0) {
        el.innerHTML = '<p style="color:var(--text-muted);font-size:0.82rem">No configuration found</p>';
        return;
      }

      el.innerHTML = `<table><thead><tr><th>Variable</th><th>Value</th></tr></thead><tbody>${
        keys.map(k => {
          const masked = env[k] === '****';
          return `<tr>
            <td style="font-family:var(--font-mono);font-size:0.78rem;white-space:nowrap">${_sysEsc(k)}</td>
            <td style="font-family:var(--font-mono);font-size:0.78rem;word-break:break-all;${masked ? 'color:var(--text-muted)' : ''}">${_sysEsc(env[k])}</td>
          </tr>`;
        }).join('')
      }</tbody></table>`;
    } catch {
      document.getElementById('sys-config').innerHTML = '<p style="color:var(--error);font-size:0.82rem">Failed to load config</p>';
    }
  }

  async function loadGraph() {
    try {
      const data = await API.get('/api/system/service-graph');
      const el = document.getElementById('sys-graph');
      ServiceGraph.render(el, data, { colorMode: 'type' });
    } catch {
      document.getElementById('sys-graph').innerHTML = '<p style="color:var(--error);font-size:0.82rem">Failed to load graph</p>';
    }
  }

  loadDisk();
  loadConfig();
  loadGraph();
};

function _sysEsc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
