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
const charts = new Map();

function currentTickers() {
  return form.tickers.value
    .split(',')
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean);
}

function setTickers(list) {
  form.tickers.value = list.join(',');
}

function syncChipState() {
  const active = new Set(currentTickers());
  chipsContainer.querySelectorAll('.chip').forEach((btn) => {
    btn.classList.toggle('active', active.has(btn.dataset.symbol));
  });
}

chipsContainer.addEventListener('click', (e) => {
  const btn = e.target.closest('.chip');
  if (!btn) return;

  const symbol = btn.dataset.symbol;
  const tickers = currentTickers();
  const idx = tickers.indexOf(symbol);
  if (idx >= 0) {
    tickers.splice(idx, 1);
  } else {
    tickers.push(symbol);
  }
  setTickers(tickers);
  syncChipState();
  loadData();
});

form.tickers.addEventListener('input', syncChipState);

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  await loadData();
});

async function loadData() {
  const tickers = form.tickers.value.trim();
  const range = form.range.value;
  if (!tickers) return;

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
  grid.innerHTML = '';

  for (const s of stocks) {
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
      grid.appendChild(card);
      continue;
    }

    const canvas = document.createElement('canvas');
    canvas.height = 240;
    card.appendChild(canvas);
    grid.appendChild(card);

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
  }
}

// initial load
syncChipState();
loadData();
