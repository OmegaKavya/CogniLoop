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
        mock_attempts_u1 = [{"score": 40}, {"score": 80}]
        mock_attempts_u2 = [{"score": 20}, {"score": 90}]

        def get_attempts(uid):
            return mock_attempts_u1 if uid == "u1" else mock_attempts_u2

        with patch('backend.analytics.metrics.user_repo') as mu, \
             patch('backend.analytics.metrics.quiz_repo') as mq:
            mu.get_all.return_value = mock_users
            mq.get_user_attempts.side_effect = get_attempts
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
        attempts_low = [{"score": 30}, {"score": 50}]
        attempts_high = [{"score": 20}, {"score": 95}]

        def get_attempts(uid):
            uid_num = int(uid[1:])
            return attempts_low if uid_num < 5 else attempts_high

        with patch('backend.analytics.metrics.user_repo') as mu, \
             patch('backend.analytics.metrics.quiz_repo') as mq:
            mu.get_all.return_value = mock_users
            mq.get_user_attempts.side_effect = get_attempts
            report = engine.generate_experiment_report()

        assert "statistical_significance" in report

    def test_users_with_single_attempt_excluded(self, engine):
        """Users with only 1 attempt cannot compute NLG (need pre+post)."""
        mock_users = [{"id": "u1", "study_group": "control"}]
        with patch('backend.analytics.metrics.user_repo') as mu, \
             patch('backend.analytics.metrics.quiz_repo') as mq:
            mu.get_all.return_value = mock_users
            mq.get_user_attempts.return_value = [{"score": 70}]  # Only 1 attempt
            report = engine.generate_experiment_report()
        assert report["control"]["user_count"] == 0
