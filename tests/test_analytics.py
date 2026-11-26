"""
Unit Tests: Analytics Engine (NLG & Experiment Report)
Covers: NLG calculation correctness, edge cases, statistical report structure.
"""
import pytest
from unittest.mock import patch, MagicMock
from backend.analytics.metrics import AnalyticsEngine


@pytest.fixture
def engine():
    return AnalyticsEngine()




def _a(user_id, score, probe=None, topic="os"):
    """One stored attempt, shaped as the submit handler writes it."""
    return {"user_id": user_id, "score": score, "topic_id": topic,
            "quiz_meta": {"probe": probe}}

class TestNLGCalculation:
    def test_perfect_improvement(self, engine):
        # pre=0, post=100 -> NLG = 1.0
        assert engine.calculate_nlg(0, 100) == 1.0

    def test_no_improvement(self, engine):
        # pre=50, post=50 -> NLG = 0.0
        assert engine.calculate_nlg(50, 50) == 0.0

    def test_regression(self, engine):
        # Score went down -> negative NLG
        assert engine.calculate_nlg(80, 60) < 0

    def test_partial_improvement(self, engine):
        # pre=0, post=50 -> NLG = 0.5
        assert abs(engine.calculate_nlg(0, 50) - 0.5) < 0.001

    def test_edge_case_pre_100(self, engine):
        # User already at 100% - no room for gain
        assert engine.calculate_nlg(100, 100) == 1.0
        assert engine.calculate_nlg(100, 80) == 0

    def test_high_baseline(self, engine):
        # pre=90, post=95 -> NLG = (95-90)/(100-90) = 0.5
        assert abs(engine.calculate_nlg(90, 95) - 0.5) < 0.001

    def test_nlg_bounded_above_one(self, engine):
        # NLG should not exceed 1.0 for standard inputs
        result = engine.calculate_nlg(0, 100)
        assert result <= 1.0

    def test_nlg_negative_for_drops(self, engine):
        result = engine.calculate_nlg(60, 20)
        assert result < 0


class TestExperimentReport:
    def test_empty_report_structure(self, engine):
        with patch('backend.analytics.metrics.user_repo') as mock_user_repo, \
             patch('backend.analytics.metrics.quiz_repo') as mock_quiz_repo:
            mock_user_repo.get_all.return_value = []
            report = engine.generate_experiment_report()
        assert "control" in report
        assert "experimental" in report

    def test_report_with_users(self, engine):
        mock_users = [
            {"id": "u1", "study_group": "control"},
            {"id": "u2", "study_group": "experimental"},
        ]
        # One read of every attempt, grouped by user_id, which is what the
        # engine now does instead of a per-user call.
        all_attempts = [
            _a("u1", 40, "pre"), _a("u1", 80, "post"),
            _a("u2", 20, "pre"), _a("u2", 90, "post"),
        ]

        with patch('backend.analytics.metrics.user_repo') as mu, \
             patch('backend.analytics.metrics.quiz_repo') as mq:
            mu.get_all.return_value = mock_users
            mq.all_attempts.return_value = all_attempts
            report = engine.generate_experiment_report()

        assert report["control"]["user_count"] == 1
        assert report["experimental"]["user_count"] == 1
        assert report["control"]["avg_nlg"] > 0
        assert report["experimental"]["avg_nlg"] > 0

    def test_statistical_significance_field_present(self, engine):
        mock_users = [
            {"id": f"u{i}", "study_group": "control" if i < 5 else "experimental"}
            for i in range(10)
        ]
        all_attempts = []
        for i in range(10):
            scores = (30, 50) if i < 5 else (20, 95)
            all_attempts += [_a(f"u{i}", scores[0], "pre"),
                             _a(f"u{i}", scores[1], "post")]

        with patch('backend.analytics.metrics.user_repo') as mu, \
             patch('backend.analytics.metrics.quiz_repo') as mq:
            mu.get_all.return_value = mock_users
            mq.all_attempts.return_value = all_attempts
            report = engine.generate_experiment_report()

        assert "statistical_significance" in report

    def test_users_with_single_attempt_excluded(self, engine):
        """Users with only 1 attempt cannot compute NLG (need pre+post)."""
        mock_users = [{"id": "u1", "study_group": "control"}]
        with patch('backend.analytics.metrics.user_repo') as mu, \
             patch('backend.analytics.metrics.quiz_repo') as mq:
            mu.get_all.return_value = mock_users
            mq.all_attempts.return_value = [{"user_id": "u1", "score": 70}]
            report = engine.generate_experiment_report()
        assert report["control"]["user_count"] == 0



class TestOutcomeUsesProbesOnly:
    """The pilot's outcome comes from the two probe quizzes, never practice.

    Practice quizzes differ between arms by design (control medium,
    experimental bandit-chosen), so a last-practice score partly reflects
    which tier was served. Pre and post probes are generated identically for
    everyone, which is what makes the arms comparable.
    """

    def _report(self, engine, users, attempts):
        with patch('backend.analytics.metrics.user_repo') as mu, \
             patch('backend.analytics.metrics.quiz_repo') as mq:
            mu.get_all.return_value = users
            mq.all_attempts.return_value = attempts
            return engine.generate_experiment_report()

    def test_practice_scores_do_not_move_the_outcome(self, engine):
        users = [{"id": "u1", "study_group": "experimental"}]
        # An easy practice quiz served last would have read as a huge gain.
        attempts = [_a("u1", 50, "pre"), _a("u1", 60, None), _a("u1", 60, "post"),
                    _a("u1", 100, None)]
        report = self._report(engine, users, attempts)
        assert report["experimental"]["avg_nlg"] == round((60 - 50) / 50, 3)

    def test_pre_and_post_must_be_on_the_same_topic(self, engine):
        users = [{"id": "u1", "study_group": "control"}]
        attempts = [_a("u1", 30, "pre", topic="os"), _a("u1", 90, "post", topic="qa")]
        report = self._report(engine, users, attempts)
        assert report["control"]["user_count"] == 0

    def test_a_post_before_the_pre_does_not_count(self, engine):
        users = [{"id": "u1", "study_group": "control"}]
        attempts = [_a("u1", 90, "post"), _a("u1", 30, "pre")]
        report = self._report(engine, users, attempts)
        assert report["control"]["user_count"] == 0

    def test_participants_without_a_check_quiz_are_counted_not_hidden(self, engine):
        users = [{"id": "u1", "study_group": "control"},
                 {"id": "u2", "study_group": "experimental"},
                 {"id": "u3", "study_group": "experimental"}]
        attempts = [_a("u1", 40, "pre"), _a("u1", 50, None),
                    _a("u2", 40, "pre"), _a("u2", 70, "post")]
        report = self._report(engine, users, attempts)
        assert report["control"]["without_check_quiz"] == 1
        assert report["experimental"]["user_count"] == 1
        # u3 never took a quiz at all: not a drop-out, so not counted.
        assert report["experimental"]["without_check_quiz"] == 0

    def test_the_latest_check_is_the_post_test(self, engine):
        users = [{"id": "u1", "study_group": "control"}]
        attempts = [_a("u1", 40, "pre"), _a("u1", 50, "post"), _a("u1", 70, "post")]
        report = self._report(engine, users, attempts)
        assert report["control"]["avg_nlg"] == round((70 - 40) / 60, 3)
