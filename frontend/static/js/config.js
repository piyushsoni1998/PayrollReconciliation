/* ═══════════════════════════════════════════════════════════════════
   config.js — Configuration page: mapping table editor
   Handles: GL/PR code dropdowns, auto-fill, table render, save/load
   ═══════════════════════════════════════════════════════════════════ */

// Strip leading letter-based classification prefix for display
// e.g. "A. Earning/ Gross wages" → "Earning/ Gross wages"
//      "B.1 Benefits / Expenses" → "Benefits / Expenses"
function stripStepPrefix(text) {
  return (text || '').replace(/^[A-Z][0-9.]*\.?\s+/, '');
}

// ── Custom HTML table — inline-editing data grid ─────────────────────────
// state.mappingRows is the single source of truth; no external spreadsheet lib needed.

function _readFromSheet()  { return state.mappingRows.map(r => ({ ...r })); }
function _syncFromSheet()  { /* no-op — state.mappingRows is always current */ }

// ── Badge helpers ─────────────────────────────────────────────────────────
const _AMT_CLS = {
  EarnAmt:'earn', BeneAmt:'bene', DeducAmt:'dedu',
  EETax:'eetax', ERTax:'ertax', 'EeTax & ERTax':'both', NetAmt:'net', GLOnly:'glo',
};
const _TYPE_CLS = { EARNING:'earning', BENEFIT:'benefit', DEDUCT:'deduct', TAXES:'taxes' };

function _amtBadge(v)  {
  if (!v) return '<span class="cfg-badge-empty">—</span>';
  return `<span class="cfg-amt-badge cfg-amt-${_AMT_CLS[v]||'other'}">${esc(v)}</span>`;
}
function _typeBadge(v) {
  if (!v) return '<span class="cfg-badge-empty">—</span>';
  return `<span class="cfg-type-badge cfg-type-${_TYPE_CLS[(v||'').toUpperCase()]||'other'}">${esc(v)}</span>`;
}

// ── Render a single table row ─────────────────────────────────────────────
function _renderRow(row, idx) {
  const letter = ((row.recon_step || '').match(/^([A-G])/i) || [])[1]?.toUpperCase() || '';
  const stepCls = letter ? ` cfg-step-${letter}` : '';
  return `<tr class="cfg-tr${stepCls}" data-idx="${idx}">
    <td class="cfg-td-check"><input type="checkbox" class="cfg-row-check" onchange="onRowCheckChange()"></td>
    <td class="cfg-td-num">${idx + 1}</td>
    <td class="cfg-td-cell cfg-col-step"  data-field="recon_step"     data-idx="${idx}" data-type="text">${esc(row.recon_step     ||'')}</td>
    <td class="cfg-td-cell cfg-col-glcode" data-field="gl_code"       data-idx="${idx}" data-type="gl">${esc(row.gl_code         ||'')}</td>
    <td class="cfg-td-cell cfg-col-title"  data-field="gl_title"      data-idx="${idx}" data-type="text">${esc(row.gl_title       ||'')}</td>
    <td class="cfg-td-cell cfg-col-pcode"  data-field="pay_code"      data-idx="${idx}" data-type="pr">${esc(row.pay_code         ||'')}</td>
    <td class="cfg-td-cell cfg-col-title"  data-field="pay_code_title" data-idx="${idx}" data-type="text">${esc(row.pay_code_title||'')}</td>
    <td class="cfg-td-cell cfg-col-amt"    data-field="amount_column" data-idx="${idx}" data-type="sel-amt">${_amtBadge(row.amount_column)}</td>
    <td class="cfg-td-cell cfg-col-ctype"  data-field="code_type"     data-idx="${idx}" data-type="sel-type">${_typeBadge(row.code_type)}</td>
    <td class="cfg-td-actions"><button class="cfg-btn-del" onclick="deleteMappingRow(${idx})" title="Delete row">✕</button></td>
  </tr>`;
}

// ── GL Code drill-down picker ─────────────────────────────────────────────
let _glPickerTarget = null;

function _ensureGLPicker() {
  if (document.getElementById('cfg-gl-picker')) return;
  const div = document.createElement('div');
  div.id = 'cfg-gl-picker';
  div.className = 'cfg-picker';
  div.innerHTML = `
    <div class="cfg-picker-header">
      <div class="cfg-picker-search-wrap">
        <svg class="cfg-picker-icon" width="13" height="13" viewBox="0 0 16 16" fill="none">
          <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.6"/>
          <line x1="10" y1="10" x2="14" y2="14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
        </svg>
        <input type="text" class="cfg-picker-search" id="cfg-gl-search-input"
          placeholder="Search by code or title…" autocomplete="off"
          oninput="_filterGLPicker(this.value)">
      </div>
      <span class="cfg-picker-count" id="cfg-gl-picker-count"></span>
    </div>
    <div class="cfg-picker-list" id="cfg-gl-picker-list"></div>`;
  document.body.appendChild(div);

  // Close on outside click
  document.addEventListener('mousedown', e => {
    const picker = document.getElementById('cfg-gl-picker');
    if (!picker || !_glPickerTarget) return;
    if (!picker.contains(e.target) && !_glPickerTarget.contains(e.target)) _closeGLPicker(true);
  });
}

function _openGLPicker(td) {
  _ensureGLPicker();
  _glPickerTarget = td;
  const picker = document.getElementById('cfg-gl-picker');
  const input  = document.getElementById('cfg-gl-search-input');

  // Position the picker below the cell using viewport coords (fixed)
  const rect = td.getBoundingClientRect();
  picker.style.left  = `${rect.left}px`;
  picker.style.top   = `${rect.bottom + 4}px`;
  picker.style.minWidth = `${Math.max(360, rect.width)}px`;
  picker.style.display  = 'block';

  // Pre-fill search with current value and refresh list
  const curCode = state.mappingRows[parseInt(td.dataset.idx)]?.gl_code || '';
  input.value = curCode;
  _filterGLPicker(curCode);
  input.focus();
  input.select();
}

