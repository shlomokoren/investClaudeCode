const CURRENCY_SYMBOLS = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
};

function currencyPrefix(currency) {
  return CURRENCY_SYMBOLS[currency] || currency + " ";
}

function formatCompact(value, currency) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }
  const prefix = currencyPrefix(currency);
  const abs = Math.abs(value);
  if (abs >= 1e9) {
    return `${prefix}${(value / 1e9).toFixed(1)}B`;
  }
  if (abs >= 1e6) {
    return `${prefix}${(value / 1e6).toFixed(1)}M`;
  }
  return `${prefix}${value.toFixed(0)}`;
}

function formatEps(value, currency) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }
  return `${currencyPrefix(currency)}${value.toFixed(2)}`;
}

const METRICS = [
  { key: "total_revenue", label: "Total Revenue", canvasId: "chart-total_revenue", type: "money" },
  { key: "gross_profit", label: "Gross Profit", canvasId: "chart-gross_profit", type: "money" },
  { key: "operating_income", label: "Operating Income", canvasId: "chart-operating_income", type: "money" },
  { key: "net_income", label: "Net Income", canvasId: "chart-net_income", type: "money" },
  { key: "free_cash_flow", label: "Free Cash Flow", canvasId: "chart-free_cash_flow", type: "money" },
  { key: "eps", label: "EPS", canvasId: "chart-eps", type: "eps" },
];

const charts = {};

const symbolInput = document.getElementById("symbol-input");
const symbolClearBtn = document.getElementById("symbol-clear");
const periodSelect = document.getElementById("period-select");
const errorBanner = document.getElementById("error-banner");
const loadingEl = document.getElementById("loading");
const chipsContainer = document.getElementById("symbolChips");

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.hidden = false;
}

function clearError() {
  errorBanner.hidden = true;
  errorBanner.textContent = "";
}

function setLoading(isLoading) {
  loadingEl.hidden = !isLoading;
}

function syncChipState() {
  const current = symbolInput.value.trim().toUpperCase();
  chipsContainer.querySelectorAll(".chip").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.symbol === current);
  });
}

function buildChart(metric, periods, values, currency) {
  const ctx = document.getElementById(metric.canvasId).getContext("2d");
  const isEps = metric.type === "eps";
  const formatter = isEps
    ? (v) => formatEps(v, currency)
    : (v) => formatCompact(v, currency);

  if (charts[metric.key]) {
    charts[metric.key].destroy();
  }

  charts[metric.key] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: periods,
      datasets: [
        {
          label: metric.label,
          data: values,
          backgroundColor: "#4c78dc",
          spanGaps: false,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => {
              const v = context.parsed.y;
              return v === null || v === undefined ? "N/A" : formatter(v);
            },
          },
        },
      },
      scales: {
        y: {
          ticks: {
            callback: (value) => formatter(value),
          },
        },
      },
    },
  });
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

let requestSeq = 0;

async function loadFinancials() {
  const symbol = symbolInput.value.trim().toUpperCase();
  const period = periodSelect.value;

  if (!symbol) {
    return;
  }

  const seq = ++requestSeq;

  clearError();
  setLoading(true);

  try {
    const response = await fetch(`/api/financials?symbol=${encodeURIComponent(symbol)}&period=${encodeURIComponent(period)}`);
    const data = await response.json();

    if (seq !== requestSeq) {
      return; // a newer request superseded this one
    }

    if (!response.ok) {
      throw new Error(data.error || "Failed to load financial data.");
    }

    METRICS.forEach((metric) => {
      const values = data.metrics[metric.key] || [];
      buildChart(metric, data.periods, values, data.currency);
    });
  } catch (err) {
    if (seq === requestSeq) {
      showError(err.message || "Failed to load financial data.");
    }
  } finally {
    if (seq === requestSeq) {
      setLoading(false);
    }
  }
}

const debouncedLoad = debounce(loadFinancials, 300);

chipsContainer.addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  symbolInput.value = btn.dataset.symbol;
  syncChipState();
  loadFinancials();
});

// Selecting a datalist option fires "input", not "change" (that only
// fires on blur), so the refresh has to be wired to "input".
symbolInput.addEventListener("input", () => {
  const cursor = symbolInput.selectionStart;
  symbolInput.value = symbolInput.value.toUpperCase();
  symbolInput.setSelectionRange(cursor, cursor);
  syncChipState();
  debouncedLoad();
});

// Clear the field so the datalist shows every option instead of just the
// ones matching whatever symbol is already typed in. Selecting a datalist
// option doesn't blur the input, so "focus" alone only fires on the first
// click; "click" fires every time, including while already focused. Only
// stash the previous value when the field is non-empty so the focus+click
// pair fired by a single first click doesn't clobber it with "".
function openSymbolList() {
  if (symbolInput.value !== "") {
    symbolInput.dataset.prevValue = symbolInput.value;
  }
  symbolInput.value = "";
}

symbolInput.addEventListener("focus", openSymbolList);
symbolInput.addEventListener("click", openSymbolList);

symbolInput.addEventListener("blur", () => {
  if (!symbolInput.value.trim()) {
    symbolInput.value = symbolInput.dataset.prevValue || "";
  }
});

// Explicit clear button: always empties the field and refocuses it so the
// datalist popup opens with the full list, no click/focus quirks involved.
symbolClearBtn.addEventListener("click", () => {
  openSymbolList();
  symbolInput.focus();
});

periodSelect.addEventListener("change", loadFinancials);

syncChipState();
loadFinancials();
