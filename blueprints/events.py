"""Events tab: each watch-list symbol's upcoming earnings date and dividend
schedule, pulled from yfinance.

yfinance is queried once per symbol for three things — ``Ticker.calendar``
(next earnings / ex-dividend / pay dates), ``Ticker.info`` (names, fallback
dates, annual dividend rate) and ``Ticker.dividends`` (history, for the last
paid amount and the payout frequency). Those are three network calls per
symbol on top of whatever the other tabs already do, and this app fights
Yahoo rate-limiting everywhere, so results are cached per-process for
CACHE_TTL_SECONDS. These dates don't move intraday, so a long TTL is fine;
the cache resets on restart/redeploy like the financials one.
"""

import logging
import math
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from flask import Blueprint, jsonify, render_template, request

from auth import current_user_id
from symbols import load_events_hidden, load_symbols, set_events_symbol_hidden

events_bp = Blueprint("events", __name__)

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 6 * 60 * 60
_cache = {}

# Median gap (in days) between consecutive dividends -> a human label.
_FREQUENCY_BUCKETS = [
    (45, "Monthly"),
    (135, "Quarterly"),
    (270, "Semi-annual"),
    (450, "Annual"),
]


def _as_date(value):
    """Coerce the many shapes yfinance hands back (date, datetime, pandas
    Timestamp, epoch seconds, or a list of any of those) to a plain
    ``datetime.date``, or None."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        dates = [d for d in (_as_date(v) for v in value) if d is not None]
        if not dates:
            return None
        # 'Earnings Date' is sometimes a [start, end] range — the earliest
        # still-upcoming date is the useful one; otherwise the earliest.
        today = date.today()
        upcoming = sorted(d for d in dates if d >= today)
        return upcoming[0] if upcoming else min(dates)
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _clean_float(value):
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _calendar_dict(ticker):
    """``Ticker.calendar`` is a dict in current yfinance but was a DataFrame in
    older versions — normalise to a dict, or {} on any failure."""
    try:
        cal = ticker.calendar
    except Exception:
        logger.exception("calendar fetch failed")
        return {}
    if cal is None:
        return {}
    if isinstance(cal, dict):
        return cal
    if isinstance(cal, pd.DataFrame):
        if cal.empty:
            return {}
        return {idx: cal.loc[idx].iloc[0] for idx in cal.index}
    return {}


def _dividend_history(ticker):
    """(last_amount, frequency_label, last_date) from the dividend history, or
    (None, None, None)."""
    try:
        series = ticker.dividends
    except Exception:
        return None, None, None
    if series is None or len(series) == 0:
        return None, None, None

    last_amount = _clean_float(series.iloc[-1])
    last_date = _as_date(series.index[-1])

    frequency = None
    recent = series.tail(6)
    if len(recent) >= 2:
        gaps = recent.index.to_series().diff().dropna().dt.days
        if len(gaps):
            median_gap = float(gaps.median())
            for limit, label in _FREQUENCY_BUCKETS:
                if median_gap <= limit:
                    frequency = label
                    break
    return last_amount, frequency, last_date


def _fetch_symbol_events(symbol):
    ticker = yf.Ticker(symbol)

    try:
        info = ticker.info or {}
    except Exception:
        logger.exception("info fetch failed for %s", symbol)
        info = {}

    cal = _calendar_dict(ticker)

    name = info.get("longName") or info.get("shortName") or symbol

    earnings_date = _as_date(cal.get("Earnings Date"))
    if earnings_date is None:
        earnings_date = _as_date(
            info.get("earningsTimestampStart") or info.get("earningsTimestamp")
        )
    # A start/end pair that doesn't line up means yfinance only has an
    # estimated window, not a confirmed day.
    start = _as_date(info.get("earningsTimestampStart"))
    end = _as_date(info.get("earningsTimestampEnd"))
    earnings_estimated = bool(start and end and start != end)

    ex_div_date = _as_date(cal.get("Ex-Dividend Date")) or _as_date(
        info.get("exDividendDate")
    )
    pay_date = _as_date(cal.get("Dividend Date")) or _as_date(
        info.get("dividendDate")
    )

    last_dividend, frequency, last_div_date = _dividend_history(ticker)
    if last_dividend is None:
        last_dividend = _clean_float(info.get("lastDividendValue"))

    # A company that hasn't paid in well over a year isn't a dividend payer
    # today — yfinance still reports the ancient last payment (Adobe's 2005
    # token dividend, AMD's 1995 ex-date), which is just noise here. Drop any
    # dividend field anchored before the cutoff.
    stale_cutoff = date.today() - timedelta(days=400)
    if last_div_date is not None and last_div_date < stale_cutoff:
        last_dividend = frequency = None
    if ex_div_date and ex_div_date < stale_cutoff:
        ex_div_date = None
    if pay_date and pay_date < stale_cutoff:
        pay_date = None

    annual_rate = _clean_float(info.get("dividendRate")) or _clean_float(
        info.get("trailingAnnualDividendRate")
    )

    # dividendYield's units flip-flopped between yfinance versions (fraction vs
    # percent), so derive it ourselves from the annual rate and price when we
    # can and only fall back to the reported field otherwise.
    price = _clean_float(info.get("currentPrice")) or _clean_float(
        info.get("regularMarketPrice")
    )
    dividend_yield = None
    if annual_rate and price:
        dividend_yield = round(annual_rate / price * 100, 2)
    else:
        reported = _clean_float(info.get("trailingAnnualDividendYield"))
        if reported is not None:
            dividend_yield = round(reported * 100, 2)

    # A reported zero means "no dividend", which reads better as a blank cell.
    if not last_dividend:
        last_dividend = None
    if not annual_rate:
        annual_rate = None
    if not dividend_yield:
        dividend_yield = None

    today = date.today()
    days_to_earnings = (earnings_date - today).days if earnings_date else None

    return {
        "ticker": symbol,
        "name": name,
        "earnings_date": earnings_date.isoformat() if earnings_date else None,
        "earnings_estimated": earnings_estimated,
        "days_to_earnings": days_to_earnings,
        "ex_dividend_date": ex_div_date.isoformat() if ex_div_date else None,
        "pay_date": pay_date.isoformat() if pay_date else None,
        "last_dividend": round(last_dividend, 4) if last_dividend is not None else None,
        "annual_rate": round(annual_rate, 2) if annual_rate is not None else None,
        "dividend_yield": dividend_yield,
        "frequency": frequency,
    }


def _symbol_events(symbol):
    cached = _cache.get(symbol)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    try:
        data = _fetch_symbol_events(symbol)
    except Exception:
        logger.exception("Failed to fetch events for %s", symbol)
        data = {
            "ticker": symbol,
            "name": symbol,
            "earnings_date": None,
            "earnings_estimated": False,
            "days_to_earnings": None,
            "ex_dividend_date": None,
            "pay_date": None,
            "last_dividend": None,
            "annual_rate": None,
            "dividend_yield": None,
            "frequency": None,
            "error": True,
        }
    _cache[symbol] = (time.time(), data)
    return data


@events_bp.route("/events")
def index():
    user_id = current_user_id()
    return render_template(
        "events.html",
        active_tab="events",
        symbols=load_symbols(user_id),
        hidden=load_events_hidden(user_id),
    )


@events_bp.route("/api/events/symbols/<symbol>", methods=["POST"])
def api_set_symbol_selected(symbol):
    """Remember whether a symbol is shown on the Events tab, so the filter
    survives a refresh or reopening the tab."""
    user_id = current_user_id()
    symbol = symbol.strip().upper()
    if symbol not in load_symbols(user_id):
        return jsonify({"error": f"{symbol} is not in your list"}), 404

    payload = request.get_json(silent=True) or {}
    selected = bool(payload.get("selected", True))
    set_events_symbol_hidden(user_id, symbol, hidden=not selected)
    return jsonify({"symbol": symbol, "selected": selected})


@events_bp.route("/api/events")
def api_events():
    user_id = current_user_id()
    watch_list = load_symbols(user_id)

    requested = request.args.get("symbols", "")
    selected = [s.strip().upper() for s in requested.split(",") if s.strip()]
    if selected:
        symbols = [s for s in selected if s in watch_list]
    else:
        hidden = set(load_events_hidden(user_id))
        symbols = [s for s in watch_list if s not in hidden]

    rows = [_symbol_events(symbol) for symbol in symbols]
    return jsonify({"rows": rows})