function _filterGLPicker(text) {
  const list    = document.getElementById('cfg-gl-picker-list');
  const countEl = document.getElementById('cfg-gl-picker-count');
  if (!list) return;

  const term    = (text || '').trim().toLowerCase();
  const entries = Object.entries(state.glCodeTitles);
  const filtered = term
    ? entries.filter(([code, title]) =>
        code.toLowerCase().includes(term) || title.toLowerCase().includes(term))
    : entries;

  const curCode = state.mappingRows[parseInt(_glPickerTarget?.dataset.idx || -1)]?.gl_code || '';
  const idx     = _glPickerTarget?.dataset.idx ?? '';

  if (!filtered.length) {
    list.innerHTML = `<div class="cfg-picker-empty">No GL codes match "${esc(text)}"</div>`;
  } else {
    list.innerHTML = filtered.map(([code, title]) => {
      const isActive = code === curCode ? ' cfg-picker-item-active' : '';
      return `<div class="cfg-picker-item${isActive}" onclick="_selectGLCode('${esc(code)}','${esc(idx)}')">
        <span class="cfg-picker-code">${esc(code)}</span>
        <span class="cfg-picker-title">${esc(title)}</span>
      </div>`;
    }).join('');
    // Scroll active item into view
    const active = list.querySelector('.cfg-picker-item-active');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }

  if (countEl) countEl.textContent = `${filtered.length} / ${entries.length} codes`;
}

function _selectGLCode(code, idxStr) {
  const idx = parseInt(idxStr);
  const row = state.mappingRows[idx];
  if (row) {
    row.gl_code  = code;
    row.gl_title = state.glCodeTitles[code] || row.gl_title;
    state.mappingRows[idx] = row;
    renderConfigSummary(state.mappingRows);
    _rerenderRow(idx);
  }
  _closeGLPicker(false);
}

function _closeGLPicker(restoreCell) {
  const picker = document.getElementById('cfg-gl-picker');
  if (picker) picker.style.display = 'none';
  if (_glPickerTarget) {
    if (restoreCell) _rerenderRow(parseInt(_glPickerTarget.dataset.idx));
    _glPickerTarget = null;
  }
}

// ── Pay Code drill-down picker ────────────────────────────────────────────
let _prPickerTarget = null;

function _ensurePRPicker() {
  if (document.getElementById('cfg-pr-picker')) return;
  const div = document.createElement('div');
  div.id = 'cfg-pr-picker';
  div.className = 'cfg-picker';
  div.innerHTML = `
    <div class="cfg-picker-header">
      <div class="cfg-picker-search-wrap">
        <svg class="cfg-picker-icon" width="13" height="13" viewBox="0 0 16 16" fill="none">
          <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.6"/>
          <line x1="10" y1="10" x2="14" y2="14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
        </svg>
        <input type="text" class="cfg-picker-search" id="cfg-pr-search-input"
          placeholder="Search by pay code or title…" autocomplete="off"
          oninput="_filterPRPicker(this.value)">
      </div>
      <span class="cfg-picker-count" id="cfg-pr-picker-count"></span>
    </div>
    <div class="cfg-picker-list" id="cfg-pr-picker-list"></div>`;
  document.body.appendChild(div);

  document.addEventListener('mousedown', e => {
    const picker = document.getElementById('cfg-pr-picker');
    if (!picker || !_prPickerTarget) return;
    if (!picker.contains(e.target) && !_prPickerTarget.contains(e.target)) _closePRPicker(true);
  });
}

function _openPRPicker(td) {
  _ensurePRPicker();
  _prPickerTarget = td;
  const picker = document.getElementById('cfg-pr-picker');
  const input  = document.getElementById('cfg-pr-search-input');

  const rect = td.getBoundingClientRect();
  picker.style.left     = `${rect.left}px`;
  picker.style.top      = `${rect.bottom + 4}px`;
  picker.style.minWidth = `${Math.max(400, rect.width)}px`;
  picker.style.display  = 'block';

  const curCode = state.mappingRows[parseInt(td.dataset.idx)]?.pay_code || '';
  input.value = curCode;
  _filterPRPicker(curCode);
  input.focus();
  input.select();
}

function _filterPRPicker(text) {
  const list    = document.getElementById('cfg-pr-picker-list');
  const countEl = document.getElementById('cfg-pr-picker-count');
  if (!list) return;

  const term    = (text || '').trim().toLowerCase();
  const entries = Object.entries(state.prCodeTypes);
  const filtered = term
    ? entries.filter(([code, info]) => {
        const title = typeof info === 'object' ? (info.title || '') : '';
        const ctype = typeof info === 'object' ? (info.code_type || '') : (info || '');
        return code.toLowerCase().includes(term)
            || title.toLowerCase().includes(term)
            || ctype.toLowerCase().includes(term);
      })
    : entries;

  const curCode = state.mappingRows[parseInt(_prPickerTarget?.dataset.idx || -1)]?.pay_code || '';
  const idx     = _prPickerTarget?.dataset.idx ?? '';

  if (!filtered.length) {
    list.innerHTML = `<div class="cfg-picker-empty">No pay codes match "${esc(text)}"</div>`;
  } else {
    list.innerHTML = filtered.map(([code, info]) => {
      const title = typeof info === 'object' ? (info.title || '') : '';
      const ctype = typeof info === 'object' ? (info.code_type || '') : (info || '');
      const isActive = code === curCode ? ' cfg-picker-item-active' : '';
      const typeCls  = _TYPE_CLS[(ctype || '').toUpperCase()] || 'other';
      const typeBadge = ctype
        ? `<span class="cfg-picker-type-badge cfg-type-${typeCls}">${esc(ctype)}</span>`
        : '';
      return `<div class="cfg-picker-item${isActive}" onclick="_selectPayCode('${esc(code)}','${esc(idx)}')">
        <span class="cfg-picker-code">${esc(code)}</span>
        <span class="cfg-picker-title">${esc(title)}</span>
        ${typeBadge}
      </div>`;
    }).join('');
    const active = list.querySelector('.cfg-picker-item-active');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }

  if (countEl) countEl.textContent = `${filtered.length} / ${entries.length} codes`;
}

function _selectPayCode(code, idxStr) {
  const idx  = parseInt(idxStr);
  const row  = state.mappingRows[idx];
  if (row) {
    const info  = state.prCodeTypes[code];
    const title = typeof info === 'object' ? (info.title || '') : '';
    const ctype = typeof info === 'object' ? (info.code_type || '') : (info || '');
    row.pay_code       = code;
    if (title) row.pay_code_title = title;
    if (ctype) row.code_type      = ctype;
    state.mappingRows[idx] = row;
    renderConfigSummary(state.mappingRows);
    _rerenderRow(idx);
  }
  _closePRPicker(false);
}

function _closePRPicker(restoreCell) {
  const picker = document.getElementById('cfg-pr-picker');
  if (picker) picker.style.display = 'none';
  if (_prPickerTarget) {
    if (restoreCell) _rerenderRow(parseInt(_prPickerTarget.dataset.idx));
    _prPickerTarget = null;
  }
}

