/* ═══════════════════════════════════════════════════════════════════
   results.js — Run & Results page logic
   Handles: preflight check, run reconciliation, render tables, download
   ═══════════════════════════════════════════════════════════════════ */

// ── Pre-flight checklist ──────────────────────────────────────────────────
function updatePreflight() {
  const list = document.getElementById('preflight-list');
  if (!list) return;

  const items = [
    {
      ok:     state.confirmed['gl_report'],
      warn:   !!state.files['gl_report'] && !state.confirmed['gl_report'],
      label:  'GL Report',
      detail: state.confirmed['gl_report']
        ? `${state.uploadData['gl_report']?.row_count?.toLocaleString() || ''} rows · ${state.uploadData['gl_report']?.filename || ''}`
        : (state.files['gl_report'] ? 'Uploaded — confirm column mapping to proceed' : 'Not yet uploaded'),
      badge:  state.confirmed['gl_report'] ? 'Ready' : (state.files['gl_report'] ? 'Pending' : 'Missing'),
      icon:   state.confirmed['gl_report'] ? '✓' : (state.files['gl_report'] ? '⚠' : '↑'),
    },
    {
      ok:     state.confirmed['payroll_register'],
      warn:   !!state.files['payroll_register'] && !state.confirmed['payroll_register'],
      label:  'Payroll Register',
      detail: state.confirmed['payroll_register']
        ? `${state.uploadData['payroll_register']?.row_count?.toLocaleString() || ''} rows · ${state.uploadData['payroll_register']?.filename || ''}`
        : (state.files['payroll_register'] ? 'Uploaded — confirm column mapping to proceed' : 'Not yet uploaded'),
      badge:  state.confirmed['payroll_register'] ? 'Ready' : (state.files['payroll_register'] ? 'Pending' : 'Missing'),
      icon:   state.confirmed['payroll_register'] ? '✓' : (state.files['payroll_register'] ? '⚠' : '↑'),
    },
    {
      ok:     state.configSaved || state.mappingRows.length > 0,
      warn:   !state.configSaved && state.mappingRows.length > 0,
      label:  'Reconciliation Configuration',
      detail: state.configSaved
        ? `${state.mappingRows.length} mapping rows saved for "${getClient()}"`
        : (state.mappingRows.length > 0
          ? `${state.mappingRows.length} rows loaded (unsaved) — save in Configuration to persist`
          : 'No configuration loaded — go to Configuration page'),
      badge:  state.configSaved ? 'Saved' : (state.mappingRows.length > 0 ? 'Unsaved' : 'Missing'),
      icon:   state.configSaved ? '✓' : (state.mappingRows.length > 0 ? '⚠' : '⚙'),
    },
  ];

  list.innerHTML = items.map(item => {
    const cls      = item.ok ? 'pf-ok' : (item.warn ? 'pf-warn' : 'pf-err');
    const badgeCls = item.ok ? 'ok'    : (item.warn ? 'warn'    : 'err');
    return `<li class="preflight-item ${cls}">
      <div class="pf-icon-wrap">${item.icon}</div>
      <div class="pf-text">
        <div class="pf-label">${esc(item.label)}</div>
        <div class="pf-detail">${esc(item.detail)}</div>
      </div>
      <span class="pf-badge ${badgeCls}">${item.badge}</span>
    </li>`;
  }).join('');

  const allReady = state.confirmed['gl_report'] && state.confirmed['payroll_register'] &&
                   (state.configSaved || state.mappingRows.length > 0);
  const runBtn = document.getElementById('run-btn');
  if (runBtn) runBtn.disabled = !allReady;
}

