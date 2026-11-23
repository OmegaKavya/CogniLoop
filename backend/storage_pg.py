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
import tempfile
import threading
from contextlib import contextmanager

from backend.storage import match_text

_pool = None
_pool_guard = threading.Lock()
_schema_ready = False

# The connection an enclosing transaction is using, if any. Thread-local
# because each gunicorn worker thread handles one request at a time and must
# not see another request's open transaction.
_current = threading.local()


@contextmanager
def _connection():
    """The enclosing transaction's connection, or a fresh one that commits.

    Every operation goes through here, so joining a transaction is something a
    caller opts into once at the top rather than something each store has to
    be told about.
    """
    existing = getattr(_current, "conn", None)
    if existing is not None:
        # Inside a transaction: use its connection and do NOT commit, so the
        # whole set of writes lands or none of it does.
        yield existing, False
        return
    with pool().connection() as conn:
        yield conn, True


@contextmanager
def transaction():
    """Make several document writes commit together, or not at all.

    A quiz submission writes four documents: it consumes the issued quiz
    token, updates the mastery estimate, updates the bandit posterior and
    appends the attempt. Each was its own transaction, so a crash or a failed
    write in the middle left the set inconsistent - most damagingly, a mastery
    estimate that had moved with no attempt recorded to explain why. For a
    study whose output is the attempt history, that is unusable data rather
    than merely untidy data.

    Nesting is allowed and joins the outer transaction, because the engines
    call each other and none of them should have to know whether it is the
    outermost.
    """
    if getattr(_current, "conn", None) is not None:
        yield          # already inside one
        return
    ensure_schema()
    with pool().connection() as conn:
        _current.conn = conn
        try:
            yield
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            _current.conn = None

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

        # A document under the system temp directory is always a mistake here.
        # Nothing durable belongs in /tmp - that is the ephemeral-disk problem
        # this class exists to solve - so such a path means something that
        # believed it was writing to a scratch file has been handed a real
        # database instead.
        #
        # This is not hypothetical. Twice in one day the test suite reached the
        # production database and created documents keyed by paths like
        # `/private/var/folders/.../pytest-of-kaavya/pytest-28/test_x0/users.json`,
        # 90 of them in total. Both times the silent absolute-path fallback
        # below is what made it possible, and both times it was noticed by
        # accident. Refusing is how a mistake this shape becomes a stack trace
        # on the first write instead of litter discovered later.
        # gettempdir() alone returns only the per-user $TMPDIR on macOS, so
        # /tmp, /private/tmp and /var/tmp all walked straight past this guard.
        # Found by the round 6 audit and confirmed.
        resolved = os.path.realpath(absolute)
        temp_roots = {os.path.realpath(tempfile.gettempdir())}
        # /dev/shm is a world-writable tmpfs on Linux, which is what this
        # deploys to; gettempdir() does not return it unless TMPDIR says so.
        # Added after the round 7 audit.
        #
        # These are NOT gated on the directory existing locally. Gating them
        # meant /dev/shm was refused on the Linux host that has it and allowed
        # on the macOS laptop that does not, so the guard behaved differently
        # in the place it was written from the place it runs - which is the
        # one property a guard like this must not have. Nothing legitimate
        # lives under these prefixes on either platform.
        for candidate in ("/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp",
                          "/dev/shm", "/run/shm"):
            temp_roots.add(os.path.realpath(candidate))
        if any(resolved.startswith(root + os.sep) for root in temp_roots):
            raise ValueError(
                f"refusing to use a temporary path as a database key: {path}. "
                "Something is writing scratch data to the real database - most "
                "likely a test or script running with DATABASE_URL set. Unset "
                "it, or point the caller at a path inside the project."
            )

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if absolute.startswith(root + os.sep):
            return os.path.relpath(absolute, root).replace(os.sep, "/")
        # An absolute path outside the project is allowed, because the data
        # paths in config.py are env-overridable and a deployment may put them
        # somewhere deliberate. It is only the temp case above that is never
        # legitimate.
        return absolute.replace(os.sep, "/")

    def _empty(self):
        return self._default() if callable(self._default) else dict(self._default)

    def read(self):
        # Shares the enclosing transaction's connection when there is one, so
        # a read inside a transaction observes that transaction's own writes.
        # On a separate connection it would not, and an engine reading back
        # what a previous engine just wrote would see the old value.
        with _connection() as (conn, _owned):
            with conn.cursor() as cur:
                cur.execute(f"SELECT data FROM {TABLE} WHERE key = %s", (self.key,))
                row = cur.fetchone()
        return self._empty() if row is None else row[0]

    def write(self, data):
        with _connection() as (conn, owned):
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE} (key, data) VALUES (%s, %s)
                    ON CONFLICT (key)
                    DO UPDATE SET data = EXCLUDED.data, updated_at = now()
                    """,
                    (self.key, json.dumps(data)),
                )
            if owned:
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
        with _connection() as (conn, owned):
            with conn.cursor() as cur:
                data = self._locked_read(cur)
                result = mutator(data)
                cur.execute(
                    f"UPDATE {TABLE} SET data = %s, updated_at = now() WHERE key = %s",
                    (json.dumps(data), self.key),
                )
            if owned:
                conn.commit()
            return result

    def update_replacing(self, mutator, default=None):
        with _connection() as (conn, owned):
            with conn.cursor() as cur:
                data = self._locked_read(cur)
                if default is not None and not isinstance(data, default):
                    data = default()
                new_data = mutator(data)
                cur.execute(
                    f"UPDATE {TABLE} SET data = %s, updated_at = now() WHERE key = %s",
                    (json.dumps(new_data), self.key),
                )
            if owned:
                conn.commit()
            return new_data

    # The same table holds the users list, the progress map and the BKT state,
    # and `jsonb_array_elements` raises on anything that is not an array. The
    # guard is inside the function's argument rather than in the WHERE clause
    # on purpose: a set-returning function in the FROM list is not ordered
    # against WHERE predicates, so `WHERE jsonb_typeof(d.data) = 'array'` would
    # not reliably stop the function being evaluated on a map-shaped row. As an
    # argument it always runs first, and a map-shaped document yields no rows,
    # which is what JsonStore returns for the same call.
    _ITEMS = (f"{TABLE} d, jsonb_array_elements("
              "CASE WHEN jsonb_typeof(d.data) = 'array' THEN d.data "
              "ELSE '[]'::jsonb END) WITH ORDINALITY AS x(item, ord)")

    def _list_where(self, match):
        """SQL fragment and parameters selecting this document's array items."""
        clauses = ["d.key = %s"]
        params = [self.key]
        for key, value in (match or {}).items():
            if value is None:
                # "absent or JSON null", which is what the file backend means
                # by a None in `match`. `->> = 'None'` compared against SQL
                # NULL and matched nothing, while the file backend matched
                # every row missing the field.
                clauses.append("x.item ->> %s IS NULL")
                params.append(key)
            else:
                clauses.append("x.item ->> %s = %s")
                params.extend([key, match_text(value)])
        return " AND ".join(clauses), params

    def query_list(self, match=None, drop_keys=()):
        """Filter and project inside the database.

        This is the method the whole class exists to make worthwhile. Reading
        the attempts document to show one learner their dashboard previously
        transferred every attempt by every learner, each carrying the full text
        of every question they were asked. Here the WHERE clause and the key
        removal both run server side, so what crosses the network is the rows
        that were asked for, without the field that is not being displayed.

        WITH ORDINALITY plus ORDER BY preserves document order. jsonb_agg makes
        no ordering promise on its own, and callers read the last element as
        the most recent attempt, so losing the order would quietly change which
        attempt the quiz generator treats as current.
        """
        where, params = self._list_where(match)
        projection = "x.item"
        projection_params = []
        if drop_keys:
            # jsonb - text[] removes every named key in one operation.
            projection = "(x.item - %s::text[])"
            projection_params = [list(drop_keys)]
        sql = f"""
            SELECT coalesce(jsonb_agg({projection} ORDER BY x.ord), '[]'::jsonb)
            FROM {self._ITEMS}
            WHERE {where}
        """
        with _connection() as (conn, _owned):
            with conn.cursor() as cur:
                cur.execute(sql, projection_params + params)
                row = cur.fetchone()
        return [] if row is None else row[0]

    def count_list(self, match=None):
        where, params = self._list_where(match)
        sql = f"""
            SELECT count(*)
            FROM {self._ITEMS}
            WHERE {where}
        """
        with _connection() as (conn, _owned):
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
        return 0 if row is None else row[0]

    def ensure_exists(self):
        with _connection() as (conn, owned):
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {TABLE} (key, data) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                    (self.key, json.dumps(self._empty())),
                )
            if owned:
                conn.commit()
