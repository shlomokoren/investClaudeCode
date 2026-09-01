import os

from flask import Flask, render_template

import auth

# Single source of truth for the release version. Bump on every tagged
# release (see the README): MAJOR for a deploy that needs manual work,
# MINOR for a new feature, PATCH for fixes. Keep this in step with the
# top dated section in CHANGELOG.md and the `vX.Y.Z` git tag.
__version__ = "2.1.0"
from blueprints.events import events_bp
from blueprints.financials import financials_bp
from blueprints.news import news_bp
from blueprints.price import price_bp
from blueprints.status import status_bp


def secret_key() -> str:
    """Session cookies are signed with this — a fixed fallback would let anyone
    forge a login, so refuse to start without it."""
    key = os.environ.get("SECRET_KEY")
    if not key:
        raise RuntimeError(
            "SECRET_KEY is not set. Generate one with "
            '`python -c "import secrets; print(secrets.token_hex(32))"` '
            "and put it in .env (see .env.example)."
        )
    return key


app = Flask(__name__, static_folder="public", static_url_path="")
app.debug = os.environ.get("DEBUG", "true").lower() == "true"
app.secret_key = secret_key()

auth.init_app(app)
app.register_blueprint(price_bp)
app.register_blueprint(financials_bp)
app.register_blueprint(status_bp)
app.register_blueprint(events_bp)
app.register_blueprint(news_bp)


@app.route("/healthz")
def healthz():
    """Public liveness probe — '/' now redirects to login, so probes use this.
    Also reports the running version so you can tell what's deployed."""
    return {"status": "ok", "version": __version__}


@app.route("/help")
def help_page():
    return render_template("help.html", active_tab="help", version=__version__)


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=app.debug,
    )
