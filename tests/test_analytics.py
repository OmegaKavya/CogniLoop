"""
Unit Tests: Analytics Engine (NLG & Experiment Report)
Covers: NLG calculation correctness, edge cases, statistical report structure.
"""
import json

import pytest
from unittest.mock import patch, MagicMock
from backend.analytics.metrics import AnalyticsEngine


@pytest.fixture
def engine():
    return AnalyticsEngine()




def _a(user_id, score, probe=None, topic="os", **extra):
    """One stored attempt, shaped as the submit handler writes it."""
    return {"user_id": user_id, "score": score, "topic_id": topic,
            "quiz_meta": {"probe": probe}, **extra}

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

    def test_no_change_at_a_ceiling_or_floor_is_undefined(self, engine):
        assert engine.calculate_nlg(100, 100) is None
        assert engine.calculate_nlg(0, 0) is None

    def test_a_drop_from_100_is_scaled_by_the_room_to_lose(self, engine):
        assert engine.calculate_nlg(100, 80) == -0.2

    def test_losses_are_bounded(self, engine):
        # Hake's g gives (50 - 90) / 10 = -4.0 here: one bad check quiz would
        # outweigh several participants who improved.
        assert engine.calculate_nlg(90, 50) == pytest.approx(-40 / 90)
        assert engine.calculate_nlg(100, 0) == -1.0

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
        assert report["control"]["avg_gain"] > 0
        assert report["experimental"]["avg_gain"] > 0

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
        assert report["experimental"]["avg_gain"] == round((60 - 50) / 50, 3)

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

    def test_the_first_check_is_the_post_test(self, engine):
        # A retake must not replace the outcome.
        users = [{"id": "u1", "study_group": "control"}]
        attempts = [_a("u1", 40, "pre"), _a("u1", 50, "post"), _a("u1", 70, "post")]
        report = self._report(engine, users, attempts)
        assert report["control"]["avg_gain"] == round((50 - 40) / 60, 3)

    def test_the_arm_recorded_on_the_attempt_wins(self, engine):
        users = [{"id": "u1", "study_group": "experimental"}]
        attempts = [_a("u1", 40, "pre", study_group="control"),
                    _a("u1", 70, "post", study_group="control")]
        report = self._report(engine, users, attempts)
        assert report["control"]["user_count"] == 1
        assert report["experimental"]["user_count"] == 0

    def test_undefined_gains_are_counted_not_averaged(self, engine):
        users = [{"id": "u1", "study_group": "control"},
                 {"id": "u2", "study_group": "control"}]
        attempts = [_a("u1", 100, "pre"), _a("u1", 100, "post"),
                    _a("u2", 40, "pre"), _a("u2", 70, "post")]
        report = self._report(engine, users, attempts)
        assert report["control"]["gain_undefined"] == 1
        assert report["control"]["avg_gain"] == 0.5

    def test_same_day_and_later_checks_are_reported_apart(self, engine):
        users = [{"id": "u1", "study_group": "control"},
                 {"id": "u2", "study_group": "control"}]
        attempts = [
            _a("u1", 40, "pre", timestamp="2026-12-01T10:00:00"),
            _a("u1", 70, "post", timestamp="2026-12-01T10:20:00"),
            _a("u2", 40, "pre", timestamp="2026-12-01T10:00:00"),
            _a("u2", 100, "post", timestamp="2026-12-12T18:00:00"),
        ]
        report = self._report(engine, users, attempts)
        assert report["control"]["same_day"] == {"user_count": 1, "avg_gain": 0.5}
        assert report["control"]["across_sessions"] == {"user_count": 1, "avg_gain": 1.0}


class TestSignificance:
    def _report(self, engine, users, attempts):
        with patch('backend.analytics.metrics.user_repo') as mu, \
             patch('backend.analytics.metrics.quiz_repo') as mq:
            mu.get_all.return_value = users
            mq.all_attempts.return_value = attempts
            return engine.generate_experiment_report()

    def test_one_participant_per_arm_gives_a_reason_and_valid_json(self, engine):
        users = [{"id": "u1", "study_group": "control"},
                 {"id": "u2", "study_group": "experimental"}]
        attempts = [_a("u1", 40, "pre"), _a("u1", 70, "post"),
                    _a("u2", 40, "pre"), _a("u2", 90, "post")]
        report = self._report(engine, users, attempts)
        assert isinstance(report["statistical_significance"], str)
        json.dumps(report, allow_nan=False)

    def test_identical_gains_do_not_produce_nan(self, engine):
        users = [{"id": f"u{i}", "study_group": "control" if i < 2 else "experimental"}
                 for i in range(4)]
        attempts = []
        for i in range(4):
            attempts += [_a(f"u{i}", 50, "pre"), _a(f"u{i}", 75, "post")]
        report = self._report(engine, users, attempts)
        json.dumps(report, allow_nan=False)

    def test_the_test_is_welch(self, engine):
        users = [{"id": f"u{i}", "study_group": "control" if i < 3 else "experimental"}
                 for i in range(6)]
        posts = [60, 70, 80, 70, 95, 100]
        attempts = []
        for i in range(6):
            attempts += [_a(f"u{i}", 50, "pre"), _a(f"u{i}", posts[i], "post")]
        report = self._report(engine, users, attempts)
        from scipy import stats
        gains = [engine.calculate_nlg(50, p) for p in posts]
        expected = stats.ttest_ind(gains[3:], gains[:3], equal_var=False).pvalue
        assert report["statistical_significance"]["test"] == "welch"
        assert report["statistical_significance"]["p_value"] == round(float(expected), 4)


class TestReAuditEdges:
    def _report(self, engine, users, attempts):
        with patch('backend.analytics.metrics.user_repo') as mu, \
             patch('backend.analytics.metrics.quiz_repo') as mq:
            mu.get_all.return_value = users
            mq.all_attempts.return_value = attempts
            return engine.generate_experiment_report()

    def test_two_constant_arms_are_not_called_significant(self, engine):
        # scipy returns p = 0 here, which read as a significant result.
        users = [{"id": f"u{i}", "study_group": "experimental" if i < 3 else "control"}
                 for i in range(5)]
        attempts = []
        for i in range(5):
            attempts += [_a(f"u{i}", 40, "pre"), _a(f"u{i}", 100 if i < 3 else 80, "post")]
        report = self._report(engine, users, attempts)
        assert isinstance(report["statistical_significance"], str)

    def test_an_unknown_gap_counts_as_the_same_day(self, engine):
        users = [{"id": "u1", "study_group": "control"}]
        attempts = [_a("u1", 40, "pre"), _a("u1", 70, "post")]
        report = self._report(engine, users, attempts)
        assert report["control"]["same_day"]["user_count"] == 1
        assert report["control"]["across_sessions"]["user_count"] == 0

    def test_an_empty_arm_has_no_average_rather_than_zero(self, engine):
        report = self._report(engine, [], [])
        assert report["control"]["avg_gain"] is None

    def test_probes_from_the_fallback_bank_are_counted(self, engine):
        users = [{"id": "u1", "study_group": "control"}]
        attempts = [_a("u1", 40, "pre"), {**_a("u1", 70, "post"),
                    "quiz_meta": {"probe": "post", "source": "fallback"}}]
        report = self._report(engine, users, attempts)
        assert report["control"]["probes_from_fallback"] == 1
