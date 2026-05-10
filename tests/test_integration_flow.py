"""
Integration Tests: Full User Learning Flow
Covers: Registration -> Video Tracking -> Quiz Generation -> Submission -> Review
"""
import pytest
from unittest.mock import patch


class TestFullLearningFlow:
    def _register_and_login(self, client, email="integration@test.com", name="Int User"):
        client.post('/register', json={"name": name, "email": email, "password": "password123"})
        client.post('/login', json={"email": email, "password": "password123"})

    def test_full_flow_register_to_quiz_submit(self, client):
        self._register_and_login(client)
        res = client.get('/dashboard')
        assert res.status_code == 200

        with patch('backend.quiz.quiz_generator.quiz_gen.generate_quiz') as mock_gen:
            mock_gen.return_value = {
                "difficulty": "medium",
                "questions": [{"id": 1, "text": "Q?", "options": ["A","B","C","D"], "answer": "A", "hint": "h"}],
                "num_questions": 1
            }
            quiz_res = client.get('/api/quiz-data/test_topic')
        assert quiz_res.status_code == 200
        assert quiz_res.json["success"] is True

        with client.session_transaction() as sess:
            sess['current_quiz'] = {"questions": [{"id": 1, "text": "Q?", "answer": "A"}], "difficulty": "medium"}

        with patch('backend.quiz.quiz_evaluator.evaluator.evaluate') as mock_eval:
            mock_eval.return_value = {
                "score": 100, "avg_time": 10, "total_time": 10,
                "question_results": [{"question_id": 1, "is_correct": True, "feedback": "Correct!"}]
            }
            sub_res = client.post('/api/quiz-submit', json={
                "topic_id": "os",
                "responses": [{"question_id": 1, "selected_answer": "A", "time_taken": 10}],
                "difficulty": "medium"
            })

        assert sub_res.status_code == 200
        data = sub_res.json
        assert data["success"] is True
        assert data["score"] == 100
        assert "mastery" in data
        assert "recommendation" in data

    def test_video_tracking_persists(self, client):
        self._register_and_login(client, email="video_test@test.com")
        res = client.post('/api/video-track', json={
            "topic_id": "test_topic", "pause_count": 3, "rewatch_count": 1,
            "skip_ratio": 0.0, "watch_percentage": 65, "last_time": 200,
            "total_duration": 500, "max_reached": 200
        })
        assert res.status_code == 200
        assert res.json["success"] is True

    def test_quiz_review_list_after_attempt(self, client):
        self._register_and_login(client, email="review_test@test.com")
        with client.session_transaction() as sess:
            sess['current_quiz'] = {"questions": [{"id": 1, "text": "Q?", "answer": "A"}], "difficulty": "easy"}
        with patch('backend.quiz.quiz_evaluator.evaluator.evaluate') as mock_eval:
            mock_eval.return_value = {"score": 60, "avg_time": 15, "total_time": 15,
                "question_results": [{"question_id": 1, "is_correct": False, "feedback": "Wrong"}]}
            client.post('/api/quiz-submit', json={
                "topic_id": "test_topic",
                "responses": [{"question_id": 1, "selected_answer": "B", "time_taken": 15}],
                "difficulty": "easy"
            })
        review_res = client.get('/quiz-review')
        assert review_res.status_code == 200

    def test_progress_page_accessible(self, client):
        self._register_and_login(client, email="progress_test@test.com")
        res = client.get('/progress')
        assert res.status_code == 200

    def test_video_page_accessible(self, client):
        self._register_and_login(client, email="video_page@test.com")
        res = client.get('/video/test_topic')
        assert res.status_code == 200


class TestSecurityIntegration:
    PROTECTED_ROUTES = ['/dashboard', '/progress', '/quiz-review', '/video/test_topic', '/quiz/test_topic']

    def test_all_protected_routes_redirect_when_logged_out(self, client):
        client.get('/logout')
        for route in self.PROTECTED_ROUTES:
            res = client.get(route, follow_redirects=False)
            assert res.status_code in (302, 401), \
                f"Route {route} should redirect unauthenticated users, got {res.status_code}"

    def test_login_with_wrong_password_fails(self, client):
        client.post('/register', json={"name": "Alice", "email": "alice_sec@test.com", "password": "correct"})
        client.get('/logout')
        res = client.post('/login', json={"email": "alice_sec@test.com", "password": "wrong"})
        assert res.json["success"] is False

    def test_login_with_nonexistent_user_fails(self, client):
        res = client.post('/login', json={"email": "ghost@test.com", "password": "pass"})
        assert res.json["success"] is False

    def test_register_duplicate_email_fails(self, client):
        client.post('/register', json={"name": "A", "email": "dup_sec@test.com", "password": "p"})
        res = client.post('/register', json={"name": "B", "email": "dup_sec@test.com", "password": "p"})
        assert res.json["success"] is False
