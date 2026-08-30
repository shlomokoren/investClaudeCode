function formatVolume(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  return v;
}

const rangeSelect = document.querySelector('select[name="range"]');
rangeSelect.value = window.DEFAULT_RANGE;

const form = document.getElementById('controls');
const grid = document.getElementById('grid');
const status = document.getElementById('status');
const loadBtn = document.getElementById('loadBtn');
const chipsContainer = document.getElementById('symbolChips');
const symbolEditor = document.getElementById('symbolEditor');
const symbolStatus = document.getElementById('symbolStatus');
const addSymbolBtn = document.getElementById('addSymbolBtn');
const charts = new Map();
const cards = new Map();

function currentTickers() {
  return form.tickers.value
    .split(',')
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean);
}

function setTickers(list) {
  form.tickers.value = list.join(',');
  // Assigning .value doesn't fire 'input', so refresh the chips here — that way
  // no programmatic ticker change can leave a chip looking inactive.
  syncChipState();
}

function syncChipState() {
  const active = new Set(currentTickers());
  chipsContainer.querySelectorAll('.chip').forEach((btn) => {
    btn.classList.toggle('active', active.has(btn.dataset.symbol));
  });
}

function renderChips(list) {
  const hint = document.getElementById('emptyHint');
  if (hint) hint.hidden = list.length > 0;

  chipsContainer.innerHTML = '';
  for (const symbol of list) {
    const wrap = document.createElement('span');
    wrap.className = 'chip-wrap';
    wrap.dataset.symbol = symbol;

    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.dataset.symbol = symbol;
    chip.textContent = symbol;

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'chip-remove';
    remove.dataset.remove = symbol;
    remove.title = `Remove ${symbol} from the saved list`;
    remove.setAttribute('aria-label', `Remove ${symbol}`);
    remove.innerHTML = '&times;';

    wrap.append(chip, remove);
    chipsContainer.appendChild(wrap);
  }
  syncChipState();
}

function setSymbolStatus(message, isError = false) {
  symbolStatus.textContent = message;
  symbolStatus.classList.toggle('error', isError);
}

async function saveSymbolChange(url, options, onSuccess) {
  addSymbolBtn.disabled = true;
  try {
    const resp = await fetch(url, options);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Request failed');
    renderChips(data.symbols);
    onSuccess(data);
    await loadData();
  } catch (err) {
    setSymbolStatus(err.message, true);
  } finally {
    addSymbolBtn.disabled = false;
  }
}

symbolEditor.addEventListener('submit', async (e) => {
  e.preventDefault();
  const symbol = symbolEditor.symbol.value.trim().toUpperCase();
  if (!symbol) return;

  setSymbolStatus('Checking…');
  await saveSymbolChange(
    '/api/symbols',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol }),
    },
    (data) => {
      symbolEditor.symbol.value = '';
      // show the newly added symbol right away
      setTickers(currentTickers().concat(data.added));
      setSymbolStatus(`Added ${data.added}.`);
    }
  );
});

async function removeSymbol(symbol) {
  setSymbolStatus('Removing…');
  await saveSymbolChange(
    `/api/symbols/${encodeURIComponent(symbol)}`,
    { method: 'DELETE' },
    (data) => {
      setTickers(currentTickers().filter((t) => t !== data.removed));
      setSymbolStatus(`Removed ${data.removed}.`);
    }
  );
}