// ── Run reconciliation ────────────────────────────────────────────────────
async function runReconciliation() {
  const errEl = document.getElementById('run-error');
  errEl.classList.remove('show');
  showLoading('Running reconciliation…');

  try {
    const res  = await fetch(`${API}/api/run`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        session_id:   state.sessionId,
        client_name:  getClient(),
        period_label: document.getElementById('cfg-period').value.trim(),
        user_id:      state.auth?.userId || null,
      }),
    });
    const data = await res.json();
    hideLoading();

    if (!res.ok || !data.ok) {
      // Specific guidance for wrong GL column mapping
      const detail = data.detail || {};
      if (typeof detail === 'object' && detail.error === 'wrong_gl_column') {
        errEl.innerHTML =
          `<strong>⚠ Wrong GL Code column selected</strong><br>${esc(detail.message)}<br>` +
          `<em>Go to <strong>Upload Files</strong> tab → re-confirm GL Report column mapping → ` +
          `select the column with 4-5 digit account codes.</em>`;
      } else {
        errEl.textContent = (typeof detail === 'string' ? detail : JSON.stringify(detail)) || 'Reconciliation failed.';
      }
      errEl.classList.add('show');
      return;
    }

    state.results = data;
    renderResults(data);
    populatePeriodFilter(data.available_date_range);
    document.getElementById('results-section').style.display = 'block';
    document.getElementById('new-recon-bar').style.display = 'flex';
    showDownloadBar();
    updateDashboard();
    loadRecentRuns();  // refresh recent panel so new run appears
  } catch (e) {
    hideLoading();
    errEl.textContent = `Error: ${e.message}`;
    errEl.classList.add('show');
  }
}

// ── Period filter (From month-year → To month-year) ───────────────────────
const _MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function populatePeriodFilter(dateRange) {
  const bar = document.getElementById('period-filter-bar');
  if (!bar) return;
  if (!dateRange || !dateRange.min || !dateRange.max) {
    bar.style.display = 'none';
    return;
  }

  const [minYr, minMo] = dateRange.min.split('-').map(Number);
  const [maxYr, maxMo] = dateRange.max.split('-').map(Number);

  // Build year options spanning min→max
  const years = [];
  for (let y = minYr; y <= maxYr; y++) years.push(y);
  const yearOpts = years.map(y => `<option value="${y}">${y}</option>`).join('');

  const fromYear = document.getElementById('pf-from-year');
  const toYear   = document.getElementById('pf-to-year');
  if (!fromYear || !toYear) return;

  fromYear.innerHTML = yearOpts;
  toYear.innerHTML   = yearOpts;

  // Default: from = min date of data, to = max date of data
  document.getElementById('pf-from-month').value = String(minMo).padStart(2, '0');
  fromYear.value = minYr;
  document.getElementById('pf-to-month').value   = String(maxMo).padStart(2, '0');
  toYear.value   = maxYr;

  bar.style.display = 'flex';
  const badge = document.getElementById('period-filter-badge');
  if (badge) badge.textContent = '';
}

async function applyPeriodFilter() {
  const fromMonth = document.getElementById('pf-from-month')?.value;
  const fromYear  = document.getElementById('pf-from-year')?.value;
  const toMonth   = document.getElementById('pf-to-month')?.value;
  const toYear    = document.getElementById('pf-to-year')?.value;
  if (!fromYear || !toYear) return;

  const periodStart = `${fromYear}-${fromMonth}`;
  const periodEnd   = `${toYear}-${toMonth}`;
  const badge = document.getElementById('period-filter-badge');

  const fromLabel = `${_MONTH_NAMES[parseInt(fromMonth) - 1]} ${fromYear}`;
  const toLabel   = `${_MONTH_NAMES[parseInt(toMonth)   - 1]} ${toYear}`;
  const rangeLabel = fromLabel === toLabel ? fromLabel : `${fromLabel} – ${toLabel}`;

  showLoading(`Filtering ${rangeLabel}…`);
  try {
    const res = await fetch(`${API}/api/run`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        session_id:   state.sessionId,
        client_name:  getClient(),
        period_label: document.getElementById('cfg-period').value.trim(),
        period_start: periodStart,
        period_end:   periodEnd,
        user_id:      state.auth?.userId || null,
      }),
    });
    const data = await res.json();
    hideLoading();
    if (!res.ok || !data.ok) {
      if (badge) badge.textContent = 'Filter failed';
      return;
    }
    state.results = data;
    renderResults(data);
    if (badge) badge.textContent = `Showing ${rangeLabel}`;
    updateDashboard();
  } catch (e) {
    hideLoading();
    if (badge) badge.textContent = `Error: ${e.message}`;
  }
}

