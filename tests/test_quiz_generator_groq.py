"""
Tests for the Groq-first quiz generator refactoring.
Covers: Groq path, Ollama fallback path, static fallback, prompt trimming,
        question count caps, and the new QuizGenerator API.
"""
import json
import os
from unittest.mock import patch, MagicMock
import pytest
from backend.quiz.quiz_generator import QuizGenerator


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_groq_response(questions):
    """Build a mock Groq API response object."""
    body = json.dumps({"questions": questions, "topic_id": "os", "difficulty": "medium"})
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": body}}]}
    return resp


def _make_ollama_response(questions):
    """Build a mock Ollama API response object."""
    body = json.dumps({"questions": questions, "topic_id": "os", "difficulty": "medium"})
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"response": body}
    return resp


def _sample_questions(n=5):
    return [
        {"id": i, "text": f"Question {i}?",
         "options": ["A", "B", "C", "D"], "answer": "A", "hint": "Think carefully."}
        for i in range(1, n + 1)
    ]


# ── Question count caps (max 10) ────────────────────────────────────────────

class TestQuestionCountCaps:
    def test_slow_learner_gets_max_10(self):
        gen = QuizGenerator()
        for _ in range(20):
            count = gen._get_question_count(mastery=0.2, speed_label="Slow")
            assert 9 <= count <= 10, f"Slow learner count {count} out of range"

    def test_fast_learner_range(self):
        gen = QuizGenerator()
        for _ in range(20):
            count = gen._get_question_count(mastery=0.5, speed_label="Fast")
            assert 7 <= count <= 8, f"Fast learner count {count} out of range"

    def test_never_exceeds_10(self):
        gen = QuizGenerator()
        for speed in ["Slow", "Steady", "Fast"]:
            for mastery in [0.0, 0.2, 0.5, 0.8, 1.0]:
                count = gen._get_question_count(mastery=mastery, speed_label=speed)
                assert count <= 10, f"Count {count} exceeds cap for speed={speed}, mastery={mastery}"

    def test_never_below_6(self):
        gen = QuizGenerator()
        for speed in ["Slow", "Steady", "Fast"]:
            for mastery in [0.0, 0.5, 1.0]:
                count = gen._get_question_count(mastery=mastery, speed_label=speed)
                assert count >= 6, f"Count {count} below minimum for speed={speed}, mastery={mastery}"


# ── Groq API integration ────────────────────────────────────────────────────

class TestGroqIntegration:
    def test_groq_used_when_key_set(self):
        gen = QuizGenerator()
        gen.groq_api_key = "test-key"
        questions = _sample_questions(8)

        with patch("requests.post") as mock_post:
            mock_post.return_value = _make_groq_response(questions)
            result = gen.generate_quiz("os", "Operating Systems", "vid1")

        assert result is not None
        assert "questions" in result
        assert len(result["questions"]) > 0
        # Verify Groq URL was called (not Ollama)
        call_url = mock_post.call_args[0][0]
        assert "groq.com" in call_url, f"Expected Groq URL, got: {call_url}"

    def test_groq_skipped_when_no_key(self):
        gen = QuizGenerator()
        gen.groq_api_key = ""  # no key
        questions = _sample_questions(7)

        with patch("requests.post") as mock_post:
            mock_post.return_value = _make_ollama_response(questions)
            result = gen.generate_quiz("os", "Operating Systems", "vid1")

        assert result is not None
        call_url = mock_post.call_args[0][0]
        assert "ollama" in call_url or "localhost" in call_url, f"Expected Ollama URL, got: {call_url}"

    def test_groq_rate_limit_falls_back_to_ollama(self):
        gen = QuizGenerator()
        gen.groq_api_key = "test-key"
        questions = _sample_questions(7)

        groq_resp = MagicMock()
        groq_resp.status_code = 429  # rate limited
        ollama_resp = _make_ollama_response(questions)

        with patch("requests.post") as mock_post:
            mock_post.side_effect = [groq_resp, ollama_resp]
            result = gen.generate_quiz("os", "Operating Systems", "vid1")

        assert result is not None
        assert "questions" in result

    def test_groq_exception_falls_back_to_ollama(self):
        gen = QuizGenerator()
        gen.groq_api_key = "test-key"
        questions = _sample_questions(7)

        import requests as req_module
        with patch("requests.post") as mock_post:
            mock_post.side_effect = [
                req_module.exceptions.Timeout(),   # Groq times out
                _make_ollama_response(questions)    # Ollama succeeds
            ]
            result = gen.generate_quiz("os", "Operating Systems", "vid1")

        assert result is not None
        assert len(result["questions"]) > 0

    def test_both_fail_returns_static_fallback(self):
        gen = QuizGenerator()
        gen.groq_api_key = "test-key"

        import requests as req_module
        with patch("requests.post") as mock_post:
            mock_post.side_effect = req_module.exceptions.ConnectionError()
            result = gen.generate_quiz("os", "Operating Systems", "vid1")

        assert result is not None
        assert "questions" in result
        assert len(result["questions"]) >= 6  # static fallback has 10 questions

    def test_groq_bad_json_falls_back(self):
        gen = QuizGenerator()
        gen.groq_api_key = "test-key"
        questions = _sample_questions(7)

        bad_groq = MagicMock()
        bad_groq.status_code = 200
        bad_groq.json.return_value = {"choices": [{"message": {"content": "not json {"}}]}

        with patch("requests.post") as mock_post:
            mock_post.side_effect = [bad_groq, _make_ollama_response(questions)]
            result = gen.generate_quiz("os", "Operating Systems", "vid1")

        assert result is not None


# ── Prompt builder ──────────────────────────────────────────────────────────

class TestPromptBuilder:
    def test_prompt_contains_topic(self):
        gen = QuizGenerator()
        prompt = gen._build_prompt("os", "Operating Systems", 8, "medium",
                                   "General Learner", "Steady", 0.5, "Context:\n\n", [])
        assert "Operating Systems" in prompt

    def test_prompt_contains_difficulty(self):
        gen = QuizGenerator()
        prompt = gen._build_prompt("os", "OS", 8, "hard",
                                   "General Learner", "Steady", 0.5, "", [])
        assert "hard" in prompt

    def test_prompt_includes_avoid_questions(self):
        gen = QuizGenerator()
        avoid = ["What is a process?", "Define thread."]
        prompt = gen._build_prompt("os", "OS", 8, "medium",
                                   "General Learner", "Steady", 0.5, "", avoid)
        assert "What is a process?" in prompt

    def test_low_mastery_instruction(self):
        gen = QuizGenerator()
        prompt = gen._build_prompt("os", "OS", 8, "medium",
                                   "General Learner", "Steady", 0.2, "", [])
        assert "foundational" in prompt.lower()

    def test_high_mastery_instruction(self):
        gen = QuizGenerator()
        prompt = gen._build_prompt("os", "OS", 8, "medium",
                                   "General Learner", "Steady", 0.8, "", [])
        assert "analytical" in prompt.lower() or "challenging" in prompt.lower()
