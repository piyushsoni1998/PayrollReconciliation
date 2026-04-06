/* ═══════════════════════════════════════════════════════════════════
   history.js — Reconciliation History page logic
   Handles: list all runs, filter, load full results from a record
   ═══════════════════════════════════════════════════════════════════ */

let _allRuns       = [];
let _histTabFilter = 'all';   // 'all' | 'clean' | 'var'

// ── Helpers ───────────────────────────────────────────────────────────────
const _fmtAmt = v => `$${Math.abs(v || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function _statusBadge(s) {
  if (s.is_clean) return `<span class="hist-badge hist-badge-clean">CLEAN</span>`;
  const n = s.variances || 0;
  return `<span class="hist-badge hist-badge-var">${n} VARIANCE${n === 1 ? '' : 'S'}</span>`;
}

// ── Recent runs panel on Upload page ─────────────────────────────────────
async function loadRecentRuns() {
  const bodyEl  = document.getElementById('recent-recon-body');
  const countEl = document.getElementById('recent-recon-count');
  if (!bodyEl) return;

  bodyEl.innerHTML = '<div class="recent-recon-loading">Loading recent runs…</div>';
  if (countEl) countEl.style.display = 'none';

  try {
    const uid  = state.auth?.userId ? `&user_id=${enc(state.auth.userId)}` : '';
    const res  = await fetch(`${API}/api/recon-history?limit=5${uid}`);
    const data = await res.json();

    if (!data.ok || !data.runs?.length) {
      bodyEl.innerHTML = '<div class="recent-recon-empty">No previous reconciliations found. Complete a run and it will appear here.</div>';
      return;
    }

    const runs  = data.runs.slice(0, 5);
    const total = data.runs.length;
    if (countEl) { countEl.textContent = `${total} total`; countEl.style.display = 'inline'; }

    const rows = runs.map(r => {
      const s      = r.summary_stats || {};
      const viewBtn = r._id
        ? `<button class="btn btn-blue btn-sm" style="font-size:11px;padding:3px 10px" onclick="viewHistoryRecord('${esc(r._id)}')">View</button>`
        : `<span style="font-size:11px;color:var(--text-3)">—</span>`;
      return `<tr>
        <td style="width:8px;padding-left:16px"><span class="rr-dot ${s.is_clean ? 'ok' : 'var'}"></span></td>
        <td class="rr-client">${esc(r.client_name || '—')}</td>
        <td>${esc(r.period_label || '—')}</td>
        <td>${_statusBadge(s)}</td>
        <td style="color:var(--text-2);font-variant-numeric:tabular-nums">${(s.total_lines || 0).toLocaleString()} lines &nbsp;·&nbsp; ${_fmtAmt(s.total_variance)}</td>
        <td class="rr-date">${esc(r.created_at || '')}</td>
        <td style="text-align:right;padding-right:16px">${viewBtn}</td>
      </tr>`;
    }).join('');

    bodyEl.innerHTML = `<table class="recent-recon-table">
      <thead><tr>
        <th style="width:8px;padding-left:16px"></th>
        <th>Client</th><th>Period</th><th>Status</th><th>Summary</th><th>Date</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;

  } catch (e) {
    bodyEl.innerHTML = `<div class="recent-recon-empty">Could not load history: ${esc(e.message)}</div>`;
  }
}

// ── Tab filter ────────────────────────────────────────────────────────────
function setHistTab(tab) {
  _histTabFilter = tab;
  ['all', 'clean', 'var'].forEach(t => {
    document.getElementById(`hist-tab-${t}`)?.classList.toggle('active', t === tab);
  });
  _applyFilters();
}

// ── Load & render history list ────────────────────────────────────────────
function _setupHistoryAuthUI(signedIn) {
  const promptEl = document.getElementById('history-signin-prompt');
  const subEl    = document.getElementById('history-page-sub');
  if (promptEl) promptEl.style.display = signedIn ? 'none' : 'flex';
  if (subEl) {
    subEl.textContent = signedIn
      ? `Showing your runs — signed in as ${state.auth.displayName || state.auth.username}`
      : 'All past reconciliation runs saved in the database.';
  }
}