// ── Start inline editing a cell ───────────────────────────────────────────
function _startEdit(td) {
  if (td.classList.contains('cfg-editing')) return;
  const field = td.dataset.field;
  const idx   = parseInt(td.dataset.idx);
  const type  = td.dataset.type;
  const row   = state.mappingRows[idx];
  if (!row) return;

  // GL Code → open drill-down picker instead of plain input
  if (type === 'gl' && Object.keys(state.glCodeTitles).length) {
    td.classList.add('cfg-editing');
    _openGLPicker(td);
    return;
  }

  // Pay Code → open drill-down picker instead of plain input
  if (type === 'pr' && Object.keys(state.prCodeTypes).length) {
    td.classList.add('cfg-editing');
    _openPRPicker(td);
    return;
  }

  const curVal = row[field] || '';
  td.classList.add('cfg-editing');

  let el;
  if (type === 'sel-amt') {
    el = document.createElement('select');
    el.className = 'cfg-cell-select';
    AMOUNT_COL_OPTIONS.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o; opt.textContent = o || '(none)';
      if (o === curVal) opt.selected = true;
      el.appendChild(opt);
    });
  } else if (type === 'sel-type') {
    el = document.createElement('select');
    el.className = 'cfg-cell-select';
    CODE_TYPE_OPTIONS.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o; opt.textContent = o || '(none)';
      if (o === curVal) opt.selected = true;
      el.appendChild(opt);
    });
  } else {
    el = document.createElement('input');
    el.className = 'cfg-cell-input';
    el.value = curVal;
    if (type === 'pr') el.setAttribute('list', 'cfg-pr-list');
  }

  const commit = () => {
    const newVal = el.value;
    row[field] = newVal;
    if (field === 'gl_code' && newVal) {
      const t = state.glCodeTitles[newVal.trim()];
      if (t) row.gl_title = t;
    }
    if (field === 'pay_code' && newVal) {
      const info = state.prCodeTypes[newVal.trim()];
      if (info) {
        const t  = typeof info === 'object' ? (info.title || '') : '';
        const ct = typeof info === 'object' ? (info.code_type || '') : info;
        if (t)  row.pay_code_title = t;
        if (ct) row.code_type = ct;
      }
    }
    state.mappingRows[idx] = row;
    renderConfigSummary(state.mappingRows);
    _rerenderRow(idx);
  };

  el.addEventListener('blur',    commit);
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { commit(); el.blur(); }
    if (e.key === 'Escape') { td.classList.remove('cfg-editing'); _rerenderRow(idx); }
    if (e.key === 'Tab')    { commit(); }
  });

  td.innerHTML = '';
  td.appendChild(el);
  el.focus();
  if (el.tagName === 'INPUT') /** @type {HTMLInputElement} */ (el).select();
}

// ── Re-render a single row in place ──────────────────────────────────────
function _rerenderRow(idx) {
  const row  = state.mappingRows[idx];
  const tbody = document.getElementById('cfg-tbody');
  if (!row || !tbody) return;
  const tr = tbody.querySelector(`tr[data-idx="${idx}"]`);
  if (!tr) return;

  const letter = ((row.recon_step || '').match(/^([A-G])/i) || [])[1]?.toUpperCase() || '';
  tr.className = `cfg-tr${letter ? ` cfg-step-${letter}` : ''}`;

  tr.querySelectorAll('td[data-field]').forEach(td => {
    td.classList.remove('cfg-editing');
    const f = td.dataset.field;
    if (f === 'amount_column') td.innerHTML = _amtBadge(row[f]);
    else if (f === 'code_type') td.innerHTML = _typeBadge(row[f]);
    else td.textContent = row[f] || '';
    // Rebind click
    td.onclick = null;
    td.addEventListener('click', () => _startEdit(td));
  });
}

// ── Row selection ─────────────────────────────────────────────────────────
function toggleAllRows(cb) {
  document.querySelectorAll('#cfg-tbody .cfg-row-check').forEach(c => c.checked = cb.checked);
  onRowCheckChange();
}
function onRowCheckChange() {
  const n = document.querySelectorAll('#cfg-tbody .cfg-row-check:checked').length;
  const bar = document.getElementById('cfg-bulk-bar');
  if (!bar) return;
  if (n > 0) {
    bar.style.display = 'flex';
    bar.querySelector('.cfg-bulk-count').textContent = `${n} row${n !== 1 ? 's' : ''} selected`;
  } else {
    bar.style.display = 'none';
  }
}

// ── Delete rows ───────────────────────────────────────────────────────────
function deleteMappingRow(idx) {
  if (!confirm('Delete this row?')) return;
  state.mappingRows.splice(idx, 1);
  renderMappingConfigTable(state.mappingRows);
}
function deleteSelectedRows() {
  const indices = new Set();
  document.querySelectorAll('#cfg-tbody .cfg-row-check:checked').forEach(cb => {
    const tr = cb.closest('tr');
    if (tr) indices.add(parseInt(tr.dataset.idx));
  });
  if (!indices.size) return;
  if (!confirm(`Delete ${indices.size} selected row${indices.size !== 1 ? 's' : ''}?`)) return;
  state.mappingRows = state.mappingRows.filter((_, i) => !indices.has(i));
  renderMappingConfigTable(state.mappingRows);
}

// ── Fetch codes from uploaded files ──────────────────────────────────────
async function fetchGLCodes() {
  if (!state.sessionId) return;
  try {
    const res  = await fetch(`${API}/api/gl-codes?session_id=${enc(state.sessionId)}`);
    const data = await res.json();
    if (data.ok && data.codes && Object.keys(data.codes).length > 0) {
      state.glCodeTitles = data.codes;
      showFilesLoadedBanner();
      autoPopulateConfigFromFiles();
    }
  } catch (_) {}
  renderMappingConfigTable(state.mappingRows);
}

async function fetchPRCodes() {
  if (!state.sessionId) return;
  try {
    const res  = await fetch(`${API}/api/pr-codes?session_id=${enc(state.sessionId)}`);
    const data = await res.json();
    if (data.ok && data.codes && Object.keys(data.codes).length > 0) {
      state.prCodeTypes = data.codes;
      showFilesLoadedBanner();
      autoPopulateConfigFromFiles();
    }
  } catch (_) {}
  renderMappingConfigTable(state.mappingRows);
}

function showFilesLoadedBanner() {
  const el = document.getElementById('gl-loaded-banner');
  if (!el) return;
  const glCount = Object.keys(state.glCodeTitles).length;
  const prCount = Object.keys(state.prCodeTypes).length;
  const parts = [];
  if (glCount) parts.push(`${glCount} GL codes`);
  if (prCount) parts.push(`${prCount} pay codes`);
  if (parts.length) {
    el.innerHTML = `<span class="banner-icon">✓</span> ${parts.join(' · ')} loaded from your uploaded files — select from dropdowns in the table below`;
    el.style.display = 'flex';
  }
}

