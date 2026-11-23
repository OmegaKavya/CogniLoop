"""
Concurrency-safe JSON persistence.

The problem this solves
-----------------------
Every engine in this project persisted state by reading a JSON file, mutating
the result and writing it back, with no coordination between requests. Three
separate defects followed:

  1. Lost updates. Read-modify-write without holding a lock across both halves
     means two concurrent requests read the same state and the second write
     discards the first. Measured on this codebase: of 200 concurrent writes of
     distinct keys, 4 survived.

  2. File corruption. `open(path, "w")` truncates immediately, so a reader can
     observe a half-written file and a crash mid-write leaves invalid JSON.
     Measured: the BKT state file was left unparseable.

  3. Truncate-before-lock. The repository layer did acquire an advisory lock,
     but only *after* `open(path, "w")` had already truncated the file, so the
     lock protected nothing.

The fix has three parts:

  * A dedicated lock file per data file. The lock must live on an inode that is
    never replaced; locking the data file itself breaks as soon as the file is
    atomically replaced, because other holders are left locking the old inode.

  * The lock is held across the entire read-modify-write, not around each half
    separately. This is what actually prevents lost updates.

  * Writes go to a temporary file in the same directory, are flushed and
    fsynced, then moved into place with os.replace, which is atomic on POSIX.
    A reader therefore sees either the old file or the new one, never a partial
    one, and an interrupted write cannot corrupt existing state.

Advisory locks coordinate separate processes (gunicorn workers). An additional
in-process mutex coordinates threads within one worker, which is cheaper than
going to the filesystem and does not depend on flock's per-descriptor
semantics.
"""

import json
import os
import threading
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

_mutexes = {}
_mutexes_guard = threading.Lock()


def _mutex_for(path):
    key = os.path.abspath(path)
    with _mutexes_guard:
        if key not in _mutexes:
            _mutexes[key] = threading.RLock()
        return _mutexes[key]


