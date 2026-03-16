/* ---------------------------------------------------------------------------
   components.js — Reusable UI components
   --------------------------------------------------------------------------- */

const Components = {
  /**
   * Render a metric card.
   */
  metricCard(value, label, color = 'var(--accent)') {
    return `<div class="metric-card">
      <div class="metric-value" style="color:${color}">${value}</div>
      <div class="metric-label">${label}</div>
    </div>`;
  },

  /**
   * Status dot with merged container + health state.
   * States: running+healthy -> success, running+unhealthy -> warning,
   *         running+none -> success (no healthcheck), stopped -> error
   */
  statusDot(state, health) {
    let cls = 'status-unknown';
    if (state === 'running') {
      cls = health === 'unhealthy' ? 'status-unhealthy' : 'status-healthy';
    } else if (state === 'exited' || state === 'stopped') {
      cls = 'status-stopped';
    }
    return `<span class="status-dot ${cls}"></span>`;
  },

  /**
   * Status badge (text).
   */
  statusBadge(state, health) {
    let label, cls;
    if (state === 'running') {
      if (health === 'unhealthy') {
        label = 'unhealthy';
        cls = 'badge-warning';
      } else if (health === 'healthy') {
        label = 'healthy';
        cls = 'badge-success';
      } else {
        label = 'running';
        cls = 'badge-success';
      }
    } else {
      label = state || 'unknown';
      cls = 'badge-error';
    }
    return `<span class="badge ${cls}">${label}</span>`;
  },

  /**
   * Time-ago display. Returns HTML with auto-updating.
   */
  timeAgo(timestamp) {
    if (!timestamp) return '<span class="time-ago">--</span>';
    const id = 'ta-' + Math.random().toString(36).slice(2, 8);
    // Register for updates
    setTimeout(() => Components._startTimeAgo(id, timestamp), 0);
    return `<span class="time-ago" id="${id}" data-ts="${timestamp}"></span>`;
  },

  _startTimeAgo(id, timestamp) {
    const el = document.getElementById(id);
    if (!el) return;
    const update = () => {
      const now = Date.now() / 1000;
      const ts = typeof timestamp === 'number' ? timestamp : new Date(timestamp).getTime() / 1000;
      const diff = Math.max(0, now - ts);
      let text;
      if (diff < 5) text = 'just now';
      else if (diff < 60) text = `${Math.floor(diff)}s ago`;
      else if (diff < 3600) text = `${Math.floor(diff / 60)}m ago`;
      else if (diff < 86400) text = `${Math.floor(diff / 3600)}h ago`;
      else text = `${Math.floor(diff / 86400)}d ago`;
      el.textContent = text;
    };
    update();
    const interval = setInterval(() => {
      if (!document.getElementById(id)) { clearInterval(interval); return; }
      update();
    }, 10000);
  },

  /**
   * Show a toast notification.
   */
  toast(message, severity = 'info', durationMs = 5000) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast toast-${severity}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
      el.classList.add('toast-out');
      setTimeout(() => el.remove(), 300);
    }, durationMs);
  },

  /**
   * Copy text to clipboard with visual feedback.
   */
  async copyToClipboard(text, feedbackEl = null) {
    try {
      await navigator.clipboard.writeText(text);
      if (feedbackEl) {
        const orig = feedbackEl.textContent;
        feedbackEl.textContent = 'Copied!';
        setTimeout(() => feedbackEl.textContent = orig, 1500);
      }
    } catch {
      Components.toast('Copy failed', 'error');
    }
  },

  /**
   * Show a confirmation modal. Returns a Promise<boolean>.
   */
  confirm(title, message) {
    return new Promise(resolve => {
      const overlay = document.createElement('div');
      overlay.className = 'modal-overlay active';
      overlay.innerHTML = `<div class="modal">
        <h3>${title}</h3>
        <p>${message}</p>
        <div class="modal-actions">
          <button class="btn" id="modal-cancel">Cancel</button>
          <button class="btn btn-danger" id="modal-confirm">Confirm</button>
        </div>
      </div>`;
      document.body.appendChild(overlay);

      overlay.querySelector('#modal-cancel').onclick = () => {
        overlay.remove();
        resolve(false);
      };
      overlay.querySelector('#modal-confirm').onclick = () => {
        overlay.remove();
        resolve(true);
      };
      overlay.onclick = (e) => {
        if (e.target === overlay) { overlay.remove(); resolve(false); }
      };
    });
  },

  /**
   * Loading skeleton placeholder.
   */
  skeleton(width = '100%', height = '1rem') {
    return `<div class="skeleton" style="width:${width};height:${height}"></div>`;
  },

  /**
   * Tabs component.
   * @param {Array<{id, label}>} tabs
   * @param {string} activeId
   * @returns {string} HTML
   */
  tabs(tabDefs, activeId) {
    return `<div class="tabs">${tabDefs.map(t =>
      `<button class="tab${t.id === activeId ? ' active' : ''}" data-tab="${t.id}">${t.label}</button>`
    ).join('')}</div>`;
  },

  /**
   * Format bytes to human readable.
   */
  formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  },
};