// ── Auto-fill: Pay Code → Code Type ──────────────────────────────────────
function onPayCodeInput(idx, inputEl) {
  const code = inputEl.value.trim();
  state.mappingRows[idx].pay_code = code;
  const info = state.prCodeTypes[code];
  const ctype = typeof info === 'object' ? info.code_type : info;
  if (ctype) {
    const ctSelect = inputEl.closest('tr')?.querySelectorAll('select')[1];
    if (ctSelect) { ctSelect.value = ctype; state.mappingRows[idx].code_type = ctype; }
  }
}

// ── Update step / GL group across all matching rows ──────────────────────
function updateGroupStep(oldStep, newStep) {
  const trimmed = newStep.trim();
  if (!trimmed) return;
  state.mappingRows.forEach(r => { if (r.recon_step === oldStep) r.recon_step = trimmed; });
}

function updateGroupGLCode(step, oldCode, newCode) {
  const trimmed = newCode.trim();
  state.mappingRows.forEach(r => {
    if (r.recon_step === step && r.gl_code === oldCode) r.gl_code = trimmed;
  });
  if (trimmed && state.glCodeTitles[trimmed]) {
    const title = state.glCodeTitles[trimmed];
    state.mappingRows.forEach(r => {
      if (r.recon_step === step && r.gl_code === trimmed && !r.gl_title) r.gl_title = title;
    });
    renderMappingConfigTable(state.mappingRows);
  }
}

function updateGroupGLTitle(step, glCode, newTitle) {
  const trimmed = newTitle.trim();
  state.mappingRows.forEach(r => {
    if (r.recon_step === step && r.gl_code === glCode) r.gl_title = trimmed;
  });
}

// ── Add rows ──────────────────────────────────────────────────────────────
function addMappingRow() {
  const lastRow = state.mappingRows[state.mappingRows.length - 1];
  state.mappingRows.push({
    recon_step: lastRow?.recon_step || '', gl_code: '', gl_title: '',
    pay_code: '', pay_code_title: '', amount_column: 'EarnAmt', code_type: '',
  });
  renderMappingConfigTable(state.mappingRows);
  // Scroll to and focus the new row's first editable cell
  setTimeout(() => {
    const tbody = document.getElementById('cfg-tbody');
    const lastTr = tbody?.lastElementChild;
    if (lastTr) {
      lastTr.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      const firstCell = lastTr.querySelector('td[data-field]');
      if (firstCell) _startEdit(firstCell);
    }
  }, 50);
}

function addMappingRowToSection(step) {
  let lastIdx = -1;
  state.mappingRows.forEach((r, i) => { if (r.recon_step === step) lastIdx = i; });
  const newRow = { recon_step: step, gl_code: '', gl_title: '', pay_code: '', pay_code_title: '', amount_column: 'EarnAmt', code_type: '' };
  if (lastIdx >= 0) state.mappingRows.splice(lastIdx + 1, 0, newRow);
  else state.mappingRows.push(newRow);
  renderMappingConfigTable(state.mappingRows);
}


// ── Load from Files — auto-generate rows from uploaded files ─────────────

// Fallback GL-range heuristics for codes not in the template
function _glFallbackStep(code) {
  const n = parseInt(code, 10);
  if (isNaN(n)) return 'Other';
  if ((n >= 5000 && n <= 5099) || (n >= 6000 && n <= 6999)) return 'A. Earning/ Gross wages';
  if (n >= 5100 && n <= 5199) return 'E. ERTax / Employer Taxes';
  if (n >= 5130 && n <= 5149) return 'B. Benefits / Employer expenses';
  if (n >= 2121 && n <= 2143) return 'C. Deductions / Employee Deductions - Liabilities';
  if (n >= 2115 && n <= 2120) return 'D. Employee & Employer Taxes - Liabilities';
  if (n >= 2000 && n <= 2999) return 'C. Deductions / Employee Deductions - Liabilities';
  if (n >= 1000 && n <= 1999) return 'F. Bank Payment to Employee';
  return 'Other';
}
function _glFallbackAmtCol(code) {
  const n = parseInt(code, 10);
  if (isNaN(n)) return 'EarnAmt';
  if ((n >= 5000 && n <= 5099) || (n >= 6000 && n <= 6999)) return 'EarnAmt';
  if (n >= 5130 && n <= 5149) return 'BeneAmt';
  if (n >= 5100 && n <= 5199) return 'ERTax';
  if (n >= 2121 && n <= 2143) return 'DeducAmt';
  if (n >= 2115 && n <= 2120) return 'EETax & ERTax';
  if (n >= 2000 && n <= 2999) return 'DeducAmt';
  if (n >= 1000 && n <= 1999) return 'NetAmt';
  return 'EarnAmt';
}
function _glFallbackCodeType(code) {
  const n = parseInt(code, 10);
  if (isNaN(n)) return 'EARNING';
  if ((n >= 5000 && n <= 5099) || (n >= 6000 && n <= 6999)) return 'EARNING';
  if (n >= 5100 && n <= 5199) return 'TAXES';
  if (n >= 5130 && n <= 5149) return 'BENEFIT';
  if (n >= 2121 && n <= 2143) return 'DEDUCT';
  if (n >= 2115 && n <= 2120) return 'TAXES';
  if (n >= 1000 && n <= 1999) return '';
  return 'EARNING';
}
function _prFallbackStep(ctype) {
  if (ctype === 'BENEFIT') return 'B. Benefits / Employer expenses';
  if (ctype === 'DEDUCT')  return 'C. Deductions / Employee Deductions - Liabilities';
  if (ctype === 'TAXES')   return 'D. Employee & Employer Taxes - Liabilities';
  return 'A. Earning/ Gross wages';
}
function _prFallbackAmtCol(ctype) {
  if (ctype === 'BENEFIT') return 'BeneAmt';
  if (ctype === 'DEDUCT')  return 'DeducAmt';
  if (ctype === 'TAXES')   return 'EETax';
  return 'EarnAmt';
}

/**
 * Build suggested mapping rows by cross-referencing actual GL/PR codes
 * from uploaded files against the default mapping template.
 */
