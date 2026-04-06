/* ═══════════════════════════════════════════════════════════════════
   app.js — Core: state, constants, session, navigation, shared utils
   Page-specific logic: upload.js · config.js · results.js
   ═══════════════════════════════════════════════════════════════════ */

const API = '';

// ── Column role definitions ───────────────────────────────────────────────
const REQUIRED_ROLES = {
  gl_report: [
    { role: 'trans_source',  label: 'Transaction Source', hint: 'Filters PRS payroll transactions (e.g. TransSource)',   required: true  },
    { role: 'gl_code',       label: 'GL Code / Account',  hint: 'Account code number (e.g. AcctCode, GL Code)',         required: true  },
    { role: 'gl_title',      label: 'GL Title / Name',    hint: 'Account description or name',                          required: true  },
    { role: 'net_amount',    label: 'Net Amount',         hint: 'Net / debit / balance amount column',                  required: true  },
    { role: 'debit_amount',  label: 'Debit Amount',       hint: 'Debit column (if separate from credit)',               required: false },
    { role: 'credit_amount', label: 'Credit Amount',      hint: 'Credit column (if separate from debit)',               required: false },
    { role: 'date',          label: 'Date / Posting Date', hint: 'PostToDate, EffectiveDate, TranDate — used for year filtering', required: false },
  ],
  payroll_register: [
    { role: 'pay_code',         label: 'Pay Code',          hint: 'e.g. Wages, MC, SS, FWT, Dental16',                 required: true  },
    { role: 'code_type',        label: 'Code Type',         hint: 'EARNING, BENEFIT, DEDUCT, or TAXES',                required: true  },
    { role: 'earn_amount',      label: 'Earnings Amount',   hint: 'EarnAmt column (gross wages)',                       required: true  },
    { role: 'benefit_amount',   label: 'Benefit Amount',    hint: 'BeneAmt column (employer benefit cost)',             required: true  },
    { role: 'deduction_amount', label: 'Deduction Amount',  hint: 'DeducAmt column (employee deductions)',             required: true  },
    { role: 'ee_tax',           label: 'Employee Tax',      hint: 'EETax column (employee tax withholding)',            required: true  },
    { role: 'er_tax',           label: 'Employer Tax',      hint: 'ERTax column (employer tax contributions)',          required: true  },
    { role: 'net_amount',       label: 'Net Pay Amount',    hint: 'NetAmt column (for bank cross-check, optional)',     required: false },
    { role: 'date',             label: 'Pay Date / Period Date', hint: 'PayDate, CheckDate, Period End Date — used for year filtering', required: false },
  ],
};

const AMOUNT_COL_OPTIONS = ['EarnAmt', 'BeneAmt', 'DeducAmt', 'EETax', 'ERTax', 'EETax & ERTax', 'NetAmt'];
const CODE_TYPE_OPTIONS  = ['EARNING', 'BENEFIT', 'DEDUCT', 'TAXES', ''];

// ── App state ─────────────────────────────────────────────────────────────
const state = {
  sessionId:   null,
  configSaved: false,
  mappingRows: [],
  files:       { gl_report: null, payroll_register: null },
  confirmed:   { gl_report: false, payroll_register: false },
  uploadData:  { gl_report: null, payroll_register: null },
  glCodeTitles: {},   // { "5000": "Salaries & Wages", … } from uploaded GL file
  prCodeTypes:  {},   // { "Wages": "EARNING", "Dental16": "BENEFIT", … } from uploaded PR
  results:     null,
  auth: { token: null, userId: null, displayName: null, username: null },
};

// ── Init ──────────────────────────────────────────────────────────────────
function enterTool() {
  const landing = document.getElementById('landing-page');
  landing.classList.add('hide');
  setTimeout(() => {
    landing.style.display = 'none';
    document.getElementById('main-app').style.display = 'flex';
    showOnboardingModal();
  }, 380);
}

