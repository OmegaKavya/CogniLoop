import pytest
import os
import json
import tempfile
from unittest.mock import patch

from app import app
from backend.bkt.bkt_engine import bkt_engine
from backend.adaptation.bandit_policy import bandit_adapter
from backend.adaptation.micro_pattern import mp_manager
from backend.repositories.core_repositories import user_repo, progress_repo, quiz_repo, video_repo

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

@pytest.fixture
def client(test_data_dir):
    app.config['TESTING'] = True
    app.secret_key = 'test-secret'
    
    # Patch all the paths in repositories
    with patch.object(user_repo, 'file_path', os.path.join(test_data_dir, 'users.json')), \
         patch.object(video_repo, 'file_path', os.path.join(test_data_dir, 'videos.json')), \
         patch.object(progress_repo, 'file_path', os.path.join(test_data_dir, 'user_progress.json')), \
         patch.object(quiz_repo, 'file_path', os.path.join(test_data_dir, 'quiz_attempts.json')), \
         patch.object(bkt_engine, 'storage_path', os.path.join(test_data_dir, 'bkt_states.json')), \
         patch.object(bandit_adapter, 'storage_path', os.path.join(test_data_dir, 'bandit_q_table.json')), \
         patch.object(mp_manager, 'storage_path', os.path.join(test_data_dir, 'micro_patterns.json')):
        
        with app.test_client() as client:
            yield client
