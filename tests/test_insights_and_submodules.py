"""
Tests for the improved QuizInsightsEngine:
- Time-based diagnosis (guessed / confused / misconception)
- Cheat-sheet concept mapping for wrong questions
- Smart fallback quality (non-generic content)
- Groq path + Ollama fallback chain
"""
import json
from unittest.mock import patch, MagicMock
import pytest

from backend import config
from backend.quiz.quiz_insights import QuizInsightsEngine


def _engine(groq_key=""):
    from backend.llm import LLMClient
    return QuizInsightsEngine(
        client=LLMClient(groq_api_key=groq_key, ollama_enabled=False))


def _qr(is_correct, time_taken, text="What is a process?", selected="B", correct="A"):
    return {
        "is_correct": is_correct,
        "time_taken": time_taken,
        "text": text,
        "selected_answer": selected,
        "correct_answer": correct,
        "feedback": ""
    }


# ── Time-based diagnosis ────────────────────────────────────────────────────

class TestDiagnosis:
    """Thresholds are fractions of the question's own time limit.

    They used to be fixed seconds, and "confused" required more than 25 of
    them on a question the client cuts off at 10 to 15. It could not fire. The
    old test asserted it did, using time_taken=30.0 - a value the system is
    incapable of producing - so the test passed while the feature was dead.
    Every case below uses a time the client could actually report.
    """

    LIMIT = 12  # a medium question's budget

    def test_fast_wrong_is_guessed(self):
        assert _engine()._diagnose_question(
            _qr(is_correct=False, time_taken=3.0), self.LIMIT) == "guessed"

    def test_using_most_of_the_time_and_still_wrong_is_confused(self):
        """Reachable: 10.5s of a 12s budget is a time the client reports."""
        assert _engine()._diagnose_question(
            _qr(is_correct=False, time_taken=10.5), self.LIMIT) == "confused"

    def test_a_timed_out_question_is_confused(self):
        """On auto-advance the client reports the limit itself."""
        assert _engine()._diagnose_question(
            _qr(is_correct=False, time_taken=self.LIMIT), self.LIMIT) == "confused"

    def test_medium_wrong_is_misconception(self):
        assert _engine()._diagnose_question(
            _qr(is_correct=False, time_taken=7.0), self.LIMIT) == "misconception"

    def test_correct_returns_none(self):
        assert _engine()._diagnose_question(
            _qr(is_correct=True, time_taken=8.0), self.LIMIT) is None

    def test_fast_correct_is_a_lucky_guess(self):
        assert _engine()._diagnose_question(
            _qr(is_correct=True, time_taken=1.0), self.LIMIT) == "lucky_guess"

    def test_every_diagnosis_is_reachable_within_the_real_time_budget(self):
        """The regression test for the actual bug: with times the client can
        produce, all four outcomes must occur. The old absolute thresholds
        could only ever yield three."""
        e = _engine()
        seen = {e._diagnose_question(_qr(is_correct=c, time_taken=t), self.LIMIT)
                for c, t in [(True, 1.0), (True, 8.0), (False, 2.0),
                             (False, 7.0), (False, self.LIMIT)]}
        assert seen == {"lucky_guess", None, "guessed", "misconception", "confused"}

    def test_thresholds_scale_with_difficulty(self):
        """The same 9 seconds is a misconception on an easy question and
        confusion on a hard one, because the budgets differ."""
        e = _engine()
        q = _qr(is_correct=False, time_taken=9.0)
        assert e._diagnose_question(q, 15) == "misconception"
        assert e._diagnose_question(q, 10) == "confused"

    def test_a_missing_limit_falls_back_to_the_default(self):
        assert _engine()._diagnose_question(
            _qr(is_correct=False, time_taken=1.0)) == "guessed"

    def test_the_boundary_sits_just_below_the_confused_fraction(self):
        """Replaces a test that asserted 25.0 seconds was a misconception.
        The client cannot report 25 seconds, so that assertion described
        behaviour no learner could ever trigger."""
        e = _engine()
        just_under = config.DIAGNOSIS_CONFUSED_FRACTION * self.LIMIT - 0.1
        assert e._diagnose_question(
            _qr(is_correct=False, time_taken=just_under), self.LIMIT) == "misconception"
        assert e._diagnose_question(
            _qr(is_correct=False, time_taken=just_under + 0.2), self.LIMIT) == "confused"

    def test_zero_time_is_guessed(self):
        e = _engine()
        q = _qr(is_correct=False, time_taken=0)
        assert e._diagnose_question(q) == "guessed"


# ── Smart fallback quality ──────────────────────────────────────────────────