// ── Onboarding modal (Client + Period) ────────────────────────────────────
function showOnboardingModal() {
  const savedClient = localStorage.getItem('pr_client_name');
  const savedPeriod  = localStorage.getItem('pr_period');
  const obClient = document.getElementById('ob-client');
  const obPeriod  = document.getElementById('ob-period');
  if (savedClient && savedClient !== 'default') obClient.value = savedClient;
  if (savedPeriod)  obPeriod.value  = savedPeriod;
  document.getElementById('onboarding-modal').style.display = 'flex';
  obClient.focus();
}

function completeOnboarding() {
  const clientVal = document.getElementById('ob-client').value.trim() || 'default';
  const periodVal  = document.getElementById('ob-period').value.trim();
  const clientInput = document.getElementById('cfg-client');
  const periodInput = document.getElementById('cfg-period');
  clientInput.value = clientVal;
  periodInput.value = periodVal;
  localStorage.setItem('pr_client_name', clientVal);
  if (periodVal) localStorage.setItem('pr_period', periodVal);
  document.getElementById('onboarding-modal').style.display = 'none';
  loadMappingConfig();
  navigate('dashboard');  // sets #dashboard so refresh returns here
}

function skipOnboarding() {
  document.getElementById('onboarding-modal').style.display = 'none';
  navigate('dashboard');  // sets #dashboard so refresh returns here
}

document.addEventListener('DOMContentLoaded', async () => {

  const clientInput = document.getElementById('cfg-client');
  const periodInput = document.getElementById('cfg-period');
  const savedClient = localStorage.getItem('pr_client_name');
  const savedPeriod = localStorage.getItem('pr_period');
  if (savedClient) clientInput.value = savedClient;
  if (savedPeriod) periodInput.value = savedPeriod;

  clientInput.addEventListener('input', () => {
    localStorage.setItem('pr_client_name', clientInput.value.trim());
    updateDashboard();
  });
  periodInput.addEventListener('input', () => {
    localStorage.setItem('pr_period', periodInput.value.trim());
  });

  let _lastLoadedClient = clientInput.value.trim() || 'default';
  clientInput.addEventListener('blur', () => {
    const current = clientInput.value.trim() || 'default';
    if (current !== _lastLoadedClient) {
      _lastLoadedClient = current;
      loadMappingConfig();
    }
  });

  const sessionRestored = await createSession();
  initAuth();           // restore auth from localStorage
  setupNavigation();
  setupUploadZones();   // upload.js
  setupTabs();
  await loadMappingConfig();  // config.js
  _lastLoadedClient = clientInput.value.trim() || 'default';

  const initPage = window.location.hash.slice(1);
  const hasValidPage = initPage && !!document.getElementById(`page-${initPage}`);

  if (hasValidPage) {
    // User refreshed while inside the tool — skip landing page and onboarding
    document.getElementById('landing-page').style.display = 'none';
    document.getElementById('main-app').style.display     = 'flex';
    if (sessionRestored) await restoreUploadState();  // upload.js
    updateDashboard();
    updatePreflight();
    loadRecentRuns();
    navigate(initPage, false);  // restore exact page without adding a history entry
  } else {
    updateDashboard();
    updatePreflight();
    loadRecentRuns();
    // Default: landing page is visible; user clicks "Enter Tool" to proceed
  }
});

// ── Session ───────────────────────────────────────────────────────────────
function _clearUploadCache() {
  ['gl_report', 'payroll_register'].forEach(ft => {
    sessionStorage.removeItem(`pr_upload_${ft}`);
    sessionStorage.removeItem(`pr_confirmed_${ft}`);
  });
}

