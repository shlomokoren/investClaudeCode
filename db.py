"""Postgres (Neon) access layer.

Three tables:

    app_config(key text primary key, value jsonb, updated_at)
        Global settings shared by everyone — "default_range", "alerts", and the
        "default_stocks" list that init_db.py uses to seed the owner account.
        Keys and value types mirror the old config.json top level.

    app_user(id, email unique, provider, provider_sub, name, created_at, last_login_at)
        One row per signed-in Google account. Email is the identity key (that's
        what the login flow matches on); provider_sub is Google's stable subject
        id, kept for reference.

    user_config(user_id -> app_user, key, value jsonb, updated_at)
        Per-user settings, primary key (user_id, key). A new user gets
        default_stocks = [] and inherits nothing else; missing keys fall back to
        app_config (see symbols.py).

The connection string is read from the DATABASE_URL environment variable (a
local .env file is loaded if present). Nothing is hardcoded here.
"""

import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from psycopg.rows import tuple_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

load_dotenv(Path(__file__).parent / ".env")

CONFIG_TABLE = "app_config"
USER_TABLE = "app_user"
USER_CONFIG_TABLE = "user_config"
SYMBOLS_KEY = "default_stocks"
DISABLED_SYMBOLS_KEY = "disabled_stocks"
POSITIONS_KEY = "positions"

_SCHEMA_SQL = [
    f"""
    CREATE TABLE IF NOT EXISTS {CONFIG_TABLE} (
        key        text PRIMARY KEY,
        value      jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {USER_TABLE} (
        id            bigserial PRIMARY KEY,
        email         text NOT NULL UNIQUE,
        provider      text,
        provider_sub  text,
        name          text,
        created_at    timestamptz NOT NULL DEFAULT now(),
        last_login_at timestamptz
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {USER_CONFIG_TABLE} (
        user_id    bigint NOT NULL REFERENCES {USER_TABLE}(id) ON DELETE CASCADE,
        key        text   NOT NULL,
        value      jsonb  NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, key)
    )
    """,
]

_pool = None
_pool_lock = Lock()


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Put the Neon connection string in a .env "
            "file next to app.py (see .env.example) or export it in the "
            "environment."
        )
    return url


def get_pool() -> ConnectionPool:
    """Lazily create the process-wide connection pool.

    Neon closes idle connections aggressively, so the pool keeps no minimum and
    stays small — each gunicorn worker gets its own pool.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    database_url(),
                    min_size=0,
                    max_size=4,
                    timeout=15,
                    max_idle=60,
                    kwargs={"autocommit": True, "row_factory": tuple_row},
                )
    return _pool


def close_pool() -> None:
    """Shut the pool down — for scripts, so worker threads exit cleanly."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def ensure_schema() -> None:
    with get_pool().connection() as conn:
        for statement in _SCHEMA_SQL:
            conn.execute(statement)


# --- global config -------------------------------------------------------


def read_config() -> dict:
    """Return every global config key as a dict, e.g. {"default_range": "6mo"}."""
    with get_pool().connection() as conn:
        rows = conn.execute(f"SELECT key, value FROM {CONFIG_TABLE}").fetchall()
    return {key: value for key, value in rows}


def write_config(key: str, value) -> None:
    """Insert or replace one global config key."""
    with get_pool().connection() as conn:
        conn.execute(
            f"""
            INSERT INTO {CONFIG_TABLE} (key, value, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = now()
            """,
            (key, Json(value)),
        )


def write_config_many(config: dict, overwrite: bool = True) -> list[str]:
    """Write several global keys at once. Returns the keys actually written."""
    written = []
    with get_pool().connection() as conn:
        for key, value in config.items():
            conflict = (
                "DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
                if overwrite
                else "DO NOTHING"
            )
            row = conn.execute(
                f"""
                INSERT INTO {CONFIG_TABLE} (key, value, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (key) {conflict}
                RETURNING key
                """,
                (key, Json(value)),
            ).fetchone()
            if row:
                written.append(row[0])
    return written


# --- users ---------------------------------------------------------------


def upsert_user(email: str, provider: str, provider_sub: str, name: str = None) -> dict:
    """Create or refresh the user row for an email, stamping last_login_at.

    Matching on email (not provider_sub) keeps the login identity the same one
    the user sees, and lets init_db.py pre-seed an account before its first
    login — the real login then updates that row in place.
    """
    with get_pool().connection() as conn:
        row = conn.execute(
            f"""
            INSERT INTO {USER_TABLE} (email, provider, provider_sub, name, last_login_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (email) DO UPDATE
                SET provider      = COALESCE(EXCLUDED.provider, {USER_TABLE}.provider),
                    provider_sub  = COALESCE(EXCLUDED.provider_sub, {USER_TABLE}.provider_sub),
                    name          = COALESCE(EXCLUDED.name, {USER_TABLE}.name),
                    last_login_at = now()
            RETURNING id, email, name
            """,
            (email, provider, provider_sub, name),
        ).fetchone()
    return {"id": row[0], "email": row[1], "name": row[2]}


def find_user_by_email(email: str):
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT id, email, name FROM {USER_TABLE} WHERE email = %s", (email,)
        ).fetchone()
    return {"id": row[0], "email": row[1], "name": row[2]} if row else None


