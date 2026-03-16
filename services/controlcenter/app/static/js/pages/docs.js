/* ---------------------------------------------------------------------------
   docs.js — File tree, markdown renderer, TOC
   --------------------------------------------------------------------------- */

Pages.docs = function(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>Docs</h2>
      <p class="subtitle">Project documentation and guides</p>
    </div>

    <div class="docs-layout">
      <div class="card docs-sidebar-panel">
        <div class="card-header">
          <span class="card-title">Files</span>
        </div>
        <div id="docs-tree">
          ${Components.skeleton('100%', '200px')}
        </div>
      </div>

      <div class="card docs-content-panel">
        <div class="card-header">
          <span class="card-title" id="docs-filename">Select a file</span>
        </div>
        <div class="docs-toc" id="docs-toc" style="display:none"></div>
        <div class="docs-body" id="docs-body">
          <p style="color:var(--text-secondary);font-size:0.85rem">
            Select a file from the tree to view its content.
          </p>
        </div>
      </div>
    </div>
  `;

  // Load tree
  async function loadTree() {
    try {
      const data = await API.get('/api/docs/tree');
      const el = document.getElementById('docs-tree');
      if (!data.files || data.files.length === 0) {
        el.innerHTML = '<p style="color:var(--text-muted);font-size:0.82rem">No documentation files found</p>';
        return;
      }

      // Group by directory
      const groups = {};
      for (const f of data.files) {
        const dir = f.dir || '(root)';
        if (!groups[dir]) groups[dir] = [];
        groups[dir].push(f);
      }

      let html = '';
      for (const [dir, files] of Object.entries(groups)) {
        if (dir !== '(root)') {
          html += `<div style="font-size:0.72rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;padding:0.5rem 0 0.2rem;margin-top:0.3rem;border-top:1px solid var(--border)">${_docsEsc(dir)}</div>`;
        }
        for (const f of files) {
          const sizeKb = (f.size / 1024).toFixed(1);
          html += `<div class="docs-tree-item" data-path="${_docsEsc(f.path)}" title="${_docsEsc(f.path)}">
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_docsEsc(f.name)}</span>
            <span style="font-size:0.68rem;color:var(--text-muted);flex-shrink:0">${sizeKb} KB</span>
          </div>`;
        }
      }
      el.innerHTML = html;

      // Click handler
      el.querySelectorAll('.docs-tree-item').forEach(item => {
        item.addEventListener('click', () => {
          el.querySelectorAll('.docs-tree-item').forEach(i => i.classList.remove('active'));
          item.classList.add('active');
          loadContent(item.dataset.path);
        });
      });
    } catch {
      document.getElementById('docs-tree').innerHTML = '<p style="color:var(--error);font-size:0.82rem">Failed to load file tree</p>';
    }
  }

  async function loadContent(path) {
    const bodyEl = document.getElementById('docs-body');
    const tocEl = document.getElementById('docs-toc');
    const nameEl = document.getElementById('docs-filename');

    bodyEl.innerHTML = Components.skeleton('100%', '300px');
    nameEl.textContent = path;

    try {
      const data = await API.get('/api/docs/content?path=' + encodeURIComponent(path));

      // Render markdown
      if (typeof marked !== 'undefined') {
        bodyEl.innerHTML = '<div class="docs-md">' + marked.parse(data.content) + '</div>';
      } else {
        bodyEl.innerHTML = '<pre style="white-space:pre-wrap;font-size:0.82rem">' + _docsEsc(data.content) + '</pre>';
      }

      // Render TOC
      if (data.toc && data.toc.length > 1) {
        tocEl.style.display = '';
        tocEl.innerHTML = '<div style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;margin-bottom:0.3rem">Contents</div>' +
          data.toc.map(t => `<a href="#${t.slug}" class="docs-toc-item" style="padding-left:${(t.level - 1) * 12}px">${_docsEsc(t.title)}</a>`).join('');
      } else {
        tocEl.style.display = 'none';
      }
    } catch (e) {
      bodyEl.innerHTML = `<p style="color:var(--error);font-size:0.85rem">${_docsEsc(e.message)}</p>`;
      tocEl.style.display = 'none';
    }
  }

  loadTree();
};

function _docsEsc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