async function buildSuggestedRows() {
  if (!state._defaultTemplate) {
    try {
      const res  = await fetch(`${API}/api/mapping-config/template`);
      const data = await res.json();
      state._defaultTemplate = data.rows || [];
    } catch (_) {
      state._defaultTemplate = [];
    }
  }
  const template = state._defaultTemplate;
  const glCodes  = state.glCodeTitles;
  const prCodes  = state.prCodeTypes;

  const tmplByGL      = {};
  const tmplByPayCode = {};
  template.forEach(row => {
    if (row.gl_code) {
      (tmplByGL[row.gl_code] = tmplByGL[row.gl_code] || []).push(row);
    }
    if (row.pay_code) {
      const k = row.pay_code.toUpperCase();
      (tmplByPayCode[k] = tmplByPayCode[k] || []).push(row);
    }
  });

  const usedKeys  = new Set();
  const result    = [];
  const stepOrder = [...new Set(template.map(r => r.recon_step))];

  function rowKey(r) { return `${r.recon_step}|${r.gl_code}|${r.pay_code}`; }
  function addRow(row) {
    const k = rowKey(row);
    if (usedKeys.has(k)) return;
    usedKeys.add(k);
    result.push(row);
  }

  // Pass 1: template rows whose GL code is in the actual GL file
  Object.keys(glCodes).forEach(glCode => {
    (tmplByGL[glCode] || []).forEach(tmplRow => {
      addRow({ ...tmplRow, gl_title: glCodes[glCode] || tmplRow.gl_title });
    });
  });

  // Pass 2: template rows whose pay code is in the actual PR file
  Object.keys(prCodes).forEach(payCode => {
    (tmplByPayCode[payCode.toUpperCase()] || []).forEach(tmplRow => {
      addRow({ ...tmplRow, gl_title: glCodes[tmplRow.gl_code] || tmplRow.gl_title });
    });
  });

  // Pass 3: GL codes in actual file with NO template match → heuristic row
  Object.entries(glCodes).forEach(([glCode, glTitle]) => {
    if (tmplByGL[glCode]) return;
    addRow({ recon_step: _glFallbackStep(glCode), gl_code: glCode, gl_title: glTitle || '',
             pay_code: '', pay_code_title: '', amount_column: _glFallbackAmtCol(glCode),
             code_type: _glFallbackCodeType(glCode) });
  });

  // Pass 4: pay codes in actual file with NO template match → heuristic row
  Object.entries(prCodes).forEach(([payCode, codeType]) => {
    if (tmplByPayCode[payCode.toUpperCase()]) return;
    const ct = typeof codeType === 'object' ? codeType.code_type : codeType;
    addRow({ recon_step: _prFallbackStep(ct), gl_code: '', gl_title: '',
             pay_code: payCode, pay_code_title: '', amount_column: _prFallbackAmtCol(ct),
             code_type: ct || 'EARNING' });
  });

  result.sort((a, b) => {
    const ai = stepOrder.indexOf(a.recon_step);
    const bi = stepOrder.indexOf(b.recon_step);
    if (ai >= 0 && bi >= 0) return ai - bi;
    if (ai >= 0) return -1;
    if (bi >= 0) return 1;
    return a.recon_step.localeCompare(b.recon_step);
  });

  return result;
}

async function loadFromFiles() {
  const glCount = Object.keys(state.glCodeTitles).length;
  const prCount = Object.keys(state.prCodeTypes).length;

  if (!glCount && !prCount) {
    alert('Please upload and confirm both files first, then click Load from Files.');
    return;
  }

  showLoading('Extracting configuration from files…');
  const suggested = await buildSuggestedRows();
  hideLoading();

  if (!suggested.length) return;
  if (!confirm(`Replace current ${state.mappingRows.length} row(s) with ${suggested.length} rows extracted from your files?\n\nProceed?`)) return;

  state.mappingRows = suggested;
  renderMappingConfigTable(state.mappingRows);
}

// ── Auto-populate when both files confirmed (no saved config yet) ─────────
async function autoPopulateConfigFromFiles() {
  if (state.configSaved) return;
  if (!state.confirmed['gl_report'] || !state.confirmed['payroll_register']) return;
  const glCount = Object.keys(state.glCodeTitles).length;
  const prCount = Object.keys(state.prCodeTypes).length;
  if (!glCount && !prCount) return;

  const hasUserContent = state.mappingRows.some(r => r.gl_code || r.pay_code);
  if (hasUserContent) return;

  const suggested = await buildSuggestedRows();
  if (!suggested.length) return;

  state.mappingRows = suggested;
  renderMappingConfigTable(state.mappingRows);

  const banner = document.getElementById('gl-loaded-banner');
  if (banner) {
    banner.innerHTML = `<span class="banner-icon">✦</span> ${suggested.length} rows extracted from your uploaded files — review and save when ready`;
    banner.style.display = 'flex';
  }
}

// ── Render mapping table (custom HTML grid — inline editable) ─────────────
function renderMappingConfigTable(rows) {
  state.mappingRows = (rows || []).filter(r => Object.values(r).some(v => v));
  const container = document.getElementById('cfg-spreadsheet');
  if (!container) return;

  // Datalists for autocomplete
  const glOpts = Object.entries(state.glCodeTitles)
    .map(([code, title]) => `<option value="${esc(code)}">${esc(title)}</option>`).join('');
  const prOpts = Object.keys(state.prCodeTypes)
    .map(c => `<option value="${esc(c)}"></option>`).join('');

  // Table body rows
  const tbody = state.mappingRows.length
    ? state.mappingRows.map((r, i) => _renderRow(r, i)).join('')
    : `<tr><td colspan="10" class="cfg-empty-row">No rows yet — click Add Row or Load from Files</td></tr>`;

  container.innerHTML = `
    <datalist id="cfg-gl-list">${glOpts}</datalist>
    <datalist id="cfg-pr-list">${prOpts}</datalist>

    <!-- Bulk action bar (hidden until rows are checked) -->
    <div id="cfg-bulk-bar" class="cfg-bulk-bar" style="display:none">
      <span class="cfg-bulk-count"></span>
      <button class="btn btn-danger btn-sm" onclick="deleteSelectedRows()">✕ Delete Selected</button>
      <button class="btn btn-ghost btn-sm" onclick="toggleAllRows(document.getElementById('cfg-check-all'))">Deselect All</button>
    </div>

    <div class="cfg-table-wrap">
      <table class="cfg-table">
        <thead>
          <tr class="cfg-thead-sections">
            <th colspan="2" class="cfg-th-spacer"></th>
            <th class="cfg-th-section cfg-th-sect-steps">Steps of Reconciliation</th>
            <th colspan="2" class="cfg-th-section cfg-th-sect-gl">General Ledger (GL)</th>
            <th colspan="4" class="cfg-th-section cfg-th-sect-pr">Payroll Register</th>
            <th class="cfg-th-spacer"></th>
          </tr>
          <tr class="cfg-thead-cols">
            <th class="cfg-th-check"><input type="checkbox" id="cfg-check-all" onchange="toggleAllRows(this)" title="Select all"></th>
            <th class="cfg-th-num">#</th>
            <th class="cfg-th-col cfg-col-step">Step</th>
            <th class="cfg-th-col cfg-col-glcode">GL Code</th>
            <th class="cfg-th-col cfg-col-title">GL Title</th>
            <th class="cfg-th-col cfg-col-pcode">Pay Code</th>
            <th class="cfg-th-col cfg-col-title">Pay Code Title</th>
            <th class="cfg-th-col cfg-col-amt">Amount Column</th>
            <th class="cfg-th-col cfg-col-ctype">Code Type</th>
            <th class="cfg-th-del"></th>
          </tr>
        </thead>
        <tbody id="cfg-tbody">${tbody}</tbody>
      </table>
    </div>`;

  // Wire click-to-edit on every data cell
  container.querySelectorAll('td[data-field]').forEach(td =>
    td.addEventListener('click', () => _startEdit(td))
  );

  renderConfigSummary(state.mappingRows);
}

