// ── Bootstrap data ────────────────────────────────────────
let ORDERS    = [];
let BACKEND   = {};
let APP_CFG   = { supported_currencies: ['INR', 'USD'], default_currency: 'INR' };

function readBootData() {
  try { ORDERS  = JSON.parse(document.getElementById('ordersBoot').textContent  || '[]'); } catch(_) {}
  try { BACKEND = JSON.parse(document.getElementById('backendBoot').textContent || '{}'); } catch(_) {}
  try { APP_CFG = JSON.parse(document.getElementById('appConfig').textContent   || '{}'); } catch(_) {}
}

// ── Init ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  readBootData();
  initSidebar();
  initOrderTypeSelector();
  initCurrencyDropdowns();
  initSearch();
  initOrdersRefresh();
  initOrderInspector();
  initFormSubmission();
  renderOrdersTable(ORDERS);
  updateStats(ORDERS);
  updateBackendInfo();
});

// ── SIDEBAR ────────────────────────────────────────────────
function initSidebar() {
  const navItems = document.querySelectorAll('.nav-item');
  navItems.forEach(item => {
    item.addEventListener('click', function(e) {
      e.preventDefault();
      const sectionId = this.dataset.section;
      navItems.forEach(n => n.classList.remove('active'));
      document.querySelectorAll('.section-panel').forEach(s => s.classList.remove('active'));
      this.classList.add('active');
      const target = document.getElementById(sectionId);
      if (target) target.classList.add('active');

      if (sectionId === 'orders') {
        fetch('/api/erp/orders').then(r => r.ok ? r.json() : null).then(d => {
          if (d) { ORDERS = d.orders || []; renderOrdersTable(ORDERS); }
        }).catch(() => renderOrdersTable(ORDERS));
      }
      if (sectionId === 'analytics') {
        fetch('/api/erp/orders').then(r => r.ok ? r.json() : null).then(d => {
          if (d) { ORDERS = d.orders || []; updateStats(ORDERS); }
        }).catch(() => updateStats(ORDERS));
      }
    });
  });
}

// ── ORDER TYPE SELECTOR ────────────────────────────────────
function initOrderTypeSelector() {
  const typeBtns = document.querySelectorAll('.type-btn');
  typeBtns.forEach(btn => {
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      typeBtns.forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.form-container').forEach(c => {
        c.classList.remove('active');
        c.classList.add('hidden');
      });
      this.classList.add('active');
      const selectedForm = document.getElementById(this.dataset.type + '-form-container');
      if (selectedForm) {
        selectedForm.classList.add('active');
        selectedForm.classList.remove('hidden');
        const first = selectedForm.querySelector('input:not([type=hidden]), select, textarea');
        if (first) setTimeout(() => first.focus(), 80);
      }
    });
  });
  const pujaForm = document.getElementById('puja-form-container');
  if (pujaForm) { pujaForm.classList.add('active'); pujaForm.classList.remove('hidden'); }
}

// ── CURRENCY DROPDOWNS ─────────────────────────────────────
function initCurrencyDropdowns() {
  const currencies = APP_CFG.supported_currencies || ['INR', 'USD', 'EUR'];
  const defaultCur = APP_CFG.default_currency || 'INR';

  document.querySelectorAll('select[name="currency"]').forEach(sel => {
    const hasRealOptions = Array.from(sel.options).some(o => o.value && !o.value.includes('{'));
    if (!hasRealOptions || sel.options.length === 0) {
      sel.innerHTML = currencies.map(c =>
        `<option value="${c}"${c === defaultCur ? ' selected' : ''}>${c}</option>`
      ).join('');
    }
  });
}

// ── SEARCH & FILTER ────────────────────────────────────────
function initSearch() {
  ['orderSearch', 'orderTypeFilter', 'paymentStatusFilter'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', filterOrders);
  });
}

function filterOrders() {
  const term   = (document.getElementById('orderSearch')?.value || '').toLowerCase();
  const type   = document.getElementById('orderTypeFilter')?.value  || '';
  const status = document.getElementById('paymentStatusFilter')?.value || '';

  const tbody = document.getElementById('ordersTableBody');
  if (!tbody) return;

  let visible = 0;
  tbody.querySelectorAll('tr').forEach(row => {
    let show = true;
    if (term   && !row.textContent.toLowerCase().includes(term))   show = false;
    if (type   && !row.dataset.type?.toLowerCase().includes(type)) show = false;
    if (status && row.dataset.status?.toLowerCase() !== status)    show = false;
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  });

  const empty = document.getElementById('ordersEmptyState');
  if (empty) empty.style.display = visible === 0 ? 'block' : 'none';
}