async function saveSymbolStatus(symbol, enabled) {
  try {
    await fetch(`/api/symbols/${encodeURIComponent(symbol)}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
  } catch (err) {
    // best-effort: the chart already reflects the toggle locally even if
    // the save fails (e.g. offline), so don't interrupt the user for it.
  }
}

chipsContainer.addEventListener('click', (e) => {
  const removeBtn = e.target.closest('.chip-remove');
  if (removeBtn) {
    removeSymbol(removeBtn.dataset.remove);
    return;
  }

  const btn = e.target.closest('.chip');
  if (!btn) return;

  const symbol = btn.dataset.symbol;
  const tickers = currentTickers();
  const idx = tickers.indexOf(symbol);
  const nowEnabled = idx < 0;
  if (idx >= 0) {
    tickers.splice(idx, 1);
  } else {
    tickers.push(symbol);
  }
  setTickers(tickers);
  saveSymbolStatus(symbol, nowEnabled);

  // Toggling one stock only touches that stock's chart — the others are
  // already on screen and don't need to be re-fetched.
  if (nowEnabled) {
    addChart(symbol);
  } else {
    removeCard(symbol);
  }
});

form.tickers.addEventListener('input', syncChipState);

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  await loadData();
});

async function loadData() {
  const tickers = form.tickers.value.trim();
  const range = form.range.value;
  if (!tickers) {
    renderCharts([]);
    status.textContent = 'No tickers selected.';
    return;
  }

  loadBtn.disabled = true;
  status.textContent = 'Loading…';

  try {
    const resp = await fetch(`/api/stocks?tickers=${encodeURIComponent(tickers)}&range=${range}`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Request failed');
    renderCharts(data.stocks);
    status.textContent = `Showing ${data.stocks.length} stock(s) over ${range}.`;
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
  } finally {
    loadBtn.disabled = false;
  }
}

function renderCharts(stocks) {
  // destroy old charts
  for (const c of charts.values()) c.destroy();
  charts.clear();
  cards.clear();
  grid.innerHTML = '';

  for (const s of stocks) {
    const card = buildCard(s);
    cards.set(s.ticker, card);
    grid.appendChild(card);
  }
}

// Builds one stock's card (and its Chart instance, registered in `charts`)
// without touching the grid or any other card — the caller decides where it
// goes, so a single toggle never has to rebuild the whole grid.
function buildCard(s) {
  const card = document.createElement('div');
  card.className = 'card';
  const title = document.createElement('h2');
  const nameSuffix = s.name && s.name !== s.ticker ? ` — ${s.name}` : '';
  title.textContent = `${s.ticker}${nameSuffix}`;
  card.appendChild(title);

  if (s.error) {
    const err = document.createElement('div');
    err.className = 'error';
    err.textContent = s.error;
    card.appendChild(err);
    return card;
  }

  const canvas = document.createElement('canvas');
  canvas.height = 240;
  card.appendChild(canvas);

  const chart = new Chart(canvas, {
      data: {
        labels: s.dates,
        datasets: [
          {
            type: 'line',
            label: 'Price',
            data: s.prices,
            borderColor: '#2563eb',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0,
            yAxisID: 'yPrice',
            order: 1,
          },
          {
            type: 'line',
            label: 'SMA150',
            data: s.sma150,
            borderColor: '#ea580c',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0,
            yAxisID: 'yPrice',
            order: 2,
          },
          {
            type: 'bar',
            label: 'Volume',
            data: s.volumes,
            backgroundColor: 'rgba(148, 163, 184, 0.45)',
            borderWidth: 0,
            yAxisID: 'yVolume',
            order: 3,
          },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top' },
          tooltip: {
            enabled: true,
            callbacks: {
              label: (ctx) => {
                const v = ctx.parsed.y;
                if (ctx.dataset.label === 'Volume') {
                  return `Volume: ${v.toLocaleString()}`;
                }
                return `${ctx.dataset.label}: $${v}`;
              },
              footer: (items) => {
                if (!items.length) return '';
                const i = items[0].dataIndex;
                const price = s.prices[i];
                const sma = s.sma150[i];
                if (price == null || sma == null || sma === 0) return 'Diff%: n/a';
                const diff = ((price - sma) / sma) * 100;
                const sign = diff >= 0 ? '+' : '';
                return `Diff%: ${sign}${diff.toFixed(2)}%`;
              },
            },
          },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 8, autoSkip: true } },
          yPrice: {
            type: 'linear',
            position: 'left',
            ticks: { callback: (v) => '$' + v },
          },
          yVolume: {
            type: 'linear',
            position: 'right',
            grid: { drawOnChartArea: false },
            ticks: { callback: (v) => formatVolume(v) },
          },
        },
      },
  });
  charts.set(s.ticker, chart);
  return card;
}

// Inserts a card at the position matching its symbol's place in the current
// ticker order, so re-enabling a stock puts its chart back where it was.
function insertCard(symbol, card) {
  cards.set(symbol, card);
  const order = currentTickers();
  const idx = order.indexOf(symbol);
  let nextCard = null;
  for (let i = idx + 1; i < order.length; i++) {
    if (cards.has(order[i])) {
      nextCard = cards.get(order[i]);
      break;
    }
  }
  if (nextCard) {
    grid.insertBefore(card, nextCard);
  } else {
    grid.appendChild(card);
  }
}

function removeCard(symbol) {
  const chart = charts.get(symbol);
  if (chart) {
    chart.destroy();
    charts.delete(symbol);
  }
  const card = cards.get(symbol);
  if (card) {
    card.remove();
    cards.delete(symbol);
  }
  status.textContent = `Showing ${cards.size} stock(s) over ${form.range.value}.`;
}

async function addChart(symbol) {
  const range = form.range.value;
  try {
    const resp = await fetch(`/api/stocks?tickers=${encodeURIComponent(symbol)}&range=${range}`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Request failed');
    const card = buildCard(data.stocks[0]);
    insertCard(symbol, card);
    status.textContent = `Showing ${cards.size} stock(s) over ${range}.`;
  } catch (err) {
    status.textContent = `Error loading ${symbol}: ${err.message}`;
  }
}

// initial load
syncChipState();
loadData();
