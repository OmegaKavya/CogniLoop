"""scripts/delete_participant.py keeps the tester guide's deletion promise.

Run against JSON files in a temporary directory; the script's DOCUMENTS map
is pointed there so nothing real is touched.
"""
import importlib.util
import json
import os
from unittest.mock import patch

import pytest

from backend.storage import JsonStore

_SPEC = importlib.util.spec_from_file_location(
    "delete_participant",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "delete_participant.py"))
dp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dp)


@pytest.fixture
def docs(tmp_path, monkeypatch):
    paths = {name: str(tmp_path / f"{name}.json") for name in dp.DOCUMENTS}
    seed = {
        "users": [{"id": "a1", "email": "a@x.com"}, {"id": "b2", "email": "b@x.com"}],
        "quiz_attempts": [{"user_id": "a1"}, {"user_id": "b2"}, {"user_id": "a1"}],
        "micro_patterns": [{"user_id": "a1"}, {"user_id": "b2"}],
        "user_progress": {"a1": {}, "b2": {}},
        "bkt_states": {"a1": {}, "b2": {}},
        "active_quizzes": {"t1": {"user_id": "a1"}, "t2": {"user_id": "b2"}},
    }
    for name, path in paths.items():
        with open(path, "w") as fh:
            json.dump(seed[name], fh)
    monkeypatch.setattr(dp, "DOCUMENTS", paths)
    return paths


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def test_removes_one_participant_everywhere_and_no_one_else(docs):
    removed = dp.delete("a1")
    assert removed == {"quiz_attempts": 2, "micro_patterns": 1, "user_progress": 1,
                       "bkt_states": 1, "active_quizzes": 1, "users": 1}
    assert _load(docs["users"]) == [{"id": "b2", "email": "b@x.com"}]
    assert not any(v for v in dp.count_matches("a1").values())
    assert all(v == 1 for v in dp.count_matches("b2").values())


def test_a_failure_partway_leaves_the_participant_findable(docs):
    # The account row goes last: if anything before it fails, a re-run can
    # still resolve the participant and finish the job.
    # Dict-shaped documents (progress, BKT, active quizzes) are written with
    # `update`; make the first of them fail, after the list documents have
    # already been changed.
    def failing_update(self, mutator):
        raise OSError("disk went away")

    with patch.object(JsonStore, "update", failing_update):
        with pytest.raises(OSError):
            dp.delete("a1")

    assert dp.resolve_user("a@x.com", None) is not None
    dp.delete("a1")
    assert dp.resolve_user("a@x.com", None) is None
    assert not any(v for v in dp.count_matches("a1").values())
