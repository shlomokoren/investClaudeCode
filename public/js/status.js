const statusEl = document.getElementById('status');
const totalEl = document.getElementById('statusTotal');
const tbody = document.getElementById('statusBody');
const table = document.getElementById('statusTable');
const chipsContainer = document.getElementById('symbolChips');
const allocationCanvas = document.getElementById('allocationChart');
const allocationHint = document.getElementById('allocationHint');
let allocationChart = null;

function selectedSymbols() {
  return [...chipsContainer.querySelectorAll('.chip.active')].map((c) => c.dataset.symbol);
}

async function persistSelection(symbol, selected) {
  try {
    const resp = await fetch(`/api/status/symbols/${encodeURIComponent(symbol)}`, {
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

function computeValue(row) {
  if (row.current_price == null) return null;
  return row.current_price * row.position;
}

function formatPrice(v) {
  return v == null ? '—' : `$${v.toFixed(2)}`;
}

function formatPct(v) {
  if (v == null) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(2)}%`;
}

const NAME_COLUMN_MAX_CHARS = 90;

function renderTotal() {
  const total = rows.reduce((sum, row) => {
    const value = computeValue(row);
    return value == null ? sum : sum + value;
  }, 0);
  totalEl.innerHTML = `Total Value: <strong>${formatPrice(total)}</strong>`;
}

function colorForSlice(i, total) {
  const hue = Math.round((360 / Math.max(total, 1)) * i);
  return `hsl(${hue}, 65%, 55%)`;
}

function renderAllocationChart() {
  // Positions of 0 have no value and would just be a meaningless sliver, so
  // they're left out of the allocation breakdown entirely.
  const slices = rows
    .map((row) => ({ ticker: row.ticker, value: computeValue(row) }))
    .filter((s) => s.value != null && s.value > 0);

  if (allocationChart) {
    allocationChart.destroy();
    allocationChart = null;
  }

  if (!slices.length) {
    allocationCanvas.hidden = true;
    allocationHint.hidden = false;
    return;
  }

  allocationCanvas.hidden = false;
  allocationHint.hidden = true;

  const total = slices.reduce((sum, s) => sum + s.value, 0);

  allocationChart = new Chart(allocationCanvas, {
    type: 'pie',
    data: {
      labels: slices.map((s) => s.ticker),
      datasets: [
        {
          data: slices.map((s) => s.value),
          backgroundColor: slices.map((_, i) => colorForSlice(i, slices.length)),
          borderColor: '#fff',
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          position: 'right',
          labels: {
            generateLabels: (chart) => {
              const defaults = Chart.overrides.pie.plugins.legend.labels.generateLabels(chart);
              return defaults.map((label, i) => {
                const pct = (slices[i].value / total) * 100;
                label.text = `${slices[i].ticker} — ${pct.toFixed(1)}%`;
                return label;
              });
            },
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const pct = (ctx.parsed / total) * 100;
              return `${ctx.label}: ${pct.toFixed(1)}% ($${ctx.parsed.toFixed(2)})`;
            },
          },
        },
      },
    },
  });
}

function render() {
  renderTotal();
  renderAllocationChart();
  tbody.innerHTML = '';
  for (const row of rows) {
    const tr = document.createElement('tr');

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

    const prevCloseTd = document.createElement('td');
    prevCloseTd.textContent = formatPrice(row.previous_close);
    tr.appendChild(prevCloseTd);

    const curTd = document.createElement('td');
    curTd.textContent = formatPrice(row.current_price);
    tr.appendChild(curTd);

    const pctTd = document.createElement('td');
    pctTd.textContent = formatPct(row.change_pct);
    if (row.change_pct != null) {
      pctTd.className = row.change_pct >= 0 ? 'positive' : 'negative';
    }
    tr.appendChild(pctTd);

    const posTd = document.createElement('td');
    const posInput = document.createElement('input');
    posInput.type = 'number';
    posInput.min = '0';
    posInput.step = 'any';
    posInput.className = 'position-input';
    posInput.value = row.position;
    posInput.addEventListener('change', () => onPositionChange(row, posInput));
    posTd.appendChild(posInput);
    tr.appendChild(posTd);

    const valTd = document.createElement('td');
    valTd.textContent = formatPrice(computeValue(row));
    tr.appendChild(valTd);

    tbody.appendChild(tr);
  }
}

async function onPositionChange(row, input) {
  let position = parseFloat(input.value);
  if (isNaN(position) || position < 0) position = 0;
  input.value = position;
  row.position = position;
  render(); // reflect the new Value column immediately

  try {
    const resp = await fetch('/api/status/position', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: row.ticker, position }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Request failed');
  } catch (err) {
    statusEl.textContent = `Error saving position for ${row.ticker}: ${err.message}`;
  }
}

function sortValue(row, key) {
  if (key === 'value') return computeValue(row);
  if (key === 'name') return row.name || row.ticker;
  return row[key];
}

function applySort() {
  if (!sortKey) return;
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

async function loadStatus() {
  const symbols = selectedSymbols();
  if (chipsContainer.querySelector('.chip') && !symbols.length) {
    rows = [];
    applySort();
    render();
    statusEl.textContent = 'No symbols selected — pick one or more above.';
    return;
  }

  statusEl.textContent = 'Loading…';
  try {
    const params = new URLSearchParams({ symbols: symbols.join(',') });
    const resp = await fetch(`/api/status?${params}`);
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
  loadStatus();
});

loadStatus();