def list_users() -> list[dict]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            SELECT u.id, u.email, u.name, u.created_at, u.last_login_at,
                   COALESCE(jsonb_array_length(c.value), 0)
              FROM {USER_TABLE} u
              LEFT JOIN {USER_CONFIG_TABLE} c
                     ON c.user_id = u.id AND c.key = %s
             ORDER BY u.id
            """,
            (SYMBOLS_KEY,),
        ).fetchall()
    return [
        {
            "id": r[0],
            "email": r[1],
            "name": r[2],
            "created_at": r[3],
            "last_login_at": r[4],
            "symbol_count": r[5],
        }
        for r in rows
    ]


# --- per-user config -----------------------------------------------------


def ensure_user_defaults(user_id: int) -> None:
    """Give a brand-new user an empty watch list. Idempotent."""
    with get_pool().connection() as conn:
        conn.execute(
            f"""
            INSERT INTO {USER_CONFIG_TABLE} (user_id, key, value)
            VALUES (%s, %s, '[]'::jsonb)
            ON CONFLICT (user_id, key) DO NOTHING
            """,
            (user_id, SYMBOLS_KEY),
        )


def read_user_config(user_id: int) -> dict:
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT key, value FROM {USER_CONFIG_TABLE} WHERE user_id = %s",
            (user_id,),
        ).fetchall()
    return {key: value for key, value in rows}


def write_user_config(user_id: int, key: str, value) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            f"""
            INSERT INTO {USER_CONFIG_TABLE} (user_id, key, value, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (user_id, key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = now()
            """,
            (user_id, key, Json(value)),
        )


def add_user_symbol(user_id: int, symbol: str, key: str = SYMBOLS_KEY) -> list:
    """Append a ticker to one of this user's jsonb-array config lists if
    absent. Returns the new list. Same helper backs both the watch list
    (key=SYMBOLS_KEY) and the disabled-symbols list (key=DISABLED_SYMBOLS_KEY).

    One statement, so two concurrent edits can't clobber each other the way a
    read-modify-write from Python would.
    """
    with get_pool().connection() as conn:
        row = conn.execute(
            f"""
            INSERT INTO {USER_CONFIG_TABLE} (user_id, key, value, updated_at)
            VALUES (%(user_id)s, %(key)s, jsonb_build_array(%(symbol)s::text), now())
            ON CONFLICT (user_id, key) DO UPDATE
                SET value = CASE
                        WHEN {USER_CONFIG_TABLE}.value @> to_jsonb(%(symbol)s::text)
                            THEN {USER_CONFIG_TABLE}.value
                        ELSE {USER_CONFIG_TABLE}.value || jsonb_build_array(%(symbol)s::text)
                    END,
                    updated_at = now()
            RETURNING value
            """,
            {"user_id": user_id, "key": key, "symbol": symbol},
        ).fetchone()
    return row[0]


def remove_user_symbol(user_id: int, symbol: str, key: str = SYMBOLS_KEY) -> list:
    """Drop a ticker from one of this user's jsonb-array config lists,
    preserving order. See add_user_symbol for the shared key param."""
    with get_pool().connection() as conn:
        row = conn.execute(
            f"""
            UPDATE {USER_CONFIG_TABLE}
               SET value = COALESCE((
                       SELECT jsonb_agg(elem ORDER BY ord)
                         FROM jsonb_array_elements(value) WITH ORDINALITY AS t(elem, ord)
                        WHERE elem <> to_jsonb(%(symbol)s::text)
                   ), '[]'::jsonb),
                   updated_at = now()
             WHERE user_id = %(user_id)s AND key = %(key)s
            RETURNING value
            """,
            {"user_id": user_id, "key": key, "symbol": symbol},
        ).fetchone()
    return row[0] if row else []


def set_user_position(user_id: int, symbol: str, position: float) -> dict:
    """Set one symbol's held quantity in this user's positions object
    (key=POSITIONS_KEY), merging into whatever's already there. One
    statement, same race-free reasoning as add_user_symbol."""
    with get_pool().connection() as conn:
        row = conn.execute(
            f"""
            INSERT INTO {USER_CONFIG_TABLE} (user_id, key, value, updated_at)
            VALUES (%(user_id)s, %(key)s, jsonb_build_object(%(symbol)s::text, %(position)s::double precision), now())
            ON CONFLICT (user_id, key) DO UPDATE
                SET value = {USER_CONFIG_TABLE}.value || jsonb_build_object(%(symbol)s::text, %(position)s::double precision),
                    updated_at = now()
            RETURNING value
            """,
            {"user_id": user_id, "key": POSITIONS_KEY, "symbol": symbol, "position": position},
        ).fetchone()
    return row[0]


def remove_user_position(user_id: int, symbol: str) -> dict:
    """Drop a symbol's saved position, e.g. when it leaves the watch list."""
    with get_pool().connection() as conn:
        row = conn.execute(
            f"""
            UPDATE {USER_CONFIG_TABLE}
               SET value = COALESCE(value - %(symbol)s::text, '{{}}'::jsonb),
                   updated_at = now()
             WHERE user_id = %(user_id)s AND key = %(key)s
            RETURNING value
            """,
            {"user_id": user_id, "key": POSITIONS_KEY, "symbol": symbol},
        ).fetchone()
    return row[0] if row else {}