async function clearPeriodFilter() {
  const badge = document.getElementById('period-filter-badge');
  if (badge) badge.textContent = '';
  showLoading('Loading all data…');
  try {
    const res = await fetch(`${API}/api/run`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        session_id:   state.sessionId,
        client_name:  getClient(),
        period_label: document.getElementById('cfg-period').value.trim(),
        user_id:      state.auth?.userId || null,
      }),
    });
    const data = await res.json();
    hideLoading();
    if (!res.ok || !data.ok) return;
    state.results = data;
    renderResults(data);
    updateDashboard();
  } catch (e) {
    hideLoading();
  }
}

// ── Download Excel ────────────────────────────────────────────────────────
async function downloadExcel() {
  // When viewing a historical record, use the dedicated history download endpoint
  const url = state._historyRecordId
    ? `${API}/api/download-history/${enc(state._historyRecordId)}`
    : (() => {
        if (!state.sessionId) { alert('No active session. Please run reconciliation first.'); return null; }
        const period = enc(document.getElementById('cfg-period').value.trim());
        return `${API}/api/download?session_id=${enc(state.sessionId)}&period_label=${period}`;
      })();
  if (!url) return;
  try {
    const resp = await fetch(url);
    if (!resp.ok) { alert('Download failed: ' + await resp.text()); return; }
    const blob    = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const cd      = resp.headers.get('Content-Disposition') || '';
    const match   = cd.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : 'Payroll_Recon.xlsx';
    const a = document.createElement('a');
    a.href = blobUrl; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(blobUrl);
  } catch (e) { alert('Download error: ' + e.message); }
}

function showDownloadBar() {
  const meta   = document.getElementById('download-meta');
  if (!meta) return;
  const client = getClient();
  const period = document.getElementById('cfg-period')?.value?.trim();
  const parts  = [];
  if (client && client.toLowerCase() !== 'default') parts.push(`Client: ${client}`);
  if (period) parts.push(`Period: ${period}`);
  meta.textContent = parts.join('  ·  ');
}

// ── Render all result sections ────────────────────────────────────────────
function renderResults(data) {
  renderFilterErrorBanner(data.filter_error);
  renderStatusBanner(data.summary_stats);
  renderSummaryMetrics(data.summary_stats);
  renderReconGrouped('recon-table', data.recon_table);
  renderCombinedPivot(data.gl_pivot, data.pr_pivot, data.recon_table);
  renderResultTable('gl-pivot-table', data.gl_pivot,  false);
  renderResultTable('pr-pivot-table', data.pr_pivot,  false);
  renderUnmapped(data.unmapped_gl, data.unmapped_pr);
}

function renderFilterErrorBanner(err) {
  const el = document.getElementById('filter-error-banner');
  if (!el) return;
  if (!err) { el.style.display = 'none'; return; }

  const samples = (err.sample_dates || []).join(', ') || 'N/A';
  el.innerHTML = `
    <div class="feb-title">⛔ Date Filter Failed — Results Include All Years of GL Data</div>
    <div>
      Your GL file contains data from <strong>${esc(err.gl_data_range || '')}</strong>,
      but the period filter to <strong>${esc(err.period_requested || '')}</strong> could not be applied
      because the date column <strong>"${esc(err.date_col || '')}"</strong> format was not recognised.
      All <strong>${(err.rows_affected || 0).toLocaleString()}</strong> GL rows are included —
      this means GL amounts reflect multiple years, not just the selected period.
    </div>
    <div class="feb-detail">Sample date values from GL file: ${esc(samples)}</div>
    <div class="feb-action">
      To fix: ensure the GL export date column contains standard dates (MM/DD/YYYY, YYYY-MM-DD, DD-Mon-YYYY, etc.)
      and re-upload. Until then, do not rely on these filtered results.
    </div>`;
  el.style.display = 'block';
}

