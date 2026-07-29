import re
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
from flask import Blueprint, jsonify, render_template, request

import symbols as symbols_config
from auth import current_user_id
from symbols import load_config, load_symbols

price_bp = Blueprint("price", __name__)

SMA_WINDOW = 150

# Tickers as Yahoo writes them: letters, digits, dot, dash (BRK-B, RY.TO).
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")

RANGE_DAYS = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
}


def get_ticker_info(ticker: str) -> dict:
    """One info fetch reused for both company name and live price — an extra
    yfinance call per ticker (on top of yf.download) makes Yahoo's rate
    limiting more likely, which shows up as charts that silently fail to
    render."""
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


def get_company_name(ticker: str, info: dict) -> str:
    return info.get("longName") or info.get("shortName") or ticker


def get_current_price(info: dict):
    """Live/last-traded price, so the chart doesn't lag a full day behind
    (yf.download's daily bars don't include today until after market close)."""
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    return None if price is None else round(float(price), 2)


def fetch_stock(ticker: str, range_key: str):
    display_days = RANGE_DAYS[range_key]
    # SMA_WINDOW is in trading days; pad with the 7/5 calendar-to-trading ratio
    # plus a generous buffer for holidays so SMA150 is defined from day one.
    fetch_days = display_days + int(SMA_WINDOW * 1.5) + 30
    end = datetime.now()
    start = end - timedelta(days=fetch_days)

    df = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=True,
    )

    if df.empty:
        return {"ticker": ticker, "name": ticker, "error": "No data returned"}

    # yfinance may return MultiIndex columns when a single ticker is passed
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df["SMA150"] = df["Close"].rolling(window=SMA_WINDOW).mean()

    cutoff = end - timedelta(days=display_days)
    view = df[df.index >= pd.Timestamp(cutoff)]

    dates = [d.strftime("%Y-%m-%d") for d in view.index]
    prices = [None if pd.isna(v) else round(float(v), 2) for v in view["Close"]]
    smas = [None if pd.isna(v) else round(float(v), 2) for v in view["SMA150"]]
    volumes = [None if pd.isna(v) else int(v) for v in view["Volume"]]

    info = get_ticker_info(ticker)

    # Append (or refresh) today's live price so the line doesn't stop at
    # yesterday's close while the market is open.
    today = end.strftime("%Y-%m-%d")
    current_price = get_current_price(info)
    if current_price is not None:
        if dates and dates[-1] == today:
            prices[-1] = current_price
        else:
            dates.append(today)
            prices.append(current_price)
            smas.append(None)
            volumes.append(None)

    return {
        "ticker": ticker,
        "name": get_company_name(ticker, info),
        "dates": dates,
        "prices": prices,
        "sma150": smas,
        "volumes": volumes,
    }


@price_bp.route("/")
def index():
    config = load_config(current_user_id())
    symbols = config["default_stocks"]
    disabled = set(config.get("disabled_stocks", []))
    enabled_symbols = [s for s in symbols if s not in disabled]
    return render_template(
        "price.html",
        active_tab="price",
        default_stocks=",".join(enabled_symbols),
        default_range=config["default_range"],
        symbols=symbols,
    )


def _clean_symbol(raw: str):
    """Normalise a user-supplied ticker, or return (None, error message)."""
    symbol = (raw or "").strip().upper()
    if not symbol:
        return None, "No symbol provided"
    if not SYMBOL_RE.match(symbol):
        return None, f"'{symbol}' doesn't look like a ticker symbol"
    return symbol, None


def symbol_exists(symbol: str) -> bool:
    """Cheap sanity check so typos don't get saved into the list."""
    try:
        history = yf.Ticker(symbol).history(period="5d")
        return not history.empty
    except Exception:
        return False


@price_bp.route("/api/symbols", methods=["POST"])
def api_add_symbol():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    symbol, error = _clean_symbol(payload.get("symbol"))
    if error:
        return jsonify({"error": error}), 400

    if symbol in load_symbols(user_id):
        return jsonify({"error": f"{symbol} is already in your list"}), 409

    if not symbol_exists(symbol):
        return jsonify({"error": f"No price data found for {symbol}"}), 404

    return jsonify(
        {"symbols": symbols_config.add_symbol(user_id, symbol), "added": symbol}
    )


@price_bp.route("/api/symbols/<symbol>/status", methods=["POST"])
def api_set_symbol_status(symbol: str):
    user_id = current_user_id()
    symbol, error = _clean_symbol(symbol)
    if error:
        return jsonify({"error": error}), 400

    if symbol not in load_symbols(user_id):
        return jsonify({"error": f"{symbol} is not in your list"}), 404

    payload = request.get_json(silent=True) or {}
    enabled = bool(payload.get("enabled", True))
    symbols_config.set_symbol_enabled(user_id, symbol, enabled)
    return jsonify({"symbol": symbol, "enabled": enabled})


@price_bp.route("/api/symbols/<symbol>", methods=["DELETE"])
def api_remove_symbol(symbol: str):
    user_id = current_user_id()
    symbol, error = _clean_symbol(symbol)
    if error:
        return jsonify({"error": error}), 400

    if symbol not in load_symbols(user_id):
        return jsonify({"error": f"{symbol} is not in your list"}), 404

    return jsonify(
        {"symbols": symbols_config.remove_symbol(user_id, symbol), "removed": symbol}
    )


@price_bp.route("/api/stocks")
def api_stocks():
    tickers_param = request.args.get("tickers", "")
    range_key = request.args.get("range", "1y")

    if range_key not in RANGE_DAYS:
        return jsonify({"error": f"Invalid range: {range_key}"}), 400

    tickers = [t.strip().upper() for t in tickers_param.split(",") if t.strip()]
    if not tickers:
        return jsonify({"error": "No tickers provided"}), 400

    results = [fetch_stock(t, range_key) for t in tickers]
    return jsonify({"range": range_key, "stocks": results})