async function createSession() {
  try {
    const saved = sessionStorage.getItem('pr_session_id');
    if (saved) {
      const r = await fetch(`${API}/api/session/${saved}/status`);
      if (r.ok) { state.sessionId = saved; return true; }  // restored
      _clearUploadCache();  // session expired — clear stale file cache
    }
    const res  = await fetch(`${API}/api/session`, { method: 'POST' });
    const data = await res.json();
    state.sessionId = data.session_id;
    sessionStorage.setItem('pr_session_id', state.sessionId);
    return false;  // new session
  } catch (e) {
    showGlobalError('Cannot connect to the server. Make sure python run.py is running.');
    return false;
  }
}

// ── New Reconciliation — reset all state and start fresh ─────────────────
async function startNewReconciliation() {
  showLoading('Resetting session…');
  try {
    // Reset backend session
    if (state.sessionId) {
      await fetch(`${API}/api/session/${state.sessionId}/reset`, { method: 'POST' });
    }
  } catch (_) {}

  // Reset frontend state
  state.configSaved      = false;
  state.mappingRows      = [];
  state.files            = { gl_report: null, payroll_register: null };
  state.confirmed        = { gl_report: false, payroll_register: false };
  state.uploadData       = { gl_report: null, payroll_register: null };
  state.glCodeTitles     = {};
  state.prCodeTypes      = {};
  state.results          = null;
  state._historyRecordId = null;
  state._defaultTemplate = null;

  // Clear persisted upload cache so a reload doesn't restore stale files
  _clearUploadCache();

  // Reset upload UI for both zones
  resetUpload('gl_report');
  resetUpload('payroll_register');

  // Reset config table
  hideSavedBadge();
  hideAlert('cfg-alert');
  hideAlert('cfg-success');

  // Hide results section + new-recon bar
  const resSection = document.getElementById('results-section');
  if (resSection) resSection.style.display = 'none';
  const newReconBar = document.getElementById('new-recon-bar');
  if (newReconBar) newReconBar.style.display = 'none';
  document.getElementById('results-status-banner').innerHTML = '';

  // Reload mapping config for current client
  hideLoading();
  await loadMappingConfig();
  updateDashboard();
  navigate('upload');
}


// ── Navigation ────────────────────────────────────────────────────────────
function setupNavigation() {
  document.querySelectorAll('.nav-item[data-page]').forEach(item => {
    item.addEventListener('click', () => navigate(item.dataset.page));
  });
  // Browser back / forward support
  window.addEventListener('popstate', e => {
    const page = e.state?.page || window.location.hash.slice(1) || 'dashboard';
    if (document.getElementById(`page-${page}`)) navigate(page, false);
  });
}

function navigate(page, pushHistory = true) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item[data-page]').forEach(n => n.classList.remove('active'));
  document.getElementById(`page-${page}`)?.classList.add('active');
  document.querySelector(`.nav-item[data-page="${page}"]`)?.classList.add('active');
  window.scrollTo(0, 0);
  if (pushHistory && window.location.hash.slice(1) !== page) {
    history.pushState({ page }, '', `#${page}`);
  }
  if (page === 'results')   updatePreflight();
  if (page === 'dashboard') { updateDashboard(); loadRecentRuns(); }
  if (page === 'history')   loadHistory();
}

