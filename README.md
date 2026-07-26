# investClaudeCode

A small Flask app for tracking stocks, built with Claude Code. It has two tabs:

- **Price vs SMA150** (`/`) — price + 150-day moving average + volume chart per ticker.
- **Financials** (`/financials`) — quarterly/annual revenue, profit, income, free cash flow, and EPS charts for a single ticker.

Both tabs share one ticker list (`default_stocks` in [config.json](config.json)), shown as clickable chips on each page.

## Project layout

```
app.py                  # entry point, registers blueprints
symbols.py              # loads the shared ticker list from config.json
blueprints/
  price.py              # /  and /api/stocks
  financials.py         # /financials and /api/financials
templates/
  base.html             # shared layout + tab nav
  price.html
  financials.html
static/
  css/style.css
  js/price.js
  js/dashboard.js
config.json             # default tickers, default range, alert email (alerting not yet wired up)
```

## Running locally

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000. Environment variables: `HOST`, `PORT`, `DEBUG` (all optional, see `app.py`).

## Docker

```bash
docker build -t investclaudecode:dev01 .
docker run -it --rm -p 5000:5000 -v .\config.json:/app/config.json -d --name invest investclaudecode:dev01
```

(see [dockerstart.cmd](dockerstart.cmd))

## Deployment

- **Render**: [render.yaml](render.yaml) — `gunicorn app:app`, health check on `/`.
- **Kubernetes / OpenShift**: manifests under [k8s/](k8s/) (namespace, deployment, service, configmap, ingress, OpenShift route).
- **Heroku-style**: [Procfile](Procfile) — same `gunicorn app:app` command.

## Data source

Stock prices and financial statements come from [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo Finance), fetched on demand. The Financials tab caches responses in memory for 24 hours per symbol/period.
