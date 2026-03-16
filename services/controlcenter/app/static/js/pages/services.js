/* ---------------------------------------------------------------------------
   services.js — Container table, logs viewer, stats, env vars
   --------------------------------------------------------------------------- */

Pages.services = function(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>Services</h2>
      <p class="subtitle">Container management, logs, and stats</p>
    </div>
    <div class="card">
      <div class="card-header">
        <span class="card-title">Containers</span>
        <button class="btn btn-sm" id="svc-refresh">Refresh</button>
      </div>
      <div class="table-wrap" id="svc-table">
        ${Components.skeleton('100%', '300px')}
      </div>
    </div>
    <div id="svc-detail" style="margin-top:1rem;display:none">
      <div class="card">
        <div class="card-header">
          <span class="card-title" id="svc-detail-name">--</span>
          <div style="display:flex;gap:0.5rem">
            <button class="btn btn-sm btn-success" id="svc-btn-start">Start</button>
            <button class="btn btn-sm" id="svc-btn-restart">Restart</button>
            <button class="btn btn-sm btn-danger" id="svc-btn-stop">Stop</button>
          </div>
        </div>
        ${Components.tabs([
          {id:'logs', label:'Logs'},
          {id:'stats', label:'Stats'},
          {id:'env', label:'Env'},
        ], 'logs')}
        <div class="tab-content active" id="tab-logs">
          <pre id="svc-logs" style="max-height:400px;overflow-y:auto;font-size:0.75rem;line-height:1.4"></pre>
        </div>
        <div class="tab-content" id="tab-stats">
          <div id="svc-stats"></div>
        </div>
        <div class="tab-content" id="tab-env">
          <div id="svc-env"></div>
        </div>
      </div>
    </div>
  `;

  let _es = null;   // current log EventSource
  let _selected = null;
  let refreshTimer = null;

  // Tab switching
  container.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      container.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      container.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
      tab.classList.add('active');
      const panel = document.getElementById('tab-' + tab.dataset.tab);
      if (panel) panel.classList.add('active');
    });
  });

  async function loadTable() {
    try {
      const services = await API.get('/api/services');
      const el = document.getElementById('svc-table');
      if (!services.length) {
        el.innerHTML = '<p style="color:var(--text-muted);padding:1rem">No containers found</p>';
        return;
      }
      el.innerHTML = `<table><thead><tr>
        <th style="width:30px"></th><th>Service</th><th>State</th><th>Image</th><th>Ports</th><th></th>
      </tr></thead><tbody>${services.map(s => `<tr>
        <td>${Components.statusDot(s.state, s.health)}</td>
        <td style="font-weight:500">${s.short_name}</td>
        <td>${Components.statusBadge(s.state, s.health)}</td>
        <td style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-secondary)">${_truncImg(s.image)}</td>
        <td style="font-family:var(--font-mono);font-size:0.75rem">${_fmtPorts(s.ports)}</td>
        <td><button class="btn btn-sm svc-select-btn" data-name="${s.short_name}">Details</button></td>
      </tr>`).join('')}</tbody></table>`;

      el.querySelectorAll('.svc-select-btn').forEach(btn => {
        btn.addEventListener('click', () => selectService(btn.dataset.name));
      });
    } catch {
      document.getElementById('svc-table').innerHTML =
        '<p style="color:var(--error);padding:1rem">Failed to load services</p>';
    }
  }

  async function selectService(name) {
    _selected = name;
    document.getElementById('svc-detail').style.display = 'block';
    document.getElementById('svc-detail-name').textContent = name;

    // Activate logs tab by default
    container.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'logs'));
    container.querySelectorAll('.tab-content').forEach(tc => tc.classList.toggle('active', tc.id === 'tab-logs'));

    loadLogs(name);
    loadStats(name);
    loadEnv(name);
  }

  function loadLogs(name) {
    if (_es) { _es.close(); _es = null; }
    const pre = document.getElementById('svc-logs');
    pre.textContent = 'Loading logs...\n';

    _es = new EventSource(`/api/services/${name}/logs?tail=100`);
    _es.addEventListener('log', (e) => {
      pre.textContent += e.data + '\n';
      pre.scrollTop = pre.scrollHeight;
    });
    _es.addEventListener('system', (e) => {
      pre.textContent += '\n' + e.data + '\n';
    });
    _es.onerror = () => {
      _es.close();
      _es = null;
    };
  }

  async function loadStats(name) {
    const el = document.getElementById('svc-stats');
    el.innerHTML = Components.skeleton('100%', '100px');
    try {
      const s = await API.get(`/api/services/${name}/stats`);
      el.innerHTML = `<div class="metrics-grid" style="grid-template-columns:repeat(3,1fr)">
        ${Components.metricCard(s.cpu_percent.toFixed(1) + '%', 'CPU', 'var(--accent)')}
        ${Components.metricCard(Components.formatBytes(s.memory_usage), 'Memory', 'var(--warning)')}
        ${Components.metricCard(s.memory_percent.toFixed(1) + '%', 'Mem %', 'var(--warning)')}
      </div>
      <div class="metrics-grid" style="grid-template-columns:repeat(2,1fr);margin-top:0.5rem">
        ${Components.metricCard(Components.formatBytes(s.net_rx_bytes), 'Net RX', 'var(--success)')}
        ${Components.metricCard(Components.formatBytes(s.net_tx_bytes), 'Net TX', 'var(--success)')}
      </div>`;
    } catch {
      el.innerHTML = '<p style="color:var(--text-muted)">Stats unavailable (container may be stopped)</p>';
    }
  }

  async function loadEnv(name) {
    const el = document.getElementById('svc-env');
    el.innerHTML = Components.skeleton('100%', '100px');
    try {
      const envVars = await API.get(`/api/services/${name}/env`);
      el.innerHTML = `<table><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>
        ${envVars.map(e => `<tr>
          <td style="font-family:var(--font-mono);font-size:0.75rem">${_escH(e.key)}</td>
          <td style="font-family:var(--font-mono);font-size:0.75rem;color:${e.value === '***' ? 'var(--error)' : 'var(--text-secondary)'}">${_escH(e.value)}</td>
        </tr>`).join('')}
      </tbody></table>`;
    } catch {
      el.innerHTML = '<p style="color:var(--text-muted)">Environment unavailable</p>';
    }
  }

  // Action buttons
  document.getElementById('svc-btn-start').addEventListener('click', async () => {
    if (!_selected) return;
    try {
      await API.post(`/api/services/${_selected}/start`);
      Components.toast(`${_selected} started`, 'success');
      setTimeout(loadTable, 2000);
    } catch (e) { Components.toast(e.message, 'error'); }
  });

  document.getElementById('svc-btn-stop').addEventListener('click', async () => {
    if (!_selected) return;
    const ok = await Components.confirm('Stop Service', `Stop ${_selected}? This may affect the demo.`);
    if (!ok) return;
    try {
      await API.post(`/api/services/${_selected}/stop?confirm=true`);
      Components.toast(`${_selected} stopped`, 'warning');
      setTimeout(loadTable, 2000);
    } catch (e) { Components.toast(e.message, 'error'); }
  });

  document.getElementById('svc-btn-restart').addEventListener('click', async () => {
    if (!_selected) return;
    const ok = await Components.confirm('Restart Service', `Restart ${_selected}?`);
    if (!ok) return;
    try {
      await API.post(`/api/services/${_selected}/restart?confirm=true`);
      Components.toast(`${_selected} restarted`, 'info');
      setTimeout(loadTable, 3000);
    } catch (e) { Components.toast(e.message, 'error'); }
  });

  document.getElementById('svc-refresh').addEventListener('click', loadTable);

  loadTable();
  refreshTimer = setInterval(loadTable, 15000);

  return () => {
    if (_es) { _es.close(); _es = null; }
    if (refreshTimer) clearInterval(refreshTimer);
  };
};

function _truncImg(img) {
  if (!img) return '';
  return img.length > 40 ? img.slice(0, 37) + '...' : img;
}

function _fmtPorts(ports) {
  if (!ports || !ports.length) return '<span style="color:var(--text-muted)">internal</span>';
  return ports.map(p => `${p.host_port}`).join(', ');
}

function _escH(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}