async function loadHistory() {
  const listEl   = document.getElementById('history-list');
  const emptyEl  = document.getElementById('history-empty');
  const noDbEl   = document.getElementById('history-no-db');
  const statsBar = document.getElementById('hist-stats-bar');
  if (!listEl) return;

  const signedIn = !!state.auth?.userId;
  _setupHistoryAuthUI(signedIn);

  listEl.innerHTML = '<div class="hist-loading">Loading…</div>';
  if (emptyEl)  emptyEl.style.display  = 'none';
  if (noDbEl)   noDbEl.style.display   = 'none';
  if (statsBar) statsBar.style.display = 'none';

  try {
    const uid = signedIn ? `&user_id=${enc(state.auth.userId)}` : '';
    const res  = await fetch(`${API}/api/recon-history?limit=200${uid}`);
    const data = await res.json();

    if (!data.ok) {
      listEl.innerHTML = '';
      if (noDbEl) noDbEl.style.display = 'flex';
      setPill('nav-pill-history', false);
      return;
    }

    _allRuns = data.runs || [];
    setPill('nav-pill-history', _allRuns.length > 0);
    _updateHistStats(_allRuns);
    if (statsBar && _allRuns.length) statsBar.style.display = 'flex';
    _applyFilters();

  } catch (e) {
    listEl.innerHTML = `<div class="alert alert-error show">Could not load history: ${esc(e.message)}</div>`;
  }
}

function _updateHistStats(runs) {
  const clean = runs.filter(r => r.summary_stats?.is_clean).length;
  const lines = runs.reduce((sum, r) => sum + (r.summary_stats?.total_lines || 0), 0);
  const el = id => document.getElementById(id);
  if (el('hstat-total')) el('hstat-total').textContent = runs.length.toLocaleString();
  if (el('hstat-clean')) el('hstat-clean').textContent = clean.toLocaleString();
  if (el('hstat-var'))   el('hstat-var').textContent   = (runs.length - clean).toLocaleString();
  if (el('hstat-lines')) el('hstat-lines').textContent = lines.toLocaleString();
}

function filterHistory(query) {
  _applyFilters(query);
}

function _applyFilters(queryOverride) {
  const q = (queryOverride !== undefined
    ? queryOverride
    : document.getElementById('history-search')?.value || ''
  ).toLowerCase().trim();

  let filtered = _allRuns;
  if (_histTabFilter === 'clean') filtered = filtered.filter(r => r.summary_stats?.is_clean);
  if (_histTabFilter === 'var')   filtered = filtered.filter(r => r.summary_stats?.is_clean !== true);
  if (q) filtered = filtered.filter(r =>
    (r.client_name  || '').toLowerCase().includes(q) ||
    (r.period_label || '').toLowerCase().includes(q)
  );

  const countEl = document.getElementById('history-count');
  if (countEl) countEl.textContent = `${filtered.length} record${filtered.length === 1 ? '' : 's'}`;
  renderHistoryList(filtered);
}