// ── Dashboard ─────────────────────────────────────────────────────────────
function updateDashboard() {
  const client = getClient();

  if (state.configSaved) {
    setTile('config', 'st-ok',   'ok',   '✓ Saved',         `${state.mappingRows.length} mapping rows · ${client}`);
  } else {
    setTile('config', 'st-todo', 'todo', '⚙ Not saved',     `Using default template · ${client}`);
  }

  if (state.confirmed['gl_report']) {
    const d = state.uploadData['gl_report'];
    setTile('gl', 'st-ok', 'ok', '✓ Confirmed', d ? `${d.row_count.toLocaleString()} rows · ${d.filename}` : 'Column mapping confirmed');
  } else if (state.files['gl_report']) {
    setTile('gl', 'st-warn', 'warn', '⚠ Pending', 'Uploaded — confirm column mapping');
  } else {
    setTile('gl', 'st-todo', 'todo', '↑ Upload required', 'GL export — Excel, CSV, TSV, ODS or XLSB');
  }

  if (state.confirmed['payroll_register']) {
    const d = state.uploadData['payroll_register'];
    setTile('pr', 'st-ok', 'ok', '✓ Confirmed', d ? `${d.row_count.toLocaleString()} rows · ${d.filename}` : 'Column mapping confirmed');
  } else if (state.files['payroll_register']) {
    setTile('pr', 'st-warn', 'warn', '⚠ Pending', 'Uploaded — confirm column mapping');
  } else {
    setTile('pr', 'st-todo', 'todo', '↑ Upload required', 'Payroll Register — Excel, CSV, TSV, ODS or XLSB');
  }

  if (state.results) {
    const s = state.results.summary_stats;
    setTile('results', 'st-ok', s?.is_clean ? 'ok' : 'warn',
      s?.is_clean ? '✓ Clean' : `⚠ ${s?.variances} variance(s)`,
      `${s?.matched} matched · variance $${Math.abs(s?.total_variance || 0).toFixed(2)}`);
  } else {
    const ready = state.confirmed['gl_report'] && state.confirmed['payroll_register'];
    setTile('results', ready ? 'st-info' : 'st-todo', ready ? 'info' : 'todo',
      ready ? '▶ Ready to run' : '◈ Waiting',
      ready ? 'All files confirmed — click Run' : 'Complete steps 1–3 first');
  }

  const needConfig = !state.configSaved;
  const needUpload = !state.confirmed['gl_report'] || !state.confirmed['payroll_register'];
  setPill('nav-pill-config',  needConfig);
  setPill('nav-pill-upload',  needUpload);
  setPill('nav-pill-results', !!state.results);
}

function setTile(key, tileCls, statusCls, statusText, detailText) {
  const tileEl   = document.getElementById(`tile-${key}`);
  const statusEl = document.getElementById(`tile-${key}-status`);
  const detailEl = document.getElementById(`tile-${key}-detail`);
  if (!tileEl) return;
  tileEl.className = `status-tile ${tileCls}`;
  if (statusEl) { statusEl.className = `tile-status ${statusCls}`; statusEl.textContent = statusText; }
  if (detailEl) detailEl.textContent = detailText;
}

function setPill(id, show) {
  const el = document.getElementById(id);
  if (el) el.style.display = show ? 'flex' : 'none';
}