function renderStatusBanner(stats) {
  const el = document.getElementById('results-status-banner');
  if (!el || !stats) return;
  const isClean = stats.is_clean;
  const fmtAmt  = v => `$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const glOnlyNote = stats.gl_only_lines > 0
    ? ` · ${stats.gl_only_lines} GL-Only (informational)`
    : '';
  if (isClean) {
    el.innerHTML = `<div class="results-status-banner rsb-clean">
      <span class="rsb-icon">✓</span>
      <div class="rsb-text">
        <div class="rsb-title">Reconciliation Clean</div>
        <div class="rsb-sub">${stats.matched} of ${stats.total_lines} lines matched · No variances found${glOnlyNote}</div>
      </div>
    </div>`;
  } else {
    el.innerHTML = `<div class="results-status-banner rsb-variance">
      <span class="rsb-icon">⚠</span>
      <div class="rsb-text">
        <div class="rsb-title">${stats.variances} Variance${stats.variances !== 1 ? 's' : ''} Found</div>
        <div class="rsb-sub">Total variance: ${fmtAmt(stats.total_variance)} · ${stats.matched} matched · ${stats.total_lines} total lines${glOnlyNote}</div>
      </div>
    </div>`;
  }
}

function renderSummaryMetrics(stats) {
  if (!stats) return;
  const el     = document.getElementById('summary-metrics');
  const fmtAmt = v => `$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  el.innerHTML = `
    <div class="metric-tile">
      <div class="metric-val" data-count="${stats.total_lines}">0</div>
      <div class="metric-label">Total Lines</div>
    </div>
    <div class="metric-tile ok">
      <div class="metric-val" data-count="${stats.matched}">0</div>
      <div class="metric-label">✓ Matched</div>
    </div>
    <div class="metric-tile ${stats.variances > 0 ? 'warn' : 'ok'}">
      <div class="metric-val" data-count="${stats.variances}">0</div>
      <div class="metric-label">⚠ Variances</div>
    </div>
    <div class="metric-tile ${stats.is_clean ? 'ok' : 'warn'}">
      <div class="metric-val">${fmtAmt(stats.total_variance)}</div>
      <div class="metric-label">${stats.is_clean ? '✓ Clean' : '⚠ Variance Amount'}</div>
    </div>`;

  // Animate counters
  el.querySelectorAll('.metric-val[data-count]').forEach(el => {
    const target = parseInt(el.dataset.count, 10);
    if (!target) { el.textContent = '0'; return; }
    const steps = 30, interval = 600 / steps;
    let step = 0;
    const timer = setInterval(() => {
      step++;
      el.textContent = Math.round(target * (step / steps));
      if (step >= steps) { el.textContent = target; clearInterval(timer); }
    }, interval);
  });

  // Period warning + year filter info
  const diag   = stats.diagnostics || {};
  const warnEl = document.getElementById('period-warning');
  if (warnEl) {
    const parts = [];
    if (diag.period_start || diag.period_end) {
      const fmt = ym => {
        if (!ym) return '?';
        const [y, m] = ym.split('-');
        return `${_MONTH_NAMES[parseInt(m) - 1]} ${y}`;
      };
      const rangeLabel = (diag.period_start === diag.period_end)
        ? fmt(diag.period_start)
        : `${fmt(diag.period_start)} – ${fmt(diag.period_end)}`;

      const glStatus = diag.gl_filter_skipped
        ? ` · ⚠ GL filter skipped (date format not recognised — ${(diag.gl_rows_total || 0).toLocaleString()} rows used)`
        : ` · ${(diag.gl_rows_used || 0).toLocaleString()} GL rows`;
      const prStatus = diag.pr_filter_skipped
        ? ` · ⚠ PR filter skipped (date format not recognised — ${(diag.pr_rows_total || 0).toLocaleString()} rows used)`
        : ` · ${(diag.pr_rows_used || 0).toLocaleString()} PR rows`;

      parts.push(`📅 Period: ${rangeLabel}${glStatus}${prStatus}`);
    }
    if (diag.period_warning) parts.push('⚠ ' + diag.period_warning);

    if (parts.length) {
      warnEl.innerHTML = parts.join('<br>');
      warnEl.style.display = 'block';
    } else {
      warnEl.style.display = 'none';
    }
  }
}

