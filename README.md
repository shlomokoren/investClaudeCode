# investClaudeCode

A small Flask app for tracking stocks, built with Claude Code. It has two tabs:

- **Price vs SMA150** (`/`) — price + 150-day moving average + volume chart per ticker.
- **Financials** (`/financials`) — quarterly/annual revenue, profit, income, free cash flow, and EPS charts for a single ticker.

It's multi-user: sign in with Google and you get your own watch list, stored in Postgres (Neon). Every page requires login; a brand-new account starts with an empty list.

The list is editable from the **Price vs SMA150** tab: type a symbol in *Add symbol* to append it, or click the **×** on a chip to drop it. Changes save immediately and apply to both of your tabs. Clicking the chip itself (not the ×) still just toggles whether that ticker is charted right now.

## Project layout

```
app.py                  # entry point, registers blueprints, /healthz
auth.py                 # Google SSO (Authlib), session cookie, login gate
db.py                   # Postgres pool + app_config / app_user / user_config access
symbols.py              # global config (cached 60s) + per-user watch lists (never cached)
init_db.py              # creates the tables and seeds them from config.json
blueprints/
  price.py              # /  and /api/stocks
  financials.py         # /financials and /api/financials
templates/
  base.html             # shared layout + tab nav + signed-in user / sign out
  login.html
  price.html
  financials.html
public/
  css/style.css
  js/price.js
  js/dashboard.js
config.json             # seed values for the database only (not read at runtime)
.env                    # secrets (gitignored, see .env.example)
```

## Authentication

Google sign-in (OpenID Connect) handled server-side by Authlib. The session is a
signed cookie — permanent for 30 days, `HttpOnly`, `SameSite=Lax`, and `Secure`
whenever `DEBUG` is off — so returning users are already authenticated and no
session store is needed across gunicorn workers.

Login is enforced by a global `before_request` gate in [auth.py](auth.py), so new routes are
protected by default; only `/login`, the `/auth/...` routes, `/healthz`, and static
files are public. State-changing requests are additionally rejected if their
`Origin` header isn't this host.

To set it up, create an OAuth client (Google Cloud Console → APIs & Services →
Credentials → OAuth client ID → *Web application*) and add these authorized
redirect URIs:

```
http://127.0.0.1:5000/auth/google/callback
https://YOUR-DEPLOYED-HOST/auth/google/callback
```

Put the client ID/secret plus a random `SECRET_KEY` in `.env`. For local work
without Google credentials, set `DEV_LOGIN_EMAIL=you@example.com` — that adds a
one-click bypass button to the login page. It's ignored unless `DEBUG=true`, and
must never be set in production.

## Configuration

Three tables ([db.py](db.py)):

```sql
app_config(key text primary key, value jsonb, updated_at)              -- global
app_user(id, email unique, provider, provider_sub, name, ...)          -- accounts
user_config(user_id -> app_user, key, value jsonb, updated_at)         -- per user
```

Global keys mirror the old `config.json` top level: `default_range`, `alerts`,
plus `default_stocks`/`owner_email` used only for seeding. Watch lists are
per-user in `user_config`; a new account gets `default_stocks = []` and other
keys fall back to `app_config`.

The list is normally edited from the Price tab, which calls `POST /api/symbols`
(`{"symbol": "PLTR"}`) and `DELETE /api/symbols/<symbol>` — both scoped to the
signed-in user. Direct SQL for one user:

```sql
UPDATE user_config SET value = '["AAPL","MSFT","NVDA"]', updated_at = now()
WHERE key = 'default_stocks'
  AND user_id = (SELECT id FROM app_user WHERE email = 'you@example.com');
```

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env      # Neon URL, SECRET_KEY, Google client ID/secret
python init_db.py         # create the tables and seed them from config.json
python app.py
```

Then open http://127.0.0.1:5000. Environment variables: `DATABASE_URL` and
`SECRET_KEY` (both required — the app refuses to start without a secret key),
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (required for real login),
`DEV_LOGIN_EMAIL` (local bypass), plus `HOST`, `PORT`, `DEBUG`.

`init_db.py` also takes `--show` (dump global config, users, and each user's
list), `--force` (overwrite existing values), and `--seed-user EMAIL` (pre-create
an account with the seed watch list before its first login).

## Docker

```bash
docker build -t investclaudecode:dev01 .
docker run -it --rm -p 5000:5000 --env-file .env -d --name invest investclaudecode:dev01
```

(see [dockerstart.cmd](dockerstart.cmd))

## Deployment

Every target needs `DATABASE_URL`, `SECRET_KEY`, `GOOGLE_CLIENT_ID`, and
`GOOGLE_CLIENT_SECRET` in its environment, and its own callback URL registered
with Google. Health checks use `/healthz` because `/` now redirects to login.

- **Render**: [render.yaml](render.yaml) — `gunicorn app:app`, health check on `/healthz`. `SECRET_KEY` is auto-generated (`generateValue: true`); the other three are `sync: false`, so set them in the dashboard.
- **Kubernetes / OpenShift**: manifests under [k8s/](k8s/) (namespace, secret, deployment, service, ingress, OpenShift route). All four values come from the `invest-app-db` secret — create it with `kubectl create secret` rather than committing values.
- **Heroku-style**: [Procfile](Procfile) — same `gunicorn app:app` command; set all four as config vars.

## Data source

Stock prices and financial statements come from [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo Finance), fetched on demand. The Financials tab caches responses in memory for 24 hours per symbol/period.

## Releases

The running version is `__version__` in [app.py](app.py); it's also returned by
`/healthz` (`{"status": "ok", "version": "..."}`) and shown at the bottom of the
Help page. Keep it in step with the matching `vX.Y.Z` git tag.

Versioning is `MAJOR.MINOR.PATCH`:

| Bump | When | e.g. |
|------|------|------|
| MAJOR | A deploy needs manual work | DB migration, renamed/removed env var, auth change, redesign |
| MINOR | New backward-compatible feature | a new tab or endpoint |
| PATCH | Fixes and polish only | bug fixes, copy, styling, refactors |

To cut a release: bump `__version__`, merge to `main`, then

```bash
git tag -a v2.1.0 -m "short summary of what shipped"
git push origin v2.1.0
```

`git describe --tags` gives an interim version between releases
(`v2.0.0-7-gabc1234`).
