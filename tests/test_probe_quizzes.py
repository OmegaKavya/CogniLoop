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
        self.avoided = []

    def __call__(self, topic_id, topic_name, youtube_id, watch_time=0, difficulty="medium",
                 mastery=0.3, cluster="General Learner", speed_label="Steady",
                 avoid_questions=None):
        self.calls.append({"difficulty": difficulty, "mastery": mastery,
                           "cluster": cluster, "speed": speed_label})
        self.avoided.append(list(avoid_questions or []))
        return {"topic_id": topic_id, "difficulty": difficulty, "questions": [
            {"id": 1, "text": f"Q{len(self.calls)}?", "options": ["A", "B"], "answer": "A"}]}


def _issue(client, topic="test_topic", check=False):
    url = f'/api/quiz-data/{topic}' + ('?check=1' if check else '')
    return json.loads(client.get(url).data)


def _submit(client, token):
    return client.post('/api/quiz-submit', json={
        "quiz_token": token,
        "responses": [{"question_id": 1, "selected_answer": "A", "time_taken": 5}],
    })


def _take(client, topic="test_topic", check=False):
    """Fetch a quiz and submit it; return (issued quiz, submit response)."""
    issued = _issue(client, topic, check)
    body = json.loads(_submit(client, issued["quiz_token"]).data)
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


def _probes(user_id):
    return [a["quiz_meta"]["probe"] for a in app_module.quiz_repo.get_user_attempts(user_id)]


def test_the_check_is_refused_before_it_unlocks(client):
    # Only the button is hidden before then; the request itself is a query
    # parameter anyone can add.
    _register(client, "control")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        _take(client)                              # pre
        quiz, _ = _take(client, check=True)
    assert quiz["probe"] is None
    assert quiz["check_declined"] == "not_yet"


def test_the_check_is_issued_once_so_a_reload_cannot_replace_it(client):
    user_id = _register(client, "control")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        for _ in range(3):
            _take(client)
        _take(client, check=True)
        again, body = _take(client, check=True)    # the results page reloaded
    assert again["probe"] is None
    assert again["check_declined"] == "done"
    assert body["check_available"] is False
    assert _probes(user_id).count("post") == 1


def test_two_tabs_record_one_pre_test(client):
    user_id = _register(client, "experimental")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        first, second = _issue(client), _issue(client)
        assert first["quiz"]["probe"] == second["quiz"]["probe"] == "pre"
        _submit(client, first["quiz_token"])
        body = json.loads(_submit(client, second["quiz_token"]).data)
    assert _probes(user_id) == ["pre", None]
    assert body["probe"] is None
    # The duplicate is practice: one more quiz is still needed for the check.
    assert body["check_available"] is False


def test_the_check_avoids_everything_seen_with_the_pre_test_first(client):
    _register(client, "control")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        for _ in range(7):                         # pre and six practice
            _take(client)
        _take(client, check=True)
    avoided = gen.avoided[-1]
    # Past the old five-attempt window, the pre-test's question is still there.
    assert avoided[0] == "Q1?"
    assert sorted(avoided) == sorted(f"Q{n}?" for n in range(1, 8))


def test_a_second_submission_of_one_token_is_refused(client):
    user_id = _register(client, "control")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        issued = _issue(client)
        assert _submit(client, issued["quiz_token"]).status_code == 200
        assert _submit(client, issued["quiz_token"]).status_code in (400, 409)
    assert len(app_module.quiz_repo.get_user_attempts(user_id)) == 1


def test_a_concurrent_second_submission_gets_409_and_writes_nothing(client):
    # The second request passed the early check before the first consumed
    # the token: only the consume inside the transaction stops it.
    user_id = _register(client, "control")
    gen = _Generator()
    store = app_module.active_quiz_store
    real_get = store.get
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        issued = _issue(client)
        held = real_get(issued["quiz_token"], user_id)
        assert _submit(client, issued["quiz_token"]).status_code == 200
        with patch.object(store, 'get', return_value=held):
            late = _submit(client, issued["quiz_token"])
    assert late.status_code == 409
    assert len(app_module.quiz_repo.get_user_attempts(user_id)) == 1


def test_a_quiz_that_expires_during_grading_is_still_recorded(client):
    user_id = _register(client, "control")
    gen = _Generator()
    real_evaluate = app_module.evaluator.evaluate
    later = patch('backend.quiz.quiz_session.time.time',
                  return_value=10 ** 12)

    def slow_evaluate(quiz, responses):
        later.start()                              # the clock runs past expiry
        return real_evaluate(quiz, responses)

    try:
        with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
             patch('app.refine_insights_in_background'), \
             patch.object(app_module.evaluator, 'evaluate', side_effect=slow_evaluate):
            issued = _issue(client)
            response = _submit(client, issued["quiz_token"])
    finally:
        later.stop()
    assert response.status_code == 200
    assert len(app_module.quiz_repo.get_user_attempts(user_id)) == 1


def test_a_non_ascii_token_is_a_400_not_a_500(client):
    # compare_digest raises on non-ASCII str, but only once there is a stored
    # token to compare against, so one is issued first.
    _register(client, "control")
    with patch.object(app_module.quiz_gen, 'generate_quiz', _Generator()):
        _issue(client)
    assert _submit(client, "\u00e9t\u00e9").status_code == 400
