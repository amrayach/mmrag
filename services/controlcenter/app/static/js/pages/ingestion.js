/* ---------------------------------------------------------------------------
   ingestion.js — PDF upload zone, RSS controls, progress bars
   --------------------------------------------------------------------------- */

Pages.ingestion = function(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>Ingestion</h2>
      <p class="subtitle">PDF upload, RSS sync, and processing status</p>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
      <!-- PDF Panel -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">PDF Ingestion</span>
          <span class="time-ago" id="ing-pdf-ts">--</span>
        </div>
        <div id="ing-pdf-dropzone" class="dropzone">
          <p>Drop PDF here or <label class="btn btn-sm btn-accent" style="cursor:pointer">
            Browse <input type="file" id="ing-pdf-file" accept=".pdf" style="display:none">
          </label></p>
          <p style="font-size:0.7rem;color:var(--text-muted);margin-top:0.3rem">Max 100 MB</p>
          <p style="font-size:0.7rem;color:var(--text-muted);margin-top:0.25rem">OpenDataLoader PDF layout extraction with page-level bounding boxes; captions still use qwen2.5vl:7b.</p>
        </div>
        <div id="ing-pdf-upload-status" style="margin-top:0.5rem;font-size:0.82rem"></div>
        <div style="margin-top:0.8rem;display:flex;gap:0.5rem">
          <button class="btn btn-sm" id="ing-pdf-scan">Scan Inbox</button>
        </div>
        <div id="ing-pdf-status" style="margin-top:0.8rem;font-size:0.82rem">
          ${Components.skeleton('100%', '60px')}
        </div>
      </div>

      <!-- RSS Panel -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">RSS Ingestion</span>
          <span class="time-ago" id="ing-rss-ts">--</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:0.5rem">
          <button class="btn btn-sm btn-accent" id="ing-rss-sync">Sync RSS Feeds</button>
          <button class="btn btn-sm" id="ing-rss-backfill">Backfill Images</button>
          <button class="btn btn-sm" id="ing-rss-recaption">Recaption Images</button>
        </div>
        <div id="ing-rss-status" style="margin-top:0.8rem;font-size:0.82rem">
          ${Components.skeleton('100%', '60px')}
        </div>
      </div>
    </div>

    <!-- DB Stats -->
    <div class="card">
      <div class="card-header">
        <span class="card-title">Database Stats</span>
        <button class="btn btn-sm" id="ing-db-refresh">Refresh</button>
      </div>
      <div id="ing-db-stats">
        ${Components.skeleton('100%', '80px')}
      </div>
    </div>

    <!-- Ingestion History -->
    <div class="card" style="margin-top:1rem">
      <div class="card-header">
        <span class="card-title">Recent Ingestions</span>
        <span class="time-ago" id="ing-history-ts">--</span>
      </div>
      <div id="ing-history">
        ${Components.skeleton('100%', '120px')}
      </div>
    </div>
  `;

  let refreshTimer = null;

  // --- Drag & Drop ---
  const dropzone = document.getElementById('ing-pdf-dropzone');
  const fileInput = document.getElementById('ing-pdf-file');

  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.style.borderColor = 'var(--accent)';
    dropzone.style.background = 'rgba(233,69,96,0.08)';
  });
  dropzone.addEventListener('dragleave', () => {
    dropzone.style.borderColor = '';
    dropzone.style.background = '';
  });
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.style.borderColor = '';
    dropzone.style.background = '';
    const file = e.dataTransfer.files[0];
    if (file && file.name.toLowerCase().endsWith('.pdf')) {
      uploadPDF(file);
    } else {
      Components.toast('Only PDF files are accepted', 'warning');
    }
  });
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) uploadPDF(fileInput.files[0]);
  });

  async function uploadPDF(file) {
    const statusEl = document.getElementById('ing-pdf-upload-status');
    statusEl.innerHTML = `<span style="color:var(--warning)">Uploading ${_ingEsc(file.name)}...</span>`;
    try {
      const fd = new FormData();
      fd.append('file', file);
      const result = await API.postMultipart('/api/ingestion/pdf/upload', fd);
      statusEl.innerHTML = `<span style="color:var(--success)">${result.status}: ${_ingEsc(result.filename || file.name)}</span>`;
      Components.toast('PDF uploaded', 'success');
      setTimeout(loadPDFStatus, 2000);
    } catch (e) {
      statusEl.innerHTML = `<span style="color:var(--error)">Upload failed: ${_ingEsc(e.message)}</span>`;
      Components.toast('Upload failed', 'error');
    }
  }

  // --- PDF Controls ---
  document.getElementById('ing-pdf-scan').addEventListener('click', async () => {
    try {
      await API.post('/api/ingestion/pdf/scan');
      Components.toast('PDF scan triggered via n8n', 'success');
      setTimeout(loadPDFStatus, 2000);
    } catch (e) { Components.toast(e.message, 'error'); }
  });

  // --- RSS Controls ---
  document.getElementById('ing-rss-sync').addEventListener('click', async () => {
    try {
      await API.post('/api/ingestion/rss/sync');
      Components.toast('RSS sync triggered via n8n', 'success');
      setTimeout(loadRSSStatus, 3000);
    } catch (e) { Components.toast(e.message, 'error'); }
  });

  document.getElementById('ing-rss-backfill').addEventListener('click', async () => {
    const ok = await Components.confirm('Backfill Images', 'This will caption all uncaptioned RSS images. It may take a while.');
    if (!ok) return;
    try {
      await API.post('/api/ingestion/rss/backfill');
      Components.toast('Image backfill started', 'info');
    } catch (e) { Components.toast(e.message, 'error'); }
  });

  document.getElementById('ing-rss-recaption').addEventListener('click', async () => {
    const ok = await Components.confirm('Recaption Images', 'This will re-caption all RSS images. This is a long-running operation.');
    if (!ok) return;
    try {
      await API.post('/api/ingestion/rss/recaption');
      Components.toast('Image recaption started', 'info');
    } catch (e) { Components.toast(e.message, 'error'); }
  });

  // --- Status Loading ---
  async function loadPDFStatus() {
    try {
      const s = await API.get('/api/ingestion/pdf/status');
      const el = document.getElementById('ing-pdf-status');
      el.innerHTML = `<div class="metrics-grid" style="grid-template-columns:repeat(3,1fr)">
        ${Components.metricCard(s.active_docs || 0, 'Active', 'var(--warning)')}
        ${Components.metricCard(s.completed_docs || 0, 'Completed', 'var(--success)')}
        ${Components.metricCard(s.inbox_files || 0, 'In Inbox')}
      </div>
      <div style="margin-top:0.5rem;display:flex;gap:1rem;font-size:0.75rem;color:var(--text-secondary)">
        <span>Chunks: ${s.completed_text_chunks || 0}</span>
        <span>Images: ${s.completed_images || 0}</span>
        <span>Skipped: ${s.skipped_images || 0}</span>
        <span>Failed: ${s.failed_docs || 0}</span>
        <span>Errors: ${s.error_files || 0}</span>
        <span>Queue: ${s.caption_queue_size || 0}/${s.caption_queue_max || 0}</span>
      </div>`;
      document.getElementById('ing-pdf-ts').textContent = 'updated ' + new Date().toLocaleTimeString();
    } catch {
      document.getElementById('ing-pdf-status').innerHTML =
        '<p style="color:var(--text-muted)">pdf-ingest unavailable</p>';
    }
  }

  async function loadRSSStatus() {
    try {
      const s = await API.get('/api/ingestion/rss/status');
      const el = document.getElementById('ing-rss-status');
      const items = [];
      if (s.is_running !== undefined) items.push(`Running: ${s.is_running ? 'yes' : 'no'}`);
      if (s.total_articles !== undefined) items.push(`Articles: ${s.total_articles}`);
      if (s.total_feeds !== undefined) items.push(`Feeds: ${s.total_feeds}`);
      if (s.last_run !== undefined) items.push(`Last run: ${s.last_run || 'never'}`);

      el.innerHTML = items.length
        ? `<div style="display:flex;flex-wrap:wrap;gap:0.8rem;font-size:0.8rem;color:var(--text-secondary)">${items.map(i => `<span>${i}</span>`).join('')}</div>`
        : `<pre style="font-size:0.75rem">${JSON.stringify(s, null, 2)}</pre>`;
      document.getElementById('ing-rss-ts').textContent = 'updated ' + new Date().toLocaleTimeString();
    } catch {
      document.getElementById('ing-rss-status').innerHTML =
        '<p style="color:var(--text-muted)">rss-ingest unavailable</p>';
    }
  }

  async function loadDBStats() {
    try {
      const s = await API.get('/api/ingestion/db-stats');
      const el = document.getElementById('ing-db-stats');
      const types = Object.entries(s.chunks_by_type || {});
      el.innerHTML = `<div class="metrics-grid" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">
        ${Components.metricCard(s.total_docs || 0, 'Documents')}
        ${Components.metricCard(s.total_chunks || 0, 'Total Chunks')}
        ${types.map(([t, c]) => Components.metricCard(c, t + ' chunks', t === 'image' ? 'var(--warning)' : 'var(--success)')).join('')}
      </div>`;
    } catch {
      document.getElementById('ing-db-stats').innerHTML =
        '<p style="color:var(--error)">Failed to load DB stats</p>';
    }
  }

  document.getElementById('ing-db-refresh').addEventListener('click', loadDBStats);

  async function loadHistory() {
    try {
      const rows = await API.get('/api/ingestion/history');
      const el = document.getElementById('ing-history');
      if (!rows.length) {
        el.innerHTML = '<p style="color:var(--text-muted)">No ingestion history</p>';
        return;
      }
      el.innerHTML = `<table><thead><tr>
        <th>Filename</th><th>Source</th><th>Chunks</th><th>Images</th><th>Date</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td style="font-family:var(--font-mono);font-size:0.78rem;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_ingEsc(r.filename || '')}</td>
        <td><span class="badge ${r.source_type === 'pdf' ? 'badge-info' : 'badge-warning'}">${_ingEsc(r.source_type || '?')}</span></td>
        <td>${r.chunks}</td>
        <td>${r.images}</td>
        <td style="font-size:0.75rem;color:var(--text-secondary);white-space:nowrap">${r.created_at ? new Date(r.created_at).toLocaleString('de-DE') : '--'}</td>
      </tr>`).join('')}</tbody></table>`;
      document.getElementById('ing-history-ts').textContent = 'updated ' + new Date().toLocaleTimeString();
    } catch {
      document.getElementById('ing-history').innerHTML = '<p style="color:var(--error)">Failed to load history</p>';
    }
  }

  function refresh() {
    loadPDFStatus();
    loadRSSStatus();
    loadDBStats();
    loadHistory();
  }

  refresh();
  refreshTimer = setInterval(() => { loadPDFStatus(); loadRSSStatus(); }, 10000);

  return () => { if (refreshTimer) clearInterval(refreshTimer); };
};

function _ingEsc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
