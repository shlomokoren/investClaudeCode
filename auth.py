"""Google SSO (OpenID Connect) via Authlib, with cookie-based sessions.

Flow: /login shows the button → /auth/google redirects to Google →
/auth/google/callback verifies the ID token, upserts the app_user row keyed on
the (verified) email, and stores {id, email, name} in Flask's signed session
cookie. The cookie is permanent, so a returning user is already authenticated
and never sees Google again until it expires; because it's signed rather than
server-side state, it works across gunicorn workers with no session store.

init_app() installs a global before_request gate, so a new route is protected by
default — anything reachable without login has to be named in PUBLIC_ENDPOINTS.
"""

import os
from datetime import timedelta
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import db

auth_bp = Blueprint("auth", __name__)
oauth = OAuth()

GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"
SESSION_USER_KEY = "user"
SESSION_LIFETIME = timedelta(days=30)

# Endpoints reachable without a session. Everything else requires login.
PUBLIC_ENDPOINTS = {
    "static",
    "healthz",
    "auth.login",
    "auth.google_login",
    "auth.google_callback",
    "auth.dev_login",
}


# --- setup ---------------------------------------------------------------


def init_app(app) -> None:
    app.permanent_session_lifetime = SESSION_LIFETIME
    # Assigned, not setdefault(): Flask ships these keys with weaker defaults
    # already present, so setdefault() would silently leave them as they are.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Cookies only travel over HTTPS unless we're running the local debug server.
    app.config["SESSION_COOKIE_SECURE"] = not app.debug

    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url=GOOGLE_METADATA_URL,
        client_kwargs={"scope": "openid email profile"},
    )

    app.register_blueprint(auth_bp)
    app.before_request(_reject_cross_origin_writes)
    app.before_request(_require_login)
    app.context_processor(lambda: {"current_user": current_user()})

    bypass_email = dev_login_email(app)
    if bypass_email:
        app.logger.warning(
            "DEV_LOGIN_EMAIL is set and DEBUG is on: /auth/dev-login will sign "
            "anyone in as %s. Never set this in production.",
            bypass_email,
        )


def google_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID")) and bool(
        os.environ.get("GOOGLE_CLIENT_SECRET")
    )


def dev_login_email(app=None):
    """Local-only login bypass: needs DEV_LOGIN_EMAIL *and* debug mode.

    Takes an explicit app so init_app() can call it before any app context
    exists; inside a request, current_app is used.
    """
    email = (os.environ.get("DEV_LOGIN_EMAIL") or "").strip().lower()
    if not email:
        return None
    if not (app or current_app).debug:
        return None
    return email


# --- session helpers -----------------------------------------------------


def current_user():
    return session.get(SESSION_USER_KEY)


def current_user_id():
    user = current_user()
    return user["id"] if user else None


def login_required(view):
    """Belt-and-braces decorator; the before_request gate already covers routes."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            return _unauthenticated_response()
        return view(*args, **kwargs)

    return wrapper


def _sign_in(email: str, name: str, provider: str, provider_sub: str) -> dict:
    user = db.upsert_user(
        email=email.strip().lower(), provider=provider, provider_sub=provider_sub, name=name
    )
    db.ensure_user_defaults(user["id"])
    session.permanent = True
    session[SESSION_USER_KEY] = user
    return user


def _unauthenticated_response():
    if request.path.startswith("/api/"):
        return jsonify({"error": "Login required"}), 401
    return redirect(url_for("auth.login", next=request.full_path))


def _safe_next(raw: str) -> str:
    """Only allow same-site relative redirects."""
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return url_for("price.index")


# --- request gates -------------------------------------------------------


def _require_login():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if current_user():
        return None
    return _unauthenticated_response()


def _reject_cross_origin_writes():
    """Cheap CSRF guard: cookie auth + state-changing request must be same-origin."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return jsonify({"error": "Cross-origin request rejected"}), 403
    return None


# --- routes --------------------------------------------------------------


@auth_bp.route("/login")
def login():
    if current_user():
        return redirect(_safe_next(request.args.get("next")))
    return render_template(
        "login.html",
        next_url=request.args.get("next", ""),
        google_enabled=google_configured(),
        dev_login_email=dev_login_email(),
    )


@auth_bp.route("/auth/google")
def google_login():
    if not google_configured():
        return (
            render_template(
                "login.html",
                next_url="",
                google_enabled=False,
                dev_login_email=dev_login_email(),
                error="Google sign-in isn't configured on this server "
                "(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are missing).",
            ),
            503,
        )

    session["next_url"] = _safe_next(request.args.get("next"))
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/google/callback")
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
    except Exception as exc:  # bad state, expired code, user denied consent…
        current_app.logger.warning("Google callback failed: %s", exc)
        return _login_error("Sign-in failed or was cancelled. Please try again.")

    info = token.get("userinfo") or {}
    email = (info.get("email") or "").strip().lower()

    if not email:
        return _login_error("Google didn't return an email address for that account.")
    if info.get("email_verified") is False:
        return _login_error(f"The email {email} isn't verified with Google.")

    _sign_in(
        email=email,
        name=info.get("name"),
        provider="google",
        provider_sub=info.get("sub"),
    )
    return redirect(_safe_next(session.pop("next_url", None)))


@auth_bp.route("/auth/dev-login", methods=["POST"])
def dev_login():
    """Sign in without Google. Only live when DEV_LOGIN_EMAIL is set in debug mode."""
    email = dev_login_email()
    if not email:
        return jsonify({"error": "Dev login is disabled"}), 404

    _sign_in(email=email, name="Dev user", provider="dev", provider_sub=None)
    current_app.logger.warning("Dev login used for %s", email)
    return redirect(_safe_next(request.form.get("next")))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def _login_error(message: str, status: int = 400):
    return (
        render_template(
            "login.html",
            next_url="",
            google_enabled=google_configured(),
            dev_login_email=dev_login_email(),
            error=message,
        ),
        status,
    )