// ── ORDERS REFRESH ─────────────────────────────────────────
function initOrdersRefresh() {
  const btn = document.getElementById('refreshOrders');
  if (!btn) return;
  btn.addEventListener('click', async function() {
    const orig = this.textContent;
    this.disabled = true;
    this.textContent = 'Refreshing…';
    try {
      const res = await fetch('/api/erp/orders');
      if (res.ok) {
        const data = await res.json();
        ORDERS = data.orders || [];
        renderOrdersTable(ORDERS);
        updateStats(ORDERS);
      }
    } catch(_) {}
    this.disabled = false;
    this.textContent = orig;
  });
}

// ── RENDER ORDERS TABLE ────────────────────────────────────
function renderOrdersTable(orders) {
  const tbody = document.getElementById('ordersTableBody');
  const empty = document.getElementById('ordersEmptyState');
  if (!tbody) return;

  tbody.innerHTML = '';

  if (!orders || orders.length === 0) {
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  orders.forEach(o => {
    const tr = document.createElement('tr');
    tr.dataset.type   = o.order_type || '';
    tr.dataset.status = (o.payment_status || '').toLowerCase();

    const service   = o.puja_name || o.item_name || '—';
    const typeClass = o.order_type === 'puja' ? 'puja' : 'ecommerce';
    const typeLabel = o.order_type === 'puja' ? '🙏 Puja' : '🛒 Ecom';
    const statusCls  = (o.payment_status || 'unpaid').toLowerCase();
    const statusLabel = statusEmoji(o.payment_status) + ' ' + capitalize(o.payment_status || 'unpaid');
    const date   = (o.created_at || o.order_date || '').slice(0, 10) || '—';
    const amount = o.amount ? `${o.currency || ''} ${parseFloat(o.amount).toLocaleString('en-IN')}` : '—';

    tr.innerHTML = `
      <td><span class="order-uid-cell">${esc(o.order_uid)}</span></td>
      <td><span class="type-badge ${typeClass}">${typeLabel}</span></td>
      <td>
        <div class="customer-cell">
          <div class="name">${esc(o.customer_name || '—')}</div>
          <div class="phone">${esc(o.phone || '')}</div>
        </div>
      </td>
      <td>${esc(service)}</td>
      <td class="amount-cell">${amount}</td>
      <td><span class="status-pill ${statusCls}">${statusLabel}</span></td>
      <td>${date}</td>
      <td>
        <div class="table-actions">
          ${o.payment_link ? `<button class="action-btn" onclick="copyLink('${esc(o.payment_link)}')">📋 Copy Link</button>` : ''}
        </div>
      </td>`;
    tbody.appendChild(tr);
  });

  // Refresh inspector dropdown
  const sel = document.getElementById('backendOrderSelect');
  if (sel) {
    sel.innerHTML = '<option value="">Select an order…</option>' +
      orders.map(o => `<option value="${esc(o.order_uid)}">${esc(o.order_uid)} — ${esc(o.customer_name || '')}</option>`).join('');
  }
}

function copyLink(url) {
  navigator.clipboard.writeText(url)
    .then(() => alert('Payment link copied!'))
    .catch(() => prompt('Copy this link:', url));
}

function esc(str) {
  return String(str || '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function capitalize(s) { return s ? s[0].toUpperCase() + s.slice(1) : ''; }

function statusEmoji(s) {
  return { paid: '✅', unpaid: '⏳', pending: '⏸', failed: '❌' }[s] || '•';
}

// ── STATS ──────────────────────────────────────────────────
function updateStats(orders) {
  setText('statTotal',   orders.length);
  setText('statPaid',    orders.filter(o => o.payment_status === 'paid').length);
  setText('statUnpaid',  orders.filter(o => o.payment_status === 'unpaid').length);
  setText('statPending', orders.filter(o => o.payment_status === 'pending').length);
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── BACKEND INFO ───────────────────────────────────────────
function updateBackendInfo() {
  if (!BACKEND || !Object.keys(BACKEND).length) return;
  setText('activePaymentProvider', BACKEND.payment_provider_label || '—');
  const path = document.getElementById('gatewayWebhookPath');
  if (path) path.textContent = BACKEND.webhook_url_path || '—';
  const db = document.getElementById('backendDbPath');
  if (db) db.textContent = BACKEND.db_path || '—';
}

// ── ORDER INSPECTOR ────────────────────────────────────────
function initOrderInspector() {
  const btn    = document.getElementById('inspectBackendOrder');
  const sel    = document.getElementById('backendOrderSelect');
  const output = document.getElementById('backendJson');

  if (btn) {
    btn.addEventListener('click', async function() {
      const uid = sel?.value;
      if (!uid) { output.textContent = 'Select an order to inspect.'; return; }
      try {
        output.textContent = 'Loading…';
        const res  = await fetch(`/api/erp/backend/orders/${encodeURIComponent(uid)}`);
        const data = await res.json();
        output.textContent = JSON.stringify(data, null, 2);
      } catch(e) {
        output.textContent = `Error: ${e.message}`;
      }
    });
  }

  const refreshBtn = document.getElementById('refreshBackend');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async function() {
      const orig = this.textContent;
      this.disabled = true; this.textContent = 'Refreshing…';
      try {
        const res = await fetch('/api/erp/orders');
        if (res.ok) {
          const data = await res.json();
          ORDERS = data.orders || [];
          renderOrdersTable(ORDERS);
          updateStats(ORDERS);
        }
      } catch(_) {}
      this.disabled = false; this.textContent = orig;
    });
  }
}

// ── FORM SUBMISSION ────────────────────────────────────────
function initFormSubmission() {
  // Prevent accidental form submit (Enter key etc.) — button handles everything
  document.querySelectorAll('.order-form').forEach(form => {
    form.addEventListener('submit', e => e.preventDefault());
  });

  document.querySelectorAll('.generate-link').forEach(btn => {
    btn.addEventListener('click', generatePaymentLink);
  });
}

async function generatePaymentLink(e) {
  e.preventDefault();
  const btn       = e.currentTarget;
  const form      = btn.closest('.order-form');
  const messageEl = form.querySelector('.message');
  const linkInput = form.querySelector('[name="payment_link"]');
  const origHTML  = btn.innerHTML;

  // Native HTML5 validation
  if (!form.checkValidity()) {
    form.reportValidity();
    return;
  }

  btn.disabled  = true;
  btn.innerHTML = `<span style="opacity:.7">⏳</span> ${btn.dataset.busyText || 'Generating…'}`;

  try {
    // ── Step 1: Save the order ─────────────────────────────
    const formData = Object.fromEntries(new FormData(form));
    formData.payment_link = ''; // will be filled next
    // Combine country code + phone number into single phone field
    if (formData.phone_country_code && formData.phone_number) {
      formData.phone = formData.phone_country_code + formData.phone_number.replace(/\D/g, '');
    } else if (formData.phone_number) {
      formData.phone = formData.phone_number;
    }
    delete formData.phone_country_code;
    delete formData.phone_number;

    const saveRes = await fetch('/api/erp/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData)
    });
    const saveResult = await saveRes.json();
    console.log('[ERP] save response status:', saveRes.status, saveResult);

    if (!saveRes.ok) {
      showMsg(messageEl, saveResult.error || saveResult.message || 'Failed to save order', 'bad');
      return;
    }

    const order    = saveResult.order || {};
    const orderUid = order.order_uid || saveResult.order_uid || '';
    console.log('[ERP] order.payment_link from save:', order.payment_link);
    console.log('[ERP] order.payment_link_error:', order.payment_link_error);

    // Update order ID in header
    const idEl = form.querySelector('.order-id-value');
    if (idEl && orderUid) idEl.textContent = orderUid;

    // ── Step 2: Read link directly from save response ─────────
    // The server generates the Razorpay link during order creation.
    // We never call a second endpoint — that hits a different Vercel
    // container which has no DB and always 404s the order.
    const paymentLink = order.payment_link || saveResult.payment_link || '';
    const linkError   = order.payment_link_error   || '';

    // ── Step 3: Show result inline ─────────────────────────
    if (linkInput) linkInput.value = paymentLink;

    // Remove any old result bar
    form.querySelector('.link-result-bar')?.remove();

    if (paymentLink) {
      const bar = document.createElement('div');
      bar.className = 'link-result-bar';
      bar.innerHTML = `
        <span class="link-result-url" title="${esc(paymentLink)}">${esc(paymentLink)}</span>
        <button type="button" class="copy-link-btn" data-url="${esc(paymentLink)}">📋 Copy</button>`;
      bar.querySelector('.copy-link-btn').addEventListener('click', function() {
        navigator.clipboard.writeText(this.dataset.url)
          .then(() => { this.textContent = '✅ Copied!'; setTimeout(() => this.textContent = '📋 Copy', 2000); })
          .catch(() => prompt('Copy this link:', this.dataset.url));
      });
      linkInput.closest('.form-group').after(bar);
    }

    let msg, msgType;
    if (paymentLink) {
      msg     = `✅ Order ${orderUid} saved — payment link ready!`;
      msgType = 'ok';
    } else if (linkError) {
      msg     = `⚠️ Order ${orderUid} saved but payment link failed: ${linkError}`;
      msgType = 'bad';
    } else {
      msg     = `✅ Order ${orderUid} saved (no payment link — check gateway config)`;
      msgType = 'ok';
    }
    showMsg(messageEl, msg, msgType);

    // ── Step 4: Refresh orders list silently ──────────────
    fetch('/api/erp/orders').then(r => r.ok ? r.json() : null).then(d => {
      if (d) { ORDERS = d.orders || []; renderOrdersTable(ORDERS); updateStats(ORDERS); }
    }).catch(() => {});

  } catch(err) {
    showMsg(messageEl, `Error: ${err.message}`, 'bad');
  } finally {
    btn.disabled  = false;
    btn.innerHTML = origHTML;
  }
}

function showMsg(el, text, type) {
  if (!el) return;
  el.textContent = text;
  el.className   = `message ${type}`;
}
