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
  initPhoneCodeDropdowns();
  initSearch();
  initOrdersRefresh();
  initOrderInspector();
  initFormSubmission();
  initBackfillButtons();
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
        loadAnalytics();
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

// ── PHONE COUNTRY CODES ────────────────────────────────────
// [ISO country, name, dial code]. India first, rest alphabetical.
const PHONE_COUNTRIES = [
  ['AC', 'Ascension Island', '247'],
  ['AQ', 'Antarctica', '672'],
  ['AX', 'Aland Islands', '358'],
  ['BL', 'St Barthelemy', '590'],
  ['BQ', 'Caribbean Netherlands', '599'],
  ['CC', 'Cocos (Keeling) Islands', '61'],
  ['CX', 'Christmas Island', '61'],
  ['EH', 'Western Sahara', '212'],
  ['MF', 'St Martin', '590'],
  ['NF', 'Norfolk Island', '672'],
  ['PM', 'St Pierre and Miquelon', '508'],
  ['SH', 'St Helena', '290'],
  ['SJ', 'Svalbard and Jan Mayen', '47'],
  ['PN', 'Pitcairn Islands', '64'],
  ['TA', 'Tristan da Cunha', '290'],
  ['IN', 'India', '91'],
  ['AF', 'Afghanistan', '93'],
  ['AL', 'Albania', '355'],
  ['DZ', 'Algeria', '213'],
  ['AS', 'American Samoa', '1684'],
  ['AD', 'Andorra', '376'],
  ['AO', 'Angola', '244'],
  ['AI', 'Anguilla', '1264'],
  ['AG', 'Antigua and Barbuda', '1268'],
  ['AR', 'Argentina', '54'],
  ['AM', 'Armenia', '374'],
  ['AW', 'Aruba', '297'],
  ['AU', 'Australia', '61'],
  ['AT', 'Austria', '43'],
  ['AZ', 'Azerbaijan', '994'],
  ['BS', 'Bahamas', '1242'],
  ['BH', 'Bahrain', '973'],
  ['BD', 'Bangladesh', '880'],
  ['BB', 'Barbados', '1246'],
  ['BY', 'Belarus', '375'],
  ['BE', 'Belgium', '32'],
  ['BZ', 'Belize', '501'],
  ['BJ', 'Benin', '229'],
  ['BM', 'Bermuda', '1441'],
  ['BT', 'Bhutan', '975'],
  ['BO', 'Bolivia', '591'],
  ['BA', 'Bosnia and Herzegovina', '387'],
  ['BW', 'Botswana', '267'],
  ['BR', 'Brazil', '55'],
  ['IO', 'British Indian Ocean Territory', '246'],
  ['VG', 'British Virgin Islands', '1284'],
  ['BN', 'Brunei', '673'],
  ['BG', 'Bulgaria', '359'],
  ['BF', 'Burkina Faso', '226'],
  ['BI', 'Burundi', '257'],
  ['KH', 'Cambodia', '855'],
  ['CM', 'Cameroon', '237'],
  ['CA', 'Canada', '1'],
  ['CV', 'Cape Verde', '238'],
  ['KY', 'Cayman Islands', '1345'],
  ['CF', 'Central African Republic', '236'],
  ['TD', 'Chad', '235'],
  ['CL', 'Chile', '56'],
  ['CN', 'China', '86'],
  ['CO', 'Colombia', '57'],
  ['KM', 'Comoros', '269'],
  ['CG', 'Congo', '242'],
  ['CD', 'Congo (DRC)', '243'],
  ['CK', 'Cook Islands', '682'],
  ['CR', 'Costa Rica', '506'],
  ['CI', "Cote d'Ivoire", '225'],
  ['HR', 'Croatia', '385'],
  ['CU', 'Cuba', '53'],
  ['CW', 'Curacao', '599'],
  ['CY', 'Cyprus', '357'],
  ['CZ', 'Czech Republic', '420'],
  ['DK', 'Denmark', '45'],
  ['DJ', 'Djibouti', '253'],
  ['DM', 'Dominica', '1767'],
  ['DO', 'Dominican Republic', '1809'],
  ['EC', 'Ecuador', '593'],
  ['EG', 'Egypt', '20'],
  ['SV', 'El Salvador', '503'],
  ['GQ', 'Equatorial Guinea', '240'],
  ['ER', 'Eritrea', '291'],
  ['EE', 'Estonia', '372'],
  ['SZ', 'Eswatini', '268'],
  ['ET', 'Ethiopia', '251'],
  ['FK', 'Falkland Islands', '500'],
  ['FO', 'Faroe Islands', '298'],
  ['FJ', 'Fiji', '679'],
  ['FI', 'Finland', '358'],
  ['FR', 'France', '33'],
  ['GF', 'French Guiana', '594'],
  ['PF', 'French Polynesia', '689'],
  ['GA', 'Gabon', '241'],
  ['GM', 'Gambia', '220'],
  ['GE', 'Georgia', '995'],
  ['DE', 'Germany', '49'],
  ['GH', 'Ghana', '233'],
  ['GI', 'Gibraltar', '350'],
  ['GR', 'Greece', '30'],
  ['GL', 'Greenland', '299'],
  ['GD', 'Grenada', '1473'],
  ['GP', 'Guadeloupe', '590'],
  ['GU', 'Guam', '1671'],
  ['GT', 'Guatemala', '502'],
  ['GG', 'Guernsey', '44'],
  ['GN', 'Guinea', '224'],
  ['GW', 'Guinea-Bissau', '245'],
  ['GY', 'Guyana', '592'],
  ['HT', 'Haiti', '509'],
  ['HN', 'Honduras', '504'],
  ['HK', 'Hong Kong', '852'],
  ['HU', 'Hungary', '36'],
  ['IS', 'Iceland', '354'],
  ['ID', 'Indonesia', '62'],
  ['IR', 'Iran', '98'],
  ['IQ', 'Iraq', '964'],
  ['IE', 'Ireland', '353'],
  ['IM', 'Isle of Man', '44'],
  ['IL', 'Israel', '972'],
  ['IT', 'Italy', '39'],
  ['JM', 'Jamaica', '1876'],
  ['JP', 'Japan', '81'],
  ['JE', 'Jersey', '44'],
  ['JO', 'Jordan', '962'],
  ['KZ', 'Kazakhstan', '7'],
  ['KE', 'Kenya', '254'],
  ['KI', 'Kiribati', '686'],
  ['XK', 'Kosovo', '383'],
  ['KW', 'Kuwait', '965'],
  ['KG', 'Kyrgyzstan', '996'],
  ['LA', 'Laos', '856'],
  ['LV', 'Latvia', '371'],
  ['LB', 'Lebanon', '961'],
  ['LS', 'Lesotho', '266'],
  ['LR', 'Liberia', '231'],
  ['LY', 'Libya', '218'],
  ['LI', 'Liechtenstein', '423'],
  ['LT', 'Lithuania', '370'],
  ['LU', 'Luxembourg', '352'],
  ['MO', 'Macau', '853'],
  ['MG', 'Madagascar', '261'],
  ['MW', 'Malawi', '265'],
  ['MY', 'Malaysia', '60'],
  ['MV', 'Maldives', '960'],
  ['ML', 'Mali', '223'],
  ['MT', 'Malta', '356'],
  ['MH', 'Marshall Islands', '692'],
  ['MQ', 'Martinique', '596'],
  ['MR', 'Mauritania', '222'],
  ['MU', 'Mauritius', '230'],
  ['YT', 'Mayotte', '262'],
  ['MX', 'Mexico', '52'],
  ['FM', 'Micronesia', '691'],
  ['MD', 'Moldova', '373'],
  ['MC', 'Monaco', '377'],
  ['MN', 'Mongolia', '976'],
  ['ME', 'Montenegro', '382'],
  ['MS', 'Montserrat', '1664'],
  ['MA', 'Morocco', '212'],
  ['MZ', 'Mozambique', '258'],
  ['MM', 'Myanmar', '95'],
  ['NA', 'Namibia', '264'],
  ['NR', 'Nauru', '674'],
  ['NP', 'Nepal', '977'],
  ['NL', 'Netherlands', '31'],
  ['NC', 'New Caledonia', '687'],
  ['NZ', 'New Zealand', '64'],
  ['NI', 'Nicaragua', '505'],
  ['NE', 'Niger', '227'],
  ['NG', 'Nigeria', '234'],
  ['NU', 'Niue', '683'],
  ['KP', 'North Korea', '850'],
  ['MK', 'North Macedonia', '389'],
  ['MP', 'Northern Mariana Islands', '1670'],
  ['NO', 'Norway', '47'],
  ['OM', 'Oman', '968'],
  ['PK', 'Pakistan', '92'],
  ['PW', 'Palau', '680'],
  ['PS', 'Palestine', '970'],
  ['PA', 'Panama', '507'],
  ['PG', 'Papua New Guinea', '675'],
  ['PY', 'Paraguay', '595'],
  ['PE', 'Peru', '51'],
  ['PH', 'Philippines', '63'],
  ['PL', 'Poland', '48'],
  ['PT', 'Portugal', '351'],
  ['PR', 'Puerto Rico', '1787'],
  ['QA', 'Qatar', '974'],
  ['RE', 'Reunion', '262'],
  ['RO', 'Romania', '40'],
  ['RU', 'Russia', '7'],
  ['RW', 'Rwanda', '250'],
  ['WS', 'Samoa', '685'],
  ['SM', 'San Marino', '378'],
  ['ST', 'Sao Tome and Principe', '239'],
  ['SA', 'Saudi Arabia', '966'],
  ['SN', 'Senegal', '221'],
  ['RS', 'Serbia', '381'],
  ['SC', 'Seychelles', '248'],
  ['SL', 'Sierra Leone', '232'],
  ['SG', 'Singapore', '65'],
  ['SX', 'Sint Maarten', '1721'],
  ['SK', 'Slovakia', '421'],
  ['SI', 'Slovenia', '386'],
  ['SB', 'Solomon Islands', '677'],
  ['SO', 'Somalia', '252'],
  ['ZA', 'South Africa', '27'],
  ['KR', 'South Korea', '82'],
  ['SS', 'South Sudan', '211'],
  ['ES', 'Spain', '34'],
  ['LK', 'Sri Lanka', '94'],
  ['KN', 'St Kitts and Nevis', '1869'],
  ['LC', 'St Lucia', '1758'],
  ['VC', 'St Vincent and Grenadines', '1784'],
  ['SD', 'Sudan', '249'],
  ['SR', 'Suriname', '597'],
  ['SE', 'Sweden', '46'],
  ['CH', 'Switzerland', '41'],
  ['SY', 'Syria', '963'],
  ['TW', 'Taiwan', '886'],
  ['TJ', 'Tajikistan', '992'],
  ['TZ', 'Tanzania', '255'],
  ['TH', 'Thailand', '66'],
  ['TL', 'Timor-Leste', '670'],
  ['TG', 'Togo', '228'],
  ['TK', 'Tokelau', '690'],
  ['TO', 'Tonga', '676'],
  ['TT', 'Trinidad and Tobago', '1868'],
  ['TN', 'Tunisia', '216'],
  ['TR', 'Turkey', '90'],
  ['TM', 'Turkmenistan', '993'],
  ['TC', 'Turks and Caicos Islands', '1649'],
  ['TV', 'Tuvalu', '688'],
  ['VI', 'US Virgin Islands', '1340'],
  ['UG', 'Uganda', '256'],
  ['UA', 'Ukraine', '380'],
  ['AE', 'United Arab Emirates', '971'],
  ['GB', 'United Kingdom', '44'],
  ['US', 'United States', '1'],
  ['UY', 'Uruguay', '598'],
  ['UZ', 'Uzbekistan', '998'],
  ['VU', 'Vanuatu', '678'],
  ['VA', 'Vatican City', '39'],
  ['VE', 'Venezuela', '58'],
  ['VN', 'Vietnam', '84'],
  ['WF', 'Wallis and Futuna', '681'],
  ['YE', 'Yemen', '967'],
  ['ZM', 'Zambia', '260'],
  ['ZW', 'Zimbabwe', '263']
];

