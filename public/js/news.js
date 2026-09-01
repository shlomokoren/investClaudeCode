const chipsContainer = document.getElementById('symbolChips');
const form = document.getElementById('newsControls');
const daysSelect = form.days;
const refreshBtn = document.getElementById('refreshBtn');
const statusEl = document.getElementById('status');
const feed = document.getElementById('newsFeed');

daysSelect.value = window.DEFAULT_DAYS || '2';

function selectedSymbols() {
  return [...chipsContainer.querySelectorAll('.chip.active')].map((c) => c.dataset.symbol);
}

function relativeTime(iso) {
  if (!iso) return '';
  const then = new Date(iso);
  if (isNaN(then)) return '';
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function render(items) {
  feed.innerHTML = '';
  for (const item of items) {
    const article = document.createElement('article');
    article.className = 'news-item';

    if (item.thumbnail) {
      const img = document.createElement('img');
      img.className = 'news-thumb';
      img.src = item.thumbnail;
      img.alt = '';
      img.loading = 'lazy';
      img.referrerPolicy = 'no-referrer';
      img.addEventListener('error', () => img.remove());
      article.appendChild(img);
    }

    const body = document.createElement('div');
    body.className = 'news-body';

    const h3 = document.createElement('h3');
    h3.className = 'news-title';
    if (item.url) {
      const a = document.createElement('a');
      a.href = item.url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = item.title;
      h3.appendChild(a);
    } else {
      h3.textContent = item.title;
    }
    body.appendChild(h3);

    const meta = document.createElement('div');
    meta.className = 'news-meta';
    const bits = [];
    if (item.publisher) bits.push(item.publisher);
    const rel = relativeTime(item.published);
    if (rel) bits.push(rel);
    meta.textContent = bits.join(' · ');
    for (const ticker of item.tickers || []) {
      const tag = document.createElement('span');
      tag.className = 'news-tag';
      tag.textContent = ticker;
      meta.appendChild(tag);
    }
    body.appendChild(meta);

    if (item.summary) {
      const p = document.createElement('p');
      p.className = 'news-summary';
      p.textContent = item.summary;
      body.appendChild(p);
    }

    article.appendChild(body);
    feed.appendChild(article);
  }
}

async function loadNews() {
  const symbols = selectedSymbols();
  const days = daysSelect.value;

  if (!symbols.length) {
    feed.innerHTML = '';
    statusEl.textContent = 'Select at least one symbol to see its news.';
    return;
  }

  statusEl.textContent = 'Loading…';
  refreshBtn.disabled = true;
  try {
    const params = new URLSearchParams({ symbols: symbols.join(','), days });
    const resp = await fetch(`/api/news?${params}`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Request failed');
    render(data.items);
    statusEl.textContent = data.items.length
      ? `${data.items.length} stor${data.items.length === 1 ? 'y' : 'ies'} in the last ${data.days} day(s).`
      : `No stories for the selected symbols in the last ${data.days} day(s).`;
  } catch (err) {
    feed.innerHTML = '';
    statusEl.textContent = `Error: ${err.message}`;
  } finally {
    refreshBtn.disabled = false;
  }
}

async function persistSelection(symbol, selected) {
  try {
    const resp = await fetch(`/api/news/symbols/${encodeURIComponent(symbol)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.error || 'Request failed');
    }
  } catch (err) {
    // Non-fatal: the feed still reflects the toggle, the choice just didn't save.
    statusEl.textContent = `Couldn't save the ${symbol} selection: ${err.message}`;
  }
}

chipsContainer.addEventListener('click', (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  const selected = chip.classList.toggle('active');
  persistSelection(chip.dataset.symbol, selected);
  loadNews();
});

form.addEventListener('submit', (e) => {
  e.preventDefault();
  loadNews();
});
daysSelect.addEventListener('change', loadNews);

loadNews();