// ── Collect current table state ───────────────────────────────────────────
function collectMappingRows() {
  return state.mappingRows.map(r => ({ ...r }));
}

// ── Load / Save / Reset ───────────────────────────────────────────────────
async function loadMappingConfig() {
  const client = getClient();
  showLoading('Loading mapping config…');
  try {
    const res  = await fetch(`${API}/api/mapping-config?client_name=${enc(client)}`);
    const data = await res.json();
    hideLoading();
    state.mappingRows = data.rows || [];
  } catch (e) {
    hideLoading();
    showAlert('cfg-alert', `Could not load config: ${e.message}`);
  }
  renderMappingConfigTable(state.mappingRows);
}

async function saveMappingConfig() {
  const rows = collectMappingRows();
  if (!rows.length) { showAlert('cfg-alert', 'No rows to save.'); return; }

  showLoading('Saving configuration…');
  const res  = await fetch(`${API}/api/mapping-config`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ client_name: getClient(), rows }),
  });
  const data = await res.json();
  hideLoading();

  if (data.ok) {
    state.configSaved = true;
    state.mappingRows = rows;
    showSavedBadge();
    showAlert('cfg-success', `✅ Saved for "${getClient()}" — ${data.row_count} rows.`);
    hideAlert('cfg-alert');
    updateDashboard();
  } else {
    showAlert('cfg-alert', data.detail || 'Save failed.');
  }
}

async function saveAndNavigateNext() {
  await saveMappingConfig();
  if (state.configSaved) navigate('results');
}

async function resetToDefault() {
  if (!confirm('Clear all rows? The table will be emptied so you can configure from scratch.')) return;

  // Delete saved config on backend
  try {
    await fetch(`${API}/api/mapping-config?client_name=${enc(getClient())}`, { method: 'DELETE' });
  } catch (_) {}

  // Clear all state
  state.mappingRows = [];
  state.configSaved = false;

  renderMappingConfigTable([]);
  hideSavedBadge();
  hideAlert('cfg-alert');
  hideAlert('cfg-success');
  updateDashboard();
  updatePreflight();

  showAlert('cfg-success', 'Table cleared — add rows manually, click "Load from Files", or use the AI Assistant.');
}

function toggleAmtLegend() {
  const panel = document.getElementById('amt-legend-panel');
  const btn   = document.getElementById('btn-amt-legend');
  if (!panel) return;
  const show = panel.style.display === 'none';
  panel.style.display = show ? 'block' : 'none';
  if (btn) btn.textContent = show ? '✕ Close Guide' : '📖 Guide';
}

// ── Step chip navigation — scroll to first row of a given step ────────────
function jumpToStep(letter) {
  const tbody = document.getElementById('cfg-tbody');
  if (!tbody) return;
  const tr = tbody.querySelector(`tr.cfg-step-${letter.toUpperCase()}`);
  if (!tr) return;
  tr.scrollIntoView({ behavior: 'smooth', block: 'center' });
  tr.classList.remove('cfg-row-jump');
  tr.getBoundingClientRect(); // force reflow to restart CSS animation
  tr.classList.add('cfg-row-jump');
  setTimeout(() => tr.classList.remove('cfg-row-jump'), 1000);
}

// ── Row search — dims non-matching rows without touching the data ─────────
function filterConfigRows(text) {
  const tbody   = document.getElementById('cfg-tbody');
  const countEl = document.getElementById('cfg-search-count');
  if (!tbody) return;

  const term = (text || '').trim().toLowerCase();
  const rows = tbody.querySelectorAll('tr.cfg-tr');

  if (!term) {
    rows.forEach(tr => tr.classList.remove('cfg-row-dimmed'));
    if (countEl) countEl.textContent = '';
    return;
  }

  let matched = 0;
  rows.forEach(tr => {
    const isMatch = tr.textContent.toLowerCase().includes(term);
    tr.classList.toggle('cfg-row-dimmed', !isMatch);
    if (isMatch) matched++;
  });
  if (countEl) countEl.textContent = `${matched} match${matched !== 1 ? 'es' : ''}`;
}

// ── Update the row-count pill in the chips bar ────────────────────────────
function _updateRowCount(rows) {
  const el = document.getElementById('cfg-row-count');
  if (!el || !rows) return;
  const steps = new Set(rows.map(r => (r.recon_step || '').match(/^([A-G])/i)?.[1]?.toUpperCase()).filter(Boolean));
  el.textContent = `${rows.length} rows · ${steps.size} steps`;
}

