/* ═══════════════════════════════════════════════════════════════════
   upload.js — Upload Files page logic
   Handles: file zones, drag-drop, column role assignment, confirmation
   ═══════════════════════════════════════════════════════════════════ */

function setupUploadZones() {
  ['gl_report', 'payroll_register'].forEach(ft => {
    const zone = document.getElementById(`zone-${ft}`);

    // Single permanent click handler — always resolves the CURRENT input at click time
    zone.addEventListener('click', e => {
      const input = zone.querySelector('input[type=file]');
      if (!input) return;
      if (!zone.classList.contains('has-file') && e.target !== input) input.click();
    });

    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => {
      e.preventDefault(); zone.classList.remove('dragover');
      if (e.dataTransfer.files[0]) handleFileUpload(ft, e.dataTransfer.files[0]);
    });

    // Wire the initial input's change event
    _bindInputChange(ft, zone.querySelector('input[type=file]'));
  });
}

function _bindInputChange(fileType, input) {
  if (!input) return;
  input.addEventListener('change', () => { if (input.files[0]) handleFileUpload(fileType, input.files[0]); });
}

async function handleFileUpload(fileType, file, sheetName = null) {
  showLoading(`Uploading ${file.name}…`);
  const fd = new FormData();
  fd.append('file',        file);
  fd.append('session_id',  state.sessionId);
  fd.append('client_name', getClient());
  fd.append('use_bedrock', 'true');
  fd.append('use_cache',   'true');
  if (sheetName) fd.append('sheet_name', sheetName);

  try {
    const res  = await fetch(`${API}/api/upload/${fileType}`, { method: 'POST', body: fd });
    const data = await res.json();
    hideLoading();

    if (!res.ok || !data.ok) { showZoneError(fileType, data.detail || 'Upload failed.'); return; }

    if (!sheetName && data.sheets && data.sheets.length > 1) {
      showSheetSelector(fileType, data.sheets, file);
      return;
    }

    state.files[fileType]      = data;
    state.uploadData[fileType] = data;
    state.confirmed[fileType]  = false;

    // Persist upload response so a page refresh can restore the UI
    sessionStorage.setItem(`pr_upload_${fileType}`, JSON.stringify({
      filename: data.filename, row_count: data.row_count, col_count: data.col_count,
      header_row: data.header_row, columns: data.columns,
      mapping: data.mapping, confidence: data.confidence, preview: data.preview,
    }));
    sessionStorage.removeItem(`pr_confirmed_${fileType}`);

    renderFileSuccess(fileType, data);
    renderColumnAssignment(fileType, data);
    if (data.preview) renderPreview(fileType, data.columns, data.preview);
    updateStepStatus(fileType);
    updateDashboard();
    updatePreflight();
  } catch (e) {
    hideLoading();
    showZoneError(fileType, `Error: ${e.message}`);
  }
}

function showSheetSelector(fileType, sheets, file) {
  const sheetRow = document.getElementById(`sheet-row-${fileType}`);
  const sel      = document.getElementById(`sheet-sel-${fileType}`);
  sel.innerHTML  = sheets.map(s => `<option>${s}</option>`).join('');
  sheetRow.classList.add('show');
  renderFileSuccess(fileType, { filename: file.name, row_count: 0, col_count: 0, header_row: 0 });
  sel.onchange = () => handleFileUpload(fileType, file, sel.value);
  handleFileUpload(fileType, file, sheets[0]);
}

function renderFileSuccess(fileType, data) {
  const zone = document.getElementById(`zone-${fileType}`);
  zone.classList.add('has-file');
  zone.querySelector('.upload-inner').innerHTML = `
    <div class="file-success-row">
      <div class="file-success-icon">✅</div>
      <div class="file-success-info">
        <div class="file-success-name">${esc(data.filename)}</div>
        <div class="file-success-meta">
          ${data.row_count ? data.row_count.toLocaleString() + ' rows' : ''}
          ${data.col_count ? ' · ' + data.col_count + ' columns' : ''}
          ${data.header_row !== undefined ? ' · header row ' + (data.header_row + 1) : ''}
        </div>
      </div>
      <div class="file-success-act">
        <button class="btn btn-ghost btn-sm" onclick="resetUpload('${fileType}')">Change</button>
      </div>
    </div>`;
}

function renderPreview(fileType, cols, rows) {
  const el = document.getElementById(`preview-${fileType}`);
  if (!el) return;
  const headers = cols.map(c => `<th>${esc(c)}</th>`).join('');
  const body    = rows.map(row =>
    `<tr>${cols.map(c => `<td>${esc(row[c] ?? '')}</td>`).join('')}</tr>`
  ).join('');
  el.innerHTML = `<details>
    <summary class="preview-summary">▸ Preview — first ${rows.length} rows</summary>
    <div class="preview-wrap">
      <table class="preview-table">
        <thead><tr>${headers}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  </details>`;
  el.style.display = 'block';
}

