/* ---------------------------------------------------------------------------
   demo_access.js — Demo access code administration via demo-site proxy
   --------------------------------------------------------------------------- */

Pages.demo_access = function(container) {
  const state = {
    codes: [],
    demoPublicUrl: '',
    lastCreated: null,
    loading: false,
    creating: false,
  };

  container.innerHTML = `
    <div class="page-header">
      <h2>Demo-Zugang</h2>
      <p class="subtitle">Interne Verwaltung der zeitlich begrenzten Demo-Codes</p>
    </div>

    <div class="demo-access-error" id="da-error" aria-live="polite" style="display:none"></div>

    <div class="demo-access-layout">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Neuen Code erstellen</span>
        </div>
        <form class="demo-access-form" id="da-create-form">
          <label>
            <span>Bezeichnung</span>
            <input type="text" id="da-label" placeholder="z.B. Kundentermin 14:00" autocomplete="off" required>
          </label>
          <label>
            <span>G&uuml;ltigkeit</span>
            <select id="da-ttl">
              <option value="1">1 Stunde</option>
              <option value="24" selected>24 Stunden</option>
              <option value="48">48 Stunden</option>
              <option value="168">7 Tage</option>
            </select>
          </label>
          <label>
            <span>Max. Einl&ouml;sungen</span>
            <input type="number" id="da-max-redemptions" min="1" step="1" value="1" inputmode="numeric">
          </label>
          <label>
            <span>Erstellt von</span>
            <input type="text" id="da-created-by" value="Sven" autocomplete="name">
          </label>
          <label class="demo-access-form-wide">
            <span>Notizen</span>
            <textarea id="da-notes" rows="3" placeholder="Interner Kontext, nicht f&uuml;r Reviewer sichtbar"></textarea>
          </label>
          <div class="demo-access-actions">
            <button class="btn btn-accent" id="da-create-btn" type="submit">Code erstellen</button>
          </div>
        </form>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title">Zuletzt erstellt</span>
        </div>
        <div id="da-created-panel" aria-live="polite">
          <p class="demo-access-muted">Nach dem Erstellen wird der vollst&auml;ndige Code hier einmal angezeigt.</p>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <span class="card-title">Aktive und bisherige Codes</span>
        <button class="btn btn-sm" id="da-refresh" type="button">Aktualisieren</button>
      </div>
      <div class="table-wrap" id="da-table">
        ${Components.skeleton('100%', '260px')}
      </div>
    </div>
  `;

  const form = document.getElementById('da-create-form');
  const createBtn = document.getElementById('da-create-btn');
  const refreshBtn = document.getElementById('da-refresh');
  const errorEl = document.getElementById('da-error');
  const tableEl = document.getElementById('da-table');
  const createdPanel = document.getElementById('da-created-panel');

  function setError(message) {
    if (!message) {
      errorEl.style.display = 'none';
      errorEl.textContent = '';
      return;
    }
    errorEl.style.display = '';
    errorEl.textContent = message;
  }

  async function requestJson(url, options = {}) {
    let resp;
    try {
      resp = await fetch(url, options);
    } catch {
      throw new Error('Demo-Zugang API konnte nicht erreicht werden.');
    }
    const contentType = resp.headers.get('content-type') || '';
    let payload = null;
    let text = '';

    if (contentType.includes('application/json')) {
      try { payload = await resp.json(); } catch { payload = null; }
    } else {
      try { text = await resp.text(); } catch { text = ''; }
    }

    if (!resp.ok) {
      const err = new Error(_daErrorMessage(resp.status, payload, text));
      err.status = resp.status;
      err.payload = payload;
      throw err;
    }

    return payload || {};
  }

  async function loadCodes() {
    state.loading = true;
    setError('');
    tableEl.innerHTML = Components.skeleton('100%', '260px');

    try {
      const data = await requestJson('/api/demo-access/codes');
      state.demoPublicUrl = _daFirstString(data.demo_public_url, state.demoPublicUrl);
      state.codes = _daNormalizeCodes(data);
      renderCreatedPanel();
      renderTable();
    } catch (e) {
      state.codes = [];
      tableEl.innerHTML = '<p style="color:var(--error);padding:1rem">Codes konnten nicht geladen werden.</p>';
      setError(e.message || 'Demo-Code-Liste konnte nicht geladen werden.');
    } finally {
      state.loading = false;
    }
  }

  async function createCode(event) {
    event.preventDefault();
    if (state.creating) return;

    const payload = {
      label: document.getElementById('da-label').value.trim(),
      ttl_hours: parseInt(document.getElementById('da-ttl').value, 10),
      max_redemptions: Math.max(1, parseInt(document.getElementById('da-max-redemptions').value, 10) || 1),
      notes: document.getElementById('da-notes').value.trim(),
      created_by: document.getElementById('da-created-by').value.trim() || 'Sven',
    };

    state.creating = true;
    setError('');
    createBtn.disabled = true;
    createBtn.textContent = 'Erstelle...';

    try {
      const data = await requestJson('/api/demo-access/codes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      state.demoPublicUrl = _daFirstString(data.demo_public_url, state.demoPublicUrl);
      state.lastCreated = _daNormalizeCreated(data, payload, state.demoPublicUrl);
      renderCreatedPanel();
      Components.toast('Demo-Code erstellt', 'success');

      document.getElementById('da-label').value = '';
      document.getElementById('da-notes').value = '';
      document.getElementById('da-max-redemptions').value = '1';
      await loadCodes();
    } catch (e) {
      setError(e.message || 'Demo-Code konnte nicht erstellt werden.');
      Components.toast('Demo-Code konnte nicht erstellt werden', 'error');
    } finally {
      state.creating = false;
      createBtn.disabled = false;
      createBtn.textContent = 'Code erstellen';
    }
  }

  async function revokeCode(index, button) {
    const item = state.codes[index];
    if (!item || !item.revokeKey) return;

    const ok = await Components.confirm(
      'Demo-Code widerrufen',
      `Code ${_daEsc(item.displayCode)} wirklich widerrufen? Bereits eingeloggte Sessions k&ouml;nnen davon getrennt behandelt werden.`
    );
    if (!ok) return;

    button.disabled = true;
    button.textContent = 'Widerrufe...';
    setError('');

    try {
      await requestJson(`/api/demo-access/codes/${encodeURIComponent(item.revokeKey)}/revoke`, {
        method: 'POST',
      });
      Components.toast('Demo-Code widerrufen', 'warning');
      await loadCodes();
    } catch (e) {
      setError(e.message || 'Demo-Code konnte nicht widerrufen werden.');
      Components.toast('Widerruf fehlgeschlagen', 'error');
      button.disabled = false;
      button.textContent = 'Widerrufen';
    }
  }

  function renderCreatedPanel() {
    const item = state.lastCreated;
    if (!item || !item.code) {
      createdPanel.innerHTML = `
        <p class="demo-access-muted">Nach dem Erstellen wird der vollst&auml;ndige Code hier einmal angezeigt.</p>
        ${state.demoPublicUrl ? `<div class="demo-access-kv"><span>Demo-URL</span><code>${_daEsc(state.demoPublicUrl)}</code></div>` : ''}
      `;
      return;
    }

    const invitation = _daInvitationText(item.demoPublicUrl, item.code);
    createdPanel.innerHTML = `
      <div class="demo-access-result">
        <div class="demo-access-kv">
          <span>Code</span>
          <code class="demo-access-code">${_daEsc(item.code)}</code>
        </div>
        <div class="demo-access-kv">
          <span>Demo-URL</span>
          ${item.demoPublicUrl ? `<code>${_daEsc(item.demoPublicUrl)}</code>` : '<em>Nicht in der API-Antwort enthalten</em>'}
        </div>
        <div class="demo-access-kv">
          <span>L&auml;uft ab</span>
          <strong>${_daFormatDate(item.expiresAt)}</strong>
        </div>
        <div class="demo-access-copy-row">
          <button class="btn btn-sm" id="da-copy-code" type="button">Code kopieren</button>
          <button class="btn btn-sm" id="da-copy-invite" type="button" ${invitation ? '' : 'disabled'}>Einladung kopieren</button>
        </div>
      </div>
    `;

    const copyCodeBtn = document.getElementById('da-copy-code');
    const copyInviteBtn = document.getElementById('da-copy-invite');
    copyCodeBtn.addEventListener('click', () => Components.copyToClipboard(item.code, copyCodeBtn));
    copyInviteBtn.addEventListener('click', () => {
      if (invitation) Components.copyToClipboard(invitation, copyInviteBtn);
    });
  }

  function renderTable() {
    if (!state.codes.length) {
      tableEl.innerHTML = '<p style="color:var(--text-muted);padding:1rem">Noch keine Demo-Codes gefunden.</p>';
      return;
    }

    tableEl.innerHTML = `<table class="demo-access-table"><thead><tr>
      <th>Code</th>
      <th>Bezeichnung</th>
      <th>Status</th>
      <th>L&auml;uft ab</th>
      <th>Einl&ouml;sungen</th>
      <th>Erstellt von</th>
      <th>Notizen</th>
      <th></th>
    </tr></thead><tbody>${state.codes.map((item, index) => `<tr>
      <td><code>${_daEsc(item.displayCode)}</code></td>
      <td>${_daEsc(item.label || '--')}</td>
      <td>${_daStatusBadge(item.status)}</td>
      <td style="white-space:nowrap">${_daFormatDate(item.expiresAt)}</td>
      <td style="font-family:var(--font-mono)">${item.redemptionCount} / ${item.maxRedemptions || '--'}</td>
      <td>${_daEsc(item.createdBy || '--')}</td>
      <td class="demo-access-notes">${_daEsc(item.notes || '')}</td>
      <td>${item.status === 'active' && item.revokeKey
        ? `<button class="btn btn-sm btn-danger da-revoke-btn" type="button" data-index="${index}">Widerrufen</button>`
        : '<span style="color:var(--text-muted);font-size:0.75rem">--</span>'}
      </td>
    </tr>`).join('')}</tbody></table>`;

    tableEl.querySelectorAll('.da-revoke-btn').forEach(btn => {
      btn.addEventListener('click', () => revokeCode(parseInt(btn.dataset.index, 10), btn));
    });
  }

  form.addEventListener('submit', createCode);
  refreshBtn.addEventListener('click', loadCodes);

  loadCodes();

  return () => {
    state.lastCreated = null;
    state.codes = [];
  };
};

function _daNormalizeCodes(data) {
  const rows = Array.isArray(data)
    ? data
    : Array.isArray(data.codes)
      ? data.codes
      : Array.isArray(data.items)
        ? data.items
        : [];

  return rows
    .filter(row => row && typeof row === 'object')
    .map(_daNormalizeCode);
}

function _daNormalizeCode(row) {
  const code = _daFirstString(row.code, row.full_code, row.access_code, row.token);
  const prefix = _daFirstString(row.code_prefix, row.prefix, row.token_prefix);
  const redemptionCount = _daNumber(row.redemption_count, row.redemptions, row.used_count, row.uses, 0);
  const maxRedemptions = _daNumber(row.max_redemptions, row.maxRedemptions, row.redemption_limit, row.max_uses, 0);
  const expiresAt = _daFirstString(row.expires_at, row.expiresAt, row.expiry, row.expires);
  const status = _daStatus(row, redemptionCount, maxRedemptions, expiresAt);
  const revokeKey = _daFirstString(row.code, row.full_code, row.access_code, row.code_prefix, row.prefix, row.token_prefix);

  return {
    displayCode: prefix || _daMaskCode(code) || '--',
    revokeKey,
    label: _daFirstString(row.label, row.name, row.title),
    status,
    expiresAt,
    redemptionCount,
    maxRedemptions,
    notes: _daFirstString(row.notes, row.note),
    createdBy: _daFirstString(row.created_by, row.createdBy, row.creator),
  };
}

function _daNormalizeCreated(data, payload, fallbackUrl) {
  const code = _daFirstString(data.code, data.full_code, data.access_code, data.token);
  return {
    code,
    demoPublicUrl: _daFirstString(data.demo_public_url, data.public_url, fallbackUrl),
    expiresAt: _daFirstString(data.expires_at, data.expiresAt, data.expiry, data.expires),
    maxRedemptions: _daNumber(data.max_redemptions, data.maxRedemptions, payload.max_redemptions, 1),
  };
}

function _daStatus(row, redemptionCount, maxRedemptions, expiresAt) {
  const direct = _daFirstString(row.status, row.state).toLowerCase();
  if (['active', 'used', 'expired', 'revoked'].includes(direct)) return direct;
  if (direct === 'redeemed') return 'used';
  if (direct === 'disabled') return 'revoked';
  if (row.revoked || row.revoked_at) return 'revoked';
  if (expiresAt && new Date(expiresAt).getTime() < Date.now()) return 'expired';
  if (maxRedemptions > 0 && redemptionCount >= maxRedemptions) return 'used';
  return 'active';
}

function _daStatusBadge(status) {
  const map = {
    active: ['badge-success', 'Aktiv'],
    used: ['badge-info', 'Eingel&ouml;st'],
    expired: ['badge-warning', 'Abgelaufen'],
    revoked: ['badge-error', 'Widerrufen'],
  };
  const [cls, label] = map[status] || ['badge-info', status || 'Unbekannt'];
  return `<span class="badge ${cls}">${map[status] ? label : _daEsc(label)}</span>`;
}

function _daErrorMessage(status, payload, text) {
  const errorCode = payload && payload.error;
  if (status === 503 && errorCode === 'admin_disabled') {
    return 'Demo-Code-Verwaltung ist nicht konfiguriert. DEMO_SITE_ADMIN_TOKEN fehlt im Control Center.';
  }

  if (status === 502) {
    return 'Demo-Site ist nicht erreichbar. Bitte Demo-Site und Control-Center-Konfiguration pr\u00fcfen.';
  }

  const detail = payload && (payload.message || payload.detail || payload.error);
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }
  if (Array.isArray(detail) && detail.length) {
    return 'Die Anfrage wurde vom Backend abgelehnt.';
  }
  if (text && text.trim()) {
    return text.trim().slice(0, 180);
  }
  return `Anfrage fehlgeschlagen (HTTP ${status}).`;
}

function _daInvitationText(url, code) {
  if (!url || !code) return '';
  return `Hier ist der Demo-Link: ${url}
Zugangscode: ${code}
Der Code ist zeitlich begrenzt und nur f\u00fcr die Demo gedacht.`;
}

function _daFirstString(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function _daNumber(...values) {
  const fallback = values[values.length - 1];
  for (const value of values.slice(0, -1)) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
  return fallback;
}

function _daMaskCode(code) {
  if (!code) return '';
  if (code.length <= 8) return `${code.slice(0, 3)}...`;
  return `${code.slice(0, 4)}...${code.slice(-4)}`;
}

function _daFormatDate(iso) {
  if (!iso) return '--';
  try {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleString('de-DE', {
      dateStyle: 'short',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

function _daEsc(value) {
  const d = document.createElement('div');
  d.textContent = value == null ? '' : String(value);
  return d.innerHTML;
}
