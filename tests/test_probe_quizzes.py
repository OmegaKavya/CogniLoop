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

    def __init__(self, per_quiz=1):
        self.calls = []
        self.avoided = []
        self.per_quiz = per_quiz

    def __call__(self, topic_id, topic_name, youtube_id, watch_time=0, difficulty="medium",
                 mastery=0.3, cluster="General Learner", speed_label="Steady",
                 avoid_questions=None):
        self.calls.append({"difficulty": difficulty, "mastery": mastery,
                           "cluster": cluster, "speed": speed_label})
        self.avoided.append(list(avoid_questions or []))
        n = len(self.calls)
        if self.per_quiz == 1:
            texts = [f"Q{n}?"]
        else:
            texts = [f"Q{n}.{i}?" for i in range(1, self.per_quiz + 1)]
        return {"topic_id": topic_id, "difficulty": difficulty, "questions": [
            {"id": i, "text": t, "options": ["A", "B"], "answer": "A"}
            for i, t in enumerate(texts, start=1)]}


def _issue(client, topic="test_topic", check=False):
    url = f'/api/quiz-data/{topic}' + ('?check=1' if check else '')
    return json.loads(client.get(url).data)


def _submit(client, token, ids=(1,)):
    return client.post('/api/quiz-submit', json={
        "quiz_token": token,
        "responses": [{"question_id": i, "selected_answer": "A", "time_taken": 5} for i in ids],
    })


def _take(client, topic="test_topic", check=False):
    """Fetch a quiz, answer every question, submit; return (quiz, response)."""
    issued = _issue(client, topic, check)
    ids = [q["id"] for q in issued["quiz"]["questions"]]
    body = json.loads(_submit(client, issued["quiz_token"], ids).data)
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


def test_two_tabs_share_one_pre_test(client):
    # The second tab is handed the same starting quiz, so only one can be
    # submitted and the starting point cannot be redrawn.
    user_id = _register(client, "experimental")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        first, second = _issue(client), _issue(client)
        assert second["quiz_token"] == first["quiz_token"]
        assert _submit(client, first["quiz_token"]).status_code == 200
        assert _submit(client, second["quiz_token"]).status_code in (400, 409)
    assert _probes(user_id) == ["pre"]


def test_a_second_pre_test_that_slips_through_is_recorded_as_practice(client):
    # If two starting quizzes are ever issued (an expired one replaced, or two
    # requests racing), the one submitted second is practice.
    user_id = _register(client, "experimental")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'), \
         patch.object(app_module.active_quiz_store, 'find_probe', return_value=None):
        first, second = _issue(client), _issue(client)
        _submit(client, first["quiz_token"])
        body = json.loads(_submit(client, second["quiz_token"]).data)
    assert _probes(user_id) == ["pre", None]
    assert body["probe"] is None
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


def test_reloading_a_check_quiz_hands_back_the_same_one(client):
    # A fresh check quiz on every reload let a learner look at several and
    # submit the best.
    _register(client, "control")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        for _ in range(3):
            _take(client)
        first, again = _issue(client, check=True), _issue(client, check=True)
    assert first["quiz"]["probe"] == "post"
    assert again["quiz_token"] == first["quiz_token"]
    assert again["quiz"]["questions"] == first["quiz"]["questions"]
    assert len(gen.calls) == 4


def test_reloading_the_starting_quiz_hands_back_the_same_one(client):
    _register(client, "experimental")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen):
        first, again = _issue(client), _issue(client)
    assert first["quiz"]["probe"] == "pre"
    assert again["quiz_token"] == first["quiz_token"]
    assert len(gen.calls) == 1


def test_the_attempt_records_its_arm_and_the_quiz_source(client):
    user_id = _register(client, "control")
    gen = _Generator()
    with patch.object(app_module.quiz_gen, 'generate_quiz',
                      lambda *a, **k: {**gen(*a, **k), "source": "fallback"}), \
         patch('app.refine_insights_in_background'):
        _take(client)
    stored = app_module.quiz_repo.get_user_attempts(user_id)[-1]
    assert stored["study_group"] == "control"
    assert stored["quiz_meta"]["source"] == "fallback"


def test_the_check_avoid_list_is_not_capped(client):
    _register(client, "control")
    gen = _Generator(per_quiz=6)
    with patch.object(app_module.quiz_gen, 'generate_quiz', gen), \
         patch('app.refine_insights_in_background'):
        for _ in range(8):                         # 48 questions seen
            _take(client)
        _take(client, check=True)
    assert len(gen.avoided[-1]) == 48
    assert gen.avoided[-1][:6] == [f"Q1.{i}?" for i in range(1, 7)]
    assert len(gen.avoided[-2]) == 30            # practice keeps its window


def test_an_account_with_no_pre_test_is_told_the_check_cannot_open(client):
    user_id = _register(client, "control")
    for _ in range(3):
        app_module.quiz_repo.add_attempt({"user_id": user_id, "topic_id": "test_topic",
                                          "score": 50, "quiz_meta": {"probe": None}})
    with patch.object(app_module.quiz_gen, 'generate_quiz', _Generator()):
        quiz = _issue(client, check=True)["quiz"]
    assert quiz["probe"] is None
    assert quiz["check_declined"] == "unavailable"


def test_a_lone_surrogate_token_is_a_400(client):
    _register(client, "control")
    with patch.object(app_module.quiz_gen, 'generate_quiz', _Generator()):
        _issue(client)
    response = client.post('/api/quiz-submit', data='{"quiz_token": "\\ud800", "responses": []}',
                           content_type='application/json')
    assert response.status_code == 400


def test_the_fallback_bank_serves_unseen_questions_before_seen_ones():
    # A topic's authored bank is small, so a check quiz drawn from it used to
    # come back as the first questions of the bank, seen or not.
    bank = [{"id": i, "text": f"B{i}?"} for i in range(1, 13)]
    seen = [f"B{i}?" for i in range(1, 10)]
    picked = app_module.quiz_gen._unseen_first(bank, 7, seen)
    texts = [q["text"] for q in picked]
    assert texts[:3] == ["B10?", "B11?", "B12?"]
    assert len(texts) == 7 and len(set(texts)) == 7