function renderConfigSummary(rows) {
  _updateRowCount(rows);          // keep the chips-bar pill in sync
  const el = document.getElementById('config-summary-panel');
  if (!el) return;
  if (!rows || !rows.length) { el.innerHTML = ''; return; }

  // Step breakdown
  const stepMap = {};
  const glOnlyRows = [];
  rows.forEach(r => {
    const step = r.recon_step || 'Other';
    if (!stepMap[step]) stepMap[step] = { count: 0, letter: (step.match(/^([A-G])/i) || ['','?'])[1].toUpperCase() };
    stepMap[step].count++;
    if ((r.amount_column || '').toLowerCase() === 'glonly') glOnlyRows.push(r);
  });

  const stepColors = {
    A:'#FFFDE7',B:'#F1F8E9',C:'#E3F2FD',D:'#FCE4EC',E:'#EDE7F6',F:'#E0F7FA',G:'#F3E5F5'
  };
  const stepNames = {
    A:'Earnings',B:'Benefits',C:'Deductions',D:'EE/ER Tax Liab.',E:'ER Tax Exp.',F:'Bank Pay',G:'Accrued'
  };

  const tiles = Object.entries(stepMap).map(([step, info]) => {
    const bg  = stepColors[info.letter] || '#F5F5F5';
    const nm  = stepNames[info.letter] || stripStepPrefix(step);
    const nm2 = nm.length > 16 ? nm.slice(0,15) + '…' : nm;
    const gloLabel = info.letter === 'G' || step.toLowerCase().includes('accru')
      ? ' <span class="csp-glonly-badge">GLOnly</span>' : '';
    return `<div class="csp-step-tile" style="background:${bg}" title="${esc(step)}">
      <span class="csp-step-letter">${esc(info.letter)}</span>
      <span class="csp-step-name">${esc(nm2)}</span>
      <span class="csp-step-count">${info.count}</span>${gloLabel}
    </div>`;
  }).join('');

  // Coverage check (only if files are loaded)
  let coverageHtml = '';
  const glFile = state.glCodeTitles || {};
  const prFile = state.prCodeTypes  || {};
  const cfgGL  = new Set(rows.map(r => (r.gl_code || '').trim()).filter(Boolean));
  const cfgPR  = new Set(rows.map(r => (r.pay_code || '').trim().toUpperCase()).filter(Boolean));

  if (Object.keys(glFile).length) {
    const fileGLCodes = Object.keys(glFile);
    const missing = fileGLCodes.filter(c => !cfgGL.has(c));
    const extra   = [...cfgGL].filter(c => !glFile[c] && c !== '');
    const glOk    = missing.length === 0;
    const glBadge = missing.length
      ? missing.map(c => `<span class="csp-cov-missing">${esc(c)}</span>`).join(' ')
      : '';
    coverageHtml += `<div class="csp-cov-item">
      <span class="${glOk ? 'csp-cov-ok' : 'csp-cov-warn'}">${glOk ? '✓' : '⚠'}</span>
      <span>GL codes: ${fileGLCodes.length - missing.length}/${fileGLCodes.length} covered</span>
      ${glBadge}
      ${extra.length ? `<span style="font-size:11px;color:var(--text-3)">(+${extra.length} config-only)</span>` : ''}
    </div>`;
  }
  if (Object.keys(prFile).length) {
    const filePR = Object.keys(prFile).map(c => c.toUpperCase());
    // prFile values may be objects {code_type, title} or plain strings
    const missing = filePR.filter(c => !cfgPR.has(c));
    const prOk   = missing.length === 0;
    const prBadge = missing.length
      ? missing.slice(0, 6).map(c => `<span class="csp-cov-missing">${esc(c)}</span>`).join(' ')
        + (missing.length > 6 ? ` <span style="font-size:11px;color:var(--text-3)">+${missing.length-6} more</span>` : '')
      : '';
    coverageHtml += `<div class="csp-cov-item">
      <span class="${prOk ? 'csp-cov-ok' : 'csp-cov-warn'}">${prOk ? '✓' : '⚠'}</span>
      <span>Pay codes: ${filePR.length - missing.length}/${filePR.length} covered</span>
      ${prBadge}
    </div>`;
  }

  const glOnlyNote = glOnlyRows.length
    ? `<span style="font-size:12px;color:var(--text-2)"> · ${glOnlyRows.length} GL-Only account${glOnlyRows.length>1?'s':''}: ${glOnlyRows.map(r=>r.gl_code).join(', ')}</span>`
    : '';

  el.innerHTML = `<div class="csp-wrap">
    <div class="csp-top">
      <span class="csp-headline">${rows.length} mapping rows · ${Object.keys(stepMap).length} steps</span>${glOnlyNote}
    </div>
    <div class="csp-steps">${tiles}</div>
    ${coverageHtml ? `<div class="csp-coverage">${coverageHtml}</div>` : ''}
  </div>`;
}

function showSavedBadge() {
  const el = document.getElementById('config-saved-badge');
  if (el) el.style.display = 'inline-flex';
}
function hideSavedBadge() {
  const el = document.getElementById('config-saved-badge');
  if (el) el.style.display = 'none';
}

// ── AI Table Assistant — chat history ────────────────────────────────────
const _aiHistory = [];

function _escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _renderChatHistory() {
  const el = document.getElementById('ai-chat-history');
  if (!el || !_aiHistory.length) return;
  el.style.display = 'block';
  el.innerHTML = _aiHistory.map(item => `
    <div class="ai-cmd-item">
      <div class="ai-cmd-user">
        <span class="ai-cmd-icon">▶</span>
        <span class="ai-cmd-text">${_escHtml(item.cmd)}</span>
        <span class="ai-cmd-time">${item.time}</span>
      </div>
      <div class="ai-cmd-result ${item.ok ? 'ai-cmd-ok' : 'ai-cmd-err'}">${_escHtml(item.result)}</div>
    </div>`).join('');
  el.scrollTop = el.scrollHeight;
}

function _addHistory(cmd, result, ok) {
  const now = new Date();
  const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  _aiHistory.push({ cmd, result, ok, time });
  if (_aiHistory.length > 8) _aiHistory.shift();
  _renderChatHistory();
}

// ── Configuration method tab switcher ────────────────────────────────────
function switchCfgTab(tab) {
  ['upload', 'ai', 'manual'].forEach(t => {
    const body = document.getElementById(`cfg-tab-${t}`);
    const btn  = document.querySelector(`.cfg-method-tab[data-tab="${t}"]`);
    if (body) body.style.display = t === tab ? '' : 'none';
    if (btn)  btn.classList.toggle('active', t === tab);
  });
}