class TestSmartFallback:
    def test_fallback_returns_required_keys(self):
        e = _engine()
        incorrect = [_qr(False, 3.0), _qr(False, 30.0)]
        result = e._smart_fallback("os", "Operating Systems", 40, 0.4, incorrect)
        for key in ("focus_concepts", "cheat_sheet", "resources", "summary", "diagnoses"):
            assert key in result, f"Missing key: {key}"

    def test_fallback_diagnosis_counts_correct(self):
        e = _engine()
        incorrect = [
            _qr(False, 2.0),   # guessed
            _qr(False, 3.5),   # guessed
            _qr(False, 30.0),  # confused
            _qr(False, 10.0),  # misconception
        ]
        result = e._smart_fallback("os", "Operating Systems", 25, 0.2, incorrect)
        diag = result["diagnoses"]
        assert diag["guessed"] == 2
        assert diag["confused"] == 1
        assert diag["misconception"] == 1

    def test_fallback_resources_are_not_generic_google(self):
        e = _engine()
        incorrect = [_qr(False, 10.0)]
        result = e._smart_fallback("os", "Operating Systems", 50, 0.4, incorrect)
        for res in result["resources"]:
            assert "video" in res["url"].lower() or "geeksforgeeks" in res["url"].lower(), \
                f"Resource not CogniLoop/GFG: {res['url']}"

    def test_fallback_cheat_sheet_uses_topic_drills(self):
        e = _engine()
        incorrect = [_qr(False, 10.0, text="scheduling problem")]
        result = e._smart_fallback("os", "Operating Systems", 50, 0.4, incorrect)
        # cheat sheet should contain real content, not the generic "do nothing"
        assert len(result["cheat_sheet"]) >= 2

    def test_perfect_score_returns_advanced_content(self):
        e = _engine()
        result = e.generate_insights("Operating Systems", 100, 0.9, [], topic_id="os")
        assert "perfect" in result["summary"].lower() or "strong" in result["summary"].lower() \
               or "excellent" in result["summary"].lower() or "mastery" in result["summary"].lower()
        assert "Advanced" in result["focus_concepts"] or any("advanc" in c.lower() for c in result["focus_concepts"])

    def test_low_score_summary_mentions_score(self):
        e = _engine()
        incorrect = [_qr(False, 3.0) for _ in range(8)]
        result = e.generate_insights("OS", 20, 0.1, incorrect + [_qr(True, 5.0)]*2, topic_id="os")
        assert "20" in result["summary"] or "low" in result["summary"].lower() or "score" in result["summary"].lower()


# ── Groq path ───────────────────────────────────────────────────────────────

