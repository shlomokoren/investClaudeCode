# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env          # DATABASE_URL, SECRET_KEY, GOOGLE_CLIENT_ID/SECRET (see below)
python init_db.py             # create the tables and seed them from config.json
python init_db.py --show      # dump global config + every user and their watch list
python app.py                 # runs on 127.0.0.1:5000 by default (HOST/PORT/DEBUG env vars)
```

Required env vars: `DATABASE_URL` and `SECRET_KEY` (app refuses to start without the
latter), `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` for real login. For local work
without Google credentials, `DEV_LOGIN_EMAIL=you@example.com` adds a one-click login
bypass to `/login` — double-gated on `DEBUG=true`, so it's inert in any deployment.

Docker:
```bash
docker build -t investclaudecode:dev01 .
docker run -it --rm -p 5000:5000 --env-file .env -d --name invest investclaudecode:dev01
```

There are no automated tests or linters configured in this repo currently.

`AGENTS.md` is a condensed duplicate of this file for non-Claude agents — if you change architecture-relevant facts here (env vars, file responsibilities, deployment contract), mirror the change there too.

## Architecture

Multi-user Flask app with two feature areas wired together as blueprints, sharing one login gate and one page layout. Every user has their own watch list.

- **`app.py`** — creates the `Flask` app, sets `app.debug` from `DEBUG` *before* `auth.init_app()` (cookie flags depend on it), requires `SECRET_KEY` (no fallback — a fixed default would let anyone forge a session), registers the two blueprints and a public `/healthz` used by deployment probes since `/` now redirects to login.
- **`auth.py`** — Google OIDC via Authlib. `init_app()` installs a global `before_request` login gate, so **new routes are protected by default**; anything public must be named in `PUBLIC_ENDPOINTS`. Also installs `_reject_cross_origin_writes` (cheap CSRF guard: non-GET with a foreign `Origin` → 403) and a context processor exposing `current_user` to templates. Sessions are signed cookies (permanent, 30 days, `HttpOnly`/`SameSite=Lax`/`Secure` unless debugging) — no server-side store, so they work across gunicorn workers. Cookie flags are **assigned, not `setdefault()`**: Flask ships those keys with weaker defaults already present, so `setdefault` would silently no-op. Login upserts `app_user` keyed on the verified email, then `db.ensure_user_defaults()` gives new users an empty list. `/auth/dev-login` is a local bypass gated on `DEV_LOGIN_EMAIL` *and* `current_app.debug`; `dev_login_email(app=None)` takes an explicit app because `init_app()` runs outside any app context.
- **`db.py`** — Postgres (Neon) access layer. `DATABASE_URL` is read from the environment or a local `.env` (loaded via `python-dotenv`); there is no hardcoded fallback, so a missing value raises at first DB use rather than silently degrading. Three tables: `app_config(key, value jsonb, updated_at)` for global settings, `app_user(id, email unique, provider, provider_sub, name, created_at, last_login_at)`, and `user_config(user_id -> app_user ON DELETE CASCADE, key, value jsonb, updated_at)` keyed `(user_id, key)`. `upsert_user()` matches on **email**, not `provider_sub`, so `init_db.py` can pre-seed an account before its first login and the real login updates that row in place. A lazily-created `psycopg_pool.ConnectionPool` (`min_size=0`, `max_size=4`) is per-process, so each gunicorn worker holds its own; `close_pool()` exists for scripts.
- **`init_db.py`** — one-off bootstrap: `ensure_schema()`, seed global keys from `config.json`, then seed `owner_email`'s watch list (`--force` to overwrite, `--show` to dump config + users + lists, `--seed-user EMAIL` to target another account). It reads the live `app_config` ticker list *before* overwriting globals, so UI edits aren't lost to a stale `config.json`. `config.json` is *only* a seed file — nothing reads it at request time.
- **`symbols.py`** — global settings (`load_global_config()`) are cached in-process for `CACHE_TTL_SECONDS` (60) since they're identical for everyone. **Per-user config is deliberately never cached** — a shared cache would serve one user's ticker list to another, and it's a single primary-key lookup on `user_config`. `load_config(user_id)` layers the user's rows over the globals but forces `default_stocks` to `[]` first, so a user who has added nothing gets an empty list rather than the global seed list. `load_symbols(user_id)`, `add_symbol(user_id, symbol)`, and `remove_symbol(user_id, symbol)` are all user-scoped. Both blueprints pass the signed-in user's list into their template as `symbols`, which renders a row of clickable ticker chips on both pages (`static/js/price.js` and `static/js/dashboard.js` each wire up click handling for their own page's chips independently — there's no shared JS between the two). The price page wraps each chip in `.chip-wrap` with a `.chip-remove` × button and adds an *Add symbol* form; the financials page renders bare `.chip` buttons, so keep `.chip` styling changes safe for both.
- **`templates/base.html`** — shared layout (tab nav + `<head>`/Chart.js include). The nav renders tabs, the signed-in email, and a POST sign-out form only when `current_user` is set, so `login.html` can extend the same base without them. `price.html`, `financials.html`, and `login.html` extend it and fill the `content`/`scripts` blocks. All styling lives in the single `static/css/style.css` (no per-page stylesheets).
- **`blueprints/price.py`** — also owns the ticker-list editor used by the Price tab: `POST /api/symbols` and `DELETE /api/symbols/<symbol>`, both scoped to `current_user_id()`. Adds are validated in three steps (regex `SYMBOL_RE`, duplicate check, then `symbol_exists()` which asks yfinance for 5 days of history) so typos never reach the database. Both endpoints return the full updated list, which `price.js` re-renders chips from. The add/remove SQL in `db.py` is a single atomic statement over the jsonb array rather than a read-modify-write, so concurrent edits can't clobber each other. In `price.js`, `setTickers()` calls `syncChipState()` itself — assigning `input.value` doesn't fire the `input` event, so without that a programmatic change leaves chips looking inactive. `fetch_stock()` pulls extra calendar padding (`display_days + SMA_WINDOW*1.5 + 30`) before the requested display range so the 150-day SMA is fully defined from day one of the visible window, then trims back to the display range before returning JSON.
- **`blueprints/financials.py`** — pulls income statement + cash flow statement via `yfinance`. Row labels aren't consistent across tickers/yfinance versions, so `METRIC_LABELS`/`FREE_CASH_FLOW_LABELS`/etc. list fallback label names, and `_extract_row()` tries them in order. Free Cash Flow is computed as Operating Cash Flow + Capex when yfinance doesn't report it directly (capex is stored negative). Results are cached in an in-memory dict (`_cache`) keyed by `(symbol, period)` for 24 hours — this cache is per-process and resets on restart/redeploy.

### Deployment targets

All deployment configs invoke the same `gunicorn app:app`, all need `DATABASE_URL`, `SECRET_KEY`, `GOOGLE_CLIENT_ID`, and `GOOGLE_CLIENT_SECRET` in the environment, and all probe `/healthz` (not `/`, which redirects to login). Each host's `https://HOST/auth/google/callback` must also be registered as an authorized redirect URI in the Google OAuth client.
- `render.yaml` (Render, health check on `/healthz`; `SECRET_KEY` uses `generateValue: true`, the rest are `sync: false` so values are set in the dashboard)
- `Procfile` (Heroku-style)
- `k8s/` manifests (namespace/secret/deployment/service/ingress/OpenShift route) — all four values come from the `invest-app-db` secret via `secretKeyRef`; the old ConfigMap that mounted `config.json` is gone
- `Dockerfile` (copies `app.py`, `auth.py`, `symbols.py`, `db.py`, `init_db.py`, `config.json`, `blueprints/`, `templates/`, `static/`)

When adding new top-level modules or directories that the app imports at runtime, update the `COPY` lines in `Dockerfile` accordingly.