// ── Column Role Assignment Table ──────────────────────────────────────────
function renderColumnAssignment(fileType, data) {
  const wrap = document.getElementById(`mapping-${fileType}`);
  if (!wrap) return;

  const roles      = REQUIRED_ROLES[fileType] || [];
  const allCols    = data.columns || [];
  const mapping    = data.mapping || {};
  const confidence = data.confidence || {};

  const roleToCol = {};
  Object.entries(mapping).forEach(([col, role]) => {
    if (role && !roleToCol[role]) roleToCol[role] = col;
  });

  const tableRows = roles.map(ri => {
    const detected = roleToCol[ri.role] || null;
    const conf     = detected ? (confidence[detected] || 0) : 0;
    const isMiss   = !detected;
    const isAI     = conf > 0 && conf < 85;

    const badgeCls = isMiss ? 'cb-miss' : isAI ? 'cb-ai' : 'cb-auto';
    const badgeTxt = isMiss ? 'Not detected' : isAI ? `AI ${conf.toFixed(0)}%` : `Auto ${conf.toFixed(0)}%`;

    const opts = ['(not mapped)', ...allCols].map(c =>
      `<option value="${esc(c)}"${c === (detected || '(not mapped)') ? ' selected' : ''}>${esc(c)}</option>`
    ).join('');

    return `<tr>
      <td>
        <div class="role-name">${esc(ri.label)}</div>
        <div class="role-hint">${esc(ri.hint)}</div>
      </td>
      <td><span class="${ri.required ? 'role-req' : 'role-opt'}">${ri.required ? 'Required' : 'Optional'}</span></td>
      <td>
        <select class="role-col-select" data-role="${esc(ri.role)}" data-ft="${fileType}"
          onchange="onRoleSelectChange(this)">${opts}</select>
      </td>
      <td><span class="cbadge ${badgeCls}">${badgeTxt}</span></td>
    </tr>`;
  }).join('');

  wrap.innerHTML = `
    <div class="role-assignment-header">
      <div class="role-assignment-title">Column Role Assignment</div>
      <div class="role-assignment-sub">Columns were auto-detected via AI. Review and adjust if needed, then confirm.</div>
    </div>
    <table class="role-table">
      <thead><tr>
        <th style="width:190px">Role</th>
        <th style="width:76px">Required</th>
        <th>Mapped Column</th>
        <th style="width:110px">Confidence</th>
      </tr></thead>
      <tbody>${tableRows}</tbody>
    </table>
    <div id="mapping-alert-${fileType}" class="alert alert-error" style="margin-top:10px"></div>
    <div class="confirm-bar">
      <button class="btn btn-blue btn-sm" onclick="confirmColumnMapping('${fileType}')">
        ✓ Confirm Column Mapping
      </button>
      <div class="confirm-done" id="confirm-done-${fileType}">✓ Confirmed</div>
    </div>`;
  wrap.style.display = 'block';
}

function onRoleSelectChange(sel) {
  const badge = sel.closest('tr').querySelector('.cbadge');
  if (!badge) return;
  if (sel.value !== '(not mapped)') {
    badge.className = 'cbadge cb-manual';
    badge.textContent = 'Manual';
  } else {
    badge.className = 'cbadge cb-none';
    badge.textContent = '—';
  }
}

async function confirmColumnMapping(fileType) {
  const selects   = document.querySelectorAll(`select[data-ft="${fileType}"]`);
  const roleToCol = {};
  selects.forEach(sel => { if (sel.value !== '(not mapped)') roleToCol[sel.dataset.role] = sel.value; });

  const mapping = {};
  Object.entries(roleToCol).forEach(([role, col]) => { mapping[col] = role; });

  const reqRoles = (REQUIRED_ROLES[fileType] || []).filter(r => r.required).map(r => r.role);
  const missing  = reqRoles.filter(r => !roleToCol[r]);
  const alertEl  = document.getElementById(`mapping-alert-${fileType}`);
  if (missing.length) {
    alertEl.textContent = `Please assign: ${missing.map(r =>
      REQUIRED_ROLES[fileType].find(x => x.role === r)?.label || r
    ).join(', ')}`;
    alertEl.classList.add('show');
    return;
  }
  alertEl.classList.remove('show');

  showLoading('Saving column mapping…');
  const res = await fetch(`${API}/api/confirm-mapping`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({
      session_id:  state.sessionId,
      file_type:   fileType,
      mapping,
      client_name: getClient(),
      save_cache:  true,
    }),
  });
  hideLoading();

  const data = await res.json().catch(() => ({}));
  if (res.ok) {
    state.confirmed[fileType] = true;
    sessionStorage.setItem(`pr_confirmed_${fileType}`, 'true');
    document.getElementById(`confirm-done-${fileType}`)?.classList.add('show');
    updateStepStatus(fileType);
    updateDashboard();
    updatePreflight();
    if (fileType === 'gl_report')        fetchGLCodes();
    if (fileType === 'payroll_register') fetchPRCodes();

    // Show any column-mapping warnings (e.g. Fund Code detected as GL Code)
    const warns = data.warnings || [];
    if (warns.length) {
      alertEl.className = 'alert alert-warning';
      alertEl.innerHTML = warns.map(w =>
        `⚠ ${esc(w)}`
      ).join('<br>');
      alertEl.classList.add('show');
    }
  } else {
    alertEl.className = 'alert alert-error';
    alertEl.textContent = data.detail || 'Confirmation failed.';
    alertEl.classList.add('show');
  }
}