// ── Tabs ──────────────────────────────────────────────────────────────────
function setupTabs() {
  document.addEventListener('click', e => {
    const btn = e.target.closest('.tab-btn[data-tab-group]');
    if (!btn) return;
    const tabBar = btn.closest('.tab-bar');
    if (!tabBar) return;
    const container = tabBar.parentElement;
    container.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    container.querySelector(`#${btn.dataset.tab}`)?.classList.add('active');
    tabBar.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
}

// ── Shared utilities ──────────────────────────────────────────────────────
function getClient() {
  return document.getElementById('cfg-client')?.value?.trim() || 'default';
}
function enc(s)   { return encodeURIComponent(s); }
function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function showLoading(msg = 'Processing…') {
  document.getElementById('loading-text').textContent = msg;
  document.getElementById('loading-overlay').classList.add('show');
}
function hideLoading() {
  document.getElementById('loading-overlay').classList.remove('show');
}
function showGlobalError(msg) {
  const el = document.getElementById('global-error');
  if (el) { el.textContent = msg; el.style.display = 'block'; el.classList.add('show'); }
}
function showAlert(id, msg) {
  const el = document.getElementById(id);
  if (el) { el.textContent = msg; el.classList.add('show'); }
}
function hideAlert(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('show');
}

// ── Authentication ────────────────────────────────────────────────────────
function initAuth() {
  const token       = localStorage.getItem('pr_auth_token');
  const userId      = localStorage.getItem('pr_auth_user_id');
  const displayName = localStorage.getItem('pr_auth_display_name');
  const username    = localStorage.getItem('pr_auth_username');
  if (token && userId) {
    state.auth = { token, userId, displayName: displayName || username, username };
    _applyAuthUI();
    // Verify token is still valid in background
    fetch(`${API}/api/auth/verify?token=${enc(token)}`)
      .then(r => { if (!r.ok) { _clearAuth(); _applyAuthUI(); } })
      .catch(() => {});
  }
}

function _applyAuthUI() {
  const signedIn = !!state.auth.userId;
  document.getElementById('auth-signin-btn').style.display = signedIn ? 'none' : 'flex';
  document.getElementById('auth-badge').style.display      = signedIn ? 'flex' : 'none';
  if (signedIn) {
    const name = state.auth.displayName || state.auth.username || 'User';
    document.getElementById('auth-display-name').textContent = name;
    document.getElementById('auth-avatar').textContent = name.charAt(0).toUpperCase();
  }
}

function _clearAuth() {
  state.auth = { token: null, userId: null, displayName: null, username: null };
  localStorage.removeItem('pr_auth_token');
  localStorage.removeItem('pr_auth_user_id');
  localStorage.removeItem('pr_auth_display_name');
  localStorage.removeItem('pr_auth_username');
}

function _saveAuth(data) {
  state.auth = {
    token:       data.token,
    userId:      data.user_id,
    displayName: data.display_name || data.username,
    username:    data.username,
  };
  localStorage.setItem('pr_auth_token',        data.token);
  localStorage.setItem('pr_auth_user_id',      data.user_id);
  localStorage.setItem('pr_auth_display_name', data.display_name || data.username);
  localStorage.setItem('pr_auth_username',     data.username);
}

function openAuthModal() {
  const modal = document.getElementById('auth-modal');
  document.getElementById('login-error').textContent = '';
  document.getElementById('reg-error').textContent   = '';
  modal.showModal();
}

function closeAuthModal(e) {
  if (e && e.target !== document.getElementById('auth-modal')) return;
  document.getElementById('auth-modal').close();
}

function switchAuthTab(tab) {
  document.getElementById('auth-panel-login').style.display    = tab === 'login'    ? '' : 'none';
  document.getElementById('auth-panel-register').style.display = tab === 'register' ? '' : 'none';
  document.getElementById('auth-tab-login').classList.toggle('active',    tab === 'login');
  document.getElementById('auth-tab-register').classList.toggle('active', tab === 'register');
}

async function submitLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errEl    = document.getElementById('login-error');
  errEl.textContent = '';
  if (!username || !password) { errEl.textContent = 'Please enter username and password.'; return; }
  try {
    const res  = await fetch(`${API}/api/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.detail || 'Login failed.'; return; }
    _saveAuth(data);
    _applyAuthUI();
    document.getElementById('auth-modal').close();
    // Reload history with user filter if on history page
    if (window.location.hash === '#history') loadHistory();
  } catch (e) {
    errEl.textContent = 'Could not connect to server.';
  }
}

async function submitRegister() {
  const username     = document.getElementById('reg-username').value.trim();
  const displayName  = document.getElementById('reg-display-name').value.trim();
  const password     = document.getElementById('reg-password').value;
  const errEl        = document.getElementById('reg-error');
  errEl.textContent  = '';
  if (!username || !password) { errEl.textContent = 'Username and password are required.'; return; }
  try {
    const res  = await fetch(`${API}/api/auth/register`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, display_name: displayName }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.detail || 'Registration failed.'; return; }
    _saveAuth(data);
    _applyAuthUI();
    document.getElementById('auth-modal').close();
    if (window.location.hash === '#history') loadHistory();
  } catch (e) {
    errEl.textContent = 'Could not connect to server.';
  }
}

function signOut() {
  _clearAuth();
  _applyAuthUI();
  // Refresh history page if active (will show sign-in prompt)
  if (window.location.hash === '#history') loadHistory();
}
