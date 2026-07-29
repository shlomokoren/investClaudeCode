# Agent Guide for investClaudeCode

## What this project is
- A small Flask web app for authenticated stock tracking.
- Users sign in with Google and manage their own watch list.
- Price charts use Yahoo Finance data via `yfinance`.
- Financial data is also fetched from `yfinance` and cached in memory.

## Key files
- `app.py` — app factory and blueprint registration.
- `auth.py` — Google OIDC login gate, session cookie setup, CSRF-style origin checks.
- `db.py` — Postgres access layer, `app_config`, `app_user`, `user_config` tables.
- `symbols.py` — global config caching + per-user watch list logic.
- `init_db.py` — schema creation and seed data from `config.json`.
- `blueprints/price.py` — price page + ticker list API.
- `blueprints/financials.py` — financials page + statement extraction.
- `templates/` and `static/` — shared page layout plus page-specific assets.

## Useful behavior notes
- Every page requires login except `/login`, OAuth callback routes, `/healthz`, and static files.
- The login gate is installed globally in `auth.init_app()`.
- `config.json` is a database seed file only; it is not read at runtime.
- New routes should be validated against the auth gate and public endpoint allowlist when appropriate.
- The app uses signed cookies for session state; there is no server-side session store.
- Top-level runtime imports must also be added to `Dockerfile` `COPY` lines.

## Run / debug commands
```bash
pip install -r requirements.txt
python init_db.py
python app.py
```

Docker:
```bash
docker build -t investclaudecode:dev01 .
docker run -it --rm -p 5000:5000 --env-file .env -d --name invest investclaudecode:dev01
```

## Environment requirements
- `DATABASE_URL` — required
- `SECRET_KEY` — required
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — required for real login
- `DEV_LOGIN_EMAIL` — local debug bypass only when `DEBUG=true`
- `HOST`, `PORT`, `DEBUG` — optional runtime config

## Deployment contract
- Uses `gunicorn app:app` in Docker/Render/Procfile/k8s manifests.
- Health checks must target `/healthz`.
- Google callback URI must match deployed host: `/auth/google/callback`.

## Important conventions for AI agents
- Preserve user-specific config separation: per-user watch lists are stored in `user_config`, global app defaults are in `app_config`.
- `symbols.py` intentionally caches only global config for 60 seconds, not per-user config.
- `price.py` validates ticker additions with regex, duplicate detection, and a `yfinance` history probe.
- The price page and financials page render ticker chips separately; changes should stay compatible with both.

## Documentation references
- See `README.md` for architecture, auth, config, and deployment details.
- See `CLAUDE.md` for quick commands and behavior notes.
