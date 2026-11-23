import os

# ---------------------------------------------------------------------------
# Force the file backend before anything imports the application.
#
# This is not tidiness. `app.py` calls load_dotenv on import, and importing it
# constructs the repository singletons, whose `ensure_exists()` writes through
# `open_store()`. So with DATABASE_URL readable - from the environment OR from
# .env - merely importing the app points the entire suite at the production
# database, and every test that redirects a repository to a tmp_path writes a
# document there keyed by that temporary path.
#
# That already happened. 39 documents keyed by paths like
# `/private/var/folders/.../pytest-of-kaavya/pytest-7/...` were found in the
# production database, written on 21 Nov 2026 between 12:33 and 13:02 UTC.
# Nothing reported it: the guard below watches the `data/` DIRECTORY on disk
# and is structurally blind to writes that go to Postgres instead.
#
# Setting the variable to empty rather than deleting it matters, because
# load_dotenv does not overwrite a key already present in os.environ. Deleting
# it would simply let .env put it back.
#
# `tests/test_storage_postgres.py` is the one module that wants a database. It
# restores the URL from _PG_TEST_URL at its own import, so opting in stays
# explicit and stays confined to that file.
# ---------------------------------------------------------------------------
def _capture_database_url():
    """Find a Postgres URL for the opt-in integration tests.

    DATABASE_URL_TEST is preferred and is where the credential lives in .env.
    The name matters: `open_store()` switches on DATABASE_URL, so storing it
    under that name in .env would mean a plain `python3 app.py` silently read
    and wrote the live database instead of local JSON files. DATABASE_URL is
    still honoured from the shell, for the case where somebody really does
    want to point a run at a database.
    """
    for name in ("DATABASE_URL_TEST", "DATABASE_URL"):
        url = os.environ.get(name, "").strip()
        if url:
            return url

    env_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    found = {}
    try:
        with open(env_file) as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key in ("DATABASE_URL_TEST", "DATABASE_URL"):
                    found[key] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return found.get("DATABASE_URL_TEST") or found.get("DATABASE_URL") or ""


os.environ["_PG_TEST_URL"] = _capture_database_url()
os.environ["DATABASE_URL"] = ""

import pytest
import json
import tempfile
from unittest.mock import patch

from flask.testing import FlaskClient

from app import app
from backend.bkt.bkt_engine import bkt_engine
from backend.adaptation.bandit_policy import bandit_adapter
from backend.adaptation.micro_pattern import mp_manager
from backend.repositories.core_repositories import user_repo, progress_repo, quiz_repo, video_repo
from backend.quiz.quiz_session import active_quiz_store

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTION_DATA_DIR = os.path.join(PROJECT_ROOT, 'data')


@pytest.fixture(scope='session', autouse=True)
def guard_production_data():
    """Fail the run if the suite writes to the real data directory.

    Engines resolve their storage path at call time, so a singleton whose path
    the fixtures forget to patch will silently persist into data/ and corrupt
    real learner state. That happened; this makes it loud instead.
    """
    def snapshot():
        if not os.path.isdir(PRODUCTION_DATA_DIR):
            return {}
        return {
            name: os.path.getmtime(os.path.join(PRODUCTION_DATA_DIR, name))
            for name in os.listdir(PRODUCTION_DATA_DIR)
            if name.endswith('.json')
        }

    def stray_keys():
        """Documents in the database keyed by anything but `data/...`.

        The application only ever writes `data/...`, so an absolute path is a
        test that reached a real database. Returns None if there is no
        database to ask, which is the normal case.
        """
        # _PG_TEST_URL, not DATABASE_URL: the latter is deliberately blank for
        # almost the whole session, so reading it here would make this check
        # silently do nothing in exactly the runs that need it.
        url = os.environ.get("_PG_TEST_URL", "").strip()
        if not url:
            return None
        previous = os.environ.get("DATABASE_URL", "")
        os.environ["DATABASE_URL"] = url
        try:
            from backend.storage_pg import pool, TABLE
            with pool().connection() as conn:
                with conn.cursor() as cur:
                    # Anything the application did not write. The app only
                    # ever addresses `data/...`, so this catches an absolute
                    # temp path AND a `tests/_pg_*` key that a crashed
                    # integration test failed to clean up. The earlier version
                    # matched only paths starting with `/`, which would have
                    # let the second case through.
                    cur.execute(
                        f"SELECT key FROM {TABLE} WHERE key NOT LIKE %s",
                        ("data/%",))
                    return {row[0] for row in cur.fetchall()}
        except Exception as exc:  # unreachable database is not a test failure
            print(f"[guard] could not check Postgres for stray keys: {exc}")
            return None
        finally:
            os.environ["DATABASE_URL"] = previous

    before = snapshot()
    strays_before = stray_keys()
    yield
    after = snapshot()
    touched = sorted(
        name for name, mtime in after.items()
        if name not in before or before[name] != mtime
    )
    assert not touched, (
        "tests wrote to production data files: " + ", ".join(touched) +
        " -- patch the owning singleton's path in the fixtures"
    )

    # The check above reads the filesystem, so it is structurally blind to a
    # suite that was pointed at Postgres instead. Check the other half.
    #
    # Only keys this run ADDED are a failure. Keys that were already there are
    # somebody else's mess - reported, because they should be cleaned up, but
    # not a reason to fail a run that did nothing wrong. Conflating the two
    # makes the guard fire forever until the database is tidied, and a check
    # that always fails is a check people learn to ignore.
    strays_after = stray_keys()
    if strays_before is None or strays_after is None:
        return
    if strays_before:
        print(f"\n[guard] NOTE: {len(strays_before)} pre-existing document(s) in "
              f"the database are keyed by local paths, left by an earlier run. "
              f"They are not this run's doing. Clean up with:\n"
              f"[guard]   DELETE FROM documents WHERE key LIKE '/%';")
    added = sorted(strays_after - strays_before)
    assert not added, (
        f"this run wrote {len(added)} document(s) to the database keyed by "
        "local paths, e.g. " + added[0] + " -- the suite reached a real "
        "database. DATABASE_URL should be blank for every module except "
        "tests/test_storage_postgres.py; see the note at the top of this file."
    )