def match_text(value):
    """The text a value compares as, matching Postgres `->>` exactly.

    `->>` renders a JSON boolean as lowercase "true"/"false", while Python's
    str(True) is "True". Comparing with str() therefore made `match={"x": True}`
    find rows on the file backend and nothing at all on Postgres - a difference
    a caller could observe, which the two classes exist to prevent. Found by
    the round 6 audit and confirmed against a real database.

    None is not a text value: it means "absent or JSON null" and is handled
    separately by each backend, because `str(None)` as a comparison made the
    file backend match EVERY row whose field was missing.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) or isinstance(value, str):
        # Verified to render identically on both backends, including very
        # large integers, zero and the empty string.
        return str(value)
    # Everything else is refused rather than compared, because the two
    # backends do not agree on its text and the disagreement is silent:
    # query_list simply returns fewer rows on Postgres than on a file.
    #
    #   dict   Python str() uses single quotes, Postgres ->> emits JSON
    #   list   same
    #   float  str(1e20) is "1e+20"; Postgres renders the digits in full.
    #          Simple values like 0.5 do agree, which is worse rather than
    #          better - it means the failure only appears at the extremes.
    #
    # Found by the round 7 audit. `match` is for scalar field equality; a
    # caller needing to match a structure should compare a field inside it,
    # and one needing a float should pass the text it was stored as.
    raise TypeError(
        f"query_list match values must be str, int, bool or None, not "
        f"{type(value).__name__}. The two storage backends do not render "
        f"this type identically, so a match on it would silently return "
        f"different rows depending on which backend is in use."
    )


def _matches(item, match):
    """True when every key in `match` equals the item's value.

    Values compare as the text Postgres `->>` would produce, so the backends
    agree. A None in `match` means the field is absent or null.
    """
    if not match:
        return True
    for key, value in match.items():
        actual = item.get(key)
        if value is None:
            if actual is not None:
                return False
        elif actual is None or match_text(actual) != match_text(value):
            return False
    return True


def _without(item, drop_keys):
    if not drop_keys:
        return item
    return {k: v for k, v in item.items() if k not in drop_keys}


class JsonStore:
    """A JSON document on disk that can be read and updated safely.

    Use `update` whenever the new value depends on the old one. `read` followed
    by `write` is not equivalent: it reopens the lock in between and reintroduces
    the lost-update race this class exists to prevent.
    """

    def __init__(self, path, default=None, indent=2):
        self.path = path
        self.indent = indent
        self._default = default if default is not None else dict
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.lock_path = path + ".lock"

    def _empty(self):
        return self._default() if callable(self._default) else dict(self._default)

    @contextmanager
    def _locked(self, exclusive):
        with _mutex_for(self.path):
            if fcntl is None:
                yield
                return
            # Opened with "a" so the lock file is created if absent and never
            # truncated; its contents are irrelevant, only its inode matters.
            with open(self.lock_path, "a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _read_unlocked(self):
        try:
            with open(self.path, "r") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return self._empty()
        return data

    def _write_unlocked(self, data):
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        tmp_path = os.path.join(directory, f".{os.path.basename(self.path)}.tmp{os.getpid()}")
        with open(tmp_path, "w") as handle:
            json.dump(data, handle, indent=self.indent)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, self.path)

    def read(self):
        with self._locked(exclusive=False):
            return self._read_unlocked()

    def write(self, data):
        with self._locked(exclusive=True):
            self._write_unlocked(data)

    def update(self, mutator):
        """Apply `mutator(data)` and persist, holding the lock throughout.

        Whatever the mutator returns is returned to the caller; the (possibly
        mutated) data structure is what gets written.
        """
        with self._locked(exclusive=True):
            data = self._read_unlocked()
            result = mutator(data)
            self._write_unlocked(data)
            return result

    def update_replacing(self, mutator, default=None):
        """Like `update`, but persists whatever the mutator returns.

        Required for documents whose top level is a list: a mutator cannot
        replace the caller's object by rebinding its own parameter, so the new
        value has to come back as a return value.
        """
        with self._locked(exclusive=True):
            data = self._read_unlocked()
            if default is not None and not isinstance(data, default):
                data = default()
            new_data = mutator(data)
            self._write_unlocked(new_data)
            return new_data

    def query_list(self, match=None, drop_keys=()):
        """Items of a list-shaped document, filtered and projected.

        Exists so that callers who need one user's rows, or rows without their
        heaviest field, do not have to pull the whole document and discard most
        of it. Here that saving is only in memory, because the file has to be
        read either way; against Postgres the same call filters and projects
        inside the database, so the discarded part never crosses the network.
        That is the case this method is for, and the reason the signature is
        shaped around what SQL can do rather than around a Python predicate.

        Document order is preserved: callers treat the last element as the most
        recent attempt.
        """
        data = self.read()
        if not isinstance(data, list):
            return []
        return [_without(item, drop_keys) for item in data
                if isinstance(item, dict) and _matches(item, match)]

    def count_list(self, match=None):
        """How many items match, without materialising them."""
        data = self.read()
        if not isinstance(data, list):
            return 0
        return sum(1 for item in data
                   if isinstance(item, dict) and _matches(item, match))

    def ensure_exists(self):
        with self._locked(exclusive=True):
            if not os.path.exists(self.path):
                self._write_unlocked(self._empty())


def open_store(path, default=None, indent=2):
    """Return the store this deployment should use for `path`.

    Postgres when DATABASE_URL is set, JSON files otherwise. The choice lives
    here rather than at the five call sites so there is one place to read to
    know where data goes, and so local development and the test suite keep
    working with no database and no configuration.

    Both classes implement the same contract, including `update` holding a
    lock across the whole read-modify-write. A caller cannot tell them apart.
    """
    if os.environ.get("DATABASE_URL", "").strip():
        from backend.storage_pg import PgStore

        return PgStore(path, default=default, indent=indent)
    return JsonStore(path, default=default, indent=indent)
