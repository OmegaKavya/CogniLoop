"""
Tests that quiz answers are not always in the same position.

This matters more than the equivalent checkpoint problem. Quiz scores feed
mastery estimation and the difficulty policy, so a learner who scores by always
picking the first option would drive mastery to ceiling without learning, and
the routing policy would then adapt on a meaningless signal.

Answers are stored as exact option text rather than an index, so reordering the
options cannot invalidate them; these tests assert that invariant too.
"""
import collections

from backend.llm import LLMClient
from backend.quiz.quiz_generator import QuizGenerator


def offline_generator():
    """A generator with no provider configured, so it uses the static pool."""
    return QuizGenerator(client=LLMClient(groq_api_key="", ollama_enabled=False))


class TestStaticPoolOptionOrder:
    def test_answer_is_not_always_first(self):
        positions = collections.Counter()
        gen = offline_generator()
        for _ in range(30):
            quiz = gen.generate_quiz('os', 'Operating Systems', 'vid')
            for q in quiz['questions']:
                positions[q['options'].index(q['answer'])] += 1
        assert len(positions) == 4, f"answer never lands in some slots: {dict(positions)}"
        share = max(positions.values()) / sum(positions.values())
        assert share < 0.45, f"answer concentrated at one position ({share:.0%})"

    def test_answer_text_survives_shuffling(self):
        gen = offline_generator()
        for _ in range(20):
            quiz = gen.generate_quiz('dbms', 'DBMS', 'vid')
            for q in quiz['questions']:
                assert q['answer'] in q['options'], q['text'][:60]

    def test_options_are_not_duplicated_or_dropped(self):
        gen = offline_generator()
        for _ in range(20):
            for q in gen.generate_quiz('cn', 'Computer Networks', 'vid')['questions']:
                assert len(q['options']) == len(set(q['options']))
                assert len(q['options']) >= 2


class TestShuffleHelper:
    def test_shuffles_in_place_and_returns_payload(self):
        gen = offline_generator()
        payload = {"questions": [{"text": "q", "options": ["a", "b", "c", "d"], "answer": "a"}]}
        out = gen._shuffle_question_options(payload)
        assert out is payload
        assert sorted(out["questions"][0]["options"]) == ["a", "b", "c", "d"]
        assert out["questions"][0]["answer"] == "a"

    def test_tolerates_missing_or_degenerate_options(self):
        gen = offline_generator()
        gen._shuffle_question_options({"questions": [{"text": "q"}]})
        gen._shuffle_question_options({"questions": [{"options": ["only"], "answer": "only"}]})
        gen._shuffle_question_options({})
        gen._shuffle_question_options(None)

    def test_model_supplied_quiz_is_also_shuffled(self):
        """The model tends to list the answer first as well, so the model path
        must be shuffled rather than trusted."""
        from unittest.mock import MagicMock, patch
        import json

        questions = [{"id": i, "text": f"Question {i} about scheduling and memory?",
                      "options": [f"correct-{i}", f"w1-{i}", f"w2-{i}", f"w3-{i}"],
                      "answer": f"correct-{i}", "hint": "h"} for i in range(1, 9)]
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {
            "content": json.dumps({"topic_id": "os", "difficulty": "medium",
                                   "num_questions": 8, "questions": questions})}}]}
        response.text = ""

        gen = QuizGenerator(client=LLMClient(groq_api_key="k", ollama_enabled=False))
        positions = collections.Counter()
        with patch("backend.llm.requests.post", return_value=response):
            for _ in range(30):
                quiz = gen.generate_quiz('os', 'Operating Systems', 'vid')
                for q in quiz['questions']:
                    if q['answer'] in q['options']:
                        positions[q['options'].index(q['answer'])] += 1
        assert len(positions) == 4, f"model path not shuffled: {dict(positions)}"
