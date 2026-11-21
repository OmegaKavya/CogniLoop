"""Postgres-backed document store with JsonStore's interface.

Why this exists
---------------
Render's free tier has an ephemeral filesystem and `render.yaml` declares no
disk, so every deploy, restart and idle spin-down destroyed every account,
mastery estimate and attempt history. Proven, not assumed: an account
registered at 15:01 could not log in at 16:05 the same day.

Why it mirrors JsonStore rather than replacing it
-------------------------------------------------
`JsonStore` already had the right shape: read, write, and an `update` that
holds a lock across the whole read-modify-write so concurrent writers cannot
lose each other's changes. That contract is what the five call sites depend on,
so this class implements the same one and the call sites change by one word.

What actually improves
----------------------
`JsonStore` serialised writers with a POSIX advisory lock, which coordinates
processes on one machine. `SELECT ... FOR UPDATE` inside a transaction
coordinates them across machines, so this is also the first version that would
survive being run on more than one instance.

Local development and the test suite keep using JsonStore: with DATABASE_URL
unset, nothing here is imported or required.
"""
import json
import os
import threading

_pool = None
_pool_guard = threading.Lock()
_schema_ready = False

TABLE = "documents"


def _dsn():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    # Heroku-style URLs still use the scheme SQLAlchemy dropped; psycopg wants
    # postgresql://. Neon and Supabase both hand out postgresql:// already, so
    # this only matters if the URL is copied from somewhere older.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def pool():
    """One lazily-created pool per process.

    Lazy because importing this module must not require a database: the test
    suite and local development never set DATABASE_URL, and an import-time
    connection would turn a missing variable into a crash loop on a host that
    redeploys per commit.
    """
    global _pool
    if _pool is None:
        with _pool_guard:
            if _pool is None:
                from psycopg_pool import ConnectionPool

                # prepare_threshold=None disables psycopg's automatic prepared
                # statements. They break against a transaction-mode pooler such
                # as Neon's -pooler endpoint or PgBouncer, because the prepared
                # statement is registered on one backend connection and the next
                # execution can land on another. The failure is intermittent and
                # reads as "prepared statement does not exist", which is a long
                # way from the cause. Nothing here runs the same query often
                # enough for the lost optimisation to matter.
                #
                # Small pool: a free Postgres allows few connections and this
                # runs on one small instance. Opening lazily keeps a cold start
                # cheap, and min_size=0 lets Neon scale to zero undisturbed.
                _pool = ConnectionPool(
                    _dsn(),
                    min_size=0,
                    max_size=4,
                    open=True,
                    timeout=10.0,
                    kwargs={"prepare_threshold": None},
                )
    return _pool


def ensure_schema():
    """Create the table once per process.

    JSONB rather than text: it is validated on write, so a malformed document
    is rejected at the boundary instead of surfacing as a JSONDecodeError on
    the next read.
    """
    global _schema_ready
    if _schema_ready:
        return
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    key        TEXT PRIMARY KEY,
                    data       JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        conn.commit()
    _schema_ready = True


class PgStore:
    """A JSON document in Postgres, addressed by the path it used to live at.

    The key is the old file path, normalised relative to the repository root.
    Keeping the path as the identifier means the call sites, the migration
    script and the on-disk backups all refer to a document the same way.
    """

    def __init__(self, path, default=None, indent=2):
        # `path` is kept as an attribute because base_repository compares it to
        # decide whether its cached store is still the right one.
        self.path = path
        self.indent = indent
        self._default = default if default is not None else dict
        self.key = self._key_for(path)
        ensure_schema()

    @staticmethod
    def _key_for(path):
        absolute = os.path.abspath(path)
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if absolute.startswith(root + os.sep):
            return os.path.relpath(absolute, root).replace(os.sep, "/")
        return absolute.replace(os.sep, "/")

    def _empty(self):
        return self._default() if callable(self._default) else dict(self._default)

    def read(self):
        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT data FROM {TABLE} WHERE key = %s", (self.key,))
                row = cur.fetchone()
        return self._empty() if row is None else row[0]

    def write(self, data):
        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE} (key, data) VALUES (%s, %s)
                    ON CONFLICT (key)
                    DO UPDATE SET data = EXCLUDED.data, updated_at = now()
                    """,
                    (self.key, json.dumps(data)),
                )
            conn.commit()

    def _locked_read(self, cur):
        """Read the row with a write lock held, creating it if absent.

        The INSERT runs first so that two writers racing on a document that
        does not exist yet both end up contending for the same row, rather than
        both inserting and one losing. SELECT FOR UPDATE then serialises them
        for the rest of the transaction, which is the cross-machine equivalent
        of the advisory lock JsonStore holds.
        """
        cur.execute(
            f"INSERT INTO {TABLE} (key, data) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (self.key, json.dumps(self._empty())),
        )
        cur.execute(f"SELECT data FROM {TABLE} WHERE key = %s FOR UPDATE", (self.key,))
        return cur.fetchone()[0]

    def update(self, mutator):
        with pool().connection() as conn:
            with conn.cursor() as cur:
                data = self._locked_read(cur)
                result = mutator(data)
                cur.execute(
                    f"UPDATE {TABLE} SET data = %s, updated_at = now() WHERE key = %s",
                    (json.dumps(data), self.key),
                )
            conn.commit()
            return result

    def update_replacing(self, mutator, default=None):
        with pool().connection() as conn:
            with conn.cursor() as cur:
                data = self._locked_read(cur)
                if default is not None and not isinstance(data, default):
                    data = default()
                new_data = mutator(data)
                cur.execute(
                    f"UPDATE {TABLE} SET data = %s, updated_at = now() WHERE key = %s",
                    (json.dumps(new_data), self.key),
                )
            conn.commit()
            return new_data

    def ensure_exists(self):
        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {TABLE} (key, data) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                    (self.key, json.dumps(self._empty())),
                )
            conn.commit()