function initPhoneCodeDropdowns() {
  const flag = iso => String.fromCodePoint(...[...iso].map(ch => 0x1F1E6 + ch.charCodeAt(0) - 65));
  document.querySelectorAll('select[name="phone_country_code"]').forEach(sel => {
    sel.innerHTML = '';
    [...PHONE_COUNTRIES].sort((a, b) => (a[0] === 'IN' ? -1 : b[0] === 'IN' ? 1 : a[1].localeCompare(b[1])))
      .forEach(([iso, name, dial]) => {
      const opt = document.createElement('option');
      opt.value = '+' + dial;
      opt.textContent = `${flag(iso)} +${dial} ${name}`;
      sel.appendChild(opt);
    });
    sel.value = '+91';
  });
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

// ── BACKFILL ────────────────────────────────────────────────
function initBackfillButtons() {
  const msg = document.getElementById('backfillMsg');

  async function runAction(btn, url, label) {
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ Running…';
    if (msg) msg.textContent = '';
    try {
      const res  = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
      const data = await res.json();
      if (msg) {
        msg.textContent = data.message || (data.ok ? '✅ Done' : `❌ ${data.error}`);
        msg.style.color = data.ok ? '#16a34a' : '#dc2626';
      }
      if (data.ok) loadAnalytics();   // refresh tables
    } catch(e) {
      if (msg) { msg.textContent = `❌ ${e.message}`; msg.style.color = '#dc2626'; }
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  }

  const btnBackfill   = document.getElementById('btnBackfill');
  const btnSyncStatus = document.getElementById('btnSyncStatus');

  if (btnBackfill)
    btnBackfill.addEventListener('click', () =>
      runAction(btnBackfill, '/api/erp/razorpay/backfill', 'Import'));

  if (btnSyncStatus)
    btnSyncStatus.addEventListener('click', () =>
      runAction(btnSyncStatus, '/api/erp/razorpay/sync-status', 'Sync'));
}

// ── ANALYTICS ──────────────────────────────────────────────
async function loadAnalytics() {
  try {
    const res  = await fetch('/api/erp/analytics');
    if (!res.ok) return;
    const data = await res.json();
    const s    = data.stats || {};
    const cur  = s.currency || 'INR';

    const fmt = (n) => `${cur} ${parseFloat(n || 0).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

    setText('statTotal',       s.total_orders    ?? '—');
    setText('statLinks',       s.links_generated ?? '—');
    setText('statPaid',        s.paid_orders     ?? '—');
    setText('statUnpaid',      s.unpaid_orders   ?? '—');
    setText('statPending',     s.pending_orders  ?? '—');
    setText('statRevenue',     fmt(s.total_revenue));
    setText('statPujaRevenue', fmt(s.puja_revenue));
    setText('statEcomRevenue', fmt(s.ecom_revenue));
    setText('statSplit',       `🙏 ${s.puja_orders ?? 0}  /  🛒 ${s.ecom_orders ?? 0}`);

    // ── Recent paid transactions ──────────────────────────
    const tbody = document.getElementById('paidTransactionsBody');
    const paid  = data.recent_paid || [];
    if (tbody) {
      if (!paid.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#94a3b8;padding:24px">No successful transactions yet.</td></tr>';
      } else {
        tbody.innerHTML = paid.map(o => {
          const amt    = parseFloat(o.payment_amount || o.amount || 0);
          const amtFmt = `${o.currency || cur} ${amt.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
          const service = esc(o.puja_name || o.item_name || '—');
          const date    = (o.paid_at || o.updated_at || '').slice(0, 10) || '—';
          return `<tr>
            <td><span class="order-uid-cell">${esc(o.order_uid)}</span></td>
            <td><div class="customer-cell"><div class="name">${esc(o.customer_name || '—')}</div><div class="phone">${esc(o.phone || '')}</div></div></td>
            <td>${service}</td>
            <td class="amount-cell" style="color:#16a34a;font-weight:600">${amtFmt}</td>
            <td>${esc((o.payment_provider || '—').replace(/^\w/, c => c.toUpperCase()))}</td>
            <td>${date}</td>
          </tr>`;
        }).join('');
      }
    }

    // ── Payment links generated ───────────────────────────
    const linksTbody = document.getElementById('linksGeneratedBody');
    const links      = data.links_generated || [];
    if (linksTbody) {
      if (!links.length) {
        linksTbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#94a3b8;padding:24px">No payment links generated yet.</td></tr>';
      } else {
        linksTbody.innerHTML = links.map(o => {
          const amt     = parseFloat(o.amount || 0);
          const amtFmt  = `${o.currency || cur} ${amt.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
          const service = esc(o.puja_name || o.item_name || '—');
          const date    = (o.created_at || '').slice(0, 10) || '—';
          const status  = o.payment_status || 'unpaid';
          const statusCls = status.toLowerCase();
          const statusLabel = statusEmoji(status) + ' ' + capitalize(status);
          const linkUrl = o.payment_link || '';
          return `<tr>
            <td><span class="order-uid-cell">${esc(o.order_uid)}</span></td>
            <td><div class="customer-cell"><div class="name">${esc(o.customer_name || '—')}</div><div class="phone">${esc(o.phone || '')}</div></div></td>
            <td>${service}</td>
            <td class="amount-cell">${amtFmt}</td>
            <td style="max-width:180px">
              ${linkUrl
                ? `<a href="${esc(linkUrl)}" target="_blank" style="font-size:12px;color:#6366f1;word-break:break-all">${esc(linkUrl.replace('https://',''))}</a>
                   <button class="action-btn" style="margin-left:4px" onclick="copyLink('${esc(linkUrl)}')">📋</button>`
                : '<span style="color:#94a3b8">—</span>'}
            </td>
            <td><span class="status-pill ${statusCls}">${statusLabel}</span></td>
            <td>${date}</td>
          </tr>`;
        }).join('');
      }
    }
  } catch(_) {}
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
