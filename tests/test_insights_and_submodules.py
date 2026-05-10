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
from backend.quiz.quiz_insights import QuizInsightsEngine


def _engine(groq_key=""):
    e = QuizInsightsEngine()
    e.groq_api_key = groq_key
    return e


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
    def test_fast_wrong_is_guessed(self):
        e = _engine()
        q = _qr(is_correct=False, time_taken=3.0)
        assert e._diagnose_question(q) == "guessed"

    def test_slow_wrong_is_confused(self):
        e = _engine()
        q = _qr(is_correct=False, time_taken=30.0)
        assert e._diagnose_question(q) == "confused"

    def test_medium_wrong_is_misconception(self):
        e = _engine()
        q = _qr(is_correct=False, time_taken=12.0)
        assert e._diagnose_question(q) == "misconception"

    def test_correct_returns_none(self):
        e = _engine()
        q = _qr(is_correct=True, time_taken=8.0)
        assert e._diagnose_question(q) is None

    def test_boundary_exactly_5s_is_misconception(self):
        e = _engine()
        q = _qr(is_correct=False, time_taken=5.0)
        # >= 5 and <= 25 → misconception
        assert e._diagnose_question(q) == "misconception"

    def test_boundary_exactly_25s_is_misconception(self):
        e = _engine()
        q = _qr(is_correct=False, time_taken=25.0)
        assert e._diagnose_question(q) == "misconception"

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
            assert "nptel" in res["url"].lower() or "geeksforgeeks" in res["url"].lower(), \
                f"Resource not NPTEL/GFG: {res['url']}"

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

    def test_each_topic_has_three_modules(self):
        from utils.constants import SUBMODULE_DEFINITIONS
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            assert len(mods) == 3, f"Topic '{topic}' has {len(mods)} modules, expected 3"

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
            prev_end = -1
            for mod in mods:
                assert mod["start_sec"] >= 0
                # Contiguous is fine (start == prev_end), only overlap is invalid
                assert mod["start_sec"] >= prev_end, \
                    f"Module '{mod['title']}' starts at {mod['start_sec']} before prev end {prev_end}"
                if mod["end_sec"] is not None:
                    assert mod["end_sec"] > mod["start_sec"]
                    prev_end = mod["end_sec"]

    def test_exam_angles_contain_gate_tip(self):
        from utils.constants import SUBMODULE_DEFINITIONS
        for topic, mods in SUBMODULE_DEFINITIONS.items():
            for mod in mods:
                if mod["exam_angle"]:
                    assert "GATE" in mod["exam_angle"] or "Tip" in mod["exam_angle"], \
                        f"Exam angle for '{topic}' module '{mod['title']}' doesn't mention GATE"


# ── build_topic_submodules integration ──────────────────────────────────────

class TestBuildTopicSubmodules:
    def _build(self, topic_id, title="Test"):
        import app
        return app.build_topic_submodules({"id": topic_id, "video_id": "vid1", "title": title})

    def test_os_returns_three_submodules(self):
        mods = self._build("os", "Operating Systems")
        assert len(mods) == 3

    def test_submodule_ids_are_scoped(self):
        mods = self._build("ds", "Data Structures")
        for i, mod in enumerate(mods, start=1):
            assert mod["id"] == f"ds-m{i}"

    def test_video_id_propagated(self):
        import app
        mods = app.build_topic_submodules({"id": "os", "video_id": "abc123", "title": "OS"})
        for mod in mods:
            assert mod["video_id"] == "abc123"

    def test_unknown_topic_uses_generic_fallback(self):
        mods = self._build("unknown_topic", "Some Topic")
        assert len(mods) == 3
        assert mods[0]["title"] == "Module 1: Foundations"

    def test_exam_angle_present_in_known_topics(self):
        for topic in ("os", "ds", "dbms", "cn"):
            mods = self._build(topic)
            for mod in mods:
                assert "exam_angle" in mod
