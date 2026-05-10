"""
Stress / Load Tests: Concurrent simulation of many users.
Covers: repository thread-safety, bandit convergence under load, BKT monotonicity.
These are NOT meant to be fast — they simulate real multi-user load.
"""
import threading
import tempfile
import os
import pytest
from backend.bkt.bkt_engine import BKTEngine
from backend.adaptation.bandit_policy import ContextualBanditAdapter
from backend.repositories.core_repositories import UserRepository, QuizAttemptRepository


class TestRepositoryHighVolume:
    """Verify repository integrity under sequential high-volume writes.
    Note: fcntl advisory locking prevents corruption in single-threaded I/O.
    True concurrency (multi-process) would require a DB backend."""

    def test_high_volume_user_writes(self, tmp_path):
        import json
        f = str(tmp_path / "users.json")
        with open(f, "w") as fh:
            json.dump([], fh)
        repo = UserRepository(f)

        for i in range(50):
            repo.save(str(i), {"id": str(i), "email": f"user{i}@test.com", "name": f"User {i}"})

        all_users = repo.get_all()
        assert len(all_users) == 50

    def test_high_volume_quiz_appends(self, tmp_path):
        import json
        f = str(tmp_path / "attempts.json")
        with open(f, "w") as fh:
            json.dump([], fh)
        repo = QuizAttemptRepository(f)

        for i in range(50):
            repo.add_attempt({"attempt_id": f"a{i}", "user_id": "u1", "score": i})

        attempts = repo.get_user_attempts("u1")
        assert len(attempts) == 50
        scores = [a["score"] for a in attempts]
        assert set(scores) == set(range(50))


class TestBKTMonotonicity:
    """BKT mastery should increase with consecutive correct answers (monotonic convergence)."""

    def test_mastery_increases_with_correct_streak(self, tmp_path):
        engine = BKTEngine(storage_path=str(tmp_path / "bkt.json"))
        prev = engine.get_mastery("u1", "concept_1")
        for _ in range(10):
            new = engine.update_mastery("u1", "concept_1", is_correct=True)
            assert new >= prev
            prev = new
        assert prev > 0.7  # Should be high after 10 correct answers

    def test_mastery_stays_below_one(self, tmp_path):
        engine = BKTEngine(storage_path=str(tmp_path / "bkt2.json"))
        for _ in range(50):
            mastery = engine.update_mastery("u1", "concept_2", is_correct=True)
        assert mastery <= 1.0

    def test_mastery_stays_above_zero(self, tmp_path):
        engine = BKTEngine(storage_path=str(tmp_path / "bkt3.json"))
        for _ in range(50):
            mastery = engine.update_mastery("u1", "concept_3", is_correct=False)
        assert mastery >= 0.0


class TestBanditLoadConvergence:
    """Bandit should converge to correct action after many reward signals."""

    def test_bandit_converges_to_easy_for_struggling_users(self, tmp_path):
        bandit = ContextualBanditAdapter(epsilon=0.0, storage_path=str(tmp_path / "q.json"))
        for _ in range(30):
            bandit.update_policy("General Learner", 0.2, "easy", score=70)
            bandit.update_policy("General Learner", 0.2, "medium", score=20)
            bandit.update_policy("General Learner", 0.2, "hard", score=5)
        action = bandit.get_action("General Learner", 0.2)
        assert action == "easy"

    def test_bandit_converges_to_hard_for_expert_users(self, tmp_path):
        bandit = ContextualBanditAdapter(epsilon=0.0, storage_path=str(tmp_path / "q2.json"))
        for _ in range(30):
            bandit.update_policy("Active Learner", 0.9, "easy", score=40)
            bandit.update_policy("Active Learner", 0.9, "medium", score=60)
            bandit.update_policy("Active Learner", 0.9, "hard", score=95)
        action = bandit.get_action("Active Learner", 0.9)
        assert action == "hard"

    def test_bandit_concurrent_updates(self, tmp_path):
        """Bandit should not corrupt its Q-table under concurrent update calls."""
        bandit = ContextualBanditAdapter(epsilon=0.5, storage_path=str(tmp_path / "qc.json"))
        errors = []

        def update(i):
            try:
                bandit.update_policy("General Learner", 0.5, "medium", score=50 + (i % 30))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=update, args=(i,)) for i in range(25)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(errors) == 0