function renderHistoryList(runs) {
  const listEl  = document.getElementById('history-list');
  const emptyEl = document.getElementById('history-empty');
  if (!listEl) return;

  if (!runs.length) {
    listEl.innerHTML = '';
    if (emptyEl) emptyEl.style.display = 'flex';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  const rows = runs.map((r, i) => _renderHistRow(r, i)).join('');
  listEl.innerHTML = `
    <table class="hist-table">
      <thead>
        <tr class="hist-thead-row">
          <th class="hist-th" style="width:100px">Status</th>
          <th class="hist-th">Client</th>
          <th class="hist-th">Period</th>
          <th class="hist-th hist-th-num">Total Lines</th>
          <th class="hist-th hist-th-num">Matched</th>
          <th class="hist-th hist-th-num">Variances</th>
          <th class="hist-th hist-th-num">Variance Amt</th>
          <th class="hist-th">Source Files</th>
          <th class="hist-th">Run Date</th>
          <th class="hist-th hist-th-act"></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function _fileRowHtml(tag, name, rowCount) {
  const countSpan = rowCount ? `<span class="hist-file-rows">${rowCount.toLocaleString()}</span>` : '';
  return `<div class="hist-file-row"><span class="hist-file-tag">${tag}</span><span class="hist-file-name">${esc(name)}</span>${countSpan}</div>`;
}

function _renderHistRow(run, idx) {
  const s        = run.summary_stats || {};
  const varColor = s.variances > 0 ? 'var(--red-text)' : 'var(--green-text)';
  const amtColor = s.is_clean ? 'var(--green-text)' : 'var(--red-text)';

  const glInfo = run.gl_filename ? _fileRowHtml('GL', run.gl_filename, run.gl_row_count) : '';
  const prInfo = run.pr_filename ? _fileRowHtml('PR', run.pr_filename, run.pr_row_count) : '';

  const viewBtn = run._id
    ? `<button class="hist-act-btn hist-act-view" onclick="viewHistoryRecord('${esc(run._id)}')">View Results</button>`
    : '';
  const newBtn = `<button class="hist-act-btn hist-act-new" onclick="startNewReconForClient('${esc(run.client_name || '')}', '${esc(run.period_label || '')}')">New Run</button>`;

  const stripeCls = idx % 2 === 0 ? '' : ' hist-tr-alt';

  return `<tr class="hist-tr${stripeCls}">
    <td class="hist-td">${_statusBadge(s)}</td>
    <td class="hist-td hist-td-client">${esc(run.client_name || '—')}</td>
    <td class="hist-td">${esc(run.period_label || '—')}</td>
    <td class="hist-td hist-td-num">${(s.total_lines || 0).toLocaleString()}</td>
    <td class="hist-td hist-td-num" style="color:var(--green-text)">${(s.matched || 0).toLocaleString()}</td>
    <td class="hist-td hist-td-num" style="color:${varColor}">${(s.variances || 0).toLocaleString()}</td>
    <td class="hist-td hist-td-num hist-td-amt" style="color:${amtColor}">${_fmtAmt(s.total_variance)}</td>
    <td class="hist-td hist-td-files">${glInfo}${prInfo}</td>
    <td class="hist-td hist-td-date">${esc(run.created_at || '—')}</td>
    <td class="hist-td hist-td-act">${viewBtn}${newBtn}</td>
  </tr>`;
}

// ── Load and display a specific history record ────────────────────────────
async function viewHistoryRecord(recordId) {
  showLoading('Loading historical results…');
  try {
    const res  = await fetch(`${API}/api/recon-history/${enc(recordId)}`);
    const data = await res.json();
    hideLoading();

    if (!data.ok || !data.record) {
      showGlobalError('Could not load this record.');
      return;
    }

    const rec = data.record;
    const rd  = rec.result_data || {};

    // Populate state with history data so results page renders correctly
    state.results = {
      summary_stats: rec.summary_stats,
      recon_table:   rd.recon_table,
      gl_pivot:      rd.gl_pivot,
      pr_pivot:      rd.pr_pivot,
      unmapped_gl:   rd.unmapped_gl || [],
      unmapped_pr:   rd.unmapped_pr || [],
    };
    // Store the history record ID so downloadExcel() uses the history endpoint
    state._historyRecordId = recordId;

    // Navigate to results page and render
    navigate('results');
    renderResults(state.results);
    document.getElementById('results-section').style.display = 'block';
    document.getElementById('new-recon-bar').style.display = 'flex';

    // Update download meta
    const meta = document.getElementById('download-meta');
    if (meta) {
      const parts = [];
      if (rec.client_name && rec.client_name !== 'default') parts.push(`Client: ${rec.client_name}`);
      if (rec.period_label) parts.push(`Period: ${rec.period_label}`);
      parts.push(`Viewed from history · ${rec.created_at}`);
      meta.textContent = parts.join('  ·  ');
    }

    updateDashboard();
  } catch (e) {
    hideLoading();
    showGlobalError(`Error loading record: ${e.message}`);
  }
}

// ── Start a new run pre-filling client name ───────────────────────────────
function startNewReconForClient(clientName, periodLabel) {
  // Pre-fill client/period inputs
  const clientInput = document.getElementById('cfg-client');
  const periodInput = document.getElementById('cfg-period');
  if (clientInput && clientName) {
    clientInput.value = clientName;
    localStorage.setItem('pr_client_name', clientName);
  }
  if (periodInput && periodLabel) {
    periodInput.value = '';  // Let user pick new period
  }
  startNewReconciliation();
}
