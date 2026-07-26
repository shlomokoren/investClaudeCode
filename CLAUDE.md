# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt
python app.py                 # runs on 127.0.0.1:5000 by default (HOST/PORT/DEBUG env vars)
```

Docker:
```bash
docker build -t investclaudecode:dev01 .
docker run -it --rm -p 5000:5000 -v .\config.json:/app/config.json -d --name invest investclaudecode:dev01
```

There are no automated tests or linters configured in this repo currently.

## Architecture

Flask app with two independent feature areas wired together as blueprints, sharing one ticker list and one page layout.

- **`app.py`** — creates the `Flask` app and registers `blueprints/price.py` (mounted at `/`) and `blueprints/financials.py` (mounted at `/financials`). Both blueprints define their own `/api/...` JSON endpoint alongside their page route.
- **`symbols.py`** — single source of truth for the ticker list, read from `config.json`'s `default_stocks`. Both blueprints call `load_symbols()` and pass the result into their template as `symbols`, which renders the same row of clickable ticker chips on both pages (`static/js/price.js` and `static/js/dashboard.js` each wire up click handling for their own page's chips independently — there's no shared JS between the two).
- **`templates/base.html`** — shared layout (tab nav + `<head>`/Chart.js include). `price.html` and `financials.html` extend it and fill the `content`/`scripts` blocks. All styling lives in the single `static/css/style.css` (no per-page stylesheets).
- **`blueprints/price.py`** — `fetch_stock()` pulls extra calendar padding (`display_days + SMA_WINDOW*1.5 + 30`) before the requested display range so the 150-day SMA is fully defined from day one of the visible window, then trims back to the display range before returning JSON.
- **`blueprints/financials.py`** — pulls income statement + cash flow statement via `yfinance`. Row labels aren't consistent across tickers/yfinance versions, so `METRIC_LABELS`/`FREE_CASH_FLOW_LABELS`/etc. list fallback label names, and `_extract_row()` tries them in order. Free Cash Flow is computed as Operating Cash Flow + Capex when yfinance doesn't report it directly (capex is stored negative). Results are cached in an in-memory dict (`_cache`) keyed by `(symbol, period)` for 24 hours — this cache is per-process and resets on restart/redeploy.

### Deployment targets

All deployment configs invoke the same `gunicorn app:app`:
- `render.yaml` (Render, health check on `/`)
- `Procfile` (Heroku-style)
- `k8s/` manifests (namespace/deployment/service/configmap/ingress/OpenShift route)
- `Dockerfile` (copies `app.py`, `symbols.py`, `config.json`, `blueprints/`, `templates/`, `static/`)

When adding new top-level modules or directories that the app imports at runtime, update the `COPY` lines in `Dockerfile` accordingly.
