import pytest
import os
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

    before = snapshot()
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
    from app import login_limiter, register_limiter
    login_limiter.clear()
    register_limiter.clear()
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