function resetUpload(fileType) {
  state.files[fileType]      = null;
  state.uploadData[fileType] = null;
  state.confirmed[fileType]  = false;
  sessionStorage.removeItem(`pr_upload_${fileType}`);
  sessionStorage.removeItem(`pr_confirmed_${fileType}`);

  const zone = document.getElementById(`zone-${fileType}`);
  zone.classList.remove('has-file');
  zone.querySelector('.upload-inner').innerHTML = `
    <div class="upload-icon">📂</div>
    <div class="upload-label">Click or drag &amp; drop</div>
    <div class="upload-hint">Excel, CSV, TSV, ODS — .xlsx .xls .xlsm .xlsb .csv .tsv .txt .ods</div>
    <input type="file" accept=".xlsx,.xls,.xlsm,.xltx,.xlsb,.csv,.tsv,.txt,.ods">`;

  // Wire only the input's change event — the zone's click listener already exists from setupUploadZones()
  _bindInputChange(fileType, zone.querySelector('input[type=file]'));

  document.getElementById(`sheet-row-${fileType}`)?.classList.remove('show');
  const mapEl = document.getElementById(`mapping-${fileType}`);
  if (mapEl) { mapEl.innerHTML = ''; mapEl.style.display = 'none'; }
  const preEl = document.getElementById(`preview-${fileType}`);
  if (preEl) { preEl.innerHTML = ''; preEl.style.display = 'none'; }

  updateStepStatus(fileType);
  updateDashboard();
  updatePreflight();
}

function updateStepStatus(fileType) {
  const textEl = document.getElementById(`status-${fileType}`);
  const dotEl  = document.getElementById(`dot-${fileType}`);
  if (!textEl) return;
  if (state.confirmed[fileType]) {
    textEl.textContent = '✓ Confirmed';
    textEl.style.color = 'var(--green-text)';
    if (dotEl) { dotEl.className = 'status-dot st-ok'; }
  } else if (state.files[fileType]) {
    textEl.textContent = 'Pending';
    textEl.style.color = 'var(--amber-text)';
    if (dotEl) { dotEl.className = 'status-dot st-pending'; }
  } else {
    textEl.textContent = 'Waiting';
    textEl.style.color = 'var(--text-3)';
    if (dotEl) { dotEl.className = 'status-dot'; }
  }
}

// ── Session restore — called on page refresh when a session is still alive ──
async function restoreUploadState() {
  for (const ft of ['gl_report', 'payroll_register']) {
    const raw = sessionStorage.getItem(`pr_upload_${ft}`);
    if (!raw) continue;
    let data;
    try { data = JSON.parse(raw); } catch { sessionStorage.removeItem(`pr_upload_${ft}`); continue; }

    state.files[ft]      = data;
    state.uploadData[ft] = data;

    renderFileSuccess(ft, data);
    if (data.columns && data.mapping) renderColumnAssignment(ft, data);
    if (data.preview)                 renderPreview(ft, data.columns, data.preview);

    if (sessionStorage.getItem(`pr_confirmed_${ft}`) === 'true') {
      state.confirmed[ft] = true;
      document.getElementById(`confirm-done-${ft}`)?.classList.add('show');
    }
    updateStepStatus(ft);
  }

  // Re-populate GL code / pay-code dropdowns used by the Config page
  if (state.confirmed.gl_report)        await fetchGLCodes();
  if (state.confirmed.payroll_register) await fetchPRCodes();
}

function showZoneError(fileType, msg) {
  const zone = document.getElementById(`zone-${fileType}`);
  let err = zone.parentElement.querySelector(`.zone-err-${fileType}`);
  if (!err) {
    err = document.createElement('div');
    err.className = `alert alert-error zone-err-${fileType}`;
    zone.parentElement.insertBefore(err, zone.nextSibling);
  }
  err.textContent = msg;
  err.classList.add('show');
}
