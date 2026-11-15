"""Tests for the integrity of the quiz loop.

These pin properties that were all violated at once before this module existed:
the answer key was served to the client in two places, the client chose the
difficulty its own mastery update was computed with, and a language model had
the final say on whether an answer was right.

Each of those corrupts more than a single score. Quiz results feed the mastery
estimate, which feeds the difficulty policy, which decides what the learner is
shown next - so a leaked key or a client-named parameter does not merely
inflate one number, it poisons the signal the system adapts on and any analysis
built on the data it produces.
"""
import json
import time
import uuid
from unittest.mock import patch

from app import app
from backend.quiz.quiz_session import ActiveQuizStore, public_view


def _register(client, email=None):
    """Register a learner and return their user id."""
    email = email or f"integrity-{uuid.uuid4().hex[:10]}@test.com"
    client.post('/register', json={"name": "Integrity", "email": email, "password": "pw"})
    with client.session_transaction() as sess:
        return sess['user_id']


def _quiz(difficulty="medium"):
    return {
        "topic_id": "test_topic",
        "difficulty": difficulty,
        "num_questions": 2,
        "questions": [
            {"id": 1, "text": "Q1?", "options": ["A", "B", "C", "D"],
             "answer": "B", "hint": "h1"},
            {"id": 2, "text": "Q2?", "options": ["A", "B", "C", "D"],
             "answer": "D", "hint": "h2"},
        ],
    }


class TestAnswerKeyNeverReachesTheClient:
    def test_api_response_carries_no_answers(self, client):
        _register(client)
        with patch('backend.quiz.quiz_generator.QuizGenerator.generate_quiz',
                   return_value=_quiz()):
            res = client.get('/api/quiz-data/test_topic')

        assert res.status_code == 200
        body = json.loads(res.data)
        for question in body['quiz']['questions']:
            for leaked in ('answer', 'correct_answer', 'correct', 'correct_index'):
                assert leaked not in question, (
                    f"'{leaked}' was served to the client: {question}")

    def test_session_cookie_does_not_contain_the_quiz(self, client):
        _register(client)
        with patch('backend.quiz.quiz_generator.QuizGenerator.generate_quiz',
                   return_value=_quiz()):
            client.get('/api/quiz-data/test_topic')

        with client.session_transaction() as sess:
            assert 'current_quiz' not in sess, (
                "the quiz is back in the session cookie, which is signed but "
                "not encrypted and so is readable by the learner holding it")

    def test_public_view_does_not_mutate_the_original(self):
        quiz = _quiz()
        public_view(quiz)
        assert quiz['questions'][0]['answer'] == "B", (
            "redaction stripped the server's own copy, which would make "
            "grading impossible")

    def test_public_view_preserves_what_the_learner_needs(self):
        redacted = public_view(_quiz())
        question = redacted['questions'][0]
        for needed in ('id', 'text', 'options', 'hint'):
            assert needed in question
        assert len(question['options']) == 4


class TestTokenOwnershipAndReplay:
    def test_token_is_required(self, client):
        _register(client)
        res = client.post('/api/quiz-submit', json={
            "topic_id": "test_topic", "responses": []})
        assert res.status_code == 400

    def test_another_learners_token_is_rejected(self, client, test_data_dir):
        store = ActiveQuizStore(file_path=f"{test_data_dir}/active_quizzes.json")
        victim_token = store.issue("9001", _quiz())
        assert store.get(victim_token, "9002") is None, (
            "a token issued to one learner graded for another")
        assert store.get(victim_token, "9001") is not None

    def test_token_grades_exactly_once(self, client, test_data_dir):
        store = ActiveQuizStore(file_path=f"{test_data_dir}/active_quizzes.json")
        token = store.issue("9003", _quiz())
        assert store.consume(token, "9003") is not None
        assert store.consume(token, "9003") is None, (
            "the same issued quiz was graded twice, which lets one set of "
            "questions be replayed for repeated mastery updates")

    def test_expired_token_is_rejected(self, client, test_data_dir):
        store = ActiveQuizStore(file_path=f"{test_data_dir}/active_quizzes.json",
                                ttl_seconds=60)
        now = time.time()
        token = store.issue("9004", _quiz(), now=now)
        assert store.get(token, "9004", now=now + 30) is not None
        assert store.get(token, "9004", now=now + 61) is None

    def test_unknown_token_is_rejected(self, client, test_data_dir):
        store = ActiveQuizStore(file_path=f"{test_data_dir}/active_quizzes.json")
        store.issue("9005", _quiz())
        assert store.get("not-a-real-token", "9005") is None

    def test_two_tabs_each_hold_a_valid_quiz(self, client, test_data_dir):
        """Keying by learner made a second tab silently void the first."""
        store = ActiveQuizStore(file_path=f"{test_data_dir}/active_quizzes.json")
        first = store.issue("9006", _quiz("easy"))
        second = store.issue("9006", _quiz("hard"))
        assert store.get(first, "9006")['difficulty'] == "easy"
        assert store.get(second, "9006")['difficulty'] == "hard"

    def test_outstanding_quizzes_are_capped(self, client, test_data_dir):
        store = ActiveQuizStore(file_path=f"{test_data_dir}/active_quizzes.json",
                                max_per_user=3)
        tokens = [store.issue("9007", _quiz()) for _ in range(6)]
        live = [t for t in tokens if store.get(t, "9007") is not None]
        assert len(live) <= 3, f"{len(live)} outstanding quizzes, cap was 3"
        # The most recent survive.
        assert store.get(tokens[-1], "9007") is not None


