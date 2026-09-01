import logging
import math
import time

import pandas as pd
import yfinance as yf
from flask import Blueprint, jsonify, render_template, request

from auth import current_user_id
from symbols import load_financials_symbol, load_symbols, set_financials_symbol

financials_bp = Blueprint("financials", __name__)

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 24 * 60 * 60
_cache = {}

# Row labels to look for in the yfinance income statement DataFrame, in
# fallback order. Row names occasionally differ between tickers, so each
# metric may have more than one acceptable label.
METRIC_LABELS = {
    "total_revenue": ["Total Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income"],
    "net_income": ["Net Income"],
    "eps": ["Diluted EPS", "Basic EPS"],
}

# Cash flow statement row labels. Free Cash Flow isn't present as a direct
# row on every ticker/yfinance version, so we fall back to computing it from
# operating cash flow and capital expenditure (capex is reported negative).
FREE_CASH_FLOW_LABELS = ["Free Cash Flow"]
OPERATING_CASH_FLOW_LABELS = ["Operating Cash Flow", "Total Cash From Operating Activities"]
CAPITAL_EXPENDITURE_LABELS = ["Capital Expenditure", "Capital Expenditures"]


def _clean_value(value):
    """Convert a pandas/numpy scalar to a JSON-safe value, NaN -> None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return float(value)


def _extract_row(df, labels):
    """Return the first matching row (as a list, oldest -> newest) or None."""
    for label in labels:
        if label in df.index:
            return [_clean_value(v) for v in df.loc[label].tolist()]
    return None


def _period_label(date, period):
    if period == "quarterly":
        quarter = (date.month - 1) // 3 + 1
        return f"Q{quarter} {date.year}"
    return str(date.year)


def _fetch_free_cash_flow_by_period(ticker, period):
    """Return {period_label: value} for Free Cash Flow, keyed the same way
    as the income statement periods so the two can be joined by label even
    if the underlying statements don't share the exact same date columns."""
    df = ticker.quarterly_cashflow if period == "quarterly" else ticker.cashflow

    if df is None or df.empty:
        return {}

    df = df.sort_index(axis=1, ascending=True)

    fcf_row = _extract_row(df, FREE_CASH_FLOW_LABELS)
    if fcf_row is None:
        ocf_row = _extract_row(df, OPERATING_CASH_FLOW_LABELS)
        capex_row = _extract_row(df, CAPITAL_EXPENDITURE_LABELS)
        if ocf_row is None or capex_row is None:
            return {}
        # capex is reported as a negative outflow, so FCF = OCF + capex.
        fcf_row = [
            None if ocf is None or capex is None else ocf + capex
            for ocf, capex in zip(ocf_row, capex_row)
        ]

    return {
        _period_label(date, period): value
        for date, value in zip(df.columns, fcf_row)
    }


def _fetch_financials(symbol, period):
    ticker = yf.Ticker(symbol)

    if period == "quarterly":
        df = ticker.quarterly_income_stmt
    else:
        df = ticker.income_stmt

    if df is None or df.empty:
        return None

    # yfinance documents columns as newest-first; sort explicitly ascending
    # by date so we don't depend on that ordering holding for every ticker.
    df = df.sort_index(axis=1, ascending=True)

    logger.info("Income statement rows for %s (%s): %s", symbol, period, list(df.index))

    try:
        currency = ticker.info.get("financialCurrency", "USD")
    except Exception:
        logger.exception("Failed to fetch ticker.info for %s", symbol)
        currency = "USD"

    periods = [_period_label(date, period) for date in df.columns]

    metrics = {
        name: _extract_row(df, labels) for name, labels in METRIC_LABELS.items()
    }

    try:
        fcf_by_period = _fetch_free_cash_flow_by_period(ticker, period)
    except Exception:
        logger.exception("Failed to fetch cash flow statement for %s", symbol)
        fcf_by_period = {}
    metrics["free_cash_flow"] = [fcf_by_period.get(label) for label in periods]

    return {
        "symbol": symbol,
        "period": period,
        "currency": currency,
        "periods": periods,
        "metrics": metrics,
    }


@financials_bp.route("/financials")
def index():
    user_id = current_user_id()
    symbols = load_symbols(user_id)
    # Reopen on whatever ticker was last viewed, so a refresh doesn't reset it.
    initial_symbol = load_financials_symbol(user_id) or (
        symbols[0] if symbols else "NVDA"
    )
    return render_template(
        "financials.html",
        active_tab="financials",
        symbols=symbols,
        initial_symbol=initial_symbol,
    )


@financials_bp.route("/api/financials")
def api_financials():
    symbol = request.args.get("symbol", "").strip().upper()
    period = request.args.get("period", "quarterly").strip().lower()

    if not symbol:
        return jsonify({"error": "symbol is required"}), 400

    if period not in ("quarterly", "annual"):
        return jsonify({"error": "period must be 'quarterly' or 'annual'"}), 400

    cache_key = (symbol, period)
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        _remember_symbol(symbol)
        return jsonify(cached[1])

    try:
        data = _fetch_financials(symbol, period)
    except Exception:
        logger.exception("Failed to fetch financials for %s (%s)", symbol, period)
        return jsonify({"error": f"Failed to fetch data for '{symbol}'"}), 404

    if data is None:
        return jsonify({"error": f"No income statement data found for '{symbol}'"}), 404

    _cache[cache_key] = (time.time(), data)
    _remember_symbol(symbol)
    return jsonify(data)


def _remember_symbol(symbol: str) -> None:
    """Persist the last successfully-loaded ticker for this user so the
    Financials tab reopens on it. Best-effort — a DB hiccup here must not
    fail the data response."""
    user_id = current_user_id()
    if not user_id:
        return
    try:
        set_financials_symbol(user_id, symbol)
    except Exception:
        logger.exception("Failed to remember financials symbol %s", symbol)