// ── Config Excel import via drop zone ────────────────────────────────────
async function handleCfgImportDrop(file) {
  if (!file) return;

  const inner   = document.getElementById('cfg-import-inner');
  const alertEl = document.getElementById('cfg-upload-alert');
  if (alertEl) alertEl.style.display = 'none';

  // Show uploading spinner
  if (inner) inner.innerHTML = `
    <div class="cfg-zone-uploading">
      <div class="cfg-zone-spinner"></div>
      <div class="cfg-import-label">Reading <strong>${esc(file.name)}</strong>…</div>
    </div>`;

  const fd = new FormData();
  fd.append('file',        file);
  fd.append('client_name', getClient());

  try {
    const res  = await fetch(`${API}/api/mapping-config/import`, { method: 'POST', body: fd });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      _resetImportZone();
      const msg = data.detail || 'Could not parse the file. Make sure it matches the expected format.';
      if (alertEl) { alertEl.textContent = msg; alertEl.style.display = ''; }
      return;
    }

    // Show success state with preview summary
    if (inner) inner.innerHTML = `
      <div class="cfg-zone-success">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="#059669" stroke-width="1.8"/>
          <polyline points="8,12 11,15 16,9" stroke="#059669" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div>
          <div class="cfg-zone-success-name">${esc(file.name)}</div>
          <div class="cfg-zone-success-meta">${data.row_count} rows ready to load</div>
        </div>
        <button class="cfg-zone-reupload" onclick="_resetImportZone()" title="Upload a different file">✕</button>
      </div>
      <div class="cfg-import-preview-actions">
        <button class="btn btn-blue btn-sm" onclick="_applyImportedRows(${JSON.stringify(data.rows).replace(/"/g, '&quot;')})">
          Load ${data.row_count} rows into table
        </button>
        <span class="cfg-import-preview-note">Review the table, then click Save to apply permanently.</span>
      </div>`;

    // Reset the file input so the same file can be re-selected if needed
    const input = document.getElementById('cfg-import-file-input');
    if (input) input.value = '';

  } catch (e) {
    _resetImportZone();
    if (alertEl) { alertEl.textContent = `Error: ${e.message}`; alertEl.style.display = ''; }
  }
}

function _applyImportedRows(rows) {
  state.mappingRows = rows;
  renderMappingConfigTable(state.mappingRows);
  _resetImportZone();
  switchCfgTab('manual');
  showAlert('cfg-success', `${rows.length} rows loaded from file — review the table and click Save to apply.`);
}

function _resetImportZone() {
  const inner = document.getElementById('cfg-import-inner');
  if (!inner) return;
  inner.innerHTML = `
    <svg width="38" height="38" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="3" width="18" height="18" rx="3" stroke="#4F6BF5" stroke-width="1.4"/>
      <path d="M8 12h3V8h2v4h3l-4 4-4-4z" fill="#4F6BF5"/>
      <line x1="7" y1="18" x2="17" y2="18" stroke="#4F6BF5" stroke-width="1.3" stroke-linecap="round"/>
    </svg>
    <div class="cfg-import-label">Drop your configuration Excel file here</div>
    <div class="cfg-import-sub">or click to browse &nbsp;·&nbsp; .xlsx / .xls only</div>
    <input type="file" class="cfg-zone-input" id="cfg-import-file-input"
      accept=".xlsx,.xls" onchange="handleCfgImportDrop(this.files[0])">`;
}

// Fill the textarea from an example chip
function aiChip(btn) {
  const ta = document.getElementById('ai-description');
  if (ta) { ta.value = btn.textContent.trim(); ta.focus(); }
}

async function generateMappingWithAI() {
  const description = document.getElementById('ai-description').value.trim();
  if (!description) {
    showAlert('ai-alert', 'Please type a command or description.');
    return;
  }
  hideAlert('ai-alert');

  const btn = document.getElementById('btn-ai-generate');
  btn.disabled = true;
  btn.innerHTML = '<span class="ai-send-icon">✦</span> Thinking…';

  // Collect current non-empty rows to send as context
  const currentRows = collectMappingRows().filter(
    r => r.recon_step || r.gl_code || r.pay_code
  );
  const prevCount = currentRows.length;
  const isEdit    = prevCount > 0;

  showLoading(isEdit ? 'AI is updating your table…' : 'AI is generating your configuration…');

  try {
    const res  = await fetch(`${API}/api/generate-mapping`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        client_name:  getClient(),
        description,
        current_rows: currentRows,
      }),
    });
    const data = await res.json();
    hideLoading();
    btn.disabled = false;
    btn.innerHTML = '<span class="ai-send-icon">✦</span> Ask AI';

    if (!res.ok || !data.ok) {
      const msg = data.detail || 'AI request failed. Check AWS Bedrock credentials.';
      showAlert('ai-alert', msg);
      _addHistory(description, '✕ ' + msg, false);
      return;
    }

    const newRows  = data.rows || [];
    const delta    = newRows.length - prevCount;
    const deltaStr = delta > 0 ? `+${delta} rows added` :
                     delta < 0 ? `${Math.abs(delta)} rows removed` : 'rows updated';
    const summary  = `✓ ${isEdit ? 'Table updated' : 'Config generated'} — ${newRows.length} rows total (${deltaStr})`;

    state.mappingRows = newRows;
    renderMappingConfigTable(state.mappingRows);

    _addHistory(description, summary, true);
    document.getElementById('ai-description').value = '';

    // Show truncation warning if the AI response was cut off but partially recovered
    if (data.warning) {
      const alertEl = document.getElementById('ai-alert');
      if (alertEl) {
        alertEl.className = 'alert alert-warning show';
        alertEl.textContent = data.warning;
      }
    } else {
      hideAlert('ai-alert');
    }

  } catch (e) {
    hideLoading();
    btn.disabled = false;
    btn.innerHTML = '<span class="ai-send-icon">✦</span> Ask AI';
    const msg = `Error: ${e.message}`;
    showAlert('ai-alert', msg);
    _addHistory(description, '✕ ' + msg, false);
  }
}

async function downloadConfigExcel() {
  const client = getClient();
  // Save current state first so the export reflects the latest edits
  const rows = collectMappingRows();
  if (rows.length) {
    await fetch(`${API}/api/mapping-config`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({client_name: client, rows}),
    });
  }
  window.location.href = `${API}/api/mapping-config/export?client_name=${enc(client)}`;
}

function triggerImportConfig() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.xlsx,.xls';
  input.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    showLoading('Importing configuration from Excel…');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('client_name', getClient());
    try {
      const res  = await fetch(`${API}/api/mapping-config/import`, {method: 'POST', body: fd});
      const data = await res.json();
      hideLoading();
      if (!res.ok || !data.ok) {
        showAlert('cfg-alert', data.detail || 'Import failed.');
        return;
      }
      if (!confirm(`Import ${data.row_count} rows from "${file.name}"?\nThis will replace the current configuration.`)) return;
      state.mappingRows = data.rows;
      renderMappingConfigTable(state.mappingRows);
      showAlert('cfg-success', `Imported ${data.row_count} rows from ${file.name}. Review and click Save to apply.`);
    } catch (ex) {
      hideLoading();
      showAlert('cfg-alert', `Import error: ${ex.message}`);
    }
  };
  input.click();
}
