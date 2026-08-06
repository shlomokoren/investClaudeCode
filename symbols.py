"""Config accessors: global settings plus each signed-in user's watch list.

Global values (default_range, alerts) live in app_config and are cached
in-process for a minute — they're identical for everyone, so caching them is
safe. Per-user values are NOT cached: a shared cache would serve one user's
ticker list to another, and the lookup is a single primary-key hit on
user_config anyway. See db.py for the schema.
"""

import time
from threading import Lock

import db

CACHE_TTL_SECONDS = 60
REQUIRED_GLOBAL_KEYS = ("default_range",)

_cache = {"config": None, "loaded_at": 0.0}
_lock = Lock()


def load_global_config(refresh: bool = False) -> dict:
    """Settings shared by all users, cached for CACHE_TTL_SECONDS."""
    with _lock:
        fresh = (
            _cache["config"] is not None
            and time.monotonic() - _cache["loaded_at"] < CACHE_TTL_SECONDS
        )
        if fresh and not refresh:
            return _cache["config"]

        config = db.read_config()
        missing = [key for key in REQUIRED_GLOBAL_KEYS if key not in config]
        if missing:
            raise RuntimeError(
                f"Config keys missing from the {db.CONFIG_TABLE} table: "
                f"{', '.join(missing)}. Seed the database with "
                "`python init_db.py`."
            )

        _cache["config"] = config
        _cache["loaded_at"] = time.monotonic()
        return config


def load_config(user_id: int) -> dict:
    """Effective config for one user: their rows over the global defaults.

    default_stocks is deliberately per-user only — a user who has never added a
    ticker gets an empty list, not the global seed list.
    """
    config = dict(load_global_config())
    config[db.SYMBOLS_KEY] = []
    config.update(db.read_user_config(user_id))
    return config


def load_symbols(user_id: int) -> list:
    return db.read_user_config(user_id).get(db.SYMBOLS_KEY, [])


def save_symbols(user_id: int, symbols: list) -> None:
    """Replace one user's ticker list."""
    db.write_user_config(user_id, db.SYMBOLS_KEY, list(symbols))


def add_symbol(user_id: int, symbol: str) -> list:
    """Add one ticker to a user's list. Returns the updated list."""
    return db.add_user_symbol(user_id, symbol)


def remove_symbol(user_id: int, symbol: str) -> list:
    """Remove one ticker from a user's list. Returns the updated list.

    Also drops any saved disabled-status and position for the symbol, so
    re-adding it later starts fresh rather than resurrecting stale state.
    """
    db.remove_user_symbol(user_id, symbol, key=db.DISABLED_SYMBOLS_KEY)
    db.remove_user_position(user_id, symbol)
    return db.remove_user_symbol(user_id, symbol)


def load_disabled_symbols(user_id: int) -> list:
    """Tickers in the watch list currently toggled off (chart hidden)."""
    return db.read_user_config(user_id).get(db.DISABLED_SYMBOLS_KEY, [])


def set_symbol_enabled(user_id: int, symbol: str, enabled: bool) -> bool:
    """Persist a symbol's chart-visibility toggle. Returns the new state."""
    if enabled:
        db.remove_user_symbol(user_id, symbol, key=db.DISABLED_SYMBOLS_KEY)
    else:
        db.add_user_symbol(user_id, symbol, key=db.DISABLED_SYMBOLS_KEY)
    return enabled


def load_positions(user_id: int) -> dict:
    """Symbol -> held quantity. Symbols with no saved position are absent
    (treat as 0), not included as explicit zeros."""
    return db.read_user_config(user_id).get(db.POSITIONS_KEY, {})


def set_position(user_id: int, symbol: str, position: float) -> float:
    """Persist how many shares of a symbol the user holds. Returns it back."""
    db.set_user_position(user_id, symbol, position)
    return position


def clear_cache() -> None:
    """Drop the cached global config (per-user config is never cached)."""
    with _lock:
        _cache["config"] = None
        _cache["loaded_at"] = 0.0
