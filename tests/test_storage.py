"""
Tests for concurrency-safe JSON persistence.

These are regression tests for measured data loss. Before JsonStore existed,
200 concurrent repository writes of distinct keys left 4 survivors, 150
concurrent BKT updates left 0, and the BKT state file was left unparseable.
"""
import json
import os
import threading

from backend import config
from backend.adaptation.bandit_policy import ContextualBanditAdapter
from backend.adaptation.micro_pattern import MicroPatternManager
from backend.bkt.bkt_engine import BKTEngine
from backend.repositories.base_repository import BaseJsonRepository
from backend.repositories.core_repositories import (
    QuizAttemptRepository,
    UserProgressRepository,
    UserRepository,
)
from backend.storage import JsonStore


def run_concurrently(fn, n):
    threads = [threading.Thread(target=fn, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


class TestJsonStore:
    def test_update_holds_lock_across_read_and_write(self, tmp_path):
        """Concurrent increments of one counter must all be counted."""
        store = JsonStore(str(tmp_path / "counter.json"))
        store.write({"n": 0})

        def bump(_):
            store.update(lambda d: d.__setitem__("n", d.get("n", 0) + 1))

        run_concurrently(bump, 200)
        assert store.read()["n"] == 200

    def test_concurrent_distinct_keys_all_survive(self, tmp_path):
        store = JsonStore(str(tmp_path / "keys.json"))
        store.write({})
        run_concurrently(lambda i: store.update(lambda d: d.__setitem__(f"k{i}", i)), 200)
        assert len(store.read()) == 200

    def test_write_is_atomic_and_leaves_valid_json(self, tmp_path):
        path = tmp_path / "atomic.json"
        store = JsonStore(str(path))
        run_concurrently(lambda i: store.write({"writer": i, "payload": list(range(50))}), 60)
        json.loads(path.read_text())  # must parse

    def test_no_temp_files_left_behind(self, tmp_path):
        store = JsonStore(str(tmp_path / "clean.json"))
        run_concurrently(lambda i: store.update(lambda d: d.__setitem__(f"k{i}", i)), 30)
        leftovers = [p for p in os.listdir(tmp_path) if ".tmp" in p]
        assert leftovers == []

    def test_corrupt_file_reads_as_empty_rather_than_raising(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{ this is not json")
        assert JsonStore(str(path)).read() == {}

    def test_missing_file_reads_as_empty(self, tmp_path):
        assert JsonStore(str(tmp_path / "absent.json")).read() == {}

    def test_update_returns_mutator_result(self, tmp_path):
        store = JsonStore(str(tmp_path / "r.json"))
        store.write({"a": 1})
        assert store.update(lambda d: d["a"] + 41) == 42


class TestRepositoryConcurrency:
    def test_concurrent_saves_do_not_lose_records(self, tmp_path):
        repo = BaseJsonRepository(str(tmp_path / "repo.json"))
        run_concurrently(lambda i: repo.save(f"user{i}", {"v": i}), 200)
        assert len(repo.get_all()) == 200

    def test_path_reassignment_redirects_persistence(self, tmp_path):
        """file_path is the source of truth; tests rely on patching it."""
        repo = BaseJsonRepository(str(tmp_path / "first.json"))
        repo.save("a", {"v": 1})

        repo.file_path = str(tmp_path / "second.json")
        assert repo.get_all() == {}
        repo.save("b", {"v": 2})

        assert set(json.loads((tmp_path / "first.json").read_text())) == {"a"}
        assert set(json.loads((tmp_path / "second.json").read_text())) == {"b"}


class TestDomainRepositoryConcurrency:
    """These subclasses previously re-introduced the race by reading with
    get_all() and writing with _write_data() under separate locks."""

    def test_concurrent_registrations_all_persist(self, tmp_path):
        repo = UserRepository(str(tmp_path / "u.json"))
        run_concurrently(lambda i: repo.save(i, {"id": i, "email": f"u{i}@x"}), 150)
        assert len(repo.get_all()) == 150

    def test_repeated_saves_of_one_user_do_not_duplicate(self, tmp_path):
        repo = UserRepository(str(tmp_path / "u2.json"))
        repo.save(1, {"id": 1, "v": 0})
        run_concurrently(lambda i: repo.save(1, {"id": 1, "v": i}), 60)
        assert len(repo.get_all()) == 1

    def test_concurrent_quiz_attempts_are_all_recorded(self, tmp_path):
        repo = QuizAttemptRepository(str(tmp_path / "q.json"))
        run_concurrently(lambda i: repo.add_attempt({"user_id": i, "score": i}), 150)
        assert len(repo.get_all()) == 150

    def test_concurrent_progress_writes_all_persist(self, tmp_path):
        repo = UserProgressRepository(str(tmp_path / "p.json"))
        run_concurrently(lambda i: repo.save_progress(i, "topic", {"done": i}), 150)
        assert len(repo.get_all()) == 150

    def test_repository_paths_come_from_config(self):
        assert UserRepository().file_path == config.USERS_PATH
        assert QuizAttemptRepository().file_path == config.QUIZ_ATTEMPTS_PATH

    def test_repository_paths_are_absolute(self):
        """Relative paths would resolve against the process working directory."""
        assert os.path.isabs(UserRepository().file_path)


class TestMicroPatternConcurrency:
    """Video tracking is the highest-frequency write in the app. Its previous
    unlocked read-modify-write corrupted the file under load, after which every
    later append failed too, permanently breaking tracking and clustering."""

    def _manager(self, tmp_path):
        return MicroPatternManager(storage_path=str(tmp_path / "mp.json"),
                                   model_path=str(tmp_path / "model.pkl"))

    def _event(self, i):
        return {"pause_count": i, "rewatch_count": 0,
                "skip_ratio": 0.1, "watch_percentage": 50}

    def test_concurrent_events_are_all_logged(self, tmp_path):
        mp = self._manager(tmp_path)
        run_concurrently(lambda i: mp.log_interaction(f"u{i}", "v1", self._event(i)), 200)
        assert len(mp._store.read()) == 200

    def test_file_stays_parseable_under_load(self, tmp_path):
        mp = self._manager(tmp_path)
        run_concurrently(lambda i: mp.log_interaction(f"u{i}", "v1", self._event(i)), 120)
        json.loads((tmp_path / "mp.json").read_text())

    def test_logging_still_works_after_concurrent_load(self, tmp_path):
        """Corruption used to be permanent; it must not be."""
        mp = self._manager(tmp_path)
        run_concurrently(lambda i: mp.log_interaction(f"u{i}", "v1", self._event(i)), 120)
        assert mp.log_interaction("later", "v1", self._event(1)) is True
        assert len(mp._store.read()) == 121


class TestEngineConcurrency:
    def test_concurrent_learners_all_persist(self, tmp_path):
        engine = BKTEngine(storage_path=str(tmp_path / "bkt.json"),
                           use_fitted_params=False)
        run_concurrently(
            lambda i: engine.update_mastery(f"u{i}", "skill", True, difficulty="medium"),
            150)
        assert len(engine.get_all_states()) == 150

    def test_concurrent_updates_for_one_learner_are_not_lost(self, tmp_path):
        """Every observation must move the posterior; none may be overwritten."""
        engine = BKTEngine(storage_path=str(tmp_path / "bkt2.json"),
                           use_fitted_params=False)
        single = BKTEngine(storage_path=str(tmp_path / "bkt3.json"),
                           use_fitted_params=False)

        run_concurrently(
            lambda _: engine.update_mastery("same", "skill", True, difficulty="medium"),
            40)
        for _ in range(40):
            single.update_mastery("same", "skill", True, difficulty="medium")

        assert engine.get_mastery("same", "skill") == single.get_mastery("same", "skill")

    def test_storage_path_reassignment_redirects_state(self, tmp_path):
        engine = BKTEngine(storage_path=str(tmp_path / "a.json"),
                           use_fitted_params=False)
        engine.update_mastery("u", "s", True, difficulty="medium")
        engine.storage_path = str(tmp_path / "b.json")
        assert engine.get_all_states() == {}

    def test_bandit_concurrent_updates_are_all_counted(self, tmp_path):
        bandit = ContextualBanditAdapter(storage_path=str(tmp_path / "q.json"),
                                         epsilon=0.0)
        run_concurrently(
            lambda _: bandit.update_policy("C", 0.5, "medium", score=80), 120)
        assert bandit.q_table["C_Medium"]["medium"]["count"] == 120
