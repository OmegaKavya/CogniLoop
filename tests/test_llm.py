"""
Tests for the shared language-model client and model-backed grading.

Two properties matter most and are regression tests for real defects:

  * A provider that is not configured must not be contacted. Evaluation used to
    call a local Ollama unconditionally; on a host without one, a refused
    connection still cost about eight seconds on every quiz submission.

  * Grading must never depend on the model. Generation had a Groq path and
    evaluation did not, so in production the only provider was unreachable and
    every learner silently received canned fallback feedback.
"""
import json
from unittest.mock import MagicMock, patch

from backend.llm import LLMClient, _extract_json
from backend.quiz.quiz_evaluator import QuizEvaluator


def groq_response(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
    r.text = ""
    return r


def ollama_response(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {"response": json.dumps(payload)}
    return r


class TestProviderSelection:
    def test_no_providers_makes_no_network_call(self):
        client = LLMClient(groq_api_key="", ollama_enabled=False)
        with patch("backend.llm.requests.post") as post:
            assert client.complete_json("hi") is None
        post.assert_not_called()
        assert client.providers() == []

    def test_groq_is_preferred_when_configured(self):
        client = LLMClient(groq_api_key="k", ollama_enabled=True)
        with patch("backend.llm.requests.post") as post:
            post.return_value = groq_response({"ok": True})
            assert client.complete_json("hi") == {"ok": True}
        assert post.call_count == 1
        assert "groq.com" in post.call_args[0][0]

    def test_ollama_used_when_no_groq_key(self):
        client = LLMClient(groq_api_key="", ollama_enabled=True)
        with patch("backend.llm.requests.post") as post:
            post.return_value = ollama_response({"ok": True})
            assert client.complete_json("hi") == {"ok": True}
        assert "11434" in post.call_args[0][0]

    def test_disabled_ollama_is_never_contacted(self):
        client = LLMClient(groq_api_key="", ollama_enabled=False)
        with patch("backend.llm.requests.post") as post:
            client.complete_json("hi")
        post.assert_not_called()

    def test_rate_limited_groq_falls_back_to_ollama(self):
        client = LLMClient(groq_api_key="k", ollama_enabled=True)
        with patch("backend.llm.requests.post") as post:
            post.side_effect = [groq_response({}, status=429),
                                ollama_response({"ok": True})]
            assert client.complete_json("hi") == {"ok": True}
        assert post.call_count == 2

    def test_provider_exception_does_not_propagate(self):
        client = LLMClient(groq_api_key="k", ollama_enabled=False)
        with patch("backend.llm.requests.post", side_effect=OSError("boom")):
            assert client.complete_json("hi") is None

    def test_configured_fallback_is_tried_after_the_primary(self):
        """A second OpenAI-compatible endpoint is a config change, not a code change."""
        client = LLMClient(groq_api_key="k", ollama_enabled=False)
        client.fallback_url = "https://api.example.com/v1/chat/completions"
        client.fallback_api_key = "fk"
        client.fallback_model = "some-model"
        client.fallback_name = "cloudflare"

        assert client.providers() == ["groq", "cloudflare"]
        with patch("backend.llm.requests.post") as post:
            post.side_effect = [groq_response({}, status=429),
                                groq_response({"ok": True})]
            assert client.complete_json("hi") == {"ok": True}
        assert post.call_count == 2
        assert post.call_args_list[1][0][0] == "https://api.example.com/v1/chat/completions"

    def test_fallback_ignored_unless_both_url_and_key_are_set(self):
        client = LLMClient(groq_api_key="", ollama_enabled=False)
        client.fallback_url = "https://api.example.com/v1/chat/completions"
        assert client.providers() == []
        assert client.available is False

    def test_generation_and_grading_share_one_provider_set(self):
        """The drift between these two call sites is what broke grading."""
        from backend.quiz.quiz_generator import QuizGenerator
        gen, ev = QuizGenerator(), QuizEvaluator()
        assert gen.client.providers() == ev.client.providers()


class TestJsonExtraction:
    def test_plain_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_embedded_in_prose(self):
        assert _extract_json('Sure! [{"id": "1"}] hope that helps') == [{"id": "1"}]

    def test_unparseable_returns_none(self):
        assert _extract_json("no json here") is None
        assert _extract_json("") is None


class TestGradingDegradation:
    QUIZ = {"questions": [
        {"id": 1, "text": "Q1", "answer": "A", "options": ["A", "B"]},
        {"id": 2, "text": "Q2", "answer": "B", "options": ["A", "B"]},
    ]}
    RESP = [{"question_id": 1, "selected_answer": "A", "time_taken": 5},
            {"question_id": 2, "selected_answer": "A", "time_taken": 5}]

    def test_grades_correctly_without_any_model(self):
        ev = QuizEvaluator(client=LLMClient(groq_api_key="", ollama_enabled=False))
        result = ev.evaluate(self.QUIZ, self.RESP)
        assert result["score"] == 50.0
        assert result["question_results"][0]["is_correct"] is True
        assert result["question_results"][1]["is_correct"] is False

    def test_no_network_call_when_no_provider(self):
        ev = QuizEvaluator(client=LLMClient(groq_api_key="", ollama_enabled=False))
        with patch("backend.llm.requests.post") as post:
            ev.evaluate(self.QUIZ, self.RESP)
        post.assert_not_called()

    def test_model_verdict_is_used_when_available(self):
        """A semantically equivalent answer should pass, unlike exact matching."""
        ev = QuizEvaluator(client=LLMClient(groq_api_key="k", ollama_enabled=False))
        verdict = [{"id": "1", "is_correct": True, "feedback": "Equivalent phrasing."},
                   {"id": "2", "is_correct": False, "feedback": "Not quite."}]
        with patch("backend.llm.requests.post", return_value=groq_response(verdict)):
            result = ev.evaluate(self.QUIZ,
                                 [{"question_id": 1, "selected_answer": "a ", "time_taken": 5},
                                  {"question_id": 2, "selected_answer": "A", "time_taken": 5}])
        assert result["question_results"][0]["feedback"] == "Equivalent phrasing."
        assert result["score"] == 50.0

    def test_malformed_model_output_falls_back_per_question(self):
        ev = QuizEvaluator(client=LLMClient(groq_api_key="k", ollama_enabled=False))
        with patch("backend.llm.requests.post",
                   return_value=groq_response({"unexpected": "shape"})):
            result = ev.evaluate(self.QUIZ, self.RESP)
        assert result["score"] == 50.0

    def test_unanswered_question_is_marked_incorrect(self):
        ev = QuizEvaluator(client=LLMClient(groq_api_key="", ollama_enabled=False))
        result = ev.evaluate(self.QUIZ,
                             [{"question_id": 1, "selected_answer": "", "time_taken": 3}])
        assert result["question_results"][0]["is_correct"] is False