@pytest.fixture(scope='session')
def test_data_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create empty json files
        files_to_init = {
            'users.json': [],
            'user_progress.json': {},
            'quiz_attempts.json': [],
            'micro_patterns.json': [],
            'bkt_states.json': {},
            'videos.json': [{'id': 'test_topic', 'title': 'Test Topic', 'video_id': 'xyz123'}]
        }
        
        for filename, initial_content in files_to_init.items():
            with open(os.path.join(temp_dir, filename), 'w') as f:
                json.dump(initial_content, f)
                
        yield temp_dir

@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Abuse limits are process-wide, so without this each test inherits the
    attempts made by every test before it."""
    from app import (login_limiter, register_limiter, quiz_generate_limiter,
                     quiz_submit_limiter, video_track_limiter, analytics_limiter)
    for limiter in (login_limiter, register_limiter, quiz_generate_limiter,
                    quiz_submit_limiter, video_track_limiter, analytics_limiter):
        limiter.clear()
    yield


class CsrfAwareClient(app.test_client_class or FlaskClient):
    """A test client that echoes the CSRF cookie, as a browser does.

    The application protects authenticated state-changing requests with a
    double-submit token: the server sets a readable `csrf_token` cookie and
    `static/js/security_guard.js` returns it in an `X-CSRF-Token` header. A
    bare test client sends the cookie but not the header, so every
    authenticated POST would be rejected.

    Attaching the header here keeps the tests exercising what a browser
    actually does. That the protection works is covered separately, by tests
    that deliberately omit or corrupt the header.
    """

    def open(self, *args, **kwargs):
        method = str(kwargs.get('method', args[1] if len(args) > 1 else 'GET')).upper()
        if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            cookie = self.get_cookie('csrf_token')
            if cookie is not None and not kwargs.get('_skip_csrf'):
                headers = dict(kwargs.get('headers') or {})
                headers.setdefault('X-CSRF-Token', cookie.value)
                kwargs['headers'] = headers
        kwargs.pop('_skip_csrf', None)
        return super().open(*args, **kwargs)


@pytest.fixture
def client(test_data_dir):
    app.config['TESTING'] = True
    app.secret_key = 'test-secret'
    app.test_client_class = CsrfAwareClient
    
    # Patch all the paths in repositories
    with patch.object(user_repo, 'file_path', os.path.join(test_data_dir, 'users.json')), \
         patch.object(video_repo, 'file_path', os.path.join(test_data_dir, 'videos.json')), \
         patch.object(progress_repo, 'file_path', os.path.join(test_data_dir, 'user_progress.json')), \
         patch.object(quiz_repo, 'file_path', os.path.join(test_data_dir, 'quiz_attempts.json')), \
         patch.object(bkt_engine, 'storage_path', os.path.join(test_data_dir, 'bkt_states.json')), \
         patch.object(bandit_adapter, 'storage_path', os.path.join(test_data_dir, 'bandit_q_table.json')), \
         patch.object(mp_manager, 'storage_path', os.path.join(test_data_dir, 'micro_patterns.json')), \
         patch.object(active_quiz_store, 'file_path', os.path.join(test_data_dir, 'active_quizzes.json')):

        with app.test_client() as client:
            yield client


@pytest.fixture
def issued_quiz(client):
    """Issue a quiz server-side and hand back the token the client must present.

    The answer key is no longer reachable from the session cookie, so a test
    cannot stage one by writing to `session`; it has to go through the same
    issuing path the application uses.
    """
    def issue(user_id, quiz):
        return active_quiz_store.issue(user_id, quiz)
    return issue
