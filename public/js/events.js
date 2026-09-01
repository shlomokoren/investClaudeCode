const statusEl = document.getElementById('status');
const tbody = document.getElementById('eventsBody');
const table = document.getElementById('eventsTable');
const chipsContainer = document.getElementById('symbolChips');

function selectedSymbols() {
  return [...chipsContainer.querySelectorAll('.chip.active')].map((c) => c.dataset.symbol);
}

async function persistSelection(symbol, selected) {
  try {
    const resp = await fetch(`/api/events/symbols/${encodeURIComponent(symbol)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.error || 'Request failed');
    }
  } catch (err) {
    // Non-fatal: the table still reflects the toggle, the choice just didn't save.
    statusEl.textContent = `Couldn't save the ${symbol} filter: ${err.message}`;
  }
}

let rows = [];
let sortKey = null;
let sortDir = 1;

const NAME_COLUMN_MAX_CHARS = 90;
const MS_PER_DAY = 24 * 60 * 60 * 1000;

function parseDate(iso) {
  if (!iso) return null;
  const d = new Date(iso + 'T00:00:00');
  return isNaN(d) ? null : d;
}

function daysFromNow(iso) {
  const d = parseDate(iso);
  if (!d) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d - today) / MS_PER_DAY);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function formatDate(iso) {
  const d = parseDate(iso);
  if (!d) return '—';
  // Fixed English format rather than toLocaleDateString(), whose day/month/year
  // order and month names follow the viewer's OS locale.
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

function formatDays(n) {
  if (n == null) return '—';
  if (n === 0) return 'today';
  if (n < 0) return `${-n}d ago`;
  return `in ${n}d`;
}

function formatMoney(v, digits) {
  return v == null ? '—' : `$${v.toFixed(digits)}`;
}

function formatPct(v) {
  return v == null ? '—' : `${v.toFixed(2)}%`;
}

// The soonest still-upcoming event (earnings or ex-dividend) for a row, in
// days from today — used for the default sort. Past-only rows sort last.
function soonestEventDays(row) {
  const candidates = [
    daysFromNow(row.earnings_date),
    daysFromNow(row.ex_dividend_date),
  ].filter((n) => n != null && n >= 0);
  return candidates.length ? Math.min(...candidates) : null;
}

function render() {
  tbody.innerHTML = '';
  for (const row of rows) {
    const tr = document.createElement('tr');
    if (row.error) tr.classList.add('row-error');

    const nameTd = document.createElement('td');
    const ticker = row.ticker;
    const suffix = row.name && row.name !== ticker ? ` — ${row.name}` : '';
    const full = ticker + suffix;
    let displaySuffix = suffix;
    if (full.length > NAME_COLUMN_MAX_CHARS) {
      const allowed = Math.max(NAME_COLUMN_MAX_CHARS - ticker.length - 1, 0);
      displaySuffix = suffix.slice(0, allowed) + '…';
      nameTd.title = full;
    }
    const tickerEl = document.createElement('strong');
    tickerEl.textContent = ticker;
    nameTd.appendChild(tickerEl);
    nameTd.appendChild(document.createTextNode(displaySuffix));
    tr.appendChild(nameTd);

    const earningsTd = document.createElement('td');
    earningsTd.textContent = formatDate(row.earnings_date);
    if (row.earnings_date && row.earnings_estimated) {
      const flag = document.createElement('span');
      flag.className = 'est-flag';
      flag.textContent = 'est.';
      earningsTd.appendChild(document.createTextNode(' '));
      earningsTd.appendChild(flag);
    }
    tr.appendChild(earningsTd);

    const daysTd = document.createElement('td');
    const d = row.days_to_earnings;
    daysTd.textContent = formatDays(d);
    if (d != null && d >= 0 && d <= 7) daysTd.className = 'soon';
    tr.appendChild(daysTd);

    const exTd = document.createElement('td');
    exTd.textContent = formatDate(row.ex_dividend_date);
    const exDays = daysFromNow(row.ex_dividend_date);
    if (exDays != null && exDays >= 0 && exDays <= 7) exTd.className = 'soon';
    tr.appendChild(exTd);

    const payTd = document.createElement('td');
    payTd.textContent = formatDate(row.pay_date);
    tr.appendChild(payTd);

    const lastDivTd = document.createElement('td');
    lastDivTd.textContent = formatMoney(row.last_dividend, 4);
    tr.appendChild(lastDivTd);

    const rateTd = document.createElement('td');
    rateTd.textContent = formatMoney(row.annual_rate, 2);
    tr.appendChild(rateTd);

    const yieldTd = document.createElement('td');
    yieldTd.textContent = formatPct(row.dividend_yield);
    tr.appendChild(yieldTd);

    const freqTd = document.createElement('td');
    freqTd.textContent = row.frequency || '—';
    tr.appendChild(freqTd);

    tbody.appendChild(tr);
  }
}

function sortValue(row, key) {
  if (key === 'name') return row.name || row.ticker;
  if (key === 'earnings_date' || key === 'ex_dividend_date' || key === 'pay_date') {
    const d = parseDate(row[key]);
    return d ? d.getTime() : null;
  }
  return row[key];
}

function applySort() {
  if (!sortKey) {
    // Default: soonest upcoming event first, rows with no upcoming event last.
    rows.sort((a, b) => {
      const av = soonestEventDays(a);
      const bv = soonestEventDays(b);
      if (av == null && bv == null) return (a.ticker || '').localeCompare(b.ticker || '');
      if (av == null) return 1;
      if (bv == null) return -1;
      return av - bv;
    });
    return;
  }
  rows.sort((a, b) => {
    const av = sortValue(a, sortKey);
    const bv = sortValue(b, sortKey);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'string') return av.localeCompare(bv) * sortDir;
    return (av - bv) * sortDir;
  });
}

function updateHeaderIndicators() {
  table.querySelectorAll('th[data-sort]').forEach((th) => {
    const active = th.dataset.sort === sortKey;
    th.classList.toggle('sorted-asc', active && sortDir === 1);
    th.classList.toggle('sorted-desc', active && sortDir === -1);
  });
}

function sortBy(key) {
  if (sortKey === key) {
    sortDir *= -1;
  } else {
    sortKey = key;
    sortDir = 1;
  }
  applySort();
  updateHeaderIndicators();
  render();
}

table.querySelectorAll('th[data-sort]').forEach((th) => {
  th.addEventListener('click', () => sortBy(th.dataset.sort));
});

async function loadEvents() {
  const symbols = selectedSymbols();
  if (chipsContainer.querySelector('.chip') && !symbols.length) {
    rows = [];
    render();
    statusEl.textContent = 'No symbols selected — pick one or more above.';
    return;
  }

  statusEl.textContent = 'Loading…';
  try {
    const params = new URLSearchParams({ symbols: symbols.join(',') });
    const resp = await fetch(`/api/events?${params}`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Request failed');
    rows = data.rows;
    applySort();
    render();
    statusEl.textContent = rows.length
      ? `Showing ${rows.length} stock(s).`
      : 'Your watch list is empty — add symbols from the Price Chart tab.';
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
  }
}

chipsContainer.addEventListener('click', (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  const selected = chip.classList.toggle('active');
  persistSelection(chip.dataset.symbol, selected);
  loadEvents();
});

loadEvents();