function renderReconGrouped(elId, tableData) {
  const el = document.getElementById(elId);
  if (!el || !tableData) return;

  const cols    = tableData.columns || [];
  const stepIdx = cols.findIndex(c => /reconciliation.?step/i.test(c));
  const amtCols = new Set();
  cols.forEach((c, i) => {
    if (/amount|amt|earn|bene|deduc|tax|net|variance|balance/i.test(c)) amtCols.add(i);
  });

  let lastStep = null;
  const rows = (tableData.rows || []).map(row => {
    const step    = stepIdx >= 0 ? String(row[stepIdx] || '') : '';
    const status  = String(row[row.length - 2] || '');
    const isTotal = step.toUpperCase() === 'TOTAL';
    const isMatch = status.includes('Match');
    const isVar   = status.includes('Variance') || status.includes('No PR');
    let html = '';

    if (!isTotal && step && step !== lastStep) {
      html += `<tr class="row-step-hdr"><td colspan="${cols.length}">${esc(step)}</td></tr>`;
      lastStep = step;
    }
    const cls   = isTotal ? 'row-total' : isMatch ? 'row-match' : isVar ? 'row-var' : '';
    const cells = row.map((val, i) => {
      const isNum = amtCols.has(i) && val !== '' && !isNaN(parseFloat(String(val).replace(/,/g, '')));
      const fmt   = isNum
        ? parseFloat(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : esc(val);
      return `<td class="${isNum ? 'num' : ''}">${fmt}</td>`;
    }).join('');
    html += `<tr class="${cls}">${cells}</tr>`;
    return html;
  }).join('');

  el.innerHTML = `<div class="result-wrap">
    <table class="result-table">
      <thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

function renderCombinedPivot(glPivot, prPivot, reconTable) {
  const el = document.getElementById('combined-pivot');
  if (!el) return;
  if (!glPivot || !prPivot) { el.innerHTML = ''; return; }

  // Build {glCode → status} from recon table for GLOnly detection
  const _reconStatus = {};
  if (reconTable) {
    const rCols = reconTable.columns || [];
    const rCodeIdx   = rCols.findIndex(c => /^gl[\s_-]?code$/i.test(c));
    const rStatusIdx = rCols.findIndex(c => /^status$/i.test(c));
    if (rCodeIdx >= 0 && rStatusIdx >= 0) {
      (reconTable.rows || []).forEach(r => {
        const code = String(r[rCodeIdx] || '').trim();
        if (code) _reconStatus[code] = String(r[rStatusIdx] || '');
      });
    }
  }

  const glCols   = glPivot.columns || [];
  const glRows   = glPivot.rows   || [];
  const gRMIdx   = glCols.findIndex(c => /reconciliation.?mapping/i.test(c));
  const gCodeIdx = glCols.findIndex(c => /^gl[\s_-]?code$/i.test(c));
  const gTitIdx  = glCols.findIndex(c => /gl[\s_-]?title/i.test(c));
  const gNetIdx  = glCols.findIndex(c => /sum.*net|net.*amount/i.test(c));

  const prCols    = prPivot.columns || [];
  const prRows    = prPivot.rows    || [];
  const prRMIdx   = prCols.findIndex(c => /reconciliation.?mapping/i.test(c));
  const prAmtIdxs = new Set();
  prCols.forEach((c, i) => { if (/earn|bene|deduc|eetax|ertax|variance/i.test(c)) prAmtIdxs.add(i); });

  const TOTAL_COLS = 3 + prCols.length;

  function fmt(val) {
    const n = parseFloat(String(val ?? '').replace(/,/g, ''));
    if (isNaN(n)) return { s: esc(String(val ?? '')), neg: false, zero: false, num: false };
    if (n === 0)  return { s: '-', neg: false, zero: true, num: true };
    const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return { s: n < 0 ? `-${s}` : s, neg: n < 0, zero: false, num: true };
  }

  function matchingPrRows(glCode) {
    if (!glCode || prRMIdx < 0) return [];
    const re = new RegExp(`(?<!\\d)${glCode}(?!\\d)`);
    return prRows.filter(r => re.test(String(r[prRMIdx] ?? '')));
  }

  let tbody = '', lastStep = null;

  // Running totals — accumulated during the row-building loop
  let glNetTotal = 0;
  const prColTotals = {};
  prAmtIdxs.forEach(i => { prColTotals[i] = 0; });
  // Track which PR rows have been counted (by Reconciliation Mapping string)
  // so rows that appear for multiple GL codes are only summed once.
  const countedPrMappings = new Set();

  glRows.forEach(glRow => {
    const step   = String(glRow[gRMIdx]   ?? '').trim();
    const glCode = String(glRow[gCodeIdx] ?? '').trim();
    const glTit  = String(glRow[gTitIdx]  ?? '').trim();
    const glNet  = fmt(glRow[gNetIdx]);

    if (step && step !== lastStep) {
      tbody += `<tr class="row-step-hdr"><td colspan="${TOTAL_COLS}">${esc(step)}</td></tr>`;
      lastStep = step;
    }

    const isGlOnly  = (_reconStatus[glCode] || '').toLowerCase().includes('gl only');
    const matches   = isGlOnly ? [] : matchingPrRows(glCode);
    const span      = Math.max(matches.length, 1);
    const glCells =
      `<td rowspan="${span}" class="ci-gl-code">${esc(glCode)}</td>` +
      `<td rowspan="${span}" class="ci-gl-title">${esc(glTit)}</td>` +
      `<td rowspan="${span}" class="num ci-gl-net${glNet.neg ? ' ci-neg' : ''}">${glNet.s}</td>`;

    // Accumulate GL net total (exclude GL Only rows — informational only)
    if (!isGlOnly) {
      const rawNet = parseFloat(String(glRow[gNetIdx] ?? '').replace(/,/g, ''));
      if (!isNaN(rawNet)) glNetTotal += rawNet;
    }

    if (isGlOnly) {
      tbody += `<tr class="ci-gl-only">${glCells}<td colspan="${prCols.length}" class="ci-gl-only-note">GL Only — informational balance, no PR counterpart</td></tr>`;
      return;
    }
    if (matches.length === 0) {
      tbody += `<tr class="ci-no-pr">${glCells}${prCols.map(() => '<td></td>').join('')}</tr>`;
      return;
    }
    matches.forEach((prRow, pi) => {
      // Accumulate PR totals — count each unique PR mapping only once
      const mappingKey = String(prRow[prRMIdx] ?? '');
      if (!countedPrMappings.has(mappingKey)) {
        countedPrMappings.add(mappingKey);
        prAmtIdxs.forEach(i => {
          const v = parseFloat(String(prRow[i] ?? '').replace(/,/g, ''));
          if (!isNaN(v)) prColTotals[i] += v;
        });
      }

      const prCells = prCols.map((col, i) => {
        const isAmt = prAmtIdxs.has(i);
        const isVar = /variance/i.test(col);
        if (!isAmt) return `<td class="ci-pr-txt">${esc(String(prRow[i] ?? ''))}</td>`;
        const v = fmt(prRow[i]);
        if (v.zero) return `<td class="num ci-zero">-</td>`;
        const cls = isVar
          ? `num ci-var${v.neg ? ' ci-var-ok' : ' ci-var-bad'}`
          : `num${v.neg ? ' ci-neg' : ''}`;
        return `<td class="${cls}">${v.s}</td>`;
      }).join('');
      tbody += `<tr class="${pi > 0 ? 'ci-extra' : ''}">${pi === 0 ? glCells : ''}${prCells}</tr>`;
    });
  });

  // ── Totals footer row ────────────────────────────────────────────────────
  const glNetFmt = fmt(glNetTotal);
  const prTotalCells = prCols.map((col, i) => {
    if (!prAmtIdxs.has(i)) return `<td class="ci-total-empty"></td>`;
    const v = fmt(prColTotals[i] || 0);
    const isVar = /variance/i.test(col);
    const cls = isVar
      ? `num ci-total${v.neg ? ' ci-var-ok' : (v.zero ? '' : ' ci-var-bad')}`
      : `num ci-total${v.neg ? ' ci-neg' : ''}`;
    return `<td class="${cls}">${v.zero ? '-' : v.s}</td>`;
  }).join('');

  const tfoot =
    `<tfoot><tr class="ci-total-row">` +
    `<td colspan="2" class="ci-total-label">TOTAL</td>` +
    `<td class="num ci-total${glNetFmt.neg ? ' ci-neg' : ''}">${glNetFmt.s}</td>` +
    prTotalCells +
    `</tr></tfoot>`;

  const superHdr =
    `<tr class="ci-super">` +
    `<th colspan="3" class="ci-super-gl">Pivot of GL</th>` +
    `<th colspan="${prCols.length}" class="ci-super-pr">Pivot of Payroll Register</th>` +
    `</tr>`;
  const colHdr =
    `<th class="ci-gh">GL Code</th><th class="ci-gh">GL Title</th><th class="ci-gh num">Sum of Net</th>` +
    prCols.map(c => `<th class="ci-ph${/variance/i.test(c) ? ' ci-var-th' : ''}">${esc(c)}</th>`).join('');

  el.innerHTML =
    `<div class="result-wrap ci-wrap"><table class="result-table ci-tbl">` +
    `<thead>${superHdr}<tr>${colHdr}</tr></thead><tbody>${tbody}</tbody>${tfoot}</table></div>`;
}

function renderResultTable(elId, tableData, isRecon) {
  const el = document.getElementById(elId);
  if (!el || !tableData) return;
  const amtCols = new Set();
  (tableData.columns || []).forEach((c, i) => {
    if (/amount|amt|earn|bene|deduc|tax|net|variance|balance/i.test(c)) amtCols.add(i);
  });
  const headers = (tableData.columns || []).map(c => `<th>${esc(c)}</th>`).join('');
  const rows    = (tableData.rows || []).map(row => {
    const status  = isRecon ? (row[row.length - 2] || '') : '';
    const isTotal = String(row[0]).includes('TOTAL');
    const cls     = isTotal ? 'row-total' : status.includes('Match') ? 'row-match' : (status.includes('Variance') || status.includes('No PR')) ? 'row-var' : '';
    const cells   = row.map((val, i) => {
      const isNum = amtCols.has(i) && val !== '' && !isNaN(parseFloat(String(val).replace(/,/g, '')));
      const fmt   = isNum
        ? parseFloat(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : esc(val);
      return `<td class="${isNum ? 'num' : ''}">${fmt}</td>`;
    }).join('');
    return `<tr class="${cls}">${cells}</tr>`;
  }).join('');
  el.innerHTML = `<div class="result-wrap"><table class="result-table"><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderUnmapped(unmappedGl, unmappedPr) {
  const el = document.getElementById('unmapped-content');
  if (!el) return;
  let html = '';

  if (!unmappedGl?.length && !unmappedPr?.length) {
    html = `<div class="unmapped-clean">
      <span style="font-size:18px">✓</span>
      All GL codes and payroll pairs are fully mapped — nothing to review
    </div>`;
  } else {
    html += `<p style="font-size:12.5px;color:var(--text-2);margin-bottom:16px;line-height:1.6">
      The items below appear in your uploaded files but have no matching row in the Configuration. Add them via the Configuration page and re-run.
    </p>`;

    if (unmappedGl?.length) {
      html += `<div class="unmapped-block">
        <div class="unmapped-title" style="color:var(--red-text)">
          GL Codes not in mapping
          <span class="unmapped-count">${unmappedGl.length}</span>
        </div>
        <div class="result-wrap" style="max-width:320px">
          <table class="result-table">
            <thead><tr><th>GL Code</th></tr></thead>
            <tbody>${unmappedGl.map(c => `<tr><td style="font-weight:600;color:var(--blue-dark)">${esc(c)}</td></tr>`).join('')}</tbody>
          </table>
        </div>
      </div>`;
    }

    if (unmappedPr?.length) {
      html += `<div class="unmapped-block">
        <div class="unmapped-title" style="color:var(--red-text)">
          Payroll pairs not in mapping
          <span class="unmapped-count">${unmappedPr.length}</span>
        </div>
        <div class="result-wrap" style="max-width:420px">
          <table class="result-table">
            <thead><tr><th>Pay Code</th><th>Code Type</th></tr></thead>
            <tbody>${unmappedPr.map(k => `<tr>
              <td style="font-weight:600;color:var(--blue-dark)">${esc(k[0])}</td>
              <td><span style="font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:3px;background:var(--amber-bg);color:var(--amber-text)">${esc(k[1])}</span></td>
            </tr>`).join('')}</tbody>
          </table>
        </div>
      </div>`;
    }
  }
  el.innerHTML = html;
}
