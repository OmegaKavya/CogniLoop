"""Copy the JSON documents in data/ into Postgres.

Run once, from the repository root, with DATABASE_URL pointing at the target:

    DATABASE_URL=postgresql://... PYTHONPATH=. python3 scripts/migrate_json_to_postgres.py

It is safe to run more than once. By default it refuses to overwrite a document
that already exists in the database, so a second run after real users have
signed up cannot replace their data with whatever is on this laptop. Pass
--overwrite to replace deliberately.

The files are left untouched, so the JSON remains a backup of the state at
migration time.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.storage_pg import PgStore, TABLE, ensure_schema, pool  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Only the documents the application actually persists. The figure scratch
# files (_fig_*.json) are simulation by-products and the .lock files are not
# documents at all.
SKIP_PREFIXES = ("_fig_",)


def documents():
    for name in sorted(os.listdir(DATA_DIR)):
        if not name.endswith(".json"):
            continue
        if name.startswith(SKIP_PREFIXES):
            continue
        yield os.path.join(DATA_DIR, name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true",
                        help="replace documents that already exist in the database")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be copied and change nothing")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL", "").strip():
        sys.exit("DATABASE_URL is not set. Refusing to run.")

    ensure_schema()

    copied = skipped = failed = 0
    for path in documents():
        key = PgStore._key_for(path)
        try:
            with open(path) as handle:
                data = json.load(handle)
        except (OSError, ValueError) as error:
            print(f"  SKIP  {key}: unreadable ({error})")
            failed += 1
            continue

        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM {TABLE} WHERE key = %s", (key,))
                exists = cur.fetchone() is not None

                if exists and not args.overwrite:
                    print(f"  SKIP  {key}: already in the database")
                    skipped += 1
                    continue

                size = os.path.getsize(path)
                verb = "WOULD" if args.dry_run else ("REPLACE" if exists else "COPY")
                print(f"  {verb:<7} {key} ({size:,} bytes)")

                if not args.dry_run:
                    cur.execute(
                        f"""
                        INSERT INTO {TABLE} (key, data) VALUES (%s, %s)
                        ON CONFLICT (key)
                        DO UPDATE SET data = EXCLUDED.data, updated_at = now()
                        """,
                        (key, json.dumps(data)),
                    )
                    copied += 1
            conn.commit()

    print(f"\ncopied {copied}, skipped {skipped}, failed {failed}")
    if not args.dry_run and copied:
        print("The JSON files are untouched and now serve as a point-in-time backup.")


if __name__ == "__main__":
    main()