class TestInsightsGroqPath:
    def _mock_groq_response(self, payload):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
        return resp

    def test_groq_insights_used_when_key_set(self):
        e = _engine(groq_key="test-key")
        incorrect = [_qr(False, 10.0)]
        groq_payload = {
            "focus_concepts": ["Scheduling"], "cheat_sheet": ["Review FCFS"],
            "resources": [{"title": "GFG", "url": "https://gfg.com"}], "summary": "Needs work."
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = self._mock_groq_response(groq_payload)
            result = e.generate_insights("OS", 50, 0.4, [_qr(True,5)] + incorrect, topic_id="os")

        assert result["summary"] == "Needs work."
        assert "Scheduling" in result["focus_concepts"]

    def test_groq_failure_uses_smart_fallback(self):
        e = _engine(groq_key="test-key")
        incorrect = [_qr(False, 10.0)]
        import requests as req_module
        with patch("requests.post") as mock_post:
            mock_post.side_effect = req_module.exceptions.Timeout()
            result = e.generate_insights("OS", 50, 0.4, incorrect, topic_id="os")

        # Should still return valid structure from smart fallback
        assert "focus_concepts" in result
        assert "summary" in result


# ── Submodule definitions ────────────────────────────────────────────────────

class TestSubmoduleDefinitions:
    def test_all_four_topics_defined(self):
        from utils.constants import SUBMODULE_DEFINITIONS
        for topic in ("os", "ds", "dbms", "cn"):
            assert topic in SUBMODULE_DEFINITIONS, f"Topic '{topic}' missing"

    def test_each_topic_has_at_least_four_modules(self):
        """A floor, not an exact count.

        Pinning this at exactly four made the curriculum's shape a test
        requirement: Data Structures legitimately needs six, because stacks and
        queues, hashing, and graph traversal are each a submodule's worth of
        material and were previously crammed into titles that no video covered.
        """
        from utils.constants import SUBMODULE_DEFINITIONS
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            assert len(mods) >= 4, f"Topic '{topic}' has only {len(mods)} modules"

    def test_each_module_has_required_keys(self):
        from utils.constants import SUBMODULE_DEFINITIONS
        required = {"title", "objective", "exam_angle", "start_sec", "checkpoints"}
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            for i, mod in enumerate(mods):
                for key in required:
                    assert key in mod, f"Topic '{topic}' module {i} missing key '{key}'"

    def test_each_module_has_three_checkpoints(self):
        from utils.constants import SUBMODULE_DEFINITIONS
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            for i, mod in enumerate(mods):
                n = len(mod["checkpoints"])
                assert n == 3, f"Topic '{topic}' module {i} has {n} checkpoints, expected 3"

    def test_each_checkpoint_has_four_options(self):
        from utils.constants import SUBMODULE_DEFINITIONS
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            for mod in mods:
                for cp in mod["checkpoints"]:
                    assert len(cp["options"]) == 4, \
                        f"Checkpoint {cp['id']} has {len(cp['options'])} options, expected 4"
                    assert 0 <= cp["correct_index"] <= 3

    def test_module_time_segments_are_ordered(self):
        from utils.constants import SUBMODULE_DEFINITIONS
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            for mod in mods:
                assert mod["start_sec"] >= 0
                assert mod["end_sec"] is not None, (
                    f"{topic}/{mod['title']}: end_sec is None, which plays the "
                    f"whole video - that shipped 135-minute submodules")
                assert mod["end_sec"] > mod["start_sec"]

    def test_module_windows_are_long_enough_to_teach(self):
        """A window of a few minutes on a multi-hour course serves its
        introduction, not the subject the submodule is named after. Every
        submodule pointing at a long video once had exactly that bug."""
        from utils.constants import SUBMODULE_DEFINITIONS
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            for mod in mods:
                length = mod["end_sec"] - mod["start_sec"]
                assert length >= 8 * 60, (
                    f"{topic}/{mod['title']}: window is only "
                    f"{length // 60}m {length % 60}s")
                assert length <= 75 * 60, (
                    f"{topic}/{mod['title']}: window is {length // 60}m, "
                    f"too long for a single submodule")

    def test_exam_angles_name_an_exam_context(self):
        """Every exam angle must tie the module to a real exam setting.

        This asserted "GATE" or "Tip", case-sensitively. GATE is a computer
        science exam, and Quantitative Aptitude - added so people without a CS
        background can take part - is a placement-test subject, not a GATE one.
        Its angles say "Placement tip", which is the same kind of guidance in
        the right exam context, and the old assertion rejected it on the case
        of one letter. Matching case-insensitively against either context is
        what the check was always trying to express.
        """
        from utils.constants import SUBMODULE_DEFINITIONS
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            for mod in mods:
                if mod["exam_angle"]:
                    angle = mod["exam_angle"].lower()
                    assert any(word in angle for word in ("gate", "placement", "tip")), \
                        (f"Exam angle for '{topic}' module '{mod['title']}' names no "
                         f"exam context: {mod['exam_angle'][:60]}")


# ── build_topic_submodules integration ──────────────────────────────────────

class TestBuildTopicSubmodules:
    def _build(self, topic_id, title="Test"):
        import app
        return app.build_topic_submodules({"id": topic_id, "video_id": "vid1", "title": title})

    def test_os_returns_four_submodules(self):
        mods = self._build("os", "Operating Systems")
        assert len(mods) == 4

    def test_submodule_ids_are_scoped(self):
        mods = self._build("ds", "Data Structures")
        for i, mod in enumerate(mods, start=1):
            assert mod["id"] == f"ds-m{i}"

    def test_video_id_propagated(self):
        import app
        mods = app.build_topic_submodules({"id": "unknown_topic", "video_id": "abc123", "title": "Unknown"})
        for mod in mods:
            assert mod["video_id"] == "abc123"

        os_mods = app.build_topic_submodules({"id": "os", "video_id": "fallback_vid", "title": "OS"})
        for mod in os_mods:
            assert mod["video_id"] is not None

    def test_unknown_topic_uses_generic_fallback(self):
        mods = self._build("unknown_topic", "Some Topic")
        assert len(mods) == 3
        assert mods[0]["title"] == "Module 1: Foundations"

    def test_exam_angle_present_in_known_topics(self):
        for topic in ("os", "ds", "dbms", "cn"):
            mods = self._build(topic)
            for mod in mods:
                assert "exam_angle" in mod


class TestLandingStatsAreDerived:
    """The landing page advertised hand-typed figures that had gone stale:
    48 checkpoints when there were 60, and 290 tests when there were more.
    These assert the page states what the curriculum actually contains."""

    def test_curriculum_totals_match_the_definitions(self):
        from backend import curriculum_stats
        from utils.constants import SUBMODULE_DEFINITIONS

        totals = curriculum_stats.curriculum_totals()
        expected_submodules = sum(len(m) for m in SUBMODULE_DEFINITIONS.values())
        expected_checkpoints = sum(len(s.get('checkpoints') or [])
                                   for mods in SUBMODULE_DEFINITIONS.values()
                                   for s in mods)
        assert totals['modules'] == len(SUBMODULE_DEFINITIONS)
        assert totals['submodules'] == expected_submodules
        assert totals['checkpoints'] == expected_checkpoints
        assert totals['hours'] > 0

    def test_per_topic_counts_match(self):
        from backend import curriculum_stats
        from utils.constants import SUBMODULE_DEFINITIONS

        per_topic = curriculum_stats.per_topic()
        assert set(per_topic) == set(SUBMODULE_DEFINITIONS)
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            assert per_topic[topic]['submodules'] == len(mods)
            assert per_topic[topic]['minutes'] > 0

    def test_missing_stats_file_omits_the_test_count(self, tmp_path):
        """A forgotten run must show nothing rather than a stale number."""
        from unittest.mock import patch
        from backend import curriculum_stats
        with patch.object(curriculum_stats, 'PROJECT_STATS_PATH',
                          str(tmp_path / 'absent.json')):
            assert curriculum_stats.test_count() is None

    def test_landing_page_states_the_real_numbers(self, client):
        from backend import curriculum_stats
        totals = curriculum_stats.curriculum_totals()
        html = client.get('/').data.decode()
        assert f'data-target="{totals["submodules"]}"' in html
        assert f'data-target="{totals["checkpoints"]}"' in html

    def test_landing_page_makes_no_unsupported_efficacy_claim(self, client):
        """The site claimed a statistically significant improvement over static
        instruction. The paper reports the opposite: below roughly ten items a
        fixed curriculum is as good or better."""
        html = client.get('/').data.decode().lower()
        for banned in ('statistically significant', 'p&lt;0.05', 'p<0.05',
                       'gold standard'):
            assert banned not in html, f"unsupported claim on the landing page: {banned}"


class TestReviewSpeedLabelConsistency:
    """The attempt list and the detail view of the same attempt showed
    different pace labels. The detail read a top-level `speed_label` that the
    stored record does not have, so it silently fell back to "Steady" for
    every learner regardless of how fast they actually answered."""

    def test_stored_attempt_has_no_top_level_speed_label(self):
        """Documents why the template cannot read it from there."""
        from app import build_review_rows
        attempt = {"attempt_id": "a1", "topic_id": "os", "score": 50,
                   "adaptation": {"speed_label": "Fast"}}
        row = build_review_rows([attempt], {"os": "Operating Systems"})[0]
        assert row["speed_label"] == "Fast"
        assert "speed_label" not in attempt

    def test_detail_template_reads_the_same_field_as_the_list(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html = open(os.path.join(here, "frontend/templates/quiz_review.html")).read()
        assert "selected_attempt.adaptation.speed_label" in html, (
            "the detail view is reading a field the stored attempt does not "
            "have, so it will always display the default")


class TestFirstRunHonesty:
    """What a brand-new account is told about itself.

    The dashboard greeted a minutes-old account with "Welcome back", credited
    it with a "1 Day Streak" it had not earned, and showed four red 30.0%
    scores. That 30% is the BKT prior - the model's starting assumption, not a
    measurement - so a learner who had done nothing was shown four failing
    grades for work they had not attempted.
    """

    def _fresh(self, client):
        import uuid
        email = f"firstrun-{uuid.uuid4().hex[:8]}@test.com"
        client.post('/register', json={"name": "New", "email": email, "password": "pw"})
        return client.get('/dashboard').data.decode()

    def test_new_account_is_not_welcomed_back(self, client):
        assert 'Welcome back' not in self._fresh(client)

    def test_new_account_has_no_streak(self, client):
        html = self._fresh(client)
        assert '1 Day Streak' not in html
        assert '0 Day Streak' in html

    def test_untouched_topics_show_not_started_rather_than_the_prior(self, client):
        html = self._fresh(client)
        assert 'Not started' in html
        assert '30.0%' not in html, (
            "the BKT prior is being rendered as though it were a measured score")

    def test_empty_chart_explains_itself(self, client):
        html = self._fresh(client)
        assert 'No attempts yet' in html

    def test_skill_tree_leads_with_plain_language(self, client):
        html = self._fresh(client)
        assert 'Prerequisite DAG' not in html, (
            "a GATE candidate is not the audience for 'prerequisite DAG'")
        assert 'How well you know each subject' in html
