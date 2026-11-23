"""The model call is off the request path.

A submission used to run `generate_insights` inline, which tries three
providers in turn at their own timeouts. Nothing shown to the learner depends
on it, so an unreachable provider was adding its full timeout to a submission
for prose the learner had not scrolled to yet. These assert the two halves of
the split: the request produces deterministic advice without touching the
network, and the model version is written over it afterwards.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest

from backend.quiz.quiz_insights import QuizInsightsEngine
from backend.repositories.core_repositories import QuizAttemptRepository


def _results(correct=False):
    return [{"text": "What is a semaphore?", "is_correct": correct,
             "selected_answer": "a", "correct_answer": "b", "time_taken": 4.0}]


class TestRequestPathDoesNotCallTheModel:
    def test_use_model_false_never_touches_the_client(self):
        engine = QuizInsightsEngine()
        engine.client = MagicMock()
        out = engine.generate_insights("OS", 40, 0.4, _results(), topic_id="os",
                                       use_model=False)
        engine.client.complete_json.assert_not_called()
        assert out["summary"]
        assert out["focus_concepts"]

    def test_deterministic_advice_is_real_content(self):
        """Not a placeholder: the attempt is usable even if the model never
        answers, which is what makes deferring it safe."""
        engine = QuizInsightsEngine()
        engine.client = MagicMock()
        out = engine.generate_insights("OS", 40, 0.4, _results(), topic_id="os",
                                       use_model=False)
        assert len(out["cheat_sheet"]) >= 1
        assert "diagnoses" in out

    def test_use_model_true_still_calls_it(self):
        """The inline path is kept for any caller that wants to wait."""
        engine = QuizInsightsEngine()
        engine.client = MagicMock()
        engine.client.available = True
        engine.client.complete_json.return_value = {
            "focus_concepts": ["Semaphores"], "cheat_sheet": ["Read it"],
            "resources": [], "summary": "model wrote this"}
        out = engine.generate_insights("OS", 40, 0.4, _results(), topic_id="os")
        assert out["summary"] == "model wrote this"


class TestModelInsights:
    def test_returns_none_when_the_client_is_unavailable(self):
        engine = QuizInsightsEngine()
        engine.client = MagicMock()
        engine.client.available = False
        assert engine.model_insights("OS", 40, 0.4, _results()) is None

    def test_returns_none_when_the_call_fails(self):
        """None rather than a fallback: the caller already stored one and must
        not overwrite it with something no better."""
        engine = QuizInsightsEngine()
        engine.client = MagicMock()
        engine.client.available = True
        engine.client.complete_json.side_effect = RuntimeError("provider down")
        assert engine.model_insights("OS", 40, 0.4, _results()) is None

    def test_returns_none_on_a_perfect_score(self):
        engine = QuizInsightsEngine()
        engine.client = MagicMock()
        engine.client.available = True
        assert engine.model_insights("OS", 100, 0.9, _results(correct=True)) is None
        engine.client.complete_json.assert_not_called()

    def test_returns_the_model_version_with_diagnoses(self):
        engine = QuizInsightsEngine()
        engine.client = MagicMock()
        engine.client.available = True
        engine.client.complete_json.return_value = {
            "focus_concepts": ["Semaphores"], "cheat_sheet": ["Read it"],
            "resources": [], "summary": "model wrote this"}
        out = engine.model_insights("OS", 40, 0.4, _results())
        assert out["summary"] == "model wrote this"
        assert "diagnoses" in out


class TestSetInsights:
    @pytest.fixture
    def repo(self, tmp_path):
        r = QuizAttemptRepository(str(tmp_path / "attempts.json"))
        r.add_attempt({"attempt_id": "a1", "user_id": "u1",
                       "ai_insights": {"summary": "deterministic"}})
        r.add_attempt({"attempt_id": "a2", "user_id": "u2",
                       "ai_insights": {"summary": "deterministic"}})
        return r

    def test_replaces_one_attempts_insights(self, repo):
        assert repo.set_insights("u1", "a1", {"summary": "model"}) is True
        assert repo.get_attempt("u1", "a1")["ai_insights"]["summary"] == "model"

    def test_leaves_other_attempts_alone(self, repo):
        repo.set_insights("u1", "a1", {"summary": "model"})
        assert repo.get_attempt("u2", "a2")["ai_insights"]["summary"] == "deterministic"

    def test_is_scoped_to_the_owner(self, repo):
        assert repo.set_insights("u1", "a2", {"summary": "model"}) is False
        assert repo.get_attempt("u2", "a2")["ai_insights"]["summary"] == "deterministic"

    def test_missing_attempt_reports_false(self, repo):
        assert repo.set_insights("u1", "nope", {"summary": "model"}) is False

    def test_does_not_drop_a_concurrent_append(self, repo):
        """Runs under the document lock, so an attempt appended while the
        refinement is in flight survives it."""
        repo.add_attempt({"attempt_id": "a3", "user_id": "u1"})
        repo.set_insights("u1", "a1", {"summary": "model"})
        assert repo.count_user_attempts("u1") == 2


class TestBackgroundRefinement:
    def test_writes_where_the_attempt_was_stored(self, tmp_path):
        """The helper binds its destination before the thread starts. The
        repository resolves its store from file_path on every access, so a
        thread that outlives the request would otherwise write wherever that
        attribute pointed by then."""
        import app as app_module

        path = str(tmp_path / "attempts.json")
        repo = QuizAttemptRepository(path)
        repo.add_attempt({"attempt_id": "a1", "user_id": "u1",
                          "ai_insights": {"summary": "deterministic"}})

        done = threading.Event()
        original = app_module.QuizAttemptRepository

        def spy(file_path):
            done.set()
            return original(file_path)

        with patch.object(app_module.quiz_repo, "file_path", path), \
             patch.object(app_module, "QuizAttemptRepository", spy), \
             patch.object(app_module.insights_engine, "model_insights",
                          return_value={"summary": "model"}):
            app_module.refine_insights_in_background(
                "u1", "a1", "OS", 40, 0.4, _results())
            assert done.wait(timeout=5)

        for _ in range(100):
            if repo.get_attempt("u1", "a1")["ai_insights"]["summary"] == "model":
                break
            threading.Event().wait(0.05)
        assert repo.get_attempt("u1", "a1")["ai_insights"]["summary"] == "model"

    def test_a_failure_leaves_the_stored_advice_intact(self, tmp_path):
        import app as app_module

        path = str(tmp_path / "attempts.json")
        repo = QuizAttemptRepository(path)
        repo.add_attempt({"attempt_id": "a1", "user_id": "u1",
                          "ai_insights": {"summary": "deterministic"}})

        with patch.object(app_module.quiz_repo, "file_path", path), \
             patch.object(app_module.insights_engine, "model_insights",
                          side_effect=RuntimeError("provider down")):
            app_module.refine_insights_in_background(
                "u1", "a1", "OS", 40, 0.4, _results())
            threading.Event().wait(0.5)

        assert repo.get_attempt("u1", "a1")["ai_insights"]["summary"] == "deterministic"

    def test_nothing_is_written_when_the_model_declines(self, tmp_path):
        import app as app_module

        path = str(tmp_path / "attempts.json")
        repo = QuizAttemptRepository(path)
        repo.add_attempt({"attempt_id": "a1", "user_id": "u1",
                          "ai_insights": {"summary": "deterministic"}})

        with patch.object(app_module.quiz_repo, "file_path", path), \
             patch.object(app_module.insights_engine, "model_insights",
                          return_value=None):
            app_module.refine_insights_in_background(
                "u1", "a1", "OS", 40, 0.4, _results())
            threading.Event().wait(0.5)

        assert repo.get_attempt("u1", "a1")["ai_insights"]["summary"] == "deterministic"
