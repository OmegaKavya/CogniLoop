"""Regressions for the round 9 audit's confirmed findings on the submit path.

Each test fails on the code as it was before the fix:
- H-01 registration left the cohort out of the session, so a control
  participant was adapted as experimental until they next signed in;
- H-02 `consume` checked and removed a token under separate locks;
- H-03 duplicate responses inflated a score past 100%, and `time_taken` was
  taken as sent;
- M-01 the token was spent before grading, so a failed submission lost it;
- M-03 model-written links reached an href unchecked;
- M-04 a deleted participant's cookie kept working.
"""
import json
import threading
import uuid
from unittest.mock import patch

from app import app, user_repo, quiz_repo
from backend.quiz.quiz_evaluator import normalise_responses
from backend.quiz.quiz_insights import safe_link
from backend.quiz.quiz_session import ActiveQuizStore, active_quiz_store
from helpers import set_study_group


def _quiz(n=10, seconds=10):
    return {
        "topic_id": "test_topic",
        "difficulty": "medium",
        "question_time_seconds": seconds,
        "questions": [{"id": i, "text": f"Q{i}?", "options": ["A", "B", "C", "D"],
                       "answer": "B", "hint": "h"} for i in range(1, n + 1)],
    }


def _register(client):
    email = f"submit-{uuid.uuid4().hex[:10]}@test.com"
    client.post('/register', json={"name": "S", "email": email, "password": "pw"})
    with client.session_transaction() as sess:
        return sess['user_id']


def _submit(client, token, responses):
    return client.post('/api/quiz-submit', json={
        "topic_id": "test_topic", "quiz_token": token, "responses": responses})


class TestCohortComesFromTheStoredUser:
    def test_a_control_registrant_is_served_the_control_path_at_once(self, client):
        # No sign-in after registering: this is exactly what a Track A
        # participant does, and the path on which the cohort was dropped.
        user_id = _register(client)
        set_study_group(user_id, 'control')
        token = active_quiz_store.issue(user_id, _quiz(n=2))
        body = json.loads(_submit(client, token, [
            {"question_id": 1, "selected_answer": "B", "time_taken": 5}]).data)
        assert body['success']
        assert body['recommendation'] == "Continue reviewing the material sequentially."

    def test_registration_records_the_assigned_cohort_in_the_session(self, client):
        user_id = _register(client)
        stored = user_repo.find_by_id(user_id)['study_group']
        with client.session_transaction() as sess:
            assert sess['study_group'] == stored

    def test_a_tampered_session_cohort_is_overwritten(self, client):
        user_id = _register(client)
        set_study_group(user_id, 'control')
        with client.session_transaction() as sess:
            sess['study_group'] = 'experimental'
        client.get('/dashboard')
        with client.session_transaction() as sess:
            assert sess['study_group'] == 'control'


class TestDuplicateAndOutOfRangeResponses:
    def test_repeating_one_correct_answer_does_not_raise_the_score(self, client):
        user_id = _register(client)
        token = active_quiz_store.issue(user_id, _quiz(n=10))
        flood = [{"question_id": 1, "selected_answer": "B", "time_taken": -500}] * 50
        body = json.loads(_submit(client, token, flood).data)
        assert body['success']
        assert body['score'] == 10.0, "one correct answer out of ten is 10%"

    def test_times_are_clamped_to_the_question_budget(self):
        quiz = _quiz(n=3, seconds=10)
        cleaned = normalise_responses(quiz, [
            {"question_id": 1, "selected_answer": "B", "time_taken": -500},
            {"question_id": 2, "selected_answer": "B", "time_taken": 1e9},
            {"question_id": 3, "selected_answer": "B", "time_taken": "nan"},
        ])
        assert [r["time_taken"] for r in cleaned] == [0.0, 10.0, 10.0]

    def test_malformed_entries_and_unknown_questions_are_dropped(self):
        cleaned = normalise_responses(_quiz(n=2), [
            "not a dict", {"question_id": 99, "selected_answer": "B"},
            {"question_id": 1, "selected_answer": {"$ne": 1}, "time_taken": 3},
        ])
        assert len(cleaned) == 1
        assert cleaned[0]["selected_answer"] is None

    def test_an_honest_submission_is_left_alone(self):
        honest = [{"question_id": 1, "selected_answer": "B", "time_taken": 4.2,
                   "used_hint": True}]
        cleaned = normalise_responses(_quiz(n=1, seconds=10), honest)
        assert cleaned[0]["time_taken"] == 4.2
        assert cleaned[0]["selected_answer"] == "B"
        assert cleaned[0]["used_hint"] is True
        assert normalise_responses(_quiz(n=1, seconds=10), cleaned) == cleaned


