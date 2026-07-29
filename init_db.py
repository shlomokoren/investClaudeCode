"""Create the app tables in Neon and seed them from config.json.

    python init_db.py            # create tables, insert global keys that don't
                                 # exist yet, seed the owner's watch list
    python init_db.py --force    # also overwrite values already in the database
    python init_db.py --show     # print what the database currently holds
    python init_db.py --seed-user someone@example.com

Global settings (default_range, alerts) live in app_config. Watch lists are
per-user in user_config; a user created by a normal login starts with an empty
list, and only the owner account named by config.json's "owner_email" is seeded
with the config.json ticker list. config.json is a seed file only — the running
app reads everything from Postgres.
"""

import argparse
import json
from pathlib import Path

import db

SEED_PATH = Path(__file__).parent / "config.json"


def seed_owner(email: str, symbols: list, force: bool) -> str:
    """Pre-create an account with a watch list, before its first login."""
    user = db.upsert_user(email=email.strip().lower(), provider=None, provider_sub=None)
    db.ensure_user_defaults(user["id"])

    existing = db.read_user_config(user["id"]).get(db.SYMBOLS_KEY) or []
    if existing and not force:
        return f"kept {email}'s existing {len(existing)} symbol(s) (use --force to replace)"

    db.write_user_config(user["id"], db.SYMBOLS_KEY, symbols)
    return f"seeded {email} with {len(symbols)} symbol(s)"


def show() -> None:
    print("global config (app_config):")
    print(json.dumps(db.read_config(), indent=2))
    print()
    print("users (app_user):")
    users = db.list_users()
    if not users:
        print("  (none yet — nobody has signed in)")
    for u in users:
        last = u["last_login_at"].isoformat() if u["last_login_at"] else "never"
        print(f"  #{u['id']} {u['email']} — {u['symbol_count']} symbol(s), last login {last}")
        print(f"      {json.dumps(db.read_user_config(u['id']).get(db.SYMBOLS_KEY, []))}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite values that already exist in the database",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="print the current database contents and exit",
    )
    parser.add_argument(
        "--seed-user",
        metavar="EMAIL",
        help="seed this account's watch list instead of config.json's owner_email",
    )
    parser.add_argument(
        "--seed-file",
        type=Path,
        default=SEED_PATH,
        help=f"JSON file to seed from (default: {SEED_PATH.name})",
    )
    args = parser.parse_args()

    db.ensure_schema()

    if args.show:
        show()
        return

    with open(args.seed_file, encoding="utf-8") as f:
        seed = json.load(f)

    # Prefer the list already in the database over the seed file: it may have
    # been edited through the UI since config.json was written. Read it before
    # write_config_many() below can overwrite it.
    owner_symbols = db.read_config().get(db.SYMBOLS_KEY) or seed.get(db.SYMBOLS_KEY, [])

    written = db.write_config_many(seed, overwrite=args.force)
    skipped = [key for key in seed if key not in written]

    print("tables ready: app_config, app_user, user_config")
    print(f"  global keys written: {', '.join(written) or '(none)'}")
    if skipped:
        print(f"  kept existing: {', '.join(skipped)} (use --force to overwrite)")

    owner = args.seed_user or seed.get("owner_email")
    if owner:
        print("  " + seed_owner(owner, owner_symbols, args.force))
    else:
        print("  no owner_email in the seed file — no watch list seeded")

    print()
    show()


if __name__ == "__main__":
    try:
        main()
    finally:
        db.close_pool()
