/* ---------------------------------------------------------------------------
   service_graph.js — Shared SVG service dependency graph renderer
   --------------------------------------------------------------------------- */

window.ServiceGraph = {
  positions: {
    postgres:      { x: 200, y: 180 },
    ollama:        { x: 400, y: 180 },
    n8n:           { x: 300, y: 110 },
    pdf_ingest:    { x: 120, y: 50 },
    rss_ingest:    { x: 280, y: 50 },
    rag_gateway:   { x: 440, y: 50 },
    openwebui:     { x: 540, y: 110 },
    controlcenter: { x: 80,  y: 180 },
    filebrowser:   { x: 540, y: 180 },
    assets:        { x: 460, y: 240 },
    adminer:       { x: 140, y: 240 },
  },

  typeColors: {
    database: 'var(--warning)',
    gpu: 'var(--accent)',
    workflow: 'var(--success)',
    service: '#5dade2',
    frontend: 'var(--text-secondary)',
  },

  typeInitials: {
    database: 'DB', gpu: 'GPU', workflow: 'WF', frontend: 'FE', service: 'SV',
  },

  /**
   * Render the service graph SVG into a container element.
   * @param {HTMLElement} el - Target container
   * @param {Object} data - {nodes: [...], edges: [...]}
   * @param {Object} opts - Options
   * @param {string} opts.colorMode - 'type' (static by service type) or 'status' (live container state)
   */
  render(el, data, opts) {
    const nodes = data.nodes || [];
    const edges = data.edges || [];
    const colorMode = (opts && opts.colorMode) || 'type';
    const pos = this.positions;

    let svg = '<svg viewBox="0 0 620 280" style="width:100%;height:auto">';

    // Edges
    for (const e of edges) {
      const from = pos[e.from], to = pos[e.to];
      if (from && to) {
        svg += `<line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="var(--border)" stroke-width="1.5" opacity="0.6"/>`;
      }
    }

    // Nodes
    for (const n of nodes) {
      const p = pos[n.id];
      if (!p) continue;

      let strokeColor, fillColor;
      if (colorMode === 'status') {
        const st = n.state || 'unknown';
        if (st === 'running' && n.health_ok === false) {
          strokeColor = 'var(--warning)';
          fillColor = 'rgba(255,190,11,0.15)';
        } else if (st === 'running') {
          strokeColor = 'var(--success)';
          fillColor = 'rgba(0,212,170,0.15)';
        } else if (st === 'exited' || st === 'stopped') {
          strokeColor = 'var(--error)';
          fillColor = 'rgba(255,107,107,0.15)';
        } else {
          strokeColor = 'var(--text-muted)';
          fillColor = 'var(--bg-tertiary)';
        }
      } else {
        strokeColor = this.typeColors[n.type] || 'var(--text-secondary)';
        fillColor = 'var(--bg-tertiary)';
      }

      const initial = this.typeInitials[n.type] || 'SV';
      svg += `<circle cx="${p.x}" cy="${p.y}" r="16" fill="${fillColor}" stroke="${strokeColor}" stroke-width="2"/>`;
      svg += `<text x="${p.x}" y="${p.y + 3}" text-anchor="middle" fill="${strokeColor}" font-size="8" font-weight="700" font-family="var(--font-mono)">${initial}</text>`;
      svg += `<text x="${p.x}" y="${p.y + 28}" text-anchor="middle" fill="var(--text-secondary)" font-size="9" font-family="var(--font-sans)">${n.label}</text>`;
    }

    svg += '</svg>';
    el.innerHTML = svg;
  }
};