class TestTokenIsSpentExactlyOnce:
    def test_concurrent_consumers_get_the_quiz_once(self, tmp_path):
        store = ActiveQuizStore(file_path=str(tmp_path / "active.json"))
        token = store.issue("u1", _quiz(n=1))
        results, start = [], threading.Barrier(8)

        def take():
            start.wait()
            results.append(store.consume(token, "u1"))

        threads = [threading.Thread(target=take) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(r is not None for r in results) == 1

    def test_a_failed_submission_leaves_the_token_usable(self, client):
        user_id = _register(client)
        token = active_quiz_store.issue(user_id, _quiz(n=2))
        answer = [{"question_id": 1, "selected_answer": "B", "time_taken": 5}]
        with patch('app.evaluator.evaluate', return_value=None):
            assert _submit(client, token, answer).status_code == 500
        # Pressing Submit again must work rather than report an expired quiz.
        retry = _submit(client, token, answer)
        assert retry.status_code == 200 and json.loads(retry.data)['success']
        assert _submit(client, token, answer).status_code == 400

    def test_a_non_json_body_is_a_400_not_a_500(self, client):
        _register(client)
        res = client.post('/api/quiz-submit', data="x",
                          content_type='text/plain')
        assert res.status_code == 400


class TestModelLinksAreChecked:
    def test_only_https_and_site_paths_survive(self):
        assert safe_link("https://example.org/a") == "https://example.org/a"
        assert safe_link("/video/qa#study-notes") == "/video/qa#study-notes"
        for bad in ("javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,x",
                    "http://example.org", "//evil.example", "/\\evil.example",
                    "https://", None, 5, {"url": "x"}):
            assert safe_link(bad) is None, bad

    def test_review_page_drops_a_stored_javascript_link(self, client):
        user_id = _register(client)
        attempt_id = f"{user_id}-xsscheck01"
        quiz_repo.add_attempt({
            "attempt_id": attempt_id, "user_id": user_id, "topic_id": "test_topic",
            "topic_name": "T", "timestamp": "2026-11-26T00:00:00", "score": 0,
            "mastery": 0.3, "avg_time": 9.5, "total_time": 9.5,
            "adaptation": {"speed_label": "Steady", "new_difficulty": "medium"},
            "behavior_cluster": "General Learner", "recommendation": "r",
            "quiz_meta": {"difficulty": "medium", "num_questions": 1,
                          "timer_seconds": 10, "hint_unlock_seconds": 5},
            "question_results": [{"id": "1", "text": "Q", "is_correct": False,
                                  "time_taken": 9.5, "selected_answer": "A",
                                  "correct_answer": "B"}],
            "ai_insights": {"summary": "s", "focus_concepts": ["c"], "cheat_sheet": [],
                            "resources": [{"title": "bad", "url": "javascript:alert(1)"},
                                          {"title": "good", "url": "https://example.org/"}]},
        })
        html = client.get(f'/quiz-review/{attempt_id}').data.decode()
        assert "javascript:alert" not in html
        assert 'href="https://example.org/"' in html
        # 9.5s of a 10s budget, wrong: the server's thresholds say confused,
        # which the template's old fixed "> 25s" rule could never show.
        assert 'data-result="confused"' in html


class TestDeletedAccountsLoseTheirSession:
    def test_a_session_for_a_removed_user_is_cleared(self, client):
        user_id = _register(client)
        user_repo._store.update_replacing(
            lambda users: [u for u in users if str(u.get("id")) != str(user_id)],
            default=list)
        res = client.post('/api/quiz-submit', json={"quiz_token": "x", "responses": []})
        assert res.status_code == 401
        with client.session_transaction() as sess:
            assert 'user_id' not in sess


class TestUnreadableStorage:
    def test_a_byte_order_mark_is_not_corruption(self, tmp_path):
        from backend.storage import open_store
        path = tmp_path / "doc.json"
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps([{"a": 1}]).encode())
        assert open_store(str(path), default=list).read() == [{"a": 1}]

    def test_a_corrupt_document_is_a_json_503_for_the_api(self, client):
        from backend.storage import StorageCorrupted
        _register(client)
        with patch('app.active_quiz_store.get',
                   side_effect=StorageCorrupted("damaged")):
            res = client.post('/api/quiz-submit', json={"quiz_token": "t",
                                                         "responses": []})
        assert res.status_code == 503
        assert res.get_json()['success'] is False


class TestRefinedInsightsEndpoint:
    def _attempt(self, client):
        user_id = _register(client)
        token = active_quiz_store.issue(user_id, _quiz(n=2))
        with patch('app.refine_insights_in_background'):
            body = json.loads(_submit(client, token, [
                {"question_id": 1, "selected_answer": "A", "time_taken": 5}]).data)
        return user_id, body['attempt_id']

    def test_reports_unrefined_then_refined(self, client):
        user_id, attempt_id = self._attempt(client)
        first = client.get(f'/api/attempt-insights/{attempt_id}').get_json()
        assert first['success'] and first['refined'] is False

        quiz_repo.set_insights(user_id, attempt_id, {
            "summary": "model text", "focus_concepts": ["x"], "cheat_sheet": [],
            "resources": [], "source": "model"})
        second = client.get(f'/api/attempt-insights/{attempt_id}').get_json()
        assert second['refined'] is True
        assert second['ai_insights']['summary'] == "model text"

    def test_another_learners_attempt_is_not_found(self, client):
        _, attempt_id = self._attempt(client)
        client.get('/logout')
        _register(client)
        assert client.get(f'/api/attempt-insights/{attempt_id}').status_code == 404

    def test_requires_a_session(self, client):
        assert client.get('/api/attempt-insights/whatever').status_code == 401

    def test_model_insights_are_marked_as_such(self):
        from backend.quiz.quiz_insights import QuizInsightsEngine
        engine = QuizInsightsEngine()
        with patch.object(engine, '_model_attempt', return_value={
                "summary": "s", "focus_concepts": ["c"], "cheat_sheet": [], "resources": []}):
            out = engine.model_insights("T", 50, 0.5, [{"is_correct": False, "time_taken": 3}])
        assert out['source'] == 'model'
