import yfinance as yf
from flask import Blueprint, jsonify, render_template, request

from auth import current_user_id
from symbols import load_positions, load_symbols, set_position

status_bp = Blueprint("status", __name__)


def get_symbol_status(ticker: str) -> dict:
    """One info fetch per symbol, reused for name/previous-close/current
    price — see blueprints/price.py for why that matters (fewer calls, less
    Yahoo rate-limiting)."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}

    name = info.get("longName") or info.get("shortName") or ticker
    previous_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    change_pct = None
    if previous_close and current_price is not None:
        change_pct = round((current_price - previous_close) / previous_close * 100, 2)

    return {
        "ticker": ticker,
        "name": name,
        "previous_close": round(float(previous_close), 2) if previous_close is not None else None,
        "current_price": round(float(current_price), 2) if current_price is not None else None,
        "change_pct": change_pct,
    }


@status_bp.route("/status")
def index():
    return render_template("status.html", active_tab="status")


@status_bp.route("/api/status")
def api_status():
    user_id = current_user_id()
    symbols = load_symbols(user_id)
    positions = load_positions(user_id)

    rows = []
    for symbol in symbols:
        row = get_symbol_status(symbol)
        row["position"] = positions.get(symbol, 0)
        rows.append(row)

    return jsonify({"rows": rows})


@status_bp.route("/api/status/position", methods=["POST"])
def api_set_position():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    symbol = (payload.get("symbol") or "").strip().upper()

    if symbol not in load_symbols(user_id):
        return jsonify({"error": f"{symbol} is not in your list"}), 404

    try:
        position = float(payload.get("position", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Position must be a number"}), 400

    if position < 0:
        return jsonify({"error": "Position can't be negative"}), 400

    set_position(user_id, symbol, position)
    return jsonify({"symbol": symbol, "position": position})