class TestDifficultyIsServerAuthoritative:
    def test_client_supplied_difficulty_is_ignored(self, client):
        """A client naming `hard` would swap guess/slip from 0.30/0.05 to
        0.10/0.15 and inflate the mastery posterior per correct answer."""
        user_id = _register(client)
        from backend.quiz.quiz_session import active_quiz_store
        token = active_quiz_store.issue(user_id, _quiz(difficulty="easy"))

        captured = {}

        def fake_update(uid, tid, correct, difficulty="medium"):
            captured['difficulty'] = difficulty
            return 0.5

        with patch('backend.quiz.quiz_evaluator.evaluator.evaluate') as ev, \
             patch('app.bkt_engine.update_mastery', side_effect=fake_update):
            ev.return_value = {"score": 100, "avg_time": 10, "total_time": 10,
                               "question_results": []}
            client.post('/api/quiz-submit', json={
                "topic_id": "test_topic",
                "responses": [{"question_id": 1, "selected_answer": "B", "time_taken": 5}],
                "quiz_token": token,
                "difficulty": "hard",          # the client lying
            })

        assert captured.get('difficulty') == "easy", (
            "the mastery update used the difficulty the client sent rather "
            "than the tier the server actually served")


class TestBanditCreditAssignment:
    def test_served_tier_matches_the_requested_tier(self):
        """The generator used to override its caller with random.choice, so the
        arm the bandit selected was not the arm that got served or credited."""
        from backend.llm import LLMClient
        from backend.quiz.quiz_generator import QuizGenerator

        gen = QuizGenerator(client=LLMClient(groq_api_key="", ollama_enabled=False))
        for tier in ("easy", "medium", "hard"):
            for speed in ("Fast", "Steady", "Slow"):
                for _ in range(10):
                    quiz = gen.generate_quiz(
                        'os', 'Operating Systems', 'vid',
                        difficulty=tier, speed_label=speed)
                    assert quiz['difficulty'] == tier, (
                        f"asked for {tier} at speed {speed}, served "
                        f"{quiz['difficulty']}")

    def test_speed_still_adapts_question_count(self):
        """Removing the difficulty override must not remove speed adaptation
        altogether - it moves to a decision it does not contend for."""
        from backend.llm import LLMClient
        from backend.quiz.quiz_generator import QuizGenerator

        gen = QuizGenerator(client=LLMClient(groq_api_key="", ollama_enabled=False))
        slow = [gen._get_question_count(0.5, "Slow") for _ in range(50)]
        fast = [gen._get_question_count(0.5, "Fast") for _ in range(50)]
        assert sum(slow) / len(slow) > sum(fast) / len(fast)


