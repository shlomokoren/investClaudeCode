# Changelog

All notable, user-visible changes to Invest Dashboard are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/) — see
[README → Releases](README.md#releases) for what MAJOR / MINOR / PATCH mean here.

While working, add bullets under **[Unreleased]**. To cut a release, rename
that heading to `## [X.Y.Z] - YYYY-MM-DD`, start a fresh empty `[Unreleased]`,
set `__version__` in `app.py` to match, and merge `dev` → `main` — the release
workflow publishes a GitHub Release using the matching section below as its notes.

## [Unreleased]

### Removed
- Render deployment config (`render.yaml`) and its documentation — the app deploys on Vercel now. Procfile, k8s, and Docker configs are unchanged.

## [2.1.0] - 2026-09-01

### Added
- Automated GitHub Release on every push to `main`, versioned from `__version__` in `app.py`.
- The Financials tab now remembers the last ticker you viewed, so a refresh keeps it.

## [2.0.0] - 2026-09-01

First tagged release.

### Added
- **Price Chart** tab — each watch-list stock's price against its 150-day moving average, with volume; watch list is editable inline.
- **Financials** tab — revenue, profit, free cash flow and EPS charts for one company, quarterly or annual.
- **Portfolio** tab — watch list with live prices and daily change, an editable share position per symbol, total value, and an allocation pie chart.
- **Events** tab — each symbol's next earnings date and dividend schedule (ex-date, pay date, last amount, annual rate, yield, frequency).
- **News** tab — recent Yahoo Finance headlines for the symbols you choose, with an adjustable look-back window.
- Persisted multi-select symbol filter on the Portfolio, Events, and News tabs (remembered per user).
- Multi-user Google sign-in; every user gets a private watch list stored in Postgres.
- `/healthz` reports the running version, which is also shown on the Help page.

### Changed
- Nav tabs are colour-coded and bold.
- The Help page is a per-tab guide — what each tab is, what it's for, and how to use it.
