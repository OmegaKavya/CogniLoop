"""The pilot's pre-test and post-test are the same instrument for everyone.

Practice quizzes adapt for the experimental arm and stay at medium for
control, and the generator also varies question count and wording with
mastery. A score on a practice quiz therefore partly reflects which quiz was
served. The pre-test (first quiz on a topic) and the post-test (the final
check) are generated with identical inputs in both arms, so the outcome
measured on them compares learners, not the quizzes they were routed to.
"""
import json
import uuid
from unittest.mock import patch

import app as app_module
from app import PROBE_INPUTS
from helpers import set_study_group


def _register(client, group):
    email = f"probe-{uuid.uuid4().hex[:10]}@test.com"
    client.post('/register', json={"name": "P", "email": email, "password": "pw"})
    with client.session_transaction() as sess:
        user_id = sess['user_id']
    set_study_group(user_id, group)
    return user_id


class _Generator:
    """Stands in for the model and records what each quiz was asked for."""

    def __init__(self):
        self.calls = []

    def __call__(self, topic_id, topic_name, youtube_id, watch_time=0, difficulty="medium",
                 mastery=0.3, cluster="General Learner", speed_label="Steady",
                 avoid_questions=None):
        self.calls.append({"difficulty": difficulty, "mastery": mastery,
                           "cluster": cluster, "speed": speed_label})
        return {"topic_id": topic_id, "difficulty": difficulty, "questions": [
            {"id": 1, "text": f"Q{len(self.calls)}?", "options": ["A", "B"], "answer": "A"}]}


def _take(client, topic="test_topic", check=False):
    """Fetch a quiz and submit it; return (issued quiz, submit response)."""
    url = f'/api/quiz-data/{topic}' + ('?check=1' if check else '')
    issued = json.loads(client.get(url).data)
    body = json.loads(client.post('/api/quiz-submit', json={
        "quiz_token": issued["quiz_token"],
        "responses": [{"question_id": 1, "selected_answer": "A", "time_taken": 5}],
    }).data)
    return issued["quiz"], body


def _expected_probe_call():
    return {"difficulty": PROBE_INPUTS["difficulty"], "mastery": PROBE_INPUTS["mastery"],
            "cluster": PROBE_INPUTS["cluster"], "speed": PROBE_INPUTS["speed"]}


def test_first_quiz_is_the_pre_test_with_fixed_inputs_in_both_arms(client):
    for group in ("control", "experimental"):
        client.get('/logout')
        _register(client, group)
        gen = _Generator()
        with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
             patch('app.refine_insights_in_background'):
            quiz, body = _take(client)
        assert quiz["probe"] == "pre", group
        assert gen.calls[0] == _expected_probe_call(), group
        assert body["probe"] == "pre"


def test_practice_still_adapts_for_the_experimental_arm(client):
    _register(client, "experimental")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'), \
         patch.object(app_module.bandit_adapter, 'get_action', return_value='hard'):
        _take(client)                      # pre-test
        quiz, _ = _take(client)            # practice
    assert quiz["probe"] is None
    assert gen.calls[1]["difficulty"] == "hard"


def test_the_check_quiz_is_the_post_test_and_identical_in_both_arms(client):
    calls = {}
    for group in ("control", "experimental"):
        client.get('/logout')
        _register(client, group)
        gen = _Generator()
        with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
             patch('app.refine_insights_in_background'), \
             patch.object(app_module.bandit_adapter, 'get_action', return_value='easy'):
            _take(client)                  # pre
            _take(client)                  # practice
            _take(client)                  # practice
            quiz, body = _take(client, check=True)
        assert quiz["probe"] == "post", group
        assert quiz["difficulty"] == PROBE_INPUTS["difficulty"]
        assert body["check_available"] is False
        calls[group] = gen.calls[-1]
    assert calls["control"] == calls["experimental"] == _expected_probe_call()


def test_a_check_request_before_any_quiz_is_the_pre_test(client):
    _register(client, "experimental")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        quiz, _ = _take(client, check=True)
    assert quiz["probe"] == "pre"


def test_the_check_is_offered_after_the_pre_test_and_two_practice_quizzes(client):
    _register(client, "control")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        offered = [_take(client)[1]["check_available"] for _ in range(3)]
    assert offered == [False, False, True]


def test_the_probe_is_stored_on_the_attempt(client):
    user_id = _register(client, "control")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        _take(client)
    stored = app_module.quiz_repo.get_user_attempts(user_id)[-1]
    assert stored["quiz_meta"]["probe"] == "pre"