class TestGradingIsDeterministic:
    def test_model_cannot_flip_a_grade(self):
        """The model supplies prose. Correctness is string equality, because we
        hold the correct option text and there is nothing to adjudicate."""
        from backend.llm import LLMClient
        from backend.quiz.quiz_evaluator import QuizEvaluator

        quiz = _quiz()
        responses = [
            {"question_id": 1, "selected_answer": "B", "time_taken": 5},   # right
            {"question_id": 2, "selected_answer": "A", "time_taken": 5},   # wrong
        ]

        # A model that grades both the wrong way round.
        liar = [{"id": "1", "is_correct": False, "feedback": "f1"},
                {"id": "2", "is_correct": True, "feedback": "f2"}]

        ev = QuizEvaluator(client=LLMClient(groq_api_key="", ollama_enabled=False))
        with patch.object(ev.client, 'complete_json', return_value=liar):
            result = ev.evaluate(quiz, responses)

        by_id = {str(r['question_id']): r for r in result['question_results']}
        assert by_id['1']['is_correct'] is True, "model flipped a correct answer to wrong"
        assert by_id['2']['is_correct'] is False, "model flipped a wrong answer to correct"

    def test_model_feedback_is_still_used(self):
        from backend.llm import LLMClient
        from backend.quiz.quiz_evaluator import QuizEvaluator

        quiz = _quiz()
        responses = [{"question_id": 1, "selected_answer": "B", "time_taken": 5}]
        prose = [{"id": "1", "feedback": "A semaphore guards the critical section."}]

        ev = QuizEvaluator(client=LLMClient(groq_api_key="", ollama_enabled=False))
        with patch.object(ev.client, 'complete_json', return_value=prose):
            result = ev.evaluate(quiz, responses)

        assert result['question_results'][0]['feedback'] == \
            "A semaphore guards the critical section."

    def test_grading_works_with_no_model_at_all(self):
        from backend.llm import LLMClient
        from backend.quiz.quiz_evaluator import QuizEvaluator

        quiz = _quiz()
        responses = [
            {"question_id": 1, "selected_answer": "B", "time_taken": 5},
            {"question_id": 2, "selected_answer": "A", "time_taken": 5},
        ]
        ev = QuizEvaluator(client=LLMClient(groq_api_key="", ollama_enabled=False))
        with patch.object(ev.client, 'complete_json', return_value=None):
            result = ev.evaluate(quiz, responses)

        assert result['score'] == 50
        by_id = {str(r['question_id']): r for r in result['question_results']}
        assert by_id['1']['is_correct'] is True
        assert by_id['2']['is_correct'] is False


class TestCsrfProtection:
    """Authenticated state-changing requests must carry the double-submit token.

    The test client attaches the header automatically, as a browser does, so
    these tests strip or corrupt it deliberately. Without that, the protection
    would be present but never actually exercised.
    """

    def test_authenticated_post_without_the_header_is_rejected(self, client):
        _register(client)
        res = client.post('/api/video-track',
                          json={"topic_id": "test_topic", "watch_percentage": 10},
                          headers={"X-CSRF-Token": ""})
        assert res.status_code == 403, (
            "a state-changing request was accepted with no CSRF token")

    def test_wrong_token_is_rejected(self, client):
        _register(client)
        res = client.post('/api/video-track',
                          json={"topic_id": "test_topic", "watch_percentage": 10},
                          headers={"X-CSRF-Token": "not-the-right-token"})
        assert res.status_code == 403

    def test_correct_token_is_accepted(self, client):
        _register(client)
        res = client.post('/api/video-track',
                          json={"topic_id": "test_topic", "pause_count": 1,
                                "rewatch_count": 0, "skip_ratio": 0.0,
                                "watch_percentage": 10, "last_time": 5,
                                "total_duration": 100, "max_reached": 5})
        assert res.status_code == 200

    def test_reads_are_not_blocked(self, client):
        _register(client)
        assert client.get('/dashboard').status_code == 200

    def test_registration_does_not_require_a_token(self, client):
        """There is no session to ride before login, and requiring a token
        would reject the first request every new visitor makes."""
        res = client.post('/register', json={
            "name": "Fresh", "email": f"fresh-{uuid.uuid4().hex[:8]}@test.com",
            "password": "pw"})
        assert res.status_code in (200, 201)

    def test_token_is_bound_to_the_session(self, client, test_data_dir):
        """One learner's token must not authorise another's request."""
        _register(client)
        with client.session_transaction() as sess:
            mine = sess['csrf_token']

        other = app.test_client()
        other.post('/register', json={
            "name": "Other", "email": f"other-{uuid.uuid4().hex[:8]}@test.com",
            "password": "pw"})
        res = other.post('/api/video-track',
                         json={"topic_id": "test_topic", "watch_percentage": 10},
                         headers={"X-CSRF-Token": mine})
        assert res.status_code == 403
