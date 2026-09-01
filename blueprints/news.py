"""News tab: recent headlines for the watch-list symbols, from Yahoo Finance
via ``yfinance.Ticker.news``.

Yahoo is the source for the same reasons Price and Financials use yfinance:
no extra dependency, no API key to thread through every deployment config,
and the same in-process caching / rate-limit story that's already
documented. The trade-off is depth — Yahoo returns at most ~10 items per
ticker and can be sparse for small caps, so a short lookback window on a
quiet symbol may legitimately show nothing.

``Ticker.news`` is fetched whole and cached per-symbol for CACHE_TTL_SECONDS;
the ``days`` window is applied after the fetch, so changing it in the UI
never triggers a refetch. Item shape changed in yfinance 1.x (fields moved
under a nested ``content`` dict), so ``_normalise()`` reads both layouts.
"""

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone

import yfinance as yf
from flask import Blueprint, jsonify, render_template, request

from auth import current_user_id
from symbols import load_news_hidden, load_symbols, set_news_symbol_hidden

news_bp = Blueprint("news", __name__)

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 20 * 60
_cache = {}

DEFAULT_DAYS = 2
MAX_DAYS = 30


def _first_url(*candidates):
    for c in candidates:
        if isinstance(c, dict):
            url = c.get("url")
            if url:
                return url
        elif isinstance(c, str) and c:
            return c
    return None


def _thumbnail_url(thumb):
    if not isinstance(thumb, dict):
        return None
    resolutions = thumb.get("resolutions")
    if isinstance(resolutions, list):
        # Prefer a small-ish resolution for a list thumbnail; fall back to the
        # first entry, then the original.
        best = None
        for res in resolutions:
            w = res.get("width") or 0
            if 80 <= w <= 500 and (best is None or w < best[0]):
                best = (w, res.get("url"))
        if best:
            return best[1]
        if resolutions:
            return resolutions[0].get("url")
    return thumb.get("originalUrl")


def _parse_time(value):
    """yfinance gives either an ISO-8601 string (newer) or epoch seconds
    (older). Return an aware UTC datetime, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _normalise(raw, symbol):
    content = raw.get("content") if isinstance(raw.get("content"), dict) else raw

    published = _parse_time(
        content.get("pubDate")
        or content.get("displayTime")
        or raw.get("providerPublishTime")
    )

    provider = content.get("provider")
    publisher = (
        provider.get("displayName") if isinstance(provider, dict) else None
    ) or raw.get("publisher")

    url = _first_url(
        content.get("canonicalUrl"),
        content.get("clickThroughUrl"),
        raw.get("link"),
    )

    title = content.get("title") or raw.get("title")
    if not title:
        return None

    item_id = raw.get("id") or content.get("id")
    if not item_id:
        item_id = hashlib.sha1((url or title).encode("utf-8")).hexdigest()

    related = raw.get("relatedTickers") or content.get("relatedTickers") or []

    return {
        "id": item_id,
        "title": title,
        "summary": content.get("summary") or content.get("description"),
        "publisher": publisher,
        "url": url,
        "thumbnail": _thumbnail_url(content.get("thumbnail")),
        "published": published.isoformat() if published else None,
        "_published_ts": published.timestamp() if published else 0.0,
        "tickers": {symbol, *(t for t in related if isinstance(t, str))},
    }


def _fetch_symbol_news(symbol):
    try:
        raw_items = yf.Ticker(symbol).news or []
    except Exception:
        logger.exception("news fetch failed for %s", symbol)
        return []
    items = []
    for raw in raw_items:
        try:
            item = _normalise(raw, symbol)
        except Exception:
            logger.exception("failed to normalise a news item for %s", symbol)
            item = None
        if item:
            items.append(item)
    return items


def _symbol_news(symbol):
    cached = _cache.get(symbol)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    items = _fetch_symbol_news(symbol)
    _cache[symbol] = (time.time(), items)
    return items


@news_bp.route("/news")
def index():
    user_id = current_user_id()
    return render_template(
        "news.html",
        active_tab="news",
        symbols=load_symbols(user_id),
        hidden=load_news_hidden(user_id),
        default_days=DEFAULT_DAYS,
    )


@news_bp.route("/api/news/symbols/<symbol>", methods=["POST"])
def api_set_symbol_selected(symbol):
    """Remember whether a symbol is included in the News feed, so the choice
    survives a refresh or reopening the tab."""
    user_id = current_user_id()
    symbol = symbol.strip().upper()
    if symbol not in load_symbols(user_id):
        return jsonify({"error": f"{symbol} is not in your list"}), 404

    payload = request.get_json(silent=True) or {}
    selected = bool(payload.get("selected", True))
    set_news_symbol_hidden(user_id, symbol, hidden=not selected)
    return jsonify({"symbol": symbol, "selected": selected})


@news_bp.route("/api/news")
def api_news():
    user_id = current_user_id()
    watch_list = load_symbols(user_id)

    requested = request.args.get("symbols", "")
    selected = [s.strip().upper() for s in requested.split(",") if s.strip()]
    # Only serve news for symbols actually on the user's list; with no explicit
    # selection, fall back to the watch list minus the user's saved opt-outs.
    if selected:
        symbols = [s for s in selected if s in watch_list]
    else:
        hidden = set(load_news_hidden(user_id))
        symbols = [s for s in watch_list if s not in hidden]

    try:
        days = int(request.args.get("days", DEFAULT_DAYS))
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    days = max(1, min(days, MAX_DAYS))

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()

    merged = {}
    for symbol in symbols:
        for item in _symbol_news(symbol):
            if item["_published_ts"] < cutoff:
                continue
            existing = merged.get(item["id"])
            if existing:
                existing["tickers"] |= item["tickers"]
            else:
                merged[item["id"]] = dict(item, tickers=set(item["tickers"]))

    items = sorted(merged.values(), key=lambda i: i["_published_ts"], reverse=True)
    for item in items:
        item["tickers"] = sorted(t for t in item["tickers"] if t in symbols)
        del item["_published_ts"]

    return jsonify({"days": days, "symbols": symbols, "items": items})
