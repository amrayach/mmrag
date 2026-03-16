/* ---------------------------------------------------------------------------
   data_explorer.js — Data Explorer: documents, chunks, gallery, vector search
   --------------------------------------------------------------------------- */

Pages.data_explorer = function(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>Data Explorer</h2>
      <p class="subtitle">Browse the knowledge base — documents, chunks, images, and vector search</p>
    </div>

    <div class="metrics-grid" id="dx-stats-row">
      ${Components.skeleton('100%', '70px')}
    </div>

    ${Components.tabs([
      {id: 'documents', label: 'Documents'},
      {id: 'chunks', label: 'Chunks'},
      {id: 'gallery', label: 'Gallery'},
      {id: 'latest', label: 'Latest'},
      {id: 'vsearch', label: 'Vector Search'},
    ], 'documents')}

    <div class="tab-content active" id="tab-documents">
      <div class="dx-filters" id="dx-doc-filters">
        <button class="dx-filter-btn active" data-filter="all">All</button>
        <button class="dx-filter-btn" data-filter="pdf">PDFs</button>
        <button class="dx-filter-btn" data-filter="rss">RSS Articles</button>
      </div>
      <div id="dx-doc-list">${Components.skeleton('100%', '200px')}</div>
    </div>

    <div class="tab-content" id="tab-chunks">
      <div id="dx-chunk-list">
        <p style="color:var(--text-muted)">Select a document from the Documents tab to view its chunks.</p>
      </div>
    </div>

    <div class="tab-content" id="tab-gallery">
      <div id="dx-gallery">${Components.skeleton('100%', '200px')}</div>
      <div style="text-align:center;margin-top:1rem">
        <button class="btn btn-sm" id="dx-gallery-more" style="display:none">Load More</button>
      </div>
    </div>

    <div class="tab-content" id="tab-latest">
      <div id="dx-latest">${Components.skeleton('100%', '200px')}</div>
    </div>

    <div class="tab-content" id="tab-vsearch">
      <div class="dx-vsearch-controls">
        <input type="text" id="dx-vs-query" placeholder="Enter a search query..." class="dx-vs-input">
        <div class="dx-vsearch-settings">
          <label>Threshold: <span id="dx-vs-thresh-val">0.50</span></label>
          <input type="range" id="dx-vs-threshold" min="0.1" max="1.0" step="0.05" value="0.5">
          <label>Limit:</label>
          <select id="dx-vs-limit">
            <option value="3">3</option>
            <option value="6" selected>6</option>
            <option value="10">10</option>
            <option value="20">20</option>
          </select>
          <button class="btn btn-sm btn-accent" id="dx-vs-search">Search</button>
        </div>
      </div>
      <div id="dx-vs-results">
        <p style="color:var(--text-muted)">Enter a query to search the vector space.</p>
      </div>
    </div>

    <div class="dx-image-modal" id="dx-modal">
      <img id="dx-modal-img" src="" alt="">
      <div class="dx-image-modal-caption" id="dx-modal-caption"></div>
    </div>
  `;

  // --- State ---
  let selectedDocId = null;
  let galleryOffset = 0;
  let galleryImages = [];
  let vsDebounce = null;

  // --- Tab switching ---
  container.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      container.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      container.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    });
  });

  // --- Stats ---
  async function loadStats() {
    try {
      const s = await API.get('/api/data-explorer/stats');
      document.getElementById('dx-stats-row').innerHTML = [
        Components.metricCard(s.total_docs, 'Documents'),
        Components.metricCard(s.total_chunks, 'Chunks'),
        Components.metricCard(s.unique_images || s.chunks_by_type?.image || 0, 'Images', 'var(--warning)'),
        Components.metricCard(s.embedded_chunks, 'Embedded', 'var(--success)'),
      ].join('');
    } catch {
      document.getElementById('dx-stats-row').innerHTML =
        '<div class="card" style="grid-column:1/-1;text-align:center;color:var(--error)">Failed to load stats</div>';
    }
  }

  // --- Documents tab ---
  let docFilter = null;

  async function loadDocuments() {
    const el = document.getElementById('dx-doc-list');
    el.innerHTML = Components.skeleton('100%', '200px');
    try {
      let url = '/api/data-explorer/documents?limit=100';
      if (docFilter) url += '&source_type=' + docFilter;
      const rows = await API.get(url);
      if (!rows.length) {
        el.innerHTML = '<p style="color:var(--text-muted)">No documents found</p>';
        return;
      }
      el.innerHTML = `<table><thead><tr>
        <th>Filename</th><th>Source</th><th>Pages</th><th>Chunks</th><th>Images</th><th>Date</th>
      </tr></thead><tbody>${rows.map(r => `<tr class="dx-doc-row" data-id="${r.doc_id}" style="cursor:pointer">
        <td style="font-family:var(--font-mono);font-size:0.78rem;max-width:350px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_dxEsc(r.filename || '')}</td>
        <td><span class="badge ${_sourceClass(r.source_type)}">${_sourceLabel(r.source_type)}</span></td>
        <td>${r.pages || 0}</td>
        <td>${r.chunk_count || 0}</td>
        <td>${r.image_count || 0}</td>
        <td style="font-size:0.75rem;color:var(--text-secondary);white-space:nowrap">${_fmtDate(r.created_at)}</td>
      </tr>`).join('')}</tbody></table>`;

      // Click to view chunks
      el.querySelectorAll('.dx-doc-row').forEach(row => {
        row.addEventListener('click', () => {
          selectedDocId = row.dataset.id;
          loadChunks(selectedDocId);
          // Switch to chunks tab
          container.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
          container.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
          container.querySelector('[data-tab="chunks"]').classList.add('active');
          document.getElementById('tab-chunks').classList.add('active');
        });
      });
    } catch {
      el.innerHTML = '<p style="color:var(--error)">Failed to load documents</p>';
    }
  }

  // Filter buttons
  document.getElementById('dx-doc-filters').addEventListener('click', (e) => {
    const btn = e.target.closest('.dx-filter-btn');
    if (!btn) return;
    document.querySelectorAll('#dx-doc-filters .dx-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const f = btn.dataset.filter;
    docFilter = f === 'all' ? null : f;
    loadDocuments();
  });

  // --- Chunks tab ---
  async function loadChunks(docId) {
    const el = document.getElementById('dx-chunk-list');
    el.innerHTML = Components.skeleton('100%', '200px');
    try {
      const chunks = await API.get('/api/data-explorer/chunks/' + docId);
      if (!chunks.length) {
        el.innerHTML = '<p style="color:var(--text-muted)">No chunks found for this document</p>';
        return;
      }
      const textCount = chunks.filter(c => c.chunk_type === 'text').length;
      const imgCount = chunks.filter(c => c.chunk_type === 'image').length;

      el.innerHTML = `
        <div class="metrics-grid" style="grid-template-columns:repeat(2,1fr);margin-bottom:1rem">
          ${Components.metricCard(textCount, 'Text Chunks', 'var(--success)')}
          ${Components.metricCard(imgCount, 'Image Chunks', 'var(--warning)')}
        </div>
        <div class="dx-chunk-cards">${chunks.map(c => {
          if (c.chunk_type === 'image') {
            return `<div class="dx-chunk-card dx-chunk-image">
              <div style="display:flex;gap:0.6rem;align-items:flex-start">
                ${c.asset_path ? `<img src="/api/assets/${_dxEsc(c.asset_path)}" loading="lazy" style="width:80px;height:60px;object-fit:cover;border-radius:4px;flex-shrink:0" onerror="this.style.display='none'">` : ''}
                <div style="flex:1;min-width:0">
                  <div style="display:flex;gap:0.4rem;align-items:center;margin-bottom:0.2rem">
                    <span class="badge badge-warning">image</span>
                    <span style="font-size:0.7rem;color:var(--text-muted)">Page ${c.page}</span>
                  </div>
                  <div style="font-size:0.78rem;color:var(--text-secondary)">${_dxEsc(c.caption || 'No caption')}</div>
                </div>
              </div>
            </div>`;
          }
          return `<div class="dx-chunk-card">
            <div style="display:flex;gap:0.4rem;align-items:center;margin-bottom:0.3rem">
              <span class="badge badge-info">text</span>
              <span style="font-size:0.7rem;color:var(--text-muted)">Page ${c.page}</span>
            </div>
            <div style="font-size:0.78rem;color:var(--text-secondary);line-height:1.4">${_dxEsc((c.content_text || '').slice(0, 300))}${(c.content_text || '').length > 300 ? '...' : ''}</div>
          </div>`;
        }).join('')}</div>`;
    } catch {
      el.innerHTML = '<p style="color:var(--error)">Failed to load chunks</p>';
    }
  }

  // --- Gallery tab ---
  async function loadGallery(append) {
    const el = document.getElementById('dx-gallery');
    const moreBtn = document.getElementById('dx-gallery-more');
    if (!append) {
      el.innerHTML = Components.skeleton('100%', '200px');
      galleryOffset = 0;
      galleryImages = [];
    }
    try {
      const images = await API.get(`/api/data-explorer/images?offset=${galleryOffset}&limit=50`);
      if (!images.length && !append) {
        el.innerHTML = '<p style="color:var(--text-muted)">No images found</p>';
        moreBtn.style.display = 'none';
        return;
      }
      galleryImages = galleryImages.concat(images);
      if (!append) el.innerHTML = '';

      const frag = document.createDocumentFragment();
      for (const img of images) {
        const card = document.createElement('div');
        card.className = 'dx-gallery-card';
        card.innerHTML = `
          <img src="/api/assets/${_dxEsc(img.asset_path || '')}" loading="lazy" alt="${_dxEsc(img.caption || '')}" onerror="this.parentElement.style.display='none'">
          <div class="dx-gallery-caption">${_dxEsc(img.caption || 'No caption')}</div>
          <div class="dx-gallery-doc">${_dxEsc(img.filename || '')}</div>
        `;
        card.addEventListener('click', () => _openModal(img));
        frag.appendChild(card);
      }

      // Ensure grid wrapper exists
      let grid = el.querySelector('.dx-gallery-grid');
      if (!grid) {
        grid = document.createElement('div');
        grid.className = 'dx-gallery-grid';
        el.appendChild(grid);
      }
      grid.appendChild(frag);

      galleryOffset += images.length;
      moreBtn.style.display = images.length >= 50 ? '' : 'none';
    } catch {
      if (!append) el.innerHTML = '<p style="color:var(--error)">Failed to load images</p>';
    }
  }

  document.getElementById('dx-gallery-more').addEventListener('click', () => loadGallery(true));

  // Image modal
  function _openModal(img) {
    const modal = document.getElementById('dx-modal');
    document.getElementById('dx-modal-img').src = '/api/assets/' + (img.asset_path || '');
    document.getElementById('dx-modal-caption').textContent = img.caption || '';
    modal.classList.add('active');
  }
  document.getElementById('dx-modal').addEventListener('click', (e) => {
    if (e.target.id === 'dx-modal' || e.target.id === 'dx-modal-img') {
      document.getElementById('dx-modal').classList.remove('active');
    }
  });

  // --- Latest tab ---
  async function loadLatest() {
    const el = document.getElementById('dx-latest');
    el.innerHTML = Components.skeleton('100%', '200px');
    try {
      const rows = await API.get('/api/data-explorer/latest');
      if (!rows.length) {
        el.innerHTML = '<p style="color:var(--text-muted)">No recent ingestions</p>';
        return;
      }
      el.innerHTML = rows.map(r => `
        <div class="dx-timeline-item">
          <div class="dx-timeline-dot" style="background:${r.source_type === 'pdf' ? 'var(--accent)' : 'var(--warning)'}"></div>
          <div style="flex:1;min-width:0">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.2rem">
              <span style="font-weight:600;font-size:0.82rem">${_dxEsc(r.filename || '')}</span>
              <span class="badge ${_sourceClass(r.source_type)}" style="font-size:0.65rem">${_sourceLabel(r.source_type)}</span>
            </div>
            <div style="font-size:0.75rem;color:var(--text-secondary)">
              ${r.chunk_count || 0} chunks &middot; ${r.image_count || 0} images
              &middot; <span style="color:var(--text-muted)">${_fmtDate(r.created_at)}</span>
            </div>
          </div>
        </div>
      `).join('');
    } catch {
      el.innerHTML = '<p style="color:var(--error)">Failed to load latest</p>';
    }
  }

  // --- Vector Search tab ---
  const vsQuery = document.getElementById('dx-vs-query');
  const vsThreshold = document.getElementById('dx-vs-threshold');
  const vsLimit = document.getElementById('dx-vs-limit');
  const vsSearchBtn = document.getElementById('dx-vs-search');

  vsThreshold.addEventListener('input', () => {
    document.getElementById('dx-vs-thresh-val').textContent = parseFloat(vsThreshold.value).toFixed(2);
  });

  async function doVectorSearch() {
    const query = vsQuery.value.trim();
    if (!query) return;
    const el = document.getElementById('dx-vs-results');
    el.innerHTML = Components.skeleton('100%', '150px');
    try {
      const data = await API.post('/api/data-explorer/vector-search', {
        query: query,
        limit: parseInt(vsLimit.value),
        threshold: parseFloat(vsThreshold.value),
      });
      const results = data.results || [];
      if (!results.length) {
        el.innerHTML = `<p style="color:var(--text-muted)">No results above threshold ${data.threshold} (${data.total_before_filter} candidates checked)</p>`;
        return;
      }
      el.innerHTML = results.map((r, i) => {
        const pct = Math.round((r.similarity || 0) * 100);
        const color = pct >= 70 ? 'var(--success)' : pct >= 40 ? 'var(--warning)' : 'var(--error)';
        const content = r.chunk_type === 'image'
          ? `<div style="display:flex;gap:0.5rem;align-items:flex-start">
               ${r.asset_path ? `<img src="/api/assets/${_dxEsc(r.asset_path)}" loading="lazy" style="width:80px;height:60px;object-fit:cover;border-radius:4px" onerror="this.style.display='none'">` : ''}
               <span>${_dxEsc(r.caption || 'No caption')}</span>
             </div>`
          : `<div style="line-height:1.4">${_dxEsc((r.content_text || '').slice(0, 300))}${(r.content_text || '').length > 300 ? '...' : ''}</div>`;

        return `<div class="dx-vs-result">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.3rem">
            <div style="display:flex;gap:0.4rem;align-items:center">
              <span style="font-weight:700;font-size:0.82rem;color:${color}">#${i + 1}</span>
              <span class="badge ${r.chunk_type === 'image' ? 'badge-warning' : 'badge-info'}">${r.chunk_type}</span>
              <span style="font-size:0.7rem;color:var(--text-muted)">p.${r.page}</span>
            </div>
            <span style="font-family:var(--font-mono);font-size:0.78rem;color:${color}">${(r.similarity || 0).toFixed(4)}</span>
          </div>
          <div class="dx-score-bar"><div class="dx-score-fill" style="width:${pct}%;background:${color}"></div></div>
          <div style="font-size:0.78rem;color:var(--text-secondary);margin:0.4rem 0">${content}</div>
          <div style="font-size:0.7rem;color:var(--text-muted);font-family:var(--font-mono)">${_dxEsc(r.filename || '')}</div>
        </div>`;
      }).join('');
    } catch (e) {
      el.innerHTML = `<p style="color:var(--error)">${_dxEsc(e.message || 'Vector search failed')}</p>`;
    }
  }

  vsSearchBtn.addEventListener('click', doVectorSearch);

  // Debounced search on Enter
  vsQuery.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(vsDebounce);
      vsDebounce = setTimeout(doVectorSearch, 300);
    }
  });

  // --- Initial loads ---
  loadStats();
  loadDocuments();

  // Lazy-load other tabs on first switch
  let galleryLoaded = false, latestLoaded = false;
  container.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      if (tab.dataset.tab === 'gallery' && !galleryLoaded) {
        galleryLoaded = true;
        loadGallery(false);
      }
      if (tab.dataset.tab === 'latest' && !latestLoaded) {
        latestLoaded = true;
        loadLatest();
      }
    });
  });

  return () => {
    clearTimeout(vsDebounce);
  };
};

/* Helpers */
function _dxEsc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function _sourceClass(st) {
  if (st === 'pdf') return 'badge-info';
  if (st === 'rss_article' || st === 'rss') return 'badge-warning';
  return '';
}

function _sourceLabel(st) {
  if (st === 'pdf') return 'PDF';
  if (st === 'rss_article') return 'RSS';
  if (st === 'rss') return 'RSS';
  return st || '?';
}

function _fmtDate(iso) {
  if (!iso) return '--';
  try { return new Date(iso).toLocaleString('de-DE'); } catch { return iso; }
}
