import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"
SMA_WINDOW = 150

RANGE_DAYS = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
}


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_company_name(ticker: str) -> str:
    try:
        info = yf.Ticker(ticker).info or {}
        return info.get("longName") or info.get("shortName") or ticker
    except Exception:
        return ticker


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

    return {
        "ticker": ticker,
        "name": get_company_name(ticker),
        "dates": dates,
        "prices": prices,
        "sma150": smas,
        "volumes": volumes,
    }


@app.route("/")
def index():
    config = load_config()
    return render_template(
        "index.html",
        default_stocks=",".join(config["default_stocks"]),
        default_range=config["default_range"],
    )


@app.route("/api/stocks")
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


if __name__ == "__main__":
    import os

    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("DEBUG", "true").lower() == "true",
    )
